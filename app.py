import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# PAGE CONFIG & GLOBAL STYLE
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
/* Global */
body, .main {
    background-color: #0f172a;
    color: #e5e7eb;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1450px;
}

/* Headline */
h1, h2, h3 {
    color: #e5e7eb;
}

/* Cards */
.card {
    background: #020617;
    border-radius: 18px;
    padding: 1.1rem 1.3rem;
    border: 1px solid rgba(148,163,184,0.35);
    box-shadow: 0 18px 45px rgba(15,23,42,0.80);
}
.card-soft {
    background: radial-gradient(circle at 0 0, #1f2937 0, #020617 45%);
    border-radius: 18px;
    padding: 1.1rem 1.3rem;
    border: 1px solid rgba(148,163,184,0.35);
}

/* Metric cards */
.metric-card {
    background: linear-gradient(135deg, #0f172a, #020617);
    border-radius: 16px;
    padding: 0.75rem 1rem;
    border: 1px solid rgba(148,163,184,0.35);
}
.metric-label {
    font-size: 0.75rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #9ca3af;
}
.metric-value {
    font-size: 1.3rem;
    font-weight: 600;
    color: #e5e7eb;
}
.metric-sub {
    font-size: 0.75rem;
    color: #6b7280;
}

/* Section title badge */
.section-badge {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    padding: .18rem .6rem;
    border-radius: 999px;
    border: 1px solid rgba(148,163,184,0.55);
    font-size: .8rem;
    color: #9ca3af;
}

/* Dataframe tweaks */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
}

/* Sidebar tweaks */
[data-testid="stSidebar"] {
    background: radial-gradient(circle at 0 0, #111827 0, #020617 60%);
    border-right: 1px solid #1f2937;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def load_summary_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 1 – Summary / Transactions.

    MT5 export (0-based indexes):
        0: Login
        2: Deposit          [optional, not required]
        3: Withdrawal       [optional, not required]
        4: NET DP/WD        <= **WE USE THIS**
        7: Volume           <= used for Closed Lots = Volume / 2
        8: Commission       (column I)
        10: Swap            (column K)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # most MT5 exports have 2 header lines → data from row 3
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must have at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")

    # Optional: Deposit / Withdrawal (not needed for formula)
    df["Deposit_raw"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["Withdrawal_raw"] = pd.to_numeric(raw.iloc[:, 3], errors="coerce").fillna(0.0)

    # NET DP/WD from column E (index 4)
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)

    # Closed volume from column H (index 7)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)

    # Commission from column I (index 8)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)

    # Swap from column K (index 10)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit_raw", "Withdrawal_raw", "NET_DP_WD", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 2 / 3 – Equity report (daily snapshot).
    We only need Login, Equity and optional Currency.
    """
    try:
        df = pd.read_excel(file, header=2)
    except Exception:
        df = pd.read_excel(file)

    cols_lower = [str(c).strip().lower() for c in df.columns]

    def find_col(name_options, default_idx=None):
        for opt in name_options:
            if opt in cols_lower:
                return df.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(df.columns):
            return df.columns[default_idx]
        raise ValueError(f"Could not find a column for {name_options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)  # J by default
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


def _read_accounts_file(file: BytesIO) -> pd.DataFrame:
    """Read a book-accounts file (Login + optional Group)."""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

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


def load_book_accounts(file: BytesIO, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switches_file(file: BytesIO) -> pd.DataFrame:
    """
    Optional set of book switches (multi-accounts).

    Expected columns (case-insensitive):
      - Login
      - FromType  (A-Book / B-Book / Hybrid)
      - ToType    (A-Book / B-Book / Hybrid)
      - ShiftEquity  (equity at the time of switch)

    We *only* split daily P&L into Old book / New book using ShiftEquity.
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
        raise ValueError(f"Switches file must contain a '{col}' column.")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)
    return out


def build_report(summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label: str):
    """
    Merge everything and compute per-account metrics.

    Formula:
        NET PNL USD = ClosingEquity - OpeningEquity - NET DP/WD
    """
    # --- base from closing & opening equity
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")

    # Add summary info
    base = base.merge(summary_df, on="Login", how="left")

    # start from list of accounts we actually care about (A / B / Hybrid lists)
    report = accounts_df.merge(base, on="Login", how="left")

    # fill numeric columns
    for col in [
        "Closing Equity",
        "Opening Equity",
        "NET_DP_WD",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # DP/WD (already net from Sheet 1)
    report["NET DP/WD"] = report["NET_DP_WD"]

    # Optional split into Deposits / Withdrawals just for display
    report["Deposit"] = np.where(report["NET DP/WD"] > 0, report["NET DP/WD"], 0.0)
    report["Withdrawal"] = np.where(report["NET DP/WD"] < 0, -report["NET DP/WD"], 0.0)

    # NET PNL
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # NET PNL % vs Opening equity (abs)
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Attach switches info for reference only (book allocation done later)
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan

    if switches_df is not None and not switches_df.empty:
        report = report.merge(
            switches_df, on="Login", how="left", suffixes=("", "_sw")
        )
        # rename merged columns
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]
        report["ShiftEquity"] = report["ShiftEquity"].astype(float)
        # If there is a ToType → this becomes final Type
        report["Type"] = np.where(
            report["ShiftToType"].notna(), report["ShiftToType"], report["Type"]
        )

    report["EOD Closing Equity Date"] = eod_label

    final_cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "Currency",
        "Closed Lots",
        "NET DP/WD",
        "Opening Equity",
        "Closing Equity",
        "NET PNL USD",
        "NET PNL %",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "ShiftFromType",
        "ShiftToType",
        "ShiftEquity",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        account_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Closed_Lots=("Closed Lots", "sum"),
            NET_DP_WD=("NET DP/WD", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
            Opening_Equity=("Opening Equity", "sum"),
            Closing_Equity=("Closing Equity", "sum"),
        )
        .reset_index()
    )
    return grouped


def build_book_summary(account_df: pd.DataFrame, switches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate P&L by Type (A-Book / B-Book / Hybrid).

    If switches are provided we split the daily P&L between FROM and TO book
    using ShiftEquity:

        net_pnl        = full day P&L (as above)
        pnl_new_book   = ClosingEquity - ShiftEquity
        pnl_old_book   = net_pnl - pnl_new_book
    """
    rows = []
    switches_map = {}
    if switches_df is not None and not switches_df.empty:
        switches_map = switches_df.set_index("Login").to_dict("index")

    for _, r in account_df.iterrows():
        login = r["Login"]
        net_pnl = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        final_type = r["Type"]
        opening = r["Opening Equity"]
        closing = r["Closing Equity"]

        sw = switches_map.get(login)

        if not sw:
            # no switch → everything to final type
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
        else:
            from_type = sw["FromType"]
            to_type = sw["ToType"]
            shift_eq = float(sw["ShiftEquity"])

            pnl_new = closing - shift_eq
            pnl_old = net_pnl - pnl_new

            # old book (no account counted)
            rows.append(
                {
                    "Type": from_type,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            # new book (account belongs here)
            rows.append(
                {
                    "Type": to_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": pnl_new,
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
    )
    return book


def load_lp_breakdown_file(file: BytesIO) -> pd.DataFrame:
    """
    LP breakdown file.

    Expected columns (case-insensitive):
      - LPName
      - OpeningEquity
      - ClosingEquity
      - NetDPWD     (Net Deposit – Withdrawal)

    LP_PnL = ClosingEquity − OpeningEquity − NetDPWD
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(*candidates):
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        raise ValueError(f"LP breakdown file is missing one of {candidates}")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname", "name")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity", "opening")], errors="coerce").fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity", "closing")], errors="coerce").fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd", "net_dp_wd", "netdp")], errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# =========================================================
# SIDEBAR – LP PANEL
# =========================================================
with st.sidebar:
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.caption(
        "You can upload an LP breakdown file (multi-LP) or just leave it empty. "
        "Brokerage P&L = **Total LP P&L − Client A-Book P&L**."
    )

    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_file",
    )

# =========================================================
# MAIN HEADER
# =========================================================
st.markdown(
    """
<div class="card-soft">
  <div class="section-badge">FX client book monitor</div>
  <h1 style="margin-top: .6rem; margin-bottom: .2rem;">Client P&amp;L Monitoring Tool</h1>
  <p style="color:#9ca3af; max-width: 820px;">
    Upload MT5 exports to see account-wise, group-wise and book-wise P&amp;L, including
    A-Book vs B-Book comparison and A-Book vs LP brokerage.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
# FILE UPLOADS (CLIENT DATA)
# =========================================================
st.markdown("### 1. Upload MT5 reports")

col_eod, _ = st.columns([2, 3])
with col_eod:
    eod_label = st.text_input(
        "EOD Closing Equity Date (stored in reports)",
        placeholder="e.g. 2025-12-02 EOD",
    )

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="MT5 summary: includes NET DP/WD (col E), Volume (H), Commission (I), Swap (K).",
    )

with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        key="closing",
        help="Daily equity snapshot for the closing date.",
    )

with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        key="opening",
        help="Equity snapshot for previous EOD (used as opening equity).",
    )

st.markdown("#### Book-wise account lists")

cb1, cb2, cb3 = st.columns(3)
with cb1:
    a_book_file = st.file_uploader(
        "A-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="abook",
        help="File with Login (& optional Group) that belong to A-Book.",
    )
with cb2:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="bbook",
        help="File with Login (& optional Group) that belong to B-Book.",
    )
with cb3:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        key="hybrid",
        help="Accounts trading in hybrid model.",
    )

st.markdown("#### Book switches (optional)")

swc1, swc2 = st.columns([2, 3])
with swc1:
    switches_file = st.file_uploader(
        "Switches file (multi-accounts)",
        type=["xlsx", "xls", "csv"],
        key="switches",
        help="Columns: Login, FromType, ToType, ShiftEquity",
    )

with swc2:
    st.caption("Use this if some accounts moved from one book to another during this day.")

st.markdown("---")

# =========================================================
# MAIN ACTION
# =========================================================
if st.button("🚀 Generate report", use_container_width=True):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of A-Book / B-Book / Hybrid accounts file.")
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

                switches_df = None
                if switches_file is not None:
                    switches_df = load_switches_file(switches_file)

                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df, switches_df)

            # =================================================
            # KPI OVERVIEW
            # =================================================
            st.markdown("### 2. Overview")

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl_total = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(total_clients):,}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Unique logins</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_closed_lots:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">From Sheet-1 volume / 2</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl_total:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">All books combined</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs loss share</div>', unsafe_allow_html=True)
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
                st.markdown('<div class="metric-sub">Based on NET PNL USD</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # Simple bar chart
            chart_data = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.bar_chart(chart_data, height=260)

            # =================================================
            # FULL ACCOUNT TABLE
            # =================================================
            st.markdown("### 3. Full account P&L")
            st.dataframe(account_df, use_container_width=True)

            # =================================================
            # BOOK SUMMARY
            # =================================================
            st.markdown("### 4. A-Book / B-Book / Hybrid summary")
            st.dataframe(book_df, use_container_width=True)

            pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            pnl_h = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()

            total_books_pnl = pnl_a + pnl_b + pnl_h
            result_label = "profit" if total_books_pnl >= 0 else "loss"
            st.markdown(
                f"**Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                f"{total_books_pnl:,.2f} ({result_label})**"
            )

            # =================================================
            # TOP ACCOUNTS & GROUPS
            # =================================================
            st.markdown("### 5. Top accounts & groups")

            t1, t2 = st.columns(2)
            show_cols = [
                "Login",
                "Group",
                "Type",
                "Opening Equity",
                "Closing Equity",
                "NET PNL USD",
                "NET PNL %",
                "Closed Lots",
                "NET DP/WD",
            ]

            with t1:
                st.markdown("**Top 10 gainer accounts**")
                top_gainers = account_df.sort_values("NET PNL USD", ascending=False).head(10)
                st.dataframe(top_gainers[show_cols], use_container_width=True)

            with t2:
                st.markdown("**Top 10 loser accounts**")
                top_losers = account_df.sort_values("NET PNL USD", ascending=True).head(10)
                st.dataframe(top_losers[show_cols], use_container_width=True)

            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                    use_container_width=True,
                )
            with g2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                    use_container_width=True,
                )

            # =================================================
            # A-BOOK VS LP BROKERAGE
            # =================================================
            st.markdown("### 6. A-Book vs LP brokerage")

            st.markdown(f"- Client **A-Book P&L** (from book summary): **{pnl_a:,.2f}**")

            lp_table = None
            total_lp_pnl = 0.0
            if lp_file is not None:
                lp_table = load_lp_breakdown_file(lp_file)
                total_lp_pnl = lp_table["LP_PnL"].sum()
                st.markdown("#### LP breakdown (from file)")
                st.dataframe(lp_table, use_container_width=True)
                st.markdown(f"- Total LP P&L (all LPs): **{total_lp_pnl:,.2f}**")
            else:
                st.info("LP breakdown file not uploaded – brokerage P&L will be 0.")

            brokerage_pnl = total_lp_pnl - pnl_a
            st.markdown(
                f"- **Brokerage P&L = Total LP P&L − Client A-Book P&L "
                f"= {total_lp_pnl:,.2f} − {pnl_a:,.2f} = {brokerage_pnl:,.2f}**"
            )

            # =================================================
            # DOWNLOAD EXCEL
            # =================================================
            st.markdown("### 7. Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # A-book vs LP sheet (with brokerage formula)
                abook_lp_rows = []

                abook_lp_rows.append(
                    {"Metric": "Client_A_Book_PnL", "Value": pnl_a}
                )
                if lp_table is not None:
                    for _, row in lp_table.iterrows():
                        abook_lp_rows.append(
                            {
                                "Metric": f"LP_{row['LPName']}_PnL",
                                "Value": row["LP_PnL"],
                            }
                        )
                abook_lp_rows.append({"Metric": "Total_LP_PnL", "Value": total_lp_pnl})
                # Brokerage = LP_PnL - Client_A_Book_PnL
                abook_lp_rows.append(
                    {
                        "Metric": "Brokerage_PnL",
                        "Value": brokerage_pnl,
                    }
                )

                abook_lp_df = pd.DataFrame(abook_lp_rows)
                abook_lp_df.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
