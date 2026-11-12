import calendar
import io
from datetime import date

import pandas as pd
import streamlit as st
from supabase import create_client

APP_NAME = "Hermanus District Pastoral Programme"
st.set_page_config(page_title=f"{APP_NAME} Programme", layout="wide")

DEFAULT_PEOPLE = ["DA Lambert", "AP R Worship", "DR C. Fredericks", "REMARKS"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def val(x):
    return "" if x is None or pd.isna(x) else str(x).strip()


def month_label(m):
    return date.fromisoformat(m + "-01").strftime("%B %Y")


# ---------- Supabase client (one per browser session, so each user's login is separate) ----------
if "sb" not in st.session_state:
    st.session_state.sb = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
sb = st.session_state.sb


def login_screen():
    st.title(f"{APP_NAME} Programme")
    t_in, t_up = st.tabs(["Sign in", "Create viewer account"])
    with t_in:
        with st.form("in"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    res = sb.auth.sign_in_with_password({"email": email, "password": pw})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not sign in: {e}")
    with t_up:
        with st.form("up"):
            email = st.text_input("Email", key="e2")
            pw = st.text_input("Password (min 6 characters)", type="password", key="p2")
            if st.form_submit_button("Create account"):
                try:
                    sb.auth.sign_up({"email": email, "password": pw})
                    st.success("Account created. Check your email if confirmation is required, then sign in.")
                except Exception as e:
                    st.error(str(e))
        st.caption("New accounts can view only. An administrator can grant edit rights.")


if "user" not in st.session_state:
    login_screen()
    st.stop()

user = st.session_state.user
rows = sb.table("profiles").select("role").eq("id", user.id).execute().data
admin = bool(rows) and rows[0]["role"] == "admin"


def fetch(table):
    return sb.table(table).select("*").execute().data


def add_month():
    """Runs when the admin clicks 'Add this month' (before the page reloads)."""
    try:
        y, m = map(int, st.session_state.nm.split("-"))
        wanted = {WEEKDAYS.index(w) for w in st.session_state.nwd}
        days = [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]
        new = [{"service_date": d.isoformat()} for d in days if d.weekday() in wanted]
        if not new:
            st.session_state.msg = "Pick at least one service day."
            return
        sb.table("service_dates").upsert(new).execute()
        st.session_state.month = st.session_state.nm
        st.session_state.msg = f"Added {len(new)} service dates for {month_label(st.session_state.nm)}."
    except Exception as e:
        st.session_state.msg = f"Could not add the month: {e}"


# ---------- Exports ----------
def to_excel(sheets):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets:
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col) + 2
                ws.column_dimensions[col[0].column_letter].width = min(40, width)
    return buf.getvalue()


def to_pdf(title, sheets):
    from fpdf import FPDF

    def clean(s):
        return str(s).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(orientation="L", format="A4")
    pdf.set_margins(8, 8, 8)
    pdf.set_auto_page_break(True, 8)
    for name, df, widths in sheets:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, clean(f"{title} - {name}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=7)
        with pdf.table(col_widths=widths, line_height=4.5, text_align="LEFT") as table:
            head = table.row()
            for c in df.columns:
                head.cell(clean(c))
            for _, r in df.iterrows():
                row = table.row()
                for v in r:
                    row.cell(clean(val(v)))
    return bytes(pdf.output())


# ---------- Header ----------
st.title(f"{APP_NAME} · Pastoral Programme")
with st.sidebar:
    st.write(user.email)
    if admin:
        st.success("Admin (can edit)")
    else:
        st.info("View only")
    if st.button("Sign out"):
        sb.auth.sign_out()
        del st.session_state["user"]
        st.rerun()

if "msg" in st.session_state:
    st.toast(st.session_state.pop("msg"))

cong = sorted(fetch("congregations"), key=lambda c: c["sort"])
dates = sorted(r["service_date"] for r in fetch("service_dates"))
book = {(b["congregation_id"], b["service_date"]): b["minister"] for b in fetch("bookings")}
acts = {(a["act_date"], a["person"]): a["entry"] for a in fetch("activities")}

months = sorted({d[:7] for d in dates}) or [date.today().strftime("%Y-%m")]
this_month = date.today().strftime("%Y-%m")
c1, c2 = st.columns([1, 2])
month = c1.selectbox("Month", months, key="month", format_func=month_label,
                     index=months.index(this_month) if this_month in months else len(months) - 1)
q = c2.text_input("Find a name or activity")


def filter_rows(df):
    if not q:
        return df
    return df[df.apply(lambda r: r.astype(str).str.contains(q, case=False, regex=False).any(), axis=1)]


# Full month tables (used for the editors and for the downloads)
mdates = [d for d in dates if d.startswith(month)]
full_b = pd.DataFrame(
    [{"id": c["id"], "District": c["district"], "Congregation": c["name"],
      **{d: book.get((c["id"], d), "") for d in mdates}} for c in cong]
).set_index("id")

y, m = map(int, month.split("-"))
days = [f"{month}-{i:02d}" for i in range(1, calendar.monthrange(y, m)[1] + 1)]
extra = sorted({p for (_, p) in acts} - set(DEFAULT_PEOPLE))
people = DEFAULT_PEOPLE[:-1] + extra + ["REMARKS"]
full_a = pd.DataFrame(
    [{"iso": d, "Date": date.fromisoformat(d).strftime("%a %d"), **{p: acts.get((d, p), "") for p in people}}
     for d in days]
).set_index("iso")

# ---------- Downloads ----------
exp_b = full_b.reset_index(drop=True).rename(columns={d: date.fromisoformat(d).strftime("%a %d") for d in mdates})
exp_a = full_a.reset_index(drop=True)
d1, d2, _ = st.columns([1, 1, 3])
try:
    d1.download_button("Download Excel", to_excel([("Service bookings", exp_b), ("Activity programme", exp_a)]),
                       file_name=f"Programme_{month}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except Exception as e:
    d1.error(f"Excel export unavailable: {e}")
try:
    w_b = (2.6, 2.4) + (3,) * len(mdates)
    w_a = (1.4,) + (3,) * (len(people) - 1) + (4,)
    d2.download_button("Download PDF", to_pdf(f"{APP_NAME} - {month_label(month)}",
                       [("Service bookings", exp_b, w_b), ("Activity programme", exp_a, w_a)]),
                       file_name=f"Programme_{month}.pdf", mime="application/pdf")
except Exception as e:
    d2.error(f"PDF export unavailable: {e}")

tab_b, tab_a = st.tabs(["Service bookings", "Activity programme"])

# ---------- Service bookings ----------
with tab_b:
    df = filter_rows(full_b)
    cfg = {d: st.column_config.TextColumn(date.fromisoformat(d).strftime("%a %d"), width="medium") for d in mdates}
    edited = st.data_editor(df, column_config=cfg, hide_index=True, key=f"b{month}{q}",
                            disabled=["District", "Congregation"] if admin else True)
    changes = [(rid, d, val(edited.at[rid, d])) for rid in df.index for d in mdates
               if val(edited.at[rid, d]) != val(df.at[rid, d])]
    if admin and changes and st.button(f"Save {len(changes)} booking change(s)", type="primary"):
        try:
            for rid, d, n in changes:
                if n:
                    sb.table("bookings").upsert({"congregation_id": int(rid), "service_date": d, "minister": n}).execute()
                else:
                    sb.table("bookings").delete().eq("congregation_id", int(rid)).eq("service_date", d).execute()
            st.toast("Saved")
            st.rerun()
        except Exception as e:
            st.error(f"Not saved: {e}")
    if admin:
        with st.expander("Add a new month"):
            t = date.today()
            opts, yy, mm = [], t.year, t.month
            for _ in range(24):
                opts.append(f"{yy}-{mm:02d}")
                yy, mm = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
            st.selectbox("Month to add", opts, key="nm", format_func=month_label)
            st.multiselect("Service days", WEEKDAYS, default=["Sunday", "Wednesday"], key="nwd")
            st.button("Add this month", on_click=add_month, type="primary")
        with st.expander("Add a single service date"):
            nd = st.date_input("Date", key="nd")
            if st.button("Add date"):
                sb.table("service_dates").upsert({"service_date": nd.isoformat()}).execute()
                st.rerun()

# ---------- Activity programme ----------
with tab_a:
    adf = filter_rows(full_a)
    aedit = st.data_editor(adf, hide_index=True, key=f"a{month}{q}", disabled=["Date"] if admin else True)
    achanges = [(i, p, val(aedit.at[i, p])) for i in adf.index for p in people
                if val(aedit.at[i, p]) != val(adf.at[i, p])]
    if admin and achanges and st.button(f"Save {len(achanges)} programme change(s)", type="primary"):
        try:
            for i, p, n in achanges:
                if n:
                    sb.table("activities").upsert({"act_date": i, "person": p, "entry": n}).execute()
                else:
                    sb.table("activities").delete().eq("act_date", i).eq("person", p).execute()
            st.toast("Saved")
            st.rerun()
        except Exception as e:
            st.error(f"Not saved: {e}")
