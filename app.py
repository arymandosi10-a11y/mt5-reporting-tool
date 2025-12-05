import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP
# ---------------------------------------------------------
st.set_page_config(
    page_title="MT5 Reporting Tool",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Simple light theme override
st.markdown("""
<style>
:root {
    --primary-color:#4a90e2;
    --background-color:#ffffff;
    --text-color:#000000;
    --secondary-background-color:#f2f2f7;
}
.main {
    background-color: var(--background-color);
    color: var(--text-color);
}
</style>
""", unsafe_allow_html=True)


st.title("📊 FX Client P&L & Group Monitoring")

st.caption("Upload MT5 exports to generate daily / weekly / monthly client and group P&L.")


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    Expected columns by position (0-based index):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume (I) - full lots, will be /2 for closed lots
        10: Commission (K)
        12: Swap (M)
    We group by Login because there may be multiple transactions.
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
        raise ValueError("Summary sheet does not have at least 13 columns (A–M).")

    summary = pd.DataFrame()
    summary["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    summary["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    summary["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    summary["VolumeFull"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    summary["Commission"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)
    summary["Swap"] = pd.to_numeric(raw.iloc[:, 12], errors="coerce").fillna(0.0)

    grouped = (
        summary.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "VolumeFull", "Commission", "Swap"]
        ].sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD Equity)
    We expect columns: Login, Equity, Currency.
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
    equity_col = find_col(["equity"], 9)   # J is index 9
    currency_col = find_col(["currency"], None)

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

    lower_cols = [c.lower() for c in df.columns]
    if "login" not in df.columns and "login" in lower_cols:
        df = df.rename(columns={c: "Login" for c in df.columns if c.lower() == "login"})
    if "group" not in df.columns and "group" in lower_cols:
        df = df.rename(columns={c: "Group" for c in df.columns if c.lower() == "group"})

    if "Login" not in df.columns:
        raise ValueError("Accounts file must contain a 'Login' column.")
    if "Group" not in df.columns:
        raise ValueError("Accounts file must contain a 'Group' column.")

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def classify_book_type(group: str) -> str:
    """
    A/B book detection:
    - If group text contains '_A' -> 'A-Book'
    - If group text contains '_B' -> 'B-Book'
    - Else -> 'Unknown'
    """
    if not isinstance(group, str):
        return "Unknown"
    g = group.upper()
    if "_A" in g:
        return "A-Book"
    if "_B" in g:
        return "B-Book"
    return "Unknown"


def build_report(summary_df, closing_df, opening_df, accounts_df, report_type, report_date):
    """
    Combine all sheets & compute:
    - Closed Lots
    - NET DP/WD = Deposit - Withdrawal
    - NET PNL USD = Closing Equity - Opening Equity - (NET DP/WD)
    - Group & Type (A/B Book)
    Adds Report Type & Date columns.
    """
    report = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()

    # Opening equity (earlier EOD)
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    report = report.merge(
        open_renamed[["Login", "Opening Equity"]],
        on="Login",
        how="left",
    )

    # Merge summary & accounts
    report = report.merge(summary_df, on="Login", how="left")
    report = report.merge(accounts_df, on="Login", how="left")

    # Ensure numeric
    for col in [
        "Closing Equity",
        "Opening Equity",
        "Deposit",
        "Withdrawal",
        "VolumeFull",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots = full volume / 2
    report["Closed Lots"] = report["VolumeFull"] / 2.0

    # NET DP/WD (cash flow)
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL = Closing Equity - Opening Equity - (NET DP/WD)
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Book type from Group
    report["Type"] = report["Group"].apply(classify_book_type)

    # Attach report meta
    report["Report Type"] = report_type
    report["Report Date"] = pd.to_datetime(report_date)

    final_cols = [
        "Login",
        "Group",
        "Type",
        "Currency",
        "Closed Lots",
        "NET DP/WD",
        "NET PNL USD",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "Opening Equity",
        "Closing Equity",
        "Report Type",
        "Report Date",
    ]
    final = report[final_cols].copy().sort_values("Login").reset_index(drop=True)
    return final


def build_group_summary(report_df: pd.DataFrame) -> pd.DataFrame:
    """
    Group-wise aggregation:
    - Sum Closed Lots, NET DP/WD, NET PNL
    - Sum Opening & Closing Equity
    """
    group_df = (
        report_df.groupby(["Group", "Type", "Currency"], dropna=False)
        .agg(
            Total_Closed_Lots=("Closed Lots", "sum"),
            Total_NET_DPWD=("NET DP/WD", "sum"),
            Total_NET_PNL_USD=("NET PNL USD", "sum"),
            Total_Opening_Equity=("Opening Equity", "sum"),
            Total_Closing_Equity=("Closing Equity", "sum"),
            Accounts=("Login", "nunique"),
        )
        .reset_index()
    )
    return group_df


# ---------------------------------------------------------
# SIDEBAR – SETTINGS
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Report Settings")
    report_type = st.selectbox("Report type", ["Daily", "Weekly", "Monthly"])
    report_date = st.date_input("Report date")


# ---------------------------------------------------------
# FILE UPLOAD UI
# ---------------------------------------------------------
st.subheader("📥 Upload MT5 Files")

uc1, uc2 = st.columns(2)
uc3, uc4 = st.columns(2)

with uc1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
    )
with uc2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity",
        type=["xlsx", "xls"],
        key="closing",
    )
with uc3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity",
        type=["xlsx", "xls"],
        key="opening",
    )
with uc4:
    accounts_file = st.file_uploader(
        "Accounts mapping (Login → Group)",
        type=["xlsx", "xls", "csv"],
        key="accounts",
    )

st.markdown("---")

# ---------------------------------------------------------
# MAIN ACTION
# ---------------------------------------------------------
if st.button("🚀 Generate Report"):
    if not (summary_file and closing_file and opening_file and accounts_file):
        st.error("Please upload all four files before generating the report.")
    else:
        try:
            with st.spinner("Processing files & calculating P&L…"):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)
                accounts_df = load_accounts(accounts_file)

                report_df = build_report(
                    summary_df=summary_df,
                    closing_df=closing_df,
                    opening_df=opening_df,
                    accounts_df=accounts_df,
                    report_type=report_type,
                    report_date=report_date,
                )

                group_df = build_group_summary(report_df)

            # ---------- KPIs ----------
            st.success("Report generated successfully.")

            total_clients = report_df["Login"].nunique()
            total_closed_lots = report_df["Closed Lots"].sum()
            total_profit = report_df.loc[report_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = report_df.loc[report_df["NET PNL USD"] < 0, "NET PNL USD"].sum()
            net_pnl = report_df["NET PNL USD"].sum()

            total_profit_abs = float(total_profit)
            total_loss_abs = float(abs(total_loss))
            pnl_denominator = total_profit_abs + total_loss_abs

            if pnl_denominator > 0:
                profit_pct = (total_profit_abs / pnl_denominator) * 100.0
                loss_pct = (total_loss_abs / pnl_denominator) * 100.0
            else:
                profit_pct = 0.0
                loss_pct = 0.0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Clients", total_clients)
            k2.metric("Total Closed Lots", f"{total_closed_lots:,.2f}")
            k3.metric("Total Client Profit", f"{total_profit_abs:,.2f}")
            k4.metric("Total Client Loss", f"{-total_loss:,.2f}")

            st.markdown(
                f"**Net Client P&L:** {net_pnl:,.2f} • Profit share: {profit_pct:.1f}% • Loss share: {loss_pct:.1f}%"
            )

            # ---------- Profit vs Loss chart ----------
            chart_data = pd.DataFrame(
                {
                    "Side": ["Profit", "Loss"],
                    "Amount": [total_profit_abs, total_loss_abs],
                }
            )
            st.bar_chart(chart_data.set_index("Side")["Amount"])

            # ---------- Tabs for Accounts & Groups ----------
            tab_accounts, tab_groups = st.tabs(["👤 Accounts view", "📂 Groups view"])

            with tab_accounts:
                st.markdown("#### 🏆 Top 10 gainer accounts")
                gainers = report_df.sort_values("NET PNL USD", ascending=False).head(10)
                st.dataframe(
                    gainers[
                        ["Login", "Group", "Type", "NET PNL USD", "Closed Lots", "NET DP/WD"]
                    ],
                    use_container_width=True,
                )

                st.markdown("#### 💀 Top 10 loser accounts")
                losers = report_df.sort_values("NET PNL USD", ascending=True).head(10)
                st.dataframe(
                    losers[
                        ["Login", "Group", "Type", "NET PNL USD", "Closed Lots", "NET DP/WD"]
                    ],
                    use_container_width=True,
                )

                st.markdown("#### 📋 Account-level report (first 200 rows)")
                st.dataframe(report_df.head(200), use_container_width=True)

            with tab_groups:
                st.markdown("#### 📊 Group-wise summary")
                st.dataframe(group_df, use_container_width=True)

                st.markdown("#### 🏆 Top 5 profit groups")
                g_gainers = group_df.sort_values("Total_NET_PNL_USD", ascending=False).head(5)
                st.dataframe(g_gainers, use_container_width=True)

                st.markdown("#### 💀 Top 5 loss groups")
                g_losers = group_df.sort_values("Total_NET_PNL_USD", ascending=True).head(5)
                st.dataframe(g_losers, use_container_width=True)

            # ---------- Download Excel ----------
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
            output.seek(0)

            st.download_button(
                label="⬇️ Download full report (Excel)",
                data=output,
                file_name="FX_Client_PnL_and_Group_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
