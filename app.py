import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# PAGE CONFIG & GLOBAL STYLE (LIGHT / PREMIUM)
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
/* ===== Light premium theme ===== */
body, .main {
    background: radial-gradient(circle at top left, #ffffff 0, #f6f8fc 55%, #eef2f8 100%);
    color: #0f172a;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1450px;
}

/* Headings */
h1,h2,h3,h4 {
    color: #0f172a;
}

/* Hero / cards */
.card-soft {
    background: linear-gradient(135deg, #0b1220 0%, #111827 55%, #0b1220 100%);
    color: #f9fafb;
    border-radius: 22px;
    padding: 1.4rem 1.6rem;
    border: 1px solid rgba(255,255,255,0.10);
    box-shadow: 0 18px 55px rgba(15, 23, 42, 0.25);
}
.section-badge {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    padding: .20rem .7rem;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.25);
    font-size: .8rem;
    color: rgba(249,250,251,0.75);
}

/* Metric cards */
.metric-card {
    background: #ffffff;
    border-radius: 16px;
    padding: 0.9rem 1rem;
    border: 1px solid rgba(15,23,42,0.08);
    box-shadow: 0 10px 30px rgba(2, 6, 23, 0.06);
}
.metric-label {
    font-size: 0.75rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748b;
}
.metric-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: #0f172a;
}
.metric-sub {
    font-size: 0.78rem;
    color: #64748b;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: radial-gradient(circle at 0 0, #0b1220 0, #0b1220 45%, #0b1220 100%);
    color: #f9fafb;
    border-right: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] * {
    color: #f9fafb !important;
}

/* Dataframe */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid rgba(15,23,42,0.08);
    box-shadow: 0 10px 30px rgba(2, 6, 23, 0.05);
}

/* Inputs */
.stTextInput > div > div > input,
.stNumberInput input,
.stDateInput input {
    border-radius: 12px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# HELPERS
# =========================================================

def _read_excel_or_csv(file: BytesIO) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    # MT5 exports often have 2 header lines -> data begins at row 3
    try:
        return pd.read_excel(file, header=2)
    except Exception:
        return pd.read_excel(file)


def load_summary_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 1 – Summary / Transactions (based on your requirement)

    Columns (0-based indexes):
      A (0): Login
      E (4): Net Deposit/Withdrawal (Net D/W)
      F (5): Credit
      H (7): Total Lots/Volume  -> Closed Lots = H / 2

    Optional (if present in your export):
      I (8): Commission
      K (10): Swap
    """
    raw = _read_excel_or_csv(file)

    if raw.shape[1] < 8:
        raise ValueError("Sheet-1 must have at least columns up to H (Volume/Lots).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")

    # Net D/W from col E
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)

    # Credit from col F
    df["Credit"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)

    # Volume/Lots from col H
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)

    # Optional columns if exist
    df["Commission"] = 0.0
    df["Swap"] = 0.0
    if raw.shape[1] >= 9:
        df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    if raw.shape[1] >= 11:
        df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]
        ].sum()
    )
    return grouped


def load_equity_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 2 / 3 – Equity report
    - Equity from column J (index 9)
    Rule:
      If equity < 0 => 0
    """
    raw = _read_excel_or_csv(file)

    # Try "Login" header, else fallback to first col
    cols_lower = [str(c).strip().lower() for c in raw.columns]

    def find_col(name_options, default_idx=None):
        for opt in name_options:
            if opt in cols_lower:
                return raw.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(raw.columns):
            return raw.columns[default_idx]
        raise ValueError(f"Could not find column for {name_options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)  # J by default

    # Currency optional
    currency_col = None
    for opt in ["currency", "curr", "ccy"]:
        if opt in cols_lower:
            currency_col = raw.columns[cols_lower.index(opt)]
            break

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(raw[login_col], errors="coerce").astype("Int64")

    eq = pd.to_numeric(raw[equity_col], errors="coerce").fillna(0.0)
    out["Equity"] = eq.clip(lower=0.0)  # ✅ negative treated as 0

    out["Currency"] = raw[currency_col].astype(str) if currency_col is not None else "USD"
    return out


def _read_accounts_file(file: BytesIO) -> pd.DataFrame:
    df = _read_excel_or_csv(file)

    lower = {str(c).lower(): c for c in df.columns}
    if "login" in lower and "Login" not in df.columns:
        df = df.rename(columns={lower["login"]: "Login"})
    if "group" in lower and "Group" not in df.columns:
        df = df.rename(columns={lower["group"]: "Group"})

    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out


def load_book_accounts(file: BytesIO, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switches_file(file: BytesIO) -> pd.DataFrame:
    df = _read_excel_or_csv(file)
    lower = {str(c).lower(): c for c in df.columns}

    def pick(col):
        if col.lower() not in lower:
            raise ValueError(f"Switches file must contain column: {col}")
        return lower[col.lower()]

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)
    return out


def build_report(summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label: str) -> pd.DataFrame:
    """
    Net PNL Formula (your exact requirement):
        NET PNL = Closing Equity - Opening Equity - Net D/W - Credit

    Rule:
        If Closing/Opening Equity < 0 => treat as 0
    """
    base = closing_df.rename(columns={"Equity": "Closing Equity"}).copy()
    open_df = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_df[["Login", "Opening Equity"]], on="Login", how="left")

    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # numeric safety
    for col in ["Closing Equity", "Opening Equity", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    # Double safety clamp (also fixes if equity column parse mismatch)
    report["Opening Equity"] = report["Opening Equity"].clip(lower=0.0)
    report["Closing Equity"] = report["Closing Equity"].clip(lower=0.0)

    # closed lots
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # dp/wd & credit columns to show
    report["NET DP/WD"] = report["NET_DP_WD"]
    report["Credit"] = report["Credit"]

    # deposit/withdraw split
    report["Deposit"] = np.where(report["NET DP/WD"] > 0, report["NET DP/WD"], 0.0)
    report["Withdrawal"] = np.where(report["NET DP/WD"] < 0, -report["NET DP/WD"], 0.0)

    # ✅ correct net pnl
    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["NET DP/WD"]
        - report["Credit"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"] > 0,
        (report["NET PNL USD"] / report["Opening Equity"]) * 100.0,
        0.0,
    )

    # switches
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan

    if switches_df is not None and not switches_df.empty:
        report = report.merge(switches_df, on="Login", how="left", suffixes=("", "_sw"))
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]
        report["ShiftEquity"] = pd.to_numeric(report["ShiftEquity"], errors="coerce").fillna(0.0)
        report["Type"] = np.where(report["ShiftToType"].notna(), report["ShiftToType"], report["Type"])

    report["EOD Closing Equity Date"] = eod_label

    final_cols = [
        "Login", "Group", "OrigType", "Type", "Currency",
        "Closed Lots", "NET DP/WD", "Credit",
        "Opening Equity", "Closing Equity",
        "NET PNL USD", "NET PNL %",
        "Deposit", "Withdrawal",
        "Commission", "Swap",
        "ShiftFromType", "ShiftToType", "ShiftEquity",
        "EOD Closing Equity Date"
    ]
    return report[final_cols].sort_values("Login").reset_index(drop=True)


def build_group_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    return (
        account_df.groupby(["Group", "Type"], dropna=False)
        .agg(
            Accounts=("Login", "nunique"),
            Closed_Lots=("Closed Lots", "sum"),
            NET_DP_WD=("NET DP/WD", "sum"),
            Credit=("Credit", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
        )
        .reset_index()
    )


def build_book_summary(account_df: pd.DataFrame, switches_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    switches_map = {}
    if switches_df is not None and not switches_df.empty:
        switches_map = switches_df.set_index("Login").to_dict("index")

    for _, r in account_df.iterrows():
        login = r["Login"]
        net_pnl = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        final_type = r["Type"]
        closing = r["Closing Equity"]

        sw = switches_map.get(login)
        if not sw:
            rows.append({"Type": final_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": net_pnl})
        else:
            from_type = sw["FromType"]
            to_type = sw["ToType"]
            shift_eq = float(sw["ShiftEquity"])

            pnl_new = closing - shift_eq
            pnl_old = net_pnl - pnl_new

            rows.append({"Type": from_type, "Accounts": 0, "Closed_Lots": 0.0, "NET_PNL_USD": pnl_old})
            rows.append({"Type": to_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": pnl_new})

    contrib = pd.DataFrame(rows)
    return (
        contrib.groupby("Type", as_index=False)
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
    )


def load_lp_breakdown_file(file: BytesIO) -> pd.DataFrame:
    df = _read_excel_or_csv(file)
    lower = {str(c).lower(): c for c in df.columns}

    def pick(*cands):
        for c in cands:
            if c.lower() in lower:
                return lower[c.lower()]
        raise ValueError(f"LP breakdown file missing one of: {cands}")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname", "name")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity", "opening")], errors="coerce").fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity", "closing")], errors="coerce").fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd", "net_dp_wd", "netdp")], errors="coerce").fillna(0.0)
    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# =========================================================
# SIDEBAR – LP PANEL
# =========================================================
with st.sidebar:
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.caption(
        "Upload LP breakdown (optional). Brokerage P&L = Total LP P&L − Client A-Book P&L."
    )
    lp_file = st.file_uploader("LP breakdown file (XLSX / CSV)", type=["xlsx", "xls", "csv"], key="lp_file")


# =========================================================
# MAIN HEADER
# =========================================================
st.markdown(
    """
<div class="card-soft">
  <div class="section-badge">FX client book monitor</div>
  <h1 style="margin-top:.65rem; margin-bottom:.25rem;">Client P&amp;L Monitoring Tool</h1>
  <p style="color:rgba(249,250,251,0.75); max-width: 880px; line-height:1.6;">
    Upload MT5 exports to see account-wise, group-wise and book-wise P&amp;L, including A-Book vs B-Book comparison and A-Book vs LP brokerage.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
# FILE UPLOADS
# =========================================================
st.markdown("### 1. Upload MT5 reports")

col_eod, _ = st.columns([2, 3])
with col_eod:
    eod_label = st.text_input("EOD Closing Equity Date (stored in reports)", placeholder="e.g. 2025-12-02")

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="Uses: Net D/W (E), Credit (F), Lots/Volume (H -> /2).",
    )

with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        key="closing",
        help="Uses Equity from column J.",
    )

with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        key="opening",
        help="Uses Equity from column J.",
    )

st.markdown("#### Book-wise account lists")

cb1, cb2, cb3 = st.columns(3)
with cb1:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with cb2:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with cb3:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")

st.markdown("#### Book switches (optional)")
swc1, swc2 = st.columns([2, 3])
with swc1:
    switches_file = st.file_uploader("Switches file", type=["xlsx", "xls", "csv"], key="switches")
with swc2:
    st.caption("Columns: Login, FromType, ToType, ShiftEquity")

st.markdown("---")

# =========================================================
# RUN
# =========================================================
if st.button("🚀 Generate report", use_container_width=True):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of A-Book / B-Book / Hybrid accounts file.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date.")
    else:
        try:
            with st.spinner("Processing files & calculating P&L…"):
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

                accounts_df = pd.concat(accounts_frames, ignore_index=True).drop_duplicates(subset=["Login"])

                switches_df = None
                if switches_file is not None:
                    switches_df = load_switches_file(switches_file)

                account_df = build_report(summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label)
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df, switches_df)

            # =================================================
            # KPI OVERVIEW
            # =================================================
            st.markdown("### 2. Overview")

            k1, k2, k3, k4 = st.columns(4)
            total_clients = int(account_df["Login"].nunique())
            total_closed_lots = float(account_df["Closed Lots"].sum())
            net_pnl_total = float(account_df["NET PNL USD"].sum())
            total_credit = float(account_df["Credit"].sum())

            total_profit = float(account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum())
            total_loss = float(account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum())

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_clients:,}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Unique logins</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Closed lots</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_closed_lots:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Sheet-1 col H / 2</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Total Credit</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{total_credit:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Sheet-1 col F</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl_total:,.2f}</div>', unsafe_allow_html=True)
                st.markdown('<div class="metric-sub">Closing − Opening − Net D/W − Credit</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            chart_data = pd.DataFrame({"Side": ["Profit", "Loss"], "Amount": [total_profit, abs(total_loss)]}).set_index("Side")
            st.bar_chart(chart_data, height=260)

            # =================================================
            # FULL ACCOUNT TABLE
            # =================================================
            st.markdown("### 3. Full account P&L")
            st.dataframe(account_df, use_container_width=True)

            # =================================================
            # BOOK SUMMARY
            # =================================================
            st.markdown("### 4. A-Book / B-Book / Hybrid summary")
            st.dataframe(book_df, use_container_width=True)

            pnl_a = float(book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum())
            pnl_b = float(book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum())
            pnl_h = float(book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum())

            total_books_pnl = pnl_a + pnl_b + pnl_h
            result_label = "profit" if total_books_pnl >= 0 else "loss"
            st.markdown(f"**Client P&L across all books: {total_books_pnl:,.2f} ({result_label})**")

            # =================================================
            # TOP ACCOUNTS & GROUPS
            # =================================================
            st.markdown("### 5. Top accounts & groups")

            show_cols = [
                "Login", "Group", "Type",
                "Opening Equity", "Closing Equity",
                "NET DP/WD", "Credit",
                "Closed Lots", "NET PNL USD", "NET PNL %"
            ]

            t1, t2 = st.columns(2)
            with t1:
                st.markdown("**Top 10 gainer accounts**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=False).head(10)[show_cols], use_container_width=True)
            with t2:
                st.markdown("**Top 10 loser accounts**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=True).head(10)[show_cols], use_container_width=True)

            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(group_df.sort_values("NET_PNL_USD", ascending=False).head(10), use_container_width=True)
            with g2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(group_df.sort_values("NET_PNL_USD", ascending=True).head(10), use_container_width=True)

            # =================================================
            # A-BOOK VS LP BROKERAGE
            # =================================================
            st.markdown("### 6. A-Book vs LP brokerage")
            st.markdown(f"- Client **A-Book P&L**: **{pnl_a:,.2f}**")

            lp_table = None
            total_lp_pnl = 0.0
            if lp_file is not None:
                lp_table = load_lp_breakdown_file(lp_file)
                total_lp_pnl = float(lp_table["LP_PnL"].sum())
                st.markdown("#### LP breakdown")
                st.dataframe(lp_table, use_container_width=True)
                st.markdown(f"- Total LP P&L: **{total_lp_pnl:,.2f}**")
            else:
                st.info("LP breakdown file not uploaded – brokerage P&L will be 0.")

            brokerage_pnl = total_lp_pnl - pnl_a
            st.markdown(f"- **Brokerage P&L = {total_lp_pnl:,.2f} − {pnl_a:,.2f} = {brokerage_pnl:,.2f}**")

            # =================================================
            # DOWNLOAD EXCEL
            # =================================================
            st.markdown("### 7. Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                abook_lp_rows = [{"Metric": "Client_A_Book_PnL", "Value": pnl_a}]
                if lp_table is not None:
                    for _, row in lp_table.iterrows():
                        abook_lp_rows.append({"Metric": f"LP_{row['LPName']}_PnL", "Value": row["LP_PnL"]})
                abook_lp_rows.append({"Metric": "Total_LP_PnL", "Value": total_lp_pnl})
                abook_lp_rows.append({"Metric": "Brokerage_PnL", "Value": brokerage_pnl})
                pd.DataFrame(abook_lp_rows).to_excel(writer, index=False, sheet_name="Abook_vs_LP")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{str(eod_label).replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
