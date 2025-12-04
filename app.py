import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP
# ---------------------------------------------------------
st.set_page_config(page_title="FX Broker P&L Monitor", layout="wide")

# Simple dark-ish styling (no broker names, generic)
st.markdown(
    """
    <style>
    .main {
        background-color: #0f172a;
        color: #e5e7eb;
    }
    .stApp {
        background-color: #020617;
        color: #e5e7eb;
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3, h4 {
        color: #e5e7eb !important;
    }
    .metric-label {
        color: #9ca3af !important;
    }
    .metric-value {
        color: #e5e7eb !important;
        font-weight: 700 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 FX Broker Client P&L Monitoring Tool")

st.markdown(
    """
Upload **4 files** exported from MT5 Manager:

1️⃣ **Sheet 1 – Summary / Transactions**  
   - Login (1st column)  
   - Deposit = column **C**  
   - Withdrawal = column **F**  
   - Volume (full lots) = column **I** (we will divide by 2 for closed lots)  
   - Commission = column **K**  
   - Swap = column **M**  
   > Profit & Date from this sheet are **ignored**.

2️⃣ **Sheet 2 – Closing Equity (today EOD)**  
   - Login, Equity (col J), Currency

3️⃣ **Sheet 3 – Opening Equity (previous day EOD)**  
   - Same format as Sheet 2

4️⃣ **Accounts file (Login → Group)**  
   - Use your **Accounts.csv** or Excel with columns:  
     - Login  
     - Group  

### Columns in final report

- Login  
- Group  
- Closed Lots (Volume ÷ 2)  
- NET DP/WD (Deposit – Withdrawal)  
- Currency  
- NET PNL USD = Closing Equity – Opening Equity – (Deposit – Withdrawal)  
- Type = A-Book / B-Book (detected from Group text: contains “_A” or “_B”)  

The app will also show:

- Total client profit & loss
- % of profit vs loss (by amount)
- Top 10 gainer accounts
- Top 10 loser accounts
- A simple profit vs loss bar chart
"""
)

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    - Column positions (0-based):
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
        # Many MT5 exports have headers on row 3 -> header=2
        # If it fails, try default header
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    # Ensure there are enough columns
    if raw.shape[1] < 13:
        raise ValueError("Summary sheet does not have at least 13 columns (A–M).")

    summary = pd.DataFrame()
    summary["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    summary["Deposit"] = pd.to_numeric(raw.iloc[:, 2], errors="coerce").fillna(0.0)
    summary["Withdrawal"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    summary["VolumeFull"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    summary["Commission"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)
    summary["Swap"] = pd.to_numeric(raw.iloc[:, 12], errors="coerce").fillna(0.0)

    # Aggregate per Login
    grouped = (
        summary.groupby("Login", as_index=False)[
            ["Deposit", "Withdrawal", "VolumeFull", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD Equity)
    We expect columns: Login, Equity, Currency
    Typically header=2 for MT5, but we fall back to header=0 if needed.
    """
    try:
        df = pd.read_excel(file, header=2)
    except Exception:
        df = pd.read_excel(file)

    # Try to find columns by name; if not, assume positions.
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

    if "Login" not in df.columns and "login" in [c.lower() for c in df.columns]:
        # Normalize column name if needed
        df = df.rename(columns={c: "Login" for c in df.columns if c.lower() == "login"})
    if "Group" not in df.columns and "group" in [c.lower() for c in df.columns]:
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
    This is generic and does NOT hardcode any broker names.
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
    - NET DP/WD = Deposit - Withdrawal
    - NET PNL USD = Closing Equity - Opening Equity - NET DP/WD
    - Group & Type (A/B Book)
    """
    # Start from equity (closing)
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
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    # Closed lots = full volume / 2
    report["Closed Lots"] = report["VolumeFull"] / 2.0

    # NET DP/WD (cash flow)
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL (confirmed formula)
    # NET PNL = Closing Equity - Opening Equity - Deposit + Withdrawal
    # which is same as: CE - OE - (Deposit - Withdrawal) = CE - OE - NET DP/WD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Classify book type
    report["Type"] = report["Group"].apply(classify_book_type)

    # Keep only requested / useful columns
    final_cols = [
        "Login",
        "Group",
        "Closed Lots",
        "NET DP/WD",
        "Currency",
        "NET PNL USD",
        "Type",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "Closing Equity",
        "Opening Equity",
    ]
    final = report[final_cols].copy().sort_values("Login").reset_index(drop=True)
    return final


# ---------------------------------------------------------
# FILE UPLOAD UI
# ---------------------------------------------------------
st.subheader("🔼 Upload your files")

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="Includes Deposit, Withdrawal, Volume, Commission, Swap",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (today EOD)",
        type=["xlsx", "xls"],
        key="closing",
        help="Daily report at end of day",
    )
with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous day)",
        type=["xlsx", "xls"],
        key="opening",
        help="Previous day's EOD equity report",
    )
with c4:
    accounts_file = st.file_uploader(
        "Accounts mapping (Login → Group)",
        type=["xlsx", "xls", "csv"],
        key="accounts",
        help="Use Accounts.csv or Excel with Login & Group",
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

            # ---------------- KPIs & STATS ----------------
            st.success("Report generated successfully!")

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

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Clients", total_clients)
            k2.metric("Total Client Profit", f"{total_profit_abs:,.2f}")
            k3.metric("Total Client Loss", f"{-total_loss:,.2f}")
            k4.metric("Net Client P&L", f"{net_pnl:,.2f}")

            st.markdown("### 📈 Profit vs Loss (Amount & %)")
            chart_data = pd.DataFrame(
                {
                    "Side": ["Profit", "Loss"],
                    "Amount": [total_profit_abs, total_loss_abs],
                    "Percent": [profit_pct, loss_pct],
                }
            )
            st.bar_chart(chart_data.set_index("Side")["Amount"])

            st.caption(
                f"Profit share: **{profit_pct:.1f}%** • Loss share: **{loss_pct:.1f}%** (by absolute amount)"
            )

            # ---------------- TOP 10 GAINERS / LOSERS ----------------
            st.markdown("### 🏆 Top 10 Gainer Accounts")
            gainers = report_df.sort_values("NET PNL USD", ascending=False).head(10)
            st.dataframe(
                gainers[
                    ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                ],
                use_container_width=True,
            )

            st.markdown("### 💀 Top 10 Loser Accounts")
            losers = report_df.sort_values("NET PNL USD", ascending=True).head(10)
            st.dataframe(
                losers[
                    ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                ],
                use_container_width=True,
            )

            # ---------------- MAIN TABLE PREVIEW ----------------
            st.markdown("### 📋 Full Report Preview (first 200 rows)")
            st.dataframe(report_df.head(200), use_container_width=True)

            # ---------------- DOWNLOAD EXCEL ----------------
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Report")
            output.seek(0)

            st.download_button(
                label="⬇️ Download Full Report (Excel)",
                data=output,
                file_name="FX_Client_PnL_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
