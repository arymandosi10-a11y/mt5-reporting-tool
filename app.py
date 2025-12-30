import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ============================================================
# PAGE CONFIG & GLOBAL STYLING
# ============================================================

st.set_page_config(page_title="Client P&L Monitoring Tool", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .main {
        background: radial-gradient(circle at top left, #ffffff 0, #f5f7fb 55%, #e9edf5 100%);
        color: #111827;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
    }
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1300px; }

    .hero-card {
        background: linear-gradient(135deg, #111827, #1f2937);
        color: #f9fafb;
        border-radius: 22px;
        padding: 1.8rem 2.2rem 1.6rem 2.2rem;
        box-shadow: 0 18px 50px rgba(15, 23, 42, 0.45);
        overflow: hidden;
    }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 0.4rem;
        padding: 0.15rem 0.7rem; border-radius: 999px;
        background: rgba(55, 65, 81, 0.8);
        font-size: 0.75rem; font-weight: 500;
        letter-spacing: .04em; text-transform: uppercase;
    }
    .hero-title { font-size: 2.0rem; font-weight: 700; margin-top: 0.7rem; margin-bottom: 0.4rem; }
    .hero-subtitle { font-size: 0.97rem; color: #d1d5db; max-width: 640px; }

    .metric-card {
        background: #ffffff; border-radius: 16px;
        padding: 0.9rem 1.1rem; border: 1px solid #e5e7eb;
        box-shadow: 0 12px 30px rgba(148, 163, 184, 0.24);
    }
    .metric-label {
        font-size: 0.78rem; color: #6b7280;
        text-transform: uppercase; letter-spacing: .06em;
    }
    .metric-value { font-size: 1.25rem; font-weight: 600; margin-top: 0.15rem; }

    .section-title {
        font-size: 1.1rem; font-weight: 650;
        margin-top: 1.8rem; margin-bottom: 0.4rem;
        display: flex; align-items: center; gap: 0.5rem;
    }
    .section-title span.badge {
        background: #e5f3ff; color: #1d4ed8;
        border-radius: 999px; font-size: 0.72rem;
        padding: 0.2rem 0.7rem;
        text-transform: uppercase; letter-spacing: .06em; font-weight: 600;
    }
    .section-caption { font-size: 0.87rem; color: #6b7280; margin-bottom: 0.6rem; }

    [data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e5e7eb; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-badge"><span>FX client book monitor</span></div>
        <div class="hero-title">Client P&L Monitoring Tool</div>
        <div class="hero-subtitle">
            Upload MT5 reports to see account-wise, group-wise and book-wise P&L
            – including A-Book vs B-Book vs Hybrid and A-Book vs LP brokerage.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# HELPERS
# ============================================================

def _read_excel_guess(file, header=2) -> pd.DataFrame:
    try:
        return pd.read_excel(file, header=header)
    except Exception:
        file.seek(0)
        return pd.read_excel(file)

def _lower_cols(df):
    return [str(c).strip().lower() for c in df.columns]

def _find_col_contains(df, keywords, fallback_idx=None):
    """Find first column whose name contains any keyword."""
    cols = _lower_cols(df)
    for k in keywords:
        for i, c in enumerate(cols):
            if k in c:
                return df.columns[i]
    if fallback_idx is not None and fallback_idx < len(df.columns):
        return df.columns[fallback_idx]
    return None

def load_summary_sheet(file, header_row=2) -> pd.DataFrame:
    """
    Summary sheet: uses fixed positions (safe for MT5 exports).
    0 Login, 4 NET DP/WD, 5 Credit, 7 ClosedVolume, 8 Commission, 10 Swap
    """
    raw = _read_excel_guess(file, header=header_row)
    if raw.shape[1] < 11:
        raise ValueError("Summary sheet must contain at least 11 columns (up to column K).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["Credit"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)
    df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    grouped = df.groupby("Login", as_index=False)[["NET_DP_WD","Credit","ClosedVolume","Commission","Swap"]].sum()
    return grouped

def load_equity_sheet(file, header_row=2, login_col=None, equity_col=None, currency_col=None) -> pd.DataFrame:
    df = _read_excel_guess(file, header=header_row)

    # Auto-detect if not provided
    if login_col is None:
        login_col = _find_col_contains(df, ["login", "account"], fallback_idx=0)
    if equity_col is None:
        equity_col = _find_col_contains(df, ["equity"], fallback_idx=None)
        if equity_col is None:
            # some reports use "balance" or "eod equity"
            equity_col = _find_col_contains(df, ["balance"], fallback_idx=9)
    if currency_col is None:
        currency_col = _find_col_contains(df, ["currency", "ccy", "curr"], fallback_idx=None)

    if login_col is None or equity_col is None:
        raise ValueError("Could not detect Login/Equity columns. Please use Column Mapping to select them manually.")

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = df[currency_col].astype(str) if currency_col is not None else "USD"
    return out

def _read_accounts_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)

    lower_cols = {str(c).lower(): c for c in df.columns}
    if "login" in lower_cols and "Login" not in df.columns:
        df = df.rename(columns={lower_cols["login"]: "Login"})
    if "group" in lower_cols and "Group" not in df.columns:
        df = df.rename(columns={lower_cols["group"]: "Group"})

    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login","Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    return out

def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df

def load_switch_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)
    lower = {str(c).lower(): c for c in df.columns}

    def pick(col):
        if col.lower() not in lower:
            raise ValueError(f"Switch file must contain column '{col}'")
        return lower[col.lower()]

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)

    if "hybridratio" in lower:
        hr = pd.to_numeric(df[pick("hybridratio")], errors="coerce")
        hr = hr.apply(lambda x: x/100.0 if pd.notna(x) and x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan
    return out

def _parse_exclude_text(text: str) -> set:
    if not text:
        return set()
    raw = text.replace(",", "\n").replace(";", "\n").replace("\t", "\n")
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    logins = set()
    for p in parts:
        try:
            logins.add(int(float(p)))
        except Exception:
            pass
    return logins

def _read_exclude_file(file) -> set:
    if file is None:
        return set()
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)

    cols = [str(c).strip().lower() for c in df.columns]
    login_col = None
    for opt in ["login", "account", "accountid", "mt5", "mt4"]:
        if opt in cols:
            login_col = df.columns[cols.index(opt)]
            break
    if login_col is None:
        login_col = df.columns[0]

    ser = pd.to_numeric(df[login_col], errors="coerce").dropna()
    return set(ser.astype(int).tolist())

def build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label) -> pd.DataFrame:
    base = closing_df.rename(columns={"Equity": "Closing Equity Raw"}).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity Raw"})

    base = base.merge(open_renamed[["Login","Opening Equity Raw"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # Numeric fill
    for col in ["Closing Equity Raw", "Opening Equity Raw", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    # ✅ Correct rule: ONLY negatives become 0; positives/0 stay same
    report["Opening Equity"] = report["Opening Equity Raw"].clip(lower=0)
    report["Closing Equity"] = report["Closing Equity Raw"].clip(lower=0)

    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    report["NET PNL USD"] = (
        report["Closing Equity"]
        - report["Opening Equity"]
        - report["NET_DP_WD"]
        - report["Credit"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"] > 0,
        (report["NET PNL USD"] / report["Opening Equity"]) * 100.0,
        0.0,
    )

    report["EOD Closing Equity Date"] = eod_label

    final_cols = [
        "Login","Group","OrigType","Type",
        "Closed Lots","NET_DP_WD","Credit","Currency",
        "Opening Equity Raw","Closing Equity Raw",
        "Opening Equity","Closing Equity",
        "NET PNL USD","NET PNL %",
        "Commission","Swap","EOD Closing Equity Date"
    ]
    report = report[final_cols].sort_values("Login").reset_index(drop=True)
    return report

def build_book_summary(account_df: pd.DataFrame, switch_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    switch_map = {}

    if switch_df is not None and not switch_df.empty:
        for _, r in switch_df.iterrows():
            if pd.notna(r.get("Login")):
                switch_map[int(r["Login"])] = r

    for _, r in account_df.iterrows():
        login = int(r["Login"])
        net_pnl = float(r["NET PNL USD"])
        closed_lots = float(r["Closed Lots"])
        final_type = str(r["Type"])

        if login in switch_map:
            sw = switch_map[login]
            from_type = str(sw["FromType"])
            to_type = str(sw["ToType"])
            shift_eq = float(sw["ShiftEquity"])
            hybrid_ratio = sw.get("HybridRatio", np.nan)
            if pd.isna(hybrid_ratio):
                hybrid_ratio = 0.5

            pnl_after = float(r["Closing Equity"]) - shift_eq
            pnl_before = net_pnl - pnl_after

            rows.append({"Type": from_type, "Accounts": 0, "Closed_Lots": 0.0, "NET_PNL_USD": pnl_before})

            if to_type.lower() == "hybrid":
                pnl_a = pnl_after * hybrid_ratio
                pnl_b = pnl_after * (1 - hybrid_ratio)
                rows.append({"Type": "A-Book", "Accounts": 1, "Closed_Lots": closed_lots * hybrid_ratio, "NET_PNL_USD": pnl_a})
                rows.append({"Type": "B-Book", "Accounts": 0, "Closed_Lots": closed_lots * (1 - hybrid_ratio), "NET_PNL_USD": pnl_b})
            else:
                rows.append({"Type": to_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": pnl_after})
        else:
            rows.append({"Type": final_type, "Accounts": 1, "Closed_Lots": closed_lots, "NET_PNL_USD": net_pnl})

    book = (
        pd.DataFrame(rows)
        .groupby("Type", as_index=False)
        .agg(Accounts=("Accounts","sum"), Closed_Lots=("Closed_Lots","sum"), NET_PNL_USD=("NET_PNL_USD","sum"))
    )
    return book

def build_top_gainers_losers(account_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    top_g = account_df.sort_values("NET PNL USD", ascending=False).head(top_n).copy()
    top_l = account_df.sort_values("NET PNL USD", ascending=True).head(top_n).copy()
    top_g["RankType"] = "Top Gainers"
    top_l["RankType"] = "Top Losers"
    return pd.concat([top_g, top_l], ignore_index=True)

# ============================================================
# SIDEBAR SETTINGS
# ============================================================

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    top_n = st.slider("Top gainers/losers count", min_value=5, max_value=50, value=10, step=5)

# ============================================================
# UPLOADS
# ============================================================

st.markdown('<div class="section-title"><span class="badge">1</span><span>Upload MT5 reports</span></div>', unsafe_allow_html=True)
st.markdown('<div class="section-caption">Upload MT5 Summary + Daily reports and map accounts. Use Column Mapping if equity shows 0.</div>', unsafe_allow_html=True)

eod_label = st.text_input("EOD Closing Equity Date (stored in the Excel report)", placeholder="e.g. 2025-12-06 EOD")

c1, c2 = st.columns(2)
c3, _ = st.columns(2)

with c1:
    summary_file = st.file_uploader("Sheet 1 – Summary / Transactions", type=["xlsx", "xls"], key="summary")
with c2:
    closing_file = st.file_uploader("Sheet 2 – Closing Equity (EOD)", type=["xlsx", "xls"], key="closing")
with c3:
    opening_file = st.file_uploader("Sheet 3 – Opening Equity (prev EOD)", type=["xlsx", "xls"], key="opening")

# Row with Exclude next to Hybrid
c5, c6, c7, c8 = st.columns(4)

with c5:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with c6:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with c7:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")
with c8:
    exclude_file = st.file_uploader("Exclude accounts (file)", type=["xlsx", "xls", "csv"], key="exclude_file_front")
    exclude_text = st.text_area("Exclude accounts (paste)", key="exclude_text_front", height=90, placeholder="10001\n10002\n10003")

st.markdown(
    """
    <div class="section-title"><span class="badge">2</span>
    <span>Book switch overrides (optional)</span></div>
    """,
    unsafe_allow_html=True,
)
switch_file = st.file_uploader("Upload book switch file", type=["xlsx", "xls", "csv"], key="switch")

# ============================================================
# COLUMN MAPPING (THE KEY FIX)
# ============================================================

with st.expander("🧩 Column Mapping (IMPORTANT if equity shows 0)", expanded=True):
    st.write("If your report shows Net P&L = 0, it means Equity column detection is wrong. Select the correct columns here.")

    closing_cols = []
    opening_cols = []
    if closing_file is not None:
        tmp = _read_excel_guess(closing_file, header=2)
        closing_cols = list(tmp.columns)
        closing_file.seek(0)
    if opening_file is not None:
        tmp2 = _read_excel_guess(opening_file, header=2)
        opening_cols = list(tmp2.columns)
        opening_file.seek(0)

    colA, colB = st.columns(2)

    with colA:
        st.markdown("**Closing file mapping**")
        closing_login_pick = st.selectbox("Closing: Login column", options=closing_cols, index=0 if closing_cols else 0, disabled=not closing_cols)
        closing_equity_pick = st.selectbox("Closing: Equity column", options=closing_cols, index=min(1, len(closing_cols)-1) if closing_cols else 0, disabled=not closing_cols)
        closing_ccy_pick = st.selectbox("Closing: Currency column (optional)", options=["(none)"] + closing_cols, index=0, disabled=not closing_cols)

    with colB:
        st.markdown("**Opening file mapping**")
        opening_login_pick = st.selectbox("Opening: Login column", options=opening_cols, index=0 if opening_cols else 0, disabled=not opening_cols)
        opening_equity_pick = st.selectbox("Opening: Equity column", options=opening_cols, index=min(1, len(opening_cols)-1) if opening_cols else 0, disabled=not opening_cols)
        opening_ccy_pick = st.selectbox("Opening: Currency column (optional)", options=["(none)"] + opening_cols, index=0, disabled=not opening_cols)

# ============================================================
# PROCESSING
# ============================================================

if st.button("🚀 Generate report"):
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

                closing_df = load_equity_sheet(
                    closing_file,
                    login_col=closing_login_pick if closing_cols else None,
                    equity_col=closing_equity_pick if closing_cols else None,
                    currency_col=None if (not closing_cols or closing_ccy_pick == "(none)") else closing_ccy_pick
                )
                opening_df = load_equity_sheet(
                    opening_file,
                    login_col=opening_login_pick if opening_cols else None,
                    equity_col=opening_equity_pick if opening_cols else None,
                    currency_col=None if (not opening_cols or opening_ccy_pick == "(none)") else opening_ccy_pick
                )

                # Build accounts map
                frames = []
                if a_book_file: frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file: frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_file: frames.append(load_book_accounts(hybrid_file, "Hybrid"))
                accounts_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Login"], keep="first")

                # Exclude
                exclude_set = set()
                exclude_set |= _read_exclude_file(exclude_file)
                exclude_set |= _parse_exclude_text(exclude_text)
                before_cnt = accounts_df["Login"].nunique()
                if exclude_set:
                    accounts_df = accounts_df[~accounts_df["Login"].astype("Int64").isin(list(exclude_set))].copy()
                after_cnt = accounts_df["Login"].nunique()
                excluded_cnt = max(0, before_cnt - after_cnt)

                switch_df = load_switch_file(switch_file) if switch_file is not None else pd.DataFrame()

                account_df = build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label)
                book_df = build_book_summary(account_df, switch_df)
                top_df = build_top_gainers_losers(account_df, top_n=top_n)

            # ===== Data health checks =====
            if account_df["Opening Equity Raw"].abs().sum() == 0 and account_df["Closing Equity Raw"].abs().sum() == 0:
                st.error("⚠️ Equity looks like ALL ZERO. Your Equity column selection is wrong. Go to Column Mapping and select the correct Equity column.")
                st.stop()

            # ====================================================
            # KPIs
            # ====================================================
            st.markdown('<div class="section-title"><span class="badge">3</span><span>High-level snapshot</span></div>', unsafe_allow_html=True)

            k1, k2, k3, k4 = st.columns(4)
            total_clients = account_df["Login"].nunique()
            net_pnl = float(account_df["NET PNL USD"].sum())
            total_profit = float(account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum())
            total_loss = float(account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum())

            with k1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Accounts (after exclude)</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(total_clients):,}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            with k2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Excluded accounts</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{int(excluded_cnt):,}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            with k3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Net client P&L (USD)</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">{net_pnl:,.2f}</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
            with k4:
                profit_abs = abs(total_profit)
                loss_abs = abs(total_loss)
                denom = profit_abs + loss_abs
                profit_pct = (profit_abs / denom * 100.0) if denom > 0 else 0.0
                loss_pct = (loss_abs / denom * 100.0) if denom > 0 else 0.0
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Profit vs loss mix</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="metric-value">P {profit_pct:.1f}% / L {loss_pct:.1f}%</div>', unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            # ====================================================
            # TOP GAINERS / LOSERS
            # ====================================================
            st.markdown('<div class="section-title"><span class="badge">4</span><span>Top gainer & top loser accounts</span></div>', unsafe_allow_html=True)
            t1, t2 = st.columns(2)
            with t1:
                st.markdown(f"**Top {top_n} gainers**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=False).head(top_n), use_container_width=True, height=420)
            with t2:
                st.markdown(f"**Top {top_n} losers**")
                st.dataframe(account_df.sort_values("NET PNL USD", ascending=True).head(top_n), use_container_width=True, height=420)

            # ====================================================
            # ALL ACCOUNTS
            # ====================================================
            st.markdown('<div class="section-title"><span class="badge">5</span><span>All accounts net P&L</span></div>', unsafe_allow_html=True)
            st.info("Rule: Only if Opening/Closing Equity is NEGATIVE → treated as 0. Positive and 0 equity stays unchanged.")
            st.dataframe(account_df, use_container_width=True, height=520)

            # ====================================================
            # BOOK SUMMARY
            # ====================================================
            st.markdown('<div class="section-title"><span class="badge">6</span><span>Book-wise overall P&L</span></div>', unsafe_allow_html=True)
            st.dataframe(book_df, use_container_width=True, height=260)

            # ====================================================
            # EXCEL DOWNLOAD (3 sheets only)
            # ====================================================
            st.markdown('<div class="section-title"><span class="badge">7</span><span>Download Excel report</span></div>', unsafe_allow_html=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                account_df.to_excel(writer, index=False, sheet_name="All_Accounts_NetPNL")
                top_df.to_excel(writer, index=False, sheet_name="Top_Gainers_Losers")
                book_df.to_excel(writer, index=False, sheet_name="Books_Overall_PNL")

            output.seek(0)
            st.download_button(
                "⬇️ Download Excel report",
                data=output,
                file_name=f"Client_PnL_Report_{eod_label.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"❌ Error while generating report: {e}")
