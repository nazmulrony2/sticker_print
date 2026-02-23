import base64
import io
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import List, Optional, TypedDict

import streamlit as st
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader


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
# Storage (PNG only)
# =========================

ITEMS_DIR = "items"
ITEMS_FILE = "items_registry.json"


class RegistryItem(TypedDict):
    """কেন: শুধুই PNG আইটেম রাখবো"""
    id: str
    name: str
    type: str  # "image" only
    value: str  # image file path


def ensure_dir(path: str) -> None:
    """কেন: items/ ডিরেক্টরি না থাকলে save ব্যর্থ হবে"""
    os.makedirs(path, exist_ok=True)


def load_items() -> List[RegistryItem]:
    """কেন: আগের সেভ করা items UI তে দেখানোর জন্য"""
    if not os.path.exists(ITEMS_FILE):
        return []
    try:
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return []

        out: List[RegistryItem] = []
        for x in data:
            if isinstance(x, dict) and "id" in x and "name" in x and "type" in x and "value" in x:
                if x["type"] == "image":
                    out.append(x)  # type: ignore
        return out
    except Exception:
        return []


def save_items(items: List[RegistryItem]) -> None:
    """কেন: items persist করে রাখবো যাতে পরে নাম দিয়ে search করা যায়"""
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def safe_filename(name: str) -> str:
    """কেন: ফাইলে সেভ করার সময় unsafe character বাদ দেয়া"""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip())
    return cleaned[:60] if cleaned else "item"


# =========================
# PDF preview
# =========================

def render_pdf_preview(pdf_bytes: bytes, height_px: int) -> None:
    """কেন: ডাউনলোডের আগে Preview দেখে alignment নিশ্চিত করা যায়"""
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
# Image fitting
# =========================

def fit_image_box(img_w: int, img_h: int, box_w: float, box_h: float) -> tuple[float, float]:
    """
    কেন: ইমেজকে distortion ছাড়া box-এর ভিতরে fit করবো (aspect ratio বজায় রেখে)
    """
    if img_w <= 0 or img_h <= 0:
        return box_w, box_h
    scale = min(box_w / img_w, box_h / img_h)
    return img_w * scale, img_h * scale


# =========================
# PDF generation (PNG only)
# =========================

def generate_pdf_pages_png_only(
    item: RegistryItem,
    pages: int,
    page: PageSpec,
    grid: GridSpec,
    left_margin_mm: float,
    top_margin_mm: float,
    col_gap_mm: float,
    row_gap_mm: float,
    repeat_per_cell: int,
    draw_cell_boxes: bool,
    stroke_width_pt: float,
    image_scale: float,
) -> bytes:
    """
    কেন: pages অনুযায়ী multi-page PDF হবে।
    - PNG item => PNG ইমেজ দিয়ে print
    """
    if pages < 1:
        raise ValueError("Pages কমপক্ষে 1 হতে হবে।")

    if item["type"] != "image":
        raise ValueError("PNG-only mode: item type অবশ্যই image হতে হবে।")

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

    img_path = item["value"]
    if not os.path.exists(img_path):
        raise ValueError("Image ফাইল পাওয়া যায়নি। আবার upload করুন।")

    # কেন: একবারই লোড করে সব পেজে reuse করলে perf ভালো হয়
    pil_img = Image.open(img_path).convert("RGBA")
    img_size = (pil_img.width, pil_img.height)
    img_reader = ImageReader(pil_img)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle("95x150mm - 9x3 - multipage - PNG only")
    c.setLineWidth(stroke_width_pt)

    x0 = left_margin
    y_top = page_h - top_margin

    for _ in range(pages):
        for r in range(grid.rows):
            for col in range(grid.cols):
                x = x0 + col * (col_w + col_gap)
                y = y_top - (r + 1) * row_h - r * row_gap

                if draw_cell_boxes:
                    c.rect(x, y, col_w, row_h)

                # vertical repeat inside the cell
                padding_y = max(2.0 * mm, 0.08 * row_h)
                usable_h = max(1.0, row_h - 2 * padding_y)

                for i in range(repeat_per_cell):
                    frac = 0.5 if repeat_per_cell == 1 else i / (repeat_per_cell - 1)
                    ty = y + row_h - padding_y - (usable_h * frac)
                    tx = x + (col_w / 2.0)

                    # কেন: সিম্বল/পিক্টোগ্রাম distortion ছাড়া fit করা
                    box_w = col_w * float(image_scale)
                    box_h = (row_h / max(1, repeat_per_cell)) * float(image_scale)

                    draw_w, draw_h = fit_image_box(img_size[0], img_size[1], box_w, box_h)

                    ix = tx - (draw_w / 2.0)
                    iy = ty - (draw_h / 2.0)

                    c.drawImage(
                        img_reader,
                        ix,
                        iy,
                        width=draw_w,
                        height=draw_h,
                        mask="auto",
                        preserveAspectRatio=True,
                        anchor="c",
                    )

        c.showPage()

    c.save()
    return buf.getvalue()


# =========================
# Streamlit UI (PNG only)
# =========================

st.set_page_config(page_title="Sticker Generator", layout="centered")
st.title("Spinning Sticker Pager Generator")

st.markdown(
    """
### ব্যবহার নির্দেশিকা
- শুধু **PNG upload** করে named registry বানান  
- পরে **name দিয়ে search করে** select করুন
- PDF settings adjust করুন (margin, gap, repeat ইত্যাদি)
- **Generate PDF** বাটনে ক্লিক করুন
- PDF preview দেখুন এবং ডাউনলোড করুন
- প্রিন্ট করার সময় নিশ্চিত করুন যে স্কেলিং 100% (actual size) এ আছে, যাতে alignment ঠিক থাকে।
- সকল সিম্বল আপলোড করা হয়ে থাকলে নতুন করে আপলোড করার দরকার নেই, শুধু নাম দিয়ে সার্চ করে সিলেক্ট করে PDF বানাতে পারবেন।"""
)

ensure_dir(ITEMS_DIR)

# Load items
if "items" not in st.session_state:
    st.session_state["items"] = load_items()

items: List[RegistryItem] = st.session_state["items"]

# ---- Add new item UI (PNG only) ----
st.subheader("➕ নতুন PNG Item যোগ করুন (Name সহ)")

name_img = st.text_input("Name (যেমন: Warning, ArrowUp, Cube, Plus)", value="")
uploaded_png = st.file_uploader("Upload PNG (transparent হলে ভালো)", type=["png"])

if st.button("➕ Save PNG Item"):
    n = name_img.strip()
    if not n or uploaded_png is None:
        st.error("Name এবং PNG আপলোড দুটোই লাগবে।")
    else:
        file_base = safe_filename(n) + "_" + str(uuid.uuid4())[:8] + ".png"
        out_path = os.path.join(ITEMS_DIR, file_base)

        # কেন: Cloud/Local দুই জায়গায় persist রাখতে ডিস্কে সেভ করছি
        with open(out_path, "wb") as f:
            f.write(uploaded_png.getbuffer())

        new_item: RegistryItem = {
            "id": str(uuid.uuid4()),
            "name": n,
            "type": "image",
            "value": out_path,
        }
        items = items + [new_item]
        st.session_state["items"] = items
        save_items(items)
        st.success("PNG item saved ✅")
        st.rerun()

# ---- Search + select ----
st.subheader("🔎 Search by Name")
q = st.text_input("Search (name দিয়ে লিখুন)", value="")

def matches(item: RegistryItem, query: str) -> bool:
    """কেন: simple case-insensitive search"""
    if not query.strip():
        return True
    return query.strip().lower() in item["name"].lower()

filtered = [it for it in items if matches(it, q)]

if not filtered:
    st.warning("কোনো item পাওয়া যায়নি। নতুন item যোগ করুন।")

selected_item: Optional[RegistryItem] = None
if filtered:
    selected_item = st.selectbox(
        "Select item",
        options=filtered,
        format_func=lambda x: f"{x['name']}  (png)",
    )

# Delete selected
if selected_item is not None:
    if st.button("🗑️ Delete selected item"):
        items = [it for it in items if it["id"] != selected_item["id"]]
        st.session_state["items"] = items
        save_items(items)
        st.success("Deleted ✅")
        st.rerun()

# ---- PDF settings ----
with st.sidebar:
    st.header("PDF Settings")
    pages = st.number_input("Pages", min_value=1, max_value=500, value=1, step=1)

    left_margin_mm = st.number_input("Left Margin (mm)", min_value=0.0, max_value=30.0, value=2.5, step=0.5)
    top_margin_mm = st.number_input("Top Margin (mm)", min_value=0.0, max_value=30.0, value=0.0, step=0.5)
    col_gap_mm = st.number_input("Column Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)
    row_gap_mm = st.number_input("Row Gap (mm)", min_value=0.0, max_value=10.0, value=0.0, step=0.5)

    repeat_per_cell = st.number_input("Repeat per cell", min_value=1, max_value=20, value=4, step=1)

    image_scale = st.slider("PNG scale inside cell", min_value=0.3, max_value=1.0, value=0.85, step=0.05)

    draw_cell_boxes = st.toggle("Draw row/column cell border", value=True)
    stroke_width_pt = st.slider("Border thickness (pt)", min_value=0.1, max_value=3.0, value=0.7, step=0.1)

    st.header("Preview")
    show_preview = st.toggle("Show PDF preview", value=True)
    preview_height = st.slider("Preview height (px)", min_value=400, max_value=1100, value=700, step=50)

# ---- Generate ----
page = PageSpec()
grid = GridSpec()

if st.button("✅ Generate PDF", type="primary"):
    if selected_item is None:
        st.error("আগে একটা item select করুন।")
    else:
        try:
            pdf_bytes = generate_pdf_pages_png_only(
                item=selected_item,
                pages=int(pages),
                page=page,
                grid=grid,
                left_margin_mm=float(left_margin_mm),
                top_margin_mm=float(top_margin_mm),
                col_gap_mm=float(col_gap_mm),
                row_gap_mm=float(row_gap_mm),
                repeat_per_cell=int(repeat_per_cell),
                draw_cell_boxes=bool(draw_cell_boxes),
                stroke_width_pt=float(stroke_width_pt),
                image_scale=float(image_scale),
            )
            st.session_state["pdf_bytes"] = pdf_bytes
            st.success("PDF তৈরি হয়েছে ✅")
        except Exception as e:
            st.error(f"সমস্যা: {e}")

# ---- Preview + Download ----
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