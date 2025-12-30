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
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1300px; }

    .hero-card {
        background: linear-gradient(135deg, #111827, #1f2937);
        color: #f9fafb;
        border-radius: 22px;
        padding: 1.8rem 2.2rem 1.6rem 2.2rem;
        box-shadow: 0 18px 50px rgba(15, 23, 42, 0.45);
        position: relative; overflow: hidden;
    }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 0.4rem;
        padding: 0.15rem 0.7rem; border-radius: 999px;
        background: rgba(55, 65, 81, 0.8);
        font-size: 0.75rem; font-weight: 500;
        letter-spacing: .04em; text-transform: uppercase;
    }
    .hero-title { font-size: 2.0rem; font-weight: 700; margin-top: 0.7rem; margin-bottom: 0.4rem; }
    .hero-subtitle { font-size: 0.97rem; color: #d1d5db; max-width: 580px; }

    .metric-card {
        background: #ffffff; border-radius: 16px;
        padding: 0.9rem 1.1rem; border: 1px solid #e5e7eb;
        box-shadow: 0 12px 30px rgba(148, 163, 184, 0.24);
    }
    .metric-label {
        font-size: 0.78rem; color: #6b7280;
        text-transform: uppercase; letter-spacing: .06em;
    }
    .metric-value { font-size: 1.25rem; font-weight: 600; margin-top: 0.15rem; }

    .section-title {
        font-size: 1.1rem; font-weight: 650;
        margin-top: 1.8rem; margin-bottom: 0.4rem;
        display: flex; align-items: center; gap: 0.5rem;
    }
    .section-title span.badge {
        background: #e5f3ff; color: #1d4ed8;
        border-radius: 999px; font-size: 0.72rem;
        padding: 0.2rem 0.7rem;
        text-transform: uppercase; letter-spacing: .06em; font-weight: 600;
    }
    .section-caption { font-size: 0.87rem; color: #6b7280; margin-bottom: 0.6rem; }

    .stDataFrame tbody tr:nth-child(even) { background-color: #f9fafb; }

    [data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e5e7eb; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-badge"><span>FX client book monitor</span></div>
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

def _safe_read_excel(file, header_guess=0):
    try:
        return pd.read_excel(file, header=header_guess)
    except Exception:
        file.seek(0)
        return pd.read_excel(file)

def load_summary_sheet(file) -> pd.DataFrame:
    """
    MT5 Summary export
        0: Login
        4: NET DP/WD
        5: Credit
        7: Closed volume
        8: Commission
        10: Swap
    """
    try:
        raw = pd.read_excel(file, header=2)
    except Exception:
        file.seek(0)
        raw = pd.read_excel(file)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must contain at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["Credit"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]]
        .sum()
    )
    return grouped

def load_equity_sheet(file) -> pd.DataFrame:
    """Daily reports (EOD equity snapshots). Expect columns: Login, Equity, Currency."""
    try:
        df = pd.read_excel(file, header=2)
    except Exception:
        file.seek(0)
        df = pd.read_excel(file)

    cols_lower = [str(c).strip().lower() for c in df.columns]

    def find_col(name_options, default_idx=None):
        for opt in name_options:
            if opt in cols_lower:
                return df.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(df.columns):
            return df.columns[default_idx]
        raise ValueError(f"Could not find column for {name_options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)
    currency_col = None
    for opt in ["currency", "curr", "ccy"]:
        if opt in cols_lower:
            currency_col = df.columns[cols_lower.index(opt)]
            break

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = df[currency_col].astype(str) if currency_col is not None else "USD"
    return out

def _read_accounts_file(file) -> pd.DataFrame:
    """Read a book-accounts mapping file: expect Login and optional Group."""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

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
    """Expected: Login, FromType, ToType, ShiftEquity, optional HybridRatio"""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {str(c).lower(): c for c in df.columns}

    def pick(name):
        for k, v in lower.items():
            if k == name.lower():
                return v
        raise ValueError(f"Switch file must contain column '{name}'")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)

    if any(k.startswith("hybridratio") for k in lower.keys()):
        hr_col = pick("hybridratio")
        hr = pd.to_numeric(df[hr_col], errors="coerce")
        hr = hr.apply(lambda x: x / 100.0 if pd.notna(x) and x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan

    return out

def _clamp_negative_equity_to_zero(series: pd.Series) -> pd.Series:
    # Requirement: negative equity should be considered as 0 in Net PnL & %
    return np.where(pd.to_numeric(series, errors="coerce").fillna(0.0) < 0, 0.0, pd.to_numeric(series, errors="coerce").fillna(0.0))

def build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label, audit_show_raw=True) -> pd.DataFrame:
    """Merge all sources and calculate account-level metrics (with negative equity -> 0 rule)."""
    base = closing_df.rename(columns={"Equity": "Closing Equity Raw"}).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity Raw"})
    base = base.merge(open_renamed[["Login", "Opening Equity Raw"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # Fill numeric NaNs
    for col in ["Closing Equity Raw", "Opening Equity Raw", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Adjusted equities (negative -> 0)
    report["Opening Equity"] = _clamp_negative_equity_to_zero(report["Opening Equity Raw"])
    report["Closing Equity"] = _clamp_negative_equity_to_zero(report["Closing Equity Raw"])

    # Closed lots
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # NET PNL USD = Closing - Opening - NET DP/WD - Credit (using adjusted equities)
    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["NET_DP_WD"]
        - report["Credit"]
    )

    # NET PNL % (using adjusted opening equity)
    report["NET PNL %"] = np.where(
        report["Opening Equity"] > 0,
        (report["NET PNL USD"] / report["Opening Equity"]) * 100.0,
        0.0,
    )

    report["EOD Closing Equity Date"] = eod_label

    # Reorder
    final_cols = [
        "Login", "Group", "OrigType", "Type",
        "Closed Lots", "NET_DP_WD", "Credit", "Currency",
        "Opening Equity", "Closing Equity",
        "NET PNL USD", "NET PNL %",
        "Commission", "Swap",
        "EOD Closing Equity Date",
    ]
    if audit_show_raw:
        # keep raw columns for audit (optional)
        final_cols.insert(final_cols.index("Opening Equity")+1, "Opening Equity Raw")
        final_cols.insert(final_cols.index("Closing Equity")+1, "Closing Equity Raw")

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

            # NOTE: use adjusted closing equity from account_df
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

def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        account_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Closed_Lots=("Closed Lots", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
            Opening_Equity=("Opening Equity", "sum"),
            Closing_Equity=("Closing Equity", "sum"),
        )
        .reset_index()
    )
    return grouped

def load_lp_breakdown(file) -> pd.DataFrame:
    """Expected: LPName, OpeningEquity, ClosingEquity, NetDPWD"""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {str(c).lower(): c for c in df.columns}

    def pick(name):
        for k, v in lower.items():
            if k == name.lower():
                return v
        raise ValueError(f"LP breakdown must contain column '{name}'")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity")], errors="coerce").fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity")], errors="coerce").fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd")], errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out

def _parse_exclude_text(text: str) -> set:
    if not text:
        return set()
    # Accept comma/newline/space separated
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
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    # try common columns
    cols = [str(c).strip().lower() for c in df.columns]
    login_col = None
    for opt in ["login", "account", "accountid", "mt5", "mt4"]:
        if opt in cols:
            login_col = df.columns[cols.index(opt)]
            break
    if login_col is None:
        login_col = df.columns[0]

    ser = pd.to_numeric(df[login_col], errors="coerce").dropna()
    return set(ser.astype(int).tolist())

def build_top_gainers_losers(account_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    df = account_df.copy()
    df["RankType"] = np.where(df["NET PNL USD"] >= 0, "Gainer", "Loser")
    top_g = df.sort_values("NET PNL USD", ascending=False).head(top_n).copy()
    top_l = df.sort_values("NET PNL USD", ascending=True).head(top_n).copy()
    top_g["RankType"] = "Top Gainers"
    top_l["RankType"] = "Top Losers"
    out = pd.concat([top_g, top_l], ignore_index=True)
    return out

# ============================================================
# SIDEBAR – OPTIONAL PANELS
# ============================================================

with st.sidebar:
    st.markdown("### 🧹 Exclude accounts (NEW)")
    st.write("Upload a list OR paste logins. These accounts will be removed from the full report + summaries + Excel.")
    exclude_file = st.file_uploader("Exclude accounts file (XLSX / CSV)", type=["xlsx", "xls", "csv"], key="exclude_file")
    exclude_text = st.text_area("Or paste logins (comma/newline separated)", height=120, placeholder="e.g.\n10001\n10002\n10003")

    st.markdown("---")
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.write("Upload an LP breakdown file or leave it empty. Brokerage P&L = Total LP P&L – client A-Book P&L.")
    lp_file = st.file_uploader("LP breakdown file (XLSX / CSV)", type=["xlsx", "xls", "csv"], key="lp_file")

    st.markdown("---")
    st.markdown("### ⚙️ Accuracy controls (NEW)")
    top_n = st.slider("Top gainers/losers count", min_value=5, max_value=50, value=10, step=5)
    show_raw_equity = st.checkbox("Show raw equity columns (audit)", value=True)

# ============================================================
# MAIN – FILE UPLOADS
# ============================================================

st.markdown(
    '<div class="section-title"><span class="badge">1</span><span>Upload MT5 reports</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">'
    "Upload MT5 Summary + Daily reports and map A-Book / B-Book / Hybrid accounts."
    "</div>",
    unsafe_allow_html=True,
)

eod_label = st.text_input(
    "EOD Closing Equity Date (stored in the Excel report)",
    placeholder="e.g. 2025-12-06 EOD",
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)
c5, c6, c7 = st.columns(3)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls"],
        key="summary",
        help="MT5 Summary report (NET DP/WD, Credit, Closed volume, Commission, Swap).",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        key="closing",
    )
with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        key="opening",
    )

with c5:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with c6:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with c7:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")

st.markdown(
    """
    <div class="section-title"><span class="badge">2</span>
    <span>Book switch overrides (optional – multiple accounts)</span></div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "Upload a switch file with columns `Login, FromType, ToType, ShiftEquity, optional HybridRatio`.<br>"
    "HybridRatio is **A-Book %** after switching to Hybrid (e.g. 40 means 40% A-Book / 60% B-Book).",
    unsafe_allow_html=True,
)
switch_file = st.file_uploader("Upload book switch file", type=["xlsx", "xls", "csv"], key="switch")

st.markdown("---")

# ============================================================
# PROCESSING
# ============================================================

if st.button("🚀 Generate report"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
    else:
        try:
            with st.spinner("Processing files & calculating P&L…"):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)

                accounts_frames = []
                if a_book_file:
                    accounts_frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file:
                    accounts_frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_file:
                    accounts_frames.append(load_book_accounts(hybrid_file, "Hybrid"))

                accounts_df = pd.concat(accounts_frames, ignore_index=True)
                accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

                # Exclude list (NEW)
                exclude_set = set()
                exclude_set |= _read_exclude_file(exclude_file)
                exclude_set |= _parse_exclude_text(exclude_text)

                before_cnt = accounts_df["Login"].nunique()
                if exclude_set:
                    accounts_df = accounts_df[~accounts_df["Login"].astype("Int64").isin(list(exclude_set))].copy()
                after_cnt = accounts_df["Login"].nunique()
                excluded_cnt = max(0, before_cnt - after_cnt)

                # Switch file (optional)
                switch_df = pd.DataFrame()
                if switch_file is not None:
                    switch_df = load_switch_file(switch_file)

                # Build account-level report (negative equity -> 0 applied here)
                account_df = build_account_report(
                    summary_df, closing_df, opening_df, accounts_df, eod_label, audit_show_raw=show_raw_equity
                )

                # Accuracy checks (NEW)
                missing_open = account_df.loc[account_df["Opening Equity"].isna(), "Login"].nunique()
                missing_close = account_df.loc[account_df["Closing Equity"].isna(), "Login"].nunique()

                # Build summaries
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df, switch_df)

                # Top gainers/losers accounts (NEW)
                top_accounts_df = build_top_gainers_losers(account_df, top_n=top_n)

            # ====================================================
            # OVERVIEW KPIs
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">3</span>'
                "<span>High-level snapshot</span></div>",
                unsafe_allow_html=True,
            )

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Accounts (after exclude)</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(total_clients):,}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Excluded accounts</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(excluded_cnt):,}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L (USD)</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs loss mix</div>', unsafe_allow_html=True)
                profit_abs = float(total_profit)
                loss_abs = float(abs(total_loss))
                denom = profit_abs + loss_abs
                profit_pct = (profit_abs / denom * 100.0) if denom > 0 else 0.0
                loss_pct = (loss_abs / denom * 100.0) if denom > 0 else 0.0
                st.markdown(f'<div class="metric-value">P {profit_pct:.1f}% / L {loss_pct:.1f}%</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            if exclude_set:
                with st.expander("Show excluded logins"):
                    st.write(sorted(list(exclude_set))[:500])
                    if len(exclude_set) > 500:
                        st.info(f"Showing first 500. Total excluded list size: {len(exclude_set)}")

            # ====================================================
            # TOP GAINERS / LOSERS (NEW)
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">4</span>'
                '<span>Top gainer & top loser accounts (NEW)</span></div>',
                unsafe_allow_html=True,
            )
            t1, t2 = st.columns(2)
            with t1:
                st.markdown(f"**Top {top_n} gainers**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=False).head(top_n), use_container_width=True)
            with t2:
                st.markdown(f"**Top {top_n} losers**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=True).head(top_n), use_container_width=True)

            # ====================================================
            # FULL ACCOUNT P&L
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">5</span>'
                '<span>All accounts net P&L</span></div>',
                unsafe_allow_html=True,
            )
            st.info("Note: Negative Opening/Closing Equity is treated as 0 for NET PNL USD and NET PNL % (as requested).")
            st.dataframe(account_df, use_container_width=True)

            # ====================================================
            # BOOK SUMMARY
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">6</span>'
                '<span>Book-wise overall P&L</span></div>',
                unsafe_allow_html=True,
            )
            st.dataframe(book_df, use_container_width=True)

            pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            pnl_h = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()
            total_client_pnl = pnl_a + pnl_b + pnl_h
            client_result = "profit" if total_client_pnl >= 0 else "loss"
            st.markdown(f"**Client P&L (A + B + Hybrid): {total_client_pnl:,.2f} ({client_result})**")

            # ====================================================
            # GROUP-WISE SUMMARY
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">7</span>'
                '<span>Group-wise summary</span></div>',
                unsafe_allow_html=True,
            )

            gcol1, gcol2 = st.columns(2)
            with gcol1:
                st.markdown("**Top profit groups**")
                st.dataframe(group_df.sort_values("NET_PNL_USD", ascending=False).head(10), use_container_width=True)
            with gcol2:
                st.markdown("**Top loss groups**")
                st.dataframe(group_df.sort_values("NET_PNL_USD", ascending=True).head(10), use_container_width=True)

            # ====================================================
            # A-BOOK vs LP BROKERAGE (optional display only)
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">8</span>'
                '<span>A-Book vs LP brokerage</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"- Client A-Book P&L (from books table): **{pnl_a:,.2f}**")

            lp_table = None
            total_lp_pnl = 0.0
            if lp_file is not None:
                lp_table = load_lp_breakdown(lp_file)
                total_lp_pnl = lp_table["LP_PnL"].sum()
                st.markdown("**LP breakdown (file)**")
                st.dataframe(lp_table[["LPName", "OpeningEquity", "ClosingEquity", "NetDPWD", "LP_PnL"]], use_container_width=True)
            else:
                st.info("No LP breakdown file uploaded.")

            st.markdown(f"- Total LP P&L: **{total_lp_pnl:,.2f}**")
            brokerage_pnl = total_lp_pnl - pnl_a
            st.markdown(f"- Brokerage P&L (Total LP – A-Book): **{brokerage_pnl:,.2f}**")

            # ====================================================
            # DOWNLOAD EXCEL (Only required sheets)
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">9</span>'
                '<span>Download Excel report</span></div>',
                unsafe_allow_html=True,
            )

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                # Required sheets (as per your earlier requirement)
                account_df.to_excel(writer, index=False, sheet_name="All_Accounts_NetPNL")
                top_accounts_df.to_excel(writer, index=False, sheet_name="Top_Gainers_Losers")
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
