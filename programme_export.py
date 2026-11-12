"""Excel and PDF exports styled like the original 'November 2026 Programme' workbook."""
import calendar
import io
import math
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

TITLE = "Cape-Coastal AP Area: PASTORAL PROGRAM"
HEADERS = {"DA Lambert": "DA LAMBERT"}
# Colours taken from the original workbook
GREEN, CYAN, DKGREEN, BLUE = "70AD47", "00B0F0", "00B050", "0070C0"
BODY, REM, PEACH, HEAD, GREY, NOTE, YELLOW = "C2FF85", "E2EFDA", "FBE5D6", "C5E0B3", "808080", "D9E1F2", "FFFF00"


def make_model(month, cong, mdates, book, acts, people):
    y, m = map(int, month.split("-"))
    persons = [p for p in people if p != "REMARKS"]
    days = []
    for i in range(1, calendar.monthrange(y, m)[1] + 1):
        d = date(y, m, i)
        iso = d.isoformat()
        days.append(dict(wd=d.strftime("%a"), n=i, cells=[acts.get((iso, p), "") for p in persons],
                         rem=acts.get((iso, "REMARKS"), "")))
    groups = []
    for c in cong:
        if not groups or groups[-1][0] != c["district"]:
            groups.append((c["district"], []))
        groups[-1][1].append((c["name"].upper(), [book.get((c["id"], d), "") for d in mdates]))
    notes = [f"{date.fromisoformat(d).strftime('%a, %d %B')} - {acts[(d, 'REMARKS')]}"
             for d in mdates if acts.get((d, "REMARKS"))]
    return dict(month=date(y, m, 1).strftime("%B %Y"), short=date(y, m, 1).strftime("%b %Y"),
                persons=[HEADERS.get(p, p) for p in persons], days=days,
                heads=[date.fromisoformat(d).strftime("%a %d") for d in mdates],
                groups=groups, notes=notes)


# =====================================================================  EXCEL
def _side(spec):
    return Side(style=spec[0], color=spec[1]) if spec else Side()


def _put(ws, r, c, v=None, font=None, fill=None, al=None, bd=None):
    cell = ws.cell(r, c)
    if v is not None:
        cell.value = v
    if font:
        cell.font = font
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)
    if al:
        cell.alignment = al
    if bd:
        cell.border = Border(left=_side(bd[0]), top=_side(bd[1]), right=_side(bd[2]), bottom=_side(bd[3]))
    return cell


def _lines(text, per_line):
    return max(1, sum(max(1, math.ceil(len(p) / per_line)) for p in str(text).split("\n")))


def _activity_sheet(ws, M):
    P, n = len(M["persons"]), len(M["days"])
    R = 4 + P  # remarks column
    last = n + 2
    for col, w in [(1, 16), (2, 7.9), (3, 3.4)] + [(4 + i, 28.5) for i in range(P)] + [(R, 54.7)]:
        ws.column_dimensions[L(col)].width = w
    thick, med, thin = ("thick", GREEN), ("medium", CYAN), ("thin", CYAN)
    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=R)
    for c in range(1, R + 1):
        _put(ws, 1, c, bd=(thick if c == 1 else None, thick, thick if c == R else None, thick))
    _put(ws, 1, 1, TITLE, Font(name="Calibri", size=28, bold=True, color=BLUE),
         al=Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[1].height = 37
    # Header row
    ws.row_dimensions[2].height = 29.5
    _put(ws, 2, 1, "Month", Font(name="Calibri", size=22, bold=True, color="375623"),
         al=Alignment(horizontal="left", vertical="center"), bd=(med, med, None, thick))
    ws.merge_cells(start_row=2, start_column=2, end_row=2, end_column=3)
    _put(ws, 2, 2, "DATE", Font(name="Calibri", size=11, bold=True, color=DKGREEN),
         al=Alignment(horizontal="center", vertical="center"), bd=(None, med, med, thick))
    _put(ws, 2, 3, bd=(None, med, med, thick))
    for i, p in enumerate(M["persons"]):
        _put(ws, 2, 4 + i, p, Font(name="Arial", size=11, bold=True), BODY,
             Alignment(horizontal="left", vertical="center", wrap_text=True), (med if i == 0 else thin, med, thin, thick))
    _put(ws, 2, R, "REMARKS", Font(name="Calibri", size=20, bold=True, color=DKGREEN), REM,
         Alignment(horizontal="center", vertical="center", wrap_text=True), (None, thick, thick, thick))
    # Month label, merged down the left
    ws.merge_cells(start_row=3, start_column=1, end_row=last, end_column=1)
    for r in range(3, last + 1):
        _put(ws, r, 1, bd=(med, thick if r == 3 else None, None, thick if r == last else med))
    _put(ws, 3, 1, M["month"], Font(name="Calibri", size=44, color="000000"),
         al=Alignment(horizontal="center", vertical="center", textRotation=90, wrap_text=True))
    for k, d in enumerate(M["days"]):
        r = 3 + k
        bottom = thick if r == last else thin
        _put(ws, r, 2, d["wd"], Font(name="Calibri", size=11, bold=True, color=DKGREEN),
             al=Alignment(vertical="center"), bd=(("medium", GREEN), thin, thin, bottom))
        _put(ws, r, 3, d["n"], Font(name="Calibri", size=11, bold=True, color=DKGREEN),
             al=Alignment(horizontal="center", vertical="center"), bd=(None, thin, med, bottom))
        lines = 1
        for i, v in enumerate(d["cells"]):
            _put(ws, r, 4 + i, v or None, Font(name="Arial", size=11), BODY,
                 Alignment(horizontal="left", vertical="center", wrap_text=True),
                 (med if i == 0 else thin, thin, thin, bottom))
            lines = max(lines, _lines(v, 29))
        _put(ws, r, R, d["rem"] or None, Font(name="Calibri", size=11), REM,
             Alignment(horizontal="left", vertical="center", wrap_text=True),
             (("thin", GREEN), ("thin", GREEN), thick, thick if r == last else ("thin", GREEN)))
        lines = max(lines, _lines(d["rem"], 56))
        ws.row_dimensions[r].height = 15 if lines == 1 else 14.5 * lines
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{L(R)}{last}"


def _bookings_sheet(ws, M):
    D = len(M["heads"])
    last = 2 + D
    blk = ("medium", "000000")
    thin = ("thin", "000000")
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 18.5
    for i in range(D):
        ws.column_dimensions[L(3 + i)].width = 14.5
    # Month band
    for c in range(1, last + 1):
        _put(ws, 1, c, fill=PEACH, bd=(blk if c == 1 else None, blk, blk if c == last else None, blk))
    _put(ws, 1, 2, f"Month: {M['month']}", Font(name="Arial", size=12, bold=True), PEACH,
         Alignment(horizontal="left", vertical="center"))
    ws.row_dimensions[1].height = 18.5
    # Header row
    _put(ws, 2, 1, "DISTRICT", Font(name="Arial", size=8, bold=True), HEAD, Alignment(vertical="center", wrap_text=True), (blk,) * 4)
    _put(ws, 2, 2, "CONGREGATIONS", Font(name="Arial", size=8, bold=True), HEAD, Alignment(vertical="center", wrap_text=True), (blk,) * 4)
    for i, h in enumerate(M["heads"]):
        _put(ws, 2, 3 + i, h, Font(name="Arial", size=11, bold=True, color="FF0000"), HEAD,
             Alignment(horizontal="center", vertical="center", wrap_text=True), (blk,) * 4)
    r = 3
    total = sum(len(g[1]) for g in M["groups"])
    done = 0
    for district, rows in M["groups"]:
        first = r
        for name, cells in rows:
            done += 1
            _put(ws, r, 2, name, Font(name="Arial", size=7, bold=True), PEACH,
                 Alignment(vertical="center", wrap_text=True), (blk,) * 4)
            lines = 1
            for i, v in enumerate(cells):
                top = blk if done == 1 else thin
                bottom = blk if done == total else thin
                _put(ws, r, 3 + i, v or None, Font(name="Arial", size=8),
                     YELLOW if v.upper().startswith("DR ") else None,
                     Alignment(horizontal="center", vertical="center", wrap_text=True),
                     (blk if i == 0 else thin, top, blk if i == D - 1 else thin, bottom))
                lines = max(lines, _lines(v, 19))
            ws.row_dimensions[r].height = 15 if lines == 1 else 11 * lines + 4
            r += 1
        ws.merge_cells(start_row=first, start_column=1, end_row=r - 1, end_column=1)
        for rr in range(first, r):
            _put(ws, rr, 1, fill=PEACH, bd=(blk,) * 4)
        _put(ws, first, 1, district, Font(name="Calibri", size=12, bold=True), PEACH,
             Alignment(horizontal="center", vertical="center", textRotation=90, wrap_text=True))
    # Notes
    r += 1
    for c in range(1, last + 1):
        _put(ws, r, c, fill=GREY, bd=(blk if c == 1 else None, blk, None, None))
    _put(ws, r, 1, "Notes", Font(name="Arial", size=10, bold=True, underline="single"), GREY,
         Alignment(vertical="center"))
    for k in range(max(4, len(M["notes"]))):
        r += 1
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last)
        for c in range(1, last + 1):
            _put(ws, r, c, fill=NOTE, bd=(blk if c == 1 else None, thin, None, thin))
        _put(ws, r, 1, M["notes"][k] if k < len(M["notes"]) else None, Font(name="Arial", size=10, bold=True), NOTE,
             Alignment(vertical="center", wrap_text=True))
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:{L(last)}{r}"


def build_excel(M):
    wb = Workbook()
    a = wb.active
    a.title = f"Activity Programme_{M['short']}"
    _activity_sheet(a, M)
    _bookings_sheet(wb.create_sheet(f"Bookings_{M['short']}"), M)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =====================================================================  PDF
def build_pdf(M):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    W, H = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"{TITLE} - {M['month']}")
    MARG = 22
    UW, UH = W - 2 * MARG, H - 2 * MARG
    hx = lambda h: colors.HexColor("#" + h)
    safe = lambda s: str(s).encode("latin-1", "replace").decode("latin-1")

    def box(x, top, w, h, text="", fill=None, bold=False, size=8, color="000000", align="C",
            line=None, lw=0.5, rot=False):
        y = H - MARG - top - h
        x += MARG
        if fill:
            c.setFillColor(hx(fill))
            c.rect(x, y, w, h, stroke=0, fill=1)
        if line:
            c.setStrokeColor(hx(line))
            c.setLineWidth(lw)
            c.rect(x, y, w, h, stroke=1, fill=0)
        text = safe(text or "")
        if not text:
            return
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFillColor(hx(color))
        if rot:
            sz = size
            while c.stringWidth(text, font, sz) > h - 6 and sz > 5:
                sz -= 0.5
            c.saveState()
            c.translate(x + w / 2, y + h / 2)
            c.rotate(90)
            c.setFont(font, sz)
            c.drawCentredString(0, -sz * 0.35, text)
            c.restoreState()
            return
        lines = []
        for part in text.split("\n"):
            lines += simpleSplit(part, font, size, w - 5) or [""]
        lh = size * 1.18
        start = y + h - (h - lh * len(lines)) / 2
        c.setFont(font, size)
        for i, ln in enumerate(lines):
            base = start - (i + 1) * lh + lh * 0.25
            if align == "C":
                c.drawCentredString(x + w / 2, base, ln)
            else:
                c.drawString(x + 3, base, ln)

    def nlines(text, w, size, bold=False):
        font = "Helvetica-Bold" if bold else "Helvetica"
        return max(1, sum(len(simpleSplit(p, font, size, w - 5) or [""]) for p in safe(text).split("\n")))

    # ---------- Page 1: activity programme
    P, n = len(M["persons"]), len(M["days"])
    cw = [16, 7.9, 3.4] + [28.5] * P + [54.7]
    k = 5.25  # points per Excel character
    rows_h = []
    for d in M["days"]:
        ln = max([nlines(v, 28.5 * k, 11) for v in d["cells"]] + [nlines(d["rem"], 54.7 * k, 11)])
        rows_h.append(15 if ln == 1 else 14.5 * ln)
    total_h = 37 + 29.5 + sum(rows_h)
    sc = min(1, UW / (sum(cw) * k), UH / total_h)
    xs = [0]
    for w in cw:
        xs.append(xs[-1] + w * k * sc)
    X = lambda i: xs[i]
    Wd = lambda i, j: xs[j] - xs[i]
    R = len(cw)
    top = 0
    box(0, top, xs[R], 37 * sc, TITLE, bold=True, size=28 * sc, color=BLUE)
    top += 37 * sc
    hh = 29.5 * sc
    box(X(0), top, Wd(0, 1), hh, "Month", bold=True, size=22 * sc, color="375623", align="L", line=CYAN)
    box(X(1), top, Wd(1, 3), hh, "DATE", bold=True, size=11 * sc, color=DKGREEN, line=CYAN)
    for i, p in enumerate(M["persons"]):
        box(X(3 + i), top, Wd(3 + i, 4 + i), hh, p, BODY, True, 11 * sc, align="L", line=CYAN)
    box(X(R - 1), top, Wd(R - 1, R), hh, "REMARKS", REM, True, 20 * sc, color=DKGREEN, line=GREEN)
    top += hh
    body_top = top
    for d, rh in zip(M["days"], rows_h):
        h = rh * sc
        box(X(1), top, Wd(1, 2), h, d["wd"], bold=True, size=11 * sc, color=DKGREEN, align="L", line=CYAN, lw=0.4)
        box(X(2), top, Wd(2, 3), h, str(d["n"]), bold=True, size=11 * sc, color=DKGREEN, line=CYAN, lw=0.4)
        for i, v in enumerate(d["cells"]):
            box(X(3 + i), top, Wd(3 + i, 4 + i), h, v, BODY, False, 11 * sc, align="L", line=CYAN, lw=0.4)
        box(X(R - 1), top, Wd(R - 1, R), h, d["rem"], REM, False, 11 * sc, align="L", line=GREEN, lw=0.4)
        top += h
    box(X(0), body_top, Wd(0, 1), top - body_top, M["month"], rot=True, size=44 * sc, line=CYAN)
    c.setStrokeColor(hx(GREEN))
    c.setLineWidth(2.2)
    c.rect(MARG, H - MARG - top, xs[R], top, stroke=1, fill=0)
    c.showPage()

    # ---------- Page 2: bookings
    D = len(M["heads"])
    cw = [13, 18.5] + [14.5] * D
    k = 5.25
    data_rows = [(g, name, cells) for g, rows in M["groups"] for name, cells in rows]
    rh = [15 if (l := max(nlines(v, 14.5 * k, 8) for v in cells) if cells else 1) == 1 else 11 * l + 4
          for _, _, cells in data_rows]
    nlines_notes = max(4, len(M["notes"]))
    total_h = 18.5 + 15 + sum(rh) + 15 + 15 + nlines_notes * 14.5
    sc = min(1, UW / (sum(cw) * k), UH / total_h)
    xs = [0]
    for w in cw:
        xs.append(xs[-1] + w * k * sc)
    X = lambda i: xs[i]
    Wd = lambda i, j: xs[j] - xs[i]
    C = len(cw)
    top = 0
    box(0, top, xs[C], 18.5 * sc, "", PEACH, line="000000", lw=1.2)
    box(X(1), top, Wd(1, C), 18.5 * sc, f"Month: {M['month']}", PEACH, True, 12 * sc, align="L")
    top += 18.5 * sc
    h = 15 * sc
    box(X(0), top, Wd(0, 1), h, "DISTRICT", HEAD, True, 8 * sc, align="L", line="000000", lw=1)
    box(X(1), top, Wd(1, 2), h, "CONGREGATIONS", HEAD, True, 8 * sc, align="L", line="000000", lw=1)
    for i, t in enumerate(M["heads"]):
        box(X(2 + i), top, Wd(2 + i, 3 + i), h, t, HEAD, True, 11 * sc, color="FF0000", line="000000", lw=1)
    top += h
    table_top = top
    idx = 0
    for district, rows in M["groups"]:
        g_top = top
        for name, cells in rows:
            h = rh[idx] * sc
            idx += 1
            box(X(1), top, Wd(1, 2), h, name, PEACH, True, 7 * sc, align="L", line="000000", lw=1)
            for i, v in enumerate(cells):
                box(X(2 + i), top, Wd(2 + i, 3 + i), h, v, YELLOW if v.upper().startswith("DR ") else None,
                    False, 8 * sc, line="000000", lw=0.4)
            top += h
        box(X(0), g_top, Wd(0, 1), top - g_top, district, PEACH, True, 12 * sc, line="000000", lw=1, rot=True)
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.4)
    c.rect(MARG, H - MARG - top, xs[C], top - table_top, stroke=1, fill=0)
    top += 15 * sc
    box(0, top, xs[C], 15 * sc, "Notes", GREY, True, 10 * sc, align="L", line="000000", lw=0.8)
    top += 15 * sc
    for i in range(nlines_notes):
        box(0, top, xs[C], 14.5 * sc, M["notes"][i] if i < len(M["notes"]) else "", NOTE, True, 10 * sc,
            align="L", line="000000", lw=0.4)
        top += 14.5 * sc
    c.showPage()
    c.save()
    return buf.getvalue()
