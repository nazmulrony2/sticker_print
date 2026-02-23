import base64
import io
from dataclasses import dataclass
from typing import List, Dict, Tuple

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth


# ✅ Your final columns (exact)
COLUMNS = ["IP", "Host", "New IP", "SFP", "Cat-6", "LAN", "At/Pr", "AP", "IP/P"]


@dataclass(frozen=True)
class PdfSpec:
    # 4×6 inch
    page_width_in: float = 4.0
    page_height_in: float = 6.0

    # 3 rows per page
    split_count: int = 3

    # margins
    margin_in: float = 0.10  # ~2.5mm

    # typography
    font_name: str = "Helvetica"
    header_font_size: int = 8
    value_font_size: int = 9

    # borders
    border_thin: float = 0.8
    border_thick: float = 1.6

    # spacing
    cell_padding: float = 3.5
    line_gap: float = 1.5


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    out = out.fillna("")
    return out


def read_uploaded_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded)
    raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx/.xls).")


def wrap_text(text: str, font: str, size: int, max_width: float) -> List[str]:
    """
    কেন: cell width এর মধ্যে টেক্সট ঢুকানোর জন্য wrap
    """
    text = str(text).strip()
    if not text:
        return [""]

    words = text.split()
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        candidate = cur + " " + w
        if stringWidth(candidate, font, size) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def draw_cell_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    font: str,
    size: int,
    padding: float,
    line_gap: float,
    max_lines: int,
    center: bool = True,
):
    """
    কেন: cell-এর মধ্যে wrapped text (center align)
    """
    c.setFont(font, size)

    usable_w = max(6.0, w - 2 * padding)
    lines = wrap_text(text, font, size, usable_w)[:max_lines]

    line_h = size + line_gap
    total_h = len(lines) * line_h

    # vertical center
    start_y = y + (h + total_h) / 2.0 - line_h

    for i, line in enumerate(lines):
        line = line.strip()
        if center:
            tw = stringWidth(line, font, size)
            tx = x + (w - tw) / 2.0
        else:
            tx = x + padding
        ty = start_y - i * line_h
        c.drawString(tx, ty, line)


def draw_block_9col_table(
    c: canvas.Canvas,
    bx: float,
    by: float,
    bw: float,
    bh: float,
    row: pd.Series,
    spec: PdfSpec,
):
    """
    Block layout:
      - Outer border
      - Two rows inside: header row + value row
      - 9 columns across

    ✅ Change requested:
      - Headers (column names) ALSO rotated so they read DOWN→UP
      - Values rotated DOWN→UP
    """

    # Outer border
    c.setLineWidth(spec.border_thin)
    c.rect(bx, by, bw, bh)

    # Header row height vs value row height
    header_h = bh * 0.32
    value_h = bh - header_h

    y_header = by + bh - header_h
    y_value = by

    # Thick line between header and value
    c.setLineWidth(spec.border_thick)
    c.line(bx, y_header, bx + bw, y_header)

    # Column widths (weighted so important fields get more space)
    weights = [1.25, 1.60, 1.35, 1.20, 1.20, 0.95, 1.05, 0.90, 1.10]
    total_w = sum(weights)
    col_ws = [(wgt / total_w) * bw for wgt in weights]

    # Vertical lines
    c.setLineWidth(spec.border_thin)
    x_line = bx
    for i in range(1, len(col_ws)):
        x_line += col_ws[i - 1]
        c.line(x_line, by, x_line, by + bh)

    header_font = "Helvetica-Bold" if spec.font_name == "Helvetica" else spec.font_name

    # -----------------------------
    # Header texts (ROTATED: down-to-up)
    # -----------------------------
    x = bx
    for col, cw in zip(COLUMNS, col_ws):
        c.saveState()

        # Center of header cell
        cx = x + (cw / 2.0)
        cy = y_header + (header_h / 2.0)
        c.translate(cx, cy)

        # Rotate 90° => vertical bottom-to-top
        c.rotate(90)

        # Draw inside rotated coord system:
        # swapped dimensions: width=header_h, height=cw
        draw_cell_text(
            c=c,
            x=-(header_h / 2.0),
            y=-(cw / 2.0),
            w=header_h,
            h=cw,
            text=col,
            font=header_font,
            size=spec.header_font_size,
            padding=spec.cell_padding,
            line_gap=spec.line_gap,
            max_lines=1,
            center=True,
        )

        c.restoreState()
        x += cw

    # -----------------------------
    # Value texts (ROTATED: down-to-up)
    # -----------------------------
    x = bx
    for col, cw in zip(COLUMNS, col_ws):
        val = str(row.get(col, "")).strip()

        c.saveState()

        # Center of value cell
        cx = x + (cw / 2.0)
        cy = y_value + (value_h / 2.0)
        c.translate(cx, cy)

        # Rotate 90° => vertical bottom-to-top
        c.rotate(90)

        # swapped dimensions: width=value_h, height=cw
        draw_cell_text(
            c=c,
            x=-(value_h / 2.0),
            y=-(cw / 2.0),
            w=value_h,
            h=cw,
            text=val,
            font=spec.font_name,
            size=spec.value_font_size,
            padding=spec.cell_padding,
            line_gap=spec.line_gap,
            max_lines=3,
            center=True,
        )

        c.restoreState()
        x += cw



def generate_pdf_3up(df: pd.DataFrame, spec: PdfSpec) -> bytes:
    """
    4×6 page; 3 blocks per page; each block is 9-column table
    """
    buf = io.BytesIO()
    page_w = spec.page_width_in * inch
    page_h = spec.page_height_in * inch

    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    m = spec.margin_in * inch
    usable_w = page_w - 2 * m
    usable_h = page_h - 2 * m

    block_h = usable_h / spec.split_count
    bx = m
    bw = usable_w

    rows = df.to_dict(orient="records")
    i = 0

    while i < len(rows):
        for k in range(spec.split_count):
            idx = i + k
            # top to bottom placement
            by = m + (spec.split_count - 1 - k) * block_h
            if idx < len(rows):
                draw_block_9col_table(c, bx, by, bw, block_h, pd.Series(rows[idx]), spec)
            else:
                # empty border block
                c.setLineWidth(spec.border_thin)
                c.rect(bx, by, bw, block_h)

        c.showPage()
        i += spec.split_count

    c.save()
    return buf.getvalue()


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="4x6 PDF 3-up (All Columns)", layout="wide")
st.title('4×6" (10×15cm) — 3 Rows per Page — PDF — All 9 Columns')

uploaded = st.file_uploader("Upload CSV / Excel", type=["csv", "xlsx", "xls"])
if uploaded is None:
    st.info("Upload your file to generate PDF.")
    st.stop()

try:
    df = normalize_df(read_uploaded_file(uploaded))
except Exception as e:
    st.error(f"File read failed: {e}")
    st.stop()

missing = [c for c in COLUMNS if c not in df.columns]
if missing:
    st.error(f"Missing required columns: {missing}")
    st.stop()

st.subheader("Preview")
st.dataframe(df[COLUMNS].head(30), use_container_width=True)

with st.sidebar:
    st.header("PDF Controls")
    margin_in = st.slider("Margin (inch)", 0.0, 0.25, 0.10, 0.01)
    header_fs = st.slider("Header font size", 6, 12, 8, 1)
    value_fs = st.slider("Value font size", 6, 14, 9, 1)
    thin = st.slider("Thin border", 0.4, 2.0, 0.8, 0.1)
    thick = st.slider("Thick header divider", 0.8, 4.0, 1.6, 0.1)

    st.divider()
    st.header("Page Control")
    pages = st.number_input("Pages to generate", min_value=1, max_value=2000, value=1, step=1)
    max_rows = int(pages) * 3

df_sel = df[COLUMNS].head(max_rows)

spec = PdfSpec(
    margin_in=float(margin_in),
    header_font_size=int(header_fs),
    value_font_size=int(value_fs),
    border_thin=float(thin),
    border_thick=float(thick),
)

if st.button("Generate PDF (3 rows per page)", type="primary"):
    try:
        pdf_bytes = generate_pdf_3up(df_sel, spec)
        st.session_state["pdf_bytes"] = pdf_bytes
        st.success(f"Generated {len(df_sel)} row(s) => {((len(df_sel)+2)//3)} page(s).")
    except Exception as e:
        st.error(f"PDF generation failed: {e}")

if "pdf_bytes" in st.session_state:
    pdf_bytes: bytes = st.session_state["pdf_bytes"]

    st.download_button(
        "Download labels_3up_4x6_allcols.pdf",
        data=pdf_bytes,
        file_name="labels_3up_4x6_allcols.pdf",
        mime="application/pdf",
    )

    st.subheader("PDF Preview")
    st.components.v1.html(
        f"""
        <iframe
            src="data:application/pdf;base64,{base64.b64encode(pdf_bytes).decode("utf-8")}"
            width="100%"
            height="680"
            style="border:1px solid #ddd;border-radius:12px;"
        ></iframe>
        """,
        height=710,
    )

    st.info("Print tip: Printing preferences এ Paper size = 4×6\" এবং Scale = 100% (Actual size) রাখুন।")
