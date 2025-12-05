import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP
# ---------------------------------------------------------
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Simple light theme styling
st.markdown(
    """
<style>
body, .main {
    background-color: #f7f7fb;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
}
.report-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    border: 1px solid #e5e7eb;
}
.metric-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 0.75rem 1rem;
    border: 1px solid #e5e7eb;
}
.metric-label {
    font-size: 0.8rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.metric-value {
    font-size: 1.2rem;
    font-weight: 600;
    margin-top: 0.15rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("📊 Client P&L Monitoring")
st.caption(
    "Upload your daily MT5 exports to generate account-wise and group-wise P&L with A-Book vs B-Book comparison."
)

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    Columns (0-based index):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume full lots (I)            [optional]
        9: Volume in+out deals (J)         [used for Closed Lots]
        10: Commission (K)
        12: Swap (M)
    We group by Login because there may be multiple rows per account.
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
        raise ValueError("Summary sheet must have at least 13 columns (up to column M).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    # Full volume (optional)
    df["VolumeFull"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    # Volume in+out (column J) used for Closed Lots
    df["VolumeInOut"] = pd.to_numeric(raw.iloc[:, 9], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 12], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "VolumeFull", "VolumeInOut", "Commission", "Swap"]
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
    equity_col = find_col(["equity"], 9)  # J ~ index 9
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


def load_accounts(file) -> pd.DataFrame:
    """
    Accounts mapping:
      - Login
      - Group
    Supports CSV or Excel.
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
        raise ValueError("Accounts file must contain a 'Login' column.")
    if "Group" not in df.columns:
        raise ValueError("Accounts file must contain a 'Group' column.")

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def classify_book_type(group: str) -> str:
    """
    A/B-book detection based on group text:
      - contains '_A'  -> A-Book
      - contains '_B'  -> B-Book
      - else           -> Unknown
    """
    if not isinstance(group, str):
        return "Unknown"
    g = group.upper()
    if "_A" in g:
        return "A-Book"
    if "_B" in g:
        return "B-Book"
    return "Unknown"


def build_report(summary_df, closing_df, opening_df, accounts_df, eod_label: str):
    """
    Combine all sheets & compute per-account metrics.

    Confirmed formulas:
      NET DP/WD   = Deposit − Withdrawal
      NET PNL USD = Closing Equity − Opening Equity − NET DP/WD
                  = CE − OE − (Deposit − Withdrawal)
      Closed Lots = VolumeInOut / 2
    """
    # Base from closing equity
    report = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()

    # Merge opening equity
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    report = report.merge(
        open_renamed[["Login", "Opening Equity"]],
        on="Login",
        how="left",
    )

    # Merge summary (cash & volume)
    report = report.merge(summary_df, on="Login", how="left")

    # Merge accounts (group)
    report = report.merge(accounts_df, on="Login", how="left")

    # Ensure numeric
    for col in [
        "Closing Equity",
        "Opening Equity",
        "Deposit",
        "Withdrawal",
        "VolumeFull",
        "VolumeInOut",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots: in+out volume / 2
    report["Closed Lots"] = report["VolumeInOut"] / 2.0

    # NET DP/WD (cash flow)
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL USD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # A/B book classification
    report["Type"] = report["Group"].apply(classify_book_type)

    # Label with EOD date text
    report["EOD Closing Equity Date"] = eod_label

    # Final ordered columns
    final_cols = [
        "Login",
        "Group",
        "Type",
        "Closed Lots",
        "NET DP/WD",
        "Currency",
        "NET PNL USD",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "Opening Equity",
        "Closing Equity",
        "EOD Closing Equity Date",
    ]
    final = report[final_cols].copy().sort_values("Login").reset_index(drop=True)
    return final


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate metrics per group and type."""
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
    """Aggregate metrics for A-Book vs B-Book vs Unknown."""
    book = (
        account_df.groupby("Type")
        .agg(
            Accounts=("Login", "nunique"),
            Closed_Lots=("Closed Lots", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
        )
        .reset_index()
    )
    return book


# ---------------------------------------------------------
# FILE UPLOAD UI + EOD LABEL
# ---------------------------------------------------------
st.markdown("### 1️⃣ Upload MT5 files")

eod_label = st.text_input(
    "EOD Closing Equity Date (this text will also be stored in the Excel report)",
    placeholder="e.g. 2025-12-02 EOD",
)

upload_container = st.container()
with upload_container:
    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)

    with c1:
        summary_file = st.file_uploader(
            "Sheet 1 – Summary / Transactions",
            type=["xlsx", "xls", "csv"],
            key="summary",
            help="Includes Deposit, Withdrawal, Volume (J column for in+out), Commission, Swap.",
        )
    with c2:
        closing_file = st.file_uploader(
            "Sheet 2 – Closing Equity (EOD for report period)",
            type=["xlsx", "xls"],
            key="closing",
            help="Daily report equity snapshot (EOD) for your closing date.",
        )
    with c3:
        opening_file = st.file_uploader(
            "Sheet 3 – Opening Equity (previous EOD)",
            type=["xlsx", "xls"],
            key="opening",
            help="Previous EOD equity snapshot (used as opening equity).",
        )
    with c4:
        accounts_file = st.file_uploader(
            "Accounts mapping (Login → Group)",
            type=["xlsx", "xls", "csv"],
            key="accounts",
            help="Use Accounts.csv or Excel with Login & Group columns.",
        )

st.markdown("---")

# ---------------------------------------------------------
# MAIN ACTION
# ---------------------------------------------------------
if st.button("🚀 Generate report"):
    if not (summary_file and closing_file and opening_file and accounts_file):
        st.error("Please upload all four files before generating the report.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text (for report labelling).")
    else:
        try:
            with st.spinner("Reading files and calculating P&L…"):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)
                accounts_df = load_accounts(accounts_file)

                account_df = build_report(
                    summary_df=summary_df,
                    closing_df=closing_df,
                    opening_df=opening_df,
                    accounts_df=accounts_df,
                    eod_label=eod_label,
                )

                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # ---------------- KPIs ----------------
            st.markdown("### 2️⃣ Overview")

            kcol1, kcol2, kcol3, kcol4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with kcol1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{int(total_clients)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with kcol2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{total_closed_lots:,.2f}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with kcol3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{net_pnl:,.2f}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with kcol4:
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

            # Simple bar chart Profit vs Loss
            chart_data = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.markdown("### 3️⃣ Profit vs loss chart")
            st.bar_chart(chart_data)

            # ---------------- A-book vs B-book summary ----------------
            st.markdown("### 4️⃣ A-Book vs B-Book summary")
            st.dataframe(book_df, use_container_width=True)

            # Your requested formula:
            # Client P&L = A-Book PNL − |B-Book PNL|
            pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            client_net_from_ab = pnl_a - abs(pnl_b)   # matches example 1516.36 - 7514.17 = -5997.81

            if client_net_from_ab > 0:
                status_text = "profit"
            elif client_net_from_ab < 0:
                status_text = "loss"
            else:
                status_text = "breakeven"

            st.markdown(
                f"**Client P&L from A-Book and B-Book (A − |B|):** "
                f"{client_net_from_ab:,.2f} ({status_text})"
            )

            # ---------------- Top gainers / losers (accounts) ----------------
            st.markdown("### 5️⃣ Top 10 accounts")

            col_g, col_l = st.columns(2)
            top_gainers = account_df.sort_values("NET PNL USD", ascending=False).head(10)
            top_losers = account_df.sort_values("NET PNL USD", ascending=True).head(10)

            gain_cols = [
                "Login",
                "Group",
                "Type",
                "Opening Equity",
                "Closing Equity",
                "NET PNL USD",
                "Closed Lots",
                "NET DP/WD",
            ]

            with col_g:
                st.markdown("**Top 10 gainers (accounts)**")
                st.dataframe(top_gainers[gain_cols], use_container_width=True)

            with col_l:
                st.markdown("**Top 10 losers (accounts)**")
                st.dataframe(top_losers[gain_cols], use_container_width=True)

            # ---------------- Group-wise summary & top groups ----------------
            st.markdown("### 6️⃣ Group-wise summary")

            st.dataframe(group_df, use_container_width=True)

            gcol1, gcol2 = st.columns(2)
            with gcol1:
                st.markdown("**Top 5 profit groups**")
                top_groups_profit = group_df.sort_values("NET_PNL_USD", ascending=False).head(5)
                st.dataframe(top_groups_profit, use_container_width=True)

            with gcol2:
                st.markdown("**Top 5 loss groups**")
                top_groups_loss = group_df.sort_values("NET_PNL_USD", ascending=True).head(5)
                st.dataframe(top_groups_loss, use_container_width=True)

            # ---------------- Download Excel ----------------
            st.markdown("### 7️⃣ Download report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                # Only the three useful sheets – no blank/Info sheet
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")
            output.seek(0)

            st.download_button(
                label="⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
