import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =====================================================================
# PAGE CONFIG & GLOBAL STYLE
# =====================================================================

st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Light premium styling
st.markdown(
    """
<style>
:root {
    --bg: #f5f7fb;
    --card-bg: #ffffff;
    --accent: #2563eb;
    --accent-soft: rgba(37, 99, 235, 0.08);
    --accent-strong: #1d4ed8;
    --text-main: #111827;
    --text-subtle: #6b7280;
    --border-soft: #e5e7eb;
    --radius-lg: 16px;
    --radius-md: 12px;
    --shadow-soft: 0 18px 35px rgba(15, 23, 42, 0.08);
}

body, .main {
    background-color: var(--bg);
    color: var(--text-main);
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
}

.block-container {
    padding-top: 0.5rem;
    padding-bottom: 3rem;
}

/* Hero header */
.hero {
    background: radial-gradient(circle at 0% 0%, #eef2ff 0, #dbeafe 35%, #eff6ff 100%);
    border-radius: 0 0 24px 24px;
    padding: 24px 32px 28px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    border-bottom: 1px solid rgba(148, 163, 184, 0.35);
    margin-bottom: 1.25rem;
}
.hero-tag {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    font-size: 0.72rem;
    border-radius: 999px;
    border: 1px solid rgba(37, 99, 235, 0.25);
    background-color: rgba(255, 255, 255, 0.6);
    color: var(--accent-strong);
    gap: 0.3rem;
}
.hero-title {
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    margin-top: 0.7rem;
}
.hero-subtitle {
    font-size: 0.92rem;
    color: var(--text-subtle);
    max-width: 52rem;
}

/* Generic cards */
.card {
    background-color: var(--card-bg);
    border-radius: var(--radius-lg);
    padding: 1.25rem 1.4rem;
    border: 1px solid var(--border-soft);
    box-shadow: var(--shadow-soft);
}

.metric-card {
    background-color: var(--card-bg);
    border-radius: var(--radius-md);
    padding: 0.9rem 1.0rem;
    border: 1px solid var(--border-soft);
}
.metric-label {
    font-size: 0.75rem;
    color: var(--text-subtle);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.metric-value {
    font-size: 1.2rem;
    font-weight: 600;
    margin-top: 0.15rem;
}
.metric-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background-color: var(--accent-soft);
    color: var(--accent-strong);
    font-size: 0.76rem;
    margin-top: 0.3rem;
}

/* Section headers */
h3 {
    margin-top: 1.6rem;
    margin-bottom: 0.3rem;
}
.section-subtitle {
    font-size: 0.82rem;
    color: var(--text-subtle);
    margin-bottom: 0.6rem;
}

/* Dataframe tweaks */
.dataframe thead th {
    background-color: #f9fafb !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# =====================================================================
# HERO
# =====================================================================

st.markdown(
    """
<div class="hero">
  <div class="hero-tag">
    <span>📉 FX client book monitor</span>
  </div>
  <div class="hero-title">Client P&L Monitoring Tool</div>
  <div class="hero-subtitle">
    Upload MT5 exports to see account-wise, group-wise and book-wise P&amp;L,
    including A-Book / B-Book / Hybrid, book switches, Hybrid ratios and
    A-Book vs LP brokerage (multi-LP support).
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# =====================================================================
# HELPERS
# =====================================================================

def normalise_ratio(x: float) -> float:
    """
    Convert HybridRatio to 0–1.
    Accepts 40 -> 0.40, 0.4 -> 0.4, 50% etc.
    """
    if pd.isna(x):
        return np.nan
    try:
        x = float(x)
    except Exception:
        return np.nan
    if x > 1.0:  # treat as percent
        return x / 100.0
    return x


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Column mapping (0-based index):
        0: Login
        2: Deposit           (C)
        4: NET DP/WD         (E)
        5: Withdrawal        (F)
        7: Closed volume     (H)  -> lots = H / 2
        8: Commission        (I)
        10: Swap             (K)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # most MT5 reports have header row at index 2
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must have at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit", "NET_DP_WD", "Withdrawal", "ClosedVolume", "Commission", "Swap"]
        ].sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 or 3: Daily Reports (EOD snapshots)
    Expect columns: Login, Equity, Currency (if not present, assume USD).
    """
    try:
        df = pd.read_excel(file, header=2)
    except Exception:
        df = pd.read_excel(file)

    cols_lower = [str(c).strip().lower() for c in df.columns]

    def find_col(options, default_idx=None):
        for opt in options:
            if opt in cols_lower:
                return df.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(df.columns):
            return df.columns[default_idx]
        raise ValueError(f"Could not find any of {options}")

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
    if currency_col is not None:
        out["Currency"] = df[currency_col].astype(str)
    else:
        out["Currency"] = "USD"
    return out


def _read_accounts_file(file) -> pd.DataFrame:
    """
    Base reader for account-book lists.
    Accepts columns:
      - Login
      - Group (optional)
      - HybridRatio (optional – 0–1 or 0–100%)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower_cols = {c.lower(): c for c in df.columns}
    if "login" in lower_cols and "Login" not in df.columns:
        df = df.rename(columns={lower_cols["login"]: "Login"})
    if "group" in lower_cols and "Group" not in df.columns:
        df = df.rename(columns={lower_cols["group"]: "Group"})
    if "hybridratio" in lower_cols and "HybridRatio" not in df.columns:
        df = df.rename(columns={lower_cols["hybridratio"]: "HybridRatio"})

    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")

    if "HybridRatio" in df.columns:
        out["HybridRatio"] = df["HybridRatio"].apply(normalise_ratio)
    else:
        out["HybridRatio"] = np.nan

    return out


def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switch_file(file) -> pd.DataFrame:
    """
    Optional book switch overrides.

    Expected columns (case-insensitive):
      - Login
      - FromType
      - ToType
      - ShiftEquity
      - HybridRatio (optional, % or fraction; interpreted AFTER switch)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(name_):
        for k, v in lower.items():
            if k == name_.lower():
                return v
        raise ValueError(f"Shift file must contain column '{name_}'")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce")

    if "hybridratio" in lower:
        out["HybridRatioShift"] = df[lower["hybridratio"]].apply(normalise_ratio)
    else:
        out["HybridRatioShift"] = np.nan

    return out


def build_report(summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label):
    """
    Merge all sources → per-account DataFrame.
    """
    base = closing_df.rename(
        columns={"Equity": "ClosingEquity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "OpeningEquity"})
    base = base.merge(open_renamed[["Login", "OpeningEquity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    # Join accounts (only accounts we care about)
    report = accounts_df.merge(base, on="Login", how="left")

    # Numeric safety
    numeric_cols = [
        "ClosingEquity",
        "OpeningEquity",
        "Deposit",
        "NET_DP_WD",
        "Withdrawal",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]
    for col in numeric_cols:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots from volume / 2
    report["ClosedLots"] = report["ClosedVolume"] / 2.0

    # Join switches (multiple accounts)
    if switch_df is not None and not switch_df.empty:
        report = report.merge(switch_df, on="Login", how="left")
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]
        report.drop(columns=["FromType", "ToType"], inplace=True)
        # Final book type after switch
        report["Type"] = np.where(
            report["ShiftToType"].notna(), report["ShiftToType"], report["Type"]
        )
        # HybridRatio: override with switch value if provided
        report["HybridRatio"] = np.where(
            report["HybridRatioShift"].notna(),
            report["HybridRatioShift"],
            report["HybridRatio"],
        )
    else:
        report["ShiftFromType"] = np.nan
        report["ShiftToType"] = np.nan
        report["ShiftEquity"] = np.nan
        report["HybridRatioShift"] = np.nan

    # Default Hybrid ratio = 0.5 if still NaN and Type == "Hybrid"
    report["HybridRatio"] = np.where(
        (report["Type"] == "Hybrid") & (report["HybridRatio"].isna()),
        0.5,
        report["HybridRatio"],
    )

    # NET PNL
    report["NET_PNL_USD"] = (
        report["ClosingEquity"] - report["OpeningEquity"] - report["NET_DP_WD"]
    )
    report["NET_PNL_PCT"] = np.where(
        report["OpeningEquity"].abs() > 0,
        (report["NET_PNL_USD"] / report["OpeningEquity"].abs()) * 100.0,
        0.0,
    )

    report["EOD_Closing_Date"] = eod_label

    cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "ClosedLots",
        "NET_DP_WD",
        "Currency",
        "OpeningEquity",
        "ClosingEquity",
        "NET_PNL_USD",
        "NET_PNL_PCT",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "HybridRatio",
        "ShiftFromType",
        "ShiftToType",
        "ShiftEquity",
        "EOD_Closing_Date",
    ]
    report = report[cols].sort_values("Login").reset_index(drop=True)
    return report


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate NET_PNL by book type, splitting accounts that switched
    between books using ShiftEquity.
    """
    rows = []

    for _, r in account_df.iterrows():
        net_pnl = r["NET_PNL_USD"]
        closed_lots = r["ClosedLots"]
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_eq = r["ShiftEquity"]
        from_type = r["ShiftFromType"]
        to_type = r["ShiftToType"]

        if pd.notna(shift_eq) and isinstance(from_type, str) and isinstance(to_type, str) and from_type != to_type:
            # Split P&L into "before" and "after" switch
            total = net_pnl
            pnl_new = r["ClosingEquity"] - shift_eq
            pnl_old = total - pnl_new

            # Old book contribution (no account count here)
            rows.append(
                dict(
                    Type=from_type,
                    Accounts=0,
                    Closed_Lots=0.0,
                    NET_PNL_USD=pnl_old,
                )
            )
            # New book contribution (account counted here)
            rows.append(
                dict(
                    Type=to_type,
                    Accounts=1,
                    Closed_Lots=closed_lots,
                    NET_PNL_USD=pnl_new,
                )
            )
        else:
            rows.append(
                dict(
                    Type=final_type,
                    Accounts=1,
                    Closed_Lots=closed_lots,
                    NET_PNL_USD=net_pnl,
                )
            )

    contrib = pd.DataFrame(rows)
    if contrib.empty:
        return pd.DataFrame(columns=["Type", "Accounts", "Closed_Lots", "NET_PNL_USD"])

    book = (
        contrib.groupby("Type", as_index=False)
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
    )
    return book


def compute_a_book_exposure_pnl(account_df: pd.DataFrame) -> float:
    """
    Estimate A-Book exposure P&L (for LP comparison), taking into account:

    - Pure A-Book accounts
    - Hybrid accounts using HybridRatio
    - Book switches using ShiftEquity
    """
    a_pnl = 0.0

    for _, r in account_df.iterrows():
        net_pnl = r["NET_PNL_USD"]
        opening = r["OpeningEquity"]
        closing = r["ClosingEquity"]
        shift_eq = r["ShiftEquity"]
        from_type = r["ShiftFromType"]
        to_type = r["ShiftToType"]
        final_type = r["Type"]
        ratio = r["HybridRatio"] if pd.notna(r["HybridRatio"]) else 0.5

        def add_book(book, pnl_segment):
            nonlocal a_pnl
            if book == "A-Book":
                a_pnl += pnl_segment
            elif book == "Hybrid":
                a_pnl += pnl_segment * ratio

        if pd.notna(shift_eq) and isinstance(from_type, str) and isinstance(to_type, str) and from_type != to_type:
            total = net_pnl
            pnl_new = closing - shift_eq
            pnl_old = total - pnl_new

            add_book(from_type, pnl_old)
            add_book(to_type, pnl_new)
        else:
            add_book(final_type, net_pnl)

    return a_pnl


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        account_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Closed_Lots=("ClosedLots", "sum"),
            NET_DP_WD=("NET_DP_WD", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
            Opening_Equity=("OpeningEquity", "sum"),
            Closing_Equity=("ClosingEquity", "sum"),
        )
        .reset_index()
    )
    return grouped


def load_lp_breakdown(file) -> pd.DataFrame:
    """
    LP breakdown file (multi-LP).
    Expected columns (case-insensitive):
      - LPName
      - OpeningEquity
      - ClosingEquity
      - NetDPWD
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col):
        for k, v in lower.items():
            if k == col.lower():
                return v
        raise ValueError(f"LP breakdown must contain column '{col}'")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity")], errors="coerce").fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity")], errors="coerce").fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd")], errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# =====================================================================
# SIDEBAR – LP PANEL
# =====================================================================

with st.sidebar:
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.write(
        "Upload a LP breakdown file (**multi-LP**) or leave it empty.\n\n"
        "Brokerage P&L = **Total LP P&L − Client A-Book P&L**."
    )
    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_breakdown",
    )

# =====================================================================
# 1. UPLOAD MT5 FILES
# =====================================================================

st.markdown("### 1. Upload MT5 reports")
st.markdown(
    '<div class="section-subtitle">Sheet-1 summary, two daily reports (opening & closing), '
    'book-account lists and optional book switch overrides.</div>',
    unsafe_allow_html=True,
)

eod_label = st.text_input(
    "EOD Closing Equity Date (stored in reports)", value="", placeholder="e.g. 2025-12-06 EOD"
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)
c5, c6, c7 = st.columns(3)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="MT5 summary with NET DP/WD (col E), volume (H), commission (I), swap (K).",
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
    a_book_file = st.file_uploader(
        "A-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="abook",
        help="Columns: Login, optional Group, optional HybridRatio.",
    )
with c6:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="bbook",
    )
with c7:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        key="hybrid",
        help="Columns: Login, optional Group, optional HybridRatio (% or fraction).",
    )

st.markdown("#### Book switch overrides (optional – multiple accounts)")
st.markdown(
    '<div class="section-subtitle">'
    "Upload switch file with columns: **Login, FromType, ToType, ShiftEquity, optional HybridRatio** "
    "(HybridRatio is the A-Book percentage when switching into Hybrid, e.g. 40 → 40% A-Book / 60% B-Book)."
    "</div>",
    unsafe_allow_html=True,
)
switch_file = st.file_uploader(
    "Upload book switch file",
    type=["xlsx", "xls", "csv"],
    key="switch",
)

st.markdown("---")

# =====================================================================
# MAIN ACTION
# =====================================================================

if st.button("🚀 Generate report"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload **Summary + Closing Equity + Opening Equity** files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: **A-Book, B-Book, Hybrid** account files.")
    elif not eod_label:
        st.error("Please enter the **EOD Closing Equity Date** text.")
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

                switch_df = load_switch_file(switch_file) if switch_file is not None else None

                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)
                a_book_exposure_pnl = compute_a_book_exposure_pnl(account_df)

                # LP breakdown (optional)
                if lp_file is not None:
                    lp_df = load_lp_breakdown(lp_file)
                    total_lp_pnl = lp_df["LP_PnL"].sum()
                else:
                    lp_df = pd.DataFrame(columns=["LPName", "OpeningEquity", "ClosingEquity", "NetDPWD", "LP_PnL"])
                    total_lp_pnl = 0.0

            # =================================================================
            # 2. HIGH-LEVEL OVERVIEW
            # =================================================================
            st.markdown("### 2. High-level snapshot of today's client P&L")

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["ClosedLots"].sum()
            net_client_pnl = account_df["NET_PNL_USD"].sum()
            wins = account_df[account_df["NET_PNL_USD"] > 0]["NET_PNL_USD"].sum()
            losses = account_df[account_df["NET_PNL_USD"] < 0]["NET_PNL_USD"].sum()
            denom = abs(wins) + abs(losses)
            win_pct = (abs(wins) / denom * 100.0) if denom > 0 else 0.0
            loss_pct = (abs(losses) / denom * 100.0) if denom > 0 else 0.0

            with k1:
                st.markdown('<div class="metric-card"><div class="metric-label">Active accounts</div>'
                            f'<div class="metric-value">{int(total_clients):,}</div>'
                            '<div class="metric-pill">Unique MT5 logins</div></div>',
                            unsafe_allow_html=True)
            with k2:
                st.markdown('<div class="metric-card"><div class="metric-label">Closed lots</div>'
                            f'<div class="metric-value">{total_closed_lots:,.2f}</div>'
                            '<div class="metric-pill">From summary sheet (H/2)</div></div>',
                            unsafe_allow_html=True)
            with k3:
                st.markdown('<div class="metric-card"><div class="metric-label">Net client P&L</div>'
                            f'<div class="metric-value">{net_client_pnl:,.2f}</div>'
                            '<div class="metric-pill">Closing – Opening – NET DP/WD</div></div>',
                            unsafe_allow_html=True)
            with k4:
                st.markdown('<div class="metric-card"><div class="metric-label">Profit vs loss mix</div>'
                            f'<div class="metric-value">P {win_pct:,.1f}% / L {loss_pct:,.1f}%</div>'
                            '<div class="metric-pill">By client net P&L</div></div>',
                            unsafe_allow_html=True)

            # =================================================================
            # 3. FULL ACCOUNT TABLE
            # =================================================================
            st.markdown("### 3. Full account P&L")
            st.markdown(
                '<div class="section-subtitle">Per-account view including opening & closing equity, '
                'NET DP/WD, book type, Hybrid ratio and optional switch information.</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(account_df, use_container_width=True)

            # =================================================================
            # 4. GROUP-WISE SUMMARY
            # =================================================================
            st.markdown("### 4. Group-wise summary")
            st.dataframe(group_df, use_container_width=True)

            # =================================================================
            # 5. A-BOOK / B-BOOK / HYBRID SUMMARY
            # =================================================================
            st.markdown("### 5. A-Book / B-Book / Hybrid summary")
            st.dataframe(book_df, use_container_width=True)

            client_total_book_pnl = book_df["NET_PNL_USD"].sum()
            st.markdown(
                f"Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                f"**{client_total_book_pnl:,.2f}**"
            )

            # =================================================================
            # 6. TOP ACCOUNTS (GAINERS / LOSERS)
            # =================================================================
            st.markdown("### 6. Top 10 accounts (gainers & losers)")
            gcol1, gcol2 = st.columns(2)

            cols_show = [
                "Login",
                "Group",
                "OrigType",
                "Type",
                "OpeningEquity",
                "ClosingEquity",
                "NET_PNL_USD",
                "NET_PNL_PCT",
                "ClosedLots",
                "NET_DP_WD",
            ]

            with gcol1:
                st.markdown("**Top 10 gainer accounts**")
                gainers = account_df.sort_values("NET_PNL_USD", ascending=False).head(10)
                st.dataframe(gainers[cols_show], use_container_width=True)

            with gcol2:
                st.markdown("**Top 10 loser accounts**")
                losers = account_df.sort_values("NET_PNL_USD", ascending=True).head(10)
                st.dataframe(losers[cols_show], use_container_width=True)

            # =================================================================
            # 7. A-BOOK VS LP BROKERAGE
            # =================================================================
            st.markdown("### 7. A-Book vs LP brokerage")

            st.markdown(
                f"- Client A-Book P&L (including Hybrid ratios & switches): "
                f"**{a_book_exposure_pnl:,.2f}**"
            )

            if not lp_df.empty:
                st.markdown("#### LP breakdown (from file)")
                # IMPORTANT: no Brokerage_PnL column shown here
                st.dataframe(lp_df[["LPName", "OpeningEquity", "ClosingEquity", "NetDPWD", "LP_PnL"]],
                             use_container_width=True)

                st.markdown(f"- Total LP P&L: **{total_lp_pnl:,.2f}**")

                brokerage_pnl = total_lp_pnl - a_book_exposure_pnl
                st.markdown(
                    f"- Brokerage P&L (Total LP − Client A-Book): **{brokerage_pnl:,.2f}**"
                )
            else:
                st.info("No LP breakdown file uploaded. You can still see client A-Book P&L above.")

            # =================================================================
            # 8. DOWNLOAD EXCEL
            # =================================================================
            st.markdown("### 8. Download Excel report")
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # LP sheet if available
                if not lp_df.empty:
                    lp_df.to_excel(writer, index=False, sheet_name="LPs")

                # Compact A-Book vs LP sheet
                abook_lp_df = pd.DataFrame(
                    {
                        "Metric": [
                            "Client_A_Book_PnL",
                            "Total_LP_PnL",
                            "Brokerage_PnL (LP - A_Book)",
                        ],
                        "Value": [
                            a_book_exposure_pnl,
                            total_lp_pnl,
                            total_lp_pnl - a_book_exposure_pnl,
                        ],
                    }
                )
                abook_lp_df.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
