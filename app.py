import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP (light theme)
# ---------------------------------------------------------
st.set_page_config(
    page_title="MT5 Reporting Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --primary-color:#2563eb;
        --background-color:#ffffff;
        --text-color:#0f172a;
        --secondary-bg:#f1f5f9;
    }
    .main {
        background-color: var(--background-color);
        color: var(--text-color);
    }
    .stButton>button {
        background: var(--primary-color);
        color: white;
        border-radius: 999px;
        border: none;
        padding: 0.6rem 1.6rem;
        font-weight: 600;
    }
    .stButton>button:hover {
        filter: brightness(1.05);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 FX Client P&L Monitoring")

st.caption("Upload MT5 exports → get client & group P&L, top gainers/losers, and summary charts.")

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    Expected structure (by column position):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume (I) - full lots, will be /2 for closed lots
        10: Commission (K)
        12: Swap (M)
    Can be XLSX/XLS or CSV. Aggregated per Login.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        try:
            raw = pd.read_csv(file)
        except UnicodeDecodeError:
            # fallback for non-utf8 csv
            raw = pd.read_csv(file, encoding="latin1")
    else:
        try:
            raw = pd.read_excel(file, header=2)
        except Exception:
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
        ].sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: EOD Equity reports
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
    equity_col = find_col(["equity"], 9)  # J ≈ index 9
    currency_col = find_col(["currency"], None) if "currency" in cols_lower else None

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
    Accounts mapping: Login, Group
    Supports CSV or Excel.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        try:
            df = pd.read_csv(file)
        except UnicodeDecodeError:
            df = pd.read_csv(file, encoding="latin1")
    else:
        df = pd.read_excel(file)

    lower_map = {c.lower(): c for c in df.columns}
    if "login" in lower_map and "Login" not in df.columns:
        df = df.rename(columns={lower_map["login"]: "Login"})
    if "group" in lower_map and "Group" not in df.columns:
        df = df.rename(columns={lower_map["group"]: "Group"})

    if "Login" not in df.columns or "Group" not in df.columns:
        raise ValueError("Accounts file must contain 'Login' and 'Group' columns.")

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def classify_book_type(group: str) -> str:
    """
    A/B book detection:
    - contains '_A' -> 'A-Book'
    - contains '_B' -> 'B-Book'
    Otherwise -> 'Unknown'
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
    report = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()

    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    report = report.merge(
        open_renamed[["Login", "Opening Equity"]],
        on="Login",
        how="left",
    )

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

    # Closed lots = full volume / 2
    report["Closed Lots"] = report["VolumeFull"] / 2.0

    # NET DP/WD (cash flow)
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # ✅ FINAL CONFIRMED FORMULA:
    # NET PNL USD = Closing Equity - Opening Equity - NET DP/WD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Book type
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
# FILE UPLOAD UI (short & clean)
# ---------------------------------------------------------
st.subheader("📂 Upload MT5 exports")

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
        "Closing Equity report",
        type=["xlsx", "xls"],
        key="closing",
    )
with c3:
    opening_file = st.file_uploader(
        "Opening Equity report",
        type=["xlsx", "xls"],
        key="opening",
    )
with c4:
    accounts_file = st.file_uploader(
        "Accounts mapping (Login → Group)",
        type=["xlsx", "xls", "csv"],
        key="accounts",
    )

st.markdown("---")

# ---------------------------------------------------------
# MAIN ACTION
# ---------------------------------------------------------
if st.button("🚀 Generate Report", use_container_width=True):
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
            st.success("Report generated successfully ✅")

            total_clients = report_df["Login"].nunique()
            total_profit = report_df.loc[report_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = report_df.loc[report_df["NET PNL USD"] < 0, "NET PNL USD"].sum()
            net_pnl = report_df["NET PNL USD"].sum()

            total_profit_abs = float(total_profit)
            total_loss_abs = float(abs(total_loss))
            denom = total_profit_abs + total_loss_abs
            if denom > 0:
                profit_pct = (total_profit_abs / denom) * 100.0
                loss_pct = (total_loss_abs / denom) * 100.0
            else:
                profit_pct = loss_pct = 0.0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Clients", total_clients)
            k2.metric("Total Profit (clients)", f"{total_profit_abs:,.2f}")
            k3.metric("Total Loss (clients)", f"{-total_loss:,.2f}")
            k4.metric("Net Client P&L", f"{net_pnl:,.2f}")

            st.markdown("### 📈 Profit vs Loss")
            chart_data = pd.DataFrame(
                {
                    "Side": ["Profit", "Loss"],
                    "Amount": [total_profit_abs, total_loss_abs],
                }
            )
            st.bar_chart(chart_data.set_index("Side")["Amount"], use_container_width=True)
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

            # ---------------- GROUP-WISE SUMMARY ----------------
            st.markdown("### 📊 Group-wise Summary")
            group_summary = (
                report_df.groupby(["Group", "Type"], dropna=False)
                .agg(
                    Clients=("Login", "nunique"),
                    Closed_Lots=("Closed Lots", "sum"),
                    Net_DPWD=("NET DP/WD", "sum"),
                    Net_PNL_USD=("NET PNL USD", "sum"),
                )
                .reset_index()
                .sort_values("Net_PNL_USD", ascending=False)
            )
            st.dataframe(group_summary, use_container_width=True)

            # ---------------- MAIN TABLE PREVIEW ----------------
            st.markdown("### 📋 Full Report Preview (first 200 rows)")
            st.dataframe(report_df.head(200), use_container_width=True)

            # ---------------- DOWNLOAD EXCEL ----------------
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_summary.to_excel(writer, index=False, sheet_name="Groups")
            output.seek(0)

            st.download_button(
                label="⬇️ Download Full Excel Report",
                data=output,
                file_name="FX_Client_PnL_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
