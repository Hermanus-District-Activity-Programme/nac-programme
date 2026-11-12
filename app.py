import calendar
from datetime import date

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Cape-Coastal Programme", layout="wide")

DEFAULT_PEOPLE = ["DA Lambert", "AP R Worship", "DR C. Fredericks", "REMARKS"]


def val(x):
    return "" if x is None or pd.isna(x) else str(x).strip()


# ---------- Supabase client (one per browser session, so each user's login is separate) ----------
if "sb" not in st.session_state:
    st.session_state.sb = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
sb = st.session_state.sb


def login_screen():
    st.title("Cape-Coastal Programme")
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


# ---------- Header ----------
st.title("Cape-Coastal Area · Pastoral Programme")
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

cong = sorted(fetch("congregations"), key=lambda c: c["sort"])
dates = sorted(r["service_date"] for r in fetch("service_dates"))
book = {(b["congregation_id"], b["service_date"]): b["minister"] for b in fetch("bookings")}
acts = {(a["act_date"], a["person"]): a["entry"] for a in fetch("activities")}

months = sorted({d[:7] for d in dates}) or [date.today().strftime("%Y-%m")]
c1, c2 = st.columns([1, 2])
month = c1.selectbox("Month", months, format_func=lambda m: date.fromisoformat(m + "-01").strftime("%B %Y"))
q = c2.text_input("Find a name or activity")


def filter_rows(df):
    if not q:
        return df
    return df[df.apply(lambda r: r.astype(str).str.contains(q, case=False, regex=False).any(), axis=1)]


tab_b, tab_a = st.tabs(["Service bookings", "Activity programme"])

# ---------- Service bookings ----------
with tab_b:
    mdates = [d for d in dates if d.startswith(month)]
    df = pd.DataFrame(
        [{"id": c["id"], "District": c["district"], "Congregation": c["name"],
          **{d: book.get((c["id"], d), "") for d in mdates}} for c in cong]
    ).set_index("id")
    df = filter_rows(df)
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
        with st.expander("Add a service date"):
            nd = st.date_input("Date", key="nd")
            if st.button("Add date"):
                sb.table("service_dates").upsert({"service_date": nd.isoformat()}).execute()
                st.rerun()

# ---------- Activity programme ----------
with tab_a:
    y, m = map(int, month.split("-"))
    days = [f"{month}-{i:02d}" for i in range(1, calendar.monthrange(y, m)[1] + 1)]
    extra = sorted({p for (_, p) in acts} - set(DEFAULT_PEOPLE))
    people = DEFAULT_PEOPLE[:-1] + extra + ["REMARKS"]
    adf = pd.DataFrame(
        [{"iso": d, "Date": date.fromisoformat(d).strftime("%a %d"), **{p: acts.get((d, p), "") for p in people}}
         for d in days]
    ).set_index("iso")
    adf = filter_rows(adf)
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
