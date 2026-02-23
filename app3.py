import base64
import io
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict

import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# =========================
# Fixed page + grid
# =========================

@dataclass(frozen=True)
class PageSpec:
    """কেন: পেজ সাইজ ফিক্স রাখলে প্রিন্ট স্কেলিং/মিসম্যাচ কম হয়"""
    page_w_mm: float = 95.0
    page_h_mm: float = 150.0


@dataclass(frozen=True)
class GridSpec:
    """কেন: 9×3 গ্রিড ফিক্সড; cell 10mm×50mm"""
    cols: int = 9
    rows: int = 3
    col_w_mm: float = 10.0
    row_h_mm: float = 50.0


# =========================
# Persistence files
# =========================

FONTS_DIR = "fonts"
LIB_FILE = "library.json"         # letter/symbol save
FONTS_FILE = "fonts_registry.json"  # font registry save (user-added fonts)


# =========================
# Default font registry (built-in)
# =========================
# কেন: streamlit cloud-এ download fail হতে পারে, তাই local path first।
# online_url থাকলে toggle ON করে ডাউনলোড fallback হবে।
#
# Siyam Rupali এর raw file path GitHub repo-তে আছে (Siyamrupali_1_070ship.ttf) :contentReference[oaicite:4]{index=4}

class FontItem(TypedDict):
    id: str
    label: str
    kind: str  # "bengali" | "symbol"
    local_path: str
    online_url: str


DEFAULT_FONTS: List[FontItem] = [
    {
        "id": "siyam_rupali",
        "label": "Siyam Rupali (Bengali) ✅ recommended",
        "kind": "bengali",
        "local_path": os.path.join(FONTS_DIR, "Siyamrupali_1_070ship.ttf"),
        "online_url": "https://github.com/potasiyam/Siyam-Rupali/raw/master/Siyamrupali_1_070ship.ttf",
    },
    {
        "id": "noto_sans_bengali",
        "label": "Noto Sans Bengali (Bengali)",
        "kind": "bengali",
        "local_path": os.path.join(FONTS_DIR, "NotoSansBengali-Regular.ttf"),
        "online_url": "https://github.com/google/fonts/raw/main/ofl/notosansbengali/NotoSansBengali-Regular.ttf",
    },
    {
        "id": "noto_symbols2",
        "label": "Noto Sans Symbols 2 (Symbols)",
        "kind": "symbol",
        "local_path": os.path.join(FONTS_DIR, "NotoSansSymbols2-Regular.ttf"),
        "online_url": "https://github.com/google/fonts/raw/main/ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf",
    },
    {
        "id": "dejavu_sans",
        "label": "DejaVu Sans (Fallback symbols/latin)",
        "kind": "symbol",
        "local_path": "",   # system font, no ttf needed
        "online_url": "",
    },
]


# =========================
# Helpers: storage
# =========================

def ensure_dir(path: str) -> None:
    """কেন: fonts/ ফোল্ডার না থাকলে save/download ব্যর্থ হবে"""
    os.makedirs(path, exist_ok=True)


def load_json_file(path: str, default):
    """কেন: corrupt json হলে fallback default"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data) -> None:
    """কেন: persist state (letters/symbols/fonts) রাখতে"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_library() -> List[str]:
    """কেন: user-এর letters/symbols dropdown এ দেখাতে"""
    data = load_json_file(LIB_FILE, [])
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return []


def save_library(items: List[str]) -> None:
    """কেন: letters/symbols persist রাখতে"""
    save_json_file(LIB_FILE, items)


def load_fonts_registry() -> List[FontItem]:
    """কেন: user-add করা fonts মনে রাখতে"""
    data = load_json_file(FONTS_FILE, [])
    if isinstance(data, list):
        # very light validation
        out: List[FontItem] = []
        for x in data:
            if isinstance(x, dict) and "id" in x and "label" in x and "kind" in x:
                out.append(x)  # type: ignore
        return out
    return []


def save_fonts_registry(items: List[FontItem]) -> None:
    """কেন: user-add fonts persist রাখতে"""
    save_json_file(FONTS_FILE, items)


def merge_fonts(defaults: List[FontItem], user_fonts: List[FontItem]) -> List[FontItem]:
    """কেন: default + user fonts একসাথে UI তে দেখাতে (id conflict হলে user override)"""
    by_id: Dict[str, FontItem] = {f["id"]: f for f in defaults}
    for f in user_fonts:
        by_id[f["id"]] = f
    return list(by_id.values())


# =========================
# Font download + register
# =========================

def download_file(url: str, dest_path: str) -> bool:
    """কেন: Cloud এ local font missing হলে online থেকে এনে black-box ঠিক করতে"""
    try:
        ensure_dir(os.path.dirname(dest_path) or ".")
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception:
        return False


@st.cache_resource
def register_font_alias(alias: str, ttf_path: str) -> bool:
    """
    কেন: ReportLab-এ TTF register না করলে Unicode glyph আসবে না
    cache_resource দিলে re-run এ বারবার register করবে না
    """
    try:
        pdfmetrics.registerFont(TTFont(alias, ttf_path))
        return True
    except Exception:
        return False


def contains_bengali(text: str) -> bool:
    """কেন: auto mode-এ বাংলা detect করে Bengali font বাছাই"""
    return bool(re.search(r"[\u0980-\u09FF]", text))


def compute_font_size(base_size: int, text: str, symbol_scale: float) -> int:
    """কেন: ডাবল-লেটার/দুই ক্যারেক্টার হলে সাইজ কমালে overflow কম হয়"""
    if len(text.strip()) > 1:
        return max(6, int(round(base_size * symbol_scale)))
    return base_size


def render_pdf_preview(pdf_bytes: bytes, height_px: int) -> None:
    """কেন: PDF embed preview দিয়ে ডাউনলোডের আগে যাচাই"""
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <iframe
        src="data:application/pdf;base64,{b64}"
        width="100%"
        height="{height_px}"
        style="border: 1px solid #ddd; border-radius: 8px;"
        type="application/pdf">
    </iframe>
    """
    st.markdown(html, unsafe_allow_html=True)


# =========================
# PDF generator
# =========================

def generate_pdf_pages(
    text_value: str,
    pages: int,
    page: PageSpec,
    grid: GridSpec,
    left_margin_mm: float,
    top_margin_mm: float,
    col_gap_mm: float,
    row_gap_mm: float,
    repeat_per_cell: int,
    base_font_size: int,
    symbol_scale: float,
    draw_cell_boxes: bool,
    stroke_width_pt: float,
    chosen_font_name: str,
) -> bytes:
    """
    কেন: multi-page PDF হবে।
    letter/symbol এর চারপাশে আলাদা border নেই।
    শুধু row/column cell border থাকবে।
    """
    text_value = text_value.strip()
    if not text_value:
        raise ValueError("টেক্সট খালি রাখা যাবে না।")
    if pages < 1:
        raise ValueError("Pages কমপক্ষে 1 হতে হবে।")

    page_w = page.page_w_mm * mm
    page_h = page.page_h_mm * mm
    col_w = grid.col_w_mm * mm
    row_h = grid.row_h_mm * mm

    left_margin = left_margin_mm * mm
    top_margin = top_margin_mm * mm
    col_gap = col_gap_mm * mm
    row_gap = row_gap_mm * mm

    grid_total_w = (grid.cols * col_w) + ((grid.cols - 1) * col_gap)
    grid_total_h = (grid.rows * row_h) + ((grid.rows - 1) * row_gap)

    if left_margin + grid_total_w > page_w + 0.001:
        raise ValueError("Grid width পেজের বাইরে যাচ্ছে। Left margin/Column gap কমান।")
    if top_margin + grid_total_h > page_h + 0.001:
        raise ValueError("Grid height পেজের বাইরে যাচ্ছে। Top margin/Row gap কমান।")

    font_size = compute_font_size(base_font_size, text_value, symbol_scale)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle("95x150mm - 9x3 - multipage")

    c.setLineWidth(stroke_width_pt)

    x0 = left_margin
    y_top = page_h - top_margin

    for _ in range(pages):
        c.setFont(chosen_font_name, font_size)

        for r in range(grid.rows):
            for col in range(grid.cols):
                x = x0 + col * (col_w + col_gap)
                y = y_top - (r + 1) * row_h - r * row_gap

                if draw_cell_boxes:
                    c.rect(x, y, col_w, row_h)

                padding_y = max(2.0 * mm, 0.08 * row_h)
                usable_h = max(1.0, row_h - 2 * padding_y)

                for i in range(repeat_per_cell):
                    frac = 0.5 if repeat_per_cell == 1 else i / (repeat_per_cell - 1)
                    ty = y + row_h - padding_y - (usable_h * frac)
                    tx = x + (col_w / 2.0)

                    c.drawCentredString(tx, ty - (font_size * 0.35), text_value)

        c.showPage()

    c.save()
    return buf.getvalue()


# =========================
# UI
# =========================

st.set_page_config(page_title="95×150mm (Bangla+Symbols) Multi-font", layout="centered")
st.title("95mm × 150mm | 9×3 গ্রিড | বাংলা + সিম্বল | Multi-font + Multi-page")

st.markdown(
    """
### ✅ Cloud Hosting টিপ
- সবচেয়ে reliable: `fonts/` ফোল্ডারে TTF ফাইলগুলো **repo-তে commit** করে deploy দিন।
- Online link fallback দরকার হলে sidebar থেকে **Allow online download** ON করুন।
"""
)

ensure_dir(FONTS_DIR)

# Load persisted fonts + merge defaults
user_fonts = load_fonts_registry()
fonts_all = merge_fonts(DEFAULT_FONTS, user_fonts)

bengali_fonts = [f for f in fonts_all if f["kind"] == "bengali"]
symbol_fonts = [f for f in fonts_all if f["kind"] == "symbol"]

# Remember letters/symbols
if "library" not in st.session_state:
    st.session_state["library"] = load_library()

library: List[str] = st.session_state["library"]

with st.sidebar:
    st.header("Font download")
    allow_online_download = st.toggle("Allow online download (Cloud fallback)", value=False)
    st.caption("OFF থাকলে শুধু `fonts/` লোকাল ফাইল ব্যবহার হবে।")

    st.header("Font selection")
    bengali_choice = st.selectbox(
        "বাংলা ফন্ট বাছাই করুন",
        options=bengali_fonts,
        format_func=lambda x: x["label"],
        index=0,
    )
    symbol_choice = st.selectbox(
        "সিম্বল ফন্ট বাছাই করুন",
        options=symbol_fonts,
        format_func=lambda x: x["label"],
        index=0,
    )

    font_mode = st.radio(
        "Font mode",
        options=["Auto (বাংলা হলে Bengali, নইলে Symbols)", "Force Bengali font", "Force Symbols font"],
        index=0,
    )

    st.divider()
    st.header("Add new font (remembered)")
    st.caption("আপনি চাইলে নতুন ফন্ট আপলোড বা URL দিয়ে যোগ করতে পারবেন।")

    add_kind = st.selectbox("Font type", options=["bengali", "symbol"])
    add_label = st.text_input("Font label", value="")
    add_id = st.text_input("Font id (unique)", value="")
    add_url = st.text_input("Online .ttf URL (optional)", value="")
    uploaded = st.file_uploader("Upload .ttf (optional)", type=["ttf"])

    if st.button("➕ Add font to registry"):
        if not add_id.strip() or not add_label.strip():
            st.error("Font id এবং label লাগবে।")
        else:
            local_path = ""
            if uploaded is not None:
                # কেন: আপলোড করা ফন্ট Cloud-এও কাজ করবে (কারণ file app storage এ থাকবে)
                local_path = os.path.join(FONTS_DIR, f"{add_id.strip()}.ttf")
                with open(local_path, "wb") as f:
                    f.write(uploaded.getbuffer())

            new_font: FontItem = {
                "id": add_id.strip(),
                "label": add_label.strip(),
                "kind": add_kind,
                "local_path": local_path,
                "online_url": add_url.strip(),
            }

            updated_user_fonts = user_fonts + [new_font]
            save_fonts_registry(updated_user_fonts)
            st.success("ফন্ট যোগ হয়েছে। Reload হচ্ছে…")
            st.rerun()

    st.divider()
    st.header("Pages & layout")
    pages = st.number_input("Pages", min_value=1, max_value=500, value=1, step=1)

    left_margin_mm = st.number_input("Left Margin (mm)", min_value=0.0, max_value=30.0, value=2.5, step=0.5)
    top_margin_mm = st.number_input("Top Margin (mm)", min_value=0.0, max_value=30.0, value=0.0, step=0.5)
    col_gap_mm = st.number_input("Column Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)
    row_gap_mm = st.number_input("Row Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)

    repeat_per_cell = st.number_input("Repeat per cell", min_value=1, max_value=20, value=4, step=1)
    base_font_size = st.slider("Base font size", min_value=6, max_value=80, value=18, step=1)
    symbol_scale = st.slider("If double-letter, scale", min_value=0.3, max_value=1.0, value=0.75, step=0.05)

    draw_cell_boxes = st.toggle("Draw row/column cell border", value=True)
    stroke_width_pt = st.slider("Border thickness (pt)", min_value=0.1, max_value=3.0, value=0.7, step=0.1)

    st.header("Preview")
    show_preview = st.toggle("Show PDF preview", value=True)
    preview_height = st.slider("Preview height (px)", min_value=400, max_value=1100, value=700, step=50)


# Letters/symbols library UI
st.subheader("📚 Saved Letter / Symbol list (Remembered)")
col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    selected_item = st.selectbox(
        "লিস্ট থেকে বাছাই করুন",
        options=(library if library else ["(লিস্ট খালি)"]),
        disabled=(len(library) == 0),
    )

with col2:
    new_item = st.text_input("নতুন Letter/Symbol যোগ করুন", value="")

with col3:
    if st.button("➕ Add"):
        v = new_item.strip()
        if v and v not in library:
            library = library + [v]
            st.session_state["library"] = library
            save_library(library)
        st.rerun()

if len(library) > 0:
    if st.button("🗑️ Delete selected"):
        library = [x for x in library if x != selected_item]
        st.session_state["library"] = library
        save_library(library)
        st.rerun()

st.subheader("✍️ Print text")
text_value = st.text_input(
    "টেক্সট লিখুন (বাংলা/ডাবল-লেটার/সিম্বল হতে পারে)",
    value=(selected_item if len(library) > 0 else ""),
)

# Decide which font should be used for the current text
def prepare_font(font_item: FontItem, alias: str) -> str:
    """
    কেন: local font থাকলে সেটাই; না থাকলে allow_online_download হলে download।
    শেষে ReportLab alias register করে return।
    """
    if font_item["id"] == "dejavu_sans":
        return "Helvetica"  # সহজ fallback (ReportLab built-in)

    local_path = font_item.get("local_path", "").strip()

    # local_path empty হলে, id based default name বানিয়ে রাখি
    if not local_path:
        local_path = os.path.join(FONTS_DIR, f"{font_item['id']}.ttf")

    if not os.path.exists(local_path):
        if allow_online_download and font_item.get("online_url", "").strip():
            ok = download_file(font_item["online_url"], local_path)
            if not ok:
                # download fail হলে fallback
                return "Helvetica"
        else:
            return "Helvetica"

    # register alias -> local_path
    if register_font_alias(alias, local_path):
        return alias
    return "Helvetica"


# Font selection resolution
bengali_font_name = prepare_font(bengali_choice, alias="BENGALI_SELECTED")
symbol_font_name = prepare_font(symbol_choice, alias="SYMBOLS_SELECTED")

# Auto detect for current text
auto_is_bengali = contains_bengali(text_value)
if font_mode.startswith("Auto"):
    chosen_font_name = bengali_font_name if auto_is_bengali else symbol_font_name
elif font_mode.startswith("Force Bengali"):
    chosen_font_name = bengali_font_name
else:
    chosen_font_name = symbol_font_name

# Status
st.caption(
    f"Selected font used now: **{chosen_font_name}** | "
    f"Auto-detected Bengali: **{auto_is_bengali}**"
)

page = PageSpec()
grid = GridSpec()

# Generate
if st.button("✅ Generate PDF", type="primary"):
    try:
        pdf_bytes = generate_pdf_pages(
            text_value=text_value,
            pages=int(pages),
            page=page,
            grid=grid,
            left_margin_mm=float(left_margin_mm),
            top_margin_mm=float(top_margin_mm),
            col_gap_mm=float(col_gap_mm),
            row_gap_mm=float(row_gap_mm),
            repeat_per_cell=int(repeat_per_cell),
            base_font_size=int(base_font_size),
            symbol_scale=float(symbol_scale),
            draw_cell_boxes=bool(draw_cell_boxes),
            stroke_width_pt=float(stroke_width_pt),
            chosen_font_name=chosen_font_name,
        )
        st.session_state["pdf_bytes"] = pdf_bytes
        st.success("PDF তৈরি হয়েছে ✅")
    except Exception as e:
        st.error(f"সমস্যা: {e}")

# Preview + Download
pdf_data = st.session_state.get("pdf_bytes")
if isinstance(pdf_data, (bytes, bytearray)) and len(pdf_data) > 0:
    if show_preview:
        st.subheader("👀 PDF Preview")
        render_pdf_preview(pdf_data, height_px=int(preview_height))

    st.download_button(
        label="⬇️ Download PDF",
        data=pdf_data,
        file_name=f"labels_95x150_9x3_pages{int(pages)}.pdf",
        mime="application/pdf",
    )