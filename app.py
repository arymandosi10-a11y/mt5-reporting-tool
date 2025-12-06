import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ============================================================
# PAGE SETUP & GLOBAL STYLES
# ============================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
body, .main {
    background: radial-gradient(circle at top left, #eef2ff 0, #f9fafb 40%, #ffffff 100%);
    color: #0f172a;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 0.5rem;
    padding-bottom: 2rem;
}
h1, h2, h3, h4 {
    font-weight: 700;
}
.app-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
}
.app-badge {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: linear-gradient(135deg, #4f46e5, #06b6d4);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 1.4rem;
}
.app-title-text {
    display: flex;
    flex-direction: column;
}
.app-title-text span.subtitle {
    font-size: 0.85rem;
    color: #64748b;
}
.metric-card {
    background: rgba(255,255,255,0.9);
    border-radius: 16px;
    padding: 0.8rem 1rem;
    border: 1px solid #e5e7eb;
    box-shadow: 0 4px 16px rgba(15,23,42,0.04);
}
.metric-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
}
.metric-value {
    font-size: 1.3rem;
    font-weight: 600;
    margin-top: 0.1rem;
}
.section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0.6rem 0 0.2rem 0;
}
.section-caption {
    font-size: 0.82rem;
    color: #6b7280;
    margin-bottom: 0.4rem;
}
.step-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    background: #eef2ff;
    color: #4f46e5;
    font-size: 0.75rem;
    font-weight: 500;
    margin-bottom: 0.4rem;
}
.step-pill span.num {
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: #4f46e5;
    color: white;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
}
</style>
""",
    unsafe_allow_html=True,
)

# Header
st.markdown(
    """
<div class="app-header">
  <div class="app-badge">₿</div>
  <div class="app-title-text">
    <span>Client P&L Monitoring Dashboard</span>
    <span class="subtitle">A-Book / B-Book / Hybrid, switches & LP comparison</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Expected column positions (0-based index):
        0: Login
        2: Deposit (C)
        5: Withdrawal (F)
        7: Closed volume (H)          -> Closed lots = H / 2
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
        raise ValueError("Summary sheet must have at least 13 columns (up to column M).")

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
    equity_col = find_col(["equity"], 9)  # column J
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
    """Read a book-accounts file: expect Login and optional Group."""
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
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_switches_file(file) -> pd.DataFrame:
    """
    Multiple account book switches + hybrid ratios.

    Expected columns (case-insensitive):
      - Login
      - FromType
      - ToType
      - ShiftEquity
      - HybridA_Pct (optional)
      - HybridB_Pct (optional)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col_name, required=False):
        for k, v in lower.items():
            if k == col_name.lower():
                return df[v]
        if required:
            raise ValueError(f"Switches file must contain column '{col_name}'")
        return None

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(pick("login", True), errors="coerce").astype("Int64")
    out["ShiftFrom"] = pick("fromtype", True).astype(str)
    out["ShiftTo"] = pick("totype", True).astype(str)
    out["ShiftEquity"] = pd.to_numeric(pick("shiftequity", True), errors="coerce")
    a_pct = pick("hybrida_pct", False)
    b_pct = pick("hybridb_pct", False)
    out["HybridA_Pct"] = (
        pd.to_numeric(a_pct, errors="coerce") if a_pct is not None else np.nan
    )
    out["HybridB_Pct"] = (
        pd.to_numeric(b_pct, errors="coerce") if b_pct is not None else np.nan
    )
    return out


def build_account_report(summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label):
    """
    Merge all sources & calculate per-account metrics.
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # numeric safety
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

    # Closed lots from summary H column
    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # NET DP/WD
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]

    # NET PNL USD
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    # Merge switches (multi-account)
    report["ShiftFrom"] = np.nan
    report["ShiftTo"] = np.nan
    report["ShiftEquity"] = np.nan
    report["HybridA_Pct"] = np.nan
    report["HybridB_Pct"] = np.nan

    if switches_df is not None and not switches_df.empty:
        report = report.merge(
            switches_df,
            on="Login",
            how="left",
            suffixes=("", "_sw"),
        )
        # If there is a switch, override book type
        report["ShiftFrom"] = report["ShiftFrom"].fillna(report["OrigType"])
        report["ShiftTo"] = report["ShiftTo"]
        report["ShiftEquity"] = report["ShiftEquity"]
        report["HybridA_Pct"] = report["HybridA_Pct"]
        report["HybridB_Pct"] = report["HybridB_Pct"]

        # final type = ShiftTo where not null, else original
        report["Type"] = np.where(
            report["ShiftTo"].notna(), report["ShiftTo"], report["Type"]
        )
    else:
        report["ShiftFrom"] = report["OrigType"]

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
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "ShiftFrom",
        "ShiftTo",
        "ShiftEquity",
        "HybridA_Pct",
        "HybridB_Pct",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)

    # PnL %
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # reorder a bit for nicer display
    display_cols = [
        "Login",
        "Group",
        "OrigType",
        "Type",
        "Currency",
        "Opening Equity",
        "Closing Equity",
        "NET DP/WD",
        "NET PNL USD",
        "NET PNL %",
        "Closed Lots",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "ShiftFrom",
        "ShiftTo",
        "ShiftEquity",
        "HybridA_Pct",
        "HybridB_Pct",
        "EOD Closing Equity Date",
    ]
    return report[display_cols]


def build_book_contributions(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build contribution rows per book, splitting switches and hybrid ratios.

    For each account:
      - if no switch -> all PnL to final Type
      - if switch & ToType != Hybrid -> split into old / new book
      - if switch & ToType == Hybrid -> split post-switch PnL into A/B
        according to HybridA_Pct / HybridB_Pct, and also record Hybrid PnL.
    """
    rows = []
    for _, r in account_df.iterrows():
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        opening = float(r["Opening Equity"])
        closing = float(r["Closing Equity"])

        orig_type = str(r["OrigType"])
        final_type = str(r["Type"])

        shift_to = r["ShiftTo"]
        shift_eq = r["ShiftEquity"]

        # No switch specified
        if pd.isna(shift_to) or pd.isna(shift_eq):
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
            continue

        shift_from = str(r["ShiftFrom"]) if not pd.isna(r["ShiftFrom"]) else orig_type
        shift_to = str(shift_to)

        # post-switch PnL
        pnl_new_total = closing - shift_eq
        pnl_old = net_pnl - pnl_new_total

        # old book contribution (no account count)
        rows.append(
            {
                "Type": shift_from,
                "Accounts": 0,
                "Closed_Lots": 0.0,
                "NET_PNL_USD": pnl_old,
            }
        )

        if shift_to == "Hybrid":
            a_pct = r["HybridA_Pct"]
            b_pct = r["HybridB_Pct"]
            if pd.isna(a_pct) and pd.isna(b_pct):
                a_pct, b_pct = 50.0, 50.0
            elif pd.isna(a_pct):
                a_pct = 100.0 - float(b_pct)
            elif pd.isna(b_pct):
                b_pct = 100.0 - float(a_pct)

            total_pct = float(a_pct) + float(b_pct)
            if total_pct <= 0:
                a_frac = b_frac = 0.5
            else:
                a_frac = float(a_pct) / total_pct
                b_frac = float(b_pct) / total_pct

            # contributions to A & B (for risk / brokerage)
            rows.append(
                {
                    "Type": "A-Book",
                    "Accounts": 0,
                    "Closed_Lots": closed_lots * a_frac,
                    "NET_PNL_USD": pnl_new_total * a_frac,
                }
            )
            rows.append(
                {
                    "Type": "B-Book",
                    "Accounts": 0,
                    "Closed_Lots": closed_lots * b_frac,
                    "NET_PNL_USD": pnl_new_total * b_frac,
                }
            )
            # full hybrid for reporting
            rows.append(
                {
                    "Type": "Hybrid",
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": pnl_new_total,
                }
            )
        else:
            # normal switch
            rows.append(
                {
                    "Type": shift_to,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": pnl_new_total,
                }
            )

    contrib = pd.DataFrame(rows)
    return contrib


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


# ============================================================
# SIDEBAR – MULTI-LP INPUT
# ============================================================
with st.sidebar:
    st.markdown("### 🏛️ A-Book LP P&L (optional)")
    st.caption(
        "Fill this if you want to see A-Book brokerage vs one or more LPs.\n\n"
        "LP P&L formula: **Close − Open − Net D/W**."
    )

    default_lp = pd.DataFrame(
        [{"LP Name": "LP1", "Opening": 0.0, "Closing": 0.0, "Net_DW": 0.0}]
    )
    lp_table = st.data_editor(
        default_lp,
        num_rows="dynamic",
        key="lp_table",
        use_container_width=True,
    )

    lp_table_clean = lp_table.copy()
    lp_table_clean["LP Name"] = lp_table_clean["LP Name"].astype(str).str.strip()
    lp_table_clean = lp_table_clean[
        (lp_table_clean["LP Name"] != "")
        | (lp_table_clean[["Opening", "Closing", "Net_DW"]].abs().sum(axis=1) > 0)
    ]
    if not lp_table_clean.empty:
        lp_table_clean["LP_PnL"] = (
            lp_table_clean["Closing"]
            - lp_table_clean["Opening"]
            - lp_table_clean["Net_DW"]
        )
        total_lp_pnl = float(lp_table_clean["LP_PnL"].sum())
    else:
        lp_table_clean = pd.DataFrame(
            columns=["LP Name", "Opening", "Closing", "Net_DW", "LP_PnL"]
        )
        total_lp_pnl = 0.0

# ============================================================
# MAIN UI – FILE UPLOAD
# ============================================================
st.markdown('<div class="step-pill"><span class="num">1</span> Upload MT5 files</div>', unsafe_allow_html=True)

eod_label = st.text_input(
    "EOD Closing Equity Date (will be stored in the report)",
    placeholder="e.g. 2025-12-02 EOD",
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        help="Must include columns up to H (Closed Volume) and K, M.",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        help="Daily equity snapshot for the closing date.",
    )
with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        help="Previous EOD equity snapshot (used as opening equity).",
    )
with c4:
    switches_file = st.file_uploader(
        "Book switches & Hybrid ratios (optional, multiple accounts)",
        type=["xlsx", "xls", "csv"],
        help=(
            "Columns: Login, FromType, ToType, ShiftEquity, "
            "HybridA_Pct, HybridB_Pct. Used to split PnL between books."
        ),
    )

st.markdown('<div class="step-pill"><span class="num">2</span> Account book mappings</div>', unsafe_allow_html=True)

m1, m2, m3 = st.columns(3)
with m1:
    a_book_file = st.file_uploader(
        "A-Book accounts (Login & optional Group)",
        type=["xlsx", "xls", "csv"],
        key="abook",
    )
with m2:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="bbook",
    )
with m3:
    hybrid_file = st.file_uploader(
        "Hybrid accounts",
        type=["xlsx", "xls", "csv"],
        key="hybrid",
        help="Accounts that are fully Hybrid at the start of the day.",
    )

st.markdown("---")

# ============================================================
# MAIN ACTION
# ============================================================
generate = st.button("🚀 Generate report", type="primary")

if generate:
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload **Summary**, **Closing Equity** and **Opening Equity** files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: **A-Book**, **B-Book** or **Hybrid** accounts file.")
    elif not eod_label:
        st.error("Please enter the **EOD Closing Equity Date** text.")
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

                accounts_df = pd.concat(accounts_frames, ignore_index=True)
                accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

                switches_df = None
                if switches_file is not None:
                    switches_df = load_switches_file(switches_file)

                account_df = build_account_report(
                    summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label
                )
                group_df = build_group_summary(account_df)
                contrib_df = build_book_contributions(account_df)
                book_df = (
                    contrib_df.groupby("Type", as_index=False)
                    .agg(
                        Accounts=("Accounts", "sum"),
                        Closed_Lots=("Closed_Lots", "sum"),
                        NET_PNL_USD=("NET_PNL_USD", "sum"),
                    )
                )

            # ====================================================
            # OVERVIEW KPIs
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">3</span> Overview</div>',
                unsafe_allow_html=True,
            )

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            total_pnl = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with k1:
                st.markdown('<div class="metric-card"><div class="metric-label">Clients</div>'
                            f'<div class="metric-value">{int(total_clients)}</div></div>',
                            unsafe_allow_html=True)
            with k2:
                st.markdown('<div class="metric-card"><div class="metric-label">Closed lots</div>'
                            f'<div class="metric-value">{total_closed_lots:,.2f}</div></div>',
                            unsafe_allow_html=True)
            with k3:
                st.markdown('<div class="metric-card"><div class="metric-label">Net client P&L</div>'
                            f'<div class="metric-value">{total_pnl:,.2f}</div></div>',
                            unsafe_allow_html=True)
            with k4:
                profit_abs = float(total_profit)
                loss_abs = float(abs(total_loss))
                denom = profit_abs + loss_abs
                if denom > 0:
                    profit_pct = profit_abs / denom * 100.0
                    loss_pct = loss_abs / denom * 100.0
                else:
                    profit_pct = loss_pct = 0.0
                st.markdown(
                    '<div class="metric-card"><div class="metric-label">Profit vs loss</div>'
                    f'<div class="metric-value">P {profit_pct:.1f}% / L {loss_pct:.1f}%</div></div>',
                    unsafe_allow_html=True,
                )

            chart_data = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.markdown("#### Profit vs loss chart")
            st.bar_chart(chart_data)

            # ====================================================
            # FULL ACCOUNT TABLE
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">4</span> Full account P&L</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(account_df, use_container_width=True)

            # ====================================================
            # BOOK SUMMARY
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">5</span> A-Book / B-Book / Hybrid summary</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(book_df, use_container_width=True)

            effective_abook_pnl = float(
                contrib_df.loc[contrib_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            )
            effective_bbook_pnl = float(
                contrib_df.loc[contrib_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            )
            effective_hybrid_pnl = float(
                contrib_df.loc[contrib_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()
            )

            st.markdown(
                f"- Effective **A-Book P&L** (including switches & hybrid split): **{effective_abook_pnl:,.2f}**"
            )
            st.markdown(
                f"- Effective **B-Book P&L** (including switches & hybrid split): **{effective_bbook_pnl:,.2f}**"
            )
            st.markdown(
                f"- Reported **Hybrid P&L** (total of Hybrid segments): **{effective_hybrid_pnl:,.2f}**"
            )
            st.markdown(
                f"- Total client P&L from accounts (no double-counting): **{total_pnl:,.2f}**"
            )

            # ====================================================
            # TOP GAINERS / LOSERS (ACCOUNTS & GROUPS)
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">6</span> Top gainers & losers</div>',
                unsafe_allow_html=True,
            )

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
            gcol, lcol = st.columns(2)
            with gcol:
                st.markdown("**Top 10 gainer accounts**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=False).head(10)[
                        cols_show
                    ],
                    use_container_width=True,
                )
            with lcol:
                st.markdown("**Top 10 loser accounts**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=True).head(10)[
                        cols_show
                    ],
                    use_container_width=True,
                )

            st.markdown("**Top 10 profit groups (by P&L)**")
            st.dataframe(
                group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                use_container_width=True,
            )
            st.markdown("**Top 10 loss groups (by P&L)**")
            st.dataframe(
                group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                use_container_width=True,
            )

            # ====================================================
            # A-BOOK vs LP BROKERAGE
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">7</span> A-Book vs LP brokerage</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"- Client **A-Book P&L** (effective): **{effective_abook_pnl:,.2f}**"
            )
            st.markdown(f"- Total **LP P&L** (sum of all LPs): **{total_lp_pnl:,.2f}**")

            brokerage_pnl = total_lp_pnl - effective_abook_pnl  # as requested
            st.markdown(
                f"- **Brokerage P&L = LP_PnL − Client_A_Book_PnL = {brokerage_pnl:,.2f}**"
            )

            if not lp_table_clean.empty:
                st.markdown("**LP breakdown**")
                st.dataframe(lp_table_clean, use_container_width=True)

            # ====================================================
            # DOWNLOAD EXCEL
            # ====================================================
            st.markdown(
                '<div class="step-pill"><span class="num">8</span> Download Excel</div>',
                unsafe_allow_html=True,
            )

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # A-book vs LP sheet
                summary_rows = pd.DataFrame(
                    {
                        "Metric": [
                            "Client_A_Book_PnL",
                            "Total_LP_PnL",
                            "Brokerage_PnL",  # LP − Client
                        ],
                        "Value": [effective_abook_pnl, total_lp_pnl, brokerage_pnl],
                    }
                )
                summary_rows.to_excel(
                    writer, index=False, sheet_name="Abook_vs_LP", startrow=0
                )
                if not lp_table_clean.empty:
                    lp_table_clean.to_excel(
                        writer,
                        index=False,
                        sheet_name="Abook_vs_LP",
                        startrow=len(summary_rows) + 2,
                    )

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")

::contentReference[oaicite:0]{index=0}
