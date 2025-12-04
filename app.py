import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

st.set_page_config(page_title="MT5 Daily Report", layout="wide")

st.title("📊 MT5 Daily / Monthly P&L Reporting Tool")

st.markdown(
    """
Upload the **3 MT5 Excel files** exported from MT5 Manager:

1. **Trade Accounts Detailed** (Sheet 2 – overall per-account summary)  
2. **Closing Equity** – Daily report for *today*  
3. **Opening Equity** – Daily report for *previous day*  

The tool will generate a report similar to your **Sheet 1 (Beirman Capital style)**.

After report is generated, you can **download the final Excel**.
"""
)

# ---------- Helper functions ----------

def load_trade_accounts(file) -> pd.DataFrame:
    """Load MT5 Trade Accounts Detailed (header normally on row 3)."""
    df = pd.read_excel(file, header=2)
    keep_cols = [
        "Login", "Name", "Deposit", "Withdraw", "In/Out", "Credit",
        "Volume", "Commission", "Fee", "Swap", "Profit",
        "Cur. Balance", "Cur. Equity", "Equity Prev Day", "Currency"
    ]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    df["Login"] = pd.to_numeric(df["Login"], errors="coerce").astype("Int64")
    return df


def load_equity_report(file) -> pd.DataFrame:
    """Load MT5 Daily Report (Closing / Opening equity snapshot)."""
    df = pd.read_excel(file, header=2)
    keep_cols = ["Login", "Equity", "Currency"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    df["Login"] = pd.to_numeric(df["Login"], errors="coerce").astype("Int64")
    return df


def build_report(trade_df, closing_df, opening_df) -> pd.DataFrame:
    """Join datasets + compute PNL, DP/WD, Closed Lots, etc."""

    # Start with closing equity
    report = closing_df.rename(
        columns={"Equity": "Net Equity New", "Currency": "Currency"}
    ).copy()

    # Add opening equity (previous day)
    report = report.merge(
        opening_df.rename(columns={"Equity": "Net Equity Old"})[["Login", "Net Equity Old"]],
        on="Login",
        how="left",
    )

    # Add trade account details
    trade_cols = {
        "Profit": "Profit",
        "Swap": "Swap",
        "Commission": "Commission",
        "Fee": "Fee",
        "Volume": "Raw Volume",
    }

    trade_subset = trade_df[["Login"] + [c for c in trade_cols.keys() if c in trade_df.columns]].copy()
    trade_subset = trade_subset.rename(columns=trade_cols)
    report = report.merge(trade_subset, on="Login", how="left")

    # Ensure numeric
    for col in ["Net Equity New", "Net Equity Old", "Profit", "Swap", "Commission", "Fee", "Raw Volume"]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)

    # NET PNL CCY
    report["NET PNL CCY"] = (
        report.get("Profit", 0.0)
        + report.get("Swap", 0.0)
        + report.get("Commission", 0.0)
        + report.get("Fee", 0.0)
    )

    # NET DP/WD CCY
    report["NET DP/WD CCY"] = (
        report["Net Equity New"]
        - report["Net Equity Old"].fillna(0.0)
        - report["NET PNL CCY"]
    )

    # Closed Lots = Raw Volume / 2
    report["Closed Lots"] = report.get("Raw Volume", 0.0) / 2.0

    # Placeholder until we add advanced features
    report["Volume In USD"] = np.nan
    report["NET PNL USD"] = report["NET PNL CCY"]
    report["Group"] = np.nan
    report["Type"] = np.nan
    report["Monthly PNL USD"] = np.nan
    report["Monthly Volume In USD"] = np.nan
    report["All time PnL (from 20/9/25)"] = np.nan
    report["All time Volume USD (from 20/9/25) "] = np.nan
    report["Nr of positive trades"] = np.nan
    report["Nr of negative trades"] = np.nan
    report["Hit Percentage"] = np.nan

    # Column order
    desired_order = [
        "Login",
        "Group",
        "Net Equity New",
        "Net Equity Old",
        "NET DP/WD CCY",
        "NET PNL CCY",
        "Closed Lots",
        "Volume In USD",
        "Currency",
        "NET PNL USD",
        "Type",
        "Monthly PNL USD",
        "Monthly Volume In USD",
        "All time PnL (from 20/9/25)",
        "All time Volume USD (from 20/9/25) ",
        "Nr of positive trades",
        "Nr of negative trades",
        "Hit Percentage",
    ]

    report = report[[c for c in desired_order if c in report.columns]].copy()
    report = report.sort_values("Login").reset_index(drop=True)
    return report


# ---------- UI Layout ----------

col1, col2, col3 = st.columns(3)

with col1:
    trade_file = st.file_uploader(
        "📄 Trade Accounts Detailed",
        type=["xlsx", "xls"],
        key="trade",
        help="Export from MT5 Manager: Trade Accounts Detailed"
    )

with col2:
    closing_file = st.file_uploader(
        "📄 Closing Equity (today)",
        type=["xlsx", "xls"],
        key="closing",
        help="Daily report at end of day (Equity column J)"
    )

with col3:
    opening_file = st.file_uploader(
        "📄 Opening Equity (previous day)",
        type=["xlsx", "xls"],
        key="opening",
        help="Daily report of previous day (Equity column J)"
    )

st.markdown("---")

# ---------- Button Logic ----------

if st.button("🚀 Generate Report"):
    if not (trade_file and closing_file and opening_file):
        st.error("Please upload all three files before generating the report.")
    else:
        try:
            with st.spinner("Processing files & calculating PNL..."):
                trade_df = load_trade_accounts(trade_file)
                closing_df = load_equity_report(closing_file)
                opening_df = load_equity_report(opening_file)

                report_df = build_report(trade_df, closing_df, opening_df)

            st.success("Report generated successfully!")

            st.subheader("📋 Report Preview (first 100 rows)")
            st.dataframe(report_df.head(100), use_container_width=True)

            # Convert to Excel
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Report")
            output.seek(0)

            # Download button
            st.download_button(
                label="⬇️ Download Full Report (Excel)",
                data=output,
                file_name="MT5_Daily_Report_Output.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
