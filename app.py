import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ============================================================
# PAGE CONFIG & GLOBAL STYLING
# ============================================================

st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background: radial-gradient(circle at top left, #ffffff 0, #f5f7fb 55%, #e9edf5 100%); color: #111827;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; }
    .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1300px; }

    .hero-card { background: linear-gradient(135deg, #111827, #1f2937); color: #f9fafb; border-radius: 22px;
                padding: 1.8rem 2.2rem 1.6rem 2.2rem; box-shadow: 0 18px 50px rgba(15, 23, 42, 0.45);
                position: relative; overflow: hidden; }
    .hero-badge { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.15rem 0.7rem; border-radius: 999px;
                background: rgba(55, 65, 81, 0.8); font-size: 0.75rem; font-weight: 500; letter-spacing: .04em;
                text-transform: uppercase; }
    .hero-title { font-size: 2.0rem; font-weight: 700; margin-top: 0.7rem; margin-bottom: 0.4rem; }
    .hero-subtitle { font-size: 0.97rem; color: #d1d5db; max-width: 580px; }

    .metric-card { background: #ffffff; border-radius: 16px; padding: 0.9rem 1.1rem; border: 1px solid #e5e7eb;
                box-shadow: 0 12px 30px rgba(148, 163, 184, 0.24); }
    .metric-label { font-size: 0.78rem; color: #6b7280; text-transform: uppercase; letter-spacing: .06em; }
    .metric-value { font-size: 1.25rem; font-weight: 600; margin-top: 0.15rem; }

    .section-title { font-size: 1.1rem; font-weight: 650; margin-top: 1.8rem; margin-bottom: 0.4rem;
                    display: flex; align-items: center; gap: 0.5rem; }
    .section-title span.badge { background: #e5f3ff; color: #1d4ed8; border-radius: 999px; font-size: 0.72rem;
                                padding: 0.2rem 0.7rem; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
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
            – including A-Book vs B-Book vs Hybrid.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# ROBUST READ HELPERS (NO MAPPING UI)
# ============================================================

def _read_excel_try_headers(file, header_candidates=(0, 1, 2, 3, 4, None)):
    """Try multiple header rows. Returns list of (header_used, df)."""
    dfs = []
    for h in header_candidates:
        try:
            file.seek(0)
            df = pd.read_excel(file, header=h)
            dfs.append((h, df))
        except Exception:
            continue
    if not dfs:
        raise ValueError("Unable to read Excel file.")
    return dfs

def _normalize_cols(df: pd.DataFrame):
    cols = []
    for c in df.columns:
        c = str(c).strip()
        c = c.replace("\n", " ").replace("\r", " ")
        cols.append(c)
    df = df.copy()
    df.columns = cols
    return df

def _best_login_col(df: pd.DataFrame):
    """Find column that looks like Login (most numeric ints of length 4-10)."""
    best = None
    best_score = -1
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        ok = s.dropna()
        if ok.empty:
            continue
        # score: count of integer-like values
        score = int(((ok % 1) == 0).sum())
        # boost if column name contains login
        if "login" in str(c).lower():
            score += 100000
        if score > best_score:
            best_score = score
            best = c
    return best

def _find_col_by_keywords(df: pd.DataFrame, keywords):
    cols_lower = [str(c).strip().lower() for c in df.columns]
    for kw in keywords:
        for i, c in enumerate(cols_lower):
            if kw in c:
                return df.columns[i]
    return None

def _choose_best_df_for_equity(file):
    """Pick best (header, df) where login+equity can be detected and equity has non-zero coverage."""
    candidates = _read_excel_try_headers(file)
    best = None
    best_score = -1

    for h, df in candidates:
        df = _normalize_cols(df)
        if df.empty or len(df.columns) < 2:
            continue

        login_col = _find_col_by_keywords(df, ["login"]) or _best_login_col(df)
        eq_col = _find_col_by_keywords(df, ["equity"])
        if eq_col is None:
            # fallback: try columns that have many numeric values and big magnitudes
            num_scores = []
            for c in df.columns:
                s = pd.to_numeric(df[c], errors="coerce")
                ok = s.dropna()
                if ok.empty:
                    continue
                # equity often has larger absolute values than small counters
                score = int((ok.abs() > 1).sum())
                num_scores.append((score, c))
            num_scores.sort(reverse=True)
            eq_col = num_scores[0][1] if num_scores else None

        if login_col is None or eq_col is None:
            continue

        logins = pd.to_numeric(df[login_col], errors="coerce").dropna()
        equity = pd.to_numeric(df[eq_col], errors="coerce").dropna()

        if logins.empty or equity.empty:
            continue

        # scoring: many logins + many nonzero equities
        score = len(logins) + int((equity != 0).sum()) * 2
        if score > best_score:
            best_score = score
            best = (h, df, login_col, eq_col)

    if best is None:
        raise ValueError("Could not auto-detect Login/Equity columns. Your MT5 export format is unusual.")
    return best  # header, df, login_col, equity_col

def _choose_best_df_for_summary(file):
    """
    Auto-detect summary columns:
    Login, NET DP/WD (or Net Deposit/Withdrawal), Credit, Closed Volume, Commission, Swap
    """
    candidates = _read_excel_try_headers(file)
    best = None
    best_score = -1

    for h, df in candidates:
        df = _normalize_cols(df)
        if df.empty:
            continue

        login_col = _find_col_by_keywords(df, ["login"]) or _best_login_col(df)
        if login_col is None:
            continue

        # net dp/wd keywords vary
        net_col = (
            _find_col_by_keywords(df, ["net dp", "net dp/wd", "net deposit", "net d", "net deposit/withdraw", "net_deposit"])
        )
        # some MT5 uses "Deposit/Withdrawal" or "D/W"
        if net_col is None:
            net_col = _find_col_by_keywords(df, ["deposit", "withdraw", "dp/wd", "d/w"])

        credit_col = _find_col_by_keywords(df, ["credit"])
        vol_col = _find_col_by_keywords(df, ["closed volume", "volume", "vol"])
        comm_col = _find_col_by_keywords(df, ["commission", "comm"])
        swap_col = _find_col_by_keywords(df, ["swap"])

        # If still missing NET column, fallback: old fixed index (E = col 4) ONLY if exists
        if net_col is None and len(df.columns) > 4:
            net_col = df.columns[4]

        # scoring: must have login+net at least
        if net_col is None:
            continue

        logins = pd.to_numeric(df[login_col], errors="coerce").dropna()
        netv = pd.to_numeric(df[net_col], errors="coerce").dropna()
        if logins.empty:
            continue

        score = len(logins) + int((netv != 0).sum()) * 2
        # boost if we found more optional cols
        score += 1000 if credit_col is not None else 0
        score += 1000 if vol_col is not None else 0
        score += 1000 if comm_col is not None else 0
        score += 1000 if swap_col is not None else 0

        if score > best_score:
            best_score = score
            best = (h, df, login_col, net_col, credit_col, vol_col, comm_col, swap_col)

    if best is None:
        raise ValueError("Could not auto-detect Summary columns (Login/NET DP/WD).")
    return best

# ============================================================
# LOADERS
# ============================================================

def load_equity_sheet(file) -> pd.DataFrame:
    h, df, login_col, equity_col = _choose_best_df_for_equity(file)
    df = df.copy()
    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)

    # Currency optional
    currency_col = _find_col_by_keywords(df, ["currency", "ccy", "curr"])
    out["Currency"] = df[currency_col].astype(str) if currency_col is not None else "USD"

    out = out[out["Login"].notna()].copy()
    return out

def load_summary_sheet(file) -> pd.DataFrame:
    h, df, login_col, net_col, credit_col, vol_col, comm_col, swap_col = _choose_best_df_for_summary(file)
    df = df.copy()

    tmp = pd.DataFrame()
    tmp["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    tmp["NET_DP_WD"] = pd.to_numeric(df[net_col], errors="coerce").fillna(0.0)
    tmp["Credit"] = pd.to_numeric(df[credit_col], errors="coerce").fillna(0.0) if credit_col is not None else 0.0
    tmp["ClosedVolume"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0.0) if vol_col is not None else 0.0
    tmp["Commission"] = pd.to_numeric(df[comm_col], errors="coerce").fillna(0.0) if comm_col is not None else 0.0
    tmp["Swap"] = pd.to_numeric(df[swap_col], errors="coerce").fillna(0.0) if swap_col is not None else 0.0

    tmp = tmp[tmp["Login"].notna()].copy()
    grouped = tmp.groupby("Login", as_index=False)[["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]].sum()
    return grouped

def _read_accounts_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)
    df = _normalize_cols(df)

    lower_cols = {str(c).lower(): c for c in df.columns}
    if "login" in lower_cols:
        df = df.rename(columns={lower_cols["login"]: "Login"})
    if "group" in lower_cols:
        df = df.rename(columns={lower_cols["group"]: "Group"})
    if "Login" not in df.columns:
        df = df.rename(columns={df.columns[0]: "Login"})
    if "Group" not in df.columns:
        df["Group"] = ""

    out = df[["Login", "Group"]].copy()
    out["Login"] = pd.to_numeric(out["Login"], errors="coerce").astype("Int64")
    out = out[out["Login"].notna()].copy()
    return out

def load_book_accounts(file, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df

def load_switch_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)
    df = _normalize_cols(df)

    lower = {str(c).lower(): c for c in df.columns}
    def pick(colname):
        key = colname.lower()
        if key not in lower:
            raise ValueError(f"Switch file must contain column '{colname}'")
        return lower[key]

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[pick("login")], errors="coerce").astype("Int64")
    out["FromType"] = df[pick("fromtype")].astype(str)
    out["ToType"] = df[pick("totype")].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[pick("shiftequity")], errors="coerce").fillna(0.0)

    hr_col = None
    for k in lower.keys():
        if k.startswith("hybridratio"):
            hr_col = lower[k]
            break
    if hr_col is not None:
        hr = pd.to_numeric(df[hr_col], errors="coerce")
        hr = hr.apply(lambda x: x / 100.0 if pd.notna(x) and x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan

    out = out[out["Login"].notna()].copy()
    return out

# ============================================================
# EXCLUDE HELPERS
# ============================================================

def _parse_exclude_text(text: str) -> set[int]:
    if not text:
        return set()
    raw = text.replace(",", "\n").replace(";", "\n").replace("\t", "\n")
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    out = set()
    for p in parts:
        try:
            out.add(int(float(p)))
        except Exception:
            pass
    return out

def _read_exclude_file(file) -> set[int]:
    if file is None:
        return set()
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)
    df = _normalize_cols(df)

    col = None
    for c in df.columns:
        if str(c).strip().lower() == "login":
            col = c
            break
    if col is None:
        col = df.columns[0]

    ser = pd.to_numeric(df[col], errors="coerce").dropna()
    return set(ser.astype(int).tolist())

# ============================================================
# CALCULATION
# ============================================================

def build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label) -> pd.DataFrame:
    base = closing_df.rename(columns={"Equity": "Closing Equity"}).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    for col in ["Closing Equity", "Opening Equity", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # ✅ Your rule: only negative equity becomes 0 (positive/0 unchanged)
    report["Opening Equity"] = np.where(report["Opening Equity"] < 0, 0.0, report["Opening Equity"])
    report["Closing Equity"] = np.where(report["Closing Equity"] < 0, 0.0, report["Closing Equity"])

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
        "Login", "Group", "OrigType", "Type",
        "Closed Lots", "NET_DP_WD", "Credit",
        "Currency", "Opening Equity", "Closing Equity",
        "NET PNL USD", "NET PNL %",
        "Commission", "Swap",
        "EOD Closing Equity Date",
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
        .agg(
            Accounts=("Accounts", "sum"),
            Closed_Lots=("Closed_Lots", "sum"),
            NET_PNL_USD=("NET_PNL_USD", "sum"),
        )
    )
    return book

def _health_check(account_df: pd.DataFrame):
    """Warn if report looks 'all zeros' due to wrong parsing."""
    if account_df.empty:
        st.error("No accounts produced.")
        return

    n = len(account_df)
    zero_pnl = int((account_df["NET PNL USD"] == 0).sum())
    zero_net = int((account_df["NET_DP_WD"] == 0).sum())
    zero_open = int((account_df["Opening Equity"] == 0).sum())
    zero_close = int((account_df["Closing Equity"] == 0).sum())

    # If most rows are zero, likely parsing mismatch
    if (zero_pnl / n) > 0.85 and (zero_open / n) > 0.85 and (zero_close / n) > 0.85:
        st.warning(
            "⚠️ Data Health Warning: Most PNL/Open/Close are 0. "
            "This usually means MT5 export columns are different than expected or file is not the correct report type. "
            "This version auto-detects, but if your report is a different MT5 template, please export the standard Summary/Daily reports."
        )

# ============================================================
# UI – UPLOADS
# ============================================================

st.markdown(
    '<div class="section-title"><span class="badge">1</span><span>Upload MT5 reports</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">Only your requested changes + silent auto-detection (no mapping screen).</div>',
    unsafe_allow_html=True,
)

eod_label = st.text_input("EOD Closing Equity Date (stored in the Excel report)", placeholder="e.g. 2025-12-06 EOD")

c1, c2 = st.columns(2)
c3, _ = st.columns(2)
c5, c6, c7, c8 = st.columns(4)

with c1:
    summary_file = st.file_uploader("Sheet 1 – Summary / Transactions", type=["xlsx", "xls"], key="summary")
with c2:
    closing_file = st.file_uploader("Sheet 2 – Closing Equity (EOD for report period)", type=["xlsx", "xls"], key="closing")
with c3:
    opening_file = st.file_uploader("Sheet 3 – Opening Equity (previous EOD)", type=["xlsx", "xls"], key="opening")

with c5:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with c6:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with c7:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")

# ✅ Exclude accounts next to Hybrid
with c8:
    exclude_file = st.file_uploader("Exclude accounts (file)", type=["xlsx", "xls", "csv"], key="exclude_file")
    exclude_text = st.text_area("Exclude accounts (paste)", height=90, placeholder="10001\n10002\n10003", key="exclude_text")

st.markdown(
    '<div class="section-title"><span class="badge">2</span><span>Book switch overrides (optional)</span></div>',
    unsafe_allow_html=True,
)
switch_file = st.file_uploader("Upload book switch file", type=["xlsx", "xls", "csv"], key="switch")

st.markdown("---")
top_n = st.sidebar.slider("Top gainers/losers count", 5, 50, 10, 5)

# ============================================================
# GENERATE
# ============================================================

if st.button("🚀 Generate report"):
    if not (summary_file and closing_file and opening_file):
        st.error("Please upload Summary + Closing Equity + Opening Equity files.")
        st.stop()
    if not (a_book_file or b_book_file or hybrid_file):
        st.error("Please upload at least one of: A-Book, B-Book, Hybrid accounts file.")
        st.stop()
    if not eod_label:
        st.error("Please enter the EOD Closing Equity Date text.")
        st.stop()

    try:
        with st.spinner("Processing files & calculating P&L…"):
            summary_df = load_summary_sheet(summary_file)
            closing_df = load_equity_sheet(closing_file)
            opening_df = load_equity_sheet(opening_file)

            frames = []
            if a_book_file:
                frames.append(load_book_accounts(a_book_file, "A-Book"))
            if b_book_file:
                frames.append(load_book_accounts(b_book_file, "B-Book"))
            if hybrid_file:
                frames.append(load_book_accounts(hybrid_file, "Hybrid"))

            accounts_df = pd.concat(frames, ignore_index=True)
            accounts_df = accounts_df.drop_duplicates(subset=["Login"], keep="first")

            # Exclude
            exclude_set = set()
            exclude_set |= _read_exclude_file(exclude_file)
            exclude_set |= _parse_exclude_text(exclude_text)

            before_cnt = int(accounts_df["Login"].nunique())
            if exclude_set:
                accounts_df = accounts_df[~accounts_df["Login"].astype("Int64").isin(list(exclude_set))].copy()
            after_cnt = int(accounts_df["Login"].nunique())
            excluded_cnt = max(0, before_cnt - after_cnt)

            # Switch file
            switch_df = load_switch_file(switch_file) if switch_file is not None else pd.DataFrame()

            account_df = build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label)
            book_df = build_book_summary(account_df, switch_df)

        # Health check
        _health_check(account_df)

        # KPIs
        st.markdown(
            '<div class="section-title"><span class="badge">3</span><span>High-level snapshot</span></div>',
            unsafe_allow_html=True,
        )

        k1, k2, k3, k4 = st.columns(4)
        total_clients = int(account_df["Login"].nunique())
        net_pnl = float(account_df["NET PNL USD"].sum())
        total_profit = float(account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum())
        total_loss = float(account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum())

        with k1:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Accounts (after exclude)</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">{total_clients:,}</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with k2:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Excluded accounts</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-value">{excluded_cnt:,}</div>', unsafe_allow_html=True)
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

        # Top gainers/losers
        st.markdown(
            '<div class="section-title"><span class="badge">4</span><span>Top gainer & top loser accounts</span></div>',
            unsafe_allow_html=True,
        )
        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown(f"**Top {top_n} gainers**")
            st.dataframe(account_df.sort_values("NET PNL USD", ascending=False).head(top_n), use_container_width=True)
        with tc2:
            st.markdown(f"**Top {top_n} losers**")
            st.dataframe(account_df.sort_values("NET PNL USD", ascending=True).head(top_n), use_container_width=True)

        # All accounts
        st.markdown(
            '<div class="section-title"><span class="badge">5</span><span>All accounts net P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.info("Rule: ONLY if Opening/Closing Equity is NEGATIVE → treated as 0. Positive & 0 stays unchanged.")
        st.dataframe(account_df, use_container_width=True)

        # Books
        st.markdown(
            '<div class="section-title"><span class="badge">6</span><span>Book wise overall P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(book_df, use_container_width=True)

        # Excel (only your 3 sheets)
        st.markdown(
            '<div class="section-title"><span class="badge">7</span><span>Download Excel report</span></div>',
            unsafe_allow_html=True,
        )

        top_g = account_df.sort_values("NET PNL USD", ascending=False).head(top_n).copy()
        top_l = account_df.sort_values("NET PNL USD", ascending=True).head(top_n).copy()
        top_g["RankType"] = "Top Gainers"
        top_l["RankType"] = "Top Losers"
        top_df = pd.concat([top_g, top_l], ignore_index=True)

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
