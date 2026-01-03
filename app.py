# app.py
# ----------------------------------------------
# FX Client P&L Monitoring Tool
# ----------------------------------------------
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ======================================================
# PAGE & THEME
# ======================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS – dark hero, glass cards, subtle animations
st.markdown(
    """
<style>
:root {
    --bg-main: #020617;
    --bg-card: rgba(15,23,42,0.9);
    --bg-card-light: #0b1220;
    --accent: #38bdf8;
    --accent-soft: rgba(56,189,248,0.15);
    --border-subtle: rgba(148,163,184,0.35);
    --danger: #fb7185;
    --success: #22c55e;
    --text-main: #e5e7eb;
    --text-muted: #9ca3af;
}
body, .main {
    background-color: #020617;
    color: var(--text-main);
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 0.5rem;
    padding-bottom: 2.5rem;
}
.hero {
    background: radial-gradient(circle at top left, #1d4ed8 0, #020617 55%);
    border-radius: 24px;
    padding: 1.75rem 2.25rem 1.9rem 2.25rem;
    border: 1px solid rgba(148,163,184,0.35);
    box-shadow: 0 30px 120px rgba(15,23,42,0.9);
    position: relative;
    overflow: hidden;
}
.hero-badge {
    font-size: 0.75rem;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--accent);
    background: rgba(15,23,42,0.75);
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    border: 1px solid rgba(56,189,248,0.4);
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
}
.hero-title {
    font-size: 2.2rem;
    font-weight: 650;
    margin-top: 0.9rem;
}
.hero-sub {
    color: var(--text-muted);
    max-width: 48rem;
    font-size: 0.95rem;
}
.metric-row {
    margin-top: 1.2rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem;
}
.metric-card {
    flex: 1 1 160px;
    min-width: 0;
    background: linear-gradient(145deg,#020617,#020617 55%,#0b1120);
    border-radius: 16px;
    padding: 0.9rem 1rem;
    border: 1px solid rgba(148,163,184,0.45);
}
.metric-label {
    font-size: 0.75rem;
    letter-spacing: .08em;
    color: var(--text-muted);
    text-transform: uppercase;
}
.metric-value {
    font-size: 1.25rem;
    font-weight: 650;
    margin-top: 0.2rem;
}
.metric-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    font-size: 0.7rem;
    background: var(--accent-soft);
    color: #e0f2fe;
}
.section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin-bottom: 0.2rem;
}
.section-subtitle {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 0.7rem;
}
.section-card {
    background: var(--bg-card);
    border-radius: 18px;
    padding: 1.15rem 1.3rem;
    border: 1px solid var(--border-subtle);
    box-shadow: 0 18px 60px rgba(15,23,42,0.6);
}
.section-card-light {
    background: var(--bg-card-light);
    border-radius: 18px;
    padding: 1.1rem 1.2rem;
    border: 1px solid rgba(51,65,85,0.9);
}
.stDataFrame, .stTable {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid rgba(51,65,85,0.85);
}
.sidebar .sidebar-content {
    background-color: #020617;
}
</style>
""",
    unsafe_allow_html=True,
)

# ======================================================
# HERO HEADER
# ======================================================
st.markdown(
    """
<div class="hero">
  <div class="hero-badge">
    <span>📈 FX client book monitor</span>
  </div>
  <div class="hero-title">
    Client P&amp;L Monitoring Tool
  </div>
  <p class="hero-sub">
    Upload your MT5 exports once a day to see account-wise, group-wise and
    book-wise P&amp;L. Includes A-Book vs B-Book comparison and multi-LP
    brokerage view.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

st.write("")  # spacing

# ======================================================
# SIDEBAR – LP PANEL
# ======================================================
with st.sidebar:
    st.markdown("### 🏛️ A-Book LP P&L (optional)")
    st.caption(
        "Upload a **LP breakdown file** or leave empty. "
        "Brokerage = total LP P&L − client A-Book P&L."
    )

    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_breakdown",
        help=(
            "Expected columns (any order): "
            "`LPName`, `OpeningEquity`, `ClosingEquity`, `NetDPWD`."
        ),
    )

    st.markdown("---")
    st.caption(
        "If you don't upload a file you can still fill a single LP manually "
        "later on the results page."
    )


# ======================================================
# HELPERS – DATA LOADING
# ======================================================
def read_any_table(file, header=0):
    """Robust helper to read CSV/XLS/XLSX."""
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    # default to excel
    try:
        return pd.read_excel(file, header=header)
    except Exception:
        return pd.read_excel(file)


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions (MT5 built-in report).

    We use fixed positions by column index (0-based):

      0: Login
      4: NET DP/WD        (E)   -> already net of deposits & withdrawals
      7: Closed volume    (H)   -> we divide by 2 to get closed lots
      8: Commission       (I)
      10: Swap            (K)
    """
    raw = read_any_table(file, header=2)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must have at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")

    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["NET_DP_WD", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily MT5 reports (EOD equity snapshots).

    We search for likely column names for login & equity to be robust to
    different templates.
    """
    df = read_any_table(file, header=2)
    cols_lower = [str(c).strip().lower() for c in df.columns]

    def find_col(options, default_idx=None):
        for opt in options:
            if opt in cols_lower:
                return df.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(df.columns):
            return df.columns[default_idx]
        raise ValueError(f"Could not find any of {options!r} in equity report.")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)  # often column J
    currency_col = None
    for key in ["currency", "curr", "ccy"]:
        if key in cols_lower:
            currency_col = df.columns[cols_lower.index(key)]
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
    """Read an accounts mapping (Login + optional Group)."""
    df = read_any_table(file, header=0)
    lower = {c.lower(): c for c in df.columns}

    if "login" in lower and "Login" not in df.columns:
        df = df.rename(columns={lower["login"]: "Login"})
    if "group" in lower and "Group" not in df.columns:
        df = df.rename(columns={lower["group"]: "Group"})

    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    """Attach OrigType / Type = given book_type."""
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switch_file(file) -> pd.DataFrame:
    """
    Optional multi-account switch configuration.

    Expected columns (case-insensitive):

      - Login        (account number)
      - FromType     ("A-Book" / "B-Book" / "Hybrid")
      - ToType       (same set)
      - ShiftEquity  (equity at the moment of switch)
      - HybridShareA (0-1, optional, used only when ToType == "Hybrid")

    Example row:
      100875, B-Book, A-Book, 15000, 0.50
    """
    df = read_any_table(file, header=0)
    lower = {c.lower(): c for c in df.columns}

    def pick(name, required=True, default=None):
        key = name.lower()
        if key in lower:
            return df[lower[key]]
        if required:
            raise ValueError(f"Switch file must contain column '{name}'.")
        return default

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(pick("Login"), errors="coerce").astype("Int64")
    out["FromType"] = pick("FromType").astype(str)
    out["ToType"] = pick("ToType").astype(str)
    out["ShiftEquity"] = pd.to_numeric(pick("ShiftEquity"), errors="coerce")
    out["HybridShareA"] = pd.to_numeric(
        pick("HybridShareA", required=False, default=np.nan),
        errors="coerce",
    )
    return out


def build_account_report(
    summary_df: pd.DataFrame,
    closing_df: pd.DataFrame,
    opening_df: pd.DataFrame,
    accounts_df: pd.DataFrame,
    eod_label: str,
) -> pd.DataFrame:
    """
    Merge all MT5 sources into a full account-level report.

    NET PNL USD = Closing Equity − Opening Equity − NET DP/WD
    Closed Lots = ClosedVolume / 2
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()

    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    df = accounts_df.merge(base, on="Login", how="left")

    for col in [
        "Closing Equity",
        "Opening Equity",
        "NET_DP_WD",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        else:
            df[col] = 0.0

    df["Closed Lots"] = df["ClosedVolume"] / 2.0
    df["NET PNL USD"] = df["Closing Equity"] - df["Opening Equity"] - df["NET_DP_WD"]
    df["NET PNL %"] = np.where(
        df["Opening Equity"].abs() > 0,
        (df["NET PNL USD"] / df["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    df["EOD Closing Equity Date"] = eod_label

    ordered_cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "Closed Lots",
        "NET_DP_WD",
        "Currency",
        "Opening Equity",
        "Closing Equity",
        "NET PNL USD",
        "NET PNL %",
        "Commission",
        "Swap",
        "EOD Closing Equity Date",
    ]
    return df[ordered_cols].sort_values("Login").reset_index(drop=True)


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        account_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Closed_Lots=("Closed Lots", "sum"),
            NET_DP_WD=("NET_DP_WD", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
            Opening_Equity=("Opening Equity", "sum"),
            Closing_Equity=("Closing Equity", "sum"),
        )
        .reset_index()
    )
    return grouped


def build_book_summary(account_df: pd.DataFrame, switch_df: pd.DataFrame | None):
    """
    Book-level P&L, taking account switches into account.

    For accounts without switches:
        contribution goes fully to their OrigType.

    For switches (one row per login):

      total_pnl  = NET PNL USD
      post_pnl   = Closing Equity − ShiftEquity
      pre_pnl    = total_pnl − post_pnl

      • post_pnl belongs to the NEW book (ToType)
      • pre_pnl  belongs to the OLD book (FromType)

    For ToType == "Hybrid" we additionally use HybridShareA (0-1) to split the
    post-switch P&L between A-Book and B-Book:

      A-Book += post_pnl * HybridShareA
      B-Book += post_pnl * (1 − HybridShareA)

    The “Hybrid” row itself only reflects accounts count & lots (P&L is already
    distributed into A/B).
    """
    rows = []

    if switch_df is None or switch_df.empty:
        switch_lookup = {}
    else:
        switch_lookup = {
            int(r.Login): r for _, r in switch_df.set_index("Login").iterrows()
        }

    for _, r in account_df.iterrows():
        login = int(r["Login"])
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        orig_type = r["OrigType"]
        final_type = r["Type"]
        closing_eq = float(r["Closing Equity"])
        opening_eq = float(r["Opening Equity"])

        sw = switch_lookup.get(login)

        # No switch configured – simple case
        if sw is None:
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1.0,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
            continue

        from_type = sw.FromType
        to_type = sw.ToType
        shift_eq = float(sw.ShiftEquity)

        total_pnl = net_pnl
        post_pnl = closing_eq - shift_eq
        pre_pnl = total_pnl - post_pnl

        # 1) P&L before switch -> old book
        rows.append(
            {
                "Type": from_type,
                "Accounts": 0.0,
                "Closed_Lots": 0.0,
                "NET_PNL_USD": pre_pnl,
            }
        )

        # 2) After switch
        if to_type == "Hybrid":
            share_a = float(sw.HybridShareA) if not pd.isna(sw.HybridShareA) else 0.5
            share_a = max(0.0, min(1.0, share_a))
            share_b = 1.0 - share_a

            if share_a > 0:
                rows.append(
                    {
                        "Type": "A-Book",
                        "Accounts": share_a,  # fractional exposure
                        "Closed_Lots": closed_lots * share_a,
                        "NET_PNL_USD": post_pnl * share_a,
                    }
                )
            if share_b > 0:
                rows.append(
                    {
                        "Type": "B-Book",
                        "Accounts": share_b,
                        "Closed_Lots": closed_lots * share_b,
                        "NET_PNL_USD": post_pnl * share_b,
                    }
                )
            # Hybrid row – only headcount / lots if you want to see clients on hybrid
            rows.append(
                {
                    "Type": "Hybrid",
                    "Accounts": 1.0,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": 0.0,  # already split into A/B
                }
            )
        else:
            # Simple switch A <-> B
            rows.append(
                {
                    "Type": to_type,
                    "Accounts": 1.0,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": post_pnl,
                }
            )

    contrib = pd.DataFrame(rows)
    book = (
        contrib.groupby("Type", as_index=False)
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
        .sort_values("Type")
    )
    return book


def parse_lp_file(lp_file: BytesIO) -> pd.DataFrame:
    """
    LP breakdown input.

    Required columns (case insensitive):
      - LPName
      - OpeningEquity
      - ClosingEquity
      - NetDPWD
    """
    df = read_any_table(lp_file, header=0)
    lower = {c.lower(): c for c in df.columns}

    def pick(name):
        key = name.lower()
        if key not in lower:
            raise ValueError(f"LP file must contain column '{name}'.")
        return df[lower[key]]

    out = pd.DataFrame()
    out["LPName"] = pick("LPName").astype(str)
    out["OpeningEquity"] = pd.to_numeric(
        pick("OpeningEquity"), errors="coerce"
    ).fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(
        pick("ClosingEquity"), errors="coerce"
    ).fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(pick("NetDPWD"), errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# ======================================================
# MAIN UI – STEP 1: UPLOAD MT5 REPORTS
# ======================================================
st.markdown(
    '<div class="section-card" style="margin-top:0.9rem;">',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-title">1. Upload MT5 reports</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-subtitle">'
    "We need the daily **Summary / Transactions** (sheet 1), **Closing equity** "
    "(sheet 2), **Opening equity** (sheet 3) and the account-to-book mapping "
    "files for A-Book / B-Book / Hybrid."
    "</div>",
    unsafe_allow_html=True,
)

eod_label = st.text_input(
    "EOD Closing Equity Date (this text is stored inside the Excel report)",
    placeholder="e.g. 2025-12-06 EOD",
)

c1, c2 = st.columns(2)
with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        help="MT5 summary report with NET DP/WD, closed volume, commission & swap.",
        key="summary",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        help="Daily MT5 report with final EOD equity.",
        key="closing",
    )

c3, c4, c5 = st.columns(3)
with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        help="Daily MT5 report with previous EOD equity.",
        key="opening",
    )
with c4:
    abook_file = st.file_uploader(
        "A-Book accounts (Login → Group)",
        type=["xlsx", "xls", "csv"],
        help="Login & optional Group for A-Book clients.",
        key="abook",
    )
with c5:
    bbook_file = st.file_uploader(
        "B-Book accounts (Login → Group)",
        type=["xlsx", "xls", "csv"],
        help="Login & optional Group for B-Book clients.",
        key="bbook",
    )

c6, c7 = st.columns(2)
with c6:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        help="Login & optional Group for hybrid-risk clients.",
        key="hybrid",
    )
with c7:
    switch_file = st.file_uploader(
        "Account switch config (optional)",
        type=["xlsx", "xls", "csv"],
        help=(
            "Columns: Login, FromType, ToType, ShiftEquity, HybridShareA. "
            "Use this when some accounts moved book during the day."
        ),
        key="switch",
    )

st.markdown("</div>", unsafe_allow_html=True)  # end section-card

st.write("")

# ======================================================
# ACTION BUTTON
# ======================================================
run_button = st.button("🚀 Generate report", type="primary")


# ======================================================
# MAIN PROCESSING
# ======================================================
if run_button:
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary, Closing Equity and Opening Equity files.")
    elif not (abook_file or bbook_file or hybrid_file):
        st.error("Please upload at least one account mapping file (A-Book / B-Book / Hybrid).")
    elif not eod_label:
        st.error("Please enter the EOD closing equity date text.")
    else:
        try:
            # ------------------ Load core data ------------------
            with st.spinner("Reading MT5 files and building the account report..."):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)

                account_frames = []
                if abook_file:
                    account_frames.append(load_book_accounts(abook_file, "A-Book"))
                if bbook_file:
                    account_frames.append(load_book_accounts(bbook_file, "B-Book"))
                if hybrid_file:
                    account_frames.append(load_book_accounts(hybrid_file, "Hybrid"))

                accounts_df = pd.concat(account_frames, ignore_index=True)
                # If same login appears in multiple files, keep first
                accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

                switch_df = None
                if switch_file is not None:
                    switch_df = load_switch_file(switch_file)

                account_df = build_account_report(
                    summary_df, closing_df, opening_df, accounts_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df, switch_df)

            # ==================================================
            # KPI / OVERVIEW
            # ==================================================
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl_total = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            st.markdown(
                '<div class="section-card-light" style="margin-top:0.4rem;">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">2. Overview</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-subtitle">High-level snapshot of today\'s client P&amp;L.</div>',
                unsafe_allow_html=True,
            )

            st.markdown('<div class="metric-row">', unsafe_allow_html=True)
            # Clients
            st.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">Active accounts</div>
                    <div class="metric-value">{int(total_clients):,}</div>
                    <div class="metric-pill">Unique MT5 logins</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Closed lots
            st.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">Closed lots</div>
                    <div class="metric-value">{total_closed_lots:,.2f}</div>
                    <div class="metric-pill">From summary sheet (H/2)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Net PNL
            pnl_color = "var(--success)" if net_pnl_total >= 0 else "var(--danger)"
            st.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">Net client P&amp;L</div>
                    <div class="metric-value" style="color:{pnl_color}">{net_pnl_total:,.2f}</div>
                    <div class="metric-pill">Closing − Opening − NET DP/WD</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Profit / loss mix
            profit_abs = float(total_profit)
            loss_abs = float(abs(total_loss))
            denom = profit_abs + loss_abs
            if denom > 0:
                profit_pct = profit_abs / denom * 100.0
                loss_pct = loss_abs / denom * 100.0
            else:
                profit_pct = loss_pct = 0.0
            st.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">Profit vs loss mix</div>
                    <div class="metric-value">
                        P {profit_pct:.1f}% / L {loss_pct:.1f}%
                    </div>
                    <div class="metric-pill">By client net P&amp;L</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)  # metric-row
            st.markdown("</div>", unsafe_allow_html=True)  # section-card-light

            st.write("")

            # ==================================================
            # Full account P&L
            # ==================================================
            st.markdown(
                '<div class="section-card-light">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">3. Full account P&amp;L</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "You can filter, sort and export this table from the download button "
                "below."
            )
            st.dataframe(account_df, use_container_width=True, height=430)
            st.markdown("</div>", unsafe_allow_html=True)

            st.write("")

            # ==================================================
            # Top gainers / losers
            # ==================================================
            st.markdown(
                '<div class="section-card-light">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">4. Top accounts</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-subtitle">By net P&amp;L for today.</div>',
                unsafe_allow_html=True,
            )

            cols = [
                "Login",
                "Group",
                "OrigType",
                "Type",
                "Opening Equity",
                "Closing Equity",
                "NET PNL USD",
                "Closed Lots",
                "NET_DP_WD",
            ]

            left, right = st.columns(2)
            with left:
                st.markdown("**Top 10 gainer accounts**")
                gainers = (
                    account_df.sort_values("NET PNL USD", ascending=False)
                    .head(10)[cols]
                    .reset_index(drop=True)
                )
                st.dataframe(gainers, use_container_width=True)
            with right:
                st.markdown("**Top 10 loser accounts**")
                losers = (
                    account_df.sort_values("NET PNL USD", ascending=True)
                    .head(10)[cols]
                    .reset_index(drop=True)
                )
                st.dataframe(losers, use_container_width=True)

            st.markdown("</div>", unsafe_allow_html=True)

            st.write("")

            # ==================================================
            # Group-wise & book-wise summary
            # ==================================================
            st.markdown(
                '<div class="section-card-light">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">5. Group &amp; book summaries</div>',
                unsafe_allow_html=True,
            )
            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Group-wise summary**")
                st.dataframe(group_df, use_container_width=True, height=380)
            with g2:
                st.markdown("**A-Book / B-Book / Hybrid exposure**")
                st.dataframe(book_df, use_container_width=True, height=380)

            # also show top group gainers/losers
            st.markdown("---")
            gg1, gg2 = st.columns(2)
            with gg1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                    use_container_width=True,
                )
            with gg2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                    use_container_width=True,
                )

            st.markdown("</div>", unsafe_allow_html=True)

            st.write("")

            # ==================================================
            # A-Book vs LP brokerage
            # ==================================================
            st.markdown(
                '<div class="section-card-light">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">6. A-Book vs LP brokerage</div>',
                unsafe_allow_html=True,
            )

            # client A-Book PnL from book table (already includes switches / hybrid split)
            client_abook_pnl = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            st.markdown(
                f"- **Client A-Book P&L (from books table):** `{client_abook_pnl:,.2f}`"
            )

            # LP breakdown
            if lp_file is not None:
                lp_df = parse_lp_file(lp_file)
            else:
                # allow manual single LP entry
                with st.expander("No LP file uploaded – enter a single LP manually"):
                    lp_name = st.text_input("LP name", value="Single_LP")
                    lp_open = st.number_input(
                        "LP opening equity", value=0.0, step=100.0, format="%.2f"
                    )
                    lp_close = st.number_input(
                        "LP closing equity", value=0.0, step=100.0, format="%.2f"
                    )
                    lp_netdp = st.number_input(
                        "LP net D/W (Deposit − Withdrawal)",
                        value=0.0,
                        step=100.0,
                        format="%.2f",
                    )
                lp_df = pd.DataFrame(
                    {
                        "LPName": [lp_name],
                        "OpeningEquity": [lp_open],
                        "ClosingEquity": [lp_close],
                        "NetDPWD": [lp_netdp],
                    }
                )
                lp_df["LP_PnL"] = (
                    lp_df["ClosingEquity"] - lp_df["OpeningEquity"] - lp_df["NetDPWD"]
                )

            # Brokerage = LP_PnL − Client_A_Book_PnL (per LP as requested)
            lp_df["Brokerage_PnL"] = lp_df["LP_PnL"] - client_abook_pnl

            st.markdown("**LP breakdown (file / manual):**")
            st.dataframe(lp_df, use_container_width=True)

            total_lp_pnl = lp_df["LP_PnL"].sum()
            total_brokerage = total_lp_pnl - client_abook_pnl

            st.markdown(
                f"- **Total LP P&L (all LPs):** `{total_lp_pnl:,.2f}`  "
                f"<br>- **Brokerage P&L (total LP P&L − client A-Book P&L):** "
                f"`{total_brokerage:,.2f}`",
                unsafe_allow_html=True,
            )

            st.markdown("</div>", unsafe_allow_html=True)

            st.write("")

            # ==================================================
            # DOWNLOAD EXCEL
            # ==================================================
            st.markdown(
                '<div class="section-card-light">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="section-title">7. Download Excel report</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "You can keep this as a daily archive. It includes Account, Group, "
                "Books and A-Book vs LP sheets."
            )

            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # A-Book vs LP sheet
                ab_vs_lp = lp_df.copy()
                ab_vs_lp.insert(1, "Client_A_Book_PnL", client_abook_pnl)
                ab_vs_lp.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

            buffer.seek(0)
            st.download_button(
                "⬇️ Download XLSX",
                data=buffer,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )

            st.markdown("</div>", unsafe_allow_html=True)

        except Exception as exc:  # noqa: BLE001
            st.error(f"❌ Error while generating report: {exc}")
