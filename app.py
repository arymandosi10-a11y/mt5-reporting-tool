import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# PAGE CONFIG & THEME
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Light premium styling
st.markdown(
    """
<style>
/* Layout */
.main {
    background: radial-gradient(circle at top left, #f3f4ff 0, #ffffff 45%, #f5f7fb 100%);
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}

/* Typography */
h1, h2, h3, h4, h5 {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
    letter-spacing: 0.02em;
}
body {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
}

/* Cards */
.premium-card {
    background: #ffffffcc;
    border-radius: 18px;
    padding: 1.25rem 1.5rem;
    box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
    border: 1px solid rgba(148, 163, 184, 0.35);
}
.metric-card {
    background: #ffffff;
    border-radius: 16px;
    padding: 0.85rem 1rem;
    border: 1px solid rgba(203, 213, 225, 0.9);
}
.metric-label {
    font-size: 0.75rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.14em;
}
.metric-value {
    font-size: 1.25rem;
    font-weight: 650;
    margin-top: 0.1rem;
}
.metric-sub {
    font-size: 0.8rem;
    color: #9ca3af;
}

/* Section titles */
.section-title {
    font-size: 1.1rem;
    font-weight: 650;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6b7280;
}

/* Accent badge */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    background: rgba(59,130,246,0.06);
    color: #2563eb;
}

/* Dataframe tweaks */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 12px 30px rgba(15,23,42,0.06);
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f9fafb 0%, #eef2ff 45%, #e5f2ff 100%);
    border-right: 1px solid rgba(148,163,184,0.4);
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# TITLE
# =========================================================
st.markdown(
    """
<div style="margin-bottom:1.25rem;">
  <div class="badge">FX client book monitor</div>
  <h1 style="margin-top:0.4rem;margin-bottom:0.2rem;">
    Client P&L Monitoring Tool
  </h1>
  <p style="color:#6b7280;max-width:680px;font-size:0.95rem;">
    Upload MT5 exports to see account-wise, group-wise and book-wise P&L, 
    plus A-Book vs B-Book vs Hybrid comparison and A-Book vs LP brokerage.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
# HELPERS
# =========================================================
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1 – Summary / Transactions.

    Assumed columns (0-based index):
      0: Login (A)
      2: Deposit (C)
      4: NET DP/WD (E)
      5: Withdrawal (F)
      7: Closed volume (H) - will be divided by 2 for closed lots
      8: Commission (I)
      10: Swap (K)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # Most MT5 summary exports have 2 header rows
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must have at least 11 columns (through column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")

    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["NET_DP_WD_RAW"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)

    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "NET_DP_WD_RAW", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3 – Daily Reports (EOD equity snapshots).
    Looks for columns: Login, Equity, Currency.
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
    equity_col = find_col(["equity"], 9)   # J
    currency_col = None
    for opt in ["currency", "curr", "ccy"]:
        if opt in cols_lower:
            currency_col = df.columns[cols_lower.index(opt)]
            break

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = df[currency_col].astype(str) if currency_col else "USD"
    return out


def _read_accounts_file(file) -> pd.DataFrame:
    """Read a book-accounts file: columns Login and optional Group."""
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


def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switch_file(file) -> pd.DataFrame:
    """
    Optional: list of accounts that changed book during this period.

    Columns (case-insensitive):
      - Login
      - FromType  (A-Book / B-Book / Hybrid)
      - ToType    (A-Book / B-Book / Hybrid)
      - ShiftEquity  (equity at the moment of switch)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col_name):
        for k, v in lower.items():
            if k == col_name.lower():
                return v
        raise ValueError(f"Switch file must contain column '{col_name}'")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce")
    return out


def build_report(summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label):
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

    for col in [
        "Closing Equity",
        "Opening Equity",
        "Deposit",
        "Withdrawal",
        "NET_DP_WD_RAW",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots from H/2
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # Net DP/WD – take directly from summary sheet (column E total)
    report["NET DP/WD"] = report["NET_DP_WD_RAW"]

    # NET PNL USD = Closing - Opening - NET DP/WD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Apply book switches & split P&L
    report["ShiftEquity"] = np.nan
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan

    if switch_df is not None and not switch_df.empty:
        report = report.merge(
            switch_df, on="Login", how="left", suffixes=("", "_switch")
        )
        report["ShiftEquity"] = report["ShiftEquity"].astype(float)
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]
        report["Type"] = np.where(
            report["ShiftToType"].notna(), report["ShiftToType"], report["Type"]
        )

    report["EOD Closing Equity Date"] = eod_label

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
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate P&L by books, splitting accounts which switched book using ShiftEquity.
    For switched accounts:
      - net_pnl = account NET PNL USD
      - pnl_new = ClosingEquity − ShiftEquity
      - pnl_old = net_pnl − pnl_new
      New book carries the account count and closed lots,
      old book only carries its portion of P&L.
    """
    rows = []
    for _, r in account_df.iterrows():
        net_pnl = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        closing = r["Closing Equity"]
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_eq = r["ShiftEquity"]
        from_t = r["ShiftFromType"]
        to_t = r["ShiftToType"]

        if pd.isna(shift_eq) or pd.isna(to_t) or orig_type == final_type:
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
        else:
            pnl_new = closing - shift_eq
            pnl_old = net_pnl - pnl_new

            rows.append(
                {
                    "Type": from_t,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            rows.append(
                {
                    "Type": to_t,
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


# ---------- LP FILE HANDLING ----------
def load_lp_breakdown_file(file) -> pd.DataFrame:
    """
    LP breakdown file; may contain multiple LPs.

    Required columns (case-insensitive):
      LPName, OpeningEquity, ClosingEquity, NetDPWD

    We compute LP_PnL = ClosingEquity – OpeningEquity – NetDPWD.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col_name):
        for k, v in lower.items():
            if k == col_name.lower():
                return v
        raise ValueError(f"LP breakdown file must contain column '{col_name}'")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity")], errors="coerce").fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity")], errors="coerce").fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd")], errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# =========================================================
# SIDEBAR – LP P&L
# =========================================================
with st.sidebar:
    st.markdown("### 🏛️ A-Book LP P&L (optional)")
    st.write(
        "Upload an LP breakdown file with one or more LPs to compare "
        "A-Book client P&L vs liquidity providers. "
        "Brokerage P&L = Total LP P&L – Client A-Book P&L."
    )

    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_file",
    )

# =========================================================
# MAIN – UPLOAD MT5 REPORTS
# =========================================================
st.markdown('<div class="section-title">1. Upload MT5 reports</div>', unsafe_allow_html=True)

with st.container():
    eod_label = st.text_input(
        "EOD Closing Equity Date (stored in reports)",
        placeholder="e.g. 2025-12-06 EOD",
    )

    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)
    c5, c6, c7, c8 = st.columns(4)

    with c1:
        summary_file = st.file_uploader(
            "Sheet 1 – Summary / Transactions",
            type=["xlsx", "xls", "csv"],
            key="summary",
            help="Includes NET DP/WD (E), Closed volume (H), Commission (I), Swap (K).",
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
            help="Columns: Login, optional Group",
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
    with c8:
        switch_file = st.file_uploader(
            "Book switch overrides (optional)",
            type=["xlsx", "xls", "csv"],
            key="switch",
            help="Columns: Login, FromType, ToType, ShiftEquity",
        )

st.markdown("---")

# =========================================================
# RUN BUTTON
# =========================================================
if st.button("🚀 Generate report", type="primary"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid account list.")
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

                switch_df = load_switch_file(switch_file) if switch_file else None

                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, switch_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # =================================================
            # KPI SNAPSHOT
            # =================================================
            st.markdown('<div class="section-title">2. Snapshot of today\'s client P&L</div>', unsafe_allow_html=True)

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
                st.markdown('<div class="metric-sub">Unique MT5 logins</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markmarkdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_closed_lots:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">From summary sheet (H/2)</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Closing − Opening − NET DP/WD</div>', unsafe_allow_html=True)
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
                st.markdown('<div class="metric-sub">By client NET P&L</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            # =================================================
            # FULL ACCOUNT P&L
            # =================================================
            st.markdown('<div class="section-title">3. Full account P&L</div>', unsafe_allow_html=True)
            st.dataframe(account_df, use_container_width=True)

            # =================================================
            # BOOK SUMMARY
            # =================================================
            st.markdown('<div class="section-title">4. A-Book / B-Book / Hybrid summary</div>', unsafe_allow_html=True)
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

            # =================================================
            # GROUP SUMMARY
            # =================================================
            st.markdown('<div class="section-title">5. Group-wise summary</div>', unsafe_allow_html=True)
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

            # =================================================
            # A-BOOK VS LP BROKERAGE (NO PER-LP BROKERAGE COLUMN)
            # =================================================
            st.markdown('<div class="section-title">6. A-Book vs LP brokerage</div>', unsafe_allow_html=True)
            st.markdown(f"- Client A-Book P&L (from books table): **{pnl_a:,.2f}**")

            lp_df = None
            total_lp_pnl = 0.0
            brokerage_pnl = None

            if lp_file is not None:
                lp_df = load_lp_breakdown_file(lp_file)
                total_lp_pnl = lp_df["LP_PnL"].sum()
                brokerage_pnl = total_lp_pnl - pnl_a

                st.markdown("##### LP breakdown (file)")
                # IMPORTANT: we do NOT include Brokerage_PnL column here
                st.dataframe(lp_df, use_container_width=True)

                st.markdown(f"- Total LP P&L (sum of all LPs): **{total_lp_pnl:,.2f}**")
                st.markdown(
                    f"- Brokerage P&L (Total LP – A-Book): **{brokerage_pnl:,.2f}**"
                )
            else:
                st.info("No LP breakdown file uploaded – brokerage P&L will not be calculated.")

            # =================================================
            # DOWNLOAD EXCEL
            # =================================================
            st.markdown('<div class="section-title">7. Download Excel report</div>', unsafe_allow_html=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                if lp_df is not None:
                    lp_df.to_excel(writer, index=False, sheet_name="LP_Breakdown")

                    abook_lp_df = pd.DataFrame(
                        {
                            "Metric": [
                                "Client_A_Book_PnL",
                                "Total_LP_PnL",
                                "Brokerage_PnL_TotalLP_minus_Abook",
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
