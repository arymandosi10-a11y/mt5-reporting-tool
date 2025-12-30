import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ============================================================
# PAGE CONFIG & GLOBAL STYLING (same as your style)
# ============================================================

st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
        position: relative;
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
    .hero-subtitle { font-size: 0.97rem; color: #d1d5db; max-width: 580px; }

    .metric-card {
        background: #ffffff; border-radius: 16px;
        padding: 0.9rem 1.1rem; border: 1px solid #e5e7eb;
        box-shadow: 0 12px 30px rgba(148, 163, 184, 0.24);
    }
    .metric-label { font-size: 0.78rem; color: #6b7280; text-transform: uppercase; letter-spacing: .06em; }
    .metric-value { font-size: 1.25rem; font-weight: 600; margin-top: 0.15rem; }

    .section-title {
        font-size: 1.1rem; font-weight: 650;
        margin-top: 1.8rem; margin-bottom: 0.4rem;
        display: flex; align-items: center; gap: 0.5rem;
    }
    .section-title span.badge {
        background: #e5f3ff; color: #1d4ed8;
        border-radius: 999px; font-size: 0.72rem;
        padding: 0.2rem 0.7rem; text-transform: uppercase;
        letter-spacing: .06em; font-weight: 600;
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
            – including A-Book vs B-Book vs Hybrid.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# HELPERS (robust auto-detect + fallback to MT5 fixed columns)
# ============================================================

def _norm(c: str) -> str:
    return str(c).strip().lower().replace("\n", " ").replace("_", " ")

def _find_col(df: pd.DataFrame, keywords: list[str], required=True):
    cols = list(df.columns)
    norm_cols = [_norm(c) for c in cols]
    for kw in keywords:
        kw = kw.lower()
        for i, c in enumerate(norm_cols):
            if kw in c:
                return cols[i]
    if required:
        raise ValueError(f"Missing required column. Tried: {keywords}")
    return None

def _read_excel_try_headers(file, header_candidates=(2, 1, 0, 3, 4)):
    last_err = None
    for h in header_candidates:
        try:
            file.seek(0)
            df = pd.read_excel(file, header=h)
            # if df has at least some columns, accept
            if df is not None and df.shape[1] >= 2:
                return df
        except Exception as e:
            last_err = e
    raise ValueError(f"Unable to read Excel properly. Last error: {last_err}")

def load_equity_sheet(file) -> pd.DataFrame:
    df = _read_excel_try_headers(file)

    # Try detect by header name
    login_col = _find_col(df, ["login", "account"], required=False)
    equity_col = _find_col(df, ["equity"], required=False)
    ccy_col = _find_col(df, ["currency", "ccy", "curr"], required=False)

    # Fallback to MT5 common positions (like your old logic)
    if login_col is None:
        login_col = df.columns[0]
    if equity_col is None:
        # many MT5 have equity around column J (index 9)
        equity_col = df.columns[9] if df.shape[1] > 9 else df.columns[1]

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Equity"] = pd.to_numeric(df[equity_col], errors="coerce").fillna(0.0)
    out["Currency"] = df[ccy_col].astype(str) if ccy_col else "USD"
    out = out[out["Login"].notna()].copy()
    return out

def load_summary_sheet(file) -> pd.DataFrame:
    raw = _read_excel_try_headers(file)

    # Try detect by header name
    login_col = _find_col(raw, ["login", "account"], required=False)

    netdp_col = _find_col(raw, ["net dp", "net deposit", "deposit/withdraw", "dp/wd", "net dp/wd", "net dp wd"], required=False)
    credit_col = _find_col(raw, ["credit"], required=False)
    vol_col = _find_col(raw, ["closed volume", "volume"], required=False)
    comm_col = _find_col(raw, ["commission"], required=False)
    swap_col = _find_col(raw, ["swap"], required=False)

    # If detection fails, fallback EXACTLY like your original column positions
    # 0: Login, 4: NET DP/WD, 5: Credit, 7: Closed volume, 8: Commission, 10: Swap
    if login_col is None or netdp_col is None:
        if raw.shape[1] < 11:
            raise ValueError("Summary sheet must contain enough columns for fallback (need up to column K).")
        login_col = raw.columns[0]
        netdp_col = raw.columns[4]
        credit_col = raw.columns[5]
        vol_col = raw.columns[7]
        comm_col = raw.columns[8]
        swap_col = raw.columns[10]

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw[login_col], errors="coerce").astype("Int64")
    df["NET_DP_WD"] = pd.to_numeric(raw[netdp_col], errors="coerce").fillna(0.0)
    df["Credit"] = pd.to_numeric(raw[credit_col], errors="coerce").fillna(0.0) if credit_col is not None else 0.0
    df["ClosedVolume"] = pd.to_numeric(raw[vol_col], errors="coerce").fillna(0.0) if vol_col is not None else 0.0
    df["Commission"] = pd.to_numeric(raw[comm_col], errors="coerce").fillna(0.0) if comm_col is not None else 0.0
    df["Swap"] = pd.to_numeric(raw[swap_col], errors="coerce").fillna(0.0) if swap_col is not None else 0.0

    df = df[df["Login"].notna()].copy()

    grouped = df.groupby("Login", as_index=False)[
        ["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]
    ].sum()
    return grouped

def _read_accounts_file(file) -> pd.DataFrame:
    name = file.name.lower()
    df = pd.read_csv(file) if name.endswith(".csv") else pd.read_excel(file)

    login_col = _find_col(df, ["login", "account"], required=False) or df.columns[0]
    group_col = _find_col(df, ["group"], required=False)

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["Group"] = df[group_col].astype(str) if group_col else ""
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

    login_col = _find_col(df, ["login", "account"])
    from_col = _find_col(df, ["fromtype", "from type", "from"])
    to_col = _find_col(df, ["totype", "to type", "to"])
    shift_col = _find_col(df, ["shiftequity", "shift equity", "shift"])

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(df[login_col], errors="coerce").astype("Int64")
    out["FromType"] = df[from_col].astype(str)
    out["ToType"] = df[to_col].astype(str)
    out["ShiftEquity"] = pd.to_numeric(df[shift_col], errors="coerce").fillna(0.0)

    hr_col = _find_col(df, ["hybridratio", "hybrid ratio"], required=False)
    if hr_col is not None:
        hr = pd.to_numeric(df[hr_col], errors="coerce")
        hr = hr.apply(lambda x: x / 100.0 if pd.notna(x) and x > 1 else x)
        out["HybridRatio"] = hr.fillna(np.nan)
    else:
        out["HybridRatio"] = np.nan

    return out

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
    login_col = _find_col(df, ["login", "account"], required=False) or df.columns[0]
    ser = pd.to_numeric(df[login_col], errors="coerce").dropna()
    return set(ser.astype(int).tolist())

def build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label) -> pd.DataFrame:
    base = closing_df.rename(columns={"Equity": "Closing Equity"}).copy()
    open_renamed = opening_df.rename(columns={"Equity": "Opening Equity"})
    base = base.merge(open_renamed[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    # fill numeric
    for col in ["Closing Equity", "Opening Equity", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    report["Closed Lots"] = report["ClosedVolume"] / 2.0

    # ✅ Your required rule: ONLY if opening/closing is NEGATIVE -> treat as 0
    report["Opening Equity"] = np.where(report["Opening Equity"] < 0, 0.0, report["Opening Equity"])
    report["Closing Equity"] = np.where(report["Closing Equity"] < 0, 0.0, report["Closing Equity"])

    report["NET PNL USD"] = (
        report["Closing Equity"] - report["Opening Equity"] - report["NET_DP_WD"] - report["Credit"]
    )

    report["NET PNL %"] = np.where(
        report["Opening Equity"] > 0,
        (report["NET PNL USD"] / report["Opening Equity"]) * 100.0,
        0.0,
    )

    report["EOD Closing Equity Date"] = eod_label

    final_cols = [
        "Login", "Group", "OrigType", "Type",
        "Closed Lots", "NET_DP_WD", "Credit", "Currency",
        "Opening Equity", "Closing Equity",
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


# ============================================================
# MAIN – FILE UPLOADS
# ============================================================

st.markdown(
    '<div class="section-title"><span class="badge">1</span><span>Upload MT5 reports</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="section-caption">Only your requested features: Exclude + Top gainers/losers + Negative equity fix.</div>',
    unsafe_allow_html=True,
)

eod_label = st.text_input("EOD Closing Equity Date (stored in the Excel report)", placeholder="e.g. 2025-12-06 EOD")

c1, c2 = st.columns(2)
c3, c4 = st.columns(2)
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

# ✅ Exclude option next to Hybrid (as you requested)
with c8:
    exclude_file = st.file_uploader("Exclude accounts (file)", type=["xlsx", "xls", "csv"], key="exclude_file")
    exclude_text = st.text_area("Exclude accounts (paste)", height=90, placeholder="10001\n10002\n10003", key="exclude_text")

st.markdown(
    '<div class="section-title"><span class="badge">2</span><span>Book switch overrides (optional)</span></div>',
    unsafe_allow_html=True,
)
switch_file = st.file_uploader("Upload book switch file", type=["xlsx", "xls", "csv"], key="switch")

st.markdown("---")

# ============================================================
# PROCESSING
# ============================================================

top_n = st.sidebar.slider("Top gainers/losers count", 5, 50, 10, 5)

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

            accounts_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Login"], keep="first")

            # ✅ Exclude accounts (file + paste)
            exclude_set = set()
            exclude_set |= _read_exclude_file(exclude_file)
            exclude_set |= _parse_exclude_text(exclude_text)

            before_cnt = int(accounts_df["Login"].nunique())
            if exclude_set:
                accounts_df = accounts_df[~accounts_df["Login"].astype("Int64").isin(list(exclude_set))].copy()
            after_cnt = int(accounts_df["Login"].nunique())
            excluded_cnt = max(0, before_cnt - after_cnt)

            switch_df = load_switch_file(switch_file) if switch_file is not None else pd.DataFrame()

            account_df = build_account_report(summary_df, closing_df, opening_df, accounts_df, eod_label)
            book_df = build_book_summary(account_df, switch_df)

        # ====================================================
        # KPIs
        # ====================================================
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

        # ====================================================
        # ✅ Top gainer & top loser accounts (your request)
        # ====================================================
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

        # ====================================================
        # All accounts
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">5</span><span>All accounts net P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.info("Rule applied: ONLY if Opening/Closing Equity is NEGATIVE → treated as 0. Positive & 0 equity stays unchanged.")
        st.dataframe(account_df, use_container_width=True)

        # ====================================================
        # Book summary
        # ====================================================
        st.markdown(
            '<div class="section-title"><span class="badge">6</span><span>Book wise overall P&L</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(book_df, use_container_width=True)

        # ====================================================
        # Download Excel (ONLY 3 sheets as you asked earlier)
        # ====================================================
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
