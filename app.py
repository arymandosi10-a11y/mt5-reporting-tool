import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP & THEME
# ---------------------------------------------------------
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for a more modern UI
st.markdown(
    """
<style>
body, .main {
    background-color: #050816;
    color: #e5e7eb;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
h1, h2, h3, h4 {
    color: #f9fafb;
}
.section-card {
    background: radial-gradient(circle at top left, #1f2937, #020617 60%);
    border-radius: 18px;
    padding: 1.25rem 1.5rem;
    border: 1px solid rgba(148,163,184,0.35);
    box-shadow: 0 18px 45px rgba(15,23,42,0.55);
}
.metric-card {
    background: linear-gradient(135deg, #111827, #020617);
    border-radius: 16px;
    padding: 0.85rem 1.1rem;
    border: 1px solid rgba(75,85,99,0.7);
}
.metric-label {
    font-size: 0.78rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.metric-value {
    font-size: 1.3rem;
    font-weight: 600;
    margin-top: 0.15rem;
    color: #e5e7eb;
}
.small-caption {
    font-size: 0.78rem;
    color: #9ca3af;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 0.25rem;
}
.stTabs [data-baseweb="tab"] {
    background-color: rgba(15,23,42,0.9);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    color: #9ca3af;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, #22c55e, #06b6d4);
    color: #020617;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<h1>📈 Client P&L Command Center</h1>",
    unsafe_allow_html=True,
)
st.caption(
    "Clean MT5 monitoring for A-Book / B-Book / Hybrid clients – with book switches and LP comparison."
)

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Expected column positions (0-based index):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        7: Closed volume (H)          -> will be divided by 2 for Closed Lots
        10: Commission (K)
        12: Swap (M)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 13:
        raise ValueError(
            "Summary sheet must have at least 13 columns (up to column M)."
        )

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    # Closed volume from column H
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
    Expect columns: Login, Equity, Currency.
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
    """Read a book-accounts file: expect Login and optional Group."""
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


def build_report(summary_df, closing_df, opening_df, accounts_df, shift_row, eod_label):
    """
    Merge all sources and calculate account-level metrics.

    If a single account switch (shift_row) is provided, we store:
      - ShiftEquity
      - ShiftFromType
      - ShiftToType
    on that login.
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    # Only accounts we care about
    report = accounts_df.merge(base, on="Login", how="left")

    # numeric safety
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

    # Closed lots from summary H column
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # NET DP/WD
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL USD (total for the day)
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # NET PNL %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Book switch (one account only, from the UI)
    report["ShiftEquity"] = np.nan
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    if shift_row is not None:
        login_val = int(shift_row["Login"])
        mask = report["Login"] == login_val
        if mask.any():
            report.loc[mask, "ShiftEquity"] = float(shift_row["ShiftEquity"])
            report.loc[mask, "ShiftFromType"] = shift_row["FromType"]
            report.loc[mask, "ShiftToType"] = shift_row["ToType"]
            # override final book for that account
            report.loc[mask, "Type"] = shift_row["ToType"]

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


def split_pnl_by_book(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Allocate daily P&L between books, splitting accounts that switched book using ShiftEquity.

    For an account that switched from OLD to NEW with ShiftEquity S:

      Total P&L = CE - OE - NetDPWD
      P&L_NEW   = CE - S                       (moves in new book)
      P&L_OLD   = Total P&L - P&L_NEW

    All closed lots are counted in the final (NEW) book.
    """
    rows = []
    for _, r in account_df.iterrows():
        net_pnl = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        closing = r["Closing Equity"]
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_eq = r["ShiftEquity"]
        from_type = r["ShiftFromType"]
        to_type = r["ShiftToType"]

        # no switch
        if pd.isna(shift_eq) or pd.isna(to_type) or str(from_type) == str(to_type):
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
            continue

        # switched
        pnl_new = closing - shift_eq
        pnl_old = net_pnl - pnl_new

        # contribution to old book (no account count)
        rows.append(
            {
                "Type": from_type,
                "Accounts": 0,
                "Closed_Lots": 0.0,
                "NET_PNL_USD": pnl_old,
            }
        )
        # contribution to new book (account counted here, all lots)
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
# SIDEBAR: OPTIONAL LP P&L FOR A-BOOK
# ---------------------------------------------------------
with st.sidebar:
    st.header("🏦 A-Book LP P&L (optional)")
    st.caption(
        "Fill this to see A-Book brokerage vs LP.\n"
        "Formula: LP P&L = Close − Open − Net D/W."
    )
    lp_open = st.number_input("LP opening equity", value=0.0, step=100.0)
    lp_close = st.number_input("LP closing equity", value=0.0, step=100.0)
    lp_net_dp = st.number_input(
        "LP net D/W (Deposit − Withdrawal)", value=0.0, step=100.0
    )

# ---------------------------------------------------------
# FILE UPLOAD UI
# ---------------------------------------------------------
st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown("### 1️⃣ Upload MT5 files")

eod_label = st.text_input(
    "EOD Closing Equity Date (stored in the Excel report)",
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
        help="Includes Deposit, Withdrawal, Closed volume (H), Commission, Swap.",
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

st.markdown("#### 🔁 Single account book switch (optional)")
st.markdown(
    '<span class="small-caption">'
    "Use this if one login moved from one book to another during this day. "
    "We will split P&L between old & new book using the shift equity."
    "</span>",
    unsafe_allow_html=True,
)

switch_enabled = st.checkbox("Enable single account switch in this report")

DIRECTION_OPTIONS = {
    "A-Book → B-Book": ("A-Book", "B-Book"),
    "A-Book → Hybrid": ("A-Book", "Hybrid"),
    "B-Book → A-Book": ("B-Book", "A-Book"),
    "B-Book → Hybrid": ("B-Book", "Hybrid"),
    "Hybrid → A-Book": ("Hybrid", "A-Book"),
    "Hybrid → B-Book": ("Hybrid", "B-Book"),
}

switch_row = None
if switch_enabled:
    sc1, sc2, sc3 = st.columns([1.2, 0.8, 1.0])
    with sc1:
        direction_label = st.selectbox(
            "Switch direction",
            list(DIRECTION_OPTIONS.keys()),
        )
    with sc2:
        switch_login = st.text_input("Login to switch")
    with sc3:
        switch_equity = st.number_input(
            "Equity at moment of switch", value=0.0, step=100.0
        )

    if switch_login.strip():
        try:
            login_val = int(str(switch_login).strip())
            from_type, to_type = DIRECTION_OPTIONS[direction_label]
            switch_row = {
                "Login": login_val,
                "FromType": from_type,
                "ToType": to_type,
                "ShiftEquity": float(switch_equity),
            }
        except ValueError:
            st.warning("⚠️ Could not read the switch login as a number – switch ignored.")

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("---")

# ---------------------------------------------------------
# MAIN ACTION
# ---------------------------------------------------------
if st.button("🚀 Generate report", type="primary"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
    else:
        try:
            with st.spinner("Crunching numbers and building dashboards…"):
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

                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, switch_row, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = split_pnl_by_book(account_df)

            # =================== TABS ===================
            tab1, tab2, tab3, tab4 = st.tabs(
                ["🏠 Overview", "📋 Accounts & Groups", "📚 Books & Switch", "🏦 A-Book vs LP"]
            )

            # ------------- TAB 1: OVERVIEW -------------
            with tab1:
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("#### Global snapshot")

                k1, k2, k3, k4 = st.columns(4)
                total_clients = account_df["Login"].nunique()
                total_closed_lots = account_df["Closed Lots"].sum()
                net_pnl = account_df["NET PNL USD"].sum()
                total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
                total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

                with k1:
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(total_clients)}</div>', unsafe_allow_html=True)
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

                # Profit vs loss bar
                chart_data = pd.DataFrame(
                    {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
                ).set_index("Side")
                st.markdown("##### P&L split")
                st.bar_chart(chart_data)
                st.markdown("</div>", unsafe_allow_html=True)

            # ------------- TAB 2: ACCOUNTS & GROUPS -------------
            with tab2:
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("#### Account-level P&L")
                st.dataframe(account_df, use_container_width=True, height=420)

                st.markdown("#### Top 10 accounts")
                gcol, lcol = st.columns(2)
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
                with gcol:
                    st.markdown("**Top 10 gainers**")
                    top_gainers = account_df.sort_values("NET PNL USD", ascending=False).head(10)
                    st.dataframe(top_gainers[cols_show], use_container_width=True)
                with lcol:
                    st.markdown("**Top 10 losers**")
                    top_losers = account_df.sort_values("NET PNL USD", ascending=True).head(10)
                    st.dataframe(top_losers[cols_show], use_container_width=True)

                st.markdown("---")
                st.markdown("#### Group-wise summary")
                st.dataframe(group_df, use_container_width=True, height=420)

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
                st.markdown("</div>", unsafe_allow_html=True)

            # ------------- TAB 3: BOOKS & SWITCH -------------
            with tab3:
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("#### A-Book / B-Book / Hybrid summary")
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

                # If a switch was entered, explain the math
                if switch_row is not None:
                    login_val = int(switch_row["Login"])
                    row = account_df[account_df["Login"] == login_val]
                    if not row.empty:
                        r = row.iloc[0]
                        oe = r['Opening Equity']
                        ce = r['Closing Equity']
                        netdp = r['NET DP/WD']
                        total = r['NET PNL USD']
                        s_eq = r['ShiftEquity']
                        pnl_new = ce - s_eq
                        pnl_old = total - pnl_new
                        st.markdown("---")
                        st.markdown(f"**Switch explanation for login {login_val}:**")
                        st.markdown(
                            f"- Opening equity: {oe:,.2f} → Shift equity: {s_eq:,.2f} → Closing equity: {ce:,.2f}"
                        )
                        st.markdown(
                            f"- Total daily P&L = CE − OE − NetDP/WD = "
                            f"{ce:,.2f} − {oe:,.2f} − {netdp:,.2f} = {total:,.2f}"
                        )
                        st.markdown(
                            f"- New book P&L = CE − Shift = {ce:,.2f} − {s_eq:,.2f} = **{pnl_new:,.2f}**"
                        )
                        st.markdown(
                            f"- Old book P&L = Total − New = {total:,.2f} − {pnl_new:,.2f} = **{pnl_old:,.2f}**"
                        )
                st.markdown("</div>", unsafe_allow_html=True)

            # ------------- TAB 4: A-BOOK VS LP -------------
            with tab4:
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("#### A-Book vs LP – brokerage view")

                pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
                lp_pnl = lp_close - lp_open - lp_net_dp
                brokerage_broker = pnl_a - lp_pnl           # broker perspective
                brokerage_client = lp_pnl - pnl_a           # client perspective (opposite)

                st.markdown(f"- Client A-Book P&L: **{pnl_a:,.2f}**")
                st.markdown(
                    f"- LP P&L (Close − Open − Net D/W): "
                    f"**{lp_close:,.2f} − {lp_open:,.2f} − {lp_net_dp:,.2f} = {lp_pnl:,.2f}**"
                )
                st.markdown(
                    f"- Brokerage P&L (broker view = A-Book − LP): **{brokerage_broker:,.2f}**"
                )
                st.markdown(
                    f"- Brokerage P&L (client view = LP − A-Book): **{brokerage_client:,.2f}**"
                )

                st.markdown("---")
                st.markdown("You will also get these numbers in Excel on the *Abook_vs_LP* sheet.")
                st.markdown("</div>", unsafe_allow_html=True)

            # ---------------- Download Excel ----------------
            st.markdown("### 💾 Download Excel report")
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # A-book vs LP sheet
                pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
                lp_pnl = lp_close - lp_open - lp_net_dp
                brokerage_broker = pnl_a - lp_pnl
                brokerage_client = lp_pnl - pnl_a

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
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
