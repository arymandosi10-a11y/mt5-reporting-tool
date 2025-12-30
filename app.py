import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ============================================================
# PAGE CONFIG & GLOBAL STYLING
# ============================================================

st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main {
        background: radial-gradient(circle at top left, #ffffff 0, #f5f7fb 55%, #e9edf5 100%);
        color: #111827;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1300px;
    }
    .hero-card {
        background: linear-gradient(135deg, #111827, #1f2937);
        color: #f9fafb;
        border-radius: 22px;
        padding: 1.8rem 2.2rem 1.6rem 2.2rem;
        box-shadow: 0 18px 50px rgba(15, 23, 42, 0.45);
        overflow: hidden;
    }
    .hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.15rem 0.7rem;
        border-radius: 999px;
        background: rgba(55, 65, 81, 0.8);
        font-size: 0.75rem;
        font-weight: 500;
        letter-spacing: .04em;
        text-transform: uppercase;
    }
    .hero-title {
        font-size: 2.0rem;
        font-weight: 700;
        margin-top: 0.7rem;
        margin-bottom: 0.4rem;
    }
    .hero-subtitle {
        font-size: 0.97rem;
        color: #d1d5db;
        max-width: 640px;
    }
    .metric-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 0.9rem 1.1rem;
        border: 1px solid #e5e7eb;
        box-shadow: 0 12px 30px rgba(148, 163, 184, 0.24);
    }
    .metric-label {
        font-size: 0.78rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: .06em;
    }
    .metric-value {
        font-size: 1.25rem;
        font-weight: 600;
        margin-top: 0.15rem;
    }
    .section-title {
        font-size: 1.1rem;
        font-weight: 650;
        margin-top: 1.8rem;
        margin-bottom: 0.4rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .section-title span.badge {
        background: #e5f3ff;
        color: #1d4ed8;
        border-radius: 999px;
        font-size: 0.72rem;
        padding: 0.2rem 0.7rem;
        text-transform: uppercase;
        letter-spacing: .06em;
        font-weight: 600;
    }
    .section-caption {
        font-size: 0.87rem;
        color: #6b7280;
        margin-bottom: 0.6rem;
    }
    [data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e5e7eb;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-badge">
            <span>FX client book monitor</span>
        </div>
        <div class="hero-title">Client P&L Monitoring Tool</div>
        <div class="hero-subtitle">
            Upload MT5 reports to see account-wise, group-wise and book-wise P&L
            – including A-Book vs B-Book vs Hybrid and A-Book vs LP brokerage.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# HELPERS
# ============================================================

def _read_excel_guess(file, header=2) -> pd.DataFrame:
    try:
        return pd.read_excel(file, header=header)
    except Exception:
        file.seek(0)
        return pd.read_excel(file)

def _parse_exclude_text(text: str) -> set:
    if not text:
        return set()
    raw = text.replace(",", "\n").replace(";", "\n").replace("\t", "\n")
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    logins = set()
    for p in parts:
        try:
            logins.add(int(float(p)))
        except Exception:
            pass
    return logins

def _read_exclude_file(file) -> set:
    if file is None:
        return set()
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)

    cols = [str(c).strip().lower() for c in df.columns]
    login_col = None
    for opt in ["login", "account", "accountid"]:
        if opt in cols:
            login_col = df.columns[cols.index(opt)]
            break
    if login_col is None:
        login_col = df.columns[0]

    ser = pd.to_numeric(df[login_col], errors="coerce").dropna()
    return set(ser.astype(int).tolist())

def _read_accounts_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)

    lower_cols = {str(c).lower(): c for c in df.columns}
    if "login" in lower_cols and "Login" not in df.columns:
        df = df.rename(columns={lower_cols["login"]: "Login"})
    if "group" in lower_cols and "Group" not in df.columns:
        df = df.rename(columns={lower_cols["group"]: "Group"})

    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out

def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df

def load_switch_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)
    lower = {str(c).lower(): c for c in df.columns}

    def pick(col):
        if col.lower() not in lower:
            raise ValueError(f"Switch file must contain column '{col}'")
        return lower[col.lower()]

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)

    if "hybridratio" in lower:
        hr = pd.to_numeric(df[pick("hybridratio")], errors="coerce")
        hr = hr.apply(lambda x: x / 100.0 if pd.notna(x) and x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan

    return out

def load_equity_sheet(file, header_row=2, login_col=None, equity_col=None, currency_col=None) -> pd.DataFrame:
    df = _read_excel_guess(file, header=header_row)

    if login_col is None or equity_col is None:
        raise ValueError("Equity mapping missing: Please select Login and Equity columns in Column Mapping.")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = df[currency_col].astype(str) if currency_col else "USD"
    return out

def load_summary_sheet_mapped(
    file,
    header_row=2,
    login_col=None,
    netdpwd_col=None,
    credit_col=None,
    closedvol_col=None,
    commission_col=None,
    swap_col=None,
) -> pd.DataFrame:
    raw = _read_excel_guess(file, header=header_row)

    if login_col is None or netdpwd_col is None:
        raise ValueError("Summary mapping missing: Please select Login and NET DP/WD columns in Summary Column Mapping.")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw[login_col], errors="coerce").astype("Int64")
    df["NET_DP_WD"] = pd.to_numeric(raw[netdpwd_col], errors="coerce").fillna(0.0)

    df["Credit"] = pd.to_numeric(raw[credit_col], errors="coerce").fillna(0.0) if credit_col else 0.0
    df["ClosedVolume"] = pd.to_numeric(raw[closedvol_col], errors="coerce").fillna(0.0) if closedvol_col else 0.0
    df["Commission"] = pd.to_numeric(raw[commission_col], errors="coerce").fillna(0.0) if commission_col else 0.0
    df["Swap"] = pd.to_numeric(raw[swap_col], errors="coerce").fillna(0.0) if swap_col else 0.0

    df = df[df["Login"].notna()].copy()

    grouped = df.groupby("Login", as_index=False)[
        ["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]
    ].sum()
    return grouped

def build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label) -> pd.DataFrame:
    base = closing_df.rename(columns={"Equity": "Closing Equity Raw"}).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity Raw"})

    base = base.merge(open_renamed[["Login", "Opening Equity Raw"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    for col in ["Closing Equity Raw", "Opening Equity Raw", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    # ✅ Correct rule: ONLY negatives become 0; positives/0 stay same
    report["Opening Equity"] = report["Opening Equity Raw"].clip(lower=0)
    report["Closing Equity"] = report["Closing Equity Raw"].clip(lower=0)

    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["NET_DP_WD"]
        - report["Credit"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"] > 0,
        (report["NET PNL USD"] / report["Opening Equity"]) * 100.0,
        0.0,
    )

    report["EOD Closing Equity Date"] = eod_label

    final_cols = [
        "Login", "Group", "OrigType", "Type",
        "Closed Lots",
        "NET_DP_WD", "Credit",
        "Currency",
        "Opening Equity Raw", "Closing Equity Raw",
        "Opening Equity", "Closing Equity",
        "NET PNL USD", "NET PNL %",
        "Commission", "Swap",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report

def build_book_summary(account_df: pd.DataFrame, switch_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    switch_map = {}

    if switch_df is not None and not switch_df.empty:
        for _, r in switch_df.iterrows():
            if pd.notna(r.get("Login")):
                switch_map[int(r["Login"])] = r

    for _, r in account_df.iterrows():
        login = int(r["Login"])
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        final_type = str(r["Type"])

        if login in switch_map:
            sw = switch_map[login]
            from_type = str(sw["FromType"])
            to_type = str(sw["ToType"])
            shift_eq = float(sw["ShiftEquity"])
            hybrid_ratio = sw.get("HybridRatio", np.nan)
            if pd.isna(hybrid_ratio):
                hybrid_ratio = 0.5

            pnl_after = float(r["Closing Equity"]) - shift_eq
            pnl_before = net_pnl - pnl_after

            rows.append({"Type": from_type, "Accounts": 0, "Closed_Lots": 0.0, "NET_PNL_USD": pnl_before})

            if to_type.lower() == "hybrid":
                pnl_a = pnl_after * hybrid_ratio
                pnl_b = pnl_after * (1 - hybrid_ratio)
                rows.append({"Type": "A-Book", "Accounts": 1, "Closed_Lots": closed_lots * hybrid_ratio, "NET_PNL_USD": pnl_a})
                rows.append({"Type": "B-Book", "Accounts": 0, "Closed_Lots": closed_lots * (1 - hybrid_ratio), "NET_PNL_USD": pnl_b})
            else:
                rows.append({"Type": to_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": pnl_after})
        else:
            rows.append({"Type": final_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": net_pnl})

    book = (
        pd.DataFrame(rows)
        .groupby("Type", as_index=False)
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
    )
    return book

# ============================================================
# SIDEBAR SETTINGS
# ============================================================

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    top_n = st.slider("Top gainers/losers count", min_value=5, max_value=50, value=10, step=5)

# ============================================================
# FILE UPLOADS
# ============================================================

st.markdown(
    '<div class="section-title"><span class="badge">1</span><span>Upload MT5 reports</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">Upload Summary + Opening/Closing Equity + accounts. If some data is 0, use Column Mapping below.</div>',
    unsafe_allow_html=True,
)

eod_label = st.text_input(
    "EOD Closing Equity Date (stored in the Excel report)",
    placeholder="e.g. 2025-12-06 EOD",
)

c1, c2 = st.columns(2)
c3, _ = st.columns(2)

with c1:
    summary_file = st.file_uploader("Sheet 1 – Summary / Transactions", type=["xlsx", "xls"], key="summary")
with c2:
    closing_file = st.file_uploader("Sheet 2 – Closing Equity (EOD)", type=["xlsx", "xls"], key="closing")
with c3:
    opening_file = st.file_uploader("Sheet 3 – Opening Equity (prev EOD)", type=["xlsx", "xls"], key="opening")

# A/B/Hybrid/Exclude row
c5, c6, c7, c8 = st.columns(4)

with c5:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with c6:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with c7:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")
with c8:
    exclude_file = st.file_uploader("Exclude accounts (file)", type=["xlsx", "xls", "csv"], key="exclude_file_front")
    exclude_text = st.text_area("Exclude accounts (paste)", key="exclude_text_front", height=90, placeholder="10001\n10002\n10003")

st.markdown(
    '<div class="section-title"><span class="badge">2</span><span>Book switch overrides (optional)</span></div>',
    unsafe_allow_html=True,
)
switch_file = st.file_uploader("Upload book switch file", type=["xlsx", "xls", "csv"], key="switch")

# ============================================================
# COLUMN MAPPING (EQUITY + SUMMARY)
# ============================================================

with st.expander("🧩 Column Mapping (Fix if equity / NET DP/WD is missing)", expanded=True):
    # Read column lists
    summary_cols = []
    opening_cols = []
    closing_cols = []

    if summary_file is not None:
        tmpS = _read_excel_guess(summary_file, header=2)
        summary_cols = list(tmpS.columns)
        summary_file.seek(0)

    if closing_file is not None:
        tmpC = _read_excel_guess(closing_file, header=2)
        closing_cols = list(tmpC.columns)
        closing_file.seek(0)

    if opening_file is not None:
        tmpO = _read_excel_guess(opening_file, header=2)
        opening_cols = list(tmpO.columns)
        opening_file.seek(0)

    st.markdown("### Summary mapping (for NET DP/WD, Credit, etc.)")
    s1, s2, s3 = st.columns(3)

    with s1:
        summary_login_pick = st.selectbox("Summary: Login column", options=summary_cols, disabled=not summary_cols)
        summary_netdp_pick = st.selectbox("Summary: NET DP/WD column", options=summary_cols, disabled=not summary_cols)

    with s2:
        summary_credit_pick = st.selectbox("Summary: Credit column (optional)", options=["(none)"] + summary_cols, disabled=not summary_cols)
        summary_comm_pick = st.selectbox("Summary: Commission column (optional)", options=["(none)"] + summary_cols, disabled=not summary_cols)

    with s3:
        summary_vol_pick = st.selectbox("Summary: Closed volume column (optional)", options=["(none)"] + summary_cols, disabled=not summary_cols)
        summary_swap_pick = st.selectbox("Summary: Swap column (optional)", options=["(none)"] + summary_cols, disabled=not summary_cols)

    st.markdown("---")
    st.markdown("### Equity mapping (for Opening/Closing equity)")
    e1, e2 = st.columns(2)

    with e1:
        st.markdown("**Closing file**")
        closing_login_pick = st.selectbox("Closing: Login column", options=closing_cols, disabled=not closing_cols, key="cl_login")
        closing_equity_pick = st.selectbox("Closing: Equity column", options=closing_cols, disabled=not closing_cols, key="cl_eq")
        closing_ccy_pick = st.selectbox("Closing: Currency column (optional)", options=["(none)"] + closing_cols, disabled=not closing_cols, key="cl_ccy")

    with e2:
        st.markdown("**Opening file**")
        opening_login_pick = st.selectbox("Opening: Login column", options=opening_cols, disabled=not opening_cols, key="op_login")
        opening_equity_pick = st.selectbox("Opening: Equity column", options=opening_cols, disabled=not opening_cols, key="op_eq")
        opening_ccy_pick = st.selectbox("Opening: Currency column (optional)", options=["(none)"] + opening_cols, disabled=not opening_cols, key="op_ccy")

# ============================================================
# PROCESSING
# ============================================================

if st.button("🚀 Generate report"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
        st.stop()
    if not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
        st.stop()
    if not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
        st.stop()

    try:
        with st.spinner("Processing files & calculating P&L…"):

            # Summary (mapped)
            summary_df = load_summary_sheet_mapped(
                summary_file,
                login_col=summary_login_pick if summary_cols else None,
                netdpwd_col=summary_netdp_pick if summary_cols else None,
                credit_col=None if (not summary_cols or summary_credit_pick == "(none)") else summary_credit_pick,
                closedvol_col=None if (not summary_cols or summary_vol_pick == "(none)") else summary_vol_pick,
                commission_col=None if (not summary_cols or summary_comm_pick == "(none)") else summary_comm_pick,
                swap_col=None if (not summary_cols or summary_swap_pick == "(none)") else summary_swap_pick,
            )

            # Equity (mapped)
            closing_df = load_equity_sheet(
                closing_file,
                login_col=closing_login_pick if closing_cols else None,
                equity_col=closing_equity_pick if closing_cols else None,
                currency_col=None if (not closing_cols or closing_ccy_pick == "(none)") else closing_ccy_pick,
            )
            opening_df = load_equity_sheet(
                opening_file,
                login_col=opening_login_pick if opening_cols else None,
                equity_col=opening_equity_pick if opening_cols else None,
                currency_col=None if (not opening_cols or opening_ccy_pick == "(none)") else opening_ccy_pick,
            )

            # Accounts mapping
            frames = []
            if a_book_file:
                frames.append(load_book_accounts(a_book_file, "A-Book"))
            if b_book_file:
                frames.append(load_book_accounts(b_book_file, "B-Book"))
            if hybrid_file:
                frames.append(load_book_accounts(hybrid_file, "Hybrid"))

            accounts_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Login"], keep="first")

            # Exclude
            exclude_set = set()
            exclude_set |= _read_exclude_file(exclude_file)
            exclude_set |= _parse_exclude_text(exclude_text)

            before_cnt = accounts_df["Login"].nunique()
            if exclude_set:
                accounts_df = accounts_df[~accounts_df["Login"].astype("Int64").isin(list(exclude_set))].copy()
            after_cnt = accounts_df["Login"].nunique()
            excluded_cnt = max(0, before_cnt - after_cnt)

            # Switch
            switch_df = load_switch_file(switch_file) if switch_file is not None else pd.DataFrame()

            # Build reports
            account_df = build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label)
            book_df = build_book_summary(account_df, switch_df)

        # ====================================================
        # DATA HEALTH CHECKS (prevents “0 everywhere” confusion)
        # ====================================================
        if account_df["Opening Equity Raw"].abs().sum() == 0 and account_df["Closing Equity Raw"].abs().sum() == 0:
            st.error("⚠️ Equity looks like ALL ZERO. Your Equity column selection is wrong. Fix in Column Mapping.")
            st.stop()

        if summary_df["NET_DP_WD"].abs().sum() == 0 and summary_df["Credit"].abs().sum() == 0:
            st.warning("⚠️ Summary NET DP/WD and Credit are all zero. Likely Summary mapping is wrong. Fix in Column Mapping.")

        # Missing summary logins diagnostics
        acc_set = set(accounts_df["Login"].dropna().astype(int).tolist())
        sum_set = set(summary_df["Login"].dropna().astype(int).tolist())
        missing_in_summary = acc_set - sum_set
        if len(missing_in_summary) > 0:
            st.warning(f"⚠️ {len(missing_in_summary)} account(s) are missing in Summary file (NET DP/WD will be 0 for them).")
            with st.expander("Show missing logins (first 100)"):
                st.dataframe(pd.DataFrame({"Missing_Logins": sorted(list(missing_in_summary))[:100]}), use_container_width=True)

        # ====================================================
        # KPIs
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">3</span><span>High-level snapshot</span></div>',
            unsafe_allow_html=True,
        )

        k1, k2, k3, k4 = st.columns(4)
        total_clients = int(account_df["Login"].nunique())
        net_pnl = float(account_df["NET PNL USD"].sum())
        total_profit = float(account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum())
        total_loss = float(account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum())

        with k1:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Accounts (after exclude)</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">{total_clients:,}</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with k2:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Excluded accounts</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">{excluded_cnt:,}</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with k3:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Net client P&L (USD)</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">{net_pnl:,.2f}</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with k4:
            profit_abs = abs(total_profit)
            loss_abs = abs(total_loss)
            denom = profit_abs + loss_abs
            profit_pct = (profit_abs / denom * 100.0) if denom > 0 else 0.0
            loss_pct = (loss_abs / denom * 100.0) if denom > 0 else 0.0
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Profit vs loss mix</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">P {profit_pct:.1f}% / L {loss_pct:.1f}%</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # ====================================================
        # TOP GAINERS / LOSERS
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">4</span><span>Top gainer & top loser accounts</span></div>',
            unsafe_allow_html=True,
        )
        t1, t2 = st.columns(2)
        with t1:
            st.markdown(f"**Top {top_n} gainers**")
            st.dataframe(
                account_df.sort_values("NET PNL USD", ascending=False).head(top_n),
                use_container_width=True,
                height=420,
            )
        with t2:
            st.markdown(f"**Top {top_n} losers**")
            st.dataframe(
                account_df.sort_values("NET PNL USD", ascending=True).head(top_n),
                use_container_width=True,
                height=420,
            )

        # ====================================================
        # ALL ACCOUNTS
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">5</span><span>All accounts net P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.info("Rule: ONLY if Opening/Closing Equity is NEGATIVE → treated as 0. Positive and 0 equity stays unchanged.")
        st.dataframe(account_df, use_container_width=True, height=520)

        # ====================================================
        # BOOK SUMMARY
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">6</span><span>Book-wise overall P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(book_df, use_container_width=True, height=260)

        # ====================================================
        # EXCEL DOWNLOAD (ONLY 3 sheets)
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">7</span><span>Download Excel report</span></div>',
            unsafe_allow_html=True,
        )

        # Build top sheet combined
        top_g = account_df.sort_values("NET PNL USD", ascending=False).head(top_n).copy()
        top_l = account_df.sort_values("NET PNL USD", ascending=True).head(top_n).copy()
        top_g["RankType"] = "Top Gainers"
        top_l["RankType"] = "Top Losers"
        top_df = pd.concat([top_g, top_l], ignore_index=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            account_df.to_excel(writer, index=False, sheet_name="All_Accounts_NetPNL")
            top_df.to_excel(writer, index=False, sheet_name="Top_Gainers_Losers")
            book_df.to_excel(writer, index=False, sheet_name="Books_Overall_PNL")

        output.seek(0)
        st.download_button(
            "⬇️ Download Excel report",
            data=output,
            file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.error(f"❌ Error while generating report: {e}")
