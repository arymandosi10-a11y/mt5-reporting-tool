import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP (LIGHT THEME)
# ---------------------------------------------------------
st.set_page_config(
    page_title="MT5 Reporting Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Simple light styling
st.markdown(
    """
    <style>
    .main {
        background-color: #ffffff;
        color: #000000;
    }
    .stMetric {
        background: #f5f7fb;
        padding: 0.75rem 1rem;
        border-radius: 0.75rem;
        border: 1px solid #e0e4f0;
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 1.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 FX Client P&L Monitoring")

st.caption(
    "Upload today & yesterday equity reports + summary and accounts file to get a "
    "per-account P&L view, top winners / losers and total client profit vs loss."
)

with st.expander("File format details (click to open)", expanded=False):
    st.markdown(
        """
        **You need 4 files from MT5 Manager:**

        1. **Summary / Transactions (Sheet-1)**  
           - Login (1st column)  
           - Deposit = column **C**  
           - Withdrawal = column **F**  
           - Volume (full lots) = column **I** (tool will divide by 2 for closed lots)  
           - Commission = column **K**  
           - Swap = column **M**

        2. **Closing Equity (today EOD)** – Daily report with Login, Equity, Currency  
        3. **Opening Equity (previous day EOD)** – same format as closing  
        4. **Accounts mapping** – CSV/Excel with **Login** and **Group**

        **Key formulas used**

        - Closed Lots = Volume / 2  
        - NET DP/WD = Deposit − Withdrawal  
        - NET PNL = Closing Equity − Opening Equity − NET DP/WD  
        - Type = A-Book / B-Book (from Group: text contains `_A` or `_B`)
        """
    )

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------


def _read_csv_safely(file) -> pd.DataFrame:
    """Try reading CSV as utf-8, fall back to latin-1 to avoid codec errors."""
    try:
        file.seek(0)
        return pd.read_csv(file)
    except UnicodeDecodeError:
        file.seek(0)
        return pd.read_csv(file, encoding="latin1")


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    Positions (0-based):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume (I) - full lots, will be /2 for closed lots
        10: Commission (K)
        12: Swap (M)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = _read_csv_safely(file)
    else:
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
            file.seek(0)
            raw = pd.read_excel(file)

    if raw.shape[1] < 13:
        raise ValueError("Summary sheet must have at least 13 columns (A–M).")

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
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD Equity)
    Expect columns: Login, Equity, Currency (names can vary).
    """
    try:
        df = pd.read_excel(file, header=2)
    except Exception:
        file.seek(0)
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
    """Accounts mapping: Login + Group (CSV or Excel)."""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = _read_csv_safely(file)
    else:
        file.seek(0)
        df = pd.read_excel(file)

    cols_lower = [c.lower() for c in df.columns]
    if "login" not in cols_lower:
        raise ValueError("Accounts file must contain a 'Login' column.")
    if "group" not in cols_lower:
        raise ValueError("Accounts file must contain a 'Group' column.")

    login_col = df.columns[cols_lower.index("login")]
    group_col = df.columns[cols_lower.index("group")]

    out = df[[login_col, group_col]].copy()
    out.columns = ["Login", "Group"]
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def classify_book_type(group: str) -> str:
    """
    A/B book detection:
    - text contains '_A' -> 'A-Book'
    - text contains '_B' -> 'B-Book'
    - else -> 'Unknown'
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
    - Closed Lots = Volume / 2
    - NET DP/WD = Deposit - Withdrawal
    - NET PNL = Closing Equity - Opening Equity - NET DP/WD
    - Group & Type (A/B Book)
    """
    report = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()

    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    report = report.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")

    report = report.merge(summary_df, on="Login", how="left")
    report = report.merge(accounts_df, on="Login", how="left")

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

    report["Closed Lots"] = report["VolumeFull"] / 2.0
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # Confirmed formula:
    # NET PNL = Closing Equity - Opening Equity - (Deposit - Withdrawal)
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    report["Type"] = report["Group"].apply(classify_book_type)

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
st.subheader("🔼 Upload files")

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
    )
with c2:
    closing_file = st.file_uploader(
        "Closing Equity (today EOD)",
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
if st.button("🚀 Generate Report", use_container_width=True):
    if not (summary_file and closing_file and opening_file and accounts_file):
        st.error("Please upload **all four files** before generating the report.")
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

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Clients", total_clients)
            k2.metric("Total Profit", f"{total_profit_abs:,.2f}")
            k3.metric("Total Loss", f"{-total_loss:,.2f}")
            k4.metric("Net P&L", f"{net_pnl:,.2f}")

            st.markdown("### 📈 Profit vs Loss (amount)")
            chart_data = pd.DataFrame(
                {
                    "Side": ["Profit", "Loss"],
                    "Amount": [total_profit_abs, total_loss_abs],
                }
            )
            st.bar_chart(chart_data.set_index("Side"))

            st.caption(
                f"Profit share: **{profit_pct:.1f}%** • Loss share: **{loss_pct:.1f}%** (by absolute amount)"
            )

            # ---------------- TOP 10 GAINERS / LOSERS ----------------
            tab1, tab2, tab3 = st.tabs(["🏆 Top Gainers", "💀 Top Losers", "📋 Full Table"])

            with tab1:
                gainers = report_df.sort_values("NET PNL USD", ascending=False).head(10)
                st.dataframe(
                    gainers[
                        ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                    ],
                    use_container_width=True,
                )

            with tab2:
                losers = report_df.sort_values("NET PNL USD", ascending=True).head(10)
                st.dataframe(
                    losers[
                        ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                    ],
                    use_container_width=True,
                )

            with tab3:
                st.dataframe(report_df, use_container_width=True, height=600)

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
