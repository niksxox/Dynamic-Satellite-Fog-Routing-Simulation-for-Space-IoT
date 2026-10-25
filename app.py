from __future__ import annotations

import streamlit as st

from dashboard.pages import (experiment_history, failure_replay, network_explorer,
                             overview, performance_analytics, simulation_lab)
from dashboard.services.storage import open_repository


@st.cache_resource(show_spinner=False)
def postgres_repository():
    return open_repository("postgres")


st.set_page_config(page_title="Orbital Routing Lab", page_icon="🛰️", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { --ink: #e7eff7; --muted: #95aabe; --line: #24394c; --panel: #0d1b29; }
.stApp { background: radial-gradient(ellipse at 72% 0%, #102d43 0, #07121e 48%, #07121e 100%); color: var(--ink); }
[data-testid="stSidebar"] { background: #091724; border-right: 1px solid var(--line); }
h1,h2,h3 { letter-spacing: -0.025em; }
[data-testid="stMetric"] { background: rgba(13,27,41,.82); border: 1px solid var(--line); padding: 14px 16px; border-radius: 12px; }
[data-testid="stMetricLabel"] { color: #91a9be; }
div[data-testid="stAlert"] { border-radius: 10px; }
.mission-tag { color: #43d7bd; font-size: .78rem; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

if "dashboard_runs" not in st.session_state:
    st.session_state.dashboard_runs = {}
if "dashboard_experiments" not in st.session_state:
    st.session_state.dashboard_experiments = []

with st.sidebar:
    st.markdown('<div class="mission-tag">SPACE-IOT · RESEARCH CONSOLE</div>', unsafe_allow_html=True)
    st.title("Orbital Routing Lab")
    page = st.radio("Workspace", ["Overview", "Network Explorer", "Simulation Lab",
        "Performance Analytics", "Failure Replay", "Experiment History"], label_visibility="collapsed")
    st.divider()
    storage = st.radio("Run storage", ["local", "postgres"], horizontal=True,
        format_func=lambda x: "Local session" if x == "local" else "PostgreSQL")
    if storage == "local":
        st.caption("Session-local simulation traces and local experiment exports. No database writes.")
    else:
        st.caption("Persist simulation and experiment records using DATABASE_URL.")
    st.divider()
    st.caption("Model time is virtual seconds. Wall-clock runtime is reported separately.")

repository = None
if storage == "postgres":
    try:
        repository = postgres_repository()
        st.sidebar.success("PostgreSQL ready")
    except Exception as exc:
        st.sidebar.error(f"PostgreSQL unavailable ({type(exc).__name__}).")
        st.sidebar.caption("Check DATABASE_URL, database credentials, server reachability and schema access, or switch to Local session storage. Connection details are hidden to avoid exposing credentials.")

st.markdown('<div class="mission-tag">DYNAMIC SATELLITE · GROUND · FOG NETWORK</div>', unsafe_allow_html=True)
if page == "Overview":
    overview.render(repository)
elif page == "Network Explorer":
    network_explorer.render(repository)
elif page == "Simulation Lab":
    simulation_lab.render(repository, storage)
elif page == "Performance Analytics":
    performance_analytics.render(repository)
elif page == "Failure Replay":
    failure_replay.render(repository)
else:
    experiment_history.render(repository)
