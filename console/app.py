"""
console/app.py — WHA Membership Data Platform: admin console (was root app_v4.py, moved 2026-07-22).

Multi-page console with folder-style nav:
  Control Panel
  Reports
    Membership Performance Report
      Snapshot · Visuals · Results
    Retention Detail Report
      Run · Results
  System
    Admin Inputs
    Data & Schedule
"""

import json
import os
import re as _re_mod
import subprocess
import sys as _sys
import datetime as _dt
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

from src.hub.datahub import resolve_first_available, get_or_fetch
from reports.membership_performance_tracker.logic.retention import DEFAULT_RETENTION_GOAL


def render_altair_raw(chart, height=380):
    """LEGACY — was a components.html workaround. Unused; left in case."""
    chart = chart.properties(width="container")
    components.html(chart.to_html(), height=height, scrolling=False)


# ─────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]   # console/ lives one level below the repo root
CACHE_DIR    = PROJECT_ROOT / "data" / "cache"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "output"
ADMIN_XLSX   = PROJECT_ROOT / "data" / "raw" / "admin_inputs.xlsx"
# Runner paths resolved through the report registry (reconstruction P6) —
# the console discovers report nodes instead of hardcoding their layout.
from src.base.registry import runner_path as _runner_path
TEST_SCRIPT  = _runner_path("membership_performance_tracker")
DRILLDOWN_SCRIPT = _runner_path("retention_detail")

import os as _os
from dotenv import load_dotenv as _load_dotenv
# 2026-07-17: the console NEVER loaded .env — any env-less launch silently
# booted as 2026-03 (the March-download incident: fresh-LOOKING badge, stale
# March data; Railway affected too). .env now pins MPR_PERIOD; the structural
# fix (latest-available default + UI month selector + a freshness badge that
# shows the DATA's pull time, not the file's sync time) is tracked.
_load_dotenv(PROJECT_ROOT / ".env")
from src.config.period import parse_period as _parse_period, list_available_periods as _list_available_periods

# Reporting period (Phase C, 2026-07-18). Priority:
#   1. MPR_PERIOD env — the labeled escape hatch (badge shows "Pinned … override");
#      also how a deploy (Railway) can pin itself.
#   2. The month picked in the sidebar selector (session state).
#   3. The NEWEST period that actually has data — the honest default. This is the
#      structural fix for the March-download incident: no more hardcoded month
#      serving stale data that LOOKS fresh.
def _console_periods() -> list:
    """Months the CONSOLE can show, newest first — the union across reports.

    Was: only months with an MPR scoreboard cache, which made the picker read
    "March, June, July" (three arbitrary cache files) as if those were the
    only months that exist. The picker is platform-level, so it must offer
    what ANY report can serve; each page says for itself when it has nothing
    for the selected month (MPR shows "No cache file", dues shows its edition
    availability inline). Derived from data, never a literal list.
    """
    periods = set(_list_available_periods(CACHE_DIR))
    try:
        from reports.dues_analysis.logic.periods import default_period, fy_months
        periods |= set(fy_months(default_period()))
    except Exception:
        pass                    # a broken report must not empty the picker
    # EVERY month of the current fiscal year is pickable (Jiho 8/6: "there
    # is no August button") — months without data say so on their pages;
    # invisibility is not the same as emptiness.
    import datetime as _d
    today = _d.date.today()
    fy_start = today.year if today.month >= 10 else today.year - 1
    for i in range(12):
        m = (10 + i - 1) % 12 + 1
        y = fy_start if m >= 10 else fy_start + 1
        periods.add(f"{y}-{m:02d}")
    return sorted(periods, reverse=True)


AVAILABLE_PERIODS = _console_periods()                   # newest first
_CURRENT_PERIOD = _dt.date.today().strftime("%Y-%m")     # the month we're in
_ENV_PIN = _os.environ.get("MPR_PERIOD")
PERIOD_PINNED = bool(_ENV_PIN)
if PERIOD_PINNED:
    _period_str = _ENV_PIN
elif st.session_state.get("view_period") in AVAILABLE_PERIODS:
    _period_str = st.session_state["view_period"]
elif _CURRENT_PERIOD in AVAILABLE_PERIODS:
    # Open on THIS month (Jiho 8/13). The old default was "newest month with a
    # local scoreboard", which lands on last month whenever the current one
    # hasn't been generated on this machine yet — and a deploy wipes the
    # container's disk, so every deploy made the console open on July. The
    # month you are working in is the honest landing spot; if it has nothing
    # yet, its pages say so.
    _period_str = _CURRENT_PERIOD
else:
    _with_data = [p for p in AVAILABLE_PERIODS
                  if (CACHE_DIR / f"scoreboard_{p}.json").exists()]
    _period_str = (_with_data[0] if _with_data
                   else AVAILABLE_PERIODS[0] if AVAILABLE_PERIODS else "2026-03")
_PERIOD       = _parse_period(_period_str)
PERIOD        = _PERIOD.period          # "2026-03"
CURRENT_MONTH = _PERIOD.current_month   # "Mar"
CACHE_FILE   = CACHE_DIR / f"scoreboard_{PERIOD}.json"
SCHEDULED_RUN_LOG = OUTPUT_DIR / "scheduled_run.log"

# User-visible naming (2026-06-05 rename, finding from SP audit). Internal Python
# identifiers (TrackerV4Mapper/Writer, the package dir) stay as-is — renaming them
# is invasive churn the admin never sees. Only the SharePoint folder, output xlsx
# filename, and console labels are renamed to match the business-side name "MPR".
REPORT_NAME          = "Membership Performance Report"
DUES_REPORT_NAME     = "Dues Analysis"
TRACKER_FILENAME     = f"Membership_Performance_Report_{PERIOD}.xlsx"

OUTPUT_FILE          = OUTPUT_DIR / TRACKER_FILENAME

SP_HUB_FOLDER        = "Internal Dept Files/Membership Data Hub"
SP_ADMIN_PATH        = f"{SP_HUB_FOLDER}/admin_inputs.xlsx"
SP_SHARED_ADMIN_PATH = f"{SP_HUB_FOLDER}/Inputs/admin_inputs.xlsx"
# ONE copy only (2026-07-22, Jiho: "converge it, keep the one in the input
# folder"): the root copy was deleted from SharePoint; Inputs/
# admin_inputs.xlsx is the single admin workbook. Send Jen links to THIS file.
SP_ADMIN_READ_PATHS  = [SP_SHARED_ADMIN_PATH]


def _resolve_output_file() -> Path:
    return OUTPUT_DIR / TRACKER_FILENAME


def _sp_tracker_versioned_path() -> str:
    """Honest SP location line (8/10 — the old version FORMATTED today's
    date as the path, which was simply false for hydrated files). If this
    session fetched the file, name where it came from; otherwise name the
    layout destination builds publish to."""
    prov = st.session_state.get(f"wb_prov_{PERIOD}")
    base = f"{SP_HUB_FOLDER}/Reports/{REPORT_NAME}/Output/{PERIOD}"
    if prov == "FINAL":
        return f"{base}/FINAL/{TRACKER_FILENAME}  (the locked final)"
    if prov:
        return f"{base}/{prov}"
    return f"{base}/Runs/  (each generation is timestamped; closed months also update FINAL)"


# ─────────────────────────────────────────────────────────────────────
# Page config + global styling
# ─────────────────────────────────────────────────────────────────────
# WHA palette (per original code comments — these are the brand hexes):
#   #02b5e3  primary blue accent
#   #58595b  charcoal (text)
#   #808184  muted grey
#   #d1d2d3  border grey
#   #5a9e00  brand green
#   #e87722  brand gold
# Plus we add a few neutrals for backgrounds.
_WHA_MARK   = PROJECT_ROOT / "assets" / "wha-mark.png"
_WHA_LOGO   = PROJECT_ROOT / "assets" / "wha-logo.png"

st.set_page_config(
    page_title="WHA Data Platform",
    page_icon=str(_WHA_MARK) if _WHA_MARK.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&display=swap" rel="stylesheet">
<style>
    /* ───── Reset & base ───── */
    html, body, [class*="css"], [class*="st-"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        -webkit-font-smoothing: antialiased;
    }
    /* Restore Material Icons font on Streamlit's icon elements
       (otherwise the Inter override above turns ligatures into literal text
       like "keyboard_double_arrow_right" / "keyboard_arrow_right"). */
    [data-testid="stIconMaterial"],
    .material-icons,
    .material-symbols-outlined,
    [class*="material-icons"],
    [class*="material-symbols"],
    [data-testid="stExpanderToggleIcon"],
    [data-testid="stExpander"] svg + span,
    [data-testid="stExpander"] details > summary span:not(.section-label):not(.pill),
    button[kind="headerNoPadding"] span,
    button[kind="header"] span,
    [data-testid="stSidebarCollapseButton"] span,
    [data-testid="stSidebarCollapsedControl"] span {
        font-family: 'Material Symbols Outlined', 'Material Symbols Rounded',
                     'Material Icons' !important;
        font-feature-settings: 'liga';
        font-weight: normal !important;
        font-style: normal !important;
        font-variant-ligatures: discretionary-ligatures !important;
        text-transform: none !important;
        line-height: 1 !important;
        letter-spacing: normal !important;
        word-wrap: normal !important;
        white-space: nowrap !important;
        direction: ltr !important;
    }
    [data-testid="stAppViewContainer"] { background: #fafbfc; }

    /* Keep Streamlit's header intact so the sidebar toggle works.
       Only hide the right-side toolbar items (Deploy/Share/etc). */
    [data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stToolbarActions"] { display: none !important; }
    [data-testid="stStatusWidget"]   { display: none !important; }
    [data-testid="stDecoration"]     { display: none !important; }
    /* Hide Streamlit's main menu (kebab three-dots — Settings/About/Rerun).
       Not useful inside an internal admin tool, and it was overlapping the
       sidebar collapse arrow at the top-left corner. */
    #MainMenu,
    [data-testid="stMainMenu"]       { display: none !important; }

    /* Force sidebar to stay visible — this app's nav lives there. */
    [data-testid="stSidebar"] {
        visibility: visible !important;
        min-width: 240px !important;
    }

    /* When the sidebar is collapsed, push the expand-toggle FLUSH to the
       LEFT edge of the viewport. Default Streamlit insets it ~1.5rem so it
       looks like a stray arrow floating in space. */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"],
    button[kind="headerNoPadding"] {
        position: fixed !important;
        top: 0.4rem !important;
        left: 0 !important;
        margin-left: 0 !important;
        padding-left: 0.15rem !important;
        padding-right: 0.35rem !important;
        z-index: 999 !important;
    }

    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 4rem;
        max-width: 1240px;
    }

    /* ───── Sidebar — light, clean ───── */
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e4e6ea;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.8rem;
    }
    [data-testid="stSidebar"] .stButton button {
        background: transparent;
        color: #58595b;
        border: none;
        border-radius: 6px;
        padding: 0.5rem 0.9rem !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        font-family: 'Inter', sans-serif !important;
        justify-content: flex-start !important;
        text-align: left !important;
        min-height: 0 !important;
        line-height: 1.3 !important;
        width: 100%;
        transition: background 0.12s ease, color 0.12s ease;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background: #f0f2f5;
        color: #1d2433;
    }
    [data-testid="stSidebar"] .stButton button[kind="primary"] {
        background: #e3f6fc !important;
        color: #0092b5 !important;
        font-weight: 600 !important;
        border-left: 3px solid #02b5e3;
        border-radius: 4px;
    }

    /* Tighten — but don't eliminate — Streamlit's default vertical gap
       between sidebar widgets. Zero gap caused overlaps. */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.15rem !important; }
    [data-testid="stSidebar"] [data-testid="element-container"] {
        margin: 0 !important;
    }
    [data-testid="stSidebar"] .stButton { margin: 0 !important; }

    /* Sidebar brand header */
    .sb-brand {
        padding: 0.4rem 1rem 1.5rem 1rem;
        border-bottom: 1px solid #f0f2f5;
        margin-bottom: 1rem;
    }
    .sb-brand img {
        max-width: 180px;
        height: auto;
        display: block;
        margin-bottom: 12px;
    }
    .sb-brand-subtitle {
        font-size: 0.78rem;
        font-weight: 600;
        color: #58595b;
        letter-spacing: 0.01em;
    }
    .sb-brand-subtitle .accent { color: #02b5e3; }

    /* Sidebar section labels (top-level: REPORTS, SYSTEM) */
    .sb-section {
        font-size: 0.65rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        font-weight: 700;
        color: #a8aab0;
        padding: 2.4rem 1rem 0.7rem 1rem;
        line-height: 1.8;
    }

    /* Sidebar sub-section labels (inside a folder: "Sub-Reports", "Views") */
    .sb-subsection {
        font-size: 0.58rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-weight: 700;
        color: #c0c2c8;
        padding: 1.5rem 1rem 0.5rem 1.7rem;
        line-height: 1.8;
    }
    /* Terminates an expanded report's sub-items so the next top-level report
       doesn't read as another item under the last subsection caption. */
    .sb-group-end {
        border-bottom: 1px solid #ececf0;
        margin: 0.65rem 1rem 0.75rem 1.7rem;
    }

    /* Sidebar sub-page styling: indented, smaller, with a subtle vertical
       guide on the left to show nesting */
    .sb-sub {
        position: relative;
        margin-left: 1.1rem;
        padding-left: 0.6rem;
        border-left: 1.5px solid #e4e6ea;
    }
    .sb-sub .stButton button {
        padding: 0.35rem 0.6rem !important;
        font-size: 0.8rem !important;
        color: #808184;
        font-weight: 500 !important;
        border-radius: 4px !important;
    }
    .sb-sub .stButton button[kind="primary"] {
        background: transparent !important;
        color: #02b5e3 !important;
        border-left: none !important;
        font-weight: 600 !important;
    }
    .sb-sub .stButton button:hover {
        background: #f5f6f8;
        color: #1d2433;
    }

    /* Sidebar status footer — inline at bottom (not absolute) */
    .sb-footer {
        padding: 0.7rem 1.2rem;
        margin-top: 1.5rem;
        border-top: 1px solid #f0f2f5;
        font-size: 0.75rem;
        color: #808184;
    }
    .sb-status-dot {
        display: inline-block;
        width: 7px;
        height: 7px;
        border-radius: 50%;
        margin-right: 6px;
        vertical-align: middle;
    }

    /* ───── Page header ───── */
    .page-eyebrow {
        font-size: 0.7rem;
        letter-spacing: 0.1em;
        font-weight: 700;
        text-transform: uppercase;
        color: #02b5e3;
        margin-bottom: 6px;
    }
    .page-header {
        font-size: 1.75rem;
        font-weight: 700;
        color: #1d2433;
        letter-spacing: -0.02em;
        margin-bottom: 0.2rem;
        line-height: 1.15;
    }
    .page-sub {
        font-size: 0.92rem;
        color: #808184;
        margin-bottom: 1.8rem;
    }

    /* ───── Section labels ───── */
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #808184;
        margin-bottom: 0.6rem;
        margin-top: 1.8rem;
    }
    .section-label:first-child { margin-top: 0; }

    /* Bigger title style used above each Altair chart on the Analytics page.
       Distinct from .section-label (which is a small uppercase eyebrow). */
    .chart-title {
        font-size: 1.08rem;
        font-weight: 700;
        color: #1d2433;
        letter-spacing: -0.015em;
        margin-top: 2.2rem;
        margin-bottom: 0.35rem;
        line-height: 1.25;
    }
    .chart-title:first-child { margin-top: 0; }

    /* ───── KPI cards ───── */
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e4e6ea;
        border-radius: 10px;
        padding: 1.1rem 1.3rem;
    }
    .kpi-label {
        font-size: 0.7rem;
        color: #808184;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600;
    }
    .kpi-value {
        font-size: 1.85rem;
        font-weight: 700;
        color: #1d2433;
        margin: 6px 0 4px;
        letter-spacing: -0.02em;
        line-height: 1.1;
    }
    .kpi-meta {
        font-size: 0.78rem;
        color: #808184;
        font-weight: 400;
    }
    /* Text variants — darker for legibility on white. The brand bright
       variants (#90d000 / #f0b010) are used on bars and accents instead. */
    .kpi-green { color: #5a8a00; }   /* WHA lime, darkened for text */
    .kpi-amber { color: #b88500; }   /* WHA gold, darkened for text */
    .kpi-red   { color: #c62828; }

    /* Accent on cards that need to draw the eye — uses bright WHA gold */
    .kpi-card.alert {
        border-left: 3px solid #f0b010;
    }

    /* ───── Status bar ───── */
    .status-bar {
        background: #ffffff;
        border: 1px solid #e4e6ea;
        border-radius: 10px;
        padding: 0.85rem 1.4rem;
        display: flex;
        gap: 2.5rem;
        align-items: center;
        margin-bottom: 1.8rem;
        font-size: 0.85rem;
        color: #58595b;
    }
    .status-bar b {
        color: #1d2433;
        font-weight: 600;
        margin-right: 4px;
    }

    /* ───── Report row (checkbox left + label) ───── */
    .report-row {
        background: #ffffff;
        border: 1px solid #e4e6ea;
        border-radius: 10px;
        padding: 1rem 1.4rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        transition: border-color 0.15s;
        min-height: 56px;
    }
    .report-row:hover { border-color: #02b5e3; }
    .report-row-title {
        font-size: 0.98rem;
        font-weight: 600;
        color: #1d2433;
        letter-spacing: -0.01em;
        flex: 1;
    }

    /* Center Streamlit checkbox vertically next to the row label */
    .report-row-check [data-testid="stCheckbox"] {
        display: flex;
        align-items: center;
        margin: 0 !important;
    }
    .report-row-check [data-testid="stCheckbox"] > label {
        margin: 0 !important;
        padding: 0 !important;
    }
    .report-row-check [data-testid="stCheckbox"] [data-baseweb="checkbox"] {
        transform: scale(1.15);
    }

    /* ───── Pills ───── */
    .pill {
        display: inline-block;
        padding: 2px 9px;
        border-radius: 11px;
        font-size: 0.73rem;
        font-weight: 600;
    }
    .pill-green { background: #ecf6dc; color: #4a7d00; }
    .pill-amber { background: #fcefcb; color: #8a6200; }   /* WHA gold tint */
    .pill-red   { background: #fce8e8; color: #c62828; }
    .pill-grey  { background: #f0f2f5; color: #808184; }
    .pill-blue  { background: #e3f6fc; color: #0092b5; }

    /* ───── Run history rows ───── */
    .run-row {
        display: flex;
        gap: 1rem;
        padding: 0.5rem 0;
        border-top: 1px solid #f0f2f5;
        font-size: 0.85rem;
        color: #58595b;
    }
    .run-row:first-child { border-top: none; padding-top: 0; }
    .run-when { color: #808184; min-width: 80px; }
    .run-name { color: #1d2433; font-weight: 500; }
    .run-mode { color: #808184; }

    /* ───── Dataframes ───── */
    [data-testid="stDataFrame"] {
        border: 1px solid #e4e6ea !important;
        border-radius: 8px !important;
    }

    /* ───── Buttons (main area) ───── */
    .stButton > button {
        font-family: 'Inter', sans-serif !important;
        font-weight: 500;
        border-radius: 7px;
    }
    .stButton > button[kind="primary"] {
        background: #02b5e3 !important;
        border-color: #02b5e3 !important;
        color: #fff !important;
        font-weight: 600;
    }
    .stButton > button[kind="primary"]:hover {
        background: #0092b5 !important;
        border-color: #0092b5 !important;
    }

    /* Streamlit native alerts — colorize with WHA palette */
    [data-testid="stAlert"][data-baseweb="notification"] { border-radius: 8px; }
    div[data-testid="stAlertContainer"][kind="warning"],
    div[data-baseweb="notification"][kind="warning"] {
        background: #fcefcb !important;
        border-left: 3px solid #f0b010 !important;
        color: #6e4d00 !important;
    }
    div[data-testid="stAlertContainer"][kind="success"],
    div[data-baseweb="notification"][kind="success"] {
        background: #ecf6dc !important;
        border-left: 3px solid #90d000 !important;
        color: #2e5500 !important;
    }
    div[data-testid="stAlertContainer"][kind="info"],
    div[data-baseweb="notification"][kind="info"] {
        background: #e3f6fc !important;
        border-left: 3px solid #02b5e3 !important;
        color: #02546b !important;
    }
    div[data-testid="stAlertContainer"][kind="error"],
    div[data-baseweb="notification"][kind="error"] {
        background: #fce8e8 !important;
        border-left: 3px solid #c62828 !important;
        color: #6b1414 !important;
    }

    /* Spinner: tint with WHA gold to mark "in progress" */
    [data-testid="stSpinner"] > div { border-top-color: #f0b010 !important; }
    [data-testid="stSpinner"] [data-testid="stSpinnerText"] { color: #8a6200 !important; }

    /* Progress bar uses WHA blue */
    [data-testid="stProgress"] > div > div > div > div {
        background-color: #02b5e3 !important;
    }

    /* ───── Dividers ───── */
    hr { border-top: 1px solid #e4e6ea !important; margin: 1.5rem 0 !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────
def _resolve_password() -> str:
    """The console's login password, from config only. NO DEFAULT.

    This used to fall back to a literal password when neither the env var nor
    st.secrets was set. The live service does set APP_PASSWORD, so that
    fallback was never the gate in production — but it was a real password
    sitting in tracked source, and the failure mode it created was silent:
    `gcloud run deploy --set-env-vars` REPLACES the whole environment (the
    deploy checklist warns about exactly this), so one wrong flag drops
    APP_PASSWORD and the console keeps serving, now behind a password anyone
    with the repo can read. A downgrade nothing would have reported.

    Removed 2026-08-14, before the repo goes to an external contractor.
    Unconfigured now means CLOSED, not "open with a known key" — see
    `_check_password`. `.env.example` documents the key.
    """
    env = os.environ.get("APP_PASSWORD")
    if env:
        return env
    try:
        secret = st.secrets.get("app_password")
        if secret:
            return secret
    except Exception:
        pass
    return ""

APP_PASSWORD = _resolve_password()


def _check_password() -> bool:
    # DEV AUTOLOGIN (8/8, Jiho-authorized for deployment verification):
    # test revisions only, env-gated, reachable only through the
    # authenticated gcloud tunnel while the org policy blocks public
    # access. NEVER set on the final revision — the deploy checklist's
    # smoke test asserts the login gate is present.
    if os.environ.get("WHA_DEV_AUTOLOGIN") == "1":
        st.session_state.authenticated = True
        return True
    if st.session_state.get("authenticated"):
        return True
    _l, mid, _r = st.columns([1, 1.5, 1])
    with mid:
        import base64 as _b64
        logo_html = ""
        if _WHA_LOGO.exists():
            _logo_b64 = _b64.b64encode(_WHA_LOGO.read_bytes()).decode()
            logo_html = (
                f"<img src='data:image/png;base64,{_logo_b64}' "
                f"alt='Washington Hospitality Association' "
                f"style='max-width:340px;width:80%;height:auto;display:block;margin:0 auto 1.5rem;'/>"
            )
        st.markdown(
            f"<div style='margin-top:5rem;text-align:center;'>"
            f"{logo_html}"
            f"<h1 style='font-size:1.2rem;color:#58595b;margin:0.5rem 0 1.5rem;font-weight:600;letter-spacing:-0.01em;'>"
            f"Membership Data Platform</h1>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # FAIL CLOSED when no password is configured (2026-08-14). With the
        # literal fallback gone, an unset APP_PASSWORD must lock the door and
        # say why — never accept an empty password, and never leave a reader
        # guessing at a login that cannot succeed.
        if not APP_PASSWORD:
            st.error("This console has no password configured, so it cannot "
                     "let anyone in. Set APP_PASSWORD in the environment "
                     "(see .env.example) and restart.")
            return False
        pw = st.text_input("Password", type="password", label_visibility="collapsed",
                           placeholder="Enter password")
        if pw:
            if pw == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


if not _check_password():
    st.stop()


# ─────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────
_DEFAULTS = {
    "nav":            "control",
    "run_status":     "idle",
    "run_mode":       None,
    "log_lines":      [],
    "output_path":    None,
    "sp_sync_msgs":   [],
    "last_upload_msg": None,
    "last_upload_id":  None,
    "drilldown_status": "idle",
    "drilldown_log":    [],
    "drilldown_path":   None,
}
for k, v in _DEFAULTS.items():
    st.session_state.setdefault(k, v)


# ─────────────────────────────────────────────────────────────────────
# Backend helpers
# ─────────────────────────────────────────────────────────────────────
def _relative(seconds: float) -> str:
    if seconds < 60:    return f"{int(seconds)}s ago"
    if seconds < 3600:  return f"{int(seconds/60)}m ago"
    if seconds < 86400: return f"{int(seconds/3600)}h ago"
    return f"{int(seconds/86400)}d ago"


def format_admin_age(sp_iso: Optional[str], synced_epoch: Optional[float],
                     now: Optional[datetime] = None) -> str:
    """Badge text for the goals workbook (pure — the I/O lives in _admin_age).

    Shows when a human last EDITED it on SharePoint, not when this machine
    last COPIED it. The old reading was the local file's mtime, which said
    "never" on a fresh container (the file was safe on SP all along) and
    never moved when someone actually changed a goal — the opposite of what
    the badge is for (Jiho, 8/13).

    When the SP edit is newer than our copy, the edit has not reached a
    report yet: the workbook is read at the START of a run, so a change is
    invisible until the next one. Saying so here means nobody has to
    remember it. Unknown sync time → no claim either way.
    """
    if not sp_iso:
        return ""                       # caller falls back to local mtime
    try:
        sp_dt = datetime.fromisoformat(str(sp_iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = now or datetime.now(sp_dt.tzinfo)
    age = _relative((now - sp_dt).total_seconds())
    if synced_epoch is not None:
        synced = datetime.fromtimestamp(synced_epoch, sp_dt.tzinfo)
        if sp_dt > synced:
            return f"edited {age} · not in a report yet"
    return f"edited {age}"


def relative_age(path: Path) -> str:
    if not path.exists():
        return "never"
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    s = (datetime.now() - mtime).total_seconds()
    if s < 60:    return f"{int(s)}s ago"
    if s < 3600:  return f"{int(s/60)}m ago"
    if s < 86400: return f"{int(s/3600)}h ago"
    return f"{int(s/86400)}d ago"


def freshness_class(path: Path, stale_after_hours: int = 24) -> str:
    if not path.exists():
        return "kpi-red"
    hours = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
    return _hours_class(hours, stale_after_hours)


def _hours_class(hours: Optional[float], stale_after_hours: int = 24) -> str:
    if hours is None:
        return "kpi-red"
    if hours < stale_after_hours * 0.5:  return "kpi-green"
    if hours < stale_after_hours:        return "kpi-amber"
    return "kpi-red"


def _iso_hours_ago(iso: Optional[str]) -> Optional[float]:
    """Hours since an ISO timestamp, tz-normalised. None when unusable."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return (datetime.now() - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _admin_sp_modified_iso() -> Optional[str]:
    """When the goals workbook was last edited on SharePoint. Cached for two
    minutes — this renders on every page, and SP is a network hop."""
    try:
        from src.hub.datahub import DataHub
        hub = DataHub.connect(require_sharepoint=True)
        for item in hub.list_hub_folder("Inputs"):
            if str(item.get("name") or "").lower() == "admin_inputs.xlsx":
                return item.get("lastModifiedDateTime")
    except Exception:
        pass
    return None                          # offline → caller falls back


def _admin_age() -> str:
    text = format_admin_age(
        _admin_sp_modified_iso(),
        ADMIN_XLSX.stat().st_mtime if ADMIN_XLSX.exists() else None)
    return text or relative_age(ADMIN_XLSX)


def live_pull_estimate(minutes: Optional[int]) -> str:
    """How long a full refresh really takes (pure — see _live_pull_estimate).

    The console advertised "~80 min" for months; measured reality on 8/13 was
    3h05m, and it grows as the program does (C11's lost-cohort sweep added
    ~20 minutes on its own). The runner now records each live run's real
    duration, so this quotes the last one instead of a number that rots.
    """
    mins = int(minutes or 0)
    if mins <= 0:
        mins = 185                       # measured 2026-08-13; replaced by the first recorded run
    return f"~{mins // 60}h{mins % 60:02d}m" if mins >= 60 else f"~{mins} min"


def _live_pull_estimate() -> str:
    try:
        from src.scheduler import load_schedule
        return live_pull_estimate(load_schedule().get("last_live_minutes"))
    except Exception:
        return live_pull_estimate(None)


def _fy_start_of(period: str) -> int:
    """Fiscal-year start year for a YYYY-MM period. WHA FY = Oct 1 -> Sep 30."""
    y, m = int(period[:4]), int(period[5:7])
    return y if m >= 10 else y - 1


def _pulled_at_of(cache_path) -> "Optional[datetime]":
    """The SLX pull time recorded inside a scoreboard file, or None. Reads
    pulled_at (SLX query time), falling back to saved_at. Never the file mtime,
    which the SharePoint sync rewrites on console open (Jiho, 7/20)."""
    try:
        import re as _re
        head = cache_path.open().read(400)
        m = (_re.search(r'"pulled_at":\s*"([^"]+)"', head)
             or _re.search(r'"saved_at":\s*"([^"]+)"', head))
        if not m:
            return None
        dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def _newest_same_fy_cache(period: str):
    """The freshest scoreboard cache in the SAME fiscal year as `period`.

    The scheduled pull names its file by the REPORTING period it targets
    (close-aware: it lags an unclosed month), so the calendar-current month
    the console opens on often has no file of its own even though the live
    FY cache — which spans every month of that fiscal year — is sitting right
    there under the prior month's name. Fall back to it so the viewing month
    shows its real data instead of a false "no data yet".

    SAME-FY ONLY, deliberately: falling back across the Oct 1 boundary would
    render last year's numbers under this year's heading (the 2026-08-11
    Monthly-Trends bug). A new fiscal year with no pull yet correctly finds
    nothing here and says so.
    """
    exact = CACHE_DIR / f"scoreboard_{period}.json"
    if exact.exists():
        return exact
    fy = _fy_start_of(period)
    same_fy = [p for p in CACHE_DIR.glob("scoreboard_*.json")
               if _re_mod.search(r"scoreboard_(\d{4}-\d{2})\.json$", p.name)
               and _fy_start_of(_re_mod.search(r"(\d{4}-\d{2})", p.name).group(1)) == fy]
    if not same_fy:
        return None
    return max(same_fy, key=lambda p: _pulled_at_of(p) or datetime.min)


def _last_slx_pull_age() -> str:
    """When SLX was last pulled AT ALL — global, period-independent.

    The 'SLX Cache' freshness card used to read the VIEWING period's file, so
    opening the console on a month the scheduler hasn't named yet (every
    calendar-current month, until its prior month closes) read a missing file
    and cried 'never' — while SLX had in fact been pulled hours earlier for the
    lagging reporting month (Sep 2026 case, 2026-09-03). The card asks a global
    question; answer it globally: the newest pull time across all caches."""
    times = [t for t in (_pulled_at_of(p) for p in CACHE_DIR.glob("scoreboard_*.json"))
             if t is not None]
    if not times:
        return "never"
    s = (datetime.now() - max(times)).total_seconds()
    if s < 60:    return f"{int(s)}s ago"
    if s < 3600:  return f"{int(s / 60)}m ago"
    if s < 86400: return f"{int(s / 3600)}h ago"
    return f"{int(s / 86400)}d ago"


def _data_age() -> str:
    """Relative age of the DATA's pull time (saved_at) — never the file's mtime,
    which the SharePoint sync rewrites on console open (Jiho, 7/20)."""
    if not CACHE_FILE.exists():
        return "never"
    dt = _pulled_at_of(CACHE_FILE)
    if dt is not None:
        s = (datetime.now() - dt).total_seconds()
        if s < 60:    return f"{int(s)}s ago"
        if s < 3600:  return f"{int(s/60)}m ago"
        if s < 86400: return f"{int(s/3600)}h ago"
        return f"{int(s/86400)}d ago"
    return relative_age(CACHE_FILE)


def _goals_age() -> str:
    """Relative age of the last time a run READ admin_inputs.xlsx.

    `_data_age()` reports `pulled_at` — when SLX was last queried — and that is
    the wrong clock for goals, which come from the SharePoint workbook and are
    re-read on EVERY build, including cache-mode ones that never touch SLX.
    The two drift apart routinely (8/14: pulled_at 08-13 11:13, saved_at 08-14
    12:04), so the caption claimed the goals were a day old when the last run
    had just read them. `saved_at` is that run's clock (Jiho, 8/14).
    """
    if not CACHE_FILE.exists():
        return "never"
    try:
        import re as _re
        m = _re.search(r'"saved_at":\s*"([^"]+)"', CACHE_FILE.open().read(400))
        if m:
            dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            s = (datetime.now() - dt).total_seconds()
            if s < 60:    return f"{int(s)}s ago"
            if s < 3600:  return f"{int(s / 60)}m ago"
            if s < 86400: return f"{int(s / 3600)}h ago"
            return f"{int(s / 86400)}d ago"
    except Exception:
        pass
    return relative_age(CACHE_FILE)


def _pretty_period(p: str) -> str:
    """'2026-06' → 'June 2026' (user-facing month label)."""
    try:
        return datetime(int(p[:4]), int(p[5:7]), 1).strftime("%B %Y")
    except Exception:
        return p


def size_str(path: Path) -> str:
    if not path.exists():
        return "—"
    b = path.stat().st_size
    if b < 1024:       return f"{b} B"
    if b < 1024**2:    return f"{b/1024:.0f} KB"
    return f"{b/1024**2:.1f} MB"


def _ensure_scheduler_running():
    # On the cloud the nightly runs in a PROCESS-level daemon (D2 finding
    # 2: a session-started thread dies with the instance and never returns
    # until someone logs in). The daemon sets WHA_SCHEDULER_DAEMON=1; the
    # in-session thread then stays off so two tickers never race.
    if os.environ.get("WHA_SCHEDULER_DAEMON") == "1":
        return
    from src.scheduler import start_scheduler
    start_scheduler()


def get_sharepoint_client():
    # Master offline switch (2026-07-22): WHA_OFFLINE=1 forces every SharePoint
    # path to short-circuit — for render smoke tests and any intentionally
    # offline run. This is the single choke point all SP access flows through.
    if os.environ.get("WHA_OFFLINE") == "1":
        return None
    if "sp_client" not in st.session_state:
        try:
            from src.sharepoint.client import SharePointClient
            st.session_state.sp_client = SharePointClient.from_env()
        except Exception:
            st.session_state.sp_client = None
    return st.session_state.sp_client


def sharepoint_status():
    return (get_sharepoint_client() is not None,
            "SharePoint connected" if get_sharepoint_client() is not None else "SharePoint offline")


ADMIN_CACHE_KEY = "admin_bytes_cache"

def fetch_admin_bytes(force=False):
    def _do_fetch():
        client = get_sharepoint_client()
        if client is not None:
            data, _ = resolve_first_available(client.read_file, SP_ADMIN_READ_PATHS)
            if data is not None:
                return data, "SharePoint"
        if ADMIN_XLSX.exists():
            return ADMIN_XLSX.read_bytes(), "local"
        return None, "not found"
    return get_or_fetch(st.session_state, ADMIN_CACHE_KEY, _do_fetch, force=force)


def _pull_pid() -> Optional[str]:
    """The pid of a live pull, or None. Checks the schedule state first, then
    falls back to a process probe so CLI-launched pulls are seen too."""
    from src.scheduler import load_schedule, is_pid_alive
    pid = load_schedule().get("current_pid")
    if is_pid_alive(pid):
        return str(pid)
    # Match the MPR's runner SPECIFICALLY. "runner.py" alone matches every
    # report's runner, so a Dues run made the console announce a live SLX
    # pull that was not happening (Jiho, 2026-07-28) — and the phantom
    # progress bar then outlived the process that caused it.
    probe = subprocess.run(
        ["pgrep", "-f", "membership_performance_tracker/runner.py"],
        capture_output=True, text=True)
    return probe.stdout.split()[0] if probe.returncode == 0 else None


@st.fragment(run_every=5)
def _progress_fragment() -> None:
    """Live pull progress. A FRAGMENT (2026-07-22): it refreshes only itself
    every 5s. The first version slept-and-reran the WHOLE page, which would
    have fought the user for control for two hours and hung the test harness.
    """
    # Read-only: NEVER kill from a render path (that would SIGTERM whatever pid
    # is recorded). Recovery of a hung run is the scheduler LOOP's job
    # (_scheduler_loop → _tick_stale_pid_cleanup); here we only DISPLAY.
    from src.scheduler import (latest_progress, run_is_stale, load_schedule,
                               is_pid_alive)
    pid = _pull_pid()
    if not pid:
        st.success("Pull finished — reload the page to see the new report.")
        return
    # A pull the console did NOT launch (command line, agent session) writes
    # its progress to its own log, not ours — so "no progress in our log" is
    # meaningless for it. 8/4 near-miss: the banner called a healthy 2-hour
    # CLI pull "stalled" and offered the kill button mid-run.
    if not is_pid_alive(load_schedule().get("current_pid")):
        st.info(f"A data pull started outside the console (process {pid}) is "
                "running. Its progress can't be shown here — leave it alone; "
                "the report lands on SharePoint when it finishes.")
        return
    if run_is_stale():
        st.warning(f"Pull (process {pid}) appears **stalled** — no progress for "
                   f"over 30 minutes. Use the button to stop it and release the "
                   f"SLX lock, then start a fresh pull.")
        if st.button("Force-clear stalled pull", type="primary"):
            from src.scheduler import force_clear_run
            force_clear_run(kill=True)
            st.rerun()
        return
    pct, msg = latest_progress(OUTPUT_DIR / "scheduled_run.log")
    if pct is None:
        pct, msg = 0, "Starting…"
    st.progress(min(pct, 100) / 100.0, text=f"Live SLX pull — {pct}% · {msg}")
    st.caption(f"Running as background process {pid} — safe to close this tab; "
               "the pull continues and lands on SharePoint.")


def render_pull_progress() -> bool:
    """Show the progress bar when a pull is running. Returns True if shown."""
    if not _pull_pid():
        return False
    _progress_fragment()
    return True


def run_pipeline_sync(mode: str):
    import os as _os
    env = _os.environ.copy()
    # A console-triggered run refreshes the month being VIEWED — explicitly, so
    # the runner never depends on an inherited/pinned env (Phase C).
    env["MPR_PERIOD"] = PERIOD
    # Console-triggered runs PUBLISH (Jiho 8/3: "if it runs on localhost or
    # Railway, the right behavior is going to SP"). The runner's cache-mode
    # guard only silences bare CLI verification builds.
    env["MPR_PUBLISH"] = "1"
    cmd = [_sys.executable, str(TEST_SCRIPT)]   # never bare python3 (PATH trap, 8/6)
    if mode == "cache":
        cmd.append("--from-cache")

    st.session_state.run_mode    = mode
    st.session_state.log_lines   = []
    st.session_state.output_path = None
    st.session_state.sp_sync_msgs = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = get_sharepoint_client()
    if client is not None:
        sp_bytes, _ = resolve_first_available(client.read_file, SP_ADMIN_READ_PATHS)
        if sp_bytes is not None:
            ADMIN_XLSX.parent.mkdir(parents=True, exist_ok=True)
            # only rewrite when the CONTENT changed — a no-change download
            # must not move the file's clock (Jiho 8/6: "admin status was
            # opened and maybe clicked, but it was not changed")
            if not (ADMIN_XLSX.exists() and ADMIN_XLSX.read_bytes() == sp_bytes):
                ADMIN_XLSX.write_bytes(sp_bytes)
            st.session_state.sp_sync_msgs.append("Pulled admin inputs from SharePoint.")
        else:
            st.session_state.sp_sync_msgs.append("No admin file on SharePoint — using local copy.")

    # Banner + captured stdout land on disk so a console-triggered refresh
    # leaves an audit trail that survives the Streamlit session dying. See
    # src.scheduler.write_run_started_banner for the format contract.
    from src.scheduler import write_run_started_banner, write_run_finished_banner

    try:
        write_run_started_banner(SCHEDULED_RUN_LOG, mode, source="console")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, cwd=str(PROJECT_ROOT), env=env)
        write_run_finished_banner(SCHEDULED_RUN_LOG, rc=proc.returncode, stdout=proc.stdout)
        st.session_state.log_lines = proc.stdout.splitlines()
        for line in st.session_state.log_lines:
            if line.startswith("OUTPUT:"):
                st.session_state.output_path = line[7:].strip()
                break
        st.session_state.run_status = "done" if proc.returncode == 0 else "error"

        if st.session_state.run_status == "done" and client is not None:
            out_path = Path(st.session_state.output_path or OUTPUT_FILE)
            if out_path.exists():
                tb = out_path.read_bytes()
                vp = _sp_tracker_versioned_path()
                try:
                    client.write_file(vp, tb)
                    st.session_state.sp_sync_msgs.append("Pushed report to SharePoint.")
                except Exception as exc:
                    st.session_state.sp_sync_msgs.append(f"SharePoint push failed: {exc}")
    except Exception as exc:
        st.session_state.log_lines.append(f"Internal error: {exc}")
        st.session_state.run_status = "error"


def _run_drilldown(bill_month: int):
    import os as _os
    env = _os.environ.copy()
    cmd = [_sys.executable, str(DRILLDOWN_SCRIPT),   # never bare python3
           "--bill-month", str(bill_month), "--fy-start", "2025"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, cwd=str(PROJECT_ROOT), env=env)
        st.session_state.drilldown_log = proc.stdout.splitlines()
        for line in st.session_state.drilldown_log:
            if line.startswith("OUTPUT:"):
                st.session_state.drilldown_path = line[7:].strip()
                break
        st.session_state.drilldown_status = "done" if proc.returncode == 0 else "error"
    except Exception as exc:
        st.session_state.drilldown_log = [f"Error: {exc}"]
        st.session_state.drilldown_status = "error"


def validate_uploaded_xlsx(uploaded_bytes: bytes) -> Optional[str]:
    import tempfile
    from src.parsers.admin_inputs import parse as parse_admin_xlsx
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(uploaded_bytes)
            tmp = f.name
        parse_admin_xlsx(tmp)
        return None
    except Exception as exc:
        return str(exc)
    finally:
        try:
            Path(tmp).unlink()
        except Exception:
            pass


def _stamp_change_log(
    uploaded_bytes: bytes,
    existing_path: Path,
    user: str,
    reason: str,
) -> "tuple[bytes, int]":
    """Diff uploaded xlsx against the existing one, append a Change Log row per cell.

    Returns (new_bytes, n_changes_logged). If the existing file is missing,
    just ensures the Change Log sheet is present and returns the bytes unchanged
    (no diff baseline to compare against).
    """
    import io
    import openpyxl
    from src.parsers.admin_inputs import (
        diff_workbooks,
        ensure_change_log,
        record_change,
    )

    new_wb = openpyxl.load_workbook(io.BytesIO(uploaded_bytes))
    ensure_change_log(new_wb)

    n = 0
    if existing_path.exists():
        old_wb = openpyxl.load_workbook(existing_path)
        for sheet, cell, prev_v, new_v in diff_workbooks(old_wb, new_wb):
            if record_change(new_wb, sheet, cell, prev_v, new_v, user=user, reason=reason):
                n += 1

    buf = io.BytesIO()
    new_wb.save(buf)
    return buf.getvalue(), n


# ─────────────────────────────────────────────────────────────────────
# Cache data collectors
# ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _sp_snapshot_periods() -> frozenset:
    """Months SharePoint holds a published snapshot for.

    One folder listing, cached for five minutes — enough to label the month
    picker honestly without a network call per month per render. Returns an
    empty set when offline or on any failure, which falls the caller back to
    "what's on local disk", the behaviour before this existed.
    """
    if _os.environ.get("WHA_SKIP_SP_REFRESH") == "1" or _os.environ.get("WHA_OFFLINE") == "1":
        return frozenset()
    try:
        from src.hub.datahub import DataHub
        from src.hub.audit import SNAPSHOTS_ROOT
        hub = DataHub.connect(require_sharepoint=False)
        if hub._sp is None:
            return frozenset()
        return frozenset(
            it["name"] for it in hub.list_hub_folder(SNAPSHOTS_ROOT)
            if _re_mod.fullmatch(r"\d{4}-\d{2}", it.get("name", ""))
        )
    except Exception as e:
        print(f"[console] snapshot-period listing unavailable "
              f"({type(e).__name__}: {e}) — month labels fall back to local cache",
              flush=True)
        return frozenset()


def _refresh_cache_from_sp_once_per_session() -> bool:
    """
    Pull the latest SharePoint snapshot into the local cache on the FIRST call
    of each Streamlit session — overwriting any stale local cache.

    Set WHA_SKIP_SP_REFRESH=1 to make this a no-op (render smoke tests, or any
    intentionally-offline run) — the network pull is not part of the render
    contract those tests verify.

    EVOLVED 2026-06-06 from the original "_if_missing" version:
      The original only pulled when CACHE_FILE didn't exist locally. That
      worked for ephemeral containers (Railway baseline deploy) but BROKE on
      deployments with a persistent volume mounted on data/cache/: an old
      cache file would survive redeploys, the if-missing check would short-
      circuit, and the app would render stale data forever.

      New behavior: SP is authoritative. Each fresh Streamlit session, we pull
      from SP once and overwrite local cache. Subsequent renders within the
      same session use the (now-fresh) local cache for speed. If SP is
      unreachable (no creds, network blip, snapshot missing), we fall back
      to whatever's already on local disk — graceful degradation.

    Gated by session_state so we don't hit SP on every render. Returns True if
    a fresh cache (from SP or pre-existing local) is now on disk.
    """
    import os as _os
    if _os.environ.get("WHA_SKIP_SP_REFRESH") == "1" or _os.environ.get("WHA_OFFLINE") == "1":
        return False
    # Keyed PER PERIOD (Phase C): switching the viewed month mid-session must
    # refresh THAT month's snapshot too, and the badge reads the outcome.
    _flag = f"_sp_refresh_done::{CACHE_FILE.name}"
    if st.session_state.get(_flag):
        # Already refreshed this period in this session — cheap path.
        return CACHE_FILE.exists()
    st.session_state[_flag] = True

    try:
        from src.hub.datahub import DataHub
        from src.hub.audit import _load_latest_snapshot
        from reports.membership_performance_tracker.logic.cache import save_scoreboard, scoreboard_from_dict
        hub = DataHub.connect(require_sharepoint=False)
        if hub._sp is None:
            # Dev environment / no SP creds — keep whatever local has.
            st.session_state["_data_source"] = "offline"
            return CACHE_FILE.exists()
        # Derive period from CACHE_FILE name: "scoreboard_2026-03.json" → "2026-03"
        period = CACHE_FILE.stem.replace("scoreboard_", "")
        envelope = _load_latest_snapshot(period, hub)
        if envelope is None or "data" not in envelope:
            # FRESH INSTANCE (found on the first Cloud Run login, 8/8):
            # a blank machine has NO local caches, so the picker lands on
            # the newest fiscal month — which has no snapshot — and this
            # sync used to give up, leaving the console empty forever.
            # Walk BACKWARD to the newest month SharePoint actually has,
            # hydrate it (and its predecessor for month-over-month views),
            # then rerun so the picker re-derives from real data.
            if not list(CACHE_DIR.glob("scoreboard_*.json")):
                import datetime as _dt
                y, m = int(period[:4]), int(period[5:7])
                hydrated = 0
                for _ in range(14):
                    m -= 1
                    if m == 0:
                        y, m = y - 1, 12
                    p = f"{y}-{m:02d}"
                    env = _load_latest_snapshot(p, hub)
                    if env is not None and "data" in env:
                        save_scoreboard(
                            scoreboard_from_dict(env["data"]),
                            CACHE_DIR / f"scoreboard_{p}.json",
                            saved_at=env.get("captured_at"),
                            source="sp-published")
                        hydrated += 1
                        print(f"[console] fresh instance hydrated {p} from SP",
                              flush=True)
                        # walk the WHOLE window like the runner —
                        # stopping at 2 left June's snapshot behind and
                        # the picker honestly said "no data yet" (8/10)
                if hydrated:
                    st.session_state["_data_source"] = "sharepoint"
                    # the picker widget was born with the pre-hydration
                    # option list — drop its state so it re-derives and
                    # defaults to the newest month WITH data (8/8: it
                    # rendered as an empty "Choose an option" box)
                    st.session_state.pop("view_period", None)
                    st.rerun()
            st.session_state["_data_source"] = "offline"
            return CACHE_FILE.exists()
        # Preserve the snapshot's ORIGINAL pull time — a sync must never make
        # old data look freshly pulled (badge honesty, 2026-07-20). And say
        # WHAT this write holds: the SP snapshot is the PUBLISHED post-overlay
        # data, and this sync silently replaces a live pull's pre-overlay save
        # minutes after every pull (2026-07-30: this unmarked overwrite is what
        # sent a false drops-regression hunt through an hour of forensics —
        # this console had been quietly rewriting the cache since Monday).
        save_scoreboard(scoreboard_from_dict(envelope["data"]), CACHE_FILE,
                        saved_at=envelope.get("captured_at"),
                        source="sp-published")
        st.session_state["_data_source"] = "sharepoint"
        print(f"[console] SP cache refreshed for session: {CACHE_FILE.name}", flush=True)
        return True
    except FileNotFoundError:
        # SP has no snapshot yet — fall back to any existing local cache.
        st.session_state["_data_source"] = "offline"
        return CACHE_FILE.exists()
    except Exception as exc:
        # SP unreachable or transient error — keep going with whatever's local.
        # Logged loudly so operators can see it in container logs.
        st.session_state["_data_source"] = "offline"
        print(f"[console] SP cache refresh failed: {exc}", flush=True)
        return CACHE_FILE.exists()


# Backward-compat alias — the original name still surfaces in older code paths
# and in pre-existing instrumentation. Routes to the new implementation.
def _materialize_sp_cache_if_missing() -> bool:
    return _refresh_cache_from_sp_once_per_session()


def _load_cache_fields():
    # Refresh from SP once per Streamlit session (overwrites any stale local
    # cache — important on Railway where data/cache/ may be a persistent
    # volume that survives redeploys with stale content). Subsequent calls
    # within the same session are cheap session_state lookups; only the first
    # call hits SharePoint.
    _refresh_cache_from_sp_once_per_session()
    # DISPLAY READ falls back within the fiscal year (2026-09-03): the viewing
    # month often has no file of its own because the close-aware scheduler
    # names its output by the (lagging) reporting month, while the live FY
    # cache — spanning every month of that year — sits under the prior month's
    # name. Read that instead of returning empty. Same-FY only; never crosses
    # the Oct 1 boundary. WRITE/generate/close paths keep using the exact
    # period CACHE_FILE — this fallback is read-only.
    src = _newest_same_fy_cache(PERIOD)
    if src is None:
        return None
    try:
        return json.loads(src.read_text()).get("fields", {})
    except Exception:
        return None


TERRITORY_ORDER = [
    "EastKing","SouthKing","NorthKing","Pierce","Snohomish",
    "Spokane/NE","Southwest","TKP","Southeast","NorthCentral","Majors/NRA",
]
# FY-to-date columns (Oct-first) for the loaded period. Drops the old Sep-first bug.
MONTHS = _PERIOD.months

# Goal thresholds — fallback values if admin_inputs hasn't been loaded.
# The real values come from data.goal_retention / data.goal_penetration which
# admins set in admin_inputs.yaml / admin_inputs.xlsx.
GOAL_RETENTION_FALLBACK   = DEFAULT_RETENTION_GOAL  # single-sourced constant (#16)
GOAL_PENETRATION_FALLBACK = 0.75


def _goal_threshold(field_name: str, fallback: float) -> float:
    """Average admin-set goal across territories. Falls back to the constant
    if the field isn't populated yet (e.g. no admin inputs loaded)."""
    fields = _load_cache_fields() or {}
    f = fields.get(field_name) or {}
    if isinstance(f, dict):
        # goal_retention is [t][m]; goal_penetration is [t]
        vals = []
        for v in f.values():
            if isinstance(v, (int, float)):
                vals.append(v)
            elif isinstance(v, dict):
                vals.extend(x for x in v.values() if isinstance(x, (int, float)))
        if vals:
            return sum(vals) / len(vals)
    return fallback


def collect_statewide_kpis():
    fields = _load_cache_fields()
    if not fields:
        return None

    def _sum(name):
        f = fields.get(name) or {}
        return sum((f.get(t, {}).get(m) or 0) for t in TERRITORY_ORDER for m in MONTHS
                   if isinstance((f.get(t) or {}).get(m), (int, float)))

    def _avg_ret():
        f = fields.get("avg_retention") or {}
        vals = [v for v in f.values() if isinstance(v, (int, float))]
        return sum(vals) / len(vals) if vals else None

    def _pen_rest():
        act = fields.get("pen_active_restaurant") or {}
        mkt = fields.get("pen_market_restaurant") or {}
        a = sum(v for v in act.values() if isinstance(v, (int, float)))
        m = sum(v for v in mkt.values() if isinstance(v, (int, float)))
        return a / m if m else None

    bills_t = sum((fields.get("hosp_bills_target") or {}).get(t, {}).get(CURRENT_MONTH, 0) or 0
                  for t in TERRITORY_ORDER)
    bills_nt = sum((fields.get("hosp_bills_non_target") or {}).get(t, {}).get(CURRENT_MONTH, 0) or 0
                   for t in TERRITORY_ORDER)

    return {
        "ytd_revenue":   _sum("revenue"),
        "new_members":   _sum("new_members"),
        "avg_retention": _avg_ret(),
        "pen_restaurant": _pen_rest(),
        "billables_target": bills_t,
        "billables_non_target": bills_nt,
    }


def collect_territory_status():
    fields = _load_cache_fields()
    if not fields:
        return []
    rev   = fields.get("revenue") or {}
    retn  = fields.get("avg_retention") or {}
    rep   = fields.get("rep_name") or {}
    pa    = fields.get("pen_active_restaurant") or {}
    pm    = fields.get("pen_market_restaurant") or {}
    bt    = fields.get("hosp_bills_target") or {}
    bnt   = fields.get("hosp_bills_non_target") or {}
    bal   = fields.get("allied_bills") or {}
    out = []
    for t in TERRITORY_ORDER:
        ytd = sum((rev.get(t, {}).get(m) or 0) for m in MONTHS)
        avg = retn.get(t)
        a = pa.get(t); m = pm.get(t)
        pen = (a/m) if m else None
        out.append({
            "territory":     t,
            "rep":           rep.get(t, ""),
            "ytd_revenue":   ytd,
            "avg_retention": avg,
            "pen_restaurant": pen,
            "billables_target":      (bt.get(t)   or {}).get(CURRENT_MONTH),
            "billables_non_target":  (bnt.get(t)  or {}).get(CURRENT_MONTH),
            "billables_allied":      (bal.get(t)  or {}).get(CURRENT_MONTH),
        })
    return out


def collect_statewide_trends():
    fields = _load_cache_fields()
    if not fields:
        return None
    def _sum_across(name):
        f = fields.get(name) or {}
        out = []
        for m in MONTHS:
            total = 0; has_any = False
            for t in TERRITORY_ORDER:
                v = (f.get(t) or {}).get(m) if isinstance(f.get(t), dict) else None
                if isinstance(v, (int, float)):
                    total += v; has_any = True
            out.append(total if has_any else None)
        return out
    return {
        "months":                    MONTHS,
        "revenue":                   _sum_across("revenue"),
        "revenue_target":            _sum_across("revenue_target"),
        "revenue_non_target":        _sum_across("revenue_non_target"),
        "new_members":               _sum_across("new_members"),
        "new_members_target":        _sum_across("new_members_target"),
        "new_members_non_target":    _sum_across("new_members_non_target"),
        "drops_target":              _sum_across("drops_target"),
        "drops_non_target":          _sum_across("drops_non_target"),
        "drops_revenue_target":      _sum_across("drops_revenue_target"),
        "drops_revenue_non_target":  _sum_across("drops_revenue_non_target"),
    }


def collect_run_alerts():
    alerts_path = OUTPUT_DIR / "last_run_alerts.json"
    if not alerts_path.exists():
        return []
    try:
        alerts = json.loads(alerts_path.read_text())
    except Exception:
        return []
    items = []
    bob = alerts.get("bob_accounts") or {}
    if bob:
        items.append({"kind": "Black-Owned Business (BOB) enrollments",
                      "count": sum(len(v) for v in bob.values()),
                      "summary": "Black-Owned Business members enrolled this month — "
                                 "dues are comped, so the rep may need a manual revenue "
                                 "credit. (This is the BOB initiative, not the "
                                 "“Best of Both” 2-year promo.)",
                      "detail": bob})
    rw = alerts.get("retention_watch") or []
    if rw:
        items.append({"kind": "Retention Watch", "count": len(rw),
                      "summary": f"{len(rw)} territory(ies) below their retention goal.",
                      "detail": rw})
    ng = alerts.get("no_goal") or []
    if ng:
        items.append({"kind": "Missing Goals", "count": len(ng),
                      "summary": "Territories with revenue but no goal set.",
                      "detail": ng})
    return items


def _log_report_run_start(report: str, mode: str, source: str) -> None:
    """Record an in-process report run in the shared activity log.

    The MPR logs itself because it runs as a subprocess; dues runs in-process
    and so logged NOTHING — which is why Recent Activity showed a dues run as
    "Membership Performance Report" (the parser's fallback label) or not at
    all. Never let a logging failure kill a successful run.
    """
    try:
        from src.scheduler import write_run_started_banner
        write_run_started_banner(SCHEDULED_RUN_LOG, mode, source, report=report)
    except Exception as exc:
        print(f"[console] run-log write failed: {exc}", flush=True)


def _log_report_run_end(rc: int) -> None:
    try:
        from src.scheduler import write_run_finished_banner
        write_run_finished_banner(SCHEDULED_RUN_LOG, rc)
    except Exception as exc:
        print(f"[console] run-log write failed: {exc}", flush=True)


def collect_recent_runs(limit=5):
    """Parse the scheduled_run.log for recent run summaries (when, mode, source, status)."""
    if not SCHEDULED_RUN_LOG.exists():
        return []
    from src.scheduler import parse_recent_runs
    # `report=` is post-2026-07-27 (the log predates the platform being
    # multi-report). Entries without it ARE MPR runs — that was the only
    # writer — so the fallback label is honest, not a guess.
    runs = parse_recent_runs(SCHEDULED_RUN_LOG.read_text(errors="ignore"),
                             default_report=REPORT_NAME)
    # Orphaned "running" entries (2026-07-22, Jiho spotted a Jul-20 ghost):
    # a run whose process died (crash/kill) never writes its finish line and
    # would show "running" forever. Any run that ISN'T the newest can't still
    # be running (a newer one started after it) — mark those "interrupted".
    # The newest entry keeps "running" only while a pull process is actually
    # alive; otherwise it too is marked interrupted.
    for r in runs[:-1]:
        if r.get("status") == "running":
            r["status"] = "interrupted"
    if runs and runs[-1].get("status") == "running":
        import subprocess as _sp
        alive = _sp.run(["pgrep", "-f", "runner.py"],
                        capture_output=True).returncode == 0
        if not alive:
            runs[-1]["status"] = "interrupted"
    return list(reversed(runs))[:limit]


# ─────────────────────────────────────────────────────────────────────
# Sidebar — folder-style nav
# ─────────────────────────────────────────────────────────────────────
_ensure_scheduler_running()

def nav_button(label, key, active_key, indent=False):
    is_active = (st.session_state.nav == active_key)
    style = "primary" if is_active else "secondary"
    container_class = "sb-sub" if indent else ""
    if indent:
        st.markdown(f"<div class='{container_class}'>", unsafe_allow_html=True)
    if st.button(label, key=f"nav_{key}", use_container_width=True, type=style):
        st.session_state.nav = active_key
        st.rerun()
    if indent:
        st.markdown("</div>", unsafe_allow_html=True)


with st.sidebar:
    # Embed the WHA logo via base64 so styling sits inside .sb-brand
    # (avoids st.image's own container which breaks the bordered card).
    import base64 as _b64
    if _WHA_LOGO.exists():
        _logo_b64 = _b64.b64encode(_WHA_LOGO.read_bytes()).decode()
        st.markdown(
            f"<div class='sb-brand'>"
            f"<img src='data:image/png;base64,{_logo_b64}' alt='Washington Hospitality Association'/>"
            f"<div class='sb-brand-subtitle'>Membership Data <span class='accent'>Platform</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        # Fallback if the logo file isn't on disk
        st.markdown(
            "<div class='sb-brand'>"
            "<div class='sb-brand-subtitle'>Washington Hospitality<br>Membership Data <span class='accent'>Platform</span></div>"
            "</div>",
            unsafe_allow_html=True,
        )

    # ── What you're looking at (Phase C): month picker + honesty badge ──────
    _BADGE_CSS = ("color:#9aa0a8;font-size:0.78rem;line-height:1.5;"
                  "padding:2px 10px 8px;")
    if not AVAILABLE_PERIODS:
        st.markdown(f"<div style='{_BADGE_CSS}'>No report data yet — run a report "
                    f"from the Control Panel.</div>", unsafe_allow_html=True)
    else:
        if PERIOD_PINNED:
            st.markdown(f"<div style='{_BADGE_CSS}'>📌 Pinned to "
                        f"<b>{_pretty_period(PERIOD)}</b> (override)</div>",
                        unsafe_allow_html=True)
        elif len(AVAILABLE_PERIODS) > 1:
            # refresh BEFORE the labels compute — on a session's first
            # render the labels used to say "no data yet" about a month
            # the refresh was about to materialize (8/10 screenshot)
            _refresh_cache_from_sp_once_per_session()
            _sp_periods = _sp_snapshot_periods()
            def _period_label(p):
                # A month has data if it's cached HERE or published on
                # SharePoint. Local-only was a lie on any fresh container:
                # the session refresh hydrates the SELECTED period only, so
                # every other month read "no data yet" until you generated it
                # — which is exactly what a deploy left behind (Jiho 8/13).
                # ...or a same-fiscal-year cache/snapshot covers it: the live
                # FY scoreboard spans every month of its year, so a month
                # with no file of its own is still viewable (2026-09-03).
                _fy = _fy_start_of(p)
                has = ((CACHE_DIR / f"scoreboard_{p}.json").exists()
                       or p in _sp_periods
                       or _newest_same_fy_cache(p) is not None
                       or any(_fy_start_of(sp) == _fy for sp in _sp_periods))
                return _pretty_period(p) + ("" if has else "  · no data yet")
            st.selectbox("Viewing month", AVAILABLE_PERIODS,
                         index=(AVAILABLE_PERIODS.index(PERIOD)
                                if PERIOD in AVAILABLE_PERIODS else 0),
                         key="view_period", format_func=_period_label)
        # Keep the per-period SP refresh side effect (cache sync); the badge
        # line itself was removed per Jiho (2026-07-20) — freshness lives on
        # the Data & Schedule page.
        _refresh_cache_from_sp_once_per_session()

    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    nav_button("Control Panel", "control", "control")

    st.markdown("<div class='sb-section'>Reports</div>", unsafe_allow_html=True)

    # Membership Performance Report — folder with two subsections:
    #   Sub-Reports: Retention Detail Report, Penetration (separate report engines)
    #   Views:       Summary, Analytics, Tracker File (different views of the MPR)
    mpr_active = (st.session_state.nav.startswith("mpr.")
                  or st.session_state.nav.startswith("dd.")
                  or st.session_state.nav.startswith("pen."))
    if st.session_state.nav.startswith("mpr."):
        parent_target = st.session_state.nav
    elif st.session_state.nav.startswith(("dd.", "pen.")):
        # Already inside an MPR sub-report — keep the parent pointing at it
        parent_target = "mpr.tracker"
    else:
        parent_target = "mpr.tracker"
    nav_button("Membership Performance Report", "mpr_root", parent_target)
    if mpr_active:
        # Sub-reports removed 8/10 (Jiho): Penetration duplicated a subset
        # of the main report; Retention Detail's member-level rows now live
        # in the Members tab + Trace page. Pages stay dormant; repo folders
        # leave at packaging.

        st.markdown("<div class='sb-subsection'>Views</div>", unsafe_allow_html=True)
        nav_button("Report File",   "mpr_trk", "mpr.tracker",   indent=True)
        nav_button("Trace a Number", "mpr_trace", "mpr.trace",   indent=True)
        nav_button("Adjust a Number", "mpr_adjust", "mpr.adjust", indent=True)
        # Close the MPR group. Without this the "Views" caption ran on and
        # swallowed the next top-level report — expanding MPR made Dues
        # Analysis look like a fourth MPR view (Jiho, 7/27).
        st.markdown("<div class='sb-group-end'></div>", unsafe_allow_html=True)

    # Dues Analysis surfaces removed 8/10 (Jiho) — plumbing stays
    # dormant; the folder leaves at packaging.

    st.markdown("<div class='sb-section'>System</div>", unsafe_allow_html=True)
    nav_button("Admin Inputs",    "admin", "admin")
    nav_button("Data & Schedule", "sched", "schedule")

    # Connection footer — inline at bottom of sidebar (not absolutely positioned)
    sp_ok, sp_label = sharepoint_status()
    color = "#90d000" if sp_ok else "#808184"
    st.markdown(
        f"<div class='sb-footer'>"
        f"<span class='sb-status-dot' style='background:{color};'></span>"
        f"{sp_label}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────
# Shared rendering helpers
# ─────────────────────────────────────────────────────────────────────
def kpi_card(col, label, value, meta="", status=""):
    css = f"kpi-{status}" if status else ""
    with col:
        st.markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value {css}'>{value}</div>"
            f"<div class='kpi-meta'>{meta}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def section(text):
    st.markdown(f"<div class='section-label'>{text}</div>", unsafe_allow_html=True)


def chart_title(text):
    """Bigger, mixed-case heading used above charts (vs the small uppercase
    section() label used elsewhere)."""
    st.markdown(f"<div class='chart-title'>{text}</div>", unsafe_allow_html=True)


def _threshold_bar_chart(df, value_col, threshold, *, x_domain, x_format,
                          tooltip_label, height=320):
    """
    Build a horizontal bar chart that colors bars green ≥threshold, orange below.

    Implementation pattern: split the data into two sub-frames (on-track,
    below), render EACH as its own chart with a static mark color, and layer
    them. Vega-Lite's encoding-level color scale was failing intermittently
    in Streamlit's wrapper — static mark color always renders. The y-axis
    sort order is precomputed from the full data so both layers align.
    """
    import altair as alt
    import pandas as pd
    df = df.copy()
    df = df.sort_values(value_col, ascending=False)
    sort_order = df["territory"].tolist()

    on_track = df[df[value_col] >= threshold]
    below    = df[df[value_col] <  threshold]

    def _layer(sub_df, color):
        return alt.Chart(sub_df).mark_bar(color=color, size=18, cornerRadiusEnd=3).encode(
            x=alt.X(f"{value_col}:Q",
                    scale=alt.Scale(domain=x_domain),
                    axis=alt.Axis(format=x_format, title=None)),
            y=alt.Y("territory:N", sort=sort_order, title=None),
            tooltip=[
                alt.Tooltip("territory:N", title="Territory"),
                alt.Tooltip(f"{value_col}:Q", title=tooltip_label, format=".1%"),
            ],
        )

    layers = []
    if not on_track.empty:
        layers.append(_layer(on_track, "#90d000"))   # WHA green
    if not below.empty:
        layers.append(_layer(below,    "#f0b010"))   # WHA orange

    chart = (alt.layer(*layers) if len(layers) > 1 else layers[0])
    return chart.properties(height=height).configure_view(
        stroke=None
    ).configure_axis(
        labelFont="Inter", titleFont="Inter",
        labelColor="#58595b", gridColor="#f0f2f5", domain=False,
    )


def page_header(eyebrow, title, subtitle=""):
    st.markdown(f"<div class='page-eyebrow'>{eyebrow}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='page-header'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='page-sub'>{subtitle}</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# Month close — the two-phase ITD design (built with Jiho 2026-08-03).
# One human event per month: after running ITD in the CRM, pick the date it
# was run and press Close. Retention freezes from the last nightly snapshot
# BEFORE that morning (pre-ITD — ITD's write-offs would otherwise shrink the
# billed count and inflate the %); everything else re-captures fresh, after
# ITD, via the live pull this triggers. The month's numbers then lock.
# ─────────────────────────────────────────────────────────────────────
def render_month_close_panel():
    import datetime as _dtm
    from reports.membership_performance_tracker.logic import month_close as _mc
    from src.scheduler import CLOSE_ANCHOR

    today = _dtm.date.today()
    # VIEWED-MONTH AWARE (Jiho 8/6: "the July message persists when I select
    # other months"). The panel follows the month picker: a closed viewed
    # month shows ITS lock; the current month says it is still collecting;
    # an ended-but-unclosed month offers the close. When the viewed month
    # predates the close system, fall back to the close system's current
    # business (oldest unclosed ended month, else latest closed).
    viewed = PERIOD
    cur_period = today.strftime("%Y-%m")
    # STRICTLY the viewed month (Jiho 8/10: "each shows its month" — the
    # old fallback made a May view talk about July's close).
    if viewed < CLOSE_ANCHOR:
        section("Month Close")
        st.markdown(
            f"<div style='font-size:0.85rem;color:#808184;'>"
            f"<b>{_pretty_period(viewed)} predates the monthly close "
            f"system.</b> Its numbers are locked from the FY25-26 capture — "
            f"there is nothing to close here.</div>",
            unsafe_allow_html=True)
        return
    if viewed > cur_period:
        section("Month Close")
        st.markdown(
            f"<div style='font-size:0.85rem;color:#808184;'>"
            f"<b>{_pretty_period(viewed)} hasn't started</b> — nothing to "
            f"close yet.</div>",
            unsafe_allow_html=True)
        return
    # FILL-IF-MISSING (8/10): a fresh machine may not have hydrated this
    # month's close record — ask SharePoint before deciding anything (a
    # blank instance once offered to re-close sealed July).
    if not _mc.is_closed(viewed):
        try:
            from src.hub.datahub import DataHub as _DH
            _h = _DH.connect(require_sharepoint=False)
            if getattr(_h, "_sp", None) is not None:
                _b = _h.read_hub_file(
                    "Reports/Membership Performance Report/Data/closes/"
                    f"close_{viewed}.json")
                _dst = _mc.CLOSES_DIR / f"close_{viewed}.json"
                _dst.parent.mkdir(parents=True, exist_ok=True)
                _dst.write_bytes(_b)
        except Exception:
            pass                     # genuinely open — no record anywhere
    prev = viewed

    section("Month Close")
    closing_label = _pretty_period(prev)

    def _hub_or_none():
        try:
            from src.hub.datahub import DataHub
            hub = DataHub.connect(require_sharepoint=False)
            return hub if getattr(hub, "_sp", None) is not None else None
        except Exception:
            return None

    def _freeze_and_pull(itd_date, itd_time=None):
        try:
            doc = _mc.freeze(prev, itd_date, hub=_hub_or_none(),
                             itd_time=itd_time)
        except _mc.NoCleanSnapshot as e:
            st.error(str(e))
            return
        except _mc.StaleCapture as e:
            # the post-ITD photo gate (8/10) — must read as guidance, not
            # a crash: the operator's fix is to wait for tonight's pull
            st.error(str(e))
            st.info("Nothing was closed. The nightly run at 2 AM captures "
                    "the fresh reports; close the month after it lands.")
            return
        except _mc.AlreadyClosed as e:
            st.error(str(e))
            st.rerun()               # record restored — panel re-derives
            return
        if doc["warnings"]:
            for w in doc["warnings"]:
                st.error(f"⚠️ {w}")
            st.error("These warnings are saved on the month's record.")
        st.success(f"{closing_label} numbers saved from "
                   f"{doc['source_snapshot']} — starting the fresh pull for "
                   f"billables, drops and penetration (after-ITD picture).")
        from src.scheduler import trigger_refresh
        # the after-ITD capture must pull THE MONTH JUST CLOSED (D2 finding
        # 12: default targeting skipped it, so auto-seal never fired from
        # this flow — the panel's "locks automatically" promise was empty)
        if trigger_refresh("live", period=prev) == 0:
            # The month IS frozen at this point — only the after-ITD capture
            # did not start. Say exactly that, or it reads as a failed close.
            st.warning(f"{closing_label} is frozen, but the after-ITD pull "
                       f"did not start — one is already running. Trigger a "
                       f"full refresh once it finishes.")
        st.rerun()

    if not _mc.is_closed(prev):
        if prev == cur_period:
            st.markdown(
                f"<div style='font-size:0.85rem;color:#b0752b;'>"
                f"<b>{closing_label} hasn't ended — closing now freezes it "
                f"early, with today's picture.</b></div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div style='font-size:0.85rem;color:#808184;'>"
                f"<b>{closing_label} is still open.</b> After accounting "
                f"finishes posting and ITD has been run in the CRM, close "
                f"the month here. Retention keeps the picture from the "
                f"night <i>before</i> ITD (so members who didn't pay still "
                f"show as billed); everything else is re-captured fresh, "
                f"after ITD.</div>",
                unsafe_allow_html=True)
        c1, c1b, c2 = st.columns([1, 1, 1])
        with c1:
            itd_date = st.date_input("What day was ITD run?", value=today,
                                     max_value=today, key="close_itd_date")
        with c1b:
            itd_time = st.time_input("Around what time? (optional)",
                                     value=_dtm.time(6, 0),
                                     key="close_itd_time")
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(f"Close {closing_label}", type="primary",
                         key="close_month_btn"):
                st.session_state["close_pending"] = str(itd_date)
        if st.session_state.get("close_pending"):
            pend = _dtm.date.fromisoformat(st.session_state["close_pending"])
            try:
                chosen = _mc.choose_snapshot(
                    _mc.SNAPSHOTS_ROOT / prev, pend,
                    itd_time=st.session_state.get("close_itd_time"),
                    hub=_hub_or_none())
                st.info(f"Retention will be saved as of **{chosen.name}** — "
                        f"the last pull before ITD on {pend}. This locks "
                        f"{closing_label}.")
                if st.button("Confirm — close the month", type="primary",
                             key="close_confirm_btn"):
                    st.session_state.pop("close_pending", None)
                    _freeze_and_pull(pend,
                                     st.session_state.get("close_itd_time"))
            except _mc.NoCleanSnapshot as e:
                st.error(str(e))
                st.session_state.pop("close_pending", None)
    else:
        doc = _mc.load_close(prev) or {}
        itd_when = doc.get("itd_date", "?")
        if doc.get("itd_time"):
            itd_when += f" around {doc['itd_time']}"
        if doc.get("sealed"):
            st.success(f"🔒 {closing_label} is closed — every number is "
                       f"locked. Retention keeps the picture from the night "
                       f"before ITD (run {itd_when}); everything else is "
                       f"locked from the after-ITD capture. Re-running "
                       f"{closing_label} can change how the report looks, "
                       f"never its numbers.")
        else:
            st.success(f"🔒 {closing_label} is closed — retention is locked "
                       f"from the night before ITD (run {itd_when}). The "
                       f"rest locks automatically when the after-ITD pull "
                       f"finishes.")
        if doc.get("warnings"):
            st.warning("This close carries warnings — open the record on "
                       "SharePoint (Reports › Membership Performance Report "
                       "› Closes) before trusting the month.")
        if doc.get("amendments"):
            with st.expander(f"Change log ({len(doc['amendments'])}) — every "
                             f"change since the lock, on the record"):
                for a in doc["amendments"]:
                    st.markdown(f"- **{a.get('at', '?')[:16]}** — {a.get('what')}")
        st.caption("A close made with wrong inputs is repairable — every night's photos live in the snapshot archive, and the repair procedure is in the SOP. It is deliberately not a button.")


# ─────────────────────────────────────────────────────────────────────
# Page: Control Panel
# ─────────────────────────────────────────────────────────────────────
def page_control_panel():
    page_header("Home", "Control Panel",
                "Generate reports and check system status.")

    # System bar — platform-wide signals only. "Last Tracker" is MPR-specific
    # and now lives on the Membership Performance Report page subheader.
    st.markdown(
        f"<div class='status-bar'>"
        f"<span><b>SLX Cache</b> {_last_slx_pull_age()}</span>"
        f"<span><b>Admin Inputs</b> {_admin_age()}</span>"
        f"<span><b>SharePoint</b> {'connected' if sharepoint_status()[0] else 'offline'}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Report selection — single row with checkbox on left of the label.
    # Retention Detail Report is intentionally NOT here; it's a sub-report of
    # MPR, runnable from the sidebar (Reports › Membership Performance ›
    # Sub-Reports › Retention Detail Report).
    render_pull_progress()

    section("Select Reports")

    def _report_row(key, title, default=False):
        c_check, c_label = st.columns([0.07, 0.93], vertical_alignment="center")
        with c_check:
            st.markdown("<div class='report-row-check'>", unsafe_allow_html=True)
            checked = st.checkbox(" ", value=default, key=key,
                                  label_visibility="collapsed")
            st.markdown("</div>", unsafe_allow_html=True)
        with c_label:
            st.markdown(
                f"<div class='report-row'>"
                f"<div class='report-row-title'>{title}</div></div>",
                unsafe_allow_html=True,
            )
        return checked

    run_mpr = _report_row("sel_mpr", "Membership Performance Report", default=True)
    if run_mpr and _newest_same_fy_cache(PERIOD) is None:
        st.caption(f"⚠️ No MPR data for {_pretty_period(PERIOD)} yet — a cache "
                   f"run will create it.")
    run_dues = False   # dues surfaces removed 8/10 — row not rendered

    # Which month will Dues actually produce? Say it BEFORE the click. The
    # viewing month drives it; when Dues can't serve that month we refuse and
    # explain, rather than silently generating a different one (Jiho, 7/27:
    # picker said July, spinner said June).
    dues_edition, dues_block = PERIOD, ""
    if run_dues:
        _eds = _dues_editions()
        if PERIOD in _eds:
            st.caption(f"Edition: **{_pretty_period(PERIOD)}**")
        else:
            dues_edition = None
            dues_block = (
                f"Dues Analysis has no edition for {_pretty_period(PERIOD)} — "
                f"an edition covers a COMPLETE month, so the newest is "
                f"{_pretty_period(_eds[0])}. Switch the viewing month to run it.")
            st.caption(f"⚠️ {dues_block}")

    mode = "cache"
    if run_dues and not run_mpr:
        # Dues has no cache/live choice: its source of record is the nightly
        # CRM export, fetched from SLX's archive. Say so, rather than leaving
        # the Data Source section silently absent.
        st.caption("Source: last night's scheduled CRM exports (seconds, no "
                   "live pull).")
    if run_mpr:
        section("Data Source")
        mode_choice = st.radio(
            "mode", label_visibility="collapsed", horizontal=True,
            options=["Cache (fast, ~5s)",
                     f"Live SLX (full refresh, {_live_pull_estimate()})"],
            index=0, key="ctrl_mode",
        )
        mode = "cache" if "Cache" in mode_choice else "live"
        if mode == "cache" and not CACHE_FILE.exists():
            st.warning("No cache exists — switch to Live SLX or run a refresh from Data & Schedule.")

    st.markdown("<br>", unsafe_allow_html=True)
    col_run, _ = st.columns([1, 3])
    with col_run:
        if st.button("Generate Selected Reports", type="primary",
                     use_container_width=True,
                     disabled=not (run_mpr or run_dues)):
            # Dues first (fast, synchronous) so a live MPR pull backgrounding
            # afterward doesn't strand it.
            if run_dues and dues_edition is None:
                st.error(dues_block)
            elif run_dues:
                from reports.dues_analysis.runner import generate as generate_dues
                ed = dues_edition
                with st.spinner(f"Generating Dues Analysis ({_pretty_period(ed)})…"):
                    _log_report_run_start(DUES_REPORT_NAME, "report", "console")
                    try:
                        generate_dues(_dues_hub(), ed)
                        _log_report_run_end(0)
                        st.success(f"Dues Analysis {_pretty_period(ed)} generated.")
                    except Exception as e:
                        _log_report_run_end(1)
                        st.error(f"Dues run failed: {type(e).__name__}: {e}")
            if run_mpr and mode == "live":
                # 2026-07-22: a 2-hour pull must NEVER block the page — run in
                # the background (same path as the scheduler) and show live
                # progress; the tab can close and the pull survives.
                from src.scheduler import trigger_refresh
                if trigger_refresh("live") == 0:
                    st.warning("A pull is already running. Yours was not "
                               "started — wait for the current one to finish.")
                else:
                    st.rerun()
            elif run_mpr:
                with st.spinner("Generating from cache..."):
                    run_pipeline_sync(mode)
                # STAY on the Control Panel (Jiho, 7/27): the user didn't
                # navigate, so the app must not navigate for them. Results are
                # one click away in the sidebar and linked below.
                st.rerun()
            elif run_dues:
                st.rerun()
    if not (run_mpr or run_dues):
        st.caption("Select a report above.")

    render_month_close_panel()

    # Latest outputs — quick access to the most recent generated report files.
    # Same pattern as Admin Inputs (downloadable from its own page AND here).
    latest_mpr = _resolve_output_file()
    if latest_mpr.is_file():
        section("Latest Outputs")
        col_a, col_b = st.columns([1, 2])
        with col_a:
            with open(latest_mpr, "rb") as f:
                st.download_button(
                    "Download Report",
                    data=f.read(),
                    file_name=latest_mpr.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="ctrl_mpr_tracker_dl",
                )
        with col_b:
            sp_note = (
                f"Generated {relative_age(OUTPUT_FILE)} · {size_str(OUTPUT_FILE)} · "
                f"<span style='color:#5a8a00;'>also on SharePoint</span>"
                if sharepoint_status()[0]
                else f"Generated {relative_age(OUTPUT_FILE)} · {size_str(OUTPUT_FILE)} · local only"
            )
            st.markdown(
                f"<div style='font-size:0.82rem;color:#808184;padding-top:0.55rem;'>"
                f"<b>Membership Performance Report</b><br/>{sp_note}"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Recent runs
    section("Recent Activity")
    runs = collect_recent_runs(limit=5)
    if runs:
        for r in runs:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                when = ts.strftime("%b %-d, %-I:%M %p")
            except Exception:
                when = r["timestamp"]
            status_pill = {
                "done":    "<span class='pill pill-green'>done</span>",
                "running": "<span class='pill pill-blue'>running</span>",
                "interrupted": "<span class='pill pill-grey'>interrupted</span>",
                "error":   "<span class='pill pill-red'>error</span>",
            }.get(r["status"], "<span class='pill pill-grey'>—</span>")
            source_badge = (
                f"<span class='run-mode' style='color:#808184;'>· {r.get('source', 'scheduler')}</span>"
            )
            st.markdown(
                f"<div class='run-row'>"
                f"<span class='run-when'>{when}</span>"
                f"<span class='run-name'>{r['report']}</span>"
                f"<span class='run-mode'>· {r['mode']}</span>"
                f"{source_badge}"
                f"<span style='margin-left:auto;'>{status_pill}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No runs yet.")


# ─────────────────────────────────────────────────────────────────────
# MPR pages — Snapshot / Visuals / Results
# ─────────────────────────────────────────────────────────────────────
def _mpr_subheader():
    cache_when = _data_age() if CACHE_FILE.exists() else "no cache"
    return (f"FY {_PERIOD.fiscal_year} · through {_pretty_period(PERIOD)} · "
            f"pulled {cache_when}")




def _stamp_generated_at(dst: Path, sp_name: str, hub=None, sp_path: str = "") -> None:
    """Set the downloaded workbook's mtime to when it was GENERATED.

    A download is not a generation. Without this the file's mtime is the moment
    we fetched it, and every "Generated N ago" on the console reads N from that
    — so a fresh instance reported a two-hour-old workbook as 44 seconds old
    (8/14), and after a failed nightly it would report yesterday's workbook as
    brand new. That is the one number a reader checks to answer "did last night
    run", and it could not fail.

    The run stamps its own name: `..._20260814-122058.xlsx`. That is the
    generation time and it needs no network. FINAL copies carry no stamp, so
    fall back to SharePoint's own lastModifiedDateTime; if neither is available
    the mtime is left alone rather than invented.
    """
    import os as _os
    import re as _re
    m = _re.search(r"(\d{8})-(\d{6})", sp_name or "")
    when = None
    if m:
        try:
            when = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            when = None
    if when is None and hub is not None and sp_path:
        try:
            folder, _, leaf = sp_path.rpartition("/")
            for item in hub.list_hub_folder(folder):
                if str(item.get("name") or "") == leaf:
                    hours = _iso_hours_ago(item.get("lastModifiedDateTime"))
                    if hours is not None:
                        when = datetime.now() - timedelta(hours=hours)
                    break
        except Exception:
            pass
    if when is None:
        return
    try:
        ts = when.timestamp()
        _os.utime(dst, (ts, ts))
    except OSError:
        pass


def _hydrate_output_workbook(period: str) -> None:
    """Fill-if-missing: a fresh cloud instance never built past months, but
    their workbooks live in the SP dated Output folders — probe the last
    30 days of folders for this period's file (8/10, Jiho's July page)."""
    fname = f"Membership_Performance_Report_{period}.xlsx"
    dst = OUTPUT_DIR / fname
    if dst.exists():
        return
    try:
        from src.hub.datahub import DataHub
        hub = DataHub.connect(require_sharepoint=False)
        if getattr(hub, "_sp", None) is None:
            return
        base = f"Reports/{REPORT_NAME}/Output/{period}"
        try:                             # the locked final wins
            b = hub.read_hub_file(f"{base}/FINAL/{fname}")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
            st.session_state[f"wb_prov_{period}"] = "FINAL"
            _stamp_generated_at(dst, fname, hub, f"{base}/FINAL/{fname}")
            print(f"[console] output workbook hydrated from SP (FINAL/{period})",
                  flush=True)
            return
        except Exception:
            pass
        import re as _re
        entries = hub.list_hub_folder(f"{base}/Runs")
        # Runs/<YYYY-MM-DD>/ day folders (8/10); legacy flat files still
        # readable during the transition. Newest day, newest stamp within.
        days = sorted((e.get("name", "") for e in entries
                       if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.get("name", ""))),
                      reverse=True)
        newest = None
        for day in days:
            files = [x.get("name", "")
                     for x in hub.list_hub_folder(f"{base}/Runs/{day}")
                     if x.get("name", "").endswith(".xlsx")]
            if files:                    # timestamps sort lexically
                newest = f"{day}/{sorted(files)[-1]}"
                break
        if newest is None:
            flat = [e.get("name", "") for e in entries
                    if e.get("name", "").endswith(".xlsx")]
            if flat:
                newest = sorted(flat)[-1]
        if newest:
            b = hub.read_hub_file(f"{base}/Runs/{newest}")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
            st.session_state[f"wb_prov_{period}"] = f"Runs/{newest}"
            _stamp_generated_at(dst, newest, hub, f"{base}/Runs/{newest}")
            print(f"[console] output workbook hydrated from SP "
                  f"(Runs/{newest})", flush=True)
    except Exception:
        pass                            # page shows its honest empty state


def page_mpr_tracker():
    page_header("Membership Performance Report",
                "Report File", _mpr_subheader())

    _hydrate_output_workbook(PERIOD)
    section("Download")
    output_path = Path(st.session_state.output_path or _resolve_output_file())
    if output_path.is_file():
        with open(output_path, "rb") as f:
            st.download_button(
                "Download Report",
                data=f.read(),
                file_name=output_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                key="mpr_tracker_dl",
            )
        _verb = ("Fetched" if st.session_state.get(f"wb_prov_{PERIOD}")
                 else "Generated")
        st.text(f"{_verb} {relative_age(output_path)} · {size_str(output_path)}")
        if sharepoint_status()[0]:
            sp_versioned = _sp_tracker_versioned_path()
            st.markdown(
                f"<div style='font-size:0.82rem;color:#808184;margin-top:0.5rem;line-height:1.6;'>"
                f"Also saved to SharePoint at "
                f"<code style='font-size:0.78rem;background:#f5f6f8;padding:1px 6px;border-radius:4px;'>"
                f"{sp_versioned}"
                f"</code></div>",
                unsafe_allow_html=True,
            )
    else:
        st.text("No report generated yet. Run from Control Panel.")

    # "Findings from Last Run" removed 8/10 (Jiho): duplicated what
    # the workbook goal colors + flags tab already show.
        section("Run Log")
        with st.expander("Show log", expanded=False):
            # st.text so dollars don't render as math
            st.text("\n".join(st.session_state.log_lines[-80:]))


# ─────────────────────────────────────────────────────────────────────
# Penetration Report — sub-report of MPR
# ─────────────────────────────────────────────────────────────────────


def page_mpr_trace():
    """Trace a Number — a published cell to its member list (ruled 8/6).

    Reads the receipts the pipeline itself produced; shows the members
    behind the number, the plain-words rules that shape it, and a
    conservation check: the members must add up to the published value.
    """
    import pandas as _pd          # top of the function: the corrections block
                                  # below the verdict strip uses it, and a
                                  # later local import makes _pd unbound here
    from reports.membership_performance_tracker.logic import trace as _tr
    from reports.membership_performance_tracker.metric_registry import (
        REGISTRY, RULES)

    page_header("Membership Performance Report", "Trace a Number",
                "Pick a number; see the members behind it and the rules "
                "that shape it.")

    periods = sorted((p.stem.replace("receipts_", "")
                      for p in (PROJECT_ROOT / "data" / "receipts").glob("receipts_2*.json")),
                     reverse=True)
    if not periods:
        st.info("No receipts yet — they are captured by every live pull.")
        return

    c1, c2, c3, c4 = st.columns([1, 1.2, 1.2, 0.8])
    with c1:
        period = st.selectbox("Which report?", periods, key="trace_period",
                              format_func=lambda p: f"{_pretty_period(p)} report")
    FAMILY_LABELS = {"Retention": "Retention",
                     "Drops": "Drops",
                     "Billables": "Billables",
                     "New Members / New Sales": "New sales",
                     "Penetration": "Penetration"}
    with c2:
        family = st.selectbox("Number family", list(FAMILY_LABELS),
                              format_func=FAMILY_LABELS.get, key="trace_family")
    try:
        rows, _f = _tr._load(period)
    except Exception as exc:
        st.error(f"Could not read the receipts for {period}: {exc}")
        return
    terrs = sorted({r["territory"] for r in rows
                    if r.get("metric") == family and r.get("territory")})
    with c3:
        # "Total" (Jiho 8/12): every territory's members in one view, summed
        # against the summed published cells — same conservation rules.
        terr = st.selectbox("Territory", [_tr.TOTAL_TERRITORY] + terrs,
                            key="trace_terr",
                            format_func=lambda t: (
                                "Total — all territories"
                                if t == _tr.TOTAL_TERRITORY else t))
    months = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
              "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
    with c4:
        month = st.selectbox("Which month's column?", months,
                             key="trace_month")
    # photo families: only the report's own capture month has rosters here
    _capture_abb = _pretty_period(period).split()[0][:3]
    if family == "Penetration" and month != _capture_abb:
        st.info(f"Penetration shows LIVE NUMBERS — one count taken the "
                f"moment this report was built, not a month-by-month "
                f"history. On the {_pretty_period(period)} report it can "
                f"only be shown under {_capture_abb}, not {month}. For "
                f"{month}'s penetration, open the {month} report.")
        return
    if family == "Penetration":
        month = None    # one photo per report; the API traces the roster

    # A period with no receipts yet is a NORMAL state, not an error: it is
    # exactly where a brand-new fiscal year sits in the first days of October,
    # before the first full run has written receipts_<period>.json. Unwrapped,
    # this threw a raw FileNotFoundError traceback at the operator (found
    # 2026-08-11 while stress-testing the FY rollover) — the same class of
    # defect as the close panel's StaleCapture traceback fixed on 8/10.
    try:
        out = _tr.trace(period, family, terr, month)
    except FileNotFoundError:
        st.info(f"No receipts have been written for {period} yet, so there is "
                f"nothing to trace. Receipts are produced by a full run — once "
                f"tonight's run finishes, this page will work for {period}. "
                f"This is normal for a month that has only just started.")
        return

    if not out["members"] and not any(v not in (None, 0)
                                      for v in out["published"].values()):
        if family in ("Billables", "Penetration"):
            st.info(f"{FAMILY_LABELS[family]} shows LIVE NUMBERS — one "
                    f"count taken the moment this report was built, not a "
                    f"month-by-month history. On the "
                    f"{_pretty_period(period)} report it can only be shown "
                    f"under {_capture_abb}"
                    + (f", not {month}." if month else ".")
                    + (f" For {month}'s figures, open the {month} report."
                       if month else ""))
        else:
            _what = {"Retention": "renewals", "Drops": "drops",
                     "New Members / New Sales": "new sales",
                     "Billables": "billables",
                     "Penetration": "penetration"}.get(family, "activity")
            _where = ("any territory" if terr == _tr.TOTAL_TERRITORY else terr)
            st.info(f"No {_what} in {_where}"
                    + (f" in {month}." if month else "."))
        return

    # ---- the verdict strip ----
    cons = out["conservation"]
    pub = {k: v for k, v in out["published"].items() if v is not None}
    if cons["ok"]:
        # Streamlit's own success box brings its own font and green — it read as
        # a different application from the rest of the page (Jiho, 8/14). Same
        # shape and type scale as the corrections banner below it.
        _note = ("  " + out["frozen_note"]) if out.get("frozen_note") else ""
        st.markdown(
            f"<div style='padding:8px 12px;margin:2px 0 4px;background:#F2F8F3;"
            f"border-left:3px solid #4C9A5B;font-size:0.9rem;color:#222222;'>"
            f"\u2713 The members below add up to the published number exactly."
            f"{_note}</div>", unsafe_allow_html=True)
    # NO ALARM when they do not (Jiho, 8/13): "investigate" is not something
    # the reader can act on — a mismatch is a defect for whoever maintains
    # the report, and it lands in the run's flag list where they will see it.
    # The causes that used to fire this at people are fixed at the source
    # (sealed months carry only what is actually frozen; member lists and
    # published numbers now come from the same run). The totals strip and the
    # published line sit side by side, so nothing is hidden either.

    if pub:
        st.caption("Published: " + " · ".join(
            f"{k.replace('_', ' ')}: {v:,.0f}" if isinstance(v, (int, float))
            else f"{k}: {v}" for k, v in pub.items()))

    # HAND CORRECTIONS (8/14). Part of the answer, not a footnote: the published
    # number above already carries them, so a reader who cannot see them here
    # has no way to tell a corrected number from a computed one.
    _adjs = out.get("adjustments") or []
    if _adjs:
        st.markdown(
            f"<div style='padding:8px 12px;margin:6px 0 2px;background:#FFF8E1;"
            f"border-left:3px solid #E6B422;font-size:0.9rem;'>"
            f"<b>This number includes {len(_adjs)} hand "
            f"correction{'s' if len(_adjs) != 1 else ''}.</b> The members below "
            f"account for the rest.</div>", unsafe_allow_html=True)
        st.dataframe(_pd.DataFrame([{
            "When": (a.get("at") or "")[:16].replace("T", " "),
            "Who": a.get("who"),
            "Line": a.get("field"),
            "Change": f"{a.get('delta'):+,.0f}",
            "Member": a.get("member") or "—",
            "Why": a.get("why"),
        } for a in _adjs]), use_container_width=True, hide_index=True)

    # LIVE-NUMBER FAMILIES sometimes publish a count with no stored roster
    # behind it (penetration keeps rosters only where a run captured them —
    # July's came from a one-off backfill). Say that plainly rather than
    # leaving the reader staring at a number with nothing under it.
    if (family in ("Billables", "Penetration") and not out["members"]
            and any(v not in (None, 0) for v in out["published"].values())):
        st.caption("These are live counts from this report's own build. The "
                   "member-by-member roster behind them is not stored for "
                   "this report, so there is nothing to list here.")

    # ---- the members ----
    # "In the number" = rows the published cell actually counts. Retention
    # also includes billed-but-unpaid (they are in the denominator). For
    # every other family, counted alone decides — an excluded drop's dues
    # value must not smuggle it in (Todd's Crab Cracker, 8/6 round 2).
    if family == "Retention":
        inc = [r for r in out["members"]
               if r.get("counted") or (r.get("ask") or 0) > 0]
    else:
        inc = [r for r in out["members"] if r.get("counted")]
    exc = [r for r in out["members"] if r not in inc]
    import pandas as _pd
    def _row_view(r):
        v = {"Member": r.get("member"),
             "Member #": r.get("mid") or r.get("member_id"),
             "Band": r.get("band")}
        if terr == _tr.TOTAL_TERRITORY:
            v["Territory"] = r.get("territory")
        if family == "Drops":
            v["Dues value $"] = r.get("amount")
        elif family in ("Billables", "Penetration"):
            pass                      # a roster row IS the contribution
        else:
            v["Asked $"] = (r.get("ask") if r.get("ask") is not None
                            else r.get("amount"))
            v["Collected $"] = r.get("retained")
        v["Why"] = r.get("qualifies")
        v["Key date"] = ("" if "date estimated" in str(r.get("qualifies"))
                         else r.get("key_date"))
        return v
    if inc:
        st.markdown(f"**In the number ({len(inc)})**")
        st.dataframe(_pd.DataFrame([_row_view(r) for r in inc]),
                     use_container_width=True, hide_index=True)
        # Totals strip (Jen, demo 14:01: "The total amount, we don't have
        # that yet") — the roster reconciles against her tracker at a glance.
        if family == "Retention":
            _paid_n = sum(1 for r in inc if r.get("counted"))
            _ask_t = sum((r.get("ask") if r.get("ask") is not None
                          else r.get("amount")) or 0 for r in inc)
            _col_t = sum(r.get("retained") or 0 for r in inc)
            st.caption(f"**Totals — billed {len(inc)} · paid {_paid_n} · "
                       f"asked \\${_ask_t:,.2f} · collected \\${_col_t:,.2f}**")
        elif family == "Drops":
            _amt_t = sum(r.get("amount") or 0 for r in inc)
            st.caption(f"**Totals — {len(inc)} drops · dues value "
                       f"\\${_amt_t:,.2f}**")
        elif family == "New Members / New Sales":
            _ask_t = sum((r.get("ask") if r.get("ask") is not None
                          else r.get("amount")) or 0 for r in inc)
            _col_t = sum(r.get("retained") or 0 for r in inc)
            st.caption(f"**Totals — {len(inc)} members · asked "
                       f"\\${_ask_t:,.2f} · collected \\${_col_t:,.2f}**")
    if exc:
        with st.expander(f"Considered but excluded ({len(exc)}) — every "
                         f"absence has a reason"):
            st.dataframe(_pd.DataFrame([
                ({"Member": r.get("member"),
                  "Territory": r.get("territory"),
                  "Why excluded": r.get("qualifies")}
                 if terr == _tr.TOTAL_TERRITORY else
                 {"Member": r.get("member"),
                  "Why excluded": r.get("qualifies")})
                for r in exc]), use_container_width=True, hide_index=True)

    # Excel download (Jiho 8/12): exactly what this page shows — the counted
    # roster, the exclusions with reasons, and the published cell — portable
    # for reconciling against Jen's trackers offline.
    if inc or exc:
        import io as _io
        _buf = _io.BytesIO()
        with _pd.ExcelWriter(_buf, engine="openpyxl") as _xw:
            if inc:
                _pd.DataFrame([_row_view(r) for r in inc]).to_excel(
                    _xw, sheet_name="In the number", index=False)
            if exc:
                _pd.DataFrame([{
                    "Member": r.get("member"),
                    "Territory": r.get("territory"),
                    "Why excluded": r.get("qualifies"),
                } for r in exc]).to_excel(
                    _xw, sheet_name="Excluded", index=False)
            _pd.DataFrame([{"field": k, "value": v}
                           for k, v in out["published"].items()]).to_excel(
                _xw, sheet_name="Published", index=False)
        _fname = (f"trace_{period}_{family}_{terr}_{month or 'photo'}.xlsx"
                  .replace("/", "-").replace(" ", "_"))
        st.download_button("⬇ Download this view (Excel)", _buf.getvalue(),
                           file_name=_fname,
                           mime="application/vnd.openxmlformats-officedocument"
                                ".spreadsheetml.sheet",
                           key="trace_download")

    # ---- source + rules ----
    fam_metrics = {m: e for m, e in REGISTRY.items()
                   if e.get("family") == family}
    sources = sorted({e["source"] for e in fam_metrics.values()}) or ["slx-live"]
    SRC_WORDS = {"slx-live": "computed from the live CRM pull",
                 "crystal-export": "overlaid from the archived scheduled "
                                   "Crystal exports (data/raw/crystal)",
                 "photo": "a point-in-time roster photo from this month's "
                          "own pull", "admin": "entered in Admin Inputs",
                 "derived": "arithmetic over other traced numbers"}
    st.caption("Source: " + "; ".join(SRC_WORDS[s] for s in sources) + ".")

    rule_tags = sorted({t for e in fam_metrics.values() for t in e["rules"]})
    with st.expander(f"The rules that shape these numbers ({len(rule_tags)})"):
        for t in rule_tags:
            st.markdown(f"**{t}** — {RULES[t]}")
    with st.expander("What each line on the report means (this family)"):
        for m, e in sorted(fam_metrics.items()):
            st.markdown(f"**{m}** — {e['card']}")


def page_pen_report():
    import pandas as pd
    import altair as alt

    page_header("Membership Performance Report  ›  Sub-Reports",
                "Penetration Report",
                "Active members ÷ addressable market, per territory.")

    if not CACHE_FILE.exists():
        st.info("No cache file. Generate the Membership Performance Report first.")
        return

    rows = collect_territory_status()
    fields = _load_cache_fields() or {}
    # Target pool penetration fields (existing)
    pa  = fields.get("pen_active_restaurant") or {}
    pm  = fields.get("pen_market_restaurant") or {}
    la  = fields.get("pen_active_lodging") or {}
    lm  = fields.get("pen_market_lodging") or {}
    # Non-Target pool penetration fields (new — populate on next SLX run)
    npa = fields.get("pen_active_nt_restaurant") or {}
    npm = fields.get("pen_market_nt_restaurant") or {}
    nla = fields.get("pen_active_nt_lodging") or {}
    nlm = fields.get("pen_market_nt_lodging") or {}
    # Membership counts (current-month snapshot)
    bt   = fields.get("hosp_bills_target")     or {}
    bnt  = fields.get("hosp_bills_non_target") or {}
    bal  = fields.get("allied_bills")          or {}

    def _mar(d, t):
        v = (d.get(t) or {}).get(CURRENT_MONTH) if isinstance(d.get(t), dict) else None
        return v if isinstance(v, (int, float)) else 0

    def _sum_nums(d):
        return sum(v for v in d.values() if isinstance(v, (int, float)))

    # Statewide aggregates — penetration (target and non-target pools)
    rest_t_a, rest_t_m   = _sum_nums(pa),  _sum_nums(pm)
    lodg_t_a, lodg_t_m   = _sum_nums(la),  _sum_nums(lm)
    rest_nt_a, rest_nt_m = _sum_nums(npa), _sum_nums(npm)
    lodg_nt_a, lodg_nt_m = _sum_nums(nla), _sum_nums(nlm)

    # Statewide membership counts (current month)
    sw_target     = sum(_mar(bt,  t) for t in TERRITORY_ORDER)
    sw_non_target = sum(_mar(bnt, t) for t in TERRITORY_ORDER)
    sw_allied     = sum(_mar(bal, t) for t in TERRITORY_ORDER)
    sw_active     = sw_target + sw_non_target

    pen_thresh = _goal_threshold("goal_penetration", GOAL_PENETRATION_FALLBACK)

    def _stat_class(p):
        if p is None:           return ""
        if p >= pen_thresh:     return "green"
        return "amber"

    def _safe_div(a, b):
        return (a / b) if b else None

    def _pct_or_dash(v):
        return f"{v*100:.1f}%" if v is not None else "—"

    # ── Statewide penetration — Target POOL ───────────────────────────────
    section("Statewide — Target Pool Penetration")
    c1, c2, c3 = st.columns(3)
    rest_t_pct = _safe_div(rest_t_a, rest_t_m)
    lodg_t_pct = _safe_div(lodg_t_a, lodg_t_m)
    both_t_pct = _safe_div(rest_t_a + lodg_t_a, rest_t_m + lodg_t_m)
    kpi_card(c1, "Restaurant", _pct_or_dash(rest_t_pct),
             f"{rest_t_a:,} active of {rest_t_m:,} target locations",
             _stat_class(rest_t_pct))
    kpi_card(c2, "Lodging", _pct_or_dash(lodg_t_pct),
             f"{lodg_t_a:,} active of {lodg_t_m:,} target rooms",
             _stat_class(lodg_t_pct))
    kpi_card(c3, "Combined", _pct_or_dash(both_t_pct), "",
             _stat_class(both_t_pct))

    # ── Statewide penetration — NON-TARGET POOL ───────────────────────────
    section("Statewide — Non-Target Pool Penetration")
    n1, n2, n3 = st.columns(3)
    rest_nt_pct = _safe_div(rest_nt_a, rest_nt_m)
    lodg_nt_pct = _safe_div(lodg_nt_a, lodg_nt_m)
    both_nt_pct = _safe_div(rest_nt_a + lodg_nt_a, rest_nt_m + lodg_nt_m)
    kpi_card(n1, "Restaurant", _pct_or_dash(rest_nt_pct),
             f"{rest_nt_a:,} active of {rest_nt_m:,} sub-threshold locations")
    kpi_card(n2, "Lodging", _pct_or_dash(lodg_nt_pct),
             f"{lodg_nt_a:,} active of {lodg_nt_m:,} sub-threshold rooms")
    kpi_card(n3, "Combined", _pct_or_dash(both_nt_pct), "")

    # ── Visualization: Target vs Non-Target restaurant penetration per terr ──
    chart_rows = []
    for t in TERRITORY_ORDER:
        t_pct  = _safe_div(pa.get(t)  or 0, pm.get(t)  or 0)
        nt_pct = _safe_div(npa.get(t) or 0, npm.get(t) or 0)
        if t_pct is None and nt_pct is None:
            continue
        if t_pct is not None:
            chart_rows.append({"territory": t, "pool": "Target", "penetration": t_pct})
        if nt_pct is not None:
            chart_rows.append({"territory": t, "pool": "Non-Target", "penetration": nt_pct})
    if chart_rows:
        chart_title("Restaurant Penetration — Target vs Non-Target by Territory")
        st.text("Wide gap between the two bars = strong on Target, weaker on Non-Target.")
        cdf = pd.DataFrame(chart_rows)
        chart = alt.Chart(cdf).mark_bar(size=10, cornerRadiusEnd=2).encode(
            x=alt.X("penetration:Q",
                    axis=alt.Axis(format=".0%", title=None)),
            y=alt.Y("territory:N", sort="-x", title=None),
            yOffset=alt.YOffset("pool:N",
                                sort=["Target", "Non-Target"]),
            color=alt.Color("pool:N",
                            scale=alt.Scale(
                                domain=["Target", "Non-Target"],
                                range=["#02b5e3", "#f0b010"],
                            ),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[
                alt.Tooltip("territory:N", title="Territory"),
                alt.Tooltip("pool:N", title="Pool"),
                alt.Tooltip("penetration:Q", title="Penetration", format=".1%"),
            ],
        ).properties(height=420).configure_view(
            stroke=None
        ).configure_axis(
            labelFont="Inter", titleFont="Inter",
            labelColor="#58595b", gridColor="#f0f2f5", domain=False,
        )
        st.altair_chart(chart, use_container_width=True, theme=None)

    # ── Per-territory penetration table (clean — counts moved below) ──────
    section("Penetration by Territory")
    table_rows = []
    for t in TERRITORY_ORDER:
        r_t_pct  = _safe_div(pa.get(t)  or 0, pm.get(t)  or 0)
        l_t_pct  = _safe_div(la.get(t)  or 0, lm.get(t)  or 0)
        r_nt_pct = _safe_div(npa.get(t) or 0, npm.get(t) or 0)
        l_nt_pct = _safe_div(nla.get(t) or 0, nlm.get(t) or 0)
        if all(v is None for v in (r_t_pct, l_t_pct, r_nt_pct, l_nt_pct)):
            continue
        table_rows.append({
            "Territory":           t,
            "Restaurant Target":    _pct_or_dash(r_t_pct),
            "Restaurant Non-Tgt":   _pct_or_dash(r_nt_pct),
            "Lodging Target":       _pct_or_dash(l_t_pct),
            "Lodging Non-Tgt":      _pct_or_dash(l_nt_pct),
        })
    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

    # ── Membership counts — separate section, intentionally NOT % ─────────
    # Allied is a distinct member TYPE (not part of the size split).
    # NRA is a billing-channel disclosure (already inside Target/Non-Target counts).
    section("Membership Counts (current month)")
    m1, m2, m3 = st.columns(3)
    target_share = (sw_target / sw_active) if sw_active else None
    kpi_card(m1, "Active Hospitality", f"{sw_active:,}" if sw_active else "—",
             "Target + Non-Target")
    kpi_card(m2, "Target",
             f"{sw_target:,}" if sw_target else "—",
             (f"{target_share*100:.1f}% of active hospitality"
              if target_share is not None else "≥10 FTE / ≥40 rooms"))
    kpi_card(m3, "Non-Target",
             f"{sw_non_target:,}" if sw_non_target else "—",
             (f"{(1-target_share)*100:.1f}% of active hospitality"
              if target_share is not None else "below threshold"))

    kpi_card(st.columns(1)[0], "Allied", f"{sw_allied:,}" if sw_allied else "—", "")

    count_rows = []
    for t in TERRITORY_ORDER:
        tgt, nt = _mar(bt, t), _mar(bnt, t)
        al = _mar(bal, t)
        if tgt + nt + al == 0:
            continue
        count_rows.append({
            "Territory":      t,
            "Target":         tgt or "—",
            "Non-Target":     nt  or "—",
            "+ Allied":       al  or "—",
        })
    if count_rows:
        st.dataframe(pd.DataFrame(count_rows), hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────
# Retention Detail Report — single combined page (sub-page of MPR)
# ─────────────────────────────────────────────────────────────────────
def page_dd_combined():
    page_header("Membership Performance Report  ›  Sub-Reports",
                "Retention Detail Report",
                "Account-by-account view behind the retention metric.")

    # Configure + generate
    section("Run")
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        bm = st.selectbox(
            "Bill Month", options=list(range(1, 13)),
            format_func=lambda x: ["Jan","Feb","Mar","Apr","May","Jun",
                                   "Jul","Aug","Sep","Oct","Nov","Dec"][x-1],
            index=1, key="dd_bm",
        )
    with c2:
        st.markdown("<div style='height:1.85rem;'></div>", unsafe_allow_html=True)
        if st.button("Generate", type="primary", use_container_width=True):
            with st.spinner(f"Pulling Bill Month {bm} from SLX (~3 min)..."):
                _run_drilldown(bm)
            st.rerun()

    # Results (if available)
    if st.session_state.drilldown_status == "done":
        st.success("Retention Detail Report complete.")
    elif st.session_state.drilldown_status == "error":
        st.error("Last run failed — see log below.")

    section("Latest Result")
    dd_path_str = st.session_state.drilldown_path
    path = Path(dd_path_str) if dd_path_str else None
    if path is not None and path.is_file():
        with open(path, "rb") as f:
            st.download_button(
                "Download Report",
                data=f.read(),
                file_name=path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        st.text(f"{size_str(path)}")
    else:
        st.text("No report generated yet. Pick a bill month above and click Generate.")

    # Summary from log
    if st.session_state.drilldown_log:
        section("Summary")
        for line in st.session_state.drilldown_log:
            s = line.strip()
            if any(k in s for k in ["Statewide", "Billed:", "Paid:", "Unpaid", "Collection"]):
                st.text(s)

        with st.expander("Run log", expanded=False):
            st.text("\n".join(st.session_state.drilldown_log))


# ─────────────────────────────────────────────────────────────────────
# Admin Inputs page
# ─────────────────────────────────────────────────────────────────────
def _dues_inputs_panel(hub, key_prefix: str):
    """Download/upload dues_inputs.xlsx — the human decision workbook.

    Shared by the Dues page and Admin Inputs so there is ONE implementation of
    the validate → local → SharePoint write. Admin Inputs previously offered
    only the MPR's workbook, which made the dues decisions look like they
    lived somewhere else (Jiho, 7/27).
    """
    from pathlib import Path as _P
    inputs_local = PROJECT_ROOT / "data" / "raw" / "dues_inputs.xlsx"
    c_dl, c_ul = st.columns([1, 1])
    with c_dl:
        if inputs_local.exists():
            st.download_button(
                "Download dues_inputs.xlsx (classify here)",
                data=inputs_local.read_bytes(),
                file_name="dues_inputs.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key_prefix}_dl", use_container_width=True,
            )
            st.text(f"Updated {relative_age(inputs_local)}")
        else:
            st.text("No dues inputs workbook yet — generate Dues Analysis once.")
    with c_ul:
        # Task #17: upload path for teammates who classify locally instead of
        # on SharePoint. Validated by the same parser the run uses, then
        # written local + shared Inputs (the run's sync source).
        up = st.file_uploader("Upload edited dues_inputs.xlsx", type=["xlsx"],
                              accept_multiple_files=False,
                              key=f"{key_prefix}_upload")
        if up is not None:
            file_id = f"{up.name}-{up.size}"
            if st.session_state.get(f"{key_prefix}_upload_id") != file_id:
                contents = up.read()
                try:
                    import tempfile

                    from reports.dues_analysis.logic.inputs import parse_inputs
                    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tf:
                        tf.write(contents)
                        tf.flush()
                        parse_inputs(_P(tf.name))   # header/sheet validation
                except Exception as e:
                    st.session_state[f"{key_prefix}_msg"] = \
                        f"ERR:Not a valid dues_inputs workbook — {type(e).__name__}: {e}"
                else:
                    inputs_local.parent.mkdir(parents=True, exist_ok=True)
                    inputs_local.write_bytes(contents)
                    try:
                        hub.write_shared_input("dues_inputs.xlsx", contents)
                        dest = "SharePoint (shared Inputs) + local"
                    except Exception as e:
                        dest = f"local only ({type(e).__name__} — sync manually)"
                    st.session_state[f"{key_prefix}_msg"] = \
                        f"OK:Saved ({len(contents):,} bytes) → {dest}"
                st.session_state[f"{key_prefix}_upload_id"] = file_id
        msg = st.session_state.get(f"{key_prefix}_msg")
        if msg:
            (st.error if msg.startswith("ERR:") else st.success)(msg[4:])
    st.caption("Edited on SharePoint at Inputs/ — the run syncs it "
               "down first, so classifications persist across runs. Uploading "
               "here replaces both the local and SharePoint copies.")


def page_admin():
    page_header("System", "Admin Inputs",
                "Everything a human types. One page per report — goals and "
                "targets for the MPR, out-of-cycle decisions for Dues.")

    section("Membership Performance Report — goals & targets")
    st.markdown(
        "**Edit the goals directly on SharePoint** — open the Membership "
        "Data Hub, folder *Inputs*, file **admin_inputs.xlsx** (Excel "
        "Online). The system reads that file at the start of every run; "
        "there is nothing to upload or download here.",
    )
    st.caption("Changing a goal changes the status colors and goal lines "
               "on the next build — nothing recomputes retroactively.")

    section("What the system currently sees")
    _f = _load_cache_fields() or {}
    if not _f:
        st.info("No pull yet — goals appear here after the first refresh.")
    else:
        import pandas as _pd
        terrs = sorted((_f.get("goal_retention") or {}).keys())
        rows = []
        for t in terrs:
            ret_goals = _f.get("goal_retention", {}).get(t) or {}
            rev_goals = _f.get("goal", {}).get(t) or {}
            mem_goals = _f.get("goal_members", {}).get(t) or {}
            rows.append({
                "Territory": t,
                f"Revenue goal ({CURRENT_MONTH})": rev_goals.get(CURRENT_MONTH),
                f"Member goal ({CURRENT_MONTH})": mem_goals.get(CURRENT_MONTH),
                f"Retention goal ({CURRENT_MONTH})": ret_goals.get(CURRENT_MONTH),
                "Penetration goal": (_f.get("goal_penetration") or {}).get(t),
            })
        st.dataframe(_pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        st.caption(f"As read from SharePoint by the last run ({_goals_age()}). "
                   f"Edit on SharePoint and the next run picks it up.")
        # Goals are NOT part of a month's seal (Jiho, 8/13): a closed month
        # keeps its numbers forever, but its goal is re-read on every build,
        # so a later goal edit silently re-grades it. Said here, where the
        # edit actually happens, rather than only in the SOP.
        st.caption("Changing a sealed month's goal will change its goal "
                   "percentages and status colors.")

    # (Dues Analysis admin section removed 8/10 — see packaging plan)


# ─────────────────────────────────────────────────────────────────────
# Data & Schedule page
# ─────────────────────────────────────────────────────────────────────
def page_schedule():
    page_header("System", "Data & Schedule",
                "Data freshness and refresh schedule.")

    section("Data Freshness")
    c1, c2, c3 = st.columns(3)
    # SLX freshness is a GLOBAL question — when did we last pull SLX at all —
    # not "does THIS viewing month have a file" (2026-09-03). The card size
    # follows the newest same-FY cache so it never reads a missing future
    # month's file and shows 0 B / "never" while a real pull sits next to it.
    _fresh_src = _newest_same_fy_cache(PERIOD) or CACHE_FILE
    kpi_card(c1, "SLX Cache", size_str(_fresh_src),
             f"Refreshed {_last_slx_pull_age()}",
             freshness_class(_fresh_src, stale_after_hours=24*30))
    # ADMIN INPUTS lives on SHAREPOINT, not on this disk (fixed 2026-08-14).
    # This card measured `data/raw/admin_inputs.xlsx` — a local copy the build
    # stopped depending on. Every deploy wipes container disk, so the card read
    # "— / Modified never" while the preflight line directly below it correctly
    # said "Readable from SharePoint". Two contradictory answers on one screen,
    # and the alarming one was about a file nothing reads. `_admin_age()` asks
    # SharePoint (falling back to the local mtime only when offline).
    _adm_iso = _admin_sp_modified_iso()
    # `_admin_age()` already returns its own verb ("edited 20h ago", and
    # sometimes "· not in a report yet"); prefixing another one printed
    # "Edited edited 20h ago" on the live console (2026-08-15). Supply the verb
    # only for the offline fallback, which returns a bare age.
    _adm_txt = _admin_age()
    if not _adm_txt.startswith("edited"):
        _adm_txt = ("never edited on SharePoint" if _adm_txt == "never"
                    else f"edited {_adm_txt}")
    kpi_card(c2, "Admin Inputs", size_str(ADMIN_XLSX),
             _adm_txt[:1].upper() + _adm_txt[1:],
             _hours_class(_iso_hours_ago(_adm_iso), 24*60) if _adm_iso
             else freshness_class(ADMIN_XLSX, stale_after_hours=24*60))
    # LATEST REPORT: "Generated" means generated. `relative_age` reads mtime,
    # and on a fresh instance `_hydrate_output_workbook` DOWNLOADS the workbook
    # from SharePoint — so mtime was the download time and this card said
    # "Generated 44s ago" about a file built two hours earlier (seen 8/14).
    # Worse: on a morning after a FAILED nightly it would download yesterday's
    # workbook and still report it as just-generated, hiding the failure from
    # the one number a reader checks. Hydration now stamps the file with its
    # real generation time (see `_stamp_generated_at`), so mtime is the truth
    # again — the same rule `_data_age` already follows for the cache.
    kpi_card(c3, "Latest Report", size_str(OUTPUT_FILE),
             f"Generated {relative_age(OUTPUT_FILE)}",
             freshness_class(OUTPUT_FILE, stale_after_hours=24*7))

    section("Preflight Checks")
    sp_ok, sp_label = sharepoint_status()
    items = []
    if _newest_same_fy_cache(PERIOD) is None:
        items.append(("warn", "SLX cache", "No cache found for this fiscal year. "
                      "Run a full SLX refresh first."))
    else:
        items.append(("ok", "SLX cache", f"SLX last refreshed {_last_slx_pull_age()}."))
    _adm_bytes, _adm_src = fetch_admin_bytes()
    if _adm_bytes:
        items.append(("ok", "Admin inputs",
                      f"Readable from {_adm_src} — the system reads it on "
                      f"every run."))
    else:
        items.append(("warn", "Admin inputs",
                      "Could not read the Admin Inputs workbook from "
                      "SharePoint or the local copy."))
    items.append(("ok" if sp_ok else "info", "SharePoint", sp_label))

    for status, label, detail in items:
        pill_kind = {"ok": "green", "warn": "amber", "info": "grey"}.get(status, "grey")
        st.markdown(
            f"<div style='padding:0.5rem 0;font-size:0.88rem;color:#58595b;'>"
            f"<span class='pill pill-{pill_kind}'>{label}</span> "
            f"<span style='margin-left:8px;'>{detail}</span></div>",
            unsafe_allow_html=True,
        )

    section("Automatic Refresh Schedule")
    from datetime import time as dt_time
    from src.scheduler import (load_schedule, save_schedule, refresh_next_run,
                               trigger_refresh, is_pid_alive,
                               schedule_time_warning, SAFE_HOUR, SAFE_MINUTE)
    _sched = load_schedule()
    _running_pid = (_sched.get("current_pid")
                    if is_pid_alive(_sched.get("current_pid")) else None)

    sc1, sc2, sc3 = st.columns([1, 1, 1.2])
    with sc1:
        if _running_pid:
            st.markdown(f"<div style='font-weight:600;'>Running (pid {_running_pid})</div>",
                        unsafe_allow_html=True)
            render_pull_progress()
        elif _sched.get("enabled"):
            nr = _sched.get("next_run_ts")
            nice = (datetime.fromisoformat(nr).strftime("%a %b %-d at %-I:%M %p")
                    if nr else "—")
            st.markdown(f"<div style='font-weight:600;'>Enabled</div>"
                        f"<div style='color:#808184;font-size:0.85rem;'>Next: {nice}</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<div style='font-weight:600;color:#808184;'>Disabled</div>",
                        unsafe_allow_html=True)
        lr = _sched.get("last_run_ts")
        if lr:
            nice = datetime.fromisoformat(lr).strftime("%a %b %-d at %-I:%M %p")
            st.text(f"Last: {nice} ({_sched.get('last_run_status') or '—'})")

    with sc2:
        new_enabled = st.toggle("Enable nightly refresh", value=bool(_sched.get("enabled")))
        # The time is adjustable again (Jiho 8/12) — WHA needs it for GL/Sage
        # posting timing. The old fix was to force it back to 2:00 here on every
        # save, which meant the stored value could never differ AND the caption
        # kept claiming "2:00 AM" regardless. Warn instead of lying.
        _cur_h = int(_sched.get("hour", SAFE_HOUR))
        _cur_m = int(_sched.get("minute", SAFE_MINUTE))
        new_time = st.time_input("Run at", value=dt_time(_cur_h, _cur_m), step=300)
        _warn = schedule_time_warning(new_time.hour, new_time.minute)
        if _warn:
            st.warning(_warn)
        else:
            st.caption("02:00 is the designed slot: the month close needs a "
                       "clean before-ITD photo from each night, and the day's "
                       "Crystal export must already have landed.")
        if st.button("Save schedule", use_container_width=True):
            _sched["enabled"] = bool(new_enabled)
            _sched["hour"]    = int(new_time.hour)
            _sched["minute"]  = int(new_time.minute)
            save_schedule(_sched)
            refresh_next_run()
            st.rerun()

    with sc3:
        st.text("Runs a full SLX refresh in the background. You can close the tab — the process keeps running.")
        if st.button("Trigger Full Refresh Now",
                     disabled=(_running_pid is not None),
                     use_container_width=True):
            pid = trigger_refresh("live")
            if pid == 0:
                st.warning("A pull is already running. Yours was not started "
                           "— wait for the current one to finish.")
            else:
                s = load_schedule()
                s["last_run_ts"]     = datetime.now().isoformat()
                s["last_run_status"] = f"running (pid {pid})"
                s["current_pid"]     = pid
                save_schedule(s)
                st.success(f"Started in background (pid {pid}).")
                st.rerun()

    log_file = OUTPUT_DIR / "scheduled_run.log"
    if log_file.exists() and log_file.stat().st_size > 0:
        section("Recent Refresh Log")
        with st.expander("Show log", expanded=False):
            tail = log_file.read_text(errors="ignore").splitlines()[-40:]
            st.text("\n".join(tail))


# ─────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────
nav = st.session_state.nav
# Migrate legacy nav targets transparently
_LEGACY_NAV = {
    "mpr.snapshot": "mpr.summary",
    "mpr.visuals":  "mpr.tracker",
    "mpr.summary":  "mpr.tracker",
    "mpr.analytics": "mpr.tracker",
    "mpr.results":  "mpr.tracker",
    "dd.run":       "dd.combined",
    "dd.results":   "dd.combined",
}
def _dues_editions():
    """Edition months to offer: this FY's months through the prior month,
    newest first. Derived — no literals (logic/periods.py)."""
    from reports.dues_analysis.logic.periods import default_period, fy_months
    return list(reversed(fy_months(default_period())))


def _dues_hub():
    # Reuse the console's SharePoint client (honors WHA_OFFLINE + the session
    # cache) instead of reconnecting per render.
    from src.hub.datahub import DataHub
    return DataHub(sharepoint_client=get_sharepoint_client())


def page_dues():
    page_header("Reports", "Dues Analysis",
                "Populate finance's Dues Summary workbook automatically — "
                "billed vs collected by territory and bill month.")

    from pathlib import Path as _Path
    from reports.dues_analysis.logic.periods import default_period
    from reports.dues_analysis.runner import generate as generate_dues

    editions = _dues_editions() or [default_period()]
    out_dir = PROJECT_ROOT / "data" / "output"

    # ── Status bar ──────────────────────────────────────────────────────
    # Source of record = the nightly CRM report export, fetched from SLX's
    # attachment archive. Show how fresh it actually is: the whole failure
    # mode we guard against is a dead CRM schedule going unnoticed.
    hub = _dues_hub()

    @st.cache_data(ttl=120, show_spinner=False)
    def _dues_export_status():
        try:
            import os

            from dotenv import load_dotenv

            from reports.dues_analysis.logic import slx_reports as R
            from reports.dues_analysis.runner import EXPORT_MAX_AGE_DAYS
            from src.slx.client import SLXClient
            load_dotenv(PROJECT_ROOT / ".env")
            c = SLXClient(username=os.environ["SLX_USERNAME"],
                          password=os.environ["SLX_PASSWORD"])
            out = {}
            for label, prefix in (("DA detail", R.DA_DETAIL_PREFIX),
                                  ("New members", R.NEW_MEMBER_PREFIX)):
                e = R.latest_export(c, prefix)
                if e is None:
                    out[label] = (None, "none found")
                    continue
                age = (_dt.date.today() - e.run_date).days
                out[label] = (age, f"{e.run_date} ({e.user})")
            out["_limit"] = EXPORT_MAX_AGE_DAYS
            return out
        except Exception as exc:
            return {"_error": f"{type(exc).__name__}"}

    status = _dues_export_status()
    bits = []
    if "_error" in status:
        bits.append(f"<span><b>Exports</b> unreachable ({status['_error']})</span>")
    else:
        limit = status.get("_limit", 3)
        for label in ("DA detail", "New members"):
            age, detail = status.get(label, (None, "?"))
            if age is None:
                bits.append(f"<span><b>{label}</b> ⛔ {detail}</span>")
            else:
                mark = "✅" if age <= limit else "⚠️ STALE"
                aged = "today" if age == 0 else f"{age}d old"
                bits.append(f"<span><b>{label}</b> {mark} {aged} · {detail}</span>")
    bits.append(f"<span><b>SharePoint</b> "
                f"{'connected' if hub.sharepoint_connected else 'offline'}</span>")
    st.markdown(f"<div class='status-bar'>{''.join(bits)}</div>",
                unsafe_allow_html=True)
    if any("STALE" in b for b in bits):
        st.warning("The newest CRM export is older than the freshness limit — "
                   "the scheduled report job has most likely expired in the "
                   "CRM (it self-deletes once its end date passes). Re-create "
                   "the daily schedule; runs will refuse to publish until then.")

    # ── Run controls ────────────────────────────────────────────────────
    section("Generate")
    c_sel, c_run = st.columns([1, 1], vertical_alignment="bottom")
    with c_sel:
        edition = st.selectbox("Edition month", editions, index=0,
                               key="dues_edition", format_func=_pretty_period)
    with c_run:
        run = st.button("Generate Dues Analysis", type="primary",
                        use_container_width=True)

    if run:
        with st.spinner(f"Populating the Dues Summary workbook for "
                        f"{_pretty_period(edition)}…"):
            try:
                res = generate_dues(hub, edition)
                st.session_state.dues_last = {"edition": edition, **{
                    k: v for k, v in res.items() if k != "output_path"}}
                st.session_state.dues_last["output_name"] = \
                    _Path(res["output_path"]).name
                if res.get("publish_error"):
                    st.warning(f"Saved locally, but SharePoint publish was "
                               f"blocked ({res['publish_error']}). Close the "
                               f"file on SharePoint and re-run to sync.")
                else:
                    st.success(f"Generated {_pretty_period(edition)} — "
                               f"published to SharePoint.")
            except Exception as e:
                st.error(f"Run failed: {type(e).__name__}: {e}")

    # Load this edition's payload once — feeds both the KPI cards and the
    # Review Queue so they always agree (even before a Generate this session).
    try:
        payload = hub.load_report_data("dues_analysis", edition,
                                       hub_folder="Dues Analysis")
    except Exception:
        payload = {}
    queue = payload.get("pending_queue", [])
    warn_count = sum(len(m.get("warnings", []))
                     for m in payload.get("months", {}).values())

    # ── Result + download ───────────────────────────────────────────────
    out_file = out_dir / f"Dues_Analysis_{edition}.xlsx"
    if out_file.exists():
        cols = st.columns(3)
        # One line per member-month — the same unit the inputs workbook and
        # the runner's `pending` use, so the three never disagree.
        decisions = len({(q.get("mid"), q.get("ym")) for q in queue})
        kpi_card(cols[0], "Pending review",
                 str(decisions) if payload else "—",
                 "member-months awaiting R/P/X")
        kpi_card(cols[1], "Warnings", str(warn_count) if payload else "—",
                 "anomalies flagged this run")
        kpi_card(cols[2], "Workbook", relative_age(out_file), "last generated")
        st.download_button(
            f"Download Dues_Analysis_{edition}.xlsx",
            data=out_file.read_bytes(),
            file_name=f"Dues_Analysis_{edition}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ── The Review Queue (the thing you couldn't see) ───────────────────
    section("Review Queue — out-of-cycle payments needing a decision")
    st.markdown(
        "<div class='page-sub'>These payments landed outside the normal "
        "1st/2nd/3rd-notice window. A human decides each one in "
        "<b>dues_inputs.xlsx</b> (Classification column): "
        "<b>R</b> = reinstate · <b>P</b> = payment plan · <b>X</b> = exclude "
        "(correction pair / not dues). Blank = still pending (counted nowhere "
        "until you decide). Fewer than ~10 are usually real reinstates or "
        "payment plans; the rest are corrections.</div>",
        unsafe_allow_html=True,
    )
    if queue:
        import pandas as _pd
        df = _pd.DataFrame(queue)[["ym", "name", "amount", "bm", "paid", "code", "mid"]]
        df.columns = ["Month", "Member", "Amount", "Bill Mo.", "Paid", "Code", "MID"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No pending items for this edition (run the report to "
                   "populate, or everything is already classified).")

    # ── Inputs workbook ─────────────────────────────────────────────────
    section("Inputs workbook")
    _dues_inputs_panel(hub, "dues_page")



def page_mpr_adjust():
    """Adjust a Number — hand corrections that persist, with a reason attached.

    Designed with Jiho 2026-08-14. A number is never overwritten: a correction
    is posted ON TOP as its own entry, and replayed on every later generation.
    The seal keeps the program's own figure, so "what it computed" and "what we
    corrected" both stay answerable forever.
    """
    import pandas as _pd
    from reports.membership_performance_tracker.logic import adjustments as _adj
    from reports.membership_performance_tracker.mapper import METRIC_FIELD_MAP

    page_header("Membership Performance Report", "Adjust a Number",
                "Correct a number the program got wrong. The correction stays "
                "on every future report, with your reason attached.")

    # Only lines that ARE a stored number can be adjusted. Combined lines,
    # percentages, statuses, quarter and YTD columns are Excel formulas over
    # these — they follow on their own once the parts underneath are right.
    lines = {}
    _LINE_OF_FIELD = {f: m for m, (_k, f) in METRIC_FIELD_MAP.items()}
    for metric, (kind, field) in sorted(METRIC_FIELD_MAP.items()):
        # kind "derived" means the mapper computes it at map time from other
        # metrics — there is no stored cell to correct. Offering one gave an
        # empty territory list and no explanation (found 8/14).
        if kind == "derived":
            continue
        if field in _adj.SPLIT_SUMS:
            continue          # the Target + Non-Target sum; correct a band
        if field in _adj.DERIVED_FIELDS or field.startswith(_adj.FORBIDDEN_FIELD_PREFIXES):
            continue
        lines[metric] = (kind, field)
    if not lines:
        st.info("No adjustable lines found.")
        return

    periods = sorted((p.stem.replace("scoreboard_", "")
                      for p in CACHE_DIR.glob("scoreboard_2*.json")
                      if p.name.count(".") == 1), reverse=True)
    if not periods:
        st.info("No report data yet.")
        return

    c1, c2 = st.columns([1, 2])
    with c1:
        period = st.selectbox("Which report?", periods, key="adj_period",
                              format_func=lambda p: f"{_pretty_period(p)} report")
    with c2:
        metric = st.selectbox("Which line?", list(lines), key="adj_metric")
    kind, field = lines[metric]
    monthless = field in _adj.MONTHLESS_FIELDS

    try:
        fields = json.loads((CACHE_DIR / f"scoreboard_{period}.json").read_text())["fields"]
    except Exception as exc:
        st.error(f"Could not read {period}: {type(exc).__name__}")
        return
    terrs = sorted(t for t in (fields.get(field) or {}) if t)
    if not terrs:
        st.info(f"'{metric}' has no territories in this report.")
        return

    c3, c4 = st.columns([1, 1])
    with c3:
        territory = st.selectbox("Which territory?", terrs, key="adj_terr")
    with c4:
        if monthless:
            month = None
            st.markdown("<div style='padding-top:1.9rem;color:#808184;"
                        "font-size:0.85rem;'>This line is a single count per "
                        "territory — it has no month.</div>",
                        unsafe_allow_html=True)
        else:
            months = [m for m in _adj.MONTHS
                      if m in ((fields.get(field) or {}).get(territory) or {})]
            if kind == "tm_current":
                # A photo count only appears on the report for the month that
                # was photographed. Correcting an earlier month here changes
                # the data and shows nothing — an earlier month is corrected
                # from ITS OWN report.
                snap = _adj.MONTHS[(int(period[5:7]) - 10) % 12]
                months = [m for m in months if m == snap]
                st.caption(f"Counted once a month — only {snap} on this report.")
            month = st.selectbox("Which month?", months, key="adj_month")

    entries = _adj.load(period)
    net = _adj.total_for(entries, field, territory, month)
    raw = (fields.get(field) or {}).get(territory)
    if not monthless:
        raw = (raw or {}).get(month)
    computed = 0.0 if raw is None else float(raw)

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("The program computed", f"{computed:g}")
    m2.metric("Corrections so far", f"{net:+g}" if net else "none")
    m3.metric("On the report now", f"{computed + net:g}")

    if entries and net:
        section("Corrections on this number")
        st.dataframe(_pd.DataFrame([{
            "When": (e.get("at") or "")[:16].replace("T", " "),
            "Who": e.get("who"),
            "Change": f"{e.get('delta'):+g}",
            "Member": e.get("member") or "—",
            "Why": e.get("why"),
        } for e in _adj.for_cell(entries, field, territory, month)]),
            use_container_width=True, hide_index=True)

    section("Make a correction")
    st.markdown("<div style='color:#808184;font-size:0.85rem;'>Enter the "
                "<b>change</b>, not the new total. To take something out, use a "
                "minus sign.</div>", unsafe_allow_html=True)
    a1, a2 = st.columns([1, 2])
    with a1:
        delta = st.number_input("Change by", value=0.0, step=1.0, key="adj_delta")
    with a2:
        who = st.text_input("Your name", key="adj_who")
    # Member names come from this report's own receipts — no SLX call, and it
    # is the same list Trace shows, so the two pages agree on who exists.
    # Type to filter; leave it on "not about one member" for a lump correction.
    _NONE = "— not about one member —"
    _members = [_NONE]
    try:
        _rj = json.loads((PROJECT_ROOT / "data" / "receipts" /
                          f"receipts_{period}.json").read_text())
        _members += sorted({r.get("member") for r in _rj.get("rows", [])
                            if r.get("member")
                            and r.get("territory") in (territory, None)})
    except Exception:
        pass
    mc1, mc2 = st.columns(2)
    with mc1:
        if len(_members) > 1:
            _picked = st.selectbox("Which member? (optional)", _members,
                                   key="adj_member")
            _picked = None if _picked == _NONE else _picked
        else:
            _picked = None
    with mc2:
        # Not every correction is about somebody already in this report — a
        # member the run missed entirely will not be in the list.
        _typed = st.text_input("…or type a name", key="adj_member_typed",
                               placeholder="Someone not in the list")
    member = (_typed or "").strip() or _picked
    why = st.text_area("Why?", key="adj_why", height=80,
                       placeholder="This is the only record of why the number "
                                   "is not what the program computed.")

    if delta:
        after = computed + net + delta
        st.markdown(
            f"<div style='padding:8px 12px;background:#FFF8E1;border-left:3px "
            f"solid #E6B422;font-size:0.9rem;'>"
            f"<b>{metric}</b> — {territory}{'' if monthless else ' · ' + str(month)}"
            f"<br>on the report now <b>{computed + net:g}</b> → would become "
            f"<b>{after:g}</b></div>", unsafe_allow_html=True)

    if st.button("Post this correction", type="primary", key="adj_post"):
        try:
            _adj.post(period, field, territory, month, delta, why, who,
                      member=member)
        except _adj.AdjustmentRefused as exc:
            st.error(str(exc))
        except _adj.AdjustmentSavedLocallyOnly as exc:
            # Applied, but only here. Saying "saved" would be a lie the next
            # deploy exposes.
            st.warning(str(exc))
        else:
            st.success("Saved to SharePoint. Regenerate the report to see it.")
            st.rerun()

    # EVERY correction on this report, not just the cell in the pickers. Nobody
    # should have to remember which lines they touched, and a correction you
    # cannot find is a correction you cannot undo.
    section("Everything corrected on this report")
    if not entries:
        st.markdown("<div style='color:#808184;font-size:0.9rem;'>Nothing has "
                    "been corrected on this report.</div>",
                    unsafe_allow_html=True)
    else:
        live = _adj.by_cell(entries)
        st.markdown(
            f"<div style='color:#808184;font-size:0.85rem;'>"
            f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} across "
            f"{len([c for c, v in live.items() if v])} number"
            f"{'' if len([c for c, v in live.items() if v]) == 1 else 's'} "
            f"still changed. Reversing adds an opposite entry — nothing is ever "
            f"deleted.</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
        for i, e in enumerate(reversed(entries)):
            label = _LINE_OF_FIELD.get(e.get("field"), e.get("field"))
            when = (e.get("at") or "")[:16].replace("T", " ")
            where = e.get("territory") + (f" · {e['month']}" if e.get("month") else "")
            r1, r2 = st.columns([5, 1])
            with r1:
                st.markdown(
                    f"<div style='font-size:0.9rem;line-height:1.45;'>"
                    f"<b>{e.get('delta'):+,.0f}</b> &nbsp; {label}"
                    f"<br><span style='color:#808184;'>{where} · {e.get('who')}"
                    f" · {when}{' · ' + e['member'] if e.get('member') else ''}"
                    f"<br>{e.get('why')}</span></div>",
                    unsafe_allow_html=True)
            with r2:
                if st.button("Reverse", key=f"adj_rev_{i}_{e.get('at')}"):
                    try:
                        _adj.post(period, e["field"], e["territory"], e["month"],
                                  -float(e["delta"]),
                                  f"Reversing the correction {e.get('who')} made "
                                  f"on {when}.",
                                  who or e.get("who") or "unknown",
                                  member=e.get("member"))
                    except _adj.AdjustmentRefused as exc:
                        st.error(str(exc))
                    except _adj.AdjustmentSavedLocallyOnly as exc:
                        st.warning(str(exc))
                    else:
                        st.success("Reversed. Regenerate to see it.")
                        st.rerun()
            st.markdown("<div style='border-bottom:1px solid #eee;"
                        "margin:6px 0;'></div>", unsafe_allow_html=True)

    section("Then regenerate")
    st.markdown("<div style='color:#808184;font-size:0.85rem;'>A correction "
                "does not appear until the report is generated again.</div>",
                unsafe_allow_html=True)
    if st.button("Regenerate this report now (about 5 seconds)", key="adj_regen"):
        with st.spinner("Generating..."):
            import subprocess as _sp
            # Console-triggered runs PUBLISH (Jiho 8/3, same rule the Control
            # Panel follows). Without this the report rebuilt locally and never
            # reached SharePoint, while the page claimed it had.
            _env = dict(_os.environ, MPR_PERIOD=period, MPR_PUBLISH="1")
            r = _sp.run([_sys.executable,
                         str(PROJECT_ROOT / "reports" /
                             "membership_performance_tracker" / "runner.py"),
                         "--from-cache"],
                        cwd=str(PROJECT_ROOT), env=_env,
                        capture_output=True, text=True)
        if r.returncode == 0:
            st.success("Report regenerated and published to SharePoint — "
                       "the correction is on it now.")
        else:
            st.error(f"Generation failed:\n{(r.stderr or r.stdout)[-600:]}")


if nav in _LEGACY_NAV:
    st.session_state.nav = _LEGACY_NAV[nav]
    st.rerun()

if   nav == "control":       page_control_panel()
elif nav == "mpr.tracker":   page_mpr_tracker()
elif nav == "mpr.trace":     page_mpr_trace()
elif nav == "mpr.adjust":    page_mpr_adjust()
elif nav == "pen.report":    page_pen_report()
elif nav == "dd.combined":   page_dd_combined()
elif nav == "dues.report":   page_dues()
elif nav == "admin":         page_admin()
elif nav == "schedule":      page_schedule()
else:                        page_control_panel()
