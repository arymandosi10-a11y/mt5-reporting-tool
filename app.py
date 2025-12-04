import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# BASIC PAGE SETUP (LIGHT, CLEAN)
# ---------------------------------------------------------
st.set_page_config(
    page_title="MT5 Reporting Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

LIGHT_CSS = """
<style>
:root {
    --primary-color:#2563eb;
    --background-color:#f9fafb;
    --card-bg:#ffffff;
    --text-color:#0f172a;
    --muted-text:#6b7280;
    --border-color:#e5e7eb;
}
.main {
    background-color: var(--background-color);
    color: var(--text-color);
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}
.report-card {
    background-color: var(--card-bg);
    border-radius: 0.75rem;
    padding: 1.25rem 1.5rem;
    border: 1px solid var(--border-color);
    box-shadow: 0 10px 25px rgb(15 23 42 / 0.03);
}
.section-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 0.6rem;
}
.section-sub {
    font-size: 0.85rem;
    color: var(--muted-text);
    margin-bottom: 0.2rem;
}
</style>
"""
st.markdown(LIGHT_CSS, unsafe_allow_html=True)

st.markdown(
    "<h2>📊 FX Client P&L Monitor</h2>"
    "<p class='section-sub'>Upload MT5 exports for yesterday’s EOD and get account & group level P&L.</p>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------


def robust_read_csv(file):
    """Try a few ways to read CSV to avoid tokenizing / encoding errors."""
    try:
        return pd.read_csv(file)
    except UnicodeDecodeError:
        file.seek(0)
        try:
            return pd.read_csv(file, encoding="latin1")
        except Exception:
            file.seek(0)
            return pd.read_csv(file, encoding_errors="ignore")
    except pd.errors.ParserError:
        file.seek(0)
        return pd.read_csv(file, engine="python", sep=None)


def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions
    Columns (by position):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        8: Volume (I) - full lots, will be /2 for closed lots
        10: Commission (K)
        12: Swap (M)
    Aggregated per Login.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = robust_read_csv(file)
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
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3: Daily Reports (EOD Equity)
    Expected columns: Login, Equity, Currency.
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
    for opt in ["currency", "cur.", "curr"]:
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
    """Accounts mapping: Login, Group (CSV or Excel)."""
    name = file.name.lower()
    if name.endswith(".csv"):
        df = robust_read_csv(file)
    else:
        df = pd.read_excel(file)

    cols_lower = {c.lower(): c for c in df.columns}

    if "login" in cols_lower and "Login" not in df.columns:
        df = df.rename(columns={cols_lower["login"]: "Login"})
    if "group" in cols_lower and "Group" not in df.columns:
        df = df.rename(columns={cols_lower["group"]: "Group"})

    if "Login" not in df.columns:
        raise ValueError("Accounts file must contain a 'Login' column.")
    if "Group" not in df.columns:
        raise ValueError("Accounts file must contain a 'Group' column.")

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def classify_book_type(group: str) -> str:
    """
    A/B book detection from group text.
    No broker names are hardcoded.
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
    Combine all sheets & compute metrics.

    - Closed Lots = VolumeFull / 2
    - NET DP/WD = Deposit - Withdrawal
    - NET PNL USD = Closing Equity - Opening Equity - Deposit + Withdrawal
      (as confirmed by you)
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

    # *** UPDATED FORMULA ***
    # NET PNL USD = Closing Equity - Opening Equity - Deposit + Withdrawal
    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["Deposit"]
        + report["Withdrawal"]
    )

    # Book type from group naming
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


def build_group_report(report_df: pd.DataFrame) -> pd.DataFrame:
    """
    Group-wise aggregation, similar to account-wise.
    """
    grp = (
        report_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Accounts=("Login", "nunique"),
            Closed_Lots=("Closed Lots", "sum"),
            NET_DP_WD=("NET DP/WD", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
        )
        .reset_index()
        .sort_values("NET PNL USd".lower(), ascending=False)
    )

    # Fix column order / names nicely
    grp = grp.rename(
        columns={
            "Closed_Lots": "Closed Lots",
            "NET_DP_WD": "NET DP/WD",
            "NET_PNL_USD": "NET PNL USD",
        }
    )
    return grp


# ---------------------------------------------------------
# FILE UPLOAD UI (MINIMAL TEXT)
# ---------------------------------------------------------
with st.container():
    st.markdown("<div class='report-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Upload MT5 exports</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='section-sub'>"
        "Use yesterday EOD reports: Opening = previous day EOD, Closing = current day EOD."
        "</p>",
        unsafe_allow_html=True,
    )

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
            "Closing Equity – Today EOD (Sheet 2)",
            type=["xlsx", "xls"],
            key="closing",
        )
    with c3:
        opening_file = st.file_uploader(
            "Opening Equity – Previous EOD (Sheet 3)",
            type=["xlsx", "xls"],
            key="opening",
        )
    with c4:
        accounts_file = st.file_uploader(
            "Accounts (Login → Group)",
            type=["xlsx", "xls", "csv"],
            key="accounts",
        )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("")

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

                group_df = build_group_report(report_df)

            # ---------------- KPIs & STATS ----------------
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='report-card'>", unsafe_allow_html=True)

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

            st.markdown(
                "<div class='section-title'>Overview</div>"
                "<p class='section-sub'>High-level client P&L for the selected day.</p>",
                unsafe_allow_html=True,
            )

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Total Accounts", total_clients)
            k2.metric("Total Profit", f"{total_profit_abs:,.2f}")
            k3.metric("Total Loss", f"{-total_loss:,.2f}")
            k4.metric("Net P&L", f"{net_pnl:,.2f}")

            st.markdown("### Profit vs Loss")
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

            st.markdown("</div>", unsafe_allow_html=True)

            # ---------------- TOP 10 GAINERS / LOSERS ----------------
            st.markdown("<br>", unsafe_allow_html=True)
            col_g, col_l = st.columns(2)

            with col_g:
                st.markdown("<div class='report-card'>", unsafe_allow_html=True)
                st.markdown("<div class='section-title'>Top 10 Gainers</div>", unsafe_allow_html=True)
                gainers = report_df.sort_values("NET PNL USD", ascending=False).head(10)
                st.dataframe(
                    gainers[
                        ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                    ],
                    use_container_width=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with col_l:
                st.markdown("<div class='report-card'>", unsafe_allow_html=True)
                st.markdown("<div class='section-title'>Top 10 Losers</div>", unsafe_allow_html=True)
                losers = report_df.sort_values("NET PNL USD", ascending=True).head(10)
                st.dataframe(
                    losers[
                        ["Login", "Group", "NET PNL USD", "Closed Lots", "NET DP/WD", "Type"]
                    ],
                    use_container_width=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            # ---------------- GROUP-WISE TABLE ----------------
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='report-card'>", unsafe_allow_html=True)
            st.markdown(
                "<div class='section-title'>Group-wise P&L</div>"
                "<p class='section-sub'>Aggregated by group & book type.</p>",
                unsafe_allow_html=True,
            )
            st.dataframe(group_df, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # ---------------- MAIN TABLE PREVIEW ----------------
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='report-card'>", unsafe_allow_html=True)
            st.markdown(
                "<div class='section-title'>Account-wise Report (first 200 rows)</div>",
                unsafe_allow_html=True,
            )
            st.dataframe(report_df.head(200), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            # ---------------- DOWNLOAD EXCEL ----------------
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                report_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
            output.seek(0)

            st.download_button(
                label="⬇️ Download Excel (Accounts + Groups)",
                data=output,
                file_name="FX_Client_PnL_Report.xlsx",
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
                use_container_width=True,
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
