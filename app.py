import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------
st.set_page_config(
    page_title="Client P&L Monitoring Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# GLOBAL THEME / CSS
# ---------------------------------------------------------
st.markdown(
    """
<style>
/* ---------- Global ---------- */
html, body, [class*="css"]  {
    font-family: -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,sans-serif;
}

/* remove default margins */
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 2.5rem !important;
}

/* nice scrollbars */
::-webkit-scrollbar {
  width: 8px;
}
::-webkit-scrollbar-thumb {
  background: #6366f1;
  border-radius: 4px;
}

/* ---------- HERO BANNER ---------- */
.hero {
    background: radial-gradient(circle at top left,#4f46e5,#111827 55%);
    border-radius: 18px;
    padding: 20px 26px 22px 26px;
    margin-bottom: 1.5rem;
    color: #e5e7eb;
    position: relative;
    overflow: hidden;
}
.hero::after{
    content:'';
    position:absolute;
    right:-140px;
    top:-80px;
    width:260px;
    height:260px;
    background: radial-gradient(circle,#22c55e55,transparent 70%);
    filter: blur(0px);
}
.hero-title {
    font-size: 2.0rem;
    font-weight: 700;
    letter-spacing: -0.03em;
}
.hero-subtitle {
    font-size: 0.95rem;
    color: #cbd5f5;
    max-width: 640px;
}
.hero-chip {
    display:inline-flex;
    align-items:center;
    gap:0.35rem;
    padding: 0.15rem 0.6rem;
    border-radius:999px;
    font-size:0.75rem;
    background: rgba(15,23,42,0.7);
    border:1px solid rgba(148,163,184,0.35);
    color:#e5e7eb;
}
.hero-chip span.badge {
    display:inline-flex;
    align-items:center;
    justify-content:center;
    width:18px;
    height:18px;
    border-radius:999px;
    background:#6366f1;
    color:white;
    font-size:0.7rem;
}

/* ---------- CARDS / PANELS ---------- */
.app-card {
    background: #0b1120;
    border-radius: 16px;
    padding: 18px 18px 16px 18px;
    border: 1px solid rgba(148,163,184,0.35);
}
.app-card-light {
    background: #ffffff;
    border-radius: 14px;
    padding: 16px 16px 16px 16px;
    border: 1px solid rgba(209,213,219,0.8);
}
.app-section-title {
    font-size: 1.0rem;
    font-weight: 600;
    display:flex;
    align-items:center;
    gap:0.45rem;
    margin-bottom:0.6rem;
}
.app-section-pill {
    width:22px;
    height:22px;
    border-radius:999px;
    background:#6366f1;
    color:white;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:0.78rem;
}
.app-section-sub {
    font-size:0.83rem;
    color:#6b7280;
    margin-top:-4px;
    margin-bottom:0.6rem;
}

/* ---------- METRIC CHIPS ---------- */
.metric-chip {
    background:#111827;
    border-radius:12px;
    border:1px solid rgba(148,163,184,0.35);
    padding:0.55rem 0.6rem;
}
.metric-label {
    font-size:0.72rem;
    text-transform:uppercase;
    letter-spacing:0.09em;
    color:#9ca3af;
}
.metric-value {
    font-size:1.15rem;
    font-weight:600;
    color:#e5e7eb;
}

/* ---------- FILE UPLOAD BOX ---------- */
div[data-baseweb="file-uploader"] {
    background:#050816;
    border-radius:14px !important;
    border:1px dashed rgba(148,163,184,0.7) !important;
}
div[data-baseweb="file-uploader"] label {
    color:#e5e7eb !important;
}

/* ---------- BUTTONS ---------- */
.stButton > button {
    border-radius: 999px;
    padding: 0.45rem 1.2rem;
    border: none;
    font-weight: 600;
    background: linear-gradient(135deg,#4f46e5,#22c55e);
    color: white;
    box-shadow: 0 10px 25px rgba(37,99,235,0.35);
}
.stButton > button:hover {
    opacity: 0.94;
    box-shadow: 0 14px 30px rgba(37,99,235,0.40);
}

/* ---------- TABLE TWEAKS ---------- */
.dataframe tbody tr:nth-child(odd) {
    background-color:#f9fafb;
}
.dataframe tbody tr:nth-child(even) {
    background-color:#ffffff;
}
.dataframe thead th {
    background-color:#f3f4f6;
}

/* ---------- SIDEBAR ---------- */
section[data-testid="stSidebar"] {
    background: #020617;
}
section[data-testid="stSidebar"] .sidebar-content {
    padding-top: 0.8rem;
}
.sidebar-title {
    font-size:0.95rem;
    font-weight:600;
    color:#e5e7eb;
}
.sidebar-subtitle {
    font-size:0.8rem;
    color:#9ca3af;
}

</style>
""",
    unsafe_allow_html=True,
)
