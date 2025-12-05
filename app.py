import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# PAGE + THEME
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS (simple modern look)
st.markdown(
    """
<style>
body, .main {
    background-color: #0f172a;
    color: #e5e7eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
}
h1, h2, h3, h4 {
    color: #e5e7eb;
}
.section-card {
    background: #020617;
    border-radius: 16px;
    padding: 1.25rem 1.5rem;
    border: 1px solid #1f2937;
    box-shadow: 0 18px 60px rgba(15,23,42,0.6);
}
.metric-card {
    background: radial-gradient(circle at top left, #22c55e22, #020617);
    border-radius: 16px;
    padding: 0.9rem 1.1rem;
    border: 1px solid #1f2937;
}
.metric-label {
    font-size: 0.75rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.metric-value {
    font-size: 1.3rem;
    font-weight: 600;
    margin-top: 0.1rem;
}
.small-caption {
    font-size: 0.8rem;
    color: #9ca3af;
}
.stButton>button {
    border-radius: 999px;
    padding: 0.6rem 1.4rem;
    border: 1px solid #22c55e;
    background: linear-gradient(90deg,#22c55e,#16a34a);
    color: white;
    font-weight: 600;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    "<h1>📊 Client P&L Monitoring Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='small-caption'>Daily MT5 reporting with A-Book / B-Book / Hybrid split, book switching and A-Book vs LP brokerage.</p>",
    unsafe_allow_html=True,
)

# =========================================================
# HELPERS – FILE LOADERS
# =========================================================
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Expected column positions (0-based):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        7: Closed volume (H)  -> used for Closed Lots (volume / 2)
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
        raise ValueError("Summary sheet must have at least 13 columns (up to M).")

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
    Expect columns: Login, Equity, Currency (optional).
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
    equity_col = find_col(["equity"], 9)  # usually J
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
    Read a book-accounts file.
    Expect columns:
      - Login (required)
      - Group (optional)
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
    df["OrigType"] = book_type   # starting book
    df["Type"] = book_type       # final book (can change with switch)
    return df


# =========================================================
# CORE CALCULATIONS
# =========================================================
def build_report(summary_df, closing_df, opening_df, accounts_df, shift_df, eod_label):
    """
    Build per-account metrics:

    NET DP/WD   = Deposit − Withdrawal
    NET PNL USD = Closing Equity − Opening Equity − NET DP/WD
    Closed Lots = ClosedVolume / 2
    NET PNL %   = NET PNL USD / |Opening Equity|
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]],
                      on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    # Start from accounts list — only accounts we care about
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

    # Closed lots from Summary H column
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # Net deposits / withdrawals
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # Net PnL
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Net PnL %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # ----- Apply optional shift (single login) -----
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan

    if shift_df is not None and not shift_df.empty:
        # merge by Login; this will add FromType, ToType, ShiftEquity
        report = report.merge(shift_df, on="Login", how="left")
        # Only override rows that have a ToType
        has_shift = report["ToType"].notna()
        report.loc[has_shift, "ShiftFromType"] = report.loc[has_shift, "FromType"]
        report.loc[has_shift, "ShiftToType"] = report.loc[has_shift, "ToType"]
        report.loc[has_shift, "ShiftEquity"] = report.loc[has_shift, "ShiftEquity"]
        report.loc[has_shift, "Type"] = report.loc[has_shift, "ToType"]

        # Clean helper columns
        report = report.drop(columns=[c for c in ["FromType", "ToType"] if c in report.columns])

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


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Allocate P&L between books, splitting accounts that switched book.

    For switched account (ShiftEquity known, ShiftFromType -> ShiftToType):
      total_pnl = NET PNL USD
      pnl_new   = ClosingEquity − ShiftEquity
      pnl_old   = total_pnl − pnl_new

    The account gets counted in Accounts column of NEW book, not old one.
    """
    rows = []

    for _, r in account_df.iterrows():
        net_pnl = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        closing = r["Closing Equity"]
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_eq = r["ShiftEquity"]
        shift_from = r["ShiftFromType"]
        shift_to = r["ShiftToType"]

        # No shift or OrigType == final_type  → normal
        if pd.isna(shift_eq) or pd.isna(shift_to) or orig_type == final_type:
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
        else:
            # Split: old vs new books
            pnl_new = closing - shift_eq
            pnl_old = net_pnl - pnl_new

            # contribution for old book (no account count / lots)
            rows.append(
                {
                    "Type": shift_from,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            # contribution for new book (account counted here)
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


# =========================================================
# SIDEBAR – LP P&L
# =========================================================
with st.sidebar:
    st.markdown("### 🧮 A-Book LP P&L (optional)")
    st.markdown(
        "<p class='small-caption'>Fill this to see brokerage P&L = Client A-Book − LP.</p>",
        unsafe_allow_html=True,
    )
    lp_open = st.number_input("LP opening equity", value=0.0, step=100.0)
    lp_close = st.number_input("LP closing equity", value=0.0, step=100.0)
    lp_net_dp = st.number_input("LP net D/W (Deposit − Withdrawal)",
                                value=0.0, step=100.0)

# =========================================================
# SECTION 1 – FILE UPLOADS & SWITCH UI
# =========================================================
st.markdown("## 1️⃣ Data inputs")
section1 = st.container()
with section1:
    st.markdown("<div class='section-card'>", unsafe_allow_html=True)

    eod_label = st.text_input(
        "EOD Closing Equity Date (will be stored in Excel & table)",
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
            help="Contains Deposit, Withdrawal, Closed volume (H), Commission, Swap.",
        )
    with c2:
        closing_file = st.file_uploader(
            "Sheet 2 – Closing Equity (EOD for report date)",
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
            "A-Book accounts (Login & optional Group)",
            type=["xlsx", "xls", "csv"],
            key="abook",
        )
    with c6:
        b_book_file = st.file_uploader(
            "B-Book accounts (Login & optional Group)",
            type=["xlsx", "xls", "csv"],
            key="bbook",
        )
    with c7:
        hybrid_file = st.file_uploader(
            "Hybrid accounts (Login & optional Group – optional)",
            type=["xlsx", "xls", "csv"],
            key="hybrid",
        )

    st.markdown("---")
    st.markdown("#### 🔁 Single account book switch (optional)")

    DIRECTION_OPTIONS = {
        "A Book → B Book": ("A-Book", "B-Book"),
        "A Book → Hybrid": ("A-Book", "Hybrid"),
        "B Book → A Book": ("B-Book", "A-Book"),
        "B Book → Hybrid": ("B-Book", "Hybrid"),
        "Hybrid → A Book": ("Hybrid", "A-Book"),
        "Hybrid → B Book": ("Hybrid", "B-Book"),
    }

    switch_enabled = st.checkbox("Enable one account switch override in this report")
    switch_direction = None
    switch_login = None
    switch_equity = None

    if switch_enabled:
        sc1, sc2, sc3 = st.columns([2, 1, 1])
        with sc1:
            switch_direction = st.selectbox(
                "Switch direction",
                list(DIRECTION_OPTIONS.keys()),
            )
        with sc2:
            switch_login = st.text_input("Login to switch")
        with sc3:
            switch_equity = st.number_input(
                "Equity at moment of switch",
                value=0.0,
                step=100.0,
                help="Example: 15000 if you moved the account when equity was 15k.",
            )

    st.markdown("</div>", unsafe_allow_html=True)

# =========================================================
# MAIN ACTION
# =========================================================
st.markdown("## 2️⃣ Generate report")

if st.button("🚀 Run P&L engine"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of A-Book / B-Book / Hybrid account files.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
    else:
        try:
            with st.spinner("Reading files and calculating P&L…"):

                # ---- Load source files ----
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

                # ----- Optional single-login switch as DataFrame -----
                shift_df = None
                if switch_enabled and switch_login and switch_login.strip():
                    try:
                        login_val = int(str(switch_login).strip())
                        from_type, to_type = DIRECTION_OPTIONS[switch_direction]
                        shift_df = pd.DataFrame(
                            [
                                {
                                    "Login": login_val,
                                    "FromType": from_type,
                                    "ToType": to_type,
                                    "ShiftEquity": float(switch_equity),
                                }
                            ]
                        )
                    except Exception:
                        st.warning(
                            "Could not read the switch login as a number – ignoring the switch override."
                        )
                        shift_df = None

                # ---- Build account, group & book reports ----
                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, shift_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # =====================================================
            # 3 – KPIs
            # =====================================================
            st.markdown("## 3️⃣ Daily overview")
            box = st.container()
            with box:
                st.markdown("<div class='section-card'>", unsafe_allow_html=True)

                k1, k2, k3, k4 = st.columns(4)
                total_clients = account_df["Login"].nunique()
                total_closed_lots = account_df["Closed Lots"].sum()
                net_pnl = account_df["NET PNL USD"].sum()
                total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
                total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

                with k1:
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(total_clients)}</div>',
                                unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                with k2:
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="metric-value">{total_closed_lots:,.2f}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown("</div>", unsafe_allow_html=True)

                with k3:
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.markdown('<div class="metric-label">Net client P&L</div>',
                                unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="metric-value">{net_pnl:,.2f}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown("</div>", unsafe_allow_html=True)

                with k4:
                    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                    st.markdown('<div class="metric-label">Profit vs loss</div>',
                                unsafe_allow_html=True)
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

                # simple bar chart
                chart_data = pd.DataFrame(
                    {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
                ).set_index("Side")
                st.markdown("<br>", unsafe_allow_html=True)
                st.bar_chart(chart_data)
                st.markdown("</div>", unsafe_allow_html=True)

            # =====================================================
            # 4 – Full account P&L
            # =====================================================
            st.markdown("## 4️⃣ Full account P&L")
            st.markdown(
                "<div class='section-card'>",
                unsafe_allow_html=True,
            )
            st.dataframe(account_df, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # =====================================================
            # 5 – Book summary
            # =====================================================
            st.markdown("## 5️⃣ A-Book / B-Book / Hybrid summary")
            st.markdown("<div class='section-card'>", unsafe_allow_html=True)
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
            st.markdown("</div>", unsafe_allow_html=True)

            # =====================================================
            # 6 – Top groups & top accounts
            # =====================================================
            st.markdown("## 6️⃣ Top groups & accounts")

            st.markdown("<div class='section-card'>", unsafe_allow_html=True)
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

            st.markdown("---")

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
            ac1, ac2 = st.columns(2)
            with ac1:
                st.markdown("**Top 10 gainers (accounts)**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=False).head(10)[
                        cols_show
                    ],
                    use_container_width=True,
                )
            with ac2:
                st.markdown("**Top 10 losers (accounts)**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=True).head(10)[
                        cols_show
                    ],
                    use_container_width=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

            # =====================================================
            # 7 – A-Book vs LP brokerage
            # =====================================================
            st.markdown("## 7️⃣ A-Book vs LP brokerage")

            st.markdown("<div class='section-card'>", unsafe_allow_html=True)
            st.markdown(f"- Client A-Book P&L: **{pnl_a:,.2f}**")

            lp_pnl = lp_close - lp_open - lp_net_dp
            st.markdown(
                f"- LP P&L (Close − Open − Net D/W): **{lp_pnl:,.2f}**"
            )

            # Broker view: positive = broker earned; negative = broker lost
            brokerage_broker = pnl_a - lp_pnl
            # Client view: negative = cost to broker becomes profit to LP
            brokerage_client = -brokerage_broker

            st.markdown(
                f"- Brokerage P&L (broker view = A-Book − LP): **{brokerage_broker:,.2f}**"
            )
            st.markdown(
                f"- Brokerage P&L (client view = LP − A-Book): **{brokerage_client:,.2f}**"
            )
            st.markdown("</div>", unsafe_allow_html=True)

            # =====================================================
            # 8 – Excel export
            # =====================================================
            st.markdown("## 8️⃣ Download Excel report")
            st.markdown("<div class='section-card'>", unsafe_allow_html=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

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

            st.markdown("</div>", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
