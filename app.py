import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP – LIGHT, CLEAN UI
# ---------------------------------------------------------
st.set_page_config(
    page_title="MT5 Reporting Tool",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Simple light styling
st.markdown("""
<style>
:root {
    --primary-color:#2563eb;
    --background-color:#ffffff;
    --text-color:#111827;
    --card-bg:#f9fafb;
}
.main {
    background-color: var(--background-color);
    color: var(--text-color);
}
.block-container {
    padding-top: 1.5rem;
}
div.stMetric {
    background-color: var(--card-bg);
    padding: 0.75rem 0.75rem;
    border-radius: 0.75rem;
    border: 1px solid #e5e7eb;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 FX Broker Client P&L Monitoring Tool")

with st.expander("ℹ️ How to use (input format)", expanded=False):
    st.markdown(
        """
**You need 4 files (daily exports)**

1️⃣ **Sheet 1 – Summary / Transactions**  
   - Login (col A)  
   - Deposit = col **C**  
   - Withdrawal = col **F**  
   - Volume (full lots) = col **I**  → *we divide by 2 for Closed Lots*  
   - Commission = col **K**  
   - Swap = col **M**  
   - (Optional) Credit / Bonus columns if available – we auto-detect by header name.  
   > Profit & Date from this sheet are ignored.

2️⃣ **Sheet 2 – Closing Equity (EOD of report date)**  
   - Contains: Login, Equity (usually col J), Currency

3️⃣ **Sheet 3 – Opening Equity (previous day EOD)**  
   - Same format as Sheet 2

4️⃣ **Accounts file (Login → Group)**  
   - CSV or Excel with columns:  
     - Login  
     - Group (contains “_A” or “_B” for A-Book / B-Book)
        """
    )

st.markdown("---")

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    We use column positions:
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume (I) - full lots, will be /2 for closed lots
        10: Commission (K)
        12: Swap (M)

    PLUS (optional) Credit / Bonus columns if headers exist:
        - "credit in", "credit out", "bonus in", "bonus out"
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        # Many MT5 exports have headers on row 3 -> header=2
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 13:
        raise ValueError("Summary sheet does not have at least 13 columns (A–M).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    df["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["VolumeFull"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 12], errors="coerce").fillna(0.0)

    # Optional credit / bonus detection by header name
    cols_lower = {str(c).lower(): c for c in raw.columns}

    def sum_cols(contains_text_list):
        vals = None
        for key_lower, col_name in cols_lower.items():
            if any(txt in key_lower for txt in contains_text_list):
                col_vals = pd.to_numeric(raw[col_name], errors="coerce").fillna(0.0)
                vals = col_vals if vals is None else vals + col_vals
        if vals is None:
            return pd.Series(0.0, index=raw.index)
        return vals

    df["CreditIn"] = sum_cols(["credit in"])
    df["CreditOut"] = sum_cols(["credit out"])
    df["BonusIn"] = sum_cols(["bonus in"])
    df["BonusOut"] = sum_cols(["bonus out"])

    # Aggregate per Login
    grouped = (
        df.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "VolumeFull", "Commission", "Swap",
             "CreditIn", "CreditOut", "BonusIn", "BonusOut"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD Equity)
    Expect columns: Login, Equity, Currency (names may vary)
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
    if any("currency" in c for c in cols_lower):
        currency_col = df.columns[cols_lower.index("currency")]

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
        df = pd.read_excel(file, engine="openpyxl")

    # Normalize column names
    lower_map = {c.lower(): c for c in df.columns}
    if "login" in lower_map and "Login" not in df.columns:
        df = df.rename(columns={lower_map["login"]: "Login"})
    if "group" in lower_map and "Group" not in df.columns:
        df = df.rename(columns={lower_map["group"]: "Group"})

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


def build_report(summary_df, closing_df, opening_df, accounts_df):
    """
    Combine all sheets & compute:
    - Closed Lots
    - NET DP/WD = Deposit - Withdrawal  (cash flow)
    - NET PNL USD = Closing Equity - Opening Equity - NET DP/WD
    - Net Credit/Bonus (for deeper analytics)
    - Group & Type (A/B Book)
    """
    # Start from closing equity
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

    # Merge summary transactions (Deposit, Withdrawal, Volume, etc.)
    report = report.merge(summary_df, on="Login", how="left")

    # Merge accounts mapping (Group)
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
        "CreditIn",
        "CreditOut",
        "BonusIn",
        "BonusOut",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots = full volume / 2
    report["Closed Lots"] = report["VolumeFull"] / 2.0

    # NET DP/WD (cash flow)
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # Net credit/bonus flow (for analytics, not in main formula)
    report["Net Credit/Bonus"] = (
        (report["CreditIn"] - report["CreditOut"])
        + (report["BonusIn"] - report["BonusOut"])
    )

    # NET PNL USD (confirmed formula)
    # NET PNL USD = Closing Equity - Opening Equity - (Deposit - Withdrawal)
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Classify book type
    report["Type"] = report["Group"].apply(classify_book_type)

    # Keep main columns (extra columns still go to Excel)
    main_cols = [
        "Login",
        "Group",
        "Type",
        "Currency",
        "Closed Lots",
        "NET DP/WD",
        "NET PNL USD",
        "Net Credit/Bonus",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "Closing Equity",
        "Opening Equity",
    ]
    report = report[main_cols].copy().sort_values("Login").reset_index(drop=True)
    return report

# ---------------------------------------------------------
# FILE UPLOAD UI
# ---------------------------------------------------------

st.subheader("🔼 Upload daily files")

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Summary / Transactions (Sheet 1)",
        type=["xlsx", "xls", "csv"],
        key="summary",
    )
with c2:
    closing_file = st.file_uploader(
        "Closing Equity (EOD – report date)",
        type=["xlsx", "xls"],
        key="closing",
    )
with c3:
    opening_file = st.file_uploader(
        "Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        key="opening",
    )
with c4:
    accounts_file = st.file_uploader(
        "Accounts (Login → Group)",
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
                )

            # ---------------- KPIs ----------------
            st.success("Report generated successfully ✅")

            total_clients = report_df["Login"].nunique()
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

            # A-Book vs B-Book summary
            book_summary = (
                report_df
                .groupby("Type", dropna=False)
                .agg(
                    Accounts=("Login", "nunique"),
                    Closed_Lots=("Closed Lots", "sum"),
                    Net_PNL_USD=("NET PNL USD", "sum"),
                )
                .reset_index()
            )

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Clients", total_clients)
            k2.metric("Total Client Profit", f"{total_profit_abs:,.2f}")
            k3.metric("Total Client Loss", f"{-total_loss:,.2f}")
            k4.metric("Net Client P&L", f"{net_pnl:,.2f}")

            st.markdown("### 📈 Profit vs Loss (by amount)")
            chart_data = pd.DataFrame(
                {
                    "Side": ["Profit", "Loss"],
                    "Amount": [total_profit_abs, total_loss_abs],
                }
            )
            st.bar_chart(chart_data.set_index("Side")["Amount"])
            st.caption(
                f"Profit share: **{profit_pct:.1f}%** • Loss share: **{loss_pct:.1f}%** (by absolute amount)"
            )

            st.markdown("### 🧩 A-Book vs B-Book Summary")
            st.dataframe(book_summary, use_container_width=True)

            # ---------------- TOP 10 GAINERS / LOSERS ----------------
            st.markdown("### 🏆 Top 10 Gainer Accounts")
            gainers = report_df.sort_values("NET PNL USD", ascending=False).head(10)
            st.dataframe(
                gainers[["Login", "Group", "Type", "NET PNL USD", "Closed Lots", "NET DP/WD"]],
                use_container_width=True,
            )

            st.markdown("### 💀 Top 10 Loser Accounts")
            losers = report_df.sort_values("NET PNL USD", ascending=True).head(10)
            st.dataframe(
                losers[["Login", "Group", "Type", "NET PNL USD", "Closed Lots", "NET DP/WD"]],
                use_container_width=True,
            )

            # ---------------- GROUP-WISE SUMMARY ----------------
            st.markdown("### 🧱 Group-wise Summary")
            group_summary = (
                report_df
                .groupby(["Group", "Type", "Currency"], dropna=False)
                .agg(
                    Accounts=("Login", "nunique"),
                    Closed_Lots=("Closed Lots", "sum"),
                    Net_PNL_USD=("NET PNL USD", "sum"),
                    Net_DP_WD=("NET DP/WD", "sum"),
                )
                .reset_index()
            )
            st.dataframe(group_summary, use_container_width=True)

            # ---------------- MAIN TABLE PREVIEW ----------------
            st.markdown("### 📋 Account-wise Report (first 150 rows)")
            st.dataframe(
                report_df[
                    ["Login", "Group", "Type", "Currency", "Closed Lots", "NET DP/WD", "NET PNL USD"]
                ].head(150),
                use_container_width=True,
            )

            # ---------------- DOWNLOAD EXCEL ----------------
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Account Report")
                group_summary.to_excel(writer, index=False, sheet_name="Group Summary")
                book_summary.to_excel(writer, index=False, sheet_name="Book Summary")
            output.seek(0)

            st.download_button(
                label="⬇️ Download Full Excel Report",
                data=output,
                file_name="FX_Client_PnL_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
