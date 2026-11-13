"""Reads a programme workbook (the original layout, or one downloaded from this app)."""
import calendar
import io
import re
from datetime import date, datetime, timedelta

from openpyxl import load_workbook

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def clean(v):
    return "" if v is None else " ".join(str(v).split())


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _month_from(v):
    if isinstance(v, (datetime, date)):
        return v.year, v.month
    mt = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{4})", clean(v))
    if mt:
        for fmt in ("%B %Y", "%b %Y"):
            try:
                d = datetime.strptime(f"{mt.group(1)} {mt.group(2)}", fmt)
                return d.year, d.month
            except ValueError:
                pass
    return None


def _find_sheet(wb, word, marker):
    for ws in wb.worksheets:
        if word in ws.title.lower():
            return ws
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=8, max_col=12, values_only=True):
            if any(norm(v) == marker for v in row if v is not None):
                return ws
    return None


def detect_month(wb):
    """Prefer the 'Month: November 2026' band, then a month label on the programme sheet."""
    sheets = [_find_sheet(wb, "booking", "congregations"), _find_sheet(wb, "activity", "remarks")]
    for ws in sheets:
        if ws is None:
            continue
        for row in ws.iter_rows(min_row=1, max_row=6, max_col=4, values_only=True):
            for v in row:
                if isinstance(v, str) and v.strip().lower().startswith("month:"):
                    got = _month_from(v)
                    if got:
                        return got
    for ws in reversed(sheets):
        if ws is None:
            continue
        for row in ws.iter_rows(min_row=1, max_row=6, max_col=4, values_only=True):
            for v in row:
                if isinstance(v, (datetime, date)) or (isinstance(v, str) and re.search(r"[A-Za-z]{3,9}\s+\d{4}", v)):
                    got = _month_from(v)
                    if got:
                        return got
    return None


def _parse_bookings(ws, y, m, warn):
    hdr = None
    for r in range(1, 11):
        for c in range(1, 7):
            if norm(ws.cell(r, c).value) == "congregations":
                hdr = (r, c)
    if not hdr:
        warn("Bookings sheet: could not find the 'CONGREGATIONS' heading row.")
        return [], []
    hr, cc = hdr
    cols = []
    for c in range(cc + 1, ws.max_column + 1):
        v = ws.cell(hr, c).value
        if v is None:
            continue
        if isinstance(v, (datetime, date)):
            cols.append((c, date(v.year, v.month, v.day)))
            continue
        mt = re.search(r"(\d{1,2})\s*$", clean(v))
        if mt:
            try:
                d = date(y, m, int(mt.group(1)))
            except ValueError:
                warn(f"Bookings heading '{clean(v)}' is not a valid day of the month.")
                continue
            wd = clean(v)[:3].title()
            if wd in DAYS and DAYS[d.weekday()] != wd:
                warn(f"Bookings heading '{clean(v)}' does not match the calendar ({d.strftime('%a %d %B')}). Using the date number.")
            cols.append((c, d))
    rows, district = [], ""
    for r in range(hr + 1, ws.max_row + 1):
        a = clean(ws.cell(r, cc - 1).value) if cc > 1 else ""
        if a.lower().startswith("notes"):
            break
        name = clean(ws.cell(r, cc).value)
        if not name:
            continue
        if a:
            district = a
        vals = {d.isoformat(): clean(ws.cell(r, c).value) for c, d in cols if clean(ws.cell(r, c).value)}
        rows.append((district, name, vals))
    return rows, [d.isoformat() for _, d in cols]


def _parse_activities(ws, y, m, warn, known_people):
    hdr = None
    for r in range(1, 8):
        labels = {norm(ws.cell(r, c).value): c for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None}
        if "date" in labels and "remarks" in labels:
            hdr, dc, rc = r, labels["date"], labels["remarks"]
            break
    if not hdr:
        warn("Activity sheet: could not find the 'DATE' and 'REMARKS' heading row.")
        return {}, [], []
    known = {norm(p): p for p in known_people}
    people = []
    for c in range(dc + 2, rc):
        raw = clean(ws.cell(hdr, c).value)
        if raw:
            people.append((c, known.get(norm(raw), raw)))
    acts, preview, prev = {}, [], date(y, m, 1)
    for r in range(hdr + 1, ws.max_row + 1):
        wd = clean(ws.cell(r, dc).value)[:3].title()
        if wd not in DAYS:
            continue
        d = prev
        while d.weekday() != DAYS.index(wd):
            d += timedelta(days=1)
        if d.month != m:
            warn(f"Row '{clean(ws.cell(r, dc).value)} {clean(ws.cell(r, dc + 1).value)}' falls outside the month and was skipped.")
            continue
        try:
            num = int(float(ws.cell(r, dc + 1).value))
        except (TypeError, ValueError):
            num = None
        if num is not None and num != d.day:
            warn(f"Row '{wd} {num}' was read as {d.strftime('%a %d')} because the weekday and the date number disagree. Please check it.")
        prev = d
        row = {"Date": d.strftime("%a %d")}
        for c, p in people + [(rc, "REMARKS")]:
            v = clean(ws.cell(r, c).value)
            if v:
                k = (d.isoformat(), p)
                acts[k] = acts[k] + " / " + v if k in acts and v not in acts[k] else acts.get(k, v)
        preview.append(d.isoformat())
    for (iso, p), v in list(acts.items()):
        rem = acts.get((iso, "REMARKS"), "").lower()
        if p != "REMARKS" and rem:
            kept = [x for x in v.split(" / ") if x.lower() != rem]
            if kept:
                acts[(iso, p)] = " / ".join(kept)
            else:
                del acts[(iso, p)]
    return acts, [p for _, p in people], preview


def parse(data, month=None, known_people=()):
    """Returns dict(month, dates, book_rows, persons, acts, warnings)."""
    warnings = []
    warn = warnings.append
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ym = month or detect_month(wb)
    out = dict(month=ym, dates=[], book_rows=[], persons=[], acts={}, warnings=warnings, detected=detect_month(wb))
    if not ym:
        warn("I could not tell which month this file is for. Please choose it below.")
        return out
    y, m = ym
    bs, ac = _find_sheet(wb, "booking", "congregations"), _find_sheet(wb, "activity", "remarks")
    if bs is None and ac is None:
        warn("No 'Bookings' or 'Activity Programme' sheet was found in this file.")
        return out
    if bs is not None:
        out["book_rows"], out["dates"] = _parse_bookings(bs, y, m, warn)
    if ac is not None:
        out["acts"], out["persons"], _ = _parse_activities(ac, y, m, warn, known_people)
    return out
