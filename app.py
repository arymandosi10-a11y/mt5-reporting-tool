import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# BASIC PAGE SETUP & STYLING
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Tailwind-like minimal styling
st.markdown(
    """
<style>
body, .main {
    background: radial-gradient(circle at top left, #1d4ed8 0, #020617 55%);
    color: #e5e7eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}
.app-card {
    background: rgba(15,23,42,0.92);
    border-radius: 18px;
    padding: 1.2rem 1.4rem;
    border: 1px solid rgba(148,163,184,0.35);
    box-shadow: 0 18px 40px rgba(15,23,42,0.9);
}
.metric-card {
    background: rgba(15,23,42,0.92);
    border-radius: 16px;
    padding: 0.9rem 1.1rem;
    border: 1px solid rgba(148,163,184,0.35);
}
.metric-label {
    font-size: 0.78rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.metric-value {
    font-size: 1.25rem;
    font-weight: 650;
    margin-top: 0.2rem;
    color: #f9fafb;
}
h1, h2, h3, h4 {
    color: #e5e7eb !important;
}
.dataframe td, .dataframe th {
    color: #e5e7eb !important;
}
.stDownloadButton button {
    border-radius: 999px;
    border: none;
    background: linear-gradient(135deg,#22c55e,#16a34a);
    color: white;
    font-weight: 600;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div style="display:flex;align-items:center;gap:0.8rem;margin-bottom:0.8rem;">
  <div style="width:38px;height:38px;border-radius:999px;background:linear-gradient(135deg,#22d3ee,#6366f1);display:flex;align-items:center;justify-content:center;font-size:22px;">📊</div>
  <div>
    <div style="font-size:1.6rem;font-weight:700;">Client P&L Monitoring Tool</div>
    <div style="font-size:0.9rem;color:#9ca3af;">
      MT5 daily exports → account, group & book wise P&amp;L with A-Book / B-Book / Hybrid & LP comparison.
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
# HELPERS – LOADING SHEETS
# =========================================================
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1: Summary / Transactions

    Positions (0-based index):
      0: Login
      2: Deposit (C)
      5: Withdrawal (F)
      7: Closed volume (H)          -> ClosedLots = H / 2
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
        ].sum()
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
    equity_col = find_col(["equity"], 9)
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
    """
    Read a book-accounts file: expect Login and optional Group.
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
    Multiple switches file.

    Columns (case-insensitive):
      Login, FromType, ToType, ShiftEquity
      HybridRatioA (0-1, optional, used when ToType='Hybrid')
      HybridRatioB (0-1, optional)
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col):
        for k, v in lower.items():
            if k == col.lower():
                return v
        raise ValueError(f"Switch file must contain column '{col}'")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce")

    # optional hybrid ratios
    ratio_a_col = None
    ratio_b_col = None
    for key, val in lower.items():
        if key == "hybridratoa" or key == "hybridratioa":
            ratio_a_col = val
        if key == "hybridratob":
            ratio_b_col = val

    if ratio_a_col is not None:
        out["HybridRatioA"] = (
            pd.to_numeric(df[ratio_a_col], errors="coerce").fillna(0.5) / 100.0
            if df[ratio_a_col].max() > 1
            else pd.to_numeric(df[ratio_a_col], errors="coerce").fillna(0.5)
        )
    else:
        out["HybridRatioA"] = 0.5

    if ratio_b_col is not None:
        out["HybridRatioB"] = (
            pd.to_numeric(df[ratio_b_col], errors="coerce").fillna(0.5) / 100.0
            if df[ratio_b_col].max() > 1
            else pd.to_numeric(df[ratio_b_col], errors="coerce").fillna(0.5)
        )
    else:
        out["HybridRatioB"] = 0.5

    return out


def load_lp_file(file) -> pd.DataFrame:
    """
    Multiple LPs file.

    Columns (case-insensitive):
      LPName, OpeningEquity, ClosingEquity, NetDPWD
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(col):
        for k, v in lower.items():
            if k == col.lower():
                return v
        raise ValueError(f"LP file must contain column '{col}'")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(df[pick("openingequity")], errors="coerce")
    out["ClosingEquity"] = pd.to_numeric(df[pick("closingequity")], errors="coerce")
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd")], errors="coerce")
    return out


# =========================================================
# REPORT BUILDERS
# =========================================================
def build_account_report(summary_df, closing_df, opening_df, accounts_df, switches_df, eod_label):
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

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

    report["Closed Lots"] = report["ClosedVolume"] / 2.0
    report["NET DP/WD"] = report["Deposit"] - report["Withdrawal"]
    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )
    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        report["NET PNL USD"] / report["Opening Equity"].abs() * 100.0,
        0.0,
    )

    # Merge switches (can be empty)
    if switches_df is None:
        switches_df = pd.DataFrame(
            columns=[
                "Login",
                "FromType",
                "ToType",
                "ShiftEquity",
                "HybridRatioA",
                "HybridRatioB",
            ]
        )

    report = report.merge(
        switches_df,
        on="Login",
        how="left",
        suffixes=("", "_sw"),
    )

    # If we have a ToType, override final Type
    report["ShiftEquity"] = pd.to_numeric(report["ShiftEquity"], errors="coerce")
    report["ShiftFromType"] = report["FromType"]
    report["ShiftToType"] = report["ToType"]
    report["HybridRatioA"] = pd.to_numeric(report["HybridRatioA"], errors="coerce").fillna(
        0.0
    )
    report["HybridRatioB"] = pd.to_numeric(report["HybridRatioB"], errors="coerce").fillna(
        0.0
    )

    report["Type"] = np.where(
        report["ShiftToType"].notna(), report["ShiftToType"], report["Type"]
    )

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
        "NET PNL %",
        "Deposit",
        "Withdrawal",
        "Commission",
        "Swap",
        "ShiftFromType",
        "ShiftToType",
        "ShiftEquity",
        "HybridRatioA",
        "HybridRatioB",
        "EOD Closing Equity Date",
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report


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


def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    """
    Allocate P&L into books, including split for switches with Hybrid ratios.

    For each account row:
      1. If there is no ShiftToType or ShiftEquity, entire P&L goes to OrigType.
      2. If ToType is A-Book or B-Book:
           - P_new = closing - shift_eq
           - P_old = net - P_new
      3. If ToType is Hybrid:
           - P_hybrid_total = closing - shift_eq
           - P_A_new = P_hybrid_total * HybridRatioA
           - P_B_new = P_hybrid_total * HybridRatioB
           - P_old    = net - (P_A_new + P_B_new)
    """
    rows = []

    for _, r in account_df.iterrows():
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        closing = float(r["Closing Equity"])
        orig_type = str(r["OrigType"])
        shift_to = r["ShiftToType"]
        shift_from = r["ShiftFromType"]
        shift_eq = r["ShiftEquity"]
        ratio_a = float(r["HybridRatioA"])
        ratio_b = float(r["HybridRatioB"])

        # no valid shift
        if pd.isna(shift_to) or pd.isna(shift_eq):
            rows.append(
                {
                    "Type": orig_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )
            continue

        shift_to = str(shift_to)
        shift_from = str(shift_from) if isinstance(shift_from, str) else orig_type
        shift_eq = float(shift_eq)

        if shift_to in ["A-Book", "B-Book"]:
            pnl_new = closing - shift_eq
            pnl_old = net_pnl - pnl_new

            rows.append(
                {
                    "Type": shift_from,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            rows.append(
                {
                    "Type": shift_to,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": pnl_new,
                }
            )

        elif shift_to == "Hybrid":
            # ensure ratios sum <= 1, default 0.5/0.5
            if ratio_a <= 0 and ratio_b <= 0:
                ratio_a = ratio_b = 0.5
            total_ratio = ratio_a + ratio_b
            if total_ratio == 0:
                ratio_a = ratio_b = 0.5
                total_ratio = 1
            ratio_a /= total_ratio
            ratio_b /= total_ratio

            pnl_hybrid_total = closing - shift_eq
            pnl_a_new = pnl_hybrid_total * ratio_a
            pnl_b_new = pnl_hybrid_total * ratio_b
            pnl_old = net_pnl - (pnl_a_new + pnl_b_new)

            rows.append(
                {
                    "Type": shift_from,
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            rows.append(
                {
                    "Type": "A-Book",
                    "Accounts": 1,
                    "Closed_Lots": closed_lots * ratio_a,
                    "NET_PNL_USD": pnl_a_new,
                }
            )
            rows.append(
                {
                    "Type": "B-Book",
                    "Accounts": 1,
                    "Closed_Lots": closed_lots * ratio_b,
                    "NET_PNL_USD": pnl_b_new,
                }
            )
        else:
            # Unknown shift type – send all to orig_type
            rows.append(
                {
                    "Type": orig_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net_pnl,
                }
            )

    contrib = pd.DataFrame(rows)
    book = (
        contrib.groupby("Type", as_index=False)
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
    )
    return book


# =========================================================
# SIDEBAR – SINGLE LP INPUT (OPTIONAL)
# =========================================================
with st.sidebar:
    st.markdown(
        "<div style='font-size:1rem;font-weight:600;margin-bottom:0.2rem;'>🏛 A-Book LP P&L (optional)</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Fill this to see A-Book brokerage vs LP. Formula: LP P&L = Close − Open − Net D/W. "
        "Brokerage = LP_PnL − Client_A_Book_PnL."
    )
    lp_open = st.number_input("LP opening equity", value=0.0, step=100.0, format="%.2f")
    lp_close = st.number_input("LP closing equity", value=0.0, step=100.0, format="%.2f")
    lp_net_dp = st.number_input(
        "LP net D/W (Deposit − Withdrawal)", value=0.0, step=100.0, format="%.2f"
    )
    lp_multi_file = st.file_uploader(
        "LPs file (optional, multiple LPs)",
        type=["xlsx", "xls", "csv"],
        key="lpfile",
        help="Columns: LPName, OpeningEquity, ClosingEquity, NetDPWD.",
    )

# =========================================================
# MAIN LAYOUT – UPLOADS
# =========================================================
st.markdown("### 1️⃣ Upload MT5 core files")

eod_label = st.text_input(
    "EOD Closing Equity Date (stored in the Excel report header)",
    placeholder="e.g. 2025-12-02 EOD",
)

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)

with c1:
    summary_file = st.file_uploader(
        "Sheet 1 – Summary / Transactions",
        type=["xlsx", "xls", "csv"],
        key="summary",
        help="Includes Deposit, Withdrawal, Closed volume (H), Commission, Swap.",
    )
with c2:
    closing_file = st.file_uploader(
        "Sheet 2 – Closing Equity (EOD for report period)",
        type=["xlsx", "xls"],
        key="closing",
        help="Daily equity snapshot for the closing date.",
    )
with c3:
    opening_file = st.file_uploader(
        "Sheet 3 – Opening Equity (previous EOD)",
        type=["xlsx", "xls"],
        key="opening",
        help="Previous EOD equity snapshot (used as opening equity).",
    )

st.markdown("### 2️⃣ Account book mappings")

bc1, bc2, bc3 = st.columns(3)
with bc1:
    a_book_file = st.file_uploader(
        "A-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="abook",
        help="File with columns: Login, optional Group.",
    )
with bc2:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="bbook",
        help="File with columns: Login, optional Group.",
    )
with bc3:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        key="hybrid",
    )

st.markdown("### 3️⃣ Book switches (optional – multiple accounts)")

st.caption(
    "Upload a file if some logins moved between books during this day or became Hybrid with A/B ratio. "
    "Required columns: **Login, FromType, ToType, ShiftEquity**. "
    "Optional for Hybrid: **HybridRatioA, HybridRatioB** (0–1 or 0–100%)."
)
switches_file = st.file_uploader(
    "Book switches file (optional)",
    type=["xlsx", "xls", "csv"],
    key="switches",
)

st.markdown("---")

# =========================================================
# MAIN ACTION BUTTON
# =========================================================
if st.button("🚀 Generate report", type="primary"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
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
                    summary_df,
                    closing_df,
                    opening_df,
                    accounts_df,
                    switches_df,
                    eod_label,
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # -------------------------------------------------
            # KPIs
            # -------------------------------------------------
            st.markdown("### 4️⃣ Overview")

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Clients</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="metric-value">{int(total_clients)}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Closed lots</div>', unsafe_allow_html=True
                )
                st.markdown(
                    f'<div class="metric-value">{total_closed_lots:,.2f}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Net client P&L</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="metric-value">{net_pnl:,.2f}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with k4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Profit vs loss</div>',
                    unsafe_allow_html=True,
                )
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

            # -------------------------------------------------
            # Full accounts table
            # -------------------------------------------------
            st.markdown("### 5️⃣ Full account P&L")
            st.dataframe(account_df, use_container_width=True)

            # -------------------------------------------------
            # Book summary
            # -------------------------------------------------
            st.markdown("### 6️⃣ A-Book / B-Book / Hybrid summary")
            st.dataframe(book_df, use_container_width=True)

            pnl_a = book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum()
            pnl_b = book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum()
            pnl_h = book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum()
            total_client_pnl = pnl_a + pnl_b + pnl_h
            client_result = "profit" if total_client_pnl >= 0 else "loss"
            st.markdown(
                f"**Client P&L across A-Book, B-Book & Hybrid (A + B + Hybrid): "
                f"{total_client_pnl:,.2f} ({client_result})**"
            )

            # -------------------------------------------------
            # Top gainers / losers (accounts)
            # -------------------------------------------------
            st.markdown("### 7️⃣ Top gainers & losers (accounts)")

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

            # -------------------------------------------------
            # Top gainers / losers (groups)
            # -------------------------------------------------
            st.markdown("### 8️⃣ Top groups by P&L")

            gg1, gg2 = st.columns(2)
            with gg1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                    use_container_width=True,
                )
            with gg2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                    use_container_width=True,
                )

            # -------------------------------------------------
            # A-Book vs LP brokerage
            # -------------------------------------------------
            st.markdown("### 9️⃣ A-Book vs LP brokerage")

            st.markdown(f"- Client A-Book P&L (from books table): **{pnl_a:,.2f}**")
            lp_pnl_manual = lp_close - lp_open - lp_net_dp
            if any([lp_open, lp_close, lp_net_dp]):
                st.markdown(
                    f"- LP P&L (Close − Open − Net D/W): **{lp_pnl_manual:,.2f}**"
                )
                brokerage_broker = lp_pnl_manual - pnl_a
                brokerage_client = pnl_a - lp_pnl_manual
                st.markdown(
                    f"- Brokerage P&L (broker view = LP − A-Book): **{brokerage_broker:,.2f}**"
                )
                st.markdown(
                    f"- Brokerage P&L (client view = A-Book − LP): **{brokerage_client:,.2f}**"
                )
            else:
                brokerage_broker = 0.0
                lp_pnl_manual = 0.0

            # Multiple LPs file (optional)
            lp_multi_df = None
            if lp_multi_file is not None:
                lp_multi_df = load_lp_file(lp_multi_file)
                lp_multi_df["LP_PnL"] = (
                    lp_multi_df["ClosingEquity"]
                    - lp_multi_df["OpeningEquity"]
                    - lp_multi_df["NetDPWD"]
                )
                lp_multi_df["Brokerage_PnL"] = lp_multi_df["LP_PnL"] - pnl_a
                st.markdown("**LP breakdown (file)**")
                st.dataframe(lp_multi_df, use_container_width=True)

            # -------------------------------------------------
            # Download Excel
            # -------------------------------------------------
            st.markdown("### 🔟 Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                # Single LP metrics sheet with formula
                metrics = [
                    "Client_A_Book_PnL",
                    "LP_Opening_Equity",
                    "LP_Closing_Equity",
                    "LP_NET_DP_WD",
                    "LP_PnL",
                    "Brokerage_PnL",  # formula row
                ]
                values = [
                    pnl_a,
                    lp_open,
                    lp_close,
                    lp_net_dp,
                    lp_pnl_manual,
                    "=B6-B2",  # LP_PnL - Client_A_Book_PnL
                ]
                abook_lp_df = pd.DataFrame({"Metric": metrics, "Value": values})
                abook_lp_df.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

                # Multiple LPs sheet (if provided)
                if lp_multi_df is not None:
                    lp_multi_df.to_excel(writer, index=False, sheet_name="LPs")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
