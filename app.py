import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# =========================================================
# PAGE CONFIG & UNIQUE UI (LIGHT / PREMIUM)
# =========================================================
st.set_page_config(
    page_title="Client P&L Studio",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
body, .main{
  background:
    radial-gradient(circle at 10% 0%, rgba(99,102,241,0.08) 0, rgba(99,102,241,0) 40%),
    radial-gradient(circle at 90% 10%, rgba(16,185,129,0.08) 0, rgba(16,185,129,0) 42%),
    linear-gradient(180deg, #ffffff 0%, #f5f7fb 60%, #eef2f8 100%);
  color:#0f172a;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "SF Pro Text", Arial, sans-serif;
}
.block-container{max-width:1500px; padding-top:1.2rem; padding-bottom:3rem;}
h1,h2,h3,h4{color:#0f172a;}

.hero{
  border-radius:26px;
  padding:1.35rem 1.6rem;
  background: linear-gradient(135deg, #0b1220 0%, #111827 55%, #0b1220 100%);
  color:#f8fafc;
  border: 1px solid rgba(255,255,255,0.10);
  box-shadow: 0 20px 60px rgba(15,23,42,0.25);
  position:relative;
  overflow:hidden;
}
.hero:before{
  content:"";
  position:absolute;
  inset:-120px -120px auto auto;
  width:240px; height:240px;
  background: radial-gradient(circle, rgba(99,102,241,.35), rgba(99,102,241,0));
}
.hero:after{
  content:"";
  position:absolute;
  inset:auto auto -140px -140px;
  width:300px; height:300px;
  background: radial-gradient(circle, rgba(16,185,129,.25), rgba(16,185,129,0));
}
.hero-badge{
  display:inline-flex;
  align-items:center;
  gap:.55rem;
  padding:.25rem .8rem;
  border-radius:999px;
  font-size:.82rem;
  color: rgba(248,250,252,.78);
  border:1px solid rgba(255,255,255,.22);
  background: rgba(255,255,255,.06);
}
.hero-title{margin:.7rem 0 .2rem 0; font-size:2rem; font-weight:800;}
.hero-sub{margin:0; color:rgba(248,250,252,.75); max-width:920px; line-height:1.6;}

.section{
  margin-top:1.2rem;
  padding:1rem 1rem;
  background: rgba(255,255,255,0.85);
  border:1px solid rgba(15,23,42,0.08);
  border-radius:20px;
  box-shadow: 0 10px 30px rgba(2,6,23,0.05);
}
.section-title{
  display:flex; align-items:center; justify-content:space-between;
  gap:1rem;
}
.section-title h2{margin:0; font-size:1.2rem;}
.pill{
  display:inline-flex; align-items:center; gap:.5rem;
  padding:.25rem .75rem;
  border-radius:999px;
  background: rgba(99,102,241,0.08);
  border:1px solid rgba(99,102,241,0.20);
  color:#3730a3;
  font-size:.8rem;
}
.metric{
  background:#ffffff;
  border:1px solid rgba(15,23,42,0.08);
  border-radius:18px;
  padding:1rem 1rem;
  box-shadow: 0 12px 32px rgba(2,6,23,0.06);
}
.metric .k{font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:#64748b;}
.metric .v{font-size:1.4rem; font-weight:800; color:#0f172a; margin-top:.2rem;}
.metric .s{font-size:.78rem; color:#64748b; margin-top:.2rem;}
.small-note{color:#64748b; font-size:.86rem;}

[data-testid="stSidebar"]{
  background: radial-gradient(circle at 0 0, #0b1220 0, #0b1220 55%, #0b1220 100%);
  border-right: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] *{color:#f8fafc !important;}

[data-testid="stDataFrame"]{
  border-radius:14px;
  overflow:hidden;
  border:1px solid rgba(15,23,42,0.08);
  box-shadow: 0 10px 30px rgba(2,6,23,0.05);
}

.stTextInput > div > div > input,
.stNumberInput input,
.stDateInput input{ border-radius:12px !important; }
.stButton>button{ border-radius:14px !important; font-weight:700; }
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
    try:
        return pd.read_excel(file, header=2)  # MT5 exports often have 2 header lines
    except Exception:
        return pd.read_excel(file)

def load_summary_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 1 – Summary/Transactions
    Required (0-based):
      A(0)=Login, E(4)=NET_DP_WD, F(5)=Credit, H(7)=ClosedVolume (ClosedLots = /2)
    Optional:
      I(8)=Commission, K(10)=Swap
    """
    raw = _read_excel_or_csv(file)
    if raw.shape[1] < 8:
        raise ValueError("Sheet-1 must have at least columns up to H (Volume/Lots).")

    df = pd.DataFrame()
    df["Login"] = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")
    df["NET_DP_WD"] = pd.to_numeric(raw.iloc[:, 4], errors="coerce").fillna(0.0)
    df["Credit"] = pd.to_numeric(raw.iloc[:, 5], errors="coerce").fillna(0.0)
    df["ClosedVolume"] = pd.to_numeric(raw.iloc[:, 7], errors="coerce").fillna(0.0)

    df["Commission"] = 0.0
    df["Swap"] = 0.0
    if raw.shape[1] >= 9:
        df["Commission"] = pd.to_numeric(raw.iloc[:, 8], errors="coerce").fillna(0.0)
    if raw.shape[1] >= 11:
        df["Swap"] = pd.to_numeric(raw.iloc[:, 10], errors="coerce").fillna(0.0)

    return (
        df.groupby("Login", as_index=False)[
            ["NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]
        ].sum()
    )

def load_equity_sheet(file: BytesIO) -> pd.DataFrame:
    """
    Sheet 2/3 – Equity report
    Default:
      Login = col A(0)
      Equity = col J(9)
    Rule: equity < 0 => 0
    """
    raw = _read_excel_or_csv(file)
    cols_lower = [str(c).strip().lower() for c in raw.columns]

    def find_col(name_options, default_idx=None):
        for opt in name_options:
            if opt in cols_lower:
                return raw.columns[cols_lower.index(opt)]
        if default_idx is not None and default_idx < len(raw.columns):
            return raw.columns[default_idx]
        raise ValueError(f"Could not find column for {name_options}")

    login_col = find_col(["login"], 0)
    equity_col = find_col(["equity"], 9)

    currency_col = None
    for opt in ["currency", "curr", "ccy"]:
        if opt in cols_lower:
            currency_col = raw.columns[cols_lower.index(opt)]
            break

    out = pd.DataFrame()
    out["Login"] = pd.to_numeric(raw[login_col], errors="coerce").astype("Int64")
    eq = pd.to_numeric(raw[equity_col], errors="coerce").fillna(0.0)
    out["Equity"] = eq.clip(lower=0.0)
    out["Currency"] = raw[currency_col].astype(str) if currency_col is not None else "USD"
    return out

def _read_accounts_file(file: BytesIO) -> pd.DataFrame:
    """
    Book-wise account lists:
    - Login is column A (index 0)
    - Group is column E (index 4)  ✅ as per your requirement
    """
    raw = _read_excel_or_csv(file)

    if raw.shape[1] < 1:
        raise ValueError("Accounts file looks empty.")

    login_series = pd.to_numeric(raw.iloc[:, 0], errors="coerce").astype("Int64")

    if raw.shape[1] >= 5:
        group_series = raw.iloc[:, 4].astype(str).fillna("")
    else:
        group_series = pd.Series([""] * len(raw), dtype="object")

    out = pd.DataFrame({"Login": login_series, "Group": group_series})
    out["Group"] = out["Group"].replace(["nan", "None"], "").fillna("").astype(str).str.strip()
    return out

def load_book_accounts(file: BytesIO, book_type: str) -> pd.DataFrame:
    df = _read_accounts_file(file)
    df["OrigType"] = book_type
    df["Type"] = book_type
    return df

def build_report(summary_df, closing_df, opening_df, accounts_df, eod_label: str) -> pd.DataFrame:
    """
    Net PNL = Closing Equity - Opening Equity - Net D/W - Credit
    Equity negative => 0
    """
    base = closing_df.rename(columns={"Equity": "Closing Equity"}).copy()
    open_df = opening_df.rename(columns={"Equity": "Opening Equity"})

    base = base.merge(open_df[["Login", "Opening Equity"]], on="Login", how="left")
    base = base.merge(summary_df, on="Login", how="left")

    report = accounts_df.merge(base, on="Login", how="left")

    for col in ["Closing Equity", "Opening Equity", "NET_DP_WD", "Credit", "ClosedVolume", "Commission", "Swap"]:
        report[col] = pd.to_numeric(report.get(col, 0.0), errors="coerce").fillna(0.0)

    report["Opening Equity"] = report["Opening Equity"].clip(lower=0.0)
    report["Closing Equity"] = report["Closing Equity"].clip(lower=0.0)

    report["Closed Lots"] = report["ClosedVolume"] / 2.0
    report["NET DP/WD"] = report["NET_DP_WD"]
    report["Deposit"] = np.where(report["NET DP/WD"] > 0, report["NET DP/WD"], 0.0)
    report["Withdrawal"] = np.where(report["NET DP/WD"] < 0, -report["NET DP/WD"], 0.0)

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

    report["EOD Closing Equity Date"] = eod_label

    # NOTE: We keep Type/OrigType internally, but later we will HIDE it in the Accounts sheet export & UI.
    final_cols = [
        "Login", "Group", "OrigType", "Type", "Currency",
        "Closed Lots", "NET DP/WD", "Credit",
        "Opening Equity", "Closing Equity",
        "NET PNL USD", "NET PNL %",
        "Deposit", "Withdrawal",
        "Commission", "Swap",
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

def build_book_summary(account_df: pd.DataFrame) -> pd.DataFrame:
    return (
        account_df.groupby("Type", as_index=False)
        .agg(
            Accounts=("Login", "nunique"),
            Closed_Lots=("Closed Lots", "sum"),
            NET_DP_WD=("NET DP/WD", "sum"),
            Credit=("Credit", "sum"),
            NET_PNL_USD=("NET PNL USD", "sum"),
        )
        .sort_values("Type")
        .reset_index(drop=True)
    )

def load_lp_breakdown_file(file: BytesIO) -> pd.DataFrame:
    df = _read_excel_or_csv(file)
    lower = {str(c).strip().lower(): c for c in df.columns}

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
# SIDEBAR – OPTIONAL LP PANEL
# =========================================================
with st.sidebar:
    st.markdown("## 🧾 P&L Studio")
    st.caption("Client P&L + Group/Book summaries. Optional LP brokerage below.")
    st.divider()
    st.markdown("### 🏦 A-Book LP P&L (optional)")
    st.caption("Brokerage P&L = Total LP P&L − Client A-Book P&L.")
    lp_file = st.file_uploader("LP breakdown file (XLSX / CSV)", type=["xlsx", "xls", "csv"], key="lp_file")


# =========================================================
# MAIN HEADER
# =========================================================
st.markdown(
    """
<div class="hero">
  <div class="hero-badge">⚡ MT5 • Client P&L Studio</div>
  <div class="hero-title">Client P&L Monitoring</div>
  <p class="hero-sub">
    Net P&L = Closing − Opening − Net D/W − Credit (Equity &lt; 0 is treated as 0).
    Group is taken from Book-wise account list <b>Column E</b>.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# =========================================================
# FILE UPLOADS
# =========================================================
st.markdown(
    """
<div class="section">
  <div class="section-title">
    <h2>1) Upload MT5 reports</h2>
    <span class="pill">Required</span>
  </div>
  <div class="small-note">Required: Summary + Closing Equity + Opening Equity.</div>
</div>
""",
    unsafe_allow_html=True,
)

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

st.markdown(
    """
<div class="section">
  <div class="section-title">
    <h2>2) Book-wise account lists</h2>
    <span class="pill">Login(A) + Group(E)</span>
  </div>
  <div class="small-note">
    Group will be read from <b>Column E</b> of these files (Excel column E = index 4).
  </div>
</div>
""",
    unsafe_allow_html=True,
)

cb1, cb2, cb3 = st.columns(3)
with cb1:
    a_book_file = st.file_uploader("A-Book accounts", type=["xlsx", "xls", "csv"], key="abook")
with cb2:
    b_book_file = st.file_uploader("B-Book accounts", type=["xlsx", "xls", "csv"], key="bbook")
with cb3:
    hybrid_file = st.file_uploader("Hybrid accounts (optional)", type=["xlsx", "xls", "csv"], key="hybrid")

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

                frames = []
                if a_book_file:
                    frames.append(load_book_accounts(a_book_file, "A-Book"))
                if b_book_file:
                    frames.append(load_book_accounts(b_book_file, "B-Book"))
                if hybrid_file:
                    frames.append(load_book_accounts(hybrid_file, "Hybrid"))

                accounts_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Login"])

                account_df = build_report(summary_df, closing_df, opening_df, accounts_df, eod_label)
                group_df = build_group_summary(account_df)
                book_df = build_book_summary(account_df)

            # KPI
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>3) Overview</h2>
    <span class="pill">KPI</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

            total_clients = int(account_df["Login"].nunique())
            total_closed_lots = float(account_df["Closed Lots"].sum())
            net_pnl_total = float(account_df["NET PNL USD"].sum())
            total_credit = float(account_df["Credit"].sum())

            total_profit = float(account_df.loc[account_df["NET PNL USD"] > 0, "NET PNL USD"].sum())
            total_loss = float(account_df.loc[account_df["NET PNL USD"] < 0, "NET PNL USD"].sum())

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(f"""
<div class="metric"><div class="k">Clients</div><div class="v">{total_clients:,}</div><div class="s">Unique logins</div></div>
""", unsafe_allow_html=True)
            with k2:
                st.markdown(f"""
<div class="metric"><div class="k">Closed lots</div><div class="v">{total_closed_lots:,.2f}</div><div class="s">Sheet-1 col H / 2</div></div>
""", unsafe_allow_html=True)
            with k3:
                st.markdown(f"""
<div class="metric"><div class="k">Total Credit</div><div class="v">{total_credit:,.2f}</div><div class="s">Sheet-1 col F</div></div>
""", unsafe_allow_html=True)
            with k4:
                st.markdown(f"""
<div class="metric"><div class="k">Net client P&L</div><div class="v">{net_pnl_total:,.2f}</div><div class="s">Closing − Opening − Net D/W − Credit</div></div>
""", unsafe_allow_html=True)

            chart_data = pd.DataFrame({"Side": ["Profit", "Loss"], "Amount": [total_profit, abs(total_loss)]}).set_index("Side")
            st.bar_chart(chart_data, height=260)

            # =================================================
            # FULL ACCOUNT TABLE (Type removed from UI)
            # =================================================
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>4) Full account P&L</h2>
    <span class="pill">Accounts</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            st.dataframe(account_df.drop(columns=["Type", "OrigType"], errors="ignore"), use_container_width=True)

            # =================================================
            # BOOK SUMMARY (still uses Type)
            # =================================================
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>5) Book summary</h2>
    <span class="pill">A-Book / B-Book / Hybrid</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            st.dataframe(book_df, use_container_width=True)

            pnl_a = float(book_df.loc[book_df["Type"] == "A-Book", "NET_PNL_USD"].sum())
            pnl_b = float(book_df.loc[book_df["Type"] == "B-Book", "NET_PNL_USD"].sum())
            pnl_h = float(book_df.loc[book_df["Type"] == "Hybrid", "NET_PNL_USD"].sum())
            total_books_pnl = pnl_a + pnl_b + pnl_h
            result_label = "profit" if total_books_pnl >= 0 else "loss"
            st.markdown(f"**Client P&L across all books: {total_books_pnl:,.2f} ({result_label})**")

            # =================================================
            # TOPS (Type removed)
            # =================================================
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>6) Top accounts & groups</h2>
    <span class="pill">Leaders</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

            show_cols = [
                "Login", "Group",
                "Opening Equity", "Closing Equity",
                "NET DP/WD", "Credit",
                "Closed Lots", "NET PNL USD", "NET PNL %"
            ]

            t1, t2 = st.columns(2)
            with t1:
                st.markdown("**Top 10 gainer accounts**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=False).head(10)[show_cols],
                    use_container_width=True,
                )
            with t2:
                st.markdown("**Top 10 loser accounts**")
                st.dataframe(
                    account_df.sort_values("NET PNL USD", ascending=True).head(10)[show_cols],
                    use_container_width=True,
                )

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
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>7) A-Book vs LP brokerage</h2>
    <span class="pill">Optional</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

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
            # DOWNLOAD EXCEL (Type removed from Accounts sheet)
            # =================================================
            st.markdown(
                """
<div class="section">
  <div class="section-title">
    <h2>8) Download Excel report</h2>
    <span class="pill">Export</span>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                accounts_export = account_df.drop(columns=["Type", "OrigType"], errors="ignore")
                accounts_export.to_excel(writer, index=False, sheet_name="Accounts")
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
