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

# Light / premium-style CSS
st.markdown(
    """
    <style>
    /* Global */
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
    /* Hero */
    .hero-card {
        background: linear-gradient(135deg, #111827, #1f2937);
        color: #f9fafb;
        border-radius: 22px;
        padding: 1.8rem 2.2rem 1.6rem 2.2rem;
        box-shadow: 0 18px 50px rgba(15, 23, 42, 0.45);
        position: relative;
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
        max-width: 580px;
    }

    /* Metric cards */
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

    /* Section titles */
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

    /* Dataframes borderless header */
    .stDataFrame tbody tr:nth-child(even) {
        background-color: #f9fafb;
    }

    /* Sidebar panel */
    [data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e5e7eb;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# HERO
# ============================================================

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

def _safe_read_excel(file, header_guess=0):
    try:
        return pd.read_excel(file, header=header_guess)
    except Exception:
        file.seek(0)
        return pd.read_excel(file)


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions (MT5 "Summary" export).

    We use fixed column positions (0-based) for reliability:
        0: Login
        4: NET DP/WD (E)
        5: Credit (F)
        7: Closed volume (H)
        8: Commission (I)
        10: Swap (K)
    """
    # Many MT5 exports have 2 header lines – try with header=2 first.
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
        df.groupby("Login", as_index=False)[
            ["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily reports (EOD equity snapshots).
    Expect columns: Login, Equity, Currency.
    """
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
    equity_col = find_col(["equity"], 9)  # many MT5 reports have equity around column J
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
    """Read a book-accounts mapping file: expect Login and optional Group."""
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
    """
    Book switch overrides – multiple accounts.

    Expected columns (case-insensitive):
        Login, FromType, ToType, ShiftEquity, optional HybridRatio

    HybridRatio can be 0.4 (40%) or 40 (we convert to 0-1 range).
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

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

    # HybridRatio is optional
    if any(k.startswith("hybridratio") for k in lower.keys()):
        hr_col = pick("hybridratio")
        hr = pd.to_numeric(df[hr_col], errors="coerce")
        # If user wrote percentages > 1, convert to fraction
        hr = hr.apply(lambda x: x / 100.0 if x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan

    return out


def build_account_report(
    summary_df, closing_df, opening_df, accounts_df, eod_label
) -> pd.DataFrame:
    """
    Merge all sources and calculate account-level metrics.
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # Fill numeric NaNs
    for col in [
        "Closing Equity",
        "Opening Equity",
        "NET_DP_WD",
        "Credit",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots from summary H column
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # NET PNL USD = Closing - Opening - NET DP/WD - Credit
    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["NET_DP_WD"]
        - report["Credit"]
    )

    # NET PNL %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    report["EOD Closing Equity Date"] = eod_label

    # Reorder
    final_cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "Closed Lots",
        "NET_DP_WD",
        "Credit",
        "Currency",
        "Opening Equity",
        "Closing Equity",
        "NET PNL USD",
        "NET PNL %",
        "Commission",
        "Swap",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report


def build_book_summary(account_df: pd.DataFrame, switch_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build A-Book / B-Book / Hybrid summary, taking book switches into account.

    Uses the HybridRatio logic described above.
    """
    rows = []
    # Map login -> switch info
    switch_map = {}
    if switch_df is not None and not switch_df.empty:
        for _, r in switch_df.iterrows():
            switch_map[int(r["Login"])] = r

    for _, r in account_df.iterrows():
        login = int(r["Login"])
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        final_type = str(r["Type"])
        orig_type = str(r["OrigType"])

        if login in switch_map:
            sw = switch_map[login]
            from_type = str(sw["FromType"])
            to_type = str(sw["ToType"])
            shift_eq = float(sw["ShiftEquity"])
            hybrid_ratio = sw.get("HybridRatio", np.nan)
            if pd.isna(hybrid_ratio):
                hybrid_ratio = 0.5  # default 50/50 for Hybrid if not specified

            pnl_after = r["Closing Equity"] - shift_eq
            pnl_before = net_pnl - pnl_after

            # Before switch PNL -> from_type
            rows.append(
                {
                    "Type": from_type,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_before,
                }
            )

            # After switch
            if to_type.lower() == "hybrid":
                # Split after PNL between A and B using HybridRatio
                pnl_a = pnl_after * hybrid_ratio
                pnl_b = pnl_after * (1 - hybrid_ratio)

                rows.append(
                    {
                        "Type": "A-Book",
                        "Accounts": 1,
                        "Closed_Lots": closed_lots * hybrid_ratio,
                        "NET_PNL_USD": pnl_a,
                    }
                )
                rows.append(
                    {
                        "Type": "B-Book",
                        "Accounts": 0,
                        "Closed_Lots": closed_lots * (1 - hybrid_ratio),
                        "NET_PNL_USD": pnl_b,
                    }
                )
            else:
                # Normal switch A<->B or Hybrid<->A/B
                rows.append(
                    {
                        "Type": to_type,
                        "Accounts": 1,
                        "Closed_Lots": closed_lots,
                        "NET_PNL_USD": pnl_after,
                    }
                )
        else:
            # No switch
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )

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
    """
    LP breakdown file: can contain multiple LPs.

    Expected columns (case-insensitive):
        LPName, OpeningEquity, ClosingEquity, NetDPWD
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

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


# ============================================================
# SIDEBAR – LP PANEL
# ============================================================

with st.sidebar:
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.write(
        "Upload an LP breakdown file or leave it empty. "
        "Brokerage P&L = Total LP P&L – client A-Book P&L."
    )
    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)", type=["xlsx", "xls", "csv"], key="lp_file"
    )


# ============================================================
# MAIN – FILE UPLOADS
# ============================================================

st.markdown(
    '<div class="section-title"><span class="badge">1</span>'
    '<span>Upload MT5 reports</span></div>',
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
        help="MT5 Summary report (used for NET DP/WD, Credit, Closed volume, Commission, Swap).",
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
        help="File with columns: Login, optional Group.",
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
    )

st.markdown(
    """
    <div class="section-title"><span class="badge">2</span>
    <span>Book switch overrides (optional – multiple accounts)</span></div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "Upload a switch file with columns "
    "`Login, FromType, ToType, ShiftEquity, optional HybridRatio`.<br>"
    "HybridRatio is the **A-Book percentage** after switching to Hybrid "
    "(e.g. 40 means 40% A-Book / 60% B-Book).",
    unsafe_allow_html=True,
)
switch_file = st.file_uploader(
    "Upload book switch file", type=["xlsx", "xls", "csv"], key="switch"
)

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

                # Switch file (optional)
                switch_df = None
                if switch_file is not None:
                    switch_df = load_switch_file(switch_file)

                # Build account-level report
                account_df = build_account_report(
                    summary_df, closing_df, opening_df, accounts_df, eod_label
                )
                # Build summaries
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df, switch_df if switch_df is not None else pd.DataFrame())

            # ====================================================
            # OVERVIEW KPIs
            # ====================================================

            st.markdown(
                '<div class="section-title"><span class="badge">3</span>'
                '<span>High-level snapshot of today\'s client P&L</span></div>',
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
                st.markdown('<div class="metric-label">Active accounts</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(total_clients):,}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_closed_lots:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs loss mix</div>', unsafe_allow_html=True)
                profit_abs = float(total_profit)
                loss_abs = float(abs(total_loss))
                denom = profit_abs + loss_abs
                if denom > 0:
                    profit_pct = profit_abs / denom * 100.0
                    loss_pct = loss_abs / denom * 100.0
                else:
                    profit_pct = loss_pct = 0.0
                st.markdown(
                    f'<div class="metric-value">P {profit_pct:.1f}% / L {loss_pct:.1f}%</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            # ====================================================
            # FULL ACCOUNT P&L
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">4</span>'
                '<span>Full account P&L</span></div>',
                unsafe_allow_html=True,
            )
            st.dataframe(account_df, use_container_width=True)

            # ====================================================
            # BOOK SUMMARY
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">5</span>'
                '<span>A-Book / B-Book / Hybrid summary</span></div>',
                unsafe_allow_html=True,
            )
            st.dataframe(book_df, use_container_width=True)

            pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            pnl_h = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()
            total_client_pnl = pnl_a + pnl_b + pnl_h
            client_result = "profit" if total_client_pnl >= 0 else "loss"
            st.markdown(
                f"**Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                f"{total_client_pnl:,.2f} ({client_result})**"
            )

            # ====================================================
            # GROUP-WISE SUMMARY (TOP GAINERS / LOSERS)
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">6</span>'
                '<span>Group-wise summary</span></div>',
                unsafe_allow_html=True,
            )

            gcol1, gcol2 = st.columns(2)
            with gcol1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                    use_container_width=True,
                )
            with gcol2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                    use_container_width=True,
                )

            # ====================================================
            # A-BOOK vs LP BROKERAGE
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">7</span>'
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
                # IMPORTANT: do not show Brokerage_PnL per LP anymore
                st.dataframe(
                    lp_table[["LPName", "OpeningEquity", "ClosingEquity", "NetDPWD", "LP_PnL"]],
                    use_container_width=True,
                )
            else:
                st.info(
                    "No LP breakdown file uploaded. You can still use the Excel output "
                    "to manually fill LP figures later."
                )

            st.markdown(f"- Total LP P&L: **{total_lp_pnl:,.2f}**")
            brokerage_pnl = total_lp_pnl - pnl_a
            st.markdown(
                f"- Brokerage P&L (Total LP – A-Book): **{brokerage_pnl:,.2f}**"
            )

            # ====================================================
            # DOWNLOAD EXCEL
            # ====================================================
            st.markdown(
                '<div class="section-title"><span class="badge">8</span>'
                '<span>Download Excel report</span></div>',
                unsafe_allow_html=True,
            )

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # LP sheet (if provided)
                if lp_file is not None and lp_table is not None:
                    lp_table.to_excel(writer, index=False, sheet_name="LP")

                # A-book vs LP summary sheet
                abook_lp_df = pd.DataFrame(
                    {
                        "Metric": [
                            "Client_A_Book_PnL",
                            "Total_LP_PnL",
                            "Brokerage_PnL_(TotalLP_minus_Abook)",
                        ],
                        "Value": [
                            pnl_a,
                            total_lp_pnl,
                            brokerage_pnl,
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
