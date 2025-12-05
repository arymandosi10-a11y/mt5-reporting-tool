import numpy as np
import pandas as pd
from io import BytesIO

import streamlit as st

# -------------------------------------------------------------------
# PAGE LAYOUT & THEME
# -------------------------------------------------------------------
st.set_page_config(
    page_title="MT5 Client P&L Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for a cleaner, “dashboardy” look
st.markdown(
    """
<style>
body, .main {
    background: radial-gradient(circle at top left, #f5f3ff 0, #f9fafb 40%, #eef2ff 100%);
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}
h1, h2, h3, h4 {
    font-weight: 700;
}
.metric-card {
    background: rgba(255,255,255,0.96);
    border-radius: 16px;
    padding: 0.9rem 1.1rem;
    border: 1px solid #e5e7eb;
    box-shadow: 0 10px 25px rgba(15,23,42,0.06);
}
.metric-label {
    font-size: 0.80rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.metric-value {
    font-size: 1.4rem;
    font-weight: 600;
    margin-top: 0.15rem;
}
.section-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.18rem 0.7rem;
    border-radius: 999px;
    background: #eef2ff;
    color: #4f46e5;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.section-pill span {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.2rem;
    height: 1.2rem;
    border-radius: 99px;
    background: #4f46e5;
    color: white;
    font-size: 0.75rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------
# SMALL HELPERS
# -------------------------------------------------------------------
def fmt(x: float) -> str:
    try:
        return f"{x:,.2f}"
    except Exception:
        return str(x)


# -------------------------------------------------------------------
# DATA LOADING
# -------------------------------------------------------------------
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Assumed column positions (0-based index):
      0: Login
      2: Deposit (C)
      5: Withdrawal (F)
      7: Volume (H)         -> Closed lots = H / 2
      10: Commission (K)
      12: Swap (M)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # many MT5 exports have first 2 rows as headers / comments
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
        ].sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: EOD equity snapshots
    Tries to auto-detect Login, Equity, Currency.
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
        raise ValueError(f"Could not find any of columns {options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)  # often J
    currency_col = None
    for opt in ["currency", "curr", "ccy"]:
        if opt in cols_lower:
            currency_col = df.columns[cols_lower.index(opt)]
            break

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = "USD"
    if currency_col is not None:
        out["Currency"] = df[currency_col].astype(str)
    return out


def _read_accounts_file(file) -> pd.DataFrame:
    """Reads a book-accounts file with columns: Login, optional Group."""
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


# -------------------------------------------------------------------
# CORE CALCULATIONS
# -------------------------------------------------------------------
def build_report(
    summary_df: pd.DataFrame,
    closing_df: pd.DataFrame,
    opening_df: pd.DataFrame,
    accounts_df: pd.DataFrame,
    shift_df: pd.DataFrame | None,
    eod_label: str,
) -> pd.DataFrame:
    """
    Build full account-level report.
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
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots from H / 2
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # Net deposits / withdrawals
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # P&L
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # P&L %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Initialise shift columns
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan

    # Apply manual shift if provided
    if shift_df is not None and not shift_df.empty:
        shift_df = shift_df.copy()
        shift_df["Login"] = pd.to_numeric(shift_df["Login"], errors="coerce").astype(
            "Int64"
        )
        map_from = dict(zip(shift_df["Login"], shift_df["FromType"]))
        map_to = dict(zip(shift_df["Login"], shift_df["ToType"]))
        map_eq = dict(zip(shift_df["Login"], shift_df["ShiftEquity"]))

        report["ShiftFromType"] = report["Login"].map(map_from)
        report["ShiftToType"] = report["Login"].map(map_to)
        report["ShiftEquity"] = report["Login"].map(map_eq)

        # Override final book type
        report["Type"] = np.where(
            report["ShiftToType"].notna(), report["ShiftToType"], report["Type"]
        )

    report["EOD Closing Equity Date"] = eod_label

    cols = [
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
    report = report[cols].sort_values("Login").reset_index(drop=True)
    return report


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    return (
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


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise by book, splitting P&L for accounts that changed book.

    For an account with a shift:
        TotalPnl = NET PNL USD
        NewBookPnl = ClosingEquity − ShiftEquity
        OldBookPnl = TotalPnl − NewBookPnl
    Account count is assigned to the *new* book only.
    """
    rows = []
    for _, r in account_df.iterrows():
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_from = r["ShiftFromType"]
        shift_to = r["ShiftToType"]
        shift_eq = r["ShiftEquity"]

        if pd.isna(shift_eq) or pd.isna(shift_to) or orig_type == final_type:
            # No split
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
        else:
            # Split between old and new books
            closing = float(r["Closing Equity"])
            pnl_new = closing - float(shift_eq)
            pnl_old = net_pnl - pnl_new

            # Old book: only P&L (no account count)
            rows.append(
                {
                    "Type": shift_from,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            # New book: P&L + account + lots
            rows.append(
                {
                    "Type": shift_to,
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


# -------------------------------------------------------------------
# SIDEBAR – LP INPUTS
# -------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💼 LP A-Book P&L (optional)")
    st.caption(
        "Fill these if you want the app to calculate A-Book brokerage vs your LP."
    )
    lp_open = st.number_input("LP opening equity", value=0.0, step=100.0)
    lp_close = st.number_input("LP closing equity", value=0.0, step=100.0)
    lp_net_dp = st.number_input("LP net D/W (Deposit − Withdrawal)", value=0.0, step=100.0)
    st.write("---")
    st.caption(
        "Tip: you can leave these as 0 if you don't want the A-Book vs LP comparison."
    )

# -------------------------------------------------------------------
# HEADER
# -------------------------------------------------------------------
st.markdown(
    "<div class='section-pill'><span>1</span> FX Client P&L Monitoring</div>",
    unsafe_allow_html=True,
)
st.title("Daily MT5 Client P&L Dashboard")
st.write(
    "Upload your **MT5 Daily Reports** and **Account Book mappings** to generate "
    "account-wise, group-wise and A-Book / B-Book / Hybrid P&L, including book switches."
)

st.write("")

# -------------------------------------------------------------------
# FILE UPLOADS
# -------------------------------------------------------------------
st.subheader("Data inputs")

eod_label = st.text_input(
    "EOD Closing Equity Date label (stored in Excel & shown in tables)",
    placeholder="e.g. 2025-12-02 EOD",
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        help="MT5 summary/export that contains Deposit, Withdrawal, Volume (H), Commission, Swap.",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (current EOD)",
        type=["xlsx", "xls"],
        help="MT5 daily report for the closing date of this report.",
    )

with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        help="MT5 daily report for the previous EOD (used as opening equity).",
    )

st.write("")
st.markdown("#### Book account mapping")

c5, c6, c7 = st.columns(3)
with c5:
    a_book_file = st.file_uploader(
        "A-Book accounts",
        type=["xlsx", "xls", "csv"],
        help="File with Login and optional Group for all A-Book accounts.",
    )
with c6:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        help="File with Login and optional Group for all B-Book accounts.",
    )
with c7:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        help="File with Login and optional Group for Hybrid accounts.",
    )

# -------------------------------------------------------------------
# MANUAL SINGLE ACCOUNT SWITCH
# -------------------------------------------------------------------
st.write("")
st.markdown("#### Optional: single account book switch override")

switch_enabled = st.checkbox("Enable manual book switch for a single login", value=False)

DIRECTION_OPTIONS = {
    "A-Book → B-Book": ("A-Book", "B-Book"),
    "A-Book → Hybrid": ("A-Book", "Hybrid"),
    "B-Book → A-Book": ("B-Book", "A-Book"),
    "B-Book → Hybrid": ("B-Book", "Hybrid"),
    "Hybrid → A-Book": ("Hybrid", "A-Book"),
    "Hybrid → B-Book": ("Hybrid", "B-Book"),
}

switch_df = None

if switch_enabled:
    c_sw1, c_sw2, c_sw3 = st.columns([1.6, 1.1, 1.1])
    with c_sw1:
        switch_direction = st.selectbox("Switch direction", list(DIRECTION_OPTIONS.keys()))
    with c_sw2:
        switch_login_text = st.text_input("Login to switch")
    with c_sw3:
        switch_equity = st.number_input(
            "Equity at moment of switch", value=0.0, step=100.0
        )

    if switch_login_text.strip():
        try:
            login_val = int(switch_login_text.strip())
            from_type, to_type = DIRECTION_OPTIONS[switch_direction]
            switch_df = pd.DataFrame(
                [
                    {
                        "Login": login_val,
                        "FromType": from_type,
                        "ToType": to_type,
                        "ShiftEquity": float(switch_equity),
                    }
                ]
            )
        except ValueError:
            st.warning("⚠️ Could not parse the switch login as a number – ignoring.")

st.write("---")

# -------------------------------------------------------------------
# RUN BUTTON
# -------------------------------------------------------------------
if st.button("🚀 Generate P&L report", type="primary"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload **Summary**, **Closing Equity**, and **Opening Equity** files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
    elif not eod_label.strip():
        st.error("Please enter the **EOD Closing Equity Date label**.")
    else:
        try:
            with st.spinner("Reading files and calculating P&L…"):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)

                frames = []
                if a_book_file:
                    frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file:
                    frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_file:
                    frames.append(load_book_accounts(hybrid_file, "Hybrid"))

                accounts_df = pd.concat(frames, ignore_index=True)
                # If a login is present in multiple files, keep only first
                accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

                account_df = build_report(
                    summary_df,
                    closing_df,
                    opening_df,
                    accounts_df,
                    switch_df,
                    eod_label.strip(),
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # ------------------------------------------------------------------
            # OVERVIEW SECTION
            # ------------------------------------------------------------------
            st.markdown(
                "<div class='section-pill'><span>2</span> Overview</div>",
                unsafe_allow_html=True,
            )
            st.subheader("Dashboard snapshot")

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl_total = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{int(total_clients)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{fmt(total_closed_lots)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{fmt(net_pnl_total)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs loss</div>', unsafe_allow_html=True)
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

            # Simple profit vs loss bar
            chart_data = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.bar_chart(chart_data, height=260)

            # ------------------------------------------------------------------
            # TABS FOR DETAILS
            # ------------------------------------------------------------------
            st.markdown(
                "<div class='section-pill'><span>3</span> Detailed views</div>",
                unsafe_allow_html=True,
            )

            tab_acc, tab_books, tab_groups = st.tabs(
                ["📒 Accounts", "📚 Books", "👥 Groups & Rankings"]
            )

            # ACCOUNTS TAB
            with tab_acc:
                st.subheader("Full account P&L")
                st.dataframe(account_df, use_container_width=True, height=450)

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
                st.write("")
                gcol, lcol = st.columns(2)
                with gcol:
                    st.markdown("**Top 10 gainer accounts**")
                    st.dataframe(
                        account_df.sort_values("NET PNL USD", ascending=False)
                        .head(10)[cols_show],
                        use_container_width=True,
                    )
                with lcol:
                    st.markdown("**Top 10 loser accounts**")
                    st.dataframe(
                        account_df.sort_values("NET PNL USD", ascending=True)
                        .head(10)[cols_show],
                        use_container_width=True,
                    )

            # BOOKS TAB
            with tab_books:
                st.subheader("A-Book / B-Book / Hybrid summary")
                st.dataframe(book_df, use_container_width=True)

                pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
                pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
                pnl_h = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()
                total_client_pnl = pnl_a + pnl_b + pnl_h
                client_result = "profit" if total_client_pnl >= 0 else "loss"

                st.markdown(
                    f"**Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                    f"{fmt(total_client_pnl)} ({client_result})**"
                )

                # A-Book vs LP brokerage
                st.write("")
                st.subheader("A-Book vs LP brokerage")

                st.markdown(f"- Client **A-Book P&L**: `{fmt(pnl_a)}`")

                lp_pnl = lp_close - lp_open - lp_net_dp
                st.markdown(
                    f"- **LP P&L** (Close − Open − Net D/W): `{fmt(lp_pnl)}`"
                )

                brokerage_broker = pnl_a - lp_pnl   # broker's income
                brokerage_client = -brokerage_broker  # negative if clients lost

                st.markdown(
                    f"- **Brokerage P&L (broker view = A-Book − LP)**: "
                    f"`{fmt(brokerage_broker)}`"
                )
                st.markdown(
                    f"- **Brokerage P&L (client view = LP − A-Book)**: "
                    f"`{fmt(brokerage_client)}`  ← this will be **negative** when "
                    f"overall the clients are losing."
                )

            # GROUPS TAB
            with tab_groups:
                st.subheader("Group-wise summary")
                st.dataframe(group_df, use_container_width=True, height=420)

                st.write("")
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

            # ------------------------------------------------------------------
            # EXCEL EXPORT
            # ------------------------------------------------------------------
            st.markdown(
                "<div class='section-pill'><span>4</span> Export</div>",
                unsafe_allow_html=True,
            )
            st.subheader("Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
                lp_pnl = lp_close - lp_open - lp_net_dp
                brokerage_broker = pnl_a - lp_pnl
                brokerage_client = -brokerage_broker

                abook_lp_df = pd.DataFrame(
                    {
                        "Metric": [
                            "Client_A_Book_PnL",
                            "LP_Opening_Equity",
                            "LP_Closing_Equity",
                            "LP_NET_DP_WD",
                            "LP_PnL",
                            "Brokerage_PnL_BrokerView",
                            "Brokerage_PnL_ClientView",
                        ],
                        "Value": [
                            pnl_a,
                            lp_open,
                            lp_close,
                            lp_net_dp,
                            lp_pnl,
                            brokerage_broker,
                            brokerage_client,
                        ],
                    }
                )
                abook_lp_df.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
