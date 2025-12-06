import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# PAGE SETUP & THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="Broker Client P&L Studio",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
/* Global */
body, .main {
    background: radial-gradient(circle at top left, #eef2ff 0, #f9fafb 45%, #fefefe 100%);
    color: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1250px;
}

/* Fancy section headers */
.section-title {
    font-size: 1.15rem;
    font-weight: 700;
    margin: 0 0 0.4rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-pill {
    background: linear-gradient(135deg, #4f46e5, #6366f1);
    color: white;
    border-radius: 999px;
    padding: 0.15rem 0.55rem;
    font-size: 0.75rem;
    font-weight: 600;
}

/* Cards */
.card {
    background: rgba(255,255,255,0.95);
    border-radius: 18px;
    padding: 1rem 1.2rem;
    border: 1px solid rgba(148,163,184,0.35);
    box-shadow: 0 18px 45px rgba(15,23,42,0.08);
}
.metric-card {
    background: rgba(255,255,255,0.95);
    border-radius: 16px;
    padding: 0.9rem 1.1rem;
    border: 1px solid rgba(226,232,240,0.8);
}
.metric-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #64748b;
}
.metric-value {
    font-size: 1.25rem;
    font-weight: 700;
    margin-top: 0.1rem;
}
.metric-sub {
    font-size: 0.75rem;
    color: #94a3b8;
}

/* Dataframe */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 16px 35px rgba(15,23,42,0.06);
}

/* Download button */
.stDownloadButton button {
    border-radius: 999px;
    padding: 0.5rem 1.1rem;
    font-weight: 600;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #eef2ff 0, #f9fafb 40%, #fefefe 100%);
    border-right: 1px solid rgba(148,163,184,0.35);
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown("## 📈 Broker Client P&L Studio")
st.caption(
    "End-of-day MT5 P&L engine with A-Book / B-Book / Hybrid splitting, "
    "multi-account book shifts, and multi-LP brokerage comparison."
)

# ---------------------------------------------------------
# HELPER FUNCTIONS – LOADING FILES
# ---------------------------------------------------------
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Expected positions (0-based index):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        7: Closed volume (H)  -> used for Closed Lots ( /2 )
        10: Commission (K)
        12: Swap (M)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # broker's report normally has 2 header rows
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 13:
        raise ValueError("Summary sheet must have at least 13 columns (up to column M).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 12], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD equity snapshots)
    Expect columns: Login, Equity, Currency (or defaults to USD).
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
        raise ValueError(f"Could not find column for {name_options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)  # J
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
    Read a book-accounts file: expect Login and optional Group column.
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
    Book switches for MULTIPLE accounts.

    Expected columns (case-insensitive):

      - Login
      - FromType   (A-Book / B-Book / Hybrid)
      - ToType     (A-Book / B-Book / Hybrid)
      - ShiftEquity  (equity at the moment of switch)
      - HybridShareA (optional, %, share of hybrid profit going to A-Book.
                      Example 50 means 50% A-Book / 50% B-Book. Used only if ToType=Hybrid.)

    One row per login.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(colname, required=True, default=None):
        for k, v in lower.items():
            if k == colname.lower():
                return df[v]
        if required:
            raise ValueError(f"Switch file must contain column '{colname}'")
        return default

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(pick("login"), errors="coerce").astype("Int64")
    out["FromType"] = pick("fromtype").astype(str)
    out["ToType"] = pick("totype").astype(str)
    out["ShiftEquity"] = pd.to_numeric(pick("shiftequity"), errors="coerce")
    if "hybridsharea" in lower or "hybrid_share_a" in lower:
        out["HybridShareA"] = pd.to_numeric(
            pick("hybridsharea", required=False), errors="coerce"
        )
    else:
        out["HybridShareA"] = np.nan
    return out


def load_lp_file(file) -> pd.DataFrame:
    """
    LP file with multiple LPs.

    Expected columns (case-insensitive):
      - LPName
      - OpeningEquity
      - ClosingEquity
      - NetDPWD     (Deposit − Withdrawal for the day)

    PnL formula: Closing − Opening − NetDPWD
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(colname):
        for k, v in lower.items():
            if k == colname.lower():
                return df[v]
        raise ValueError(f"LP file must contain column '{colname}'")

    out = pd.DataFrame()
    out["LPName"] = pick("lpname").astype(str)
    out["OpeningEquity"] = pd.to_numeric(pick("openingequity"), errors="coerce").fillna(
        0.0
    )
    out["ClosingEquity"] = pd.to_numeric(pick("closingequity"), errors="coerce").fillna(
        0.0
    )
    out["NetDPWD"] = pd.to_numeric(pick("netdpwd"), errors="coerce").fillna(0.0)
    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# ---------------------------------------------------------
# METRIC BUILDERS
# ---------------------------------------------------------
def build_account_report(summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label):
    """
    Combine all sheets & compute base metrics per account,
    then attach switch info (if any).
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    # Only accounts from provided A/B/Hybrid lists
    report = accounts_df.merge(base, on="Login", how="left")

    # numeric safety
    numeric_cols = [
        "Closing Equity",
        "Opening Equity",
        "Deposit",
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

    # Closed lots from summary H column
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # NET DP/WD
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL USD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # NET PNL %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Attach switches
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan
    report["HybridShareA"] = np.nan

    if switch_df is not None and not switch_df.empty:
        switch_df = switch_df.copy()
        switch_df = switch_df.dropna(subset=["Login"])
        switch_df = switch_df.drop_duplicates(subset=["Login"], keep="last")

        report = report.merge(
            switch_df[["Login", "FromType", "ToType", "ShiftEquity", "HybridShareA"]],
            on="Login",
            how="left",
        )
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]

    report["EOD Closing Equity Date"] = eod_label

    # Columns in final order
    final_cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "Closed Lots",
        "NET DP/WD",
        "Currency",
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
        "HybridShareA",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Allocate P&L between A-Book, B-Book, Hybrid, taking into account
    switches and hybrid ratios.

    For each account:

      net_pnl = Closing − Opening − NET_DP/WD

    If NO switch:

      - If Type = 'Hybrid':
            ratioA = HybridShareA% if present else 50/50
            Abook += ratioA * net_pnl
            Bbook += (1−ratioA) * net_pnl
            Hybrid += net_pnl
      - Else:
            Book(Type) += net_pnl

    If SWITCH (we assume at most one per login):

      pnl_after = Closing − ShiftEquity
      pnl_before = net_pnl − pnl_after

      - Old period:
            FromType gets pnl_before in full
      - New period:
            If ToType = 'Hybrid':
                use HybridShareA% to split pnl_after between A/B and Hybrid.
            Else:
                ToType gets pnl_after in full.
    """
    rows = []

    for _, r in account_df.iterrows():
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        orig_type = str(r["OrigType"])
        final_type = str(r["Type"])
        shift_to = r["ShiftToType"]
        shift_from = r["ShiftFromType"]
        shift_equity = r["ShiftEquity"]
        hybrid_share_a = r["HybridShareA"]

        # default hybrid share (if used)
        if pd.isna(hybrid_share_a):
            hybrid_share_a = 50.0  # 50/50 default
        hybrid_share = float(hybrid_share_a) / 100.0
        hybrid_share = min(max(hybrid_share, 0.0), 1.0)

        # contribution helper
        def add_row(book_type, pnl, lots_contrib):
            rows.append(
                {
                    "Type": book_type,
                    "Lots": lots_contrib,
                    "NET_PNL_USD": pnl,
                }
            )

        if pd.isna(shift_to) or pd.isna(shift_from) or pd.isna(shift_equity):
            # NO SWITCH CASE
            if final_type == "Hybrid":
                pnl_hybrid = net_pnl
                pnl_a = hybrid_share * pnl_hybrid
                pnl_b = (1 - hybrid_share) * pnl_hybrid
                add_row("A-Book", pnl_a, closed_lots * hybrid_share)
                add_row("B-Book", pnl_b, closed_lots * (1 - hybrid_share))
                add_row("Hybrid", pnl_hybrid, closed_lots)
            else:
                add_row(final_type, net_pnl, closed_lots)
        else:
            # SWITCH CASE
            closing = float(r["Closing Equity"])
            pnl_after = closing - float(shift_equity)
            pnl_before = net_pnl - pnl_after

            # period before switch -> FromType
            add_row(str(shift_from), pnl_before, 0.0)

            # period after switch
            if str(shift_to) == "Hybrid":
                pnl_hybrid = pnl_after
                pnl_a = hybrid_share * pnl_hybrid
                pnl_b = (1 - hybrid_share) * pnl_hybrid
                add_row("A-Book", pnl_a, closed_lots * hybrid_share)
                add_row("B-Book", pnl_b, closed_lots * (1 - hybrid_share))
                add_row("Hybrid", pnl_hybrid, closed_lots)
            else:
                add_row(str(shift_to), pnl_after, closed_lots)

    contrib = pd.DataFrame(rows)
    if contrib.empty:
        return pd.DataFrame(columns=["Type", "Accounts", "Closed_Lots", "NET_PNL_USD"])

    # count unique accounts per book (for simplicity we count final Type accounts)
    account_counts = account_df.groupby("Type")["Login"].nunique().rename("Accounts")

    book = (
        contrib.groupby("Type", as_index=False)
        .agg(Closed_Lots=("Lots", "sum"), NET_PNL_USD=("NET_PNL_USD", "sum"))
        .merge(account_counts, left_on="Type", right_index=True, how="left")
    )

    # move Accounts column to front
    book = book[["Type", "Accounts", "Closed_Lots", "NET_PNL_USD"]]
    book["Accounts"] = book["Accounts"].fillna(0).astype(int)
    return book


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


# ---------------------------------------------------------
# SIDEBAR – A-BOOK LP P&L (MULTI-LP)
# ---------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="section-pill">LP PANEL</div>', unsafe_allow_html=True)
    st.markdown("### 🏛️ A-Book LP P&L (optional)")
    st.caption(
        "Upload an LP breakdown file **or** key values manually. "
        "Brokerage P&L = **Total LP P&L − Client A-Book P&L**."
    )

    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_file",
        help="Columns: LPName, OpeningEquity, ClosingEquity, NetDPWD",
    )

    st.markdown("---")
    st.caption("If you don't upload an LP file, you can still enter a single LP below:")

    lp_manual_open = st.number_input(
        "Single LP opening equity",
        value=0.0,
        step=100.0,
    )
    lp_manual_close = st.number_input(
        "Single LP closing equity",
        value=0.0,
        step=100.0,
    )
    lp_manual_netdp = st.number_input(
        "Single LP net D/W (Deposit − Withdrawal)",
        value=0.0,
        step=100.0,
    )


# ---------------------------------------------------------
# MAIN INPUT – MT5 / ACCOUNTS / SWITCHES
# ---------------------------------------------------------
st.markdown('<div class="section-pill">STEP 1</div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">Upload MT5 EOD files</div>', unsafe_allow_html=True)

eod_label = st.text_input(
    "EOD Closing Equity Date label (stored inside Excel export)",
    placeholder="e.g. 2025-12-02 EOD",
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)
c5, c6, c7 = st.columns(3)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="Includes Deposit, Withdrawal, Volume (H), Commission, Swap.",
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
        help="Previous EOD equity snapshot (used as opening equity).",
    )

st.markdown('<div class="section-pill">STEP 2</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-title">Book account mapping (A / B / Hybrid)</div>',
    unsafe_allow_html=True,
)

with c5:
    a_book_file = st.file_uploader(
        "A-Book accounts file",
        type=["xlsx", "xls", "csv"],
        key="abook",
        help="File with columns: Login, optional Group.",
    )
with c6:
    b_book_file = st.file_uploader(
        "B-Book accounts file",
        type=["xlsx", "xls", "csv"],
        key="bbook",
        help="File with columns: Login, optional Group.",
    )
with c7:
    hybrid_acc_file = st.file_uploader(
        "Hybrid accounts file (optional)",
        type=["xlsx", "xls", "csv"],
        key="hybrid_acc",
        help="File with columns: Login, optional Group.",
    )

st.markdown('<div class="section-pill">STEP 3</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-title">Book switches & hybrid ratios (optional)</div>',
    unsafe_allow_html=True,
)
c8, c9 = st.columns([2, 1])
with c8:
    switch_file = st.file_uploader(
        "Book switch file (multiple accounts, XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="switchfile",
        help=(
            "Columns: Login, FromType, ToType, ShiftEquity, "
            "HybridShareA (%, only used when ToType = Hybrid)."
        ),
    )
with c9:
    st.caption(
        "Example row: 1017, B-Book → Hybrid, ShiftEquity=15000, HybridShareA=50 "
        "→ profit after switch will be split 50% A-Book / 50% B-Book."
    )

st.markdown("---")

# ---------------------------------------------------------
# GENERATE REPORT
# ---------------------------------------------------------
generate = st.button("🚀 Generate report")

if generate:
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload **Summary**, **Closing Equity**, and **Opening Equity** files.")
    elif not (a_book_file or b_book_file or hybrid_acc_file):
        st.error("Please upload at least one of: **A-Book**, **B-Book**, or **Hybrid** accounts file.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date label.")
    else:
        try:
            with st.spinner("Crunching numbers and building P&L views…"):
                # Load MT5 data
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)

                # Accounts maps
                acc_frames = []
                if a_book_file:
                    acc_frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file:
                    acc_frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_acc_file:
                    acc_frames.append(load_book_accounts(hybrid_acc_file, "Hybrid"))

                accounts_df = pd.concat(acc_frames, ignore_index=True)
                accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

                # Switch file (multiple accounts)
                switch_df = None
                if switch_file is not None:
                    switch_df = load_switch_file(switch_file)

                # Build account report
                account_df = build_account_report(
                    summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

                # ----------------- LP DATA -----------------
                # 1) LP file with multiple LPs
                lp_df = None
                if lp_file is not None:
                    lp_df = load_lp_file(lp_file)

                # 2) Single LP manually (if no LP file but manual values given)
                if lp_df is None and any(
                    [lp_manual_open != 0, lp_manual_close != 0, lp_manual_netdp != 0]
                ):
                    single_pnl = lp_manual_close - lp_manual_open - lp_manual_netdp
                    lp_df = pd.DataFrame(
                        {
                            "LPName": ["Manual_LP"],
                            "OpeningEquity": [lp_manual_open],
                            "ClosingEquity": [lp_manual_close],
                            "NetDPWD": [lp_manual_netdp],
                            "LP_PnL": [single_pnl],
                        }
                    )

            # -----------------------------------------------------
            # HIGH LEVEL KPIs
            # -----------------------------------------------------
            st.markdown('<div class="section-pill">OVERVIEW</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Key metrics</div>', unsafe_allow_html=True)

            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl_total = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Total Clients</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(total_clients)}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed Lots</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_closed_lots:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net Client P&L</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl_total:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs Loss share</div>', unsafe_allow_html=True)
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

            st.markdown("### 📊 Profit vs loss bar")
            chart_data = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.bar_chart(chart_data)

            # -----------------------------------------------------
            # FULL ACCOUNT TABLE
            # -----------------------------------------------------
            st.markdown("### 🧾 Full account P&L")
            st.dataframe(account_df, use_container_width=True)

            # -----------------------------------------------------
            # BOOK SUMMARY
            # -----------------------------------------------------
            st.markdown("### 📚 A-Book / B-Book / Hybrid summary")
            st.dataframe(book_df, use_container_width=True)

            pnl_a_book = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b_book = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            pnl_hybrid = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()

            total_client_pnl_books = pnl_a_book + pnl_b_book + pnl_hybrid
            result_str = "profit" if total_client_pnl_books >= 0 else "loss"
            st.markdown(
                f"**Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                f"{total_client_pnl_books:,.2f} ({result_str})**"
            )

            # -----------------------------------------------------
            # TOP ACCOUNTS (GAINERS / LOSERS)
            # -----------------------------------------------------
            st.markdown("### 🥇 Top 10 accounts (gainers & losers)")

            cols_show = [
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
            gcol, lcol = st.columns(2)
            with gcol:
                st.markdown("**Top 10 gainer accounts**")
                top_gainers = account_df.sort_values("NET PNL USD", ascending=False).head(10)
                st.dataframe(top_gainers[cols_show], use_container_width=True)
            with lcol:
                st.markdown("**Top 10 loser accounts**")
                top_losers = account_df.sort_values("NET PNL USD", ascending=True).head(10)
                st.dataframe(top_losers[cols_show], use_container_width=True)

            # -----------------------------------------------------
            # GROUP SUMMARY
            # -----------------------------------------------------
            st.markdown("### 🧩 Group-wise summary")
            st.dataframe(group_df, use_container_width=True)

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

            # -----------------------------------------------------
            # A-BOOK vs LP BROKERAGE
            # -----------------------------------------------------
            st.markdown("### 🏛️ A-Book vs LP brokerage")

            st.markdown(
                f"- Client A-Book P&L **(from books table)**: **{pnl_a_book:,.2f}**"
            )

            total_lp_pnl = 0.0
            if lp_df is not None and not lp_df.empty:
                total_lp_pnl = lp_df["LP_PnL"].sum()
                st.markdown("#### LP breakdown (from file / manual)")
                # In the table we show each LP's own PnL only
                lp_df_display = lp_df.copy()
                lp_df_display["Brokerage_PnL_Row"] = lp_df_display["LP_PnL"]
                st.dataframe(lp_df_display, use_container_width=True)

                brokerage_total = total_lp_pnl - pnl_a_book
                st.markdown(
                    f"**Total LP P&L (sum of all LPs): {total_lp_pnl:,.2f}**  "
                    f"&nbsp;&nbsp;→ **Brokerage P&L = Total LP P&L − Client A-Book P&L "
                    f"= {brokerage_total:,.2f}**"
                )
            else:
                st.caption("No LP file or manual LP values given, so brokerage section is empty.")

            # -----------------------------------------------------
            # EXCEL EXPORT
            # -----------------------------------------------------
            st.markdown("### 📥 Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # LP breakdown sheet (if any)
                if lp_df is not None and not lp_df.empty:
                    lp_df.to_excel(writer, index=False, sheet_name="LPs")

                # A-Book vs LP summary sheet
                metrics = {
                    "Client_A_Book_PnL": [pnl_a_book],
                    "Total_LP_PnL": [total_lp_pnl],
                    "Brokerage_PnL": [total_lp_pnl - pnl_a_book],
                }
                abook_lp_df = pd.DataFrame(metrics)
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
