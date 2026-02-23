import base64
import io
from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth


# আপনার ফাইনাল কলাম লিস্ট
COLUMNS = ["IP", "Host", "New IP", "SFP", "Cat-6", "LAN", "At/Pr", "AP", "IP/P"]


@dataclass(frozen=True)
class PdfSpec:
    page_width_in: float = 4.0
    page_height_in: float = 6.0
    split_count: int = 3
    margin_in: float = 0.10
    font_name: str = "Helvetica-Bold"
    header_max_fs: int = 10
    header_min_fs: int = 6
    value_max_fs_general: int = 11
    value_max_fs_ap_boost: int = 13
    host_fixed_fs: int = 8
    value_min_fs: int = 6
    header_ratio: float = 0.22
    block_gap_pt: float = 6.0
    border_thin: float = 0.8
    border_thick: float = 1.6
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


def fit_text_to_cell(
    text: str,
    font: str,
    max_fs: int,
    min_fs: int,
    cell_w: float,
    cell_h: float,
    padding: float,
    line_gap: float,
    max_lines: int,
) -> Tuple[int, List[str]]:
    usable_w = max(6.0, cell_w - 2 * padding)
    usable_h = max(6.0, cell_h - 2 * padding)

    def fits(fs: int) -> Tuple[bool, List[str]]:
        lines = wrap_text(text, font, fs, usable_w)[:max_lines]
        line_h = fs + line_gap
        total_h = len(lines) * line_h
        return (total_h <= usable_h), lines

    lo, hi = min_fs, max_fs
    best_fs = min_fs
    best_lines = [""]

    while lo <= hi:
        mid = (lo + hi) // 2
        ok, lines = fits(mid)
        if ok:
            best_fs = mid
            best_lines = lines
            lo = mid + 1
        else:
            hi = mid - 1

    return best_fs, best_lines


def draw_fitted_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    font: str,
    fs: int,
    padding: float,
    line_gap: float,
    max_lines: int,
    center: bool = True,
):
    lines = wrap_text(text, font, fs, w - 2 * padding)[:max_lines]
    c.setFont(font, fs)

    line_h = fs + line_gap
    total_h = len(lines) * line_h
    start_y = y + (h + total_h) / 2.0 - line_h

    for i, line in enumerate(lines):
        line = line.strip()
        if center:
            tw = stringWidth(line, font, fs)
            tx = x + (w - tw) / 2.0
        else:
            tx = x + padding
        ty = start_y - i * line_h
        c.drawString(tx, ty, line)


def clip_to_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    p = c.beginPath()
    p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)


def draw_block_9col_table(
    c: canvas.Canvas,
    bx: float,
    by: float,
    bw: float,
    bh: float,
    row: pd.Series,
    spec: PdfSpec,
):
    c.setLineWidth(spec.border_thin)
    c.rect(bx, by, bw, bh)

    header_h = bh * spec.header_ratio
    value_h = bh - header_h
    y_header = by + bh - header_h
    y_value = by

    c.setLineWidth(spec.border_thick)
    c.line(bx, y_header, bx + bw, y_header)

    # ───────────────────────────────────────────────────────
    # FIXED WEIGHTS – balanced column widths (2025 version)
    # Host is still wider than average, but not extremely fat
    # LAN, AP, At/Pr, SFP, Cat-6 now have decent width
    # ───────────────────────────────────────────────────────
    weights = [1.25, 1.65, 1.35, 1.10, 1.10, 1.05, 1.05, 1.05, 1.15]
    # indices:   IP   Host  NewIP  SFP  Cat-6  LAN  At/Pr   AP   IP/P

    total_w = sum(weights)
    col_ws = [(wgt / total_w) * bw for wgt in weights]

    # Vertical lines
    c.setLineWidth(spec.border_thin)
    x_line = bx
    for i in range(1, len(col_ws)):
        x_line += col_ws[i - 1]
        c.line(x_line, by, x_line, by + bh)

    # Headers
    x = bx
    for col, cw in zip(COLUMNS, col_ws):
        c.saveState()
        clip_to_rect(c, x, y_header, cw, header_h)

        cx = x + (cw / 2.0)
        cy = y_header + (header_h / 2.0)
        c.translate(cx, cy)
        c.rotate(90)

        draw_fitted_text(
            c=c,
            x=-(header_h / 2.0),
            y=-(cw / 2.0),
            w=header_h,
            h=cw,
            text=col,
            font=spec.font_name,
            fs=spec.header_max_fs,
            padding=spec.cell_padding,
            line_gap=spec.line_gap,
            max_lines=1,
            center=True,
        )
        c.restoreState()
        x += cw

    # Values
    x = bx
    for col, cw in zip(COLUMNS, col_ws):
        val = str(row.get(col, "")).strip()

        c.saveState()
        clip_to_rect(c, x, y_value, cw, value_h)

        cx = x + (cw / 2.0)
        cy = y_value + (value_h / 2.0)
        c.translate(cx, cy)
        c.rotate(90)

        if col == "Host":
            this_fs = spec.host_fixed_fs
            this_max_lines = 3
        elif col == "AP":
            this_fs, _ = fit_text_to_cell(
                val, spec.font_name,
                spec.value_max_fs_ap_boost, spec.value_min_fs,
                cw, value_h,
                spec.cell_padding, spec.line_gap, 3
            )
            this_max_lines = 3
        else:
            this_fs, _ = fit_text_to_cell(
                val, spec.font_name,
                spec.value_max_fs_general, spec.value_min_fs,
                cw, value_h,
                spec.cell_padding, spec.line_gap, 3
            )
            this_max_lines = 3

        draw_fitted_text(
            c=c,
            x=-(value_h / 2.0),
            y=-(cw / 2.0),
            w=value_h,
            h=cw,
            text=val,
            font=spec.font_name,
            fs=this_fs,
            padding=spec.cell_padding,
            line_gap=spec.line_gap,
            max_lines=this_max_lines,
            center=True,
        )
        c.restoreState()
        x += cw


def generate_pdf_3up(df: pd.DataFrame, spec: PdfSpec) -> bytes:
    buf = io.BytesIO()
    page_w = spec.page_width_in * inch
    page_h = spec.page_height_in * inch
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    m = spec.margin_in * inch
    usable_w = page_w - 2 * m
    total_content_h = page_h - 2 * m
    total_gaps_h = spec.block_gap_pt * (spec.split_count - 1)
    block_h = (total_content_h - total_gaps_h) / spec.split_count

    bx = m
    bw = usable_w

    rows = df.to_dict(orient="records")
    i = 0

    while i < len(rows):
        current_y = m + (spec.split_count - 1) * (block_h + spec.block_gap_pt)

        for k in range(spec.split_count):
            idx = i + k
            by = current_y - k * (block_h + spec.block_gap_pt)

            if idx < len(rows):
                draw_block_9col_table(c, bx, by, bw, block_h, pd.Series(rows[idx]), spec)
            else:
                c.setLineWidth(spec.border_thin)
                c.rect(bx, by, bw, block_h)

        c.showPage()
        i += spec.split_count

    c.save()
    return buf.getvalue()


# ────────────────────────────────────────────────
#                  Streamlit UI
# ────────────────────────────────────────────────

st.set_page_config(page_title="4x6 PDF 3-up (Bold + Selection)", layout="wide")

st.title('4×6" লেবেল জেনারেটর — প্রতি পেজে ৩টা — সব বোল্ড')

uploaded = st.file_uploader("CSV / Excel আপলোড করুন", type=["csv", "xlsx", "xls"])

if uploaded is None:
    st.info("ফাইল আপলোড করুন")
    st.stop()

try:
    df = normalize_df(read_uploaded_file(uploaded))
except Exception as e:
    st.error(f"ফাইল পড়তে সমস্যা: {e}")
    st.stop()

missing = [c for c in COLUMNS if c not in df.columns]
if missing:
    st.error(f"অনুপস্থিত কলাম: {missing}")
    st.stop()

# Row selection
st.subheader("ডেটা প্রিভিউ — PDF-এ যুক্ত করতে চেক করুন")

df_preview = df[COLUMNS].copy()
df_preview.insert(0, "Select", False)

edited_df = st.data_editor(
    df_preview,
    column_config={
        "Select": st.column_config.CheckboxColumn(
            "Select",
            default=False,
            help="চেক করলে PDF-এ যাবে",
        )
    },
    hide_index=False,
    use_container_width=True,
    num_rows="fixed",
)

selected_df = edited_df[edited_df["Select"] == True].drop(columns=["Select"])

if selected_df.empty:
    st.info("কোনো সারি সিলেক্ট করা হয়নি → সব সারি ব্যবহার হবে")
    df_sel = df[COLUMNS].copy()
else:
    df_sel = selected_df
    st.success(f"নির্বাচিত সারি: {len(df_sel)} টি")


with st.sidebar:
    st.header("সেটিংস")
    margin_in = st.slider("মার্জিন (inch)", 0.0, 0.25, 0.10, 0.01)

    st.divider()
    st.subheader("Font Size (Value Columns)")
    value_max_general = st.slider("সাধারণ কলামের সর্বোচ্চ ফন্ট", 6, 16, 11, 1)

    st.divider()
    st.subheader("Layout")
    header_ratio = st.slider("Header ratio", 0.15, 0.35, 0.22, 0.01)
    block_gap = st.slider("লেবেলের মাঝে Gap (pt)", 0, 14, 6, 1)

    st.divider()
    st.subheader("Spacing")
    padding = st.slider("Cell padding (pt)", 1.0, 8.0, 3.5, 0.5)
    line_gap = st.slider("Line gap (pt)", 0.5, 4.0, 1.5, 0.5)


spec = PdfSpec(
    margin_in=float(margin_in),
    value_max_fs_general=int(value_max_general),
    header_ratio=float(header_ratio),
    block_gap_pt=float(block_gap),
    cell_padding=float(padding),
    line_gap=float(line_gap),
)


if st.button("PDF Generate করুন", type="primary"):
    try:
        pdf_bytes = generate_pdf_3up(df_sel, spec)
        st.session_state["pdf_bytes"] = pdf_bytes
        st.success(f"তৈরি হয়েছে: {len(df_sel)} লেবেল → ~{((len(df_sel)+2)//3)} পেজ")
    except Exception as e:
        st.error(f"সমস্যা: {e}")


if "pdf_bytes" in st.session_state:
    pdf_bytes = st.session_state["pdf_bytes"]

    st.download_button(
        "Download PDF",
        data=pdf_bytes,
        file_name="labels_3up_4x6_balanced.pdf",
        mime="application/pdf"
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

    st.info('প্রিন্ট টিপস: Paper Size = 4×6", Scale = 100% (Actual size)')