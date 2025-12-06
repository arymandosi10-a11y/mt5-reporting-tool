# app.py
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
#  PAGE CONFIG + GLOBAL STYLE
# =========================================================
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS (light premium look) ---
st.markdown(
    """
<style>
/* Overall page */
html, body, .main {
    background: radial-gradient(circle at top left, #fdfbff 0, #eef2f9 45%, #e8f2ff 100%);
    color: #0f172a;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Segoe UI", sans-serif;
}

/* Center content a bit, like dashboard */
.block-container {
    max-width: 1400px;
    padding-top: 1.3rem;
    padding-bottom: 3rem;
}

/* Section titles */
h1, h2, h3 {
    font-weight: 650;
}

/* Hero header */
.hero {
    background: linear-gradient(135deg, #0f172a, #1d4ed8);
    color: #f9fafb;
    border-radius: 18px;
    padding: 20px 26px;
    margin-bottom: 1.5rem;
    box-shadow: 0 18px 45px rgba(15,23,42,0.35);
}
.hero-title {
    font-size: 1.8rem;
    font-weight: 680;
}
.hero-sub {
    font-size: 0.96rem;
    opacity: 0.85;
}

/* Card-like containers */
.card {
    background: #ffffff;
    border-radius: 16px;
    padding: 18px 20px;
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
    border: 1px solid rgba(148,163,184,0.22);
}

/* Small “metric” cards */
.metric-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 12px 16px;
    border: 1px solid rgba(148,163,184,0.25);
    box-shadow: 0 10px 26px rgba(15,23,42,0.04);
}
.metric-label {
    font-size: 0.75rem;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: #6b7280;
}
.metric-value {
    font-size: 1.25rem;
    font-weight: 650;
    margin-top: 2px;
}

/* Dataframe tweaks */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    border: 1px solid rgba(148,163,184,0.35);
    overflow: hidden;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f9fafb 0, #eef2ff 40%, #e0f2fe 100%);
    border-right: 1px solid rgba(148,163,184,0.40);
}
section[data-testid="stSidebar"] h2 {
    font-size: 1rem !important;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #0f172a;
}

/* Buttons */
.stButton>button {
    border-radius: 999px;
    padding: 0.4rem 1.4rem;
    font-weight: 600;
    border: none;
    box-shadow: 0 10px 25px rgba(37,99,235,0.35);
    background: linear-gradient(135deg, #2563eb, #6366f1);
}

/* Upload widgets */
[data-testid="stFileUploader"] {
    border-radius: 16px;
}

/* Subtle labels */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 600;
    background: rgba(15,23,42,0.07);
    color: #4b5563;
}
.badge-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: #22c55e;
    margin-right: 6px;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
#  HELPER FUNCTIONS
# =========================================================
def load_summary_sheet(file) -> pd.DataFrame:
    """
    Sheet 1 – Summary / Transactions

    Expected columns (0-based index):
      0: Login (A)
      4: NET DP/WD (E)
      7: Closed Volume (H)   --> Closed lots = H/2
      8: Commission (I)
      10: Swap (K)

    We group by Login.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        raw = pd.read_csv(file)
    else:
        try:
            # many MT5 exports have headers on row 3
            raw = pd.read_excel(file, header=2)
        except Exception:
            raw = pd.read_excel(file)

    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must have at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["NetDPWD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = (
        df.groupby("Login", as_index=False)[
            ["NetDPWD", "ClosedVolume", "Commission", "Swap"]
        ]
        .sum()
    )
    return grouped


def load_equity_sheet(file) -> pd.DataFrame:
    """
    Sheet 2 & 3 – MT5 Daily report (EOD equity snapshot).
    Needs columns: Login, Equity, Currency.
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
    equity_col = find_col(["equity"], 9)  # column J in many MT5 exports
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
    Generic reader for A-Book / B-Book / Hybrid accounts file.
    Expect at least a Login column, optional Group.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}
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


def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df


def load_shift_file(file) -> pd.DataFrame:
    """
    Optional book-switch overrides (multiple accounts).

    Required columns (case-insensitive):
      Login, FromType, ToType, ShiftEquity

    Optional:
      HybridRatio   (0-1)  – not used in summary yet but kept for reference.
    """
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    lower = {c.lower(): c for c in df.columns}

    def pick(name):
        for k, v in lower.items():
            if k == name.lower():
                return v
        raise ValueError(f"Shift file must contain column '{name}'")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(
        0.0
    )
    if "hybridratio" in lower:
        out["HybridRatio"] = pd.to_numeric(
            df[lower["hybridratio"]], errors="coerce"
        ).fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan
    return out


def build_report(summary_df, closing_df, opening_df, accounts_df, shift_df, eod_label):
    """
    Core account-level report.

    NET PNL USD = Closing Equity – Opening Equity – NetDPWD.
    Closed lots = ClosedVolume / 2 (in+out).
    """
    base = closing_df.rename(
        columns={"Equity": "Closing Equity", "Currency": "Currency"}
    ).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # Ensure numeric columns
    for col in [
        "Closing Equity",
        "Opening Equity",
        "NetDPWD",
        "ClosedVolume",
        "Commission",
        "Swap",
    ]:
        if col in report.columns:
            report[col] = pd.to_numeric(report[col], errors="coerce").fillna(0.0)
        else:
            report[col] = 0.0

    report["Closed Lots"] = report["ClosedVolume"] / 2.0
    report["NET DP/WD"] = report["NetDPWD"]

    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET DP/WD"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"].abs() > 0,
        (report["NET PNL USD"] / report["Opening Equity"].abs()) * 100.0,
        0.0,
    )

    # Apply book switches if provided
    report["ShiftFromType"] = np.nan
    report["ShiftToType"] = np.nan
    report["ShiftEquity"] = np.nan
    report["HybridRatio"] = np.nan

    if shift_df is not None and not shift_df.empty:
        report = report.merge(shift_df, on="Login", how="left", suffixes=("", "_sh"))
        # if ToType present, override Type
        report["ShiftFromType"] = report["FromType"]
        report["ShiftToType"] = report["ToType"]
        report["ShiftEquity"] = report["ShiftEquity"].fillna(0.0)
        report["HybridRatio"] = report["HybridRatio"].fillna(np.nan)
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
        "Commission",
        "Swap",
        "ShiftFromType",
        "ShiftToType",
        "ShiftEquity",
        "HybridRatio",
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
    Book-level summary with split for accounts that switched book.

    If no shift: entire P&L goes to final Type.
    If shifted:
        net = NET_PNL
        pnl_new = Closing - ShiftEquity
        pnl_old = net - pnl_new
    """
    rows = []
    for _, r in account_df.iterrows():
        net = r["NET PNL USD"]
        closed_lots = r["Closed Lots"]
        closing = r["Closing Equity"]
        orig_type = r["OrigType"]
        final_type = r["Type"]
        shift_eq = r["ShiftEquity"]
        shift_to = r["ShiftToType"]

        # no switch
        if pd.isna(shift_to) or orig_type == final_type:
            rows.append(
                {
                    "Type": final_type,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": net,
                }
            )
        else:
            pnl_new = closing - shift_eq
            pnl_old = net - pnl_new

            # Old book contribution
            rows.append(
                {
                    "Type": r["ShiftFromType"],
                    "Accounts": 0,
                    "Closed_Lots": 0.0,
                    "NET_PNL_USD": pnl_old,
                }
            )
            # New book contribution (account counted here)
            rows.append(
                {
                    "Type": shift_to,
                    "Accounts": 1,
                    "Closed_Lots": closed_lots,
                    "NET_PNL_USD": pnl_new,
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


def load_lp_breakdown(lp_file: BytesIO | None):
    """
    LP breakdown file (multi-LP).

    Expected columns (case-insensitive):
      LPName, OpeningEquity, ClosingEquity, NetDPWD
    """
    if lp_file is None:
        return pd.DataFrame()

    name = lp_file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(lp_file)
    else:
        df = pd.read_excel(lp_file)

    lower = {c.lower(): c for c in df.columns}

    def pick(colname, default=None):
        for k, v in lower.items():
            if k == colname.lower():
                return v
        if default is not None:
            return default
        raise ValueError(f"LP file must contain column '{colname}'")

    out = pd.DataFrame()
    out["LPName"] = df[pick("lpname")].astype(str)
    out["OpeningEquity"] = pd.to_numeric(
        df[pick("openingequity")], errors="coerce"
    ).fillna(0.0)
    out["ClosingEquity"] = pd.to_numeric(
        df[pick("closingequity")], errors="coerce"
    ).fillna(0.0)
    out["NetDPWD"] = pd.to_numeric(df[pick("netdpwd")], errors="coerce").fillna(0.0)

    out["LP_PnL"] = out["ClosingEquity"] - out["OpeningEquity"] - out["NetDPWD"]
    return out


# =========================================================
#  SIDEBAR – LP PANEL
# =========================================================
with st.sidebar:
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.write(
        "Upload an **LP breakdown file** (multi-LP) or keep it empty. "
        "Brokerage = total LP P&L − client A-Book P&L."
    )

    lp_file = st.file_uploader(
        "LP breakdown file (XLSX / CSV)",
        type=["xlsx", "xls", "csv"],
        key="lp_file",
    )

    st.markdown("---")
    st.caption(
        "If you don’t upload a file you can still enter a single LP manually on the results sheet."
    )

# =========================================================
#  HERO HEADER
# =========================================================
st.markdown(
    """
<div class="hero">
  <div class="badge"><span class="badge-dot"></span>FX client book monitor</div>
  <div style="margin-top:8px" class="hero-title">Client P&L Monitoring Tool</div>
  <div class="hero-sub">
    Upload MT5 exports to see account-wise, group-wise and book-wise P&amp;L,
    including A-Book vs B-Book vs Hybrid and A-Book vs LP brokerage.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
#  1. UPLOAD MT5 REPORTS
# =========================================================
st.markdown("### 1. Upload MT5 reports")

with st.container():
    eod_label = st.text_input(
        "EOD Closing Equity Date (stored in reports)",
        value="",
        placeholder="e.g. 2025-12-06 EOD",
    )

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        summary_file = st.file_uploader(
            "Sheet 1 – Summary / Transactions",
            type=["xlsx", "xls", "csv"],
            help="MT5 summary export with NET DP/WD (column E), H volume, I commission, K swap.",
            key="summary",
        )
    with col_s2:
        closing_file = st.file_uploader(
            "Sheet 2 – Closing Equity (EOD for report period)",
            type=["xlsx", "xls"],
            help="Daily report for the closing date (equity snapshot).",
            key="closing",
        )

    col_s3, col_s4 = st.columns(2)
    with col_s3:
        opening_file = st.file_uploader(
            "Sheet 3 – Opening Equity (previous EOD)",
            type=["xlsx", "xls"],
            help="Previous EOD daily report (used as opening equity).",
            key="opening",
        )

# Accounts mapping
st.markdown("#### Account mapping by book")

c_a, c_b, c_h = st.columns(3)
with c_a:
    a_book_file = st.file_uploader(
        "A-Book accounts (Login + optional Group)",
        type=["xlsx", "xls", "csv"],
        key="abook",
    )
with c_b:
    b_book_file = st.file_uploader(
        "B-Book accounts",
        type=["xlsx", "xls", "csv"],
        key="bbook",
    )
with c_h:
    hybrid_file = st.file_uploader(
        "Hybrid accounts (optional)",
        type=["xlsx", "xls", "csv"],
        key="hybrid",
    )

st.markdown("#### Book switch overrides (optional – multiple accounts)")
switch_file = st.file_uploader(
    "Upload book switch file (Login, FromType, ToType, ShiftEquity, optional HybridRatio)",
    type=["xlsx", "xls", "csv"],
    key="switch",
)

st.markdown("---")

# =========================================================
#  MAIN ACTION
# =========================================================
if st.button("🚀 Generate report"):
    # basic validation
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
    elif not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book or Hybrid accounts.")
    elif not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
    else:
        try:
            with st.spinner("Processing files & calculating P&L…"):
                summary_df = load_summary_sheet(summary_file)
                closing_df = load_equity_sheet(closing_file)
                opening_df = load_equity_sheet(opening_file)

                # Accounts mapping from A/B/Hybrid files
                frames = []
                if a_book_file:
                    frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file:
                    frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_file:
                    frames.append(load_book_accounts(hybrid_file, "Hybrid"))
                accounts_df = pd.concat(frames, ignore_index=True).drop_duplicates(
                    subset=["Login"], keep="first"
                )

                # Shift overrides (multiple accounts)
                shift_df = None
                if switch_file is not None:
                    shift_df = load_shift_file(switch_file)

                account_df = build_report(
                    summary_df, closing_df, opening_df, accounts_df, shift_df, eod_label
                )
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # =================================================
            # 2. HIGH-LEVEL SNAPSHOT
            # =================================================
            st.markdown("### 2. High-level snapshot of today's client P&L")

            m1, m2, m3, m4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            total_closed_lots = account_df["Closed Lots"].sum()
            net_pnl = account_df["NET PNL USD"].sum()
            total_profit = account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum()
            total_loss = account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum()

            with m1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Active accounts</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="metric-value">{int(total_clients):,}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with m2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Closed lots (summary H/2)</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="metric-value">{total_closed_lots:,.2f}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            with m3:
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

            with m4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown(
                    '<div class="metric-label">Profit vs loss mix</div>',
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

            # Simple bar chart – profit vs loss
            chart_df = pd.DataFrame(
                {"Side": ["Profit", "Loss"], "Amount": [profit_abs, loss_abs]}
            ).set_index("Side")
            st.bar_chart(chart_df)

            # =================================================
            # 3. FULL ACCOUNT P&L
            # =================================================
            st.markdown("### 3. Full account P&L")
            st.markdown(
                "Every row is a login with opening/closing equity, NET DP/WD from summary, "
                "commission and swap from MT5 summary and final NET P&L."
            )
            st.dataframe(account_df, use_container_width=True, height=420)

            # =================================================
            # 4. GROUP-WISE SUMMARY + TOP GROUPS
            # =================================================
            st.markdown("### 4. Group-wise P&L")
            st.dataframe(group_df, use_container_width=True, height=320)

            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**Top 10 profit groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=False).head(10),
                    use_container_width=True,
                )
            with g2:
                st.markdown("**Top 10 loss groups**")
                st.dataframe(
                    group_df.sort_values("NET_PNL_USD", ascending=True).head(10),
                    use_container_width=True,
                )

            # =================================================
            # 5. A-BOOK / B-BOOK / HYBRID SUMMARY
            # =================================================
            st.markdown("### 5. A-Book / B-Book / Hybrid summary")
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

            # =================================================
            # 6. TOP 10 ACCOUNTS (GAINERS / LOSERS)
            # =================================================
            st.markdown("### 6. Top 10 accounts")

            cols_to_show = [
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
            ca, cb = st.columns(2)
            with ca:
                st.markdown("**Top 10 gainers**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=False).head(10)[
                        cols_to_show
                    ],
                    use_container_width=True,
                )
            with cb:
                st.markdown("**Top 10 losers**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=True).head(10)[
                        cols_to_show
                    ],
                    use_container_width=True,
                )

            # =================================================
            # 7. A-BOOK VS LP BROKERAGE
            # =================================================
            st.markdown("### 7. A-Book vs LP brokerage")

            st.markdown(f"- **Client A-Book P&L (from books table):** {pnl_a:,.2f}")

            lp_breakdown_df = load_lp_breakdown(lp_file)
            if lp_breakdown_df.empty:
                # single manual LP (from sidebar inputs not used -> we keep PnL = 0)
                total_lp_pnl = 0.0
                st.info(
                    "No LP breakdown file uploaded. "
                    "You can still type LP info later in the Excel sheet."
                )
            else:
                total_lp_pnl = lp_breakdown_df["LP_PnL"].sum()
                # brokerage for each LP = LP_PnL − client A-Book P&L (for comparison)
                lp_breakdown_df["Brokerage_PnL"] = (
                    lp_breakdown_df["LP_PnL"] - pnl_a
                )
                st.markdown("**LP breakdown (file)**")
                st.dataframe(lp_breakdown_df, use_container_width=True)

            brokerage_total = total_lp_pnl - pnl_a
            st.markdown(
                f"- **Total LP P&L:** {total_lp_pnl:,.2f}  "
                f"<br>- **Brokerage P&L (Total LP − A-Book):** {brokerage_total:,.2f}",
                unsafe_allow_html=True,
            )

            # =================================================
            # 8. DOWNLOAD EXCEL REPORT
            # =================================================
            st.markdown("### 8. Download Excel report")

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="Accounts")
                group_df.to_excel(writer, index=False, sheet_name="Groups")
                book_df.to_excel(writer, index=False, sheet_name="Books")

                if not lp_breakdown_df.empty:
                    lp_breakdown_df.to_excel(
                        writer, index=False, sheet_name="LP_Breakdown"
                    )

                # A-Book vs LP summary sheet
                abook_lp_df = pd.DataFrame(
                    {
                        "Metric": [
                            "Client_A_Book_PnL",
                            "Total_LP_PnL",
                            "Brokerage_PnL_Total (LP - A_Book)",
                        ],
                        "Value": [pnl_a, total_lp_pnl, brokerage_total],
                    }
                )
                abook_lp_df.to_excel(writer, index=False, sheet_name="Abook_vs_LP")

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
