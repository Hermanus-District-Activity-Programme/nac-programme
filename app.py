import calendar
import json
import secrets as pysecrets
import io
from string import capwords
from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import create_client

from programme_export import build_excel, build_pdf, make_model
from programme_import import norm, parse

APP_NAME = "Hermanus District"
st.set_page_config(page_title=f"{APP_NAME} Programme", layout="wide")

DEFAULT_PEOPLE = ["DA Lambert", "AP R Worship", "DR C. Fredericks", "REMARKS"]
EMAIL_RESET = False  # set to True once a custom email service is connected in Supabase
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _gen_pw():
    return "".join(pysecrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(10))


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
    if st.session_state.pop("idle_msg", None):
        st.warning(f"You were signed out because you were inactive for {IDLE_MINUTES} minutes. Please sign in again.")
    t_in, t_up, t_rs = st.tabs(["Sign in", "Create viewer account", "Forgot password?"])
    with t_in:
        with st.form("in"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    res = sb.auth.sign_in_with_password({"email": email.strip(), "password": pw})
                    st.session_state.user = res.user
                    st.session_state.cookie_js = res.session.refresh_token  # remember this browser
                    st.session_state.pop("no_restore", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not sign in: {e}")
        st.caption("Forgot your password? Open the 'Forgot password?' tab.")
    with t_up:
        with st.form("up"):
            n1, n2 = st.columns(2)
            first = n1.text_input("First name", key="fn2")
            sur = n2.text_input("Surname", key="sn2")
            email = st.text_input("Email", key="e2")
            pw = st.text_input("Password (min 6 characters)", type="password", key="p2")
            pw2 = st.text_input("Confirm password", type="password", key="p3")
            if st.form_submit_button("Create account"):
                if not first.strip() or not sur.strip():
                    st.error("Please enter your first name and surname.")
                elif len(pw) < 6:
                    st.error("The password must be at least 6 characters.")
                elif pw != pw2:
                    st.error("The two passwords do not match. Please type them again.")
                else:
                    try:
                        sb.auth.sign_up({"email": email.strip(), "password": pw,
                                         "options": {"data": {"first_name": first.strip(), "surname": sur.strip()}}})
                        st.success("Account created. Check your email if confirmation is required, then sign in.")
                    except Exception as e:
                        st.error(str(e))
        st.caption("New accounts can view only. An administrator can grant edit rights.")
    with t_rs:
        if not EMAIL_RESET:
            st.info("Forgot your password? Please contact a Super Administrator. They can set a temporary password "
                    "for you, and you can then change it inside the app under 'Change my password'.")
        else:
            st.write("**Step 1.** Enter your email and we will send you a code.")
            with st.form("rs1"):
                em = st.text_input("Email", key="rs_email")
                if st.form_submit_button("Send me a code"):
                    try:
                        sb.auth.reset_password_for_email(em.strip())
                        st.success("If that email has an account, a code is on its way. Check your inbox and spam folder.")
                    except Exception as e:
                        st.error(f"Could not send the code: {e}")
            st.write("**Step 2.** Type the code from the email and choose a new password.")
            with st.form("rs2"):
                em2 = st.text_input("Email", key="rs_email2")
                code = st.text_input("Code from the email", key="rs_code")
                p1 = st.text_input("New password (min 6 characters)", type="password", key="rs_p1")
                p2 = st.text_input("Confirm new password", type="password", key="rs_p2")
                if st.form_submit_button("Set new password", type="primary"):
                    if not em2.strip() or not code.strip():
                        st.error("Please enter your email and the code.")
                    elif len(p1) < 6:
                        st.error("The password must be at least 6 characters.")
                    elif p1 != p2:
                        st.error("The two passwords do not match. Please type them again.")
                    else:
                        try:
                            sb.auth.verify_otp({"email": em2.strip(), "token": code.strip(), "type": "recovery"})
                            sb.auth.update_user({"password": p1})
                            sb.auth.sign_out()
                            st.success("Your password has been changed. Open the Sign in tab and sign in with it.")
                        except Exception as e:
                            st.error(f"That did not work. Check the code, or ask for a new one. ({e})")

# ---------- Stay signed in after a page refresh ----------
COOKIE, DAYS = "hm_rt", 30
IDLE_MINUTES, WARN_SECONDS = 10, 10  # sign out after 10 minutes of inactivity, with a 10-second countdown
if st.query_params.get("idle"):  # the browser sent us here after the countdown ended
    saved = st.context.cookies.get(COOKIE)
    if saved:
        try:
            sb.auth.refresh_session(saved)
            sb.auth.sign_out()  # also cancels the saved login on Supabase's side
        except Exception:
            pass
    st.session_state.cookie_js = ""
    st.session_state.no_restore = True
    st.session_state.idle_msg = True
    st.query_params.clear()
if "user" not in st.session_state and not st.session_state.get("no_restore"):
    saved = st.context.cookies.get(COOKIE)
    if saved:
        try:
            res = sb.auth.refresh_session(saved)
            st.session_state.user = res.user
            st.session_state.cookie_js = res.session.refresh_token  # tokens rotate, so store the new one
        except Exception:
            st.session_state.cookie_js = ""  # stale cookie: clear it


def write_cookie(tok):
    """Saves (or, if tok is empty, deletes) the login token in the browser."""
    age = DAYS * 24 * 3600 if tok else 0
    components.html(
        "<script>var c=%s+'='+%s+'; max-age=%d; path=/; SameSite=Lax; Secure';"
        "try{window.parent.document.cookie=c}catch(e){document.cookie=c}</script>"
        % (json.dumps(COOKIE), json.dumps(tok), age), height=0)


if "cookie_js" in st.session_state:
    tok = st.session_state.pop("cookie_js")
    st.session_state.rt_last = tok
    write_cookie(tok)

if "user" not in st.session_state:
    login_screen()
    st.stop()

user = st.session_state.user


@st.fragment(run_every="4m")
def keep_alive():
    """Quiet check every 4 minutes: keeps the connection and login fresh, and keeps the saved token current."""
    try:
        sess = sb.auth.get_session()
        if sess and sess.refresh_token != st.session_state.get("rt_last"):
            st.session_state.rt_last = sess.refresh_token
            write_cookie(sess.refresh_token)
    except Exception:
        pass


keep_alive()

IDLE_HTML = """<script>
(function(){
  var P = window.parent, D = P.document;
  var IDLE = __IDLE__, WARN = __WARN__;
  if (P.__hmIdleStop) { try { P.__hmIdleStop(); } catch (e) {} }
  var last = Date.now(), warnStart = null, box = null;
  var evs = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'];
  function activity() { if (!box) last = Date.now(); }
  evs.forEach(function (e) { D.addEventListener(e, activity, true); });
  function hide() { if (box && box.parentNode) box.parentNode.removeChild(box); box = null; warnStart = null; last = Date.now(); }
  function stop() {
    clearInterval(iv);
    evs.forEach(function (e) { D.removeEventListener(e, activity, true); });
    if (box && box.parentNode) box.parentNode.removeChild(box);
  }
  function signout() { stop(); P.location.href = P.location.pathname + '?idle=1'; }
  function show() {
    warnStart = Date.now();
    box = D.createElement('div');
    box.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:999999;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;font-family:sans-serif';
    box.innerHTML = '<div style="background:#262730;color:#fff;padding:28px 32px;border-radius:12px;max-width:380px;text-align:center;box-shadow:0 8px 30px rgba(0,0,0,.5)">'
      + '<div style="font-size:18px;font-weight:600;margin-bottom:10px">Are you still there?</div>'
      + '<div style="margin-bottom:18px">You will be signed out in <b id="hm-count" style="font-size:22px">' + WARN + '</b> seconds because of inactivity.</div>'
      + '<button id="hm-stay" style="background:#ff4b4b;color:#fff;border:0;border-radius:8px;padding:10px 22px;font-size:15px;cursor:pointer">Stay signed in</button></div>';
    D.body.appendChild(box);
    var b = D.getElementById('hm-stay'); b.onclick = hide; b.focus();
  }
  var iv = setInterval(function () {
    var now = Date.now();
    if (!box && now - last >= IDLE) { show(); }
    else if (box) {
      var left = WARN - Math.floor((now - warnStart) / 1000);
      var c = D.getElementById('hm-count'); if (c) c.textContent = Math.max(left, 0);
      if (left <= 0) signout();
    }
  }, 1000);
  P.__hmIdleStop = stop;
})();
</script>"""
components.html(IDLE_HTML.replace("__IDLE__", str(IDLE_MINUTES * 60000)).replace("__WARN__", str(WARN_SECONDS)), height=0)
try:
    rows = sb.table("profiles").select("role,first_name,surname").eq("id", user.id).execute().data
except Exception:  # names column not created yet
    rows = sb.table("profiles").select("role").eq("id", user.id).execute().data
role = rows[0]["role"] if rows else "viewer"
my_name = " ".join(x for x in [rows[0].get("first_name"), rows[0].get("surname")] if x) if rows else ""
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


def do_delete_user(uid, email, svc):
    """Super Administrators only: permanently removes a login (their profile and assignments go with it)."""
    if not is_super or uid == user.id:
        return
    try:
        create_client(st.secrets["SUPABASE_URL"], svc).auth.admin.delete_user(uid)
        st.session_state.pop("mu_who", None)
        st.session_state.msg = f"Deleted {email}."
    except Exception as e:
        st.session_state.msg = f"Could not delete {email}: {e}"


def do_remove_date(d):
    """Super Administrators only: removes a service date and any bookings entered for it."""
    if not is_super:
        return
    try:
        sb.table("bookings").delete().eq("service_date", d).execute()
        sb.table("service_dates").delete().eq("service_date", d).execute()
        y, m = int(d[:4]), int(d[5:7])
        left = (sb.table("service_dates").select("service_date")
                .gte("service_date", f"{y}-{m:02d}-01")
                .lte("service_date", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}").execute().data)
        if not left:
            st.session_state.pop("month", None)  # that month no longer has any dates
        st.session_state.pop("rm_date", None)
        st.session_state.msg = f"Removed {date.fromisoformat(d).strftime('%a %d %B')}."
    except Exception as e:
        st.session_state.msg = f"Could not remove the date: {e}"


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
    if my_name:
        st.markdown(f"**{my_name}**")
    st.write(user.email)
    if is_super:
        st.success("Super Administrator")
    elif role == "admin":
        st.success("Admin")
    else:
        st.info("View only")
    with st.expander("Change my password"):
        with st.form("chpw"):
            np1 = st.text_input("New password (min 6 characters)", type="password", key="cp1")
            np2 = st.text_input("Confirm new password", type="password", key="cp2")
            if st.form_submit_button("Change password"):
                if len(np1) < 6:
                    st.error("The password must be at least 6 characters.")
                elif np1 != np2:
                    st.error("The two passwords do not match.")
                else:
                    try:
                        sb.auth.update_user({"password": np1})
                        st.success("Your password has been changed.")
                    except Exception as e:
                        st.error(f"Could not change the password: {e}")
    if st.button("Sign out"):
        sb.auth.sign_out()
        del st.session_state["user"]
        st.session_state.cookie_js = ""  # forget this browser
        st.session_state.no_restore = True
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

        with st.expander("Remove a service date"):
            if mdates:
                rd = st.selectbox("Date to remove", mdates, key="rm_date",
                                  format_func=lambda d: date.fromisoformat(d).strftime("%a %d %B"))
                n = sum(1 for (_, dd) in book if dd == rd)
                st.caption(f"{n} booking(s) entered for this date will also be removed." if n
                           else "No bookings are entered for this date.")
                ok = st.checkbox("Yes, remove this service date", key=f"rm_ok_{rd}")
                st.button("Remove date", disabled=not ok, on_click=do_remove_date, args=(rd,))
            else:
                st.caption("There are no service dates in this month.")

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
        full = lambda p: " ".join(x for x in [p.get("first_name"), p.get("surname")] if x) or "(no name yet)"
        profs = sorted(sb.table("profiles").select("*").execute().data,
                       key=lambda p: ((p.get("surname") or "~").lower(), (p.get("first_name") or "").lower(), p["email"] or ""))
        assign = {}
        for r in sb.table("admin_congregations").select("*").execute().data:
            assign.setdefault(r["user_id"], []).append(r["congregation_id"])
        names = {c["id"]: c["name"] for c in cong}
        st.dataframe(pd.DataFrame([{
            "Name": full(p), "Email": p["email"], "Level": LABEL.get(p["role"], p["role"]),
            "Can edit": "Everything" if p["role"] == "superadmin"
            else ", ".join(names.get(i, "?") for i in assign.get(p["id"], [])) if p["role"] == "admin" else "",
        } for p in profs]), hide_index=True)
        st.markdown("**Change someone's details or level**")
        st.caption("People appear here after they have created an account.")
        label = {p["id"]: f"{full(p)} - {p['email']}" for p in profs}
        uid = st.selectbox("Person", list(label), format_func=label.get, key="mu_who")
        cur = next(p for p in profs if p["id"] == uid)
        n1, n2 = st.columns(2)
        fn = n1.text_input("First name", value=cur.get("first_name") or "", key=f"mu_fn_{uid}")
        sn = n2.text_input("Surname", value=cur.get("surname") or "", key=f"mu_sn_{uid}")
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
                    sb.table("profiles").update({"role": lvl, "first_name": fn.strip() or None,
                                                 "surname": sn.strip() or None}).eq("id", uid).execute()
                    sb.table("admin_congregations").delete().eq("user_id", uid).execute()
                    if lvl == "admin" and picks:
                        sb.table("admin_congregations").insert(
                            [{"user_id": uid, "congregation_id": i} for i in picks]).execute()
                    st.toast("Saved")
                    st.rerun()
                except Exception as e:
                    st.error(f"Not saved: {e}")
        st.divider()
        st.markdown("**Set a temporary password**")
        st.caption("For someone who has forgotten their password. Send it to them privately (for example on WhatsApp) "
                   "and ask them to change it under 'Change my password' after signing in.")
        svc = st.secrets.get("SUPABASE_SERVICE_KEY")
        if not svc:
            st.info("This needs the 'SUPABASE_SERVICE_KEY' secret to be added in Streamlit (Settings > Secrets). "
                    "Secret names this app can see right now: " + (", ".join(st.secrets.keys()) or "none"))
        elif uid == user.id:
            st.caption("To change your own password, use 'Change my password' in the sidebar.")
        else:
            tp = st.text_input("Temporary password (min 6 characters)", value=st.session_state.setdefault(f"tp_{uid}", _gen_pw()),
                               key=f"mu_tp_{uid}")
            if st.button(f"Set temporary password for {full(cur)}", key="mu_reset"):
                if len(tp) < 6:
                    st.error("The password must be at least 6 characters.")
                else:
                    try:
                        admin_sb = create_client(st.secrets["SUPABASE_URL"], svc)
                        admin_sb.auth.admin.update_user_by_id(uid, {"password": tp})
                        st.success(f"Done. Send this temporary password to {full(cur)}:")
                        st.code(tp, language=None)
                    except Exception as e:
                        st.error(f"Could not set the password: {e}")
        st.divider()
        st.markdown("**Delete this user**")
        st.caption("Permanently removes the account and its access. Bookings and programme entries are not affected, "
                   "and the person can create a new account later.")
        if not svc:
            st.info("This needs the 'SUPABASE_SERVICE_KEY' secret to be added in Streamlit (Settings > Secrets). "
                    "Secret names this app can see right now: " + (", ".join(st.secrets.keys()) or "none"))
        elif uid == user.id:
            st.caption("You can't delete your own account.")
        else:
            sure = st.checkbox(f"Yes, permanently delete {full(cur)} ({cur['email']})", key=f"mu_del_ok_{uid}")
            st.button("Delete user", disabled=not sure, key="mu_del", on_click=do_delete_user,
                      args=(uid, cur["email"], svc))
