import calendar
import io
from string import capwords
from datetime import date

import pandas as pd
import streamlit as st
from supabase import create_client

from programme_export import build_excel, build_pdf, make_model
from programme_import import norm, parse

APP_NAME = "Hermanus District"
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
role = rows[0]["role"] if rows else "viewer"
if role not in ("viewer", "admin", "superadmin"):
    role = "viewer"
is_super = role == "superadmin"
my_cong = set()  # congregations an Admin may edit
if role == "admin":
    my_cong = {r["congregation_id"] for r in
               sb.table("admin_congregations").select("congregation_id").eq("user_id", user.id).execute().data}
admin = is_super  # full editing rights: programme, months, Excel import, users


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


def _chunks(rows, n=400):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def do_import():
    """Runs when the admin confirms an Excel import: replaces that month's data."""
    P = st.session_state.get("imp_parsed")
    if not P or not P["month"]:
        return
    try:
        y, m = P["month"]
        first = date(y, m, 1).isoformat()
        last = date(y, m, calendar.monthrange(y, m)[1]).isoformat()
        existing = fetch("congregations")
        idx = {norm(c["name"]): c["id"] for c in existing}
        nxt = max([c["sort"] for c in existing], default=0)
        for district, name, _ in P["book_rows"]:
            if norm(name) not in idx:
                nxt += 1
                new = sb.table("congregations").insert(
                    {"district": district or "District", "name": capwords(name), "sort": nxt}).execute().data[0]
                idx[norm(name)] = new["id"]
        n_b = n_a = 0
        if P["book_rows"]:
            sb.table("bookings").delete().gte("service_date", first).lte("service_date", last).execute()
            sb.table("service_dates").delete().gte("service_date", first).lte("service_date", last).execute()
            if P["dates"]:
                sb.table("service_dates").upsert([{"service_date": d} for d in P["dates"]]).execute()
            rows = {}
            for _, name, vals in P["book_rows"]:
                for iso, v in vals.items():
                    cid = idx[norm(name)]
                    rows[(cid, iso)] = {"congregation_id": cid, "service_date": iso, "minister": v}
            for ch in _chunks(list(rows.values())):
                sb.table("bookings").upsert(ch).execute()
            n_b = len(rows)
        if P["acts"]:
            sb.table("activities").delete().gte("act_date", first).lte("act_date", last).execute()
            arows = [{"act_date": d, "person": p, "entry": v} for (d, p), v in P["acts"].items()]
            for ch in _chunks(arows):
                sb.table("activities").upsert(ch).execute()
            n_a = len(arows)
        if P["dates"]:
            st.session_state.month = f"{y}-{m:02d}"
        st.session_state.msg = f"Imported {month_label(f'{y}-{m:02d}')}: {n_b} bookings and {n_a} programme entries."
    except Exception as e:
        st.session_state.msg = f"Import failed: {e}"


# ---------- Header ----------
st.title(f"{APP_NAME} · Pastoral Programme")
with st.sidebar:
    st.write(user.email)
    if is_super:
        st.success("Super Administrator")
    elif role == "admin":
        st.success("Admin")
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
if role == "admin":
    cnames = [c["name"] for c in cong if c["id"] in my_cong]
    st.sidebar.caption("You can edit: " + (", ".join(cnames) if cnames else "no congregation assigned yet"))

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

# ---------- Downloads (styled like the original workbook) ----------
M = make_model(month, cong, mdates, book, acts, people)
d1, d2, _ = st.columns([1, 1, 3])
try:
    d1.download_button("Download Excel", build_excel(M), file_name=f"Programme_{month}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except Exception as e:
    d1.error(f"Excel export unavailable: {e}")
try:
    d2.download_button("Download PDF", build_pdf(M), file_name=f"Programme_{month}.pdf", mime="application/pdf")
except Exception as e:
    d2.error(f"PDF export unavailable: {e}")

tabs = st.tabs(["Service bookings", "Activity programme"] + (["Import from Excel", "Manage users"] if is_super else []))
tab_b, tab_a = tabs[0], tabs[1]

# ---------- Service bookings ----------
with tab_b:
    df = filter_rows(full_b)
    cfg = {d: st.column_config.TextColumn(date.fromisoformat(d).strftime("%a %d"), width="medium") for d in mdates}
    if is_super or (role == "admin" and my_cong):
        edit_df = df if is_super else df[df.index.isin(my_cong)]
        if not is_super:
            st.markdown("**Your congregation(s)** - you can edit these")
        if len(edit_df):
            edited = st.data_editor(edit_df, column_config=cfg, hide_index=True, key=f"b{month}{q}",
                                    disabled=["District", "Congregation"])
            changes = [(rid, d, val(edited.at[rid, d])) for rid in edit_df.index for d in mdates
                       if val(edited.at[rid, d]) != val(edit_df.at[rid, d])]
            if changes and st.button(f"Save {len(changes)} booking change(s)", type="primary"):
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
        else:
            st.caption("None of your congregations match the search.")
        if not is_super:
            st.markdown("**All congregations** - view only")
            st.dataframe(df, column_config=cfg, hide_index=True)
    else:
        if role == "admin":
            st.info("No congregation has been assigned to you yet. Please ask a Super Administrator.")
        st.dataframe(df, column_config=cfg, hide_index=True)
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

# ---------- Import from Excel (admins only) ----------
if admin:
    with tabs[2]:
        st.write("Upload a programme workbook in the same layout as your original file, or one downloaded from this app. "
                 "The app reads the **Activity Programme** and **Bookings** sheets and shows a preview. "
                 "Nothing changes until you confirm.")
        up = st.file_uploader("Excel file (.xlsx)", type=["xlsx"], key="imp_file")
        if up:
            data = up.getvalue()
            try:
                first = parse(data, None, people)
            except Exception as e:
                st.error(f"I could not read that file: {e}")
                st.stop()
            t = date.today()
            opts, yy, mm = [], t.year - 1, t.month
            for _ in range(48):
                opts.append(f"{yy}-{mm:02d}")
                yy, mm = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
            det = first["month"] or (t.year, t.month)
            dflt = f"{det[0]}-{det[1]:02d}"
            sel = st.selectbox("Month this file is for", opts, index=opts.index(dflt) if dflt in opts else 12,
                               format_func=month_label, key=f"imp_month_{up.name}_{up.size}")
            P = parse(data, tuple(map(int, sel.split("-"))), people)
            st.session_state.imp_parsed = P
            known = {norm(c["name"]) for c in cong}
            nb, na = len(P["book_rows"]), len({d for (d, _) in P["acts"]})
            st.info(f"Found {nb} congregations with {len(P['dates'])} service dates, and programme entries on {na} days.")
            for w in P["warnings"]:
                st.warning(w)
            new_names = [n for _, n, _ in P["book_rows"] if norm(n) not in known]
            if new_names:
                st.warning("New congregations that will be added: " + ", ".join(new_names))
            pb, pa = st.tabs(["Bookings preview", "Programme preview"])
            with pb:
                heads = {d: date.fromisoformat(d).strftime("%a %d") for d in P["dates"]}
                st.dataframe(pd.DataFrame([{"District": dist, "Congregation": n, **{heads[d]: v.get(d, "") for d in P["dates"]}}
                                           for dist, n, v in P["book_rows"]]), hide_index=True)
            with pa:
                ds = sorted({d for (d, _) in P["acts"]})
                cols = P["persons"] + ["REMARKS"]
                st.dataframe(pd.DataFrame([{"Date": date.fromisoformat(d).strftime("%a %d"),
                                            **{p: P["acts"].get((d, p), "") for p in cols}} for d in ds]), hide_index=True)
            ok = st.checkbox(f"Replace the existing {month_label(sel)} bookings and programme with this file", key=f"imp_ok_{sel}")
            st.caption("Tip: use Download Excel first if you want a backup of what is currently in the app.")
            st.button("Import into the app", type="primary", disabled=not ok or not (nb or na), on_click=do_import)

# ---------- Manage users (Super Administrators only) ----------
if is_super:
    with tabs[3]:
        LABEL = {"viewer": "View only", "admin": "Admin", "superadmin": "Super Administrator"}
        profs = sorted(sb.table("profiles").select("*").execute().data, key=lambda p: p["email"] or "")
        assign = {}
        for r in sb.table("admin_congregations").select("*").execute().data:
            assign.setdefault(r["user_id"], []).append(r["congregation_id"])
        names = {c["id"]: c["name"] for c in cong}
        st.dataframe(pd.DataFrame([{
            "Email": p["email"], "Level": LABEL.get(p["role"], p["role"]),
            "Can edit": "Everything" if p["role"] == "superadmin"
            else ", ".join(names.get(i, "?") for i in assign.get(p["id"], [])) if p["role"] == "admin" else "",
        } for p in profs]), hide_index=True)
        st.markdown("**Change someone's level**")
        st.caption("People appear here after they have created an account.")
        emails = {p["id"]: p["email"] for p in profs}
        uid = st.selectbox("Person", list(emails), format_func=lambda i: emails[i], key="mu_who")
        cur = next(p for p in profs if p["id"] == uid)
        levels = ["viewer", "admin", "superadmin"]
        lvl = st.selectbox("Level", levels, index=levels.index(cur["role"]) if cur["role"] in levels else 0,
                           format_func=LABEL.get, key=f"mu_lvl_{uid}")
        picks = []
        if lvl == "admin":
            picks = st.multiselect("Congregation(s) this Admin may edit", list(names), format_func=names.get,
                                   default=[i for i in assign.get(uid, []) if i in names], key=f"mu_c_{uid}")
            if not picks:
                st.caption("An Admin with no congregation can only view.")
        if st.button("Save changes", type="primary", key="mu_save"):
            if uid == user.id and lvl != "superadmin":
                st.error("You can't lower your own level. Ask another Super Administrator to do it.")
            else:
                try:
                    sb.table("profiles").update({"role": lvl}).eq("id", uid).execute()
                    sb.table("admin_congregations").delete().eq("user_id", uid).execute()
                    if lvl == "admin" and picks:
                        sb.table("admin_congregations").insert(
                            [{"user_id": uid, "congregation_id": i} for i in picks]).execute()
                    st.toast("Saved")
                    st.rerun()
                except Exception as e:
                    st.error(f"Not saved: {e}")
