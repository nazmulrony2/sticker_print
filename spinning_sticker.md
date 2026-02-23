## Problem Analysis (বাংলা)

ঠিক আছে—আপনি **PDF দিয়েই প্রিন্ট করবেন**। আপনার mismatch-এর মূল কারণ ছবিতে স্পষ্ট:

* প্রিন্ট ডায়ালগে **Scale = 116%** দেখাচ্ছে
* আর **Page size** প্রিন্টার ভুলভাবে ধরছে (3.94 × 1.38 inches)

Thermal printer-এর ক্ষেত্রে PDF ঠিকমতো কাজ করাতে হলে:

1. PDF-এর **page size** একদম প্রিন্টারের media width/height-এর সাথে match হতে হবে
2. PDF-এর ভিতরে **কোনো extra margin/gap** থাকলে page size বড় হয়ে যায়
3. প্রিন্টার তখন auto-scale করে (এটাই 116%)

আপনার requirement অনুযায়ী সঠিক PDF page size হবে:

* প্রতি স্টিকার: **30mm (W) × 35mm (H)**
* একবারে 3 স্টিকার across ⇒ মোট width = **90mm**
* height = **35mm**

✅ Final PDF page size = **90mm × 35mm** (exact)

---

## Architecture (বাংলা)

* Page (media) = **90mm × 35mm**
* Sticker-1 origin: x=0mm
* Sticker-2 origin: x=30mm
* Sticker-3 origin: x=60mm
* প্রতিটি স্টিকারের ভিতরে 3×3 grid → margin/gap শুধুই **স্টিকারের ভেতরে**, page-এ নয়
* No outer page margin, No sticker gap (না হলে width 90mm ছাড়িয়ে যাবে)

---

## Code (Python / Streamlit) — PDF (3 stickers per page, exact 90×35mm)

```python
# app.py
import io
import os
from dataclasses import dataclass
from typing import Optional

import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


@dataclass(frozen=True)
class StickerSpec:
    """কেন: একেকটা স্টিকারের ভিতরের 3×3 grid-এর tuning আলাদা রাখতে হবে"""
    sticker_w_mm: float = 30.0
    sticker_h_mm: float = 35.0
    grid_cols: int = 3
    grid_rows: int = 3
    inner_margin_mm: float = 1.5
    cell_gap_mm: float = 0.8
    border_stroke_pt: float = 0.7  # বক্স লাইন thickness (pt)


def try_register_ttf(font_name: str, ttf_path: str) -> Optional[str]:
    """কেন: বাংলা/ইউনিকোড সিম্বল ঠিকমতো দেখাতে TTF দরকার হতে পারে"""
    if not os.path.exists(ttf_path):
        return None
    try:
        pdfmetrics.registerFont(TTFont(font_name, ttf_path))
        return font_name
    except Exception:
        return None


def draw_one_sticker(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    spec: StickerSpec,
    symbol: str,
    font_name: str,
    font_size: int,
    draw_boxes: bool,
) -> None:
    """কেন: একই স্টিকার 3 বার আঁকতে হবে (3-across)"""
    sw = spec.sticker_w_mm * mm
    sh = spec.sticker_h_mm * mm

    margin_x = spec.inner_margin_mm * mm
    margin_y = spec.inner_margin_mm * mm
    gap_x = spec.cell_gap_mm * mm
    gap_y = spec.cell_gap_mm * mm

    usable_w = sw - (2 * margin_x) - ((spec.grid_cols - 1) * gap_x)
    usable_h = sh - (2 * margin_y) - ((spec.grid_rows - 1) * gap_y)
    if usable_w <= 0 or usable_h <= 0:
        raise ValueError("Inner margin/gap too large for sticker size.")

    cell_w = usable_w / spec.grid_cols
    cell_h = usable_h / spec.grid_rows

    c.setLineWidth(spec.border_stroke_pt)
    c.setFont(font_name, font_size)

    for r in range(spec.grid_rows):
        for col in range(spec.grid_cols):
            x = x0 + margin_x + col * (cell_w + gap_x)
            # top-down placement
            y = y0 + (sh - margin_y) - (r + 1) * cell_h - r * gap_y

            if draw_boxes:
                c.rect(x, y, cell_w, cell_h)

            # centered text (single symbol)
            cx = x + cell_w / 2
            cy = y + cell_h / 2 - (font_size * 0.35)
            c.drawCentredString(cx, cy, symbol)


def generate_pdf_3across(
    symbol: str,
    pages: int,
    spec: StickerSpec,
    font_name: str,
    font_size: int,
    draw_boxes: bool,
) -> bytes:
    """
    কেন: Thermal printer scaling এড়াতে PDF page size একদম exact করতে হবে
    Page size = 3 * 30mm by 35mm => 90mm x 35mm
    """
    symbol = symbol.strip()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    if pages < 1:
        raise ValueError("Pages must be >= 1.")

    page_w = (3 * spec.sticker_w_mm) * mm  # 90mm EXACT
    page_h = spec.sticker_h_mm * mm        # 35mm EXACT

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setTitle("TSC 3-across Stickers (PDF exact size)")

    for _ in range(pages):
        # Sticker origins (no outer margin, no gap)
        for i in range(3):
            x0 = (i * spec.sticker_w_mm) * mm
            y0 = 0
            draw_one_sticker(
                c=c,
                x0=x0,
                y0=y0,
                spec=spec,
                symbol=symbol,
                font_name=font_name,
                font_size=font_size,
                draw_boxes=draw_boxes,
            )
        c.showPage()

    c.save()
    return buf.getvalue()


# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="TSC PDF 3-across 30×35mm", layout="centered")
st.title("PDF for TSC: 3 Stickers Across (Each 30mm×35mm) with 3×3 Boxes")

st.info(
    "IMPORTANT: Print with **Actual Size / 100%** and **Fit to page OFF**.\n\n"
    "If printer shows Scale != 100%, it means page size mismatch. This PDF is fixed to 90mm×35mm."
)

with st.sidebar:
    st.header("Sticker & Grid")
    inner_margin_mm = st.number_input("Inner margin (mm)", min_value=0.0, max_value=6.0, value=1.5, step=0.1)
    cell_gap_mm = st.number_input("Cell gap (mm)", min_value=0.0, max_value=6.0, value=0.8, step=0.1)
    border_stroke_pt = st.number_input("Box line thickness (pt)", min_value=0.1, max_value=3.0, value=0.7, step=0.1)

    st.header("Text")
    font_size = st.slider("Font size", min_value=8, max_value=120, value=28, step=1)
    draw_boxes = st.toggle("Draw 3×3 boxes", value=True)

    st.header("Pages")
    pages = st.number_input("How many pages? (each page prints 3 stickers)", min_value=1, max_value=500, value=1, step=1)

    st.header("Unicode Font (optional)")
    ttf_path = st.text_input("TTF path", value="fonts/NotoSans-Regular.ttf")

symbol = st.text_input("Single letter / symbol", value="A")

spec = StickerSpec(
    sticker_w_mm=30.0,
    sticker_h_mm=35.0,
    grid_cols=3,
    grid_rows=3,
    inner_margin_mm=float(inner_margin_mm),
    cell_gap_mm=float(cell_gap_mm),
    border_stroke_pt=float(border_stroke_pt),
)

font_name = "Helvetica"
registered = try_register_ttf("CustomTTF", ttf_path)
if registered:
    font_name = registered
else:
    st.warning("TTF not found. Using Helvetica (some Unicode may not render).")

if st.button("Generate PDF", type="primary"):
    try:
        pdf_bytes = generate_pdf_3across(
            symbol=symbol,
            pages=int(pages),
            spec=spec,
            font_name=font_name,
            font_size=int(font_size),
            draw_boxes=bool(draw_boxes),
        )
        st.download_button(
            "Download PDF (90mm×35mm, 3 stickers/page)",
            data=pdf_bytes,
            file_name="tsc_3across_30x35_3x3.pdf",
            mime="application/pdf",
        )
        st.success("PDF generated. Now print with 100% scale.")
    except Exception as e:
        st.error(f"Failed: {e}")
```

---

## Critical Considerations (বাংলা)

### 1) আপনার প্রিন্ট প্রিভিউতে যা দেখা উচিত

**Printer preview size** ideally হবে:

* **3.54 × 1.38 inches** (≈ 90mm × 35mm)
* **Scale: 100%**

যদি এখনও 116% দেখায়, তাহলে driver “media size” ভুল ধরছে—সেক্ষেত্রে printer preferences এ **custom paper size = 90mm × 35mm** সেট করুন।

### 2) কেন outer margin/gap বাদ দিলাম

Outer margin দিলে page width 90mm ছাড়িয়ে যাবে ⇒ driver auto-scale করবে ⇒ mismatch।

### 3) Alignment micro-tuning

আপনি যদি দেখেন বক্স একটু ডানে/বামে/উপরে/নিচে যাচ্ছে:

* `inner_margin_mm` 0.1mm করে টিউন করুন
* `cell_gap_mm` 0.1mm করে টিউন করুন

---

আপনি যে প্রিন্টার প্রিভিউ স্ক্রিনশট দিলেন সেখানে “3.94 inch” আসছে—এই কোডের PDF দিয়ে প্রিন্ট করলে সেটা **3.54 inch** হওয়া উচিত।
আপনি চাইলে পরেরবার **PDF print preview-এর স্ক্রিনশট** (scale + size সহ) পাঠান—আমি একদম pinpoint করে দেব কোন setting/driver এটা বাড়াচ্ছে
