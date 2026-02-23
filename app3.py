# app.py
import base64
import io
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, List

import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# -------------------- Fixed specs --------------------

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


# -------------------- Font management --------------------

FONTS_DIR = "fonts"
BENGALI_TTF_PATH = os.path.join(FONTS_DIR, "Siyam Rupali Regular.ttf")
SYMBOLS_TTF_PATH = os.path.join(FONTS_DIR, "Siyam Rupali Regular.ttf")

BENGALI_TTF_URL = "https://github.com/potasiyam/Siyam-Rupali/raw/master/Siyamrupali_1_070ship.ttf"
SYMBOLS_TTF_URL = "https://github.com/potasiyam/Siyam-Rupali/raw/master/Siyamrupali_1_070ship.ttf"


def ensure_dir(path: str) -> None:
    """কেন: fonts/ ফোল্ডার নিশ্চিত না হলে ডাউনলোড/লোড ব্যর্থ হতে পারে"""
    os.makedirs(path, exist_ok=True)


def download_file(url: str, dest_path: str) -> bool:
    """কেন: ফ্রি Bengali/Symbols ফন্ট না থাকলে অটো ডাউনলোড করে black-box সমস্যা কমানো"""
    try:
        ensure_dir(os.path.dirname(dest_path))
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception:
        return False


def ensure_font_file(ttf_path: str, url: str) -> bool:
    """কেন: ফন্ট লোকালে না থাকলে ডাউনলোড চেষ্টা"""
    if os.path.exists(ttf_path):
        return True
    return download_file(url, ttf_path)


def register_ttf_font(alias: str, ttf_path: str) -> bool:
    """কেন: ReportLab-এ TTF register না করলে Unicode glyph render হবে না"""
    if not os.path.exists(ttf_path):
        return False
    try:
        pdfmetrics.registerFont(TTFont(alias, ttf_path))
        return True
    except Exception:
        return False


def contains_bengali(text: str) -> bool:
    """কেন: বাংলা detect করে Bengali font ব্যবহার করবো"""
    return bool(re.search(r"[\u0980-\u09FF]", text))


def choose_font_alias(text: str) -> str:
    """কেন: বাংলা হলে Bengali font, অন্যথায় Symbols font"""
    return "BENGALI" if contains_bengali(text) else "SYMBOLS"


def compute_font_size(base_size: int, text: str, symbol_scale: float) -> int:
    """কেন: ডাবল-লেটার/দুই ক্যারেক্টার হলে সাইজ কমালে overflow কম হয়"""
    if len(text.strip()) > 1:
        return max(6, int(round(base_size * symbol_scale)))
    return base_size


# -------------------- Persistent library --------------------

LIB_FILE = "library.json"


def load_library() -> List[str]:
    """কেন: আগের saved letter/symbol UI তে দেখানোর জন্য"""
    if not os.path.exists(LIB_FILE):
        return []
    try:
        with open(LIB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        return []
    except Exception:
        return []


def save_library(items: List[str]) -> None:
    """কেন: লেটার/সিম্বল persist করে রাখা"""
    with open(LIB_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_to_library(items: List[str], new_item: str) -> List[str]:
    """কেন: ডুপ্লিকেট এড়ানো"""
    v = new_item.strip()
    if not v:
        return items
    if v in items:
        return items
    return items + [v]


def remove_from_library(items: List[str], item: str) -> List[str]:
    """কেন: ইউজার যেটা ডিলিট করবে সেটা বাদ"""
    return [x for x in items if x != item]


# -------------------- PDF preview --------------------

def render_pdf_preview(pdf_bytes: bytes, height_px: int) -> None:
    """কেন: PDF embed preview দিয়ে ডাউনলোডের আগে যাচাই করা যায়"""
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


# -------------------- PDF generation --------------------

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
    font_map: Dict[str, str],
) -> bytes:
    """
    কেন: pages অনুযায়ী multi-page PDF হবে।
    letter-এর চারপাশে ছোট border নেই।
    শুধু প্রতিটা cell (column/row) border থাকবে।
    """
    text_value = text_value.strip()
    if not text_value:
        raise ValueError("টেক্সট খালি রাখা যাবে না।")
    if pages < 1:
        raise ValueError("Pages কমপক্ষে 1 হতে হবে।")

    # Convert
    page_w = page.page_w_mm * mm
    page_h = page.page_h_mm * mm
    col_w = grid.col_w_mm * mm
    row_h = grid.row_h_mm * mm

    left_margin = left_margin_mm * mm
    top_margin = top_margin_mm * mm
    col_gap = col_gap_mm * mm
    row_gap = row_gap_mm * mm

    # Grid total size (gap সহ)
    grid_total_w = (grid.cols * col_w) + ((grid.cols - 1) * col_gap)
    grid_total_h = (grid.rows * row_h) + ((grid.rows - 1) * row_gap)

    # কেন: গ্রিড পেজের বাইরে গেলে প্রিন্টার scale করতে পারে
    if left_margin + grid_total_w > page_w + 0.001:
        raise ValueError("Grid width পেজের বাইরে যাচ্ছে। Left margin/Column gap কমান।")
    if top_margin + grid_total_h > page_h + 0.001:
        raise ValueError("Grid height পেজের বাইরে যাচ্ছে। Top margin/Row gap কমান।")

    # Font choose
    family = choose_font_alias(text_value)  # BENGALI / SYMBOLS
    font_name = font_map.get(family, "Helvetica")

    # Font size adjust (double-letter)
    font_size = compute_font_size(base_font_size, text_value, symbol_scale)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle("95x150mm - 9x3 - multipage")

    # Line width for cell borders
    c.setLineWidth(stroke_width_pt)

    x0 = left_margin
    y_top = page_h - top_margin

    for _ in range(pages):
        c.setFont(font_name, font_size)

        for r in range(grid.rows):
            for col in range(grid.cols):
                x = x0 + col * (col_w + col_gap)
                y = y_top - (r + 1) * row_h - r * row_gap

                # ✅ শুধু cell border থাকবে (আপনার requirement)
                if draw_cell_boxes:
                    c.rect(x, y, col_w, row_h)

                # vertical repeat inside the cell
                padding_y = max(2.0 * mm, 0.08 * row_h)
                usable_h = max(1.0, row_h - 2 * padding_y)

                for i in range(repeat_per_cell):
                    frac = 0.5 if repeat_per_cell == 1 else i / (repeat_per_cell - 1)
                    ty = y + row_h - padding_y - (usable_h * frac)
                    tx = x + (col_w / 2.0)

                    # baseline adjust
                    c.drawCentredString(tx, ty - (font_size * 0.35), text_value)

        c.showPage()

    c.save()
    return buf.getvalue()


# -------------------- Streamlit UI --------------------

st.set_page_config(page_title="95×150mm Multi-page (Bangla+Symbol)", layout="centered")
st.title("95mm × 150mm | 9×3 গ্রিড | বাংলা + সিম্বল সাপোর্ট | Multi-page PDF")

st.markdown(
    """
### ✅ প্রিন্ট নির্দেশনা
- **Scale = 100% / Actual Size** দিন  
- **Fit to page / Shrink to fit বন্ধ** রাখুন  
- Printer driver-এ paper size **95mm × 150mm** ঠিক আছে কিনা নিশ্চিত করুন  
"""
)

# Ensure fonts folder
ensure_dir(FONTS_DIR)

# Sidebar: font status
with st.sidebar:
    st.header("ফন্ট সাপোর্ট (Auto)")
    st.caption("বাংলা/সিম্বল black-box সমস্যা কমাতে ফ্রি Noto ফন্ট ব্যবহার করা হচ্ছে।")

    bengali_ok = ensure_font_file(BENGALI_TTF_PATH, BENGALI_TTF_URL)
    symbols_ok = ensure_font_file(SYMBOLS_TTF_PATH, SYMBOLS_TTF_URL)

    bengali_reg = register_ttf_font("BENGALI", BENGALI_TTF_PATH) if bengali_ok else False
    symbols_reg = register_ttf_font("SYMBOLS", SYMBOLS_TTF_PATH) if symbols_ok else False

    if bengali_reg:
        st.success("✅ বাংলা ফন্ট রেডি (Noto Sans Bengali)")
    else:
        st.warning(f"⚠️ বাংলা ফন্ট লোড হয়নি। এই ফাইলটা রাখুন: {BENGALI_TTF_PATH}")

    if symbols_reg:
        st.success("✅ সিম্বল ফন্ট রেডি (Noto Sans Symbols2)")
    else:
        st.warning(f"⚠️ সিম্বল ফন্ট লোড হয়নি। এই ফাইলটা রাখুন: {SYMBOLS_TTF_PATH}")

# Font map
font_map: Dict[str, str] = {
    "BENGALI": "BENGALI" if "BENGALI" in pdfmetrics.getRegisteredFontNames() else "Helvetica",
    "SYMBOLS": "SYMBOLS" if "SYMBOLS" in pdfmetrics.getRegisteredFontNames() else "Helvetica",
}

# Load library
if "library" not in st.session_state:
    st.session_state["library"] = load_library()
library: List[str] = st.session_state["library"]

# Library UI
st.subheader("📚 আপনার সেভ করা Letter / Symbol লিস্ট")
c1, c2, c3 = st.columns([2, 2, 1])

with c1:
    selected = st.selectbox(
        "লিস্ট থেকে বাছাই করুন",
        options=(library if library else ["(লিস্ট খালি)"]),
        index=0,
        disabled=(len(library) == 0),
    )
with c2:
    new_item = st.text_input("নতুন Letter/Symbol যোগ করুন (বাংলা/সিম্বল)", value="")
with c3:
    if st.button("➕ যোগ করুন"):
        updated = add_to_library(library, new_item)
        st.session_state["library"] = updated
        save_library(updated)
        st.rerun()

if len(library) > 0:
    if st.button("🗑️ সিলেক্টেড ডিলিট করুন"):
        updated = remove_from_library(library, selected)
        st.session_state["library"] = updated
        save_library(updated)
        st.rerun()

# Text input
st.subheader("✍️ প্রিন্ট করার টেক্সট")
st.caption("Dropdown থেকে বাছাই করুন, অথবা লিখে Generate করুন।")
text_value = st.text_input(
    "টেক্সট লিখুন (বাংলা/ডাবল-লেটার/সিম্বল হতে পারে)",
    value=(selected if len(library) > 0 else ""),
)

# Controls
with st.sidebar:
    st.header("Pages")
    pages = st.number_input("কয় পেজ হবে?", min_value=1, max_value=500, value=1, step=1)

    st.header("Alignment টিউনিং")
    left_margin_mm = st.number_input("Left Margin (mm)", min_value=0.0, max_value=30.0, value=2.5, step=0.5)
    top_margin_mm = st.number_input("Top Margin (mm)", min_value=0.0, max_value=30.0, value=0.0, step=0.5)
    col_gap_mm = st.number_input("Column Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)
    row_gap_mm = st.number_input("Row Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)

    st.header("Text সেটিং")
    repeat_per_cell = st.number_input("প্রতি সেলে কয়বার রিপিট হবে?", min_value=1, max_value=20, value=4, step=1)
    base_font_size = st.slider("Base Font Size", min_value=6, max_value=80, value=18, step=1)
    symbol_scale = st.slider("ডাবল-লেটার হলে সাইজ কতটা কমবে?", min_value=0.3, max_value=1.0, value=0.75, step=0.05)

    st.header("বর্ডার")
    draw_cell_boxes = st.toggle("Row/Column cell border দেখান", value=True)
    stroke_width_pt = st.slider("বর্ডার thickness (pt)", min_value=0.1, max_value=3.0, value=0.7, step=0.1)

    st.header("Preview")
    show_preview = st.toggle("Preview দেখান", value=True)
    preview_height = st.slider("Preview height (px)", min_value=400, max_value=1100, value=700, step=50)

page = PageSpec()
grid = GridSpec()

# Generate
if st.button("✅ PDF তৈরি করুন", type="primary"):
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
            font_map=font_map,
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
        label="⬇️ PDF ডাউনলোড করুন",
        data=pdf_data,
        file_name=f"labels_95x150_9x3_pages{int(pages)}.pdf",
        mime="application/pdf",
    )