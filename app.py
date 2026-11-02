import os
import json
import sqlite3
import warnings
import time
import random
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from datetime import date as _date, timedelta as _timedelta
import base64
import hashlib
import hmac
import re
import sqlite3 as _sqlite3_real

LICENSE_READ_ONLY = False   # True while an expired licence is in force (see _refresh_license)
# ---- DEMO BUILD (free trial copy) ----
DEMO_BUILD = True            # this file is the downloadable demo; a valid licence code turns it into the full program
DEMO_DAYS = 30               # days from first run
DEMO_MAX_ASSETS = 8          # units of the user's own (adding, importing, copying, OR editing/renaming a sample unit); the untouched sample data does not count
DEMO_MAX_GROUPS = 5          # asset groups of the user's own (new groups, or a renamed sample group)
DEMO_URL = "www.bioship.ca"
DEMO = {"active": False, "expired": False, "days_left": 0, "start": "", "end": ""}
LICENSE_INFO = {"state": "none", "licensee": "", "edition": "", "sites": 0, "issued": "", "expires": "", "id": "", "message": "", "source": ""}

def _readonly_stop(exc):
    """If a write was refused because the app is read-only, show a plain message and stop the page
    instead of a raw database error. Any other database error is left alone."""
    if "readonly" not in str(exc).lower():
        return
    if LICENSE_READ_ONLY and DEMO.get("expired"):
        msg = (f"The {DEMO_DAYS}-day demo has ended, so changes can't be saved. Your data is safe and is kept. "
               f"Buy a licence at {DEMO_URL} and paste the code under **Users & Security**; everything you entered carries over.")
    elif LICENSE_READ_ONLY:
        msg = ("This licence has expired, so changes can't be saved. Your data is safe. "
               "Enter a renewed licence code under **Users & Security**.")
    else:
        msg = "This account is read-only, so changes can't be saved."
    st.error(msg)
    st.stop()

class _GuardedCursor(_sqlite3_real.Cursor):
    def execute(self, *args, **kwargs):
        try:
            return super().execute(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise
    def executemany(self, *args, **kwargs):
        try:
            return super().executemany(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise
    def executescript(self, *args, **kwargs):
        try:
            return super().executescript(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise

class _GuardedConnection(_sqlite3_real.Connection):
    def cursor(self, factory=_GuardedCursor):
        return super().cursor(factory)
    def execute(self, *args, **kwargs):
        try:
            return super().execute(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise
    def executemany(self, *args, **kwargs):
        try:
            return super().executemany(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise
    def executescript(self, *args, **kwargs):
        try:
            return super().executescript(*args, **kwargs)
        except _sqlite3_real.OperationalError as e:
            _readonly_stop(e)
            raise

class _SqliteProxy:
    """Stands in for the sqlite3 module. Identical, except that connections opened while a
    read-only ('viewer') account is signed in, or while the licence has expired, refuse every write
    (and say so politely instead of showing a database error)."""
    def __getattr__(self, name):
        return getattr(_sqlite3_real, name)
    def connect(self, *args, **kwargs):
        kwargs.setdefault("factory", _GuardedConnection)
        conn = _sqlite3_real.connect(*args, **kwargs)
        try:
            if st.session_state.get("auth_role") == "viewer" or LICENSE_READ_ONLY:
                conn.execute("PRAGMA query_only = ON")
        except Exception:
            pass
        return conn
sqlite3 = _SqliteProxy()

# Page Configuration
st.set_page_config(
    page_title="An Ounce of Prevention",
    page_icon="🚀",
    layout="wide",
)

warnings.filterwarnings("ignore")
pd.set_option("future.no_silent_downcasting", True)

def get_image_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return ""

def ask_claude(label, prompt, note=True):
    """A small link that opens a new Claude chat (claude.ai) with a general question already typed in.
    Only the generic text below is sent. Nothing from the database, journal or licence is ever added.
    The person reads and can change the text before sending."""
    from urllib.parse import quote as _q
    from html import escape as _html_escape
    _url = "https://claude.ai/new?q=" + _q(prompt)
    st.markdown(f'<a href="{_url}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:6px 14px;'
                f'border:1px solid #2e7d32;border-radius:6px;color:#2e7d32;text-decoration:none;font-weight:600;font-size:0.9rem;">'
                f'💬 {_html_escape(label)}</a>', unsafe_allow_html=True)
    if note:
        st.caption("Opens Claude (claude.ai) in a new tab; you can edit the question first. Ounce of Prevention is independent and is not affiliated with or endorsed by Anthropic. "
                   "Do not paste passwords, account numbers, private journal text or other people's personal data. AI makes mistakes: check anything that matters, especially health and safety.")

def title_row(title, key):
    """Page title on the left, a regular-size Switchboard button on the right (same on every screen)."""
    _c1, _c2 = st.columns([5, 1.3], gap="small")
    with _c1: st.subheader(title)
    with _c2:
        if st.button("Switchboard", key=key, use_container_width=True):
            st.session_state.view_mode_override = "Switchboard"; st.rerun()

st.markdown(
    """
    <style>
    html, body, [class*="css"] { font-family: Arial, sans-serif; font-size: 12.0pt; }
    [data-testid="stSidebar"] { min-width: 235px !important; max-width: 260px !important; }
    .block-container, [data-testid="block-container"], .main .block-container { padding-top: 3.0rem !important; padding-bottom: 2rem !important; padding-left: 1.6rem !important; padding-right: 1.6rem !important; max-width: 100% !important; }
    button[data-baseweb="tab"] p, [role="tab"] p { font-size: 12.0pt !important; font-weight: bold !important; }
    [data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] span { font-size: 15.0pt !important; font-weight: 800 !important; color: #000000 !important; }
    .stRadio p, div[role="radiogroup"] label { white-space: nowrap !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label [data-testid="stMarkdownContainer"] p { font-size: 1.06rem !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] { gap: 0rem !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label { padding-top: 3.5px !important; padding-bottom: 3.5px !important; margin-bottom: 0px !important; min-height: 0 !important; align-items: center !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child { transform: scale(0.55); margin-right: -0.3rem !important; }
    [data-testid="stSidebar"] div[role="radiogroup"] label [data-testid="stMarkdownContainer"] p { line-height: 1.25 !important; margin: 0 !important; }
    [class*="st-key-sm_meter_"] [data-testid="stWidgetLabel"] p, [class*="st-key-chk_disregard_"] label p { font-size: 14.0pt !important; }
    .legacy-section-box { border: 2px solid #000000; padding: 10px 12px; margin-bottom: 15px; background-color: #ffffff; }
    .legacy-section-title { font-weight: bold; text-decoration: underline; font-size: 11.5pt; margin-bottom: 8px; color: #000000; }
    .access-form-container { background-color: #e0e0e0; border: 2px solid #999999; padding: 12px 15px; border-radius: 4px; margin-bottom: 15px; }
    .legacy-sign-off-box { border: 2px solid #000000; padding: 15px; margin-top: 25px; background-color: #ffffff; page-break-inside: avoid; break-inside: avoid; }
    .wo-unit-card { border: 2px solid #333333; padding: 15px; margin-bottom: 20px; background-color: #ffffff; border-radius: 4px; page-break-inside: avoid; break-inside: avoid; }
    div[data-testid="stButton"] { display: flex; justify-content: center; align-items: center; width: 100%; }
    
    /* Standard Flat Green Button Styling for all UI functions - STANDARD 44px MINIMUM HEIGHT; GROWS FOR A SECOND LINE OF TEXT */
    div.stButton > button, div.stDownloadButton button, div.stFormSubmitButton > button {
        background-color: #1b5e20 !important; background-image: none !important; color: #ffffff !important;
        border-radius: 6px !important; border: 1px solid #124116 !important; padding: 6px 10px !important;
        height: auto !important; min-height: 44px !important; width: 100% !important; margin: 0 auto !important; 
        display: flex !important; justify-content: center !important; align-items: center !important;
        box-shadow: none !important; text-shadow: none !important;
    }
    div.stButton > button p, div.stDownloadButton button p, div.stFormSubmitButton > button p {
        font-size: 12.5pt !important; font-weight: normal !important; color: #ffffff !important; margin: 0 !important; white-space: normal !important; 
    }
    div.stButton > button:hover, div.stDownloadButton button:hover, div.stFormSubmitButton > button:hover {
        background-color: #124116 !important; border-color: #0c2b0e !important;
    }
    
    /* Drop-down boxes: same 44px height as the buttons, pale green with a green border so they read as drop-downs */
    [data-testid="stSelectbox"] [data-baseweb="select"] {
        min-height: 44px !important; background-color: #f4f8f4 !important; border: 1px solid #1b5e20 !important; border-radius: 6px !important; box-sizing: border-box !important;
    }
    [data-testid="stSelectbox"] [data-baseweb="select"] > div {
        min-height: 42px !important; background-color: transparent !important; border: none !important; box-shadow: none !important; align-items: center !important;
    }
    [data-testid="stSelectbox"] [data-baseweb="select"] > div > div { background-color: transparent !important; }
    /* Dedicated Primary Action specifically isolating the Black Navigation Arrows */
    div.stButton > button[kind="primary"] { 
        background-color: #ffffff !important; border: 2px solid #000000 !important; border-radius: 6px !important; color: #000000 !important;
        width: 100% !important; min-width: 0 !important; min-height: 0 !important; height: 40px !important; padding: 0 !important;
    }
    div.stButton > button[kind="primary"]:hover { 
        background-color: #e0e0e0 !important; border-color: #000000 !important; color: #000000 !important;
    }
    div.stButton > button[kind="primary"] p {
        font-size: 14.0pt !important; font-weight: bold !important; color: #000000 !important; line-height: 1 !important;
    }

    /* True Folder Tabs Styling */
    div[data-baseweb="tab-list"] { gap: 4px; padding-bottom: 0px; border-bottom: 2px solid #ccc; }
    button[data-baseweb="tab"] {
        background-color: #e0e0e0 !important;
        border-radius: 6px 6px 0 0 !important;
        border: 1px solid #b0b0b0 !important;
        border-bottom: none !important;
        padding: 8px 10px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #ffffff !important;
        border-top: 3px solid #1b5e20 !important;
        border-bottom: 2px solid #ffffff !important;
        color: #1b5e20 !important;
        margin-bottom: -2px !important;
        z-index: 10;
    }
    div[data-baseweb="tab-highlight"] { display: none !important; }
    /* same folder-tab look for newer Streamlit versions (standard ARIA roles) */
    div[role="tablist"] { gap: 4px; padding-bottom: 0px; border-bottom: 2px solid #ccc; }
    [role="tab"] {
        background-color: #e0e0e0 !important;
        border-radius: 6px 6px 0 0 !important;
        border: 1px solid #b0b0b0 !important;
        border-bottom: none !important;
        padding: 8px 10px !important;
    }
    [role="tab"][aria-selected="true"] {
        background-color: #ffffff !important;
        border-top: 3px solid #1b5e20 !important;
        border-bottom: 2px solid #ffffff !important;
        color: #1b5e20 !important;
        margin-bottom: -2px !important;
        z-index: 10;
    }
    div[role="tablist"] [data-testid="stTabHighlight"], div[role="tablist"] [class*="highlight"] { display: none !important; }
    
    [data-testid="stDataFrame"] th, [data-testid="stDataEditor"] th, [data-testid="stDataFrame"] td, [data-testid="stDataEditor"] td, [data-testid="stDataFrame"] div, [data-testid="stDataEditor"] div { text-align: left !important; justify-content: flex-start !important; }
    [data-testid="stDataFrame"] th *, [data-testid="stDataEditor"] th * { color: #000000 !important; font-weight: 800 !important; }
    [data-testid="stDataFrame"] th svg, [data-testid="stDataEditor"] th svg { display: none !important; }
    
    /* small grey notes (captions) were hard to read: darker and a little larger */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: inherit !important; opacity: 0.92; font-size: 0.95rem !important; }
    .st-key-sw_habit button { border: 3px solid #f1c40f !important; box-shadow: 0 0 0 2px #1e8449; min-height: 3rem; }
    .st-key-sw_habit button p { font-size: 1.15rem !important; font-weight: 800 !important; }
    /* Habit builder: one size bigger and as dark as possible */
    [data-testid="stExpander"]:has(.hb-marker) p, [data-testid="stExpander"]:has(.hb-marker) li, [data-testid="stExpander"]:has(.hb-marker) label,
    [data-testid="stExpander"]:has(.hb-marker) [data-testid="stCaptionContainer"], [data-testid="stExpander"]:has(.hb-marker) [data-testid="stCaptionContainer"] *,
    [data-testid="stExpander"]:has(.hb-marker) [data-baseweb="select"] *, [data-testid="stExpander"]:has(.hb-marker) [data-testid="stRadio"] * { font-size: 1.1rem !important; color: #000000 !important; opacity: 1 !important; }
    [data-testid="stExpander"]:has(.hb-marker) strong { font-weight: 800 !important; }
    /* Darker text and clearer borders (easier on tired eyes) */
    textarea:disabled, input:disabled { -webkit-text-fill-color: #111 !important; color: #111 !important; opacity: 1 !important; }
    [data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="select"] > div { border: 1px solid #6b6b6b !important; }
    [data-testid="stDataFrame"] { border: 1px solid #555 !important; border-radius: 4px; }
    .print-only-container { display: none; }
    .screen-only-container { display: block; }
    .demo-mark { position: fixed; top: 38%; left: 0; width: 100%; text-align: center; font-size: 190px; font-weight: 900; color: rgba(150,150,150,0.13); transform: rotate(-30deg); pointer-events: none; z-index: 0; letter-spacing: 12px; }
    .app-footer { text-align: center; font-size: 9.5pt; color: #666666; margin-top: 40px; margin-bottom: 20px; border-top: 1px solid #dddddd; padding-top: 15px; }
    
    @media print {
        header, footer, [data-testid="stSidebar"], [data-testid="stToolbar"], .app-footer, .stApp > header { display: none !important; }
        div[data-testid="stElementContainer"]:has([data-testid="stSelectbox"]), div[data-testid="stElementContainer"]:has([data-testid="stNumberInput"]), div[data-testid="stElementContainer"]:has([data-testid="stButton"]), div[data-testid="stElementContainer"]:has(.screen-only-container), div[data-testid="stDataEditor"], div[data-testid="stElementContainer"]:has([data-testid="stDataFrame"]) { display: none !important; }
        .screen-only-container, [data-testid="stSelectbox"], [data-testid="stNumberInput"], [data-testid="stButton"], [data-testid="stDataEditor"], [data-testid="stDataFrame"], .stDataFrame { display: none !important; }
        [data-testid="stExpander"] details summary { padding: 4px 8px !important; min-height: 0 !important; height: auto !important; }
        [data-testid="stExpander"] details summary p { font-size: 9.5pt !important; }
        [data-testid="stExpander"] svg { display: none !important; }
        div[data-testid="stExpander"] { margin-bottom: 2px !important; }
        .print-asset-header { margin-left: 8px !important; }
        html, body, .stApp, .main, [data-testid="stAppViewBlockContainer"], .block-container { height: auto !important; min-height: 0 !important; padding: 0 !important; margin: 0 !important; overflow: visible !important; }
        .main .block-container { padding-top: 0 !important; margin-top: 0 !important; }
        .print-only-container { display: block !important; }
        body, .stApp { background-color: #ffffff !important; }
        @page { size: letter portrait; margin: 0.35in; }
    }
    </style>
""",
    unsafe_allow_html=True,
)

DB_FILENAME = "OunceOfPrevention.db"
LEGACY_DB_PATH = r"C:\Projects\Ounce\OunceOfPrevention.db"   # original developer location

def resolve_db_path():
    """Pick where the database lives. First match wins:
       1. OUNCE_DB_PATH environment variable (a full file path, or a folder)
       2. "database_path" in ounce_config.json, saved next to this script
       3. The original C:\\Projects\\Ounce database, if one already exists there
          (so existing installs keep their data)
       4. A per-user data folder: %LOCALAPPDATA%\\OunceOfPrevention on Windows,
          ~/.local/share/OunceOfPrevention elsewhere."""
    def _as_file(p):
        p = os.path.expanduser(os.path.expandvars(str(p).strip()))
        return os.path.join(p, DB_FILENAME) if (os.path.isdir(p) or not os.path.splitext(p)[1]) else p

    env_val = os.environ.get("OUNCE_DB_PATH", "").strip()
    if env_val:
        return _as_file(env_val)

    try:
        cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ounce_config.json")
        if os.path.isfile(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as fh:
                cfg_val = str(json.load(fh).get("database_path", "")).strip()
            if cfg_val:
                return _as_file(cfg_val)
    except Exception:
        pass   # a bad config file must never stop the app; fall through to defaults

    if os.path.isfile(LEGACY_DB_PATH):
        return LEGACY_DB_PATH

    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "OunceOfPrevention", DB_FILENAME)

DB_PATH = resolve_db_path()

def _config_value(key):
    """Read one value from ounce_config.json (next to this script); '' if missing or unreadable."""
    try:
        cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ounce_config.json")
        if os.path.isfile(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as fh:
                return str(json.load(fh).get(key, "")).strip()
    except Exception:
        pass
    return ""

# Name printed at the bottom of every PDF. Set "licensed_to" in ounce_config.json
# (or the OUNCE_LICENSED_TO environment variable) when a licence is issued.
LICENSED_TO = os.environ.get("OUNCE_LICENSED_TO", "").strip() or _config_value("licensed_to") or "Evaluation copy - not licensed"

def draw_licensee_line(canvas):
    """Company name in the top-left corner (when set under Settings or licensed) and a small 'Licensed to' line bottom-left."""
    canvas.saveState()
    try: _company = get_company_name()
    except Exception: _company = ""
    if _company:
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillGray(0.2)
        canvas.drawString(30, canvas._pagesize[1] - 20, _company[:80])
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillGray(0.35)
    canvas.drawString(30, 16, f"Licensed to: {LICENSED_TO}")
    canvas.restoreState()
    if DEMO.get("active") or DEMO.get("expired"):
        canvas.saveState()
        try:
            w, h = canvas._pagesize
            canvas.setFillColorRGB(0.5, 0.5, 0.5)
            canvas.setFillAlpha(0.13)      # see-through, so the text under it stays readable
            canvas.setFont("Helvetica-Bold", 110)
            canvas.translate(w / 2, h / 2); canvas.rotate(45)
            canvas.drawCentredString(0, -30, "DEMO")
            canvas.rotate(-45); canvas.translate(-w / 2, -h / 2)
            canvas.setFillAlpha(1.0); canvas.setFillGray(0.35); canvas.setFont("Helvetica-Bold", 8)
            canvas.drawRightString(w - 30, 16, f"DEMO COPY - {DEMO_URL}")
        finally:
            canvas.restoreState()

FLAC_TRACKS = [
    "02 - Piano Concerto No.1 In C Major, Op.15 - Largo.flac",
    "02. [John McCabe, piano] II. Largo.flac",
    "05 - II- Largo.flac",
    "08 - II. Adagio ovvero largo.flac",
    "16 - Klavierstucke, Op.118 - No.6 Intermezzo. Andante, largo e mesto.flac",
    "Chopin - Preludes - Largo - E minor.flac",
    "Georg_Philipp_Telemann_-_SC18_Viola_Concerto_in_G_major,_51_G9_-_1._Largo.flac",
    "String Quartet in B flat major Op.9 no.5 - III Largo Cantabile.flac",
    "String Quartet in G minor Op.74 no.3 - II Largo assai.flac",
    "Symphony No.53 in D major 'L'Imperiale' - I Largo-maestoso-vivace.flac"
]

MAINTENANCE_PROTOCOLS = [
    "Preventive Maintenance (PM)",
    "Corrective / Reactive Maintenance",
    "Predictive Maintenance (PdM)"
]

PROTOCOL_DETAILS = {
    "All": ["All"],
    "Preventive Maintenance (PM)": [
        "All",
        "Time or usage-based scheduling.",
        "Calendar dates, operational hours, or mileage milestones.",
        "Highly planned and structured.",
        "Minimize asset degradation through regular upkeep.",
        "Oil changes, filter replacements, routine calibrations, belt tightening.",
        "High-value, critical assets with known wear-and-tear lifespans."
    ],
    "Corrective / Reactive Maintenance": [
        "All",
        "Run-to-failure emergency repair.",
        "A machine stops working, breaks down, or behaves unsafely.",
        "Unplanned, urgent, and high-stress.",
        "Restore an offline asset to production as fast as possible.",
        "Rebuilding broken gearboxes, patching leaks, replacing blown fuses.",
        "Low-cost, non-critical assets that do not stop production if they fail."
    ],
    "Predictive Maintenance (PdM)": [
        "All",
        "Condition-based real-time monitoring.",
        "Sensor data anomalies (e.g., heat spikes, abnormal vibrations).",
        "Highly planned based on early warning indicators.",
        "Fix an asset exactly before it fails, maximizing component life.",
        "Laser alignments, thermal imaging scans, oil analysis, sensor replacement.",
        "High-criticality, bottleneck assets where downtime costs thousands per minute."
    ]
}

# ==========================================================================================
# BUILT-IN SAMPLE ASSET GROUPS
# One entry per group: a unit-ID prefix, a model-name pattern, 5 attribute labels, 6 part headings, 3 sample attributes,
# 5 rows of daily checklist items (two per row) and the scheduled maintenance tasks. The schedules are EXAMPLES based on
# general industry practice; always follow the manufacturer's manual and your local regulations for real equipment.
# Task fields: (tab, name, days between, meter between [hours/km], man-hours, description, who, safety, parts cost, consumables, tools)
# ==========================================================================================
SAMPLE_GROUPS = {
    'Vehicles': dict(
        prefix='TRK',
        model='Fleet Truck T-{i} (5-Ton Cargo)',
        labels=('Gross Vehicle Weight (kg)', 'Engine (L / HP)', 'Axle Configuration', 'Fuel Type', 'Plate Number'),
        parts=('Engine & Cooling:', 'Transmission & Driveline:', 'Brakes (Air/Hydraulic):', 'Suspension & Steering:', 'Electrical & Lighting:', 'Cab & Safety Equipment:'),
        attrs=[('Engine', '6.7 L diesel, 240 HP', 'Emissions equipped'), ('Axles', '4x2, dual rear wheels', 'Rated payload about 5 tons'), ('Brakes', 'Air brakes', 'Drain the tanks every day')],
        # Pre-trip checklist for a 5-ton truck on a long trip. Two items per row; "|Monday" makes an item weekly.
        checklist=[
            ('Engine oil level & condition', 'Coolant level, hoses & radiator'),
            ('Brake fluid & power steering fluid levels', 'Fuel level (fill at half a tank), no leaks or water in separator'),
            ('Tires: cold pressure, tread, sidewalls & lug nuts (all positions, duals)', 'Spare tire, jack & wheel wrench secured'),
            ('Air tanks drained; air pressure builds and holds', 'Parking brake holds; service brake pedal firm'),
            ('Lights: head, brake, turn, hazard, marker, reverse', 'Horn, backup alarm & wipers; washer fluid full'),
            ('Mirrors, windshield & windows clean and clear', 'Gauges and warning lights normal at start-up'),
            ('Belts, hoses & battery terminals secure', 'Look under the truck: oil, coolant, fuel or brake fluid leaks'),
            ('Springs, U-bolts, steering linkage & driveshaft check', 'Exhaust system secure, no leaks or rubbing'),
            ('Cargo secured: tie-downs, tarps, tailgate & doors latched', 'Load within weight rating (axle and gross weights)'),
            ('Emergency kit: triangles, flares, first aid, flashlight', 'Fire extinguisher charged and in reach'),
            ('Documents: licence, registration, insurance, permits & logbook', 'Route plan: fuel and rest stops, weather, road closures'),
            ('Spare fluids, jumper cables, tow strap & basic tool kit on board', 'Seat belts, seat position & cab free of loose items'),
            ('Grease chassis, driveshaft & steering fittings|Monday', 'Re-torque wheel lug nuts, dual wheels|Monday'),
            ('Check air filter restriction gauge|Wednesday', 'Clean battery terminals & check charge|Friday'),
        ],
        tasks=[
            ('Prevention A', 'Engine oil & filter change', 120, 12000, 1.5, 'Drain oil, replace the oil filter, check for leaks, reset the service interval.', 'Mechanic', 'Hot fluids; wheel chocks', 140.0, 'Oil, filter', 'Drain pan, filter wrench'),
            ('Prevention A', 'Grease chassis, driveshaft & steering', 45, 5000, 0.5, 'Grease all chassis fittings, slip yoke, U-joints and steering linkage.', 'Mechanic', 'None', 12.0, 'Grease', 'Grease gun'),
            ('Prevention A', 'Tire rotation, pressure & tread inspection', 90, 10000, 1.0, 'Rotate tires per the pattern, set pressures cold, measure tread, check for cuts and bulges.', 'Mechanic', 'Wheels chocked; truck on stands', 0.0, 'None', 'Gauge, torque wrench, jack stands'),
            ('Prevention A', 'Fuel filter & water separator service', 180, 20000, 1.0, 'Replace fuel filter, drain and clean the water separator, check lines for leaks.', 'Mechanic', 'Fuel; no ignition sources', 65.0, 'Fuel filter', 'Filter wrench'),
            ('Prevention B', 'Brake inspection, adjustment & air-system leakdown test', 180, 20000, 2.5, 'Measure lining, check drums, adjust slack adjusters, test air system leakdown and parking brake hold.', 'Mechanic', 'Wheels chocked; air bled', 150.0, 'Brake parts as needed', 'Gauges, jacks'),
            ('Prevention B', 'Suspension, steering & wheel bearing inspection', 180, 25000, 2.0, 'Check springs, shackles, U-bolts, tie rods and kingpins; check wheel bearing play and seals.', 'Mechanic', 'Truck on stands', 80.0, 'Grease, seals as needed', 'Pry bar, dial gauge'),
            ('Prevention B', 'Air filter inspection & replacement', 180, 20000, 0.5, 'Inspect the air filter and replace it if the restriction gauge shows the limit.', 'Mechanic', 'None', 45.0, 'Air filter', 'Hand tools'),
            ('Prevention B', 'Long-trip readiness service', 180, 15000, 3.0, 'Before an extended trip: fluids, tires incl. spare, brakes, belts and hoses, lights, battery load test, emergency kit and documents.', 'Mechanic', 'Hot fluids; wheel chocks', 120.0, 'Fluids, bulbs, wipers', 'Battery tester, gauges'),
            ('Prevention C', 'Coolant, belts, hoses & battery service', 365, 40000, 1.5, 'Test coolant freeze point and condition, replace belts and hoses as needed, clean and load test the batteries.', 'Mechanic', 'Hot coolant', 90.0, 'Coolant', 'Coolant tester, battery tester'),
            ('Prevention C', 'Transmission fluid & filter service', 365, 60000, 2.0, 'Drain and refill transmission fluid, replace the filter, inspect for metal on the magnetic plug.', 'Mechanic', 'Hot fluids', 260.0, 'Transmission fluid, filter', 'Drain pan'),
            ('Prevention C', 'Axle & differential fluid change', 365, 60000, 1.5, 'Drain and refill the rear axle, inspect the magnetic plug and breathers.', 'Mechanic', 'Hot fluids', 120.0, 'Gear oil', 'Drain pan'),
            ('Prevention C', 'Wheel alignment & steering geometry check', 365, 50000, 1.5, 'Check and adjust alignment; inspect tire wear patterns for signs of misalignment.', 'Alignment Technician', 'Truck on alignment rack', 130.0, 'None', 'Alignment rack'),
            ('Compliance', 'Annual commercial vehicle safety inspection', 365, 0, 2.0, 'Complete the annual safety inspection and keep the certificate with the vehicle record.', 'Certified Inspector', 'Inspection pit or hoist rules', 150.0, 'None', 'Inspection checklist'),
            ('Compliance', 'Annual fire extinguisher service & emergency kit renewal', 365, 0, 0.5, 'Have the extinguisher inspected, replace expired first-aid items, flares and batteries in the kit.', 'Certified Inspector', 'None', 70.0, 'First-aid items, flares', 'Inspection tag'),
        ]),
    'Mining': dict(
        prefix='MINE',
        model='Haul Truck HT-{i} (90-tonne)',
        labels=('Payload (tonnes)', 'Engine Power (kW)', 'Tire Size', 'Fuel Type', 'Fleet Number'),
        parts=('Engine & Drive Motors:', 'Crushing / Processing Equipment:', 'Hydraulics & Hoists:', 'Frame & Structure:', 'Controls & Safety Systems:', 'Conveyors & Material Handling:'),
        attrs=[('Payload', '90 tonnes', 'Rigid frame haul truck'), ('Engine', '1,000 kW diesel', 'Tier-rated'), ('Tires', '27.00R49', 'Rotated at every B service')],
        checklist=[('Inspect conveyor belt splices & tracking', 'Check primary crusher wear liners'), ('Verify haul truck payload strut pressure', 'Test excavator boom pin auto-lube'), ('Check pump bearing oil & seals', 'Inspect slurry pump impeller clearance'), ('Verify ventilation fan airflow', 'Test emergency stop pull-cords'), ('Check dust suppression system', 'Inspect guards on rotating equipment')],
        tasks=[
            ('Prevention A', 'Daily-use lubrication round', 7, 150, 1.0, 'Grease boom pins, wheel bearings and conveyor idlers on the route sheet.', 'Lube Technician', 'Machine locked out', 20.0, 'Grease', 'Grease gun'),
            ('Prevention A', 'Conveyor belt & idler inspection', 14, 300, 1.5, 'Walk the belt: splices, tracking, idler condition, skirting and pull-cords.', 'Millwright', 'LOTO; guards on', 0.0, 'None', 'Hand tools'),
            ('Prevention B', 'Engine, hydraulic & final drive oil sampling', 90, 500, 2.0, 'Take oil samples, change filters, inspect hoses and leaks.', 'Mechanic', 'Hot fluids', 250.0, 'Filters, oil', 'Sampling kit'),
            ('Prevention B', 'Crusher liner & bearing inspection', 90, 500, 3.0, 'Measure liner wear, check bearing temperature and lubrication flow.', 'Millwright', 'LOTO; confined space rules', 100.0, 'Grease', 'Gauges'),
            ('Prevention C', 'Major component inspection (frame, hoist, drive)', 365, 4000, 12.0, 'Inspect frame welds, hoist cylinders, final drives and structural pins.', 'Master Mechanic', 'Suspended load', 1500.0, 'Seals, bearings', 'Heavy tools'),
            ('Compliance', 'Annual hoist, rope & pressure vessel inspection', 365, 0, 4.0, 'Certified inspection of hoists, wire ropes and air receivers.', 'Certified Inspector', 'Fall protection', 400.0, 'None', 'Inspection tools'),
        ]),
    'Marine': dict(
        prefix='MAR',
        model='Work Boat WB-{i} (12 m)',
        unit_names={5: 'Hydro-Terran Drive Vehicle - patent pending'},
        labels=('Length (m)', 'Main Engine (HP)', 'Propulsion Type', 'Fuel Capacity (L)', 'Registration No.'),
        parts=('Main Engine & Gearbox:', 'Propeller Shaft & Seals:', 'Steering & Hydraulics:', 'Hull & Anodes:', 'Electrical & Battery Bank:', 'Safety & Fire Equipment:'),
        attrs=[('Hull', 'Aluminum, 12 m', 'Anodes checked every haul-out'), ('Main Engine', '2 x 400 HP diesel', 'Raw-water cooled'), ('Safety gear', 'Flares, PFDs, fire extinguishers', 'Dates recorded at each inspection')],
        checklist=[('Verify main engine lube oil level & pressure', 'Inspect hull sacrificial zinc anodes'), ('Check propeller shaft seal for drips', 'Test steering gear & hydraulics'), ('Verify bilge pump operation & alarms', 'Inspect radar & VHF antenna mounts'), ('Check sea water strainers', 'Test navigation lights & horn'), ('Verify battery voltage & connections', 'Inspect fire extinguishers & PFDs')],
        tasks=[
            ('Prevention A', 'Engine oil, strainer & belt check', 30, 100, 1.0, 'Check oil level, clean raw-water strainers, inspect belts and hoses.', 'Marine Mechanic', 'Engine off', 15.0, 'Oil', 'Hand tools'),
            ('Prevention A', 'Bilge pump & alarm test', 30, 0, 0.5, 'Test float switches, pumps and high-water alarms.', 'Operator', 'None', 0.0, 'None', 'None'),
            ('Prevention B', 'Engine oil & fuel filter service', 180, 250, 2.5, 'Change engine oil, oil filter and fuel filters; replace impeller if due.', 'Marine Mechanic', 'Hot fluids', 140.0, 'Oil, filters, impeller', 'Drain pump'),
            ('Prevention B', 'Steering, shaft seal & cutlass bearing check', 180, 250, 2.0, 'Inspect steering linkage and hydraulics, shaft seal and cutlass bearing wear.', 'Marine Mechanic', 'None', 50.0, 'Grease', 'Gauges'),
            ('Prevention C', 'Haul-out: hull, anodes & through-hull fittings', 365, 0, 12.0, 'Inspect hull, replace anodes, service seacocks and through-hull fittings, repaint antifouling as needed.', 'Marine Technician', 'Blocking and ladder safety', 600.0, 'Anodes, paint', 'Hand tools'),
            ('Compliance', 'Annual vessel safety equipment inspection', 365, 0, 2.0, 'Check flares, extinguishers, PFDs, life raft service dates and navigation lights.', 'Certified Inspector', 'None', 120.0, 'Flares, PFDs as needed', 'Checklist'),
        ]),
    'Aircraft': dict(
        prefix='AERO',
        model='Light Aircraft N{i}00A (Piston Single)',
        units=10,
        unit_names={1: 'Cessna 172S Skyhawk (Piston Single)', 2: 'Cessna 182T Skylane (Piston Single)', 3: 'Piper PA-28-181 Archer (Piston Single)',
                    4: 'Beechcraft A36 Bonanza (Piston Single)', 5: 'Mooney M20J (Piston Single)', 6: 'Diamond DA40 Star (Piston Single)',
                    7: 'Cirrus SR22 (Piston Single)', 8: 'Piper PA-32 Cherokee Six (Piston Single)', 9: 'Piper PA-34 Seneca V (Piston Twin)',
                    10: 'Cessna 310R (Piston Twin)'},
        labels=('Tail Number', 'Aircraft Type (Fixed/Rotary)', 'Engine Config (Prop/Jet)', 'Fuel Capacity (Gal)', 'Cruising Altitude (Ft)'),
        parts=('Airframe & Fuselage:', 'Powerplant & Nacelle:', 'Landing Gear & Hydraulics:', 'Avionics & Flight Deck:', 'Flight Controls (Aileron/Elevator/Rudder):', 'Cabin & Emergency Equipment:'),
        attrs=[('Engine', 'Piston, 180 HP', 'Hours tracked on the meter'), ('Fuel', '100LL, 56 gal', 'Sumped before each flight'), ('Avionics', 'IFR-equipped', 'Transponder check on a schedule')],
        checklist=[('Verify aircraft documents on board', 'Remove control locks & pitot covers'), ('Check fuel quantity vs. visual and sump fuel', 'Test annunciator panel & warning lights'), ('Inspect tires, brakes & landing gear', 'Check oil level and for leaks'), ('Inspect control surfaces and hinges', 'Check lights, beacon & strobes'), ('Verify fire extinguisher & first aid kit', 'Check ELT and seat belts')],
        tasks=[
            ('Prevention A', 'Pre-flight inspection record', 1, 1, 0.5, 'Complete the pre-flight walk-around and record squawks.', 'Pilot', 'Aircraft chocked, engine off', 0.0, 'None', 'Checklist'),
            ('Prevention A', 'Oil level check & top-up', 7, 10, 0.3, 'Check engine oil level and top up as needed; record quantity added.', 'Pilot / Mechanic', 'Engine off', 15.0, 'Oil', 'None'),
            ('Prevention B', '50-hour oil & filter change', 120, 50, 2.0, 'Change engine oil and filter, cut open the filter, inspect for metal, clean screens.', 'Licensed Mechanic', 'Engine off, magnetos grounded', 90.0, 'Oil, filter', 'Hand tools'),
            ('Prevention B', '100-hour inspection items: spark plugs & cylinders', 240, 100, 6.0, 'Inspect and rotate spark plugs, compression test cylinders, check exhaust and baffles.', 'Licensed Mechanic', 'Engine off, magnetos grounded', 220.0, 'Spark plugs, gaskets', 'Compression tester'),
            ('Prevention C', 'Annual inspection', 365, 0, 24.0, 'Complete the annual airworthiness inspection of airframe, engine, propeller and systems.', 'Licensed Inspector (AME)', 'Aircraft on jacks; follow shop rules', 800.0, 'As required', 'Inspector tools'),
            ('Compliance', 'ELT battery check & transponder / altimeter checks', 365, 0, 2.0, 'Check ELT operation and battery date, plus the periodic transponder and altimeter checks required for IFR flight.', 'Avionics Technician', 'None', 200.0, 'ELT battery', 'Test equipment'),
        ]),
    'Drilling Rigs': dict(
        prefix='DRILL',
        model='Triple-Double Automated Drilling Rig {i}',
        labels=('Mast Rating (daN)', 'Drawworks Power (HP)', 'Mud Pump Cap (L/min)', 'Hook Load (lbs)', 'Fuel Type'),
        parts=('Powerplant / Prime Mover:', 'High Pressure Fluid End:', 'Hydraulic / Power End:', 'Mast / Structural Frame:', 'Control Cab / Instrumentation:', 'BOP / Pressure Control:'),
        attrs=[('Mast Rating', '42 meters', 'Triple mast'), ('Drawworks', '1500 HP', 'AC Drive'), ('Top Drive', 'TDS-11', '500 Ton')],
        checklist=[('Check crown & traveling block greasing', 'Inspect drawworks brake linkage'), ('Verify mud pump fluid end expendables', 'Check shaker screens & motors'), ('BOP accumulator pre-charge pressure check', 'Inspect top drive torque rails'), ('Check generator lube oil & coolant', 'Test H2S and LEL gas detectors'), ('Verify fall protection gear & escape line', 'Inspect pipe spinner / iron roughneck')],
        tasks=[
            ('Prevention A', 'Daily rig lubrication round', 1, 24, 1.0, 'Grease crown, traveling block, top drive and drawworks points on the route sheet.', 'Rig Mechanic', 'LOTO on moving equipment', 15.0, 'Grease', 'Grease gun'),
            ('Prevention A', 'Mud pump expendables & valve check', 7, 150, 1.5, 'Inspect valves, seats, liners and pistons; replace worn parts.', 'Rig Mechanic', 'Pressure bled off', 400.0, 'Valves, seats, liners', 'Hand tools'),
            ('Prevention B', 'Drawworks brake & clutch inspection', 90, 1000, 4.0, 'Measure brake band wear, adjust clutches, check cooling water flow.', 'Rig Mechanic', 'LOTO; block the traveling equipment', 300.0, 'Brake blocks', 'Gauges'),
            ('Prevention B', 'Engine & generator service', 90, 500, 4.0, 'Change oil and filters on engines and generator sets; check coolant and belts.', 'Mechanic', 'Hot fluids', 500.0, 'Oil, filters', 'Drain pans'),
            ('Prevention C', 'Mast & substructure structural inspection', 365, 4000, 16.0, 'Inspect mast, pins, welds and guy lines; magnetic-particle test as required.', 'Structural Inspector', 'Fall protection; rig down', 1200.0, 'As required', 'Inspection kit'),
            ('Compliance', 'BOP pressure test & certification', 365, 0, 8.0, 'Function and pressure test the BOP stack and accumulator; file the test record.', 'Certified Technician', 'High pressure; barriers in place', 900.0, 'Seals, test fluid', 'Test pump'),
        ]),
    'Thermal Plant': dict(
        prefix='THERM',
        model='Thermal Generating Unit {i} (25 MW)',
        labels=('Rated Output (MW)', 'Steam Pressure (MPa)', 'Fuel Type', 'Cooling System', 'Turbine Type'),
        parts=('Boiler / Combustion Turbine:', 'Steam / Gas Turbine & Generator:', 'Feedwater & Condensate Systems:', 'Fuel Handling:', 'Controls & Protection:', 'Emissions & Ash Handling:'),
        attrs=[('Rated output', '25 MW', 'Steam turbine generator'), ('Fuel', 'Natural gas / coal', 'Per unit'), ('Cooling', 'Cooling tower', 'Chemistry checked weekly')],
        checklist=[('Check boiler feed pump vibration & seals', 'Verify turbine bearing temperatures'), ('Check lube oil level & cooler temperature', 'Inspect fuel handling system for leaks'), ('Verify condenser vacuum & cooling water flow', 'Check flue gas & stack monitoring readings'), ('Test emergency DC lube oil pump', 'Inspect steam & feedwater valves for leaks'), ('Check ash or exhaust handling system', 'Review control room alarms & trip log')],
        tasks=[
            ('Prevention A', 'Rounds: pumps, fans, bearings & leaks', 1, 24, 1.0, 'Operator rounds recording pressures, temperatures, vibration and visible leaks.', 'Operator', 'Hearing protection; hot surfaces', 0.0, 'None', 'Log sheet'),
            ('Prevention A', 'Water chemistry & blowdown check', 7, 168, 0.5, 'Test boiler and cooling water chemistry; adjust chemical feed and blowdown.', 'Operator', 'Chemical PPE', 40.0, 'Test reagents', 'Test kit'),
            ('Prevention B', 'Lube oil analysis & filter change', 90, 2000, 3.0, 'Sample turbine and pump oil; change filters; check coolers.', 'Mechanic', 'LOTO; hot oil', 300.0, 'Filters, oil', 'Sampling kit'),
            ('Prevention B', 'Feedwater pump & motor inspection', 90, 2000, 4.0, 'Check seals, coupling alignment, bearing temperature and vibration trend.', 'Millwright', 'LOTO', 250.0, 'Seals', 'Alignment tools'),
            ('Prevention C', 'Annual outage: turbine, boiler & valve inspection', 365, 8000, 80.0, 'Planned outage: borescope turbine, inspect boiler tubes, overhaul key valves.', 'Outage Crew', 'Confined space; LOTO', 15000.0, 'Gaskets, parts', 'Outage tools'),
            ('Compliance', 'Boiler, pressure vessel & safety valve certification', 365, 0, 8.0, 'Certified inspection of boiler and pressure vessels; test safety valves; renew certificates.', 'Certified Inspector', 'Confined space', 1500.0, 'Tags, gaskets', 'Test equipment'),
        ]),
    'HVAC & Boilers': dict(
        prefix='HVAC',
        model='Rooftop Unit RTU-{i} (25-ton)',
        labels=('Cooling Capacity (tons)', 'Heating Input (MBH)', 'Airflow (CFM)', 'Refrigerant Type', 'Control System'),
        parts=('Compressors / Burners:', 'Supply & Return Fans:', 'Coils & Heat Exchangers:', 'Controls & Thermostats:', 'Electrical & Starters:', 'Ductwork & Piping:'),
        attrs=[('Cooling capacity', '25 tons', 'Two scroll compressors'), ('Heating', '400 MBH gas', 'Two-stage burner'), ('Controls', 'BAS connected', 'Economizer fitted'), ('Source [1]', 'Brumbaugh, Audel HVAC Fundamentals, Vols. 1 to 3, 4th ed. (Wiley, 2004): furnaces and boilers inspected every year before the heating season by a qualified technician; filters checked monthly in the heating season and every 3 to 4 months otherwise; the low-water cut-off float chamber flushed about monthly; a carbon monoxide alarm near gas-fired equipment; vent pipes checked for water, sagging, loose joints and damage. Paraphrased in our own words (book, read)', 'library or bookstore'), ('Source [2]', 'Intervals vary with the equipment, the fuel and local codes. Follow the maker manual and a licensed technician or inspector. Not engineering advice.', 'manufacturer manual and local regulator')],
        checklist=[('Check thermostat & building temperatures', 'Listen for unusual noise or vibration'), ('Check air filters for dirt (visual)', 'Inspect condensate drain for blockage'), ('Check boiler pressure & temperature gauges', 'Look for water or refrigerant leaks'), ('Verify outside air dampers move freely', 'Check belts & pulleys (visual)'), ('Confirm no fault codes on controller', 'Check unit access panels are secured')],
        tasks=[
            ('Prevention A', 'Replace or clean air filters', 30, 720, 0.5, 'Replace pleated filters per the unit schedule and record the pressure drop.', 'Technician', 'LOTO', 40.0, 'Filters', 'Hand tools'),
            ('Prevention A', 'Check condensate drains & pans', 30, 0, 0.5, 'Clear drain lines, check pans and float switches.', 'Technician', 'LOTO', 5.0, 'Treatment tablets', 'Wet vac'),
            ('Prevention A', 'Flush low-water cut-off float chamber (if fitted)', 30, 0, 0.3, 'On a boiler with a float-type low-water cut-off, briefly open the drain below it to flush sediment from the float chamber, about once a month while the boiler runs [1]. Follow the maker instructions and ask your technician how to test that it shuts the burner off.', 'Boiler Technician', 'Hot water or steam; follow maker instructions', 0.0, 'None', 'Bucket'),
            ('Prevention A', 'Test carbon monoxide alarm near gas-fired equipment', 30, 0, 0.1, 'Press the test button on the carbon monoxide alarm near the furnace, boiler or gas appliance and confirm it sounds; replace batteries or the unit as its label says [1]. Carbon monoxide has no smell, so never rely on your nose. If it alarms, get everyone outside and call emergency services.', 'Technician', 'Carbon monoxide: leave the building if it alarms', 0.0, 'Batteries', 'None'),
            ('Prevention B', 'Belt, bearing & blower inspection', 90, 2000, 1.5, 'Check belt tension and wear, bearings, pulley alignment and blower wheel.', 'Technician', 'LOTO', 60.0, 'Belts, grease', 'Tension gauge'),
            ('Prevention B', 'Clean condenser & evaporator coils', 180, 4000, 3.0, 'Wash coils, straighten fins, check airflow and refrigerant pressures.', 'Technician', 'LOTO; chemical PPE', 40.0, 'Coil cleaner', 'Coil comb, sprayer'),
            ('Prevention C', 'Inspect vent pipes, flue & fresh-air openings', 365, 0, 0.5, 'Check vent pipes and the flue for water collecting, sagging, loose joints, corrosion and damage; check fresh-air grilles are open and clear [1]. Blocked or leaking venting can put carbon monoxide into the building.', 'Certified HVAC Technician', 'Carbon monoxide; gas appliances', 0.0, 'None', 'Flashlight, mirror'),
            ('Prevention C', 'Annual burner & refrigerant circuit service', 365, 8000, 6.0, 'Clean burners, test heat exchanger, check refrigerant charge and compressor amps.', 'Certified HVAC Technician', 'Gas and electrical hazards', 150.0, 'Gaskets', 'Gauges, combustion analyzer'),
            ('Prevention C', 'Boiler tune-up & combustion analysis', 365, 8000, 4.0, 'Clean the boiler, test low-water cut-off and combustion efficiency.', 'Boiler Technician', 'Pressure and hot surfaces', 120.0, 'Gaskets', 'Combustion analyzer'),
            ('Compliance', 'Boiler & pressure vessel inspection', 365, 0, 3.0, 'Annual certified inspection and safety valve test; post the certificate.', 'Certified Inspector', 'Hot surfaces', 200.0, 'Tags', 'Test equipment'),
        ]),
    'Pumps/Compressors': dict(
        prefix='PUMP',
        model='Process Pump / Compressor Skid {i}',
        labels=('Flow / Capacity', 'Motor Power (kW)', 'Discharge Pressure (kPa)', 'Seal Type', 'Lubricant'),
        parts=('Motor & Drive:', 'Pump or Compressor Head:', 'Seals & Bearings:', 'Coupling & Alignment:', 'Valves & Piping:', 'Controls & Gauges:'),
        attrs=[('Duty', 'Water transfer / 150 psi air', 'Mixed rotating equipment'), ('Motor', '30 kW, 3-phase', 'Vibration monitored'), ('Seals', 'Mechanical seals', 'Replace when leak rate rises')],
        checklist=[('Check discharge pressure and flow vs. normal', 'Listen for cavitation or bearing noise'), ('Check mechanical seals for leaks', 'Check oil level & colour'), ('Drain air receivers & check separators', 'Inspect belts & guards'), ('Verify gauges & relief valves', 'Check for vibration & hot spots'), ('Inspect piping, hoses & unions for leaks', 'Confirm guards & emergency stop in place')],
        tasks=[
            ('Prevention A', 'Drain receivers, check oil & seals', 7, 168, 0.5, 'Drain condensate, check compressor oil and pump seals for leaks.', 'Operator', 'Pressure isolated', 10.0, 'Oil as needed', 'None'),
            ('Prevention A', 'Vibration & temperature walk-round', 14, 336, 0.5, 'Record bearing temperature and vibration with a handheld meter.', 'Technician', 'Guards on', 0.0, 'None', 'Vibration meter'),
            ('Prevention B', 'Oil & filter change, belt check', 90, 2000, 2.0, 'Change oil, oil and air filters; check belts, coolers and unloaders.', 'Mechanic', 'LOTO; pressure released', 120.0, 'Oil, filters', 'Hand tools'),
            ('Prevention B', 'Coupling alignment & bearing greasing', 180, 4000, 2.5, 'Check shaft alignment and grease bearings to the recommended amount.', 'Millwright', 'LOTO', 40.0, 'Grease', 'Alignment tools'),
            ('Prevention C', 'Seal & bearing replacement / overhaul', 365, 8000, 8.0, 'Replace mechanical seals and bearings; inspect impellers or compressor elements.', 'Millwright', 'LOTO; drain and isolate', 900.0, 'Seals, bearings', 'Pullers, press'),
            ('Compliance', 'Relief valve & air receiver inspection', 365, 0, 3.0, 'Test relief valves and have air receivers inspected; keep the certificate on file.', 'Certified Inspector', 'Pressure vessels', 250.0, 'Tags', 'Test equipment'),
        ]),
    'Agriculture': dict(
        prefix='AG',
        model='Farm Tractor / Combine AG-{i}',
        labels=('Engine Power (HP)', 'Drive Type', 'Implement Type', 'Season Hours', 'Unit No.'),
        parts=('Engine & Fuel System:', 'Transmission & PTO:', 'Hydraulics & Hitch:', 'Header / Implement:', 'Cab, Electrical & Monitor:', 'Tires, Axles & Brakes:'),
        attrs=[('Engine', '300 HP diesel', 'Tier-rated'), ('Drive', '4WD, powershift', 'PTO and 3-point hitch'), ('Implement', 'Air seeder / header', 'Pre-season checks apply')],
        checklist=[('Check engine oil, coolant & hydraulic oil', 'Grease fittings (per lube chart)'), ('Inspect belts, chains & drives', 'Check air filter & clean radiator screen'), ('Inspect header, knives or openers', 'Check tires, pressure & wheel nuts'), ('Test lights, beacons & backup alarm', 'Check fire extinguisher & first aid kit'), ('Check PTO shield & guards in place', 'Check fuel level & drain water separator')],
        tasks=[
            ('Prevention A', 'Daily lube & fluid check (season)', 1, 10, 0.5, "Grease fittings, check fluids, belts, chains and screens before each day's work.", 'Operator', 'Engine off; guards in place', 8.0, 'Grease', 'Grease gun'),
            ('Prevention A', 'Air filter, radiator screen & belt check', 7, 50, 0.5, 'Clean screens, check air filter, belts and chain tension.', 'Operator', 'Engine off', 15.0, 'Filter as needed', 'Compressed air'),
            ('Prevention B', '250-hour service: oil & filters', 180, 250, 2.5, 'Change engine oil, filters and fuel filters; check coolant and battery.', 'Mechanic', 'Engine off', 250.0, 'Oil, filters', 'Hand tools'),
            ('Prevention B', 'Hydraulic & transmission fluid service', 180, 500, 2.5, 'Change hydraulic and transmission filters and fluid; check hoses and hitch.', 'Mechanic', 'Pressure released', 300.0, 'Fluid, filters', 'Hand tools'),
            ('Prevention C', 'Pre-season inspection: header, knives, drives & bearings', 365, 0, 8.0, 'Full off-season inspection of header, drives, bearings and wear parts before the season starts.', 'Mechanic', 'Machine blocked; guards', 700.0, 'Knives, bearings', 'Hand tools'),
            ('Compliance', 'Annual safety check: brakes, lights, PTO shields & SMV sign', 365, 0, 1.5, 'Check road safety equipment, brakes, lighting, slow-moving-vehicle emblem and shielding.', 'Certified Inspector', 'None', 100.0, 'None', 'Checklist'),
        ]),
    'Cranes & Hoists': dict(
        prefix='CRANE',
        model='Overhead Bridge Crane OC-{i} (10-tonne)',
        labels=('Rated Capacity (tonnes)', 'Span (m)', 'Hoist Type', 'Control Type', 'Serial No.'),
        parts=('Hoist & Wire Rope / Chain:', 'Trolley & Bridge Drives:', 'Hook, Block & Latch:', 'Runway & Rails:', 'Pendant / Radio Controls:', 'Limit Switches & Brakes:'),
        attrs=[('Capacity', '10 tonnes', 'Rated load plate on bridge'), ('Span', '18 m', 'Runway beams inspected yearly'), ('Hoist', 'Electric wire rope', 'Pendant control'), ('Source [1]', 'Mahato, Handbook for Mechanical Maintenance Engineers (2020), chapter on lifting and handling tackle: slings checked before each use; a thorough examination by a competent person at intervals of no more than six months (sooner for hard use, or as local rules require); discard criteria for wire rope slings (broken wires, wear, kinks and crushing, heat damage, corrosion, damaged fittings). Paraphrased in our own words (book, read)', 'library or bookstore'), ('Source [2]', 'Crane and rigging rules differ by province and state. Follow your regulator, the crane maker and a competent person. Not engineering advice.', 'regulator and manufacturer manual')],
        checklist=[('Test pendant / remote buttons & e-stop', 'Check hook latch & hook condition'), ('Inspect wire rope or chain visually', 'Test hoist upper limit switch'), ('Test brakes by lifting a light load', 'Check runway for obstructions'), ('Listen for noise in hoist, trolley & bridge', 'Check load rating label is legible'), ('Check slings and shackles before use: broken wires, kinks, worn or bent fittings', 'Check each sling is tagged with its rated load'), ('Check warning horn / lights', 'Check power festoon / conductor bar condition')],
        tasks=[
            ('Prevention A', 'Operator pre-shift inspection', 1, 8, 0.2, 'Frequent inspection: controls, limit switches, hook latch, rope and brakes before use.', 'Operator', 'Crane tagged out if a defect is found', 0.0, 'None', 'Checklist'),
            ('Prevention A', 'Wire rope & chain lubrication', 30, 100, 0.5, 'Lubricate wire rope or load chain and inspect for broken wires or stretch.', 'Mechanic', 'Crane locked out', 15.0, 'Rope lube', 'Brush'),
            ('Prevention B', 'Brake & limit switch inspection', 90, 400, 2.0, 'Inspect and adjust hoist brake, test upper and lower limits and overload device.', 'Electrician / Mechanic', 'LOTO; fall protection', 80.0, 'Brake parts', 'Hand tools'),
            ('Prevention B', 'Thorough examination of slings, shackles & lifting tackle', 180, 0, 1.0, 'A competent person examines every sling, shackle and piece of lifting tackle at least every six months (sooner after rough use or any doubt) and keeps a record [1]. Take wire rope slings out of service for: more than 5% of the wires broken in a length of six rope diameters; three or more broken wires close together; a measured diameter under 90% of nominal; kinks, crushing or a collapsed core; heat damage; corrosion that has cost flexibility; or cracked, bent or worn fittings. When in doubt, take it out. Local rules may be stricter.', 'Competent Person', 'No load on the hook; tag failed slings out of service', 20.0, 'Tags', 'Calipers, record sheet'),
            ('Prevention B', 'Gearbox oil & wheel inspection', 180, 800, 2.5, 'Check gearbox oil, wheels, rails and end trucks.', 'Mechanic', 'LOTO; fall protection', 100.0, 'Gear oil', 'Hand tools'),
            ('Prevention C', 'Periodic inspection with load test', 365, 0, 6.0, 'Documented periodic inspection of the whole crane including a rated load test.', 'Qualified Inspector', 'Test area clear; fall protection', 500.0, 'None', 'Test weights'),
            ('Compliance', 'Annual certification of crane & runway', 365, 0, 3.0, 'Third-party inspection and certification; post or file the certificate.', 'Certified Inspector', 'Fall protection', 400.0, 'Tags', 'Inspection kit'),
        ]),
    'Factory Measuring & Test Equipment': dict(
        prefix='MTE',
        model='Calibrated Instrument CI-{i} (gauge, torque wrench or meter)',
        labels=('Instrument Type', 'Range', 'Accuracy / Resolution', 'Calibration Interval (months)', 'Calibration Lab'),
        parts=('Sensing Element / Anvil:', 'Display / Dial / Scale:', 'Case & Calibration Label:', 'Adjustment Points:', 'Cables & Probes:', 'Reference Standard Used:'),
        attrs=[('Instrument type', 'Click-type torque wrench, 20-200 Nm', 'Store set to the lowest value'), ('Calibration interval', '12 months', 'Shorten it if the instrument is found out of tolerance'), ('Traceability', 'Lab certificate on file', 'Instrument ID, date, result, reference used, next due date'),
               ('Source [1]', 'ISO 9001:2015 clause 7.1.5 (monitoring and measuring resources), read through published summaries, not the standard itself: measuring equipment is calibrated or verified at set intervals or before use against traceable references, its status is kept in a record, and action is taken if earlier results are found to be invalid. Using this group helps you keep those records; it does not make anyone certified', 'iso.org; your own quality manual'),
               ('Source [2]', 'The instrument maker manual, your calibration lab and any customer or regulator requirement set the real intervals and tolerances', 'maker manual; lab certificate')],
        checklist=[('Check for damage and read the calibration due label before use', 'Do not use anything overdue, dropped or damaged; tag it and set it aside'), ('Check a working gauge against a reference (gauge block, test weight, reference thermometer)|Friday', 'Record the reading and the date')],
        tasks=[
            ('Prevention A', 'Check before use: condition and calibration label', 1, 0, 0.05, 'Before each use look for damage and read the calibration due date. Overdue, dropped or damaged instruments are tagged and taken out of service.', 'Operator', 'None', 0.0, 'None', 'None'),
            ('Prevention A', 'Weekly verification against a reference', 7, 0, 0.2, 'Check working instruments against a reference standard (gauge block, test weight, reference thermometer) and record the reading. A verification does not replace calibration.', 'Technician', 'None', 0.0, 'None', 'Reference standard'),
            ('Prevention B', 'Review calibrations coming due (next 90 days)', 90, 0, 0.5, 'List every instrument due in the next three months and book the calibration lab, allowing for turnaround time and a spare instrument.', 'Supervisor', 'None', 0.0, 'None', 'None'),
            ('Prevention B', 'Review instruments found out of tolerance', 90, 0, 0.5, 'For any instrument found out of tolerance, list the work measured since its last good check, decide what to re-check, and record the action taken.', 'Supervisor', 'None', 0.0, 'None', 'None'),
            ('Prevention C', 'Calibrate and file the certificate', 365, 0, 1.0, 'Send each instrument to a calibration lab, or calibrate against traceable standards, at the interval you have set. File the certificate with instrument ID, date, result, reference used and next due date, and update the label.', 'Technician', 'None', 150.0, 'Calibration labels', 'None'),
            ('Prevention C', 'Review calibration intervals and records', 365, 0, 1.0, 'Shorten the interval where instruments are often found out of tolerance; consider lengthening it where history is clean. Check that records are complete and filed where you can find them.', 'Supervisor', 'None', 0.0, 'None', 'None'),
        ]),
    'Machine Tools': dict(
        prefix='MACH',
        model='CNC Machining Center MC-{i}',
        labels=('Spindle Power (kW)', 'Spindle Speed (rpm)', 'Axes', 'Control Type', 'Coolant Type'),
        parts=('Spindle & Drive:', 'Axes, Ballscrews & Guideways:', 'Hydraulics & Pneumatics:', 'Coolant & Chip Systems:', 'Controls & Electrical:', 'Guards & Safety Devices:'),
        attrs=[('Spindle', '15 kW, 8,000 rpm', 'Warm-up routine required'), ('Axes', '3-axis, 1 m travel', 'Way lube checked daily'), ('Coolant', 'Water-soluble', 'Concentration checked weekly')],
        checklist=[('Check way lube & hydraulic oil levels', 'Check coolant level & concentration'), ('Clean chips from table & guards', 'Check air pressure at the machine'), ('Run spindle warm-up cycle', 'Check for fault codes on the control'), ('Inspect safety guards & light curtains', 'Test emergency stop'), ('Check tool holders & tool changer', 'Wipe down and lightly oil exposed surfaces')],
        tasks=[
            ('Prevention A', 'Daily clean-down & fluid check', 1, 8, 0.4, 'Clear chips, check way lube, coolant and air; run the spindle warm-up.', 'Operator', 'Machine stopped; guards', 5.0, 'Way oil', 'Brush, rag'),
            ('Prevention A', 'Coolant concentration & filter check', 7, 40, 0.5, 'Test coolant concentration and pH; clean the tank and filters.', 'Operator', 'Chemical PPE', 20.0, 'Coolant concentrate', 'Refractometer'),
            ('Prevention B', 'Lubrication, air filter & way cover inspection', 90, 500, 2.0, 'Refill lubricators, drain air filters, inspect way covers and wipers.', 'Maintenance Technician', 'LOTO', 60.0, 'Oil', 'Hand tools'),
            ('Prevention B', 'Spindle & ballscrew condition check', 180, 1000, 3.0, 'Check spindle runout, vibration and ballscrew backlash.', 'Maintenance Technician', 'LOTO', 50.0, 'Grease', 'Dial indicator'),
            ('Prevention C', 'Annual geometry & alignment check', 365, 2000, 8.0, 'Check machine levelness, axis squareness and positioning accuracy; adjust as needed.', 'Service Technician', 'LOTO', 600.0, 'None', 'Laser / ball bar'),
            ('Compliance', 'Safety interlock & guard verification', 365, 0, 2.0, 'Verify guards, interlocks, light curtains and emergency stops work and are documented.', 'Safety Technician', 'LOTO', 100.0, 'None', 'Test checklist'),
        ]),
    'Fire & Life Safety': dict(
        prefix='FIRE',
        model='Building Fire Protection System FP-{i}',
        labels=('Coverage Area (m2)', 'System Type', 'Panel Manufacturer', 'Water Supply', 'Last Alarm Test'),
        parts=('Fire Alarm Panel & Devices:', 'Sprinkler Mains & Heads:', 'Fire Pump & Water Supply:', 'Extinguishers & Hose Stations:', 'Emergency Lighting & Exit Signs:', 'Suppression Systems (Kitchen / Special):'),
        attrs=[('System', 'Wet sprinkler + addressable alarm', 'Monitored'), ('Extinguishers', '34 portable units', 'Tags checked monthly'), ('Emergency lighting', 'Battery units', 'Tested monthly and annually')],
        checklist=[('Check alarm panel shows normal, no troubles', 'Check sprinkler valve gauges & valve positions'), ('Check extinguishers are in place & unobstructed', 'Check pressure gauges in the green'), ('Check exit signs & emergency lights lit', 'Check exits and stairwells clear'), ('Check fire doors close and latch', 'Check kitchen hood & suppression nozzles'), ('Check fire pump controller (if fitted)', 'Review any impairment tags')],
        tasks=[
            ('Prevention A', 'Monthly extinguisher & exit light check', 30, 0, 1.0, 'Visually check every extinguisher (tag, gauge, pin, seal) and test emergency lighting briefly.', 'Facility Technician', 'None', 10.0, 'Tags', 'Checklist'),
            ('Prevention A', 'Sprinkler valve & gauge check', 30, 0, 0.5, 'Check control valves are open and locked, gauges are normal.', 'Facility Technician', 'None', 0.0, 'None', 'None'),
            ('Prevention B', 'Quarterly alarm device & waterflow test', 90, 0, 2.0, 'Test a sample of alarm devices and the waterflow alarm; notify the monitoring company first.', 'Certified Fire Technician', 'Notify occupants and monitoring', 80.0, 'None', 'Test equipment'),
            ('Prevention B', 'Fire pump weekly/monthly run & churn test', 30, 0, 0.5, 'Run the fire pump per the schedule and log pressures.', 'Certified Fire Technician', 'None', 0.0, 'None', 'Log sheet'),
            ('Prevention C', 'Annual extinguisher service & hydrostatic testing schedule', 365, 0, 4.0, 'Annual maintenance of portable extinguishers; hydrostatic tests as due.', 'Certified Fire Technician', 'None', 300.0, 'Tags, agent', 'Service kit'),
            ('Compliance', 'Annual fire alarm & sprinkler inspection and certificate', 365, 0, 6.0, 'Full annual inspection by a certified company; file the certificate for the fire authority.', 'Certified Inspector', 'Notify monitoring', 600.0, 'None', 'Test equipment'),
        ]),
    'IT & Network': dict(
        prefix='IT',
        model="Office Network & Computers IT-{i}",
        labels=("Devices Covered", "Router / Firewall", "Switch & Wi-Fi", "Backup Method", "Operating Systems"),
        parts=("Computers & Laptops:", "Switches, Wi-Fi & Router:", "Servers & Storage:", "Backup Drives & Media:", "Power & UPS:", "Cabling, Racks & Printers:"),
        attrs=[("Devices", "25 computers, 2 servers, 1 router", "Inventory list kept up to date"), ("Backup", "Nightly to external drive + weekly off-site copy", "Restore tested every quarter"), ("Operating systems", "Mostly Windows; some Mac and Linux", "All still supported by their makers")],
        checklist=[
            ("Check last night's backup finished without errors", "Check antivirus / security app shows protected"),
            ("Check server and network status lights", "Check internet connection and Wi-Fi are working"),
            ("Check UPS shows normal, no alarms", "Check server room temperature is normal"),
            ("Check free disk space on servers", "Review any warnings or alerts on screen"),
            ("Check server room door is locked", "Check cables and racks are tidy and not blocked"),
            ("Check for pending system updates on every computer|Monday", "Restart any computer that has been on for over a week|Monday"),
            ("Keep at least 20% free space on every drive|Tuesday", "Check backup drive is plugged in, powered and healthy|Tuesday"),
            ("Review security alerts and failed sign-in warnings|Wednesday", "Check printers, scanners and shared folders work|Wednesday"),
            ("Check nothing extra is plugged into the UPS or power bars|Thursday", "Look for unknown users on computers and in the router|Thursday"),
            ("Open one file from the backup copy to prove it works|Friday", "Check laptops and tablets were updated and backed up this week|Friday"),
            ("Check no new AI tools or browser add-ons were installed without approval|Monday", "Check AI assistants are not left signed in on shared computers|Monday"),
        ],
        tasks=[
            # --- Prevention A: monthly routines ---
            ("Prevention A", "Review backup logs & update status", 7, 0, 0.5, "Open the backup program and read the last week of results. Fix any failed job the same day. Check every computer shows its updates and antivirus as current.", "IT Technician", "None", 0.0, "None", "Admin console"),
            ("Prevention A", "Install OS updates (Windows, Mac, Linux)", 30, 0, 2.0, "Do this outside working hours. Windows: Settings > Windows Update > Check for updates. Mac: System Settings > General > Software Update. Linux: run the package update (for example sudo apt update, then sudo apt upgrade, or sudo dnf upgrade). Restart, then note what was installed.", "IT Technician", "Warn users first; back up before big updates", 0.0, "None", "Update tool"),
            ("Prevention A", "Update browsers, office & business programs", 30, 0, 1.0, "Update each browser, PDF reader, office suite, accounting and industry program to the latest version from its maker. Remove programs nobody uses.", "IT Technician", "None", 0.0, "None", "Software list"),
            ("Prevention A", "Run antivirus scan & check protection status", 30, 0, 1.0, "Windows: open Windows Security and check every item is green, then run a full scan on one computer. Mac and Linux: confirm the scanner or built-in protection is on and its last run is recent. Record the result.", "IT Technician", "None", 0.0, "None", "Security app"),
            ("Prevention A", "Check disk health & free space", 30, 0, 1.0, "Check free space on every drive (keep 20% free). Windows: Settings > System > Storage. Mac: Disk Utility, run First Aid. Linux: df -h, and smartctl -H on each drive if installed. Replace any drive that reports a warning.", "IT Technician", "Back up first", 0.0, "None", "Disk tools"),
            ("Prevention B", "Back up the Windows registry and make a restore point before big changes", 90, 0, 0.5, "Before installing major software or changing system settings: Windows: search 'Create a restore point', click Create. To save the registry, open regedit, choose File > Export, pick 'All', and save the file on the backup drive. Do not edit the registry if you are unsure. Helps you recover if something goes wrong.", "IT Technician", "Registry changes can stop Windows starting; back up first", 0.0, "None", "Admin console"),
            ("Prevention A", "Scan your own network for open ports, unknown devices and old software", 30, 0, 1.0, "On your own network only, with the owner's permission: use a reputable scanner or your router's device list to list every device and open service. Close or switch off anything you do not use, and update or retire anything old. Record what you found.", "IT Technician", "Only scan networks you own or are authorised to test", 0.0, "None", "Network scanner"),
            ("Prevention B", "Check firewall rules, remote access and default passwords", 90, 0, 1.0, "Review the firewall and router rules. Remove old port forwards and unused remote-access rules. Change any default password. Make sure remote access needs two-step sign-in or a VPN.", "IT Technician", "Take a backup of settings first", 0.0, "None", "Router console"),
            ("Prevention C", "Yearly: protect your business and personal identity data", 365, 1.0, "Review who holds your key records (bank, tax, corporate documents, customer lists). Lock paper files, encrypt laptops and backup drives, shred what you no longer need, and check your credit report. If you run a web shop, keep card data with the payment provider, not on your own server.", "IT Manager", "None", 0.0, "None", "Shredder"),
            ("Prevention B", "Lock down the web server and any public-facing programs", 90, 0, 1.5, "If you run a web server (for example IIS) or any program reachable from the internet: install the latest updates, remove sample pages and unused features, turn off directory listing, use strong admin passwords, and review who has administrator rights. If you do not need it reachable, switch it off.", "IT Technician", "Take a backup first", 0.0, "None", "Admin console"),
            ("Prevention B", "Review webmail and cloud account security (sign-in activity, forwarding, recovery)", 90, 0, 1.0, "For each business email and cloud account: look at recent sign-in activity, confirm no unknown forwarding rules or connected apps, check the recovery phone and email are yours and current, and turn on two-step sign-in. Change the password if anything looks odd.", "IT Manager", "None", 0.0, "None", "Account settings"),
            ("Prevention C", "Yearly staff refresher: phishing, passwords and safe computing", 365, 1.0, "A short session (30 to 60 minutes): how to spot phishing, use a password manager, keep software updated, lock the screen, and report anything odd without blame. Keep a note of who attended.", "IT Manager", "None", 0.0, "None", "Meeting room"),
            ("Prevention A", "Update the list of AI tools & connected apps", 30, 0, 0.5, "Keep a list of AI assistants, browser add-ons, plug-ins and connected apps in use: who uses each one, and which files, mailboxes or accounts it can reach.", "IT Manager", "None", 0.0, "None", "Tool list"),
            # --- Prevention B: quarterly checks ---
            ("Prevention B", "Test restore from backup", 90, 0, 1.5, "Restore one file and one whole folder from the backup to a different location and open them. Keep three copies of important data: working copy, backup, and one stored off-site.", "IT Technician", "None", 0.0, "None", "Backup software"),
            ("Prevention B", "Firewall & router check", 90, 0, 1.5, "Log in to the router. Install any firmware update. Make sure the admin password is not the factory one. Turn off remote administration, WPS and any port forwarding you do not need. Keep guest Wi-Fi separate from the office network.", "Network Technician", "Plan an outage window", 0.0, "None", "Admin login"),
            ("Prevention B", "Wi-Fi & network health check", 90, 0, 1.5, "Test internet speed and Wi-Fi signal in each work area. Remove unknown devices from the router list. Label cables and update the switch-port list. Check nothing is plugged into an overloaded power bar.", "Network Technician", "None", 0.0, "None", "Speed test, labels"),
            ("Prevention B", "Check laptop encryption & screen locks", 90, 0, 1.0, "Confirm every laptop encrypts its drive (Windows BitLocker or device encryption, Mac FileVault, Linux disk encryption), locks its screen after a few minutes, and has a recovery key stored safely.", "IT Technician", "Store recovery keys safely", 0.0, "None", "System settings"),
            ("Prevention B", "Check domain, hosting & software renewals", 90, 0, 0.5, "List the expiry or renewal date for the domain name, website hosting, email service, antivirus and every software licence. Set a reminder a month before each date.", "IT Manager", "None", 0.0, "None", "Renewal list"),
            ("Prevention B", "Review AI tool permissions & updates", 90, 0, 1.5, "Check each AI tool and connected app for new permissions or changed settings after updates. Remove access that is not needed, and keep human approval on actions that send, delete or pay.", "IT Manager", "None", 0.0, "None", "Tool list"),
            ("Prevention B", "Review who can reach what", 90, 0, 1.0, "Give each person, program and automation only the access its job needs. Remove shared logins and access nobody uses.", "IT Manager", "None", 0.0, "None", "Account list"),
            # --- Prevention C: every 6-12 months ---
            ("Prevention C", "Change tool & automation passwords/keys", 180, 0, 1.5, "Replace the passwords, API keys and tokens used by AI tools, backup jobs and other automations; update each program that uses them. Use a password manager, and turn on two-step sign-in wherever it is offered.", "IT Technician", "Test each connection afterwards", 0.0, "None", "Password manager"),
            ("Prevention C", "Annual UPS battery test & dust cleaning", 365, 0, 3.0, "Test UPS runtime, replace weak batteries, and blow dust from computers, switches and racks with compressed air.", "IT Technician", "Shut down equipment first; static care", 200.0, "UPS batteries, compressed air", "Hand tools"),
            ("Prevention C", "Hardware age & upgrade review", 365, 0, 2.0, "List the age and warranty end date of every computer, router, switch and drive. Plan to replace computers and drives older than about 4 to 5 years, and add memory or a solid-state drive to slow but sound machines. Confirm every operating system and program is still supported by its maker, and budget for next year.", "IT Manager", "None", 0.0, "None", "Equipment list"),
            ("Prevention C", "Full backup & recovery drill", 365, 0, 3.0, "Make a complete image of the main computer, keep a copy off-site, and practise rebuilding from it on a spare machine, or at least confirm the image opens. Time how long it takes.", "IT Technician", "Use a spare machine, not the live one", 0.0, "None", "Backup software, spare PC"),
            ("Prevention C", "Cable, rack & printer tidy-up", 365, 0, 2.0, "Re-label cables, tidy racks, check power bars are not overloaded or chained together, clean printer heads and replace worn parts.", "IT Technician", "Power down first", 50.0, "Labels, cable ties", "Hand tools"),
            # --- Compliance: yearly records ---
            ("Compliance", "Annual user account & password review", 365, 0, 2.0, "Remove accounts of people who have left, review administrator rights and shared passwords.", "IT Manager", "None", 0.0, "None", "Account list"),
            ("Compliance", "Annual review of AI-use rules & incident plan", 365, 0, 2.0, "Update the written rules for AI tools (what data may be entered, who approves new tools) and the steps to follow if a tool misbehaves: pause its access, change the passwords it used, record what happened.", "IT Manager", "None", 0.0, "None", "Written rules"),
            ("Compliance", "Annual IT recovery plan review", 365, 0, 2.0, "Update the one-page plan: who to call for IT help and for the internet provider, where passwords and licence keys are kept, and the steps to get back to work if the office or main computer is lost.", "IT Manager", "None", 0.0, "None", "Recovery plan"),
        ]),
    'Longevity 60 Plus': dict(
        prefix='L60',
        model='Longevity Plan 60+ {i}',
        units=1,
        unit_names={1: 'My Longevity Plan (60 and over)'},
        labels=('Age', 'Blood Pressure (mmHg)', 'Resting Heart Rate (bpm)', 'Waist (inches)', 'Family Doctor'),
        parts=('Vitamins & Supplements:', 'Home Monitors & Test Kits:', 'Exercise Gear:', 'Sleep & Recovery:', 'Kitchen Staples:', 'Traditional Practice Supplies:'),
        attrs=[('How this plan is ranked', 'Strongest evidence first', 'Labels: Strong, Moderate, Emerging, Traditional. Traditional = long use, few trials.'),
               ('Sources compared', 'Research books, trials, TCM and Ayurveda', 'Where they agree, the item is near the top. Where they disagree, the note says so.'),
               ('Not medical advice', 'Check with your doctor', 'Take your results and this list to your family doctor before changing medicines.')],
        # Ranked roughly from most to least important. Two items per row; "|Monday" makes an item weekly.
        # Not medical advice. Herbs, supplements, fasting and hard exercise can interact with medicines or health conditions: ask your doctor first.
        checklist=[
            ('No tobacco or vaping today (strongest single habit)', 'Alcohol: none, or at most one drink; keep some alcohol-free days'),
            ('Walk or move: 7,000-9,000 steps (benefit levels off around there for people over 60)', 'Break up sitting: stand and move every 30-60 minutes'),
            ('Zone 2 exercise 30 minutes (brisk walk or bike where you can still talk) - aim for about 3 hours a week', 'Sleep: 7-8 hours, same bedtime, lights out before 11 pm (TCM and sleep research agree)'),
            ('Protein at every meal (about 1.2-1.6 g per kg a day over 65: eggs, fish, yogurt, beans, meat)', 'Vegetables, beans and fibre: 2 big servings, aim 30 g fibre a day (Mediterranean pattern - strong evidence)'),
            ('Olive oil as the main fat; a handful of nuts', 'Eat inside a 10-12 hour window; finish eating 3 hours before bed (Longo, Attia and Ayurveda agree)'),
            ('Take a multivitamin with a meal (moderate evidence; COSMOS trial: slower memory decline). Look for D3, B12, folate, B6, K, zinc, selenium, iodine, magnesium, low vitamin A, no iron for men', 'Vitamin D3 with a meal (about 1,000 IU in Saskatchewan winters; ask your doctor for your dose)'),
            ('Omega-3: oily fish (salmon, sardines, trout) or fish-oil capsule with EPA + DHA about 1 g', 'Creatine 3-5 g in water or coffee (moderate evidence for muscle and thinking)'),
            ('Full-fat yogurt with live cultures once a day: two birds, one stone. Dairy fat has C15:0 (emerging, observational) and live cultures feed the gut microbiome (moderate). Kefir, sauerkraut or kimchi also count [26]', 'Limit added sugar, sweetened drinks and ultra-processed snacks'),
            ('Take prescribed medicines exactly as directed', 'Water 1.5-2 L; green tea 1-2 cups (TCM tradition, moderate evidence)'),
            ('Morning: 10-20 minutes of daylight outdoors (body clock, mood, vitamin D)', 'Morning: 10-15 minutes of qigong or tai chi (balance, blood pressure, falls - moderate evidence)'),
            ('Balance: stand on one leg while brushing teeth, 30 seconds each side', 'Brush two times and floss once (gum disease is linked to heart disease)'),
            ('Talk to or see at least one person today (loneliness is a major risk factor)', 'Do something with purpose: read, learn, create, volunteer, help someone (purpose in life is linked to longer life)'),
            ('Breathing or meditation 5-10 minutes (slow breaths, longer out than in)', 'Three lines in a journal: one thing grateful for, one done, one for tomorrow (emerging)'),
            ('Warm water on waking; scrape the tongue (Ayurveda: traditional)', 'Largest meal at midday, light supper (Ayurveda; early eating is linked to better blood sugar)'),
            ('Turmeric with black pepper and ginger in food, a little each day (Ayurveda; modest evidence)', 'Press the ST36 point (Zusanli, below the knee) for 1 minute each leg (TCM: traditional)'),
            ('Evening: screens off and lights low for the last hour', 'Evening: bedroom cool (16-19 C), dark and quiet; no food 3 hours before bed'),
            ('Evening: warm foot soak 10 minutes (TCM and Ayurveda: traditional; helps you wind down)', 'Evening: pill box filled for tomorrow; set out walking shoes'),
            ('Strength training, full body 30-45 minutes (squat, push, pull, hinge, carry)|Monday', 'Strength training, full body 30-45 minutes, a different day than before|Thursday'),
            ('High-intensity intervals: 4 x 4 minutes hard, 3 minutes easy between (only if your doctor agrees)|Friday', 'Long Zone 2 session 45-60 minutes (bike, hike, swim)|Wednesday'),
            ('Farmer carry: walk 40 steps holding heavy bags or weights, half your body weight in each hand if you can|Tuesday', 'Stretch and mobility 15 minutes: hips, shoulders, spine, ankles|Saturday'),
            ('Weigh yourself and measure your waist at the navel (keep under 33 in for men)|Monday', 'Home blood pressure: 2 readings, seated and rested, morning and evening for 3 days|Sunday'),
            ('Oily fish meal (twice a week target)|Tuesday', 'Oily fish meal (second one)|Saturday'),
            ('Beans or lentils meal (four times a week target)|Monday', 'Plan the week: groceries with vegetables, fish, beans, nuts, olive oil|Sunday'),
            ('Sauna 15-20 minutes, 2-4 times a week if you have access and your doctor agrees (Finnish studies: linked to fewer heart deaths)|Thursday', 'Time in nature or a park, about 2 hours in total this week (linked to better health)|Saturday'),
            ('Oil self-massage before a shower, abhyanga (Ayurveda: traditional, calming)|Sunday', 'Call or visit a friend or family member for a real conversation|Wednesday'),
            ('Refill the pill box; check supplement and medicine supply|Sunday', 'Review the week: sleep, steps, exercise, mood. What is one thing to do better?|Sunday'),
        ],
        tasks=[
            # ---- Prevention A: monthly self-checks (done at home) ----
            ('Prevention A', 'Monthly home health log: blood pressure, weight, waist, resting pulse', 30, 0, 0.5, 'Average the month of home blood pressure readings (under 130/80 is the usual goal; show your doctor the log if higher). Weigh yourself, measure the waist at the navel (men: under 33 inches is better) and write down the resting pulse on waking. Rising waist with falling muscle is the pattern to catch early. [Strong]', 'Me', 'Rest 5 minutes first; seated, arm at heart level', 0.0, 'Log sheet', 'Home blood pressure monitor, scale, tape measure'),
            ('Prevention A', 'Monthly fitness check: exercise totals, balance, sit-to-stand, mobility', 30, 0, 0.8, 'Add up the month: Zone 2 minutes (aim for about 180 a week), strength sessions (2-3 a week), one hard interval session a week, steps. Then test: stand on one leg with eyes open (10 seconds or more is the minimum; inability is linked to higher death risk in a large study), count chair stands in 30 seconds, check you can get up from the floor and reach overhead. [Strong]', 'Me', 'Do the balance test next to a counter or wall; stop for chest pain or fainting', 0.0, 'None', 'Watch or step counter, timer, chair'),
            ('Prevention A', 'Monthly sleep, mood and daylight review', 30, 0, 0.6, 'Sleep: usual bedtime (before 11 pm), hours, snoring, night waking. Mood and people: do I see or talk to people often, do I have a reason to get up? Low mood or loneliness for 2 weeks is worth telling your doctor. Light: morning daylight most days, screens off in the last hour. Fix the weakest one next month. [Strong; TCM traditional]', 'Me', 'If you feel hopeless, call 9-8-8 (Canada) or your doctor now', 0.0, 'None', 'Sleep log or watch'),
            ('Prevention A', 'Monthly restock: vitamins, medicines and kitchen staples', 30, 0, 0.8, 'Count the multivitamin, vitamin D3, omega-3 and creatine and reorder when under 2 weeks remain. Keep the medicine list current. Stock olive oil, nuts, beans, lentils, oats, frozen vegetables, canned salmon or sardines, eggs, plain full-fat yogurt, green tea, turmeric, ginger. [Moderate]', 'Me', 'Do not double up on doses; check dates on canned goods', 150.0, 'Multivitamin, D3, omega-3, creatine, groceries', 'Pill box'),
            ('Prevention A', 'Quarterly 3-day food log: protein, fibre and fish check', 91, 0, 1.0, 'Write down everything eaten for 3 days. Compare to: protein 1.2-1.6 g per kg, fibre 30 g, added sugar low, fish twice a week, dairy fat daily. The books disagree here: Longo suggests less protein under 65, Attia and geriatric guidelines suggest more protein over 65 to protect muscle. This plan follows the over-65 view. [Moderate]', 'Me', 'Do not start a restrictive diet without your doctor', 5.0, 'None', 'Food log app or notebook'),
            # ---- Prevention B: quarterly fitness tests and twice-a-year visits ----
            ('Prevention B', 'Quarterly fitness tests: 1-mile walk, grip strength, farmer carry', 91, 0, 1.5, 'Time a one-mile brisk walk or measure the distance in 6 minutes (cardio fitness is one of the strongest predictors of long life). Squeeze a hand dynamometer with each hand (for men over 65, under about 27 kg is low). Carry the heaviest weights you can for 1 minute (goal: half your body weight in each hand). Record all three and compare. [Strong]', 'Me', 'Warm up first; stop for chest pain or dizziness; set weights down slowly', 45.0, 'None', 'Watch, hand dynamometer, dumbbells'),
            ('Prevention B', 'Quarterly skin self-check, head to toe', 91, 0, 0.4, 'Look at all skin with a mirror: new, changing, bleeding or asymmetrical spots. Photograph anything odd and show your doctor. [Strong]', 'Me', 'None', 0.0, 'None', 'Mirror, phone camera'),
            ('Prevention B', 'Quarterly qigong or tai chi class or lesson block', 91, 0, 4.0, 'Take or renew a class. Tai chi has trial evidence for balance, falls and blood pressure. Qigong is the same family of slow movement and breathing (TCM: traditional). [Moderate]', 'Instructor', 'Stand next to a chair at first', 120.0, 'Class fee', 'Comfortable shoes'),
            ('Prevention B', 'Twice-yearly dental cleaning and medicine review', 182, 0, 2.0, 'Same trip: dentist or hygienist cleaning and gum check (gum health is linked to heart and brain health), then a stop at the pharmacist. Bring every pill, herb and supplement; ask about interactions (especially ashwagandha, ginseng, turmeric extracts, fish oil with blood thinners) and whether any drug can be stopped. [Strong]', 'Dentist and pharmacist', 'Never stop a prescription without your doctor', 200.0, 'None', 'List of all medicines'),
            ('Prevention B', 'Twice-yearly safety and screening check at home', 182, 0, 1.5, 'Walk the house for fall hazards (rugs, cords, lighting, stairs, handrails, bath mat, night lights, shoes). Check the home blood pressure cuff against the pharmacy or doctor cuff; replace if readings differ by more than 5-10 points. Answer the STOP-BANG questions for sleep apnea (3 or more yes: ask for a sleep test) and a short mood form (PHQ-9) and share any high result with your doctor. [Strong]', 'Me', 'Use a stable step stool', 20.0, 'Night lights, non-slip mats', 'Flashlight, STOP-BANG and PHQ-9 forms'),
            # ---- Prevention C: yearly bundles (one lab visit, one checkup visit) ----
            ('Prevention C', 'Annual blood work bundle (one fasting lab visit)', 365, 0, 1.5, 'One visit, ask your doctor for the whole list. FIRST: fasting insulin (with glucose, giving HOMA-IR) and HbA1c: insulin resistance shows up years before blood sugar rises, so insulin matters more than glucose alone. THEN: lipid panel with ApoB (cholesterol particles); liver (ALT, AST); kidney (creatinine, eGFR, urine ACR); complete blood count; thyroid TSH; ferritin (men: high iron is as important as low); vitamin D (25-OH); vitamin B12; hs-CRP (inflammation; repeat if high). Cheap and common. [Strong]', 'Family doctor / lab', 'Fast 10-12 hours (water is fine)', 0.0, 'None', 'Lab requisition from the doctor'),
            ('Prevention C', 'Once-in-life blood tests: Lp(a) and hepatitis C', 3650, 0, 0.5, 'Lipoprotein(a) is inherited and does not change much; one test shows if your level is high-risk. Hepatitis C is a one-time test for adults born 1945-1975 or with risk factors. Can be added to the annual blood work visit. [Strong]', 'Family doctor / lab', 'None', 0.0, 'None', 'Lab requisition'),
            ('Prevention C', 'Optional private test: omega-3 index and fatty acids (including C15:0)', 365, 0, 0.5, 'Optional private test showing omega-3 levels and some blood fatty acids such as C15:0 (found in dairy fat). Evidence for acting on the result is still emerging. [Emerging]', 'Private lab', 'None', 90.0, 'Test kit', 'Kit or lab visit'),
            ('Prevention C', 'Coronary artery calcium (CAC) scan: discuss with your doctor', 1825, 0, 1.5, 'A CT scan of the heart, not a blood test. A score of 0 is reassuring; over 400 means high risk. Usually considered at about 40-75; repeat after 5 years if zero. About $100-300 and often not insured. Overuse in low-risk people is also debated, so decide with your doctor. [Moderate]', 'Family doctor / imaging clinic', 'Small dose of radiation; ask if it is right for you', 200.0, 'None', 'Referral'),
            ('Prevention C', 'Annual physical: doctor visit, skin exam, memory screen and PSA talk', 365, 0, 1.5, 'One visit. Bring the home logs, medicine list and test results. Ask: what is my risk for heart disease, diabetes, cancer and falls? Include a skin check, a short memory test (MoCA) to set a baseline, and a talk about the PSA test (not automatic; ask the pros and cons for you). [Strong]', 'Family doctor', 'None', 0.0, 'None', 'Appointment'),
            ('Prevention C', 'Eye and hearing checkup (same outing)', 365, 0, 2.0, 'Optometrist: eye exam including glaucoma, cataract and macular check (yearly after 65). Audiologist: hearing test every 1-2 years (hearing loss is linked to faster memory decline and isolation). Book them on the same day. [Strong]', 'Optometrist and audiologist', 'None', 120.0, 'None', 'Appointment'),
            ('Prevention C', 'Yearly scorecard and goals', 365, 0, 1.0, 'Add up the year: days of exercise, steps, sleep hours, vaccines, tests done. Compare to last year and pick two habits to improve. Update the health record binder: results, vaccine dates, medicine list, doctor and emergency contacts. [Moderate]', 'Me', 'None', 0.0, 'Folder', 'Notebook, binder'),
            # ---- Compliance: screenings, vaccines and records ----
            ('Compliance', 'Fall vaccines: flu and COVID-19 (one pharmacy visit)', 365, 0, 0.5, 'Every fall. Higher-dose flu vaccines are offered to people 65 and over; ask about the current COVID-19 dose. [Strong]', 'Pharmacist', 'Tell the pharmacist about allergies', 0.0, 'None', 'Appointment'),
            ('Compliance', 'Vaccine catch-up review: Td, Shingrix, pneumococcal, RSV', 3650, 0, 0.8, 'Td (tetanus and diphtheria) every 10 years. Shingles (Shingrix): 2 doses, 2-6 months apart, from age 50. Pneumococcal pneumonia: usually once at 65. RSV: discuss at 60 and over, especially with heart or lung disease. Ask the pharmacist what your history needs and what is covered. [Strong]', 'Pharmacist / doctor', 'Sore arm and tiredness for a day or two are common', 400.0, 'None', 'Appointment, vaccine record'),
            ('Compliance', 'Colon cancer screen: stool test (FIT) every 2 years, ages 50-74', 730, 0, 0.3, 'The kit is mailed in Saskatchewan. Colonoscopy is for a positive FIT or family history, as your doctor decides. [Strong]', 'Me / Saskatchewan screening program', 'Follow the kit instructions', 0.0, 'FIT kit', 'Mailed kit'),
            ('Compliance', 'One-time scans to ask about: aorta ultrasound, bone density, lung screen', 3650, 0, 1.5, 'Ask your doctor about each: (1) one-time aorta ultrasound for men 65-75 who ever smoked; (2) bone density scan for men 70 and over or earlier with fractures, steroids or low weight; (3) lung cancer screening for heavy long-term smokers aged 55-74. Bring this list to the annual physical. [Moderate]', 'Family doctor / imaging clinic', 'None', 0.0, 'None', 'Referral'),
            ('Compliance', 'Review will, power of attorney and health care directive', 365, 0, 1.5, 'Keep documents current and tell family where they are. Peace of mind is part of staying well. [Traditional]', 'Me / lawyer', 'None', 0.0, 'None', 'Documents'),
        ]),
}

# ---- Longevity by life stage ------------------------------------------------------------------------------------------------
# Six age-band groups, named so they sort in age order (0-12, 13-17, 18-39, 40-59, 60-74, 75 Plus). Delete any band you do not need.
# 60-74 is written out above; the other adult and senior bands are derived from it so the shared advice stays in step.
_LNG_NOTE = "Not medical advice. Check with your doctor, nurse or pharmacist."
def _lt(tab, name, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None"):
    return (tab, name, days, 0, hrs, desc + " [" + _LNG_NOTE + "]" if False else desc, who, safety, cost, cons, tools)

def _longevity_40_59(g):
    g = dict(g)
    g["prefix"] = "L40"; g["model"] = "Longevity Plan 40-59 {i}"; g["unit_names"] = {1: "My Longevity Plan (40-59)"}
    g["attrs"] = [("How this plan is ranked", "Strongest evidence first", "Labels: Strong, Moderate, Emerging, Traditional. These are the years to build muscle and fitness and to catch problems early."),
                  ("Different from the 60-74 plan", "Screenings start; fasting plan allowed", "Colon, breast, shingles and PSA talks begin around 50. Fasting-mimicking diet is allowed for healthy adults under 65."),
                  ("Not medical advice", "Check with your doctor", "Take your results and this list to your family doctor before changing medicines.")]
    rows = []
    for pair in g["checklist"]:
        new = []
        for it in pair:
            it = it.replace("about 1.2-1.6 g per kg a day over 65", "about 1.0-1.6 g per kg a day; Longo suggests less, Attia more")
            if it.startswith("Do something with purpose"): it = "Do something with purpose: learn, create, build, help someone (purpose in life is linked to longer life)"
            new.append(it)
        rows.append(tuple(new))
    rows.append(("Wake the muscles: 10 push-ups, 10 squats, 30-second plank (strength fades without use)", "Try something new each week: skill, sport, language, instrument (keeps the brain building)"))
    g["checklist"] = rows
    drop = ("Colon cancer screen", "One-time scans to ask about", "Vaccine catch-up review", "Quarterly qigong")
    tasks = []
    for t in g["tasks"]:
        if t[1].startswith(drop): continue
        t = list(t)
        if t[1].startswith("Fall vaccines"): t[5] = "Every fall: flu vaccine and the current COVID-19 dose if your doctor advises. [Strong]"
        if t[1].startswith("Eye and hearing"): t[2] = 730; t[5] = "Eye exam every 1-2 years (yearly with diabetes or family glaucoma) and a hearing test if you notice loss or work in noise. Book them on the same day. [Strong]"
        if t[1].startswith("Annual physical"): t[5] = "One visit. Bring the home logs, medicine list and test results. Ask: what is my risk for heart disease, diabetes, cancer and injury? Include a skin check. Talk about the PSA test from about 50 (not automatic; ask the pros and cons for you). [Strong]"
        if t[1].startswith("Coronary artery calcium"): t[5] = "A CT scan of the heart, not a blood test. Often considered from about 40-45 with early heart disease in the family or a high Lp(a); otherwise usually not needed yet. A score of 0 is reassuring. About $100-300, often not insured. Decide with your doctor. [Moderate]"
        tasks.append(tuple(t))
    tasks.append(("Compliance", "Screenings that start in your 40s and 50s", 730, 0, 1.0, "Ask your doctor about each: colon stool test (FIT) mailed every 2 years from age 50 in Saskatchewan; breast screening (mammogram) for women, usually from 40-50 on; cervical (Pap) screening for women on the program schedule; shingles vaccine (Shingrix, 2 doses) from 50; lung screening for heavy long-term smokers. [Strong]", "Family doctor / screening program", "None", 0.0, "FIT kit", "Appointment"))
    tasks.append(("Prevention A", "Quarterly build-the-base check: lift more, run farther", 91, 0, 1.0, "Strength and fitness built now are the savings account for after 60. Test: max push-ups, bodyweight squats or a heavy carry, and a 1.5-mile run or 12-minute test. Aim to beat last quarter. [Strong]", "Me", "Warm up; stop for chest pain or fainting", 0.0, "None", "Watch, timer"))
    tasks.append(("Prevention C", "Optional: fasting-mimicking diet (5 days, 1-3 times a year)", 182, 0, 5.0, "Longo's plan: a 5-day low-calorie, plant-based pack. Evidence is early and some is from his own company. Only for healthy adults under 65, never with diabetes, pregnancy, an eating disorder or low weight, and only after your doctor agrees. [Emerging]", "Me / Family doctor", "Not for anyone over 65, underweight or on diabetes drugs", 250.0, "Fasting-mimicking meal pack", "Kitchen scale"))
    g["tasks"] = tasks
    return g

def _longevity_18_39(g):
    g = dict(g)
    g["prefix"] = "L18"; g["model"] = "Longevity Plan 18-39 {i}"; g["unit_names"] = {1: "My Longevity Plan (18-39)"}
    g["attrs"] = [("How this plan is ranked", "Strongest evidence first", "Labels: Strong, Moderate, Emerging, Traditional. Habits set now carry forward for decades."),
                  ("Different from 40-59", "Less testing, more habit building", "Blood work every few years unless risk factors. Strength, fitness, sleep, mental health and not smoking matter most."),
                  ("Not medical advice", "Check with your doctor", "Take your results and this list to your family doctor before changing medicines.")]
    tasks = []
    for t in g["tasks"]:
        t = list(t)
        if t[1].startswith(("Coronary artery", "Optional private test", "Once-in-life blood")): continue
        if t[1].startswith("Annual blood work"): t[1] = "Blood work every 1-3 years (one fasting lab visit)"; t[2] = 1095; t[5] = "Ask your doctor how often for you: yearly with family history of diabetes, high cholesterol or early heart disease; otherwise every few years. Typical list: fasting insulin and HbA1c, lipid panel with ApoB, liver, kidney, blood count, thyroid, ferritin, vitamin D, B12. [Strong]"
        if t[1].startswith("Annual physical"): t[1] = "Checkup with the family doctor every 1-2 years"; t[2] = 730; t[5] = "Blood pressure, weight, mood, sleep, family history, vaccines, skin check, sexual health and contraception talk, cervical (Pap) screening for women on the program schedule. Ask about anything that worries you. [Strong]"
        if t[1].startswith("Eye and hearing"): t[2] = 730; t[5] = "Eye exam every 2 years (yearly with glasses changes or diabetes); hearing test if you notice loss, ringing or work or play in loud places (earplugs at concerts). [Strong]"
        t[5] = t[5].replace("Talk about the PSA test from about 50 (not automatic; ask the pros and cons for you). ", "")
        tasks.append(tuple(t))
    g["tasks"] = tasks
    return g

def _longevity_75_plus(g):
    g = dict(g)
    g["prefix"] = "L75"; g["model"] = "Longevity Plan 75 Plus {i}"; g["unit_names"] = {1: "My Longevity Plan (75 and over)"}
    g["attrs"] = [("How this plan is ranked", "Strongest evidence first", "Labels: Strong, Moderate, Emerging, Traditional. Falls, muscle, medicines and staying connected matter most."),
                  ("Different from 60-74", "Falls and medicines come first", "Gentler exercise, more protein, careful weight watching, yearly medicine reviews. Cancer screening stops by choice."),
                  ("Not medical advice", "Check with your doctor", "Take your results and this list to your family doctor before changing medicines.")]
    rows = []
    for pair in g["checklist"]:
        new = []
        for it in pair:
            if it.startswith("High-intensity intervals"): it = "Gentle intervals only if your doctor agrees: 1 minute brisk, 2 minutes easy, repeat 5 times|Friday"
            new.append(it)
        rows.append(tuple(new))
    rows.append(("Rise from a chair without using your hands, 10 times (leg strength keeps you independent)", "Wear steady shoes indoors; keep a night light on the path to the bathroom"))
    rows.append(("Eat something every 4-5 hours; add a protein snack (yogurt, eggs, nuts, cheese) if appetite is low", "Check the pill box was taken; ask for help with anything you cannot do safely"))
    g["checklist"] = rows
    tasks = []
    for t in g["tasks"]:
        if t[1].startswith(("Colon cancer screen", "Optional")): continue
        t = list(t)
        if t[1].startswith("Annual physical"): t[5] = "One visit. Bring the home logs, medicine list and test results. Ask: which medicines can be stopped or reduced? What is my fall risk? Include skin check and memory screen. Cancer screening after 74 is a personal choice with your doctor; PSA screening is usually not advised. [Strong]"
        tasks.append(tuple(t))
    tasks.append(("Prevention A", "Monthly weight and appetite check", 30, 0, 0.2, "Weigh yourself on the same scale. Losing weight without trying is a reason to call the doctor. Low appetite for two weeks should be reported. [Strong]", "Me", "None", 0.0, "None", "Scale"))
    tasks.append(("Prevention B", "Quarterly falls and walking check", 91, 0, 0.6, "Time a 10-foot (3 m) walk and stand up from a chair 5 times. Slower than last time, new unsteadiness or any near-fall: tell your doctor. Ask about a physiotherapist-led balance class. [Strong]", "Me / Physiotherapist", "Stay next to a counter or wall", 0.0, "None", "Stopwatch, chair"))
    g["tasks"] = tasks
    return g

# Source list for the child and teen plans. [1], [2]... in the text point to these. Entries marked (read) were opened and checked;
# entries marked (summary) were taken from published summaries and should be checked at the link before you rely on them.
_LNG_REFS_KIDS = [
    ("Source [1]", "CSEP Canadian 24-Hour Movement Guidelines, Early Years (0-4) (read)", "csepguidelines.ca/guidelines/early-years/"),
    ("Source [2]", "CSEP Canadian 24-Hour Movement Guidelines, Children and Youth (5-17) (read)", "csepguidelines.ca/guidelines/children-youth/"),
    ("Source [3]", "Public Health Agency of Canada: provincial and territorial routine vaccination schedules, Saskatchewan (read)", "canada.ca, search: provincial territorial routine vaccination infants children"),
    ("Source [4]", "Public health dental guidance: first visit by age 1, rice-grain then pea-size fluoride toothpaste, help brushing until about age 8 (read; Ontario health unit, confirm with your dentist)", "kflaph.ca/en/health-topics/dental-care-by-age.aspx"),
    ("Source [5]", "Canadian Paediatric Society / Caring for Kids: screen time and young children (summary)", "cps.ca, caringforkids.cps.ca"),
    ("Source [6]", "American Academy of Pediatrics: read aloud with children from birth (summary)", "aap.org, early literacy toolkit"),
    ("Source [7]", "Purpose in life as an asset for well-being and a protective factor against depression in adolescents, 2023 (summary)", "pmc.ncbi.nlm.nih.gov/articles/PMC10566624"),
    ("Source [8]", "Health Canada / Canadian Paediatric Society infant nutrition: vitamin D drops for breastfed babies, iron-rich first foods (from published guidance; confirm with your nurse)", "canada.ca, Nutrition for healthy term infants"),
    ("Source [9]", "Canada's Food Guide (healthy eating for children and youth)", "food-guide.canada.ca"),
]

def _longevity_kids(g):
    T = lambda tab, nm, days, hrs, desc, who="Parent", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    return dict(prefix="L00", model="Longevity Plan 0-12 {i}", units=1, unit_names={1: "My Child (0-12)"},
        labels=("Age", "Height (cm)", "Weight (kg)", "Health Card No.", "Family Doctor"),
        parts=("Vitamins & Feeding:", "Safety Gear:", "Dental & Hygiene:", "Play & Learning:", "Sleep:", "Records:"),
        attrs=[("How this plan is ranked", "Safety and sleep first", "Then movement, food, teeth, reading and play, vaccines. Written for the parent or caregiver."),
               ("Numbers in square brackets", "[1], [2] point to the source list", "Sources are listed below as 'Source [n]'. Each task says how strong the evidence is."),
               ("Vaccine dates", "Saskatchewan schedule [3]", "Your public health nurse books them. Dates here are the routine schedule only."),
               ("Not medical advice", "Check with your doctor or nurse", "Call 811 (Saskatchewan HealthLine) or 911 if worried.")] + _LNG_REFS_KIDS,
        checklist=[
            ("SAFETY: car seat or booster fitted right every trip; seat belt on", "SAFETY under 1 year: sleep on the back, bare firm crib, no pillows, bumpers or smoke"),
            ("SLEEP: babies 0-3 mo 14-17 h, 4-11 mo 12-16 h, 1-2 yrs 11-14 h, 3-4 yrs 10-13 h, 5-12 yrs 9-11 h [1][2]", "SLEEP: same bedtime and wake time; calm routine of bath, book, bed; screens off an hour before [1][2]"),
            ("MOVE (sweat): ages 5-12, 60 minutes of hard-enough-to-puff play; ages 1-4, 3 hours of any play [1][2]", "MOVE (bones and muscles): climbing, hopping, monkey bars, carrying, pushing, 3 days a week; vigorous play 3 days [2]"),
            ("BABIES: tummy time, 30 minutes total a day while awake; floor play; no strapped seating over 1 hour at a time [1]", "BABIES: talk, sing, make faces and read to your baby from birth [6]"),
            ("SCREENS: none under 2; no more than 1 hour at ages 2-4; no more than 2 hours of fun screen time at 5-12; none at meals or in bedrooms at night [1][2][5]", "READ together 15 minutes a day: look at pictures, ask questions, let them turn pages [6]"),
            ("FOOD: eat together at the table, no screens; vegetables or fruit at each meal; water and milk; limit juice, sugary drinks, chips and sweets [9]", "FOOD babies: breastmilk or formula first; vitamin D drops 400 IU a day if breastfed; iron-rich foods (meat, beans, iron cereal) from about 6 months [8]"),
            ("TEETH: wipe baby gums; once teeth show, brush twice a day for 2 minutes with fluoride toothpaste (rice-grain size under 3, pea size from 3); adult helps until about age 8 [4]", "TEETH: floss where teeth touch once a day (floss picks are fine); no bottle or juice in bed; water after snacks [4]"),
            ("HANDS: wash with soap before eating and after the bathroom or outdoor play; cover coughs", "SUN: hat, shade and sunscreen SPF 30+ in summer, especially 11 am to 3 pm"),
            ("PLAY: free outdoor play every day, weather allowing; let them get dirty and take safe risks", "PLAY: pretend play, building, drawing and music (practice for thinking and feelings)"),
            ("CONNECT: 10-15 minutes of one-on-one attention, phone down; hug, laugh, listen", "EMOTIONS: name feelings, stay calm, keep rules clear and the same; praise effort not talent"),
            ("SAFETY: helmet on bike, scooter, skates and sleds; adult within arm's reach near water", "SAFETY: medicines, cleaners, batteries and small objects locked or out of reach; hot water 49 C or less"),
            ("SKILLS: one small chore (set the table, tidy toys, feed the pet), ages 3 and up", "SCHOOL age: backpack, lunch, water bottle and homework ready the night before"),
            ("Family outing: walk, bike, park, swim|Saturday", "Check smoke and carbon monoxide alarms; plan the week's meals with the kids|Sunday"),
            ("Trim nails; check skin head to toe for rashes, ticks and bruises|Wednesday", "Library visit or new book to share|Saturday"),
            ("Playdate or time with friends or cousins|Friday", "Family game night or movie together, phones away|Friday"),
        ],
        tasks=[
            T("Prevention A", "Monthly growth, safety and sleep check", 30, 0.5, "Measure height and weight (babies are measured at clinic visits). Walk the home: outlets covered, stair gates, window locks, cords out of reach, furniture anchored, hot water at 49 C or less. Review the month's sleep against the age range [1][2]. [Strong]", "Parent", "None", 0.0, "None", "Tape measure, scale"),
            T("Prevention A", "Monthly alarm test and emergency plan", 30, 0.3, "Press the smoke and carbon monoxide test buttons; practise the exit plan; keep 811, poison control and 911 where everyone sees them. [Strong]", "Parent", "None", 5.0, "Batteries", "Step stool"),
            T("Prevention A", "Monthly screen, reading and play review", 30, 0.4, "Add up screen time against the limits [1][2][5]. Count the days you read together [6] and the days of outdoor play and hard play [1][2]. Pick one thing to improve next month. [Moderate]", "Parent", "None", 0.0, "None", "Notebook or phone note"),
            T("Prevention A", "Monthly independence and chores check", 30, 0.3, "School-age children: can they pack their bag, make a simple snack, tidy their room, and name three people to call for help? Add one new skill a month. [Emerging]", "Parent", "None", 0.0, "None", "None"),
            T("Prevention B", "Dental check every 6 months", 182, 1.5, "First dental visit by age 1 or when the first tooth shows [4]. Cleaning, fluoride varnish and sealants as the dentist advises. Ask whether your tap water is fluoridated. [Strong]", "Dentist", "None", 120.0, "None", "Appointment"),
            T("Prevention B", "Car seat, booster and helmet fit check", 182, 0.5, "Check the car seat for fit, expiry date and recalls as the child grows; move to the next stage only at the maker's weight and height limits. Check the helmet still fits and has no cracks. [Strong]", "Parent", "Install per the manual", 0.0, "None", "Car seat manual"),
            T("Prevention B", "Twice-yearly home safety and medicine cabinet check", 182, 0.8, "Throw out expired medicines, lock up cleaners, check gates, window guards, cords, button batteries and magnets. Re-check poison control number. [Strong]", "Parent", "Wear gloves with old medicines; return to a pharmacy", 10.0, "Locks, latches", "None"),
            T("Prevention B", "Twice-yearly swimming, bike and skills check", 182, 1.0, "Can they swim 25 m, ride a bike safely, cross a street with care, and say their name, address and a parent's phone number? Book lessons for any gap. [Moderate]", "Parent / Instructor", "Supervise closely near water", 80.0, "Lessons", "Swimsuit, bike"),
            T("Prevention C", "Well-child checkup (growth, development, safety)", 365, 1.0, "Babies are seen about 2, 4, 6, 12 and 18 months (same visits as vaccines), then yearly at 2-3 years, and before school. Ask about speech, play, behaviour, sleep, feeding and safety. Bring this list. [Strong]", "Family doctor / nurse", "None", 0.0, "None", "Appointment, health card"),
            T("Prevention C", "Vision and hearing screen", 365, 1.0, "Eye exam by an optometrist yearly in childhood; a hearing check if speech is late, there are repeated ear infections or the child turns up the TV. [Strong]", "Optometrist / audiologist", "None", 0.0, "None", "Appointment"),
            T("Prevention C", "Development and school-readiness check", 365, 1.0, "Ask the doctor or nurse about developmental screening around ages 2-3 and a school-readiness check around age 4-5 (speech, vision, hearing, vaccines up to date). [Moderate]", "Family doctor / nurse", "None", 0.0, "None", "Appointment"),
            T("Prevention C", "Swimming and water-safety lesson block", 365, 8.0, "Swimming and water-safety lessons from about age 4; adults supervise always, even with lessons. [Strong]", "Instructor", "Life jackets near open water", 100.0, "Class fee", "Swimsuit, towel"),
            T("Compliance", "Infant vaccines at 2, 4 and 6 months", 3650, 1.0, "Saskatchewan routine schedule [3]: rotavirus (2, 4, 6 mo), pneumococcal (2, 4 mo), DTaP-IPV-Hib (2, 4, 6 mo). Booked through public health. Ask about the RSV antibody for babies born in or entering the RSV season (Oct 1 to Mar 31) [3]. [Strong]", "Public health nurse", "Stay 15 minutes after shots; fever medicine per nurse", 0.0, "None", "Health card, vaccine record"),
            T("Compliance", "Vaccines at 12 and 18 months", 3650, 1.0, "Saskatchewan routine schedule [3]: 12 months pneumococcal, meningococcal, MMR-V (measles, mumps, rubella, chickenpox); 18 months DTaP-IPV-Hib and MMR-V. Hepatitis A is offered to Indigenous children [3]. [Strong]", "Public health nurse", "Stay 15 minutes after shots", 0.0, "None", "Health card, vaccine record"),
            T("Compliance", "School-entry booster at 4 to 6 years", 3650, 0.5, "Saskatchewan routine schedule [3]: tetanus, diphtheria, whooping cough and polio booster (Tdap-IPV) before or at school start. [Strong]", "Public health nurse", "Stay 15 minutes after shots", 0.0, "None", "Vaccine record"),
            T("Compliance", "Grade 6 school vaccines: HPV and hepatitis B", 3650, 0.5, "Saskatchewan school program [3]: HPV (2 doses) and hepatitis B (2 doses) in Grade 6, at about age 11-12. Watch for the consent form from school. [Strong]", "Public health nurse", "Stay 15 minutes after shots", 0.0, "None", "Consent form, vaccine record"),
            T("Compliance", "Yearly flu vaccine for ages 6 months and up", 365, 0.5, "Offered every fall to everyone 6 months and older in Saskatchewan [3]. First year under 9, two doses may be needed; the nurse will say. [Strong]", "Public health nurse / pharmacist", "Stay 15 minutes after shots", 0.0, "None", "Appointment"),
            T("Compliance", "Update the child's health record and emergency card", 365, 0.5, "Keep health card number, allergies, medicines, doctor, emergency contacts and vaccine record in one folder and give the school or daycare the current copy. [Moderate]", "Parent", "None", 0.0, "Folder", "Binder"),
        ])

def _longevity_teens(g):
    T = lambda tab, nm, days, hrs, desc, who="Teen / Parent", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    return dict(prefix="L13", model="Longevity Plan 13-17 {i}", units=1, unit_names={1: "My Teen (13-17)"},
        labels=("Age", "Height (cm)", "Weight (kg)", "Health Card No.", "Family Doctor"),
        parts=("Vitamins & Food:", "Sports & Safety Gear:", "Dental & Skin:", "Sleep & Mood:", "School & Purpose:", "Records:"),
        attrs=[("How this plan is ranked", "Sleep, movement and mood first", "Then food, purpose and goals, safety, substances, relationships, vaccines. Teens can use it themselves."),
               ("Numbers in square brackets", "[2], [3] point to the source list", "Sources are listed below as 'Source [n]'. Each task says how strong the evidence is."),
               ("Help is available", "Kids Help Phone 1-800-668-6868 or text 686868; 9-8-8", "Free and private, any time. Call 911 in an emergency."),
               ("Not medical advice", "Check with your doctor or nurse", "Call 811 (Saskatchewan HealthLine) if worried.")] + _LNG_REFS_KIDS,
        checklist=[
            ("SLEEP: 8-10 hours; same wake time every day; phone charges outside the bedroom [2]", "SLEEP: no caffeine or energy drinks after noon; screens off an hour before bed [2]"),
            ("MOVE (sweat): 60 minutes a day of moderate-to-vigorous activity: sport, biking, walking fast, dancing [2]", "MOVE (strength): muscle and bone work 3 days a week (push-ups, squats, climbing, weights with good form); vigorous 3 days [2]"),
            ("SCREENS: no more than 2 hours of recreational screen time a day; stand and move every 30-60 minutes [2]", "MOOD: check in with yourself: one word for how you feel; talk to a friend or a trusted adult every day"),
            ("PURPOSE: 20-30 minutes on something that matters to you: a skill, art, sport, building, helping someone [7]", "GOALS: write one goal and the next small step; review it Sunday [7]"),
            ("FOOD: breakfast; vegetables or fruit with meals; water instead of sugary or energy drinks [9]", "FOOD: protein and iron-rich foods (meat, eggs, beans); dairy or fortified drinks for calcium; teen bones are still building [9]"),
            ("TEETH: brush 2 minutes twice a day and floss once a day; mouthguard for contact sports [4]", "SKIN: sunscreen and hat; no tanning beds; wash face after sports"),
            ("SUBSTANCES: no vaping, tobacco, cannabis or alcohol while the brain is still developing; know your plan to leave or call for a ride", "SAFETY: helmet for bike, skateboard and snow sports; seat belt always; never ride with an impaired driver; phone away when driving or biking"),
            ("RELATIONSHIPS: respect and consent; you can always say no or leave; know a trusted adult to tell", "ONLINE: private accounts; do not share location or images; screenshot and tell an adult if bullied"),
            ("LEARN: homework routine with short breaks; 20 minutes of reading something you choose", "HABITS: pack your bag, set clothes and plan tomorrow before bed"),
            ("Family dinner or a real conversation with a parent, phones away|Wednesday", "Team sport, club or longer active outing|Saturday"),
            ("Time outdoors for about 2 hours in the week|Saturday", "Check in with a friend you have not talked to lately|Friday"),
            ("Plan the week: school, practice, sleep, one thing for fun|Sunday", "Check the first aid kit and your phone's emergency contacts|Sunday"),
        ],
        tasks=[
            T("Prevention A", "Monthly sleep, mood and screen check", 30, 0.4, "Look at the month: bedtimes and wake times against 8-10 hours [2], mood, school stress, social media time. If sad, anxious or angry most days for 2 weeks, tell a parent or doctor. [Strong]", "Teen / Parent", "If you feel hopeless, call or text 9-8-8 or Kids Help Phone now", 0.0, "None", "Sleep log"),
            T("Prevention A", "Monthly growth, strength and fitness check", 30, 0.4, "Height, weight, and a simple test (push-ups, squats, plank time, a timed run or fast walk). Growth spurts need extra food and sleep. Aim for 60 minutes a day [2]. [Moderate]", "Teen / Parent", "None", 0.0, "None", "Scale, tape measure, timer"),
            T("Prevention A", "Monthly purpose and goals review", 30, 0.4, "Check last month's goal and next step. Is there something you are building, learning or helping with? Purpose and meaning are linked to better wellbeing and less depression in teens [7]. [Moderate]", "Teen", "None", 0.0, "None", "Notebook"),
            T("Prevention A", "Monthly habit review: teeth, sleep, food, phone", 30, 0.3, "Which habit slipped: flossing, breakfast, bedtime, screens out of the bedroom? Choose one to fix. Habits formed now tend to last for decades. [Moderate]", "Teen / Parent", "None", 0.0, "None", "None"),
            T("Prevention B", "Dental check every 6 months", 182, 1.5, "Cleaning, cavities, braces check, wisdom-tooth plan, sealants. [Strong]", "Dentist", "None", 120.0, "None", "Appointment"),
            T("Prevention B", "Twice-yearly sports gear and safety check", 182, 0.5, "Helmet, mouthguard, shoes and pads still fit; no cracks. Learn the concussion warning signs and stop play if they appear. [Strong]", "Teen / Parent", "No return to play after a head knock until a doctor says so", 40.0, "Mouthguard, helmet as needed", "None"),
            T("Prevention B", "Twice-yearly skin, acne and sun check", 182, 0.4, "Look at moles and skin; ask the doctor about stubborn acne. Re-stock sunscreen and hat. [Moderate]", "Teen / Parent", "None", 15.0, "Sunscreen", "Mirror"),
            T("Prevention B", "Learn CPR and first aid (course)", 1095, 6.0, "Take a first aid and CPR course (St. John Ambulance, Red Cross) and renew every 3 years. Teens are old enough to help in an emergency. [Strong]", "Instructor", "None", 80.0, "Course fee", "Course booking"),
            T("Prevention C", "Yearly checkup with the family doctor", 365, 1.0, "Growth, blood pressure, vision, mood, sleep, vaping and substance use, sexual health and relationships (a private talk), sports readiness, skin. Teens may ask to be seen alone for part of the visit. [Strong]", "Family doctor", "None", 0.0, "None", "Appointment, health card"),
            T("Prevention C", "Yearly mental health check-in", 365, 0.5, "Short mood and anxiety screening forms at the checkup (PHQ-A, GAD-7). Treat sleep problems, bullying, panic or loss of interest as health problems, not weakness. [Strong]", "Family doctor", "Call or text 9-8-8 or Kids Help Phone in a crisis", 0.0, "None", "Screening forms"),
            T("Prevention C", "Yearly vision and hearing check", 365, 1.0, "Eye exam yearly if headaches, squinting or screen strain. Hearing test if you use earbuds loudly or notice ringing. Keep volume at 60% or lower. [Moderate]", "Optometrist / audiologist", "None", 0.0, "None", "Appointment"),
            T("Compliance", "Grade 8 school vaccines: meningococcal and tetanus-whooping cough", 3650, 0.5, "Saskatchewan school program [3]: meningococcal (Men-C-ACYW-135) and Tdap in Grade 8, at about age 13-14. Watch for the consent form. Catch up any missed Grade 6 doses (HPV, hepatitis B). [Strong]", "Public health nurse", "Stay 15 minutes after shots", 0.0, "None", "Consent form, vaccine record"),
            T("Compliance", "Yearly flu vaccine", 365, 0.5, "Offered every fall in Saskatchewan [3]. [Strong]", "Public health nurse / pharmacist", "Stay 15 minutes after shots", 0.0, "None", "Appointment"),
            T("Compliance", "Check the vaccine record and catch up", 365, 0.5, "At the yearly checkup, ask the nurse to compare the record with the Saskatchewan schedule [3] and book anything missed. [Strong]", "Public health nurse", "None", 0.0, "None", "Vaccine record"),
            T("Compliance", "Update the health record and emergency card", 365, 0.5, "Allergies, medicines, doctor, emergency contacts and vaccine record. Teens should know where it is and carry a copy. [Moderate]", "Parent / Teen", "None", 0.0, "Folder", "Binder"),
        ])

_LNG_70 = SAMPLE_GROUPS.pop("Longevity 60 Plus")
SAMPLE_GROUPS["Longevity 0-12 Kids"] = _longevity_kids(_LNG_70)
SAMPLE_GROUPS["Longevity 13-17 Teens"] = _longevity_teens(_LNG_70)
SAMPLE_GROUPS["Longevity 40-59 Adults"] = _longevity_40_59(_LNG_70)
SAMPLE_GROUPS["Longevity 18-39 Adults"] = _longevity_18_39(SAMPLE_GROUPS["Longevity 40-59 Adults"])
SAMPLE_GROUPS["Longevity 75 Plus"] = _longevity_75_plus(_LNG_70)
SAMPLE_GROUPS["Longevity 60-74"] = dict(_LNG_70, prefix="L60", model="Longevity Plan 60-74 {i}", unit_names={1: "My Longevity Plan (60-74)"})

# ---- Meaning, purpose and self-esteem (added to every Longevity age band) -------------------------------------------------
# Books and studies behind the MEANING and SELF-ESTEEM items. Books are summarised in a sentence, not quoted.
_LNG_REFS_MEANING = [
    ("Source [10]", "Viktor Frankl, Man's Search for Meaning (Beacon Press edition with the 1984 postscript on 'tragic optimism'; read in full, paraphrased not quoted): meaning can come from work or creating, from love and relationships, and from the stand taken toward unavoidable suffering; life asks each of us questions, and we answer by what we do; a lost future goal drains people; boredom and emptiness (the 'existential vacuum') lie behind much restlessness; humour lets us stand back from ourselves; paradoxical intention (aim for what you fear) is a short-term technique for phobias and sleeplessness. Clinical theory and personal testimony, not trial evidence (book)", "library or bookstore"),
    ("Source [11]", "Rollo May, The Courage to Create: creating something new takes courage and is part of a healthy life (book)", "library or bookstore"),
    ("Source [12]", "Erich Fromm, The Art of Loving and Man for Himself: love is a skill built from care, responsibility, respect and knowledge of the other person (books)", "library or bookstore"),
    ("Source [13]", "Nathaniel Branden, The Six Pillars of Self-Esteem: living consciously, self-acceptance, self-responsibility, self-assertiveness, living purposefully, personal integrity (book)", "library or bookstore"),
    ("Source [14]", "Jordan B. Peterson, 12 Rules for Life: stand up straight, tell the truth, pursue what is meaningful rather than what is expedient, take responsibility, and start by cleaning your own room (book; opinions on his wider views differ)", "library or bookstore"),
    ("Source [15]", "Ayn Rand, Atlas Shrugged and The Virtue of Selfishness: pride in achievement, productive work and independence (books; her philosophy is debated, so pair it with Fromm's care for others)", "library or bookstore"),
    ("Source [16]", "VanderWeele et al., JAMA Internal Medicine 2016: women attending religious services weekly or more had lower death rates in a large US cohort. An association, not proof; community and regular practice are likely part of it (summary)", "search: VanderWeele religious service attendance mortality"),
    ("Source [17]", "Alimujiang et al., JAMA Network Open 2019: older US adults with a stronger sense of purpose had lower death rates over several years (observational, summary)", "search: Alimujiang purpose in life mortality"),
    ("Source [18]", "Baumeister et al., Psychological Science in the Public Interest 2003: high self-esteem alone does not cause better performance; self-esteem that follows real effort and responsibility works better than empty praise (summary)", "search: Baumeister self-esteem 2003"),
]

def _add_meaning(name, g):
    band = "kids" if "0-12" in name else "teens" if "13-17" in name else "senior" if ("60-74" in name or "75" in name) else "adult"
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if band == "kids":
        rows = [
            ("MEANING: at bedtime ask 'What was good today? What was hard? What are you proud of?' and just listen [10][13]", "KINDNESS: do one kind thing for someone and say thanks at dinner (care and responsibility are parts of love [12])"),
            ("WONDER: look at stars, a bug, a tree or the weather together and ask 'I wonder why...' (awe and quiet are good for the spirit, in any tradition) [16]", "CREATE: let them make something: a drawing, a fort, a song, a story, and praise the effort, not just the result [11][18]"),
            ("STORIES: read or tell stories of people who faced hard things and kept going; talk about what made them brave [10]", "VALUES: say aloud one family value each day (honesty, courage, kindness) and point out when someone showed it [14]"),
            ("Family time for service, community or faith, as your family chooses: help a neighbour, visit someone, give to others|Sunday", "Family story night: grandparents' stories, photos, how our family got through hard times|Friday"),
        ]
        tasks = [T("Prevention A", "Monthly family values and story night", 30, 1.0, "Share stories of how the family and its elders faced hard times, what they valued and what they hoped for. Children who know their family story tend to cope better with stress. Read a story about courage together. [Moderate; Traditional]", "Parent", "None", 0.0, "None", "Photos, books"),
                 T("Prevention A", "Monthly praise-the-effort check", 30, 0.2, "Count how often praise went to effort, honesty and kindness rather than looks or grades alone. Self-esteem that follows real effort works better than empty praise [13][18]. [Moderate]", "Parent", "None", 0.0, "None", "None")]
    elif band == "teens":
        rows = [
            ("MEANING: ask each morning 'What is one thing I can do today that matters?' Meaning comes from what we make, whom we love and how we face hard things [10]", "MEANING in hard times: ask 'What could this teach me, and who could it help?' Pursue what is meaningful, not just what is easy [10][14]"),
            ("SELF-ESTEEM (the six pillars [13]): pay attention, accept yourself, take responsibility, speak up honestly, act on purpose, keep your word", "SELF-ESTEEM is earned: do one hard thing today and finish it; trust built by effort lasts longer than praise [13][18]"),
            ("COURAGE: do one small brave or creative thing: share an idea, make something, ask a question, try a new skill [11]", "HONESTY: tell the truth and keep one promise to yourself; stand up straight; keep your room and your desk in order [14]"),
            ("LOVE and CARE: show someone care, respect and responsibility today, and really try to understand them [12]", "QUIET: 5-10 minutes of silence, breathing, meditation, prayer or awe in nature, in your own tradition or none [16]"),
            ("GRATITUDE: three things you are thankful for, before bed", "INTEGRITY: name one value (honesty, courage, kindness) and one action that matches it"),
            ("Read 20 pages of a book that gives meaning (Frankl, Fromm, May, Branden, Peterson) or a biography|Sunday", "Talk with an adult you respect about meaning, goals and what you want to build|Wednesday"),
            ("Serve: help someone or volunteer for an hour (community, congregation or club) [16]|Saturday", "Own your goals: what is my own productive aim and what pride would doing it well bring? Balance it with care for others [12][15]|Sunday"),
        ]
        tasks = [T("Prevention A", "Quarterly values, purpose and self-esteem review", 91, 1.0, "Rate each of Branden's six pillars 1-5: living consciously, self-acceptance, self-responsibility, self-assertiveness, living purposefully, integrity [13]. Choose one to practise. Ask: where do I find meaning (making, loving, facing hard things) [10]? Teen purpose is linked to less depression [7]. [Moderate]", "Teen", "If you feel hopeless, call or text 9-8-8 or Kids Help Phone now", 0.0, "None", "Notebook"),
                 T("Prevention B", "Quarterly book: read and discuss one book", 91, 6.0, "Pick one from the list: Man's Search for Meaning [10], The Courage to Create [11], The Art of Loving [12], The Six Pillars of Self-Esteem [13], 12 Rules for Life [14]. Write three lines about what you will do differently. [Traditional]", "Teen / Parent", "None", 20.0, "Book", "Library card"),
                 T("Prevention B", "Twice-yearly mentor or elder conversation", 182, 1.0, "Sit down with a coach, teacher, grandparent or other adult you respect. Ask how they found meaning and got through hard times. [Moderate]", "Teen", "None", 0.0, "None", "None")]
    else:
        rows = [
            ("MEANING: name one thing today that gives your life purpose: work, creating, family, helping others. Purpose is linked to longer life [10][17]", "SELF-ESTEEM (the six pillars [13]): pay attention, accept yourself, take responsibility, speak up honestly, act on purpose, keep your word"),
            ("LOVE and CARE: show care and respect to one person and try to understand them (Fromm [12]); loneliness is a major risk factor", "QUIET: 5-10 minutes of silence, meditation, prayer or awe in nature, in your own tradition or none; community worship linked to longer life in studies [16]"),
            ("COURAGE: do one small creative or brave thing; the courage to create and to try keeps life growing [11]", "GRATITUDE: three good things before bed; honesty and integrity: one value, one action [14]"),
            ("Serve: volunteer, help a neighbour or join a group, congregation or club [16][17]|Saturday", "Read 20 pages of a book that gives meaning (Frankl, Fromm, May, Branden, Peterson) [10-14]|Sunday"),
        ]
        tasks = [T("Prevention A", "Quarterly meaning and self-esteem review", 91, 1.0, "Rate each of Branden's six pillars 1-5 [13] and choose one to improve. Ask where meaning comes from right now: what I make, whom I love, how I face hard things [10]. Purpose in life is linked to lower death rates in older adults [17]. [Moderate]", "Me", "If you feel hopeless, call or text 9-8-8 or your doctor now", 0.0, "None", "Notebook")]
        tasks.append(T("Prevention A", "Quarterly: turn the question around (what is life asking of me now?)", 91, 0.5, "Frankl argued that we should stop asking what life owes us and notice that each situation puts a question to us. Write the question your life is asking this season (a person who needs you, a job to finish, a loss to face) and one thing you will do to answer it. His own books are testimony and clinical theory, not trial results [10]. [Traditional]"))
        tasks.append(T("Prevention B", "Yearly: ask the 'second time around' question", 365, 1.0, "Frankl's challenge, in our words: imagine you are living this year for the second time and you already got something wrong the first time. What would you not repeat, and what would you finally do [10]? Write it down and pick one change. A thinking exercise, not a trial result. [Traditional]"))
        if band == "senior":
            tasks.append(T("Prevention A", "Quarterly: keep a goal ahead of you", 91, 0.5, "Frankl described how people who lose sight of any future goal, in prison, unemployment or retirement, can lose their drive [10]. Keep one project with a date ahead of you (a build, a trip, a skill, a book, a job for someone else) and name the next step. Purpose in life is linked to better health in observational studies. [Emerging]"))
            tasks.append(T("Prevention C", "Yearly life review and legacy letter", 365, 2.0, "Write down what you are proud of, what you learned, whom you want to thank and what you want to pass on (stories, values, photos). Share it with family. Life review is a long-used practice with moderate evidence for mood and meaning [10]. [Moderate]", "Me", "None", 0.0, "None", "Paper, photos"))
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_MEANING if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_meaning(_n, SAMPLE_GROUPS[_n])

# ---- "When something breaks": repair and recovery, plus a careful note on psychedelics -----------------------------------
# Like a failed bearing: fix it AND check what else it damaged. Added to every Longevity age band.
_LNG_REFS_REPAIR = [
    ("Source [19]", "Psychedelic-assisted therapy (psilocybin, MDMA): early clinical trials, mostly small; in 2024 the US FDA declined to approve MDMA-assisted therapy; access in Canada is through clinical trials or Health Canada's Special Access Program (summary; check current rules)", "search: Health Canada psilocybin Special Access Program"),
    ("Source [20]", "Ibogaine: studied for opioid withdrawal in small and observational reports; not an approved treatment in Canada; serious heart-rhythm risks and deaths have been reported (summary)", "search: ibogaine safety QT prolongation review"),
    ("Source [21]", "Cannabis: no good evidence that it lengthens life; risks include psychosis, dependence and effects on the developing brain; legal for adults 19 and over in Saskatchewan (summary)", "search: Canadian Centre on Substance Use cannabis"),
    ("Source [58]", "Neuro-electric therapy (NET): a small device with electrodes behind the ears, developed for addiction treatment by Dr Meg Patterson, a Scottish surgeon. Musicians Eric Clapton (early 1970s) and Pete Townshend were reported to have been treated. Both are respected, high-profile artists, and their accounts are a fair reason to test the device properly, but they are personal accounts, not trials. Supporters say it was dismissed too quickly; critics say there are no good controlled trials. A University of Aberdeen review (Fingleton and Matheson, 2012) found four studies of NET for opiate detox, all weak: a double-blind randomized trial of only 18 opiate-dependent patients (Gariti 1992, co-authored by the Pattersons) found no difference from a lower-current placebo in withdrawal or craving; a controlled study of 24 patients (Gossop 1984) found NET patients had more severe early withdrawal than those on methadone; and two uncontrolled studies reported better results (about 80% of the 51% of patients who could be followed up were reported addiction-free in Patterson's own 1984 series of 186; 36.8% known abstinent at one month in a 2012 open-label study of 57). The reviewers concluded the evidence is poor and that better trials with blinding, controls and long follow-up are needed. The UK Medical Research Council declined to fund a full investigation in 1974, and her family says new multi-centre trials are being prepared. Omni magazine (January 1983, article on Patterson's black box by Kathleen McAuliffe) reported her claim that all but four of about 300 patients completed detox drug-free (a detox result, not a long-term one), that she calls it rapid detoxification and not a cure, and that it works best with counselling and a supportive home. In that article only 50% answered her follow-up survey, she herself warned the figures were probably too favourable because people who relapsed were less likely to reply, and a heroin-treatment researcher (Dr Richard Resnick) asked for the missing test: electrodes fitted with the current off. Consumer versions of the device are sold, but none is an approved treatment for addiction. Unproven, not disproven (review, magazine, news, skeptic and family sources, summary)", "search: Meg Patterson neuro-electric therapy"),
    ("Source [59]", "Deep transcranial magnetic stimulation (BrainsWay H4 coil): US FDA clearance (August 2020) as an aid to short-term smoking cessation in adults. A 262-person randomized, sham-controlled trial found a four-week continuous quit rate of 17.1% with active treatment versus 7.9% with sham (intention to treat). A modest effect, in one condition (company announcement of the trial; summary)", "search: BrainsWay deep TMS smoking cessation FDA clearance"),
    ("Source [60]", "Systematic review of noninvasive brain stimulation for opioid use disorder, Neuromodulation 2020; 23(3):301-311: five studies, 150 participants combined, too few and too small to combine; the authors call the research thin and say the approach should be investigated further. Also: Auricular neural stimulation for opioid detoxification, Bioelectronic Medicine 2020 (a review; says behind-the-ear nerve stimulators may ease acute withdrawal and calls for more studies) (PubMed, summary)", "search: noninvasive brain stimulation opioid use disorder systematic review"),
]

def _add_repair(name, g):
    band = "kids" if "0-12" in name else "teens" if "13-17" in name else "adult"
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if band == "kids":
        rows = [("REPAIR: if something breaks (injury, illness, a hard time), treat it, then check what else it affected: sleep, mood, school, friends", "HELP: know who to call: Saskatchewan HealthLine 811, poison control, 911; Kids Help Phone 1-800-668-6868 for older kids")]
        tasks = [T("Compliance", "Yearly 'if something breaks' repair plan", 365, 0.5, "Write down who to call for injury, illness, mood or behaviour trouble, and where the health card and medicine list are. After any illness or injury, book a follow-up and ask what else it may have affected. Like a failed bearing: fix it, then check for collateral damage. [Moderate]", "Parent", "None", 0.0, "None", "Fridge sheet")]
    elif band == "teens":
        rows = [("REPAIR: if you slip (a bad night, a vape, a fight, a missed week), restart the next day and tell someone; help early works better", "HELP: Kids Help Phone 1-800-668-6868 or text 686868; 9-8-8; 811 for substance use help; psychedelics, cannabis and ibogaine are not for teens: the brain is still developing until the mid-20s [21]")]
        tasks = [T("Compliance", "Yearly 'if something breaks' repair and substance-help plan", 365, 0.5, "Know where to get fast help for substance use, mood or safety, without blame: 811, 9-8-8, Kids Help Phone, the family doctor, school counsellor. After any injury or illness, follow up and ask what else it may have affected. Psychedelics and cannabis carry real risks for teens (psychosis, dependence, memory and learning) [21]. [Strong]", "Teen / Parent", "Call 911 for overdose or danger", 0.0, "None", "Contacts list")]
    else:
        rows = [("REPAIR: if you slip (drink, smoke, skip a week), restart the next day; ask for help early. If something breaks, treat it and check what else it damaged", "WATCH for addiction: alcohol, opioids, methamphetamine and fentanyl cause the most harm and are best avoided completely; get help early (811, family doctor)")]
        tasks = [T("Compliance", "Yearly 'if something breaks' repair plan and substance check", 365, 0.8, "Keep a plan for what to do after an injury, illness or crisis: who to call, follow-up visits, and a check for what else was damaged (like replacing a failed bearing and checking the shaft). Answer the short AUDIT-C alcohol questions and ask your doctor about any substance use, with no blame. Help: 811, 9-8-8, family doctor, Saskatchewan addictions services. [Strong]", "Me / Family doctor", "Call 911 for overdose", 0.0, "None", "Contacts list")]
        age = 25 if "18-39" in name else 0
        tasks.append(T("Prevention C", "Ask about: supervised psychedelic-assisted therapy (information only)", 730, 0.5, "Some people describe psilocybin or LSD experiences as a reset that changed their sense of meaning, and early clinical trials of psilocybin (depression, end-of-life distress) and MDMA (trauma) are promising but small, and results are still being tested [19]. Ibogaine has been studied for opioid dependence but carries serious heart-rhythm risks and is not an approved treatment in Canada [20]. Legal access in Canada is through clinical trials or Health Canada's Special Access Program, with a trained team. Not for self-treatment: risks include panic, psychosis, and dangerous interactions with antidepressants, lithium and heart medicines. Cannabis has no proven longevity benefit; moderate use by adults carries risks too [21]. Talk to your doctor first. [Emerging]" + (" Not advised before about age 25 (brain still developing)." if age else ""), "Family doctor / psychiatrist", "Never mix with antidepressants, lithium or heart drugs without a doctor", 0.0, "None", "Appointment"))
        tasks.append(T("Prevention C", "Ask about: brain and nerve stimulation for addiction and cravings (information only)", 730, 0.4, "Researchers are testing gentle magnetic and electrical stimulation for addiction. Best evidence so far: deep transcranial magnetic stimulation was cleared by the US FDA in 2020 as an aid to quit smoking, after a 262-person sham-controlled trial (four-week quit rate 17.1% versus 7.9% with sham) [59]. For opioid use disorder, a 2020 review found only five small studies (150 people) and called the research thin [60]. Neuro-electric therapy, the small ear-electrode device used by Dr Meg Patterson, was reported to have helped Eric Clapton and Pete Townshend, two respected artists whose accounts are a good reason for proper trials; but personal stories are not trials, and the evidence is weak and disputed [58]. Not a self-treatment: do not buy or build devices. Ask your doctor or an addiction clinic what is available and proven. Not medical advice. [Emerging]"))
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    refs = _LNG_REFS_REPAIR if band != "kids" else []
    g["attrs"] = list(g["attrs"]) + [r for r in refs if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_repair(_n, SAMPLE_GROUPS[_n])

# ---- Branden's practical exercises (paraphrased from his books, not quoted) -------------------------------------------------
_LNG_REFS_BRANDEN = [
    ("Source [22]", "Nathaniel Branden, The Six Pillars of Self-Esteem (1994): the six practices; the morning and evening sentence-completion routine; self-responsibility; and how parents nurture a child's self-esteem through acceptance, respect, visibility, descriptive praise and age-fit choices (book, read)", "library or bookstore"),
    ("Source [23]", "Nathaniel Branden, The Psychology of Self-Esteem (1969): the original, deeper account of what self-esteem is (book)", "library or bookstore"),
    ("Source [24]", "Nathaniel Branden, Honoring the Self (1983): self-esteem, autonomy and the personal life (book)", "library or bookstore"),
    ("Source [25]", "Nathaniel Branden, The Power of Self-Esteem (1992): the short introduction, a good first read (book)", "library or bookstore"),
]

def _add_branden(name, g):
    band = "kids" if "0-12" in name else "teens" if "13-17" in name else "adult"
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if band == "kids":
        rows = [
            ("SEEN: get down to their level, listen, and show you understood what they felt or did, without lecturing; children who feel seen learn to see themselves [22]", "PRAISE what you saw, not a verdict: 'The books are in order and it was hard work, thank you' instead of 'good girl' [22]"),
            ("ACCEPT feelings without arguing or shaming: 'You are really angry.' You do not have to agree to accept [22]", "CHOICES that fit their age: two sweaters to pick from; 'What do you think?' before giving the answer [22]"),
            ("TOUCH: hugs, cuddles and safe, loving touch every day [22]", "RESPECT: talk to your child with the courtesy you would give a guest; please and thank you; fix the problem, not the child's worth [22]"),
        ]
        tasks = [T("Prevention A", "Monthly parent practice: seen, accepted, respected", 30, 0.4, "Look at the month. Did each child feel seen (I responded to what they felt and did)? Accepted (feelings heard, not shamed)? Respected (courtesy, choices fit for age)? Did praise describe what happened instead of judging? Pick one to do more of [22]. Branden: children are best helped toward independence by offering choices as fast as they can handle them [22]. [Moderate]", "Parent", "None", 0.0, "None", "Notebook")]
    else:
        rows = [
            ("SENTENCE COMPLETION in the morning, Mon-Fri (10 minutes): write 'Living consciously to me means...' and add at least 6 different endings fast; then 'If I bring 5 percent more awareness to my day...' (and my closest relationships, and one problem) [22]", "SENTENCE COMPLETION in the evening, Mon-Fri: 'When I reflect on what happens when I bring 5 percent more awareness to my day...' with at least 6 endings. Do not reread yesterday; do not think, just write [22]. Use the locked Private journal on the Philosophy page if you want it private"),
            ("RESPONSIBILITY: I am responsible for my choices, goals, time, how I talk to people, my happiness and for raising my own self-esteem; nobody owes me my wishes [22]", "Ask: 'What am I willing to do to get what I want?' A wish with a plan is a goal; a wish without one is a daydream [22]"),
            ("Weekend review of the week's endings, then 6 endings for: 'If any of what I wrote this week is true, it would be helpful if I...'|Sunday", "Start with the short book: Branden's The Power of Self-Esteem, 20 pages a week [25]|Saturday"),
        ]
        tasks = [T("Prevention A", "Quarterly 'one-week sentence completion' challenge", 91, 1.5, "For one week, Monday to Friday, do the morning and evening sentence stems from Branden: about 10 minutes each, 6 or more endings per stem, no rereading until the weekend [22]. Keep the notebook. Notice what changes. A step-by-step routine with moderate support from clinical practice, not from large trials. [Traditional]", "Me", "If distress rises, stop and talk to a doctor or counsellor", 0.0, "None", "Notebook")]
        if band == "teens":
            tasks.append(T("Prevention B", "Twice-yearly parent talk: seen, accepted, respected", 182, 1.0, "Sit down with a parent or trusted adult. Tell them what helps you feel heard, what choices you want, and what you want to take responsibility for. Parents: listen, accept feelings without lecturing, offer more choices as they are ready [22]. [Moderate]", "Teen / Parent", "None", 0.0, "None", "None"))
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_BRANDEN if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_branden(_n, SAMPLE_GROUPS[_n])

# ---- Gut microbiome: fermented foods and plant variety (added to every Longevity age band) ----
_LNG_REFS_GUT = [
    ("Source [26]", "Wastyk et al., Cell 2021: a Stanford trial in which 10 weeks of eating fermented foods (yogurt, kefir, kimchi, sauerkraut) increased gut microbiome diversity and lowered inflammation markers. Small trial, moderate evidence (summary)", "search: Wastyk fermented foods Cell 2021"),
    ("Source [27]", "McDonald et al., mSystems 2018 (American Gut Project): people eating 30 or more different plant foods a week had more diverse gut bacteria than people eating 10 or fewer. Observational (summary)", "search: American Gut Project 30 plants per week"),
]

def _add_gut(name, g):
    g = dict(g)
    if "0-12" in name:
        row = ("Try one new fruit or vegetable this week; count the different plants the family eats (aim high, a rainbow of colours) [27]|Sunday", "Yogurt with live cultures as a snack or breakfast (plain, with fruit added at home) [26]|Wednesday")
    elif "13-17" in name:
        row = ("Count the different plants you eat this week: fruit, vegetables, beans, nuts, seeds, whole grains, herbs; aim for 30 [27]|Sunday", "Yogurt with live cultures or kefir a few times a week; sauerkraut or kimchi if you like it [26]|Wednesday")
    else:
        row = ("Count your plants: aim for 30 different plants this week (vegetables, fruit, beans, nuts, seeds, whole grains, herbs, spices) to feed gut bacteria [27]|Sunday", "A fermented food most days (yogurt, kefir, sauerkraut, kimchi): your gut bacteria thrive on variety [26]|Wednesday")
    g["checklist"] = list(g["checklist"]) + [row]
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_GUT if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_gut(_n, SAMPLE_GROUPS[_n])

# ---- Covey's seven habits and "sharpen the saw" (added to every Longevity age band) ----
_LNG_REFS_COVEY = [
    ("Source [28]", "Stephen R. Covey, The 7 Habits of Highly Effective People (1989): be proactive; begin with the end in mind; put first things first; think win-win; seek first to understand; synergize; sharpen the saw (renew the physical, mental, social/emotional and spiritual dimensions). Paraphrased in our own words and checked against the book, not quoted (book)", "library or bookstore"),
    ("Source [29]", "Sean Covey, The 7 Habits of Highly Effective Teens (1998): the seven habits written for teenagers (book, not read for this plan)", "library or bookstore"),
    ("Source [30]", "Sean Covey, The 7 Habits of Happy Kids (2008): the seven habits as stories for young children (book, not read for this plan)", "library or bookstore"),
]

def _add_covey(name, g):
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if "0-12" in name:
        rows = [
            ("BE IN CHARGE OF YOU: pick one thing you can do all by yourself today, and do it [30]", "PLAY FAIR: share and take turns so everybody wins; listen to a friend before you talk [30]"),
            ("SHARPEN THE SAW|Sunday: look after your four parts this week: body (play), mind (learn something), heart (time with people), spirit (quiet, nature, a good story) [30]", "FIRST THINGS FIRST: do your chores and homework first, then play [30]|Sunday"),
        ]
        tasks = [T("Prevention A", "Monthly 'sharpen the saw' family check", 30, 0.5, "Ask the child and yourself: did we look after body (play, sleep, food), mind (reading, learning), heart (friends, family time) and spirit (quiet, nature, stories, kindness) this month? Pick one to do more of. Sharpening the saw is Covey's seventh habit; the kids' version is in [30]. [Moderate]", "Parent", "None", 0.0, "None", "Notebook")]
    elif "13-17" in name:
        rows = [
            ("BE PROACTIVE: when something goes wrong, pause and choose your response; put your energy into what you can change [29]", "BEGIN WITH THE END IN MIND: each morning ask what you want your life to be about, and check that today fits [29]"),
            ("SEEK FIRST TO UNDERSTAND: listen to one person today until they feel understood, before you give your view [29]", "THINK WIN-WIN: in a disagreement, look for the answer that works for both people [29]"),
            ("SHARPEN THE SAW|Sunday: renew all four parts this week: body (sport), mind (learn), heart (friends, family), spirit (quiet, nature, purpose) [28][29]", "FIRST THINGS FIRST: on Sunday pick the three most important things for the week, schedule them first, say no to the rest [29]|Sunday"),
        ]
        tasks = [T("Prevention A", "Monthly 'sharpen the saw' review", 30, 0.6, "Rate body, mind, heart and spirit 1-5 for the month. Which is lowest? Choose one action for it next month. Sharpening the saw, Covey's seventh habit, is preventive maintenance for a person [28][29]. [Moderate]", "Teen", "None", 0.0, "None", "Notebook"),
                 T("Prevention C", "Yearly personal mission statement", 365, 1.0, "Write a few lines on who you want to be and what you want to stand for, then check where your time goes. Begin with the end in mind, Covey's second habit [28][29]. Rewrite it each year. [Moderate]", "Teen", "None", 0.0, "None", "Notebook")]
    else:
        rows = [
            ("BE PROACTIVE: when something goes wrong, pause and choose your response; spend your energy on what you can influence [28]", "BEGIN WITH THE END IN MIND: each morning ask what you want your life to be about, and check that today fits [28]"),
            ("SEEK FIRST TO UNDERSTAND: listen to one person today until they feel understood, before you give advice [28]", "THINK WIN-WIN: in a disagreement, look for the answer that works for both people [28]"),
            ("SHARPEN THE SAW|Sunday: renew all four parts this week: body (exercise, food, sleep), mind (read, learn), heart (people, love), spirit (quiet, nature, purpose) [28]", "FIRST THINGS FIRST: on Sunday pick the three most important things for the week, schedule them first, say no to the rest [28]|Sunday"),
        ]
        tasks = [T("Prevention A", "Monthly 'sharpen the saw' review: body, mind, heart, spirit", 30, 0.6, "Rate body, mind, heart (relationships) and spirit (meaning, quiet, purpose) 1-5 for the month. Which is lowest? Choose one action for it next month. Sharpening the saw, Covey's seventh habit, is preventive maintenance for a person [28]. [Moderate]", "Me", "None", 0.0, "None", "Notebook"),
                 T("Prevention C", "Yearly personal mission statement review", 365, 1.0, "Write or revise a few lines on what you want your life to be about, and check where your time actually goes. Begin with the end in mind, Covey's second habit [28]. [Moderate]", "Me", "None", 0.0, "None", "Notebook")]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_COVEY if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_covey(_n, SAMPLE_GROUPS[_n])

# ---- Fromm layer: stillness, being versus having, care, listening, self-knowledge (added to every Longevity age band) ----
_LNG_REFS_FROMM = [
    ("Source [31]", "Erich Fromm, The Art of Loving (1956): love as a practised art needing discipline, concentration and patience; care, responsibility, respect and knowledge; being able to be alone is a condition for loving. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [32]", "Erich Fromm, To Have or To Be? (1976): living by having (owning, consuming) versus living by being (aliveness, giving, sharing). Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [33]", "Erich Fromm, The Art of Being (1989): practices of willing one thing, being awake and aware, daily concentration, and self-analysis. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [34]", "Erich Fromm, Man for Himself (1947): productive versus non-productive character orientations; developing your own powers. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [35]", "Erich Fromm, The Revolution of Hope (1968): hope as readiness to act, not passive waiting. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [36]", "Erich Fromm, On Disobedience (1981) and The Art of Listening (1994): thinking for yourself; listening with full attention. Paraphrased, not quoted (books)", "library or bookstore"),
    ("Source [38]", "Erich Fromm (with D.T. Suzuki and R. De Martino), Zen Buddhism and Psychoanalysis (1960): awareness, being awake, and becoming less of a stranger to yourself. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [44]", "P.D. Ouspensky, The Psychology of Man's Possible Evolution (1950), and G.I. Gurdjieff's teaching as described in In Search of the Miraculous (1949): self-observation, identification, and self-remembering. Paraphrased, not quoted. A philosophy of attention, not a treatment (books)", "library or bookstore"),
    ("Source [54]", "Moving meditation: tai chi, qigong, and the slow forms (kata) of martial arts such as karate, aikido and kung fu train attention through movement; Gurdjieff also taught 'Movements' as attention exercises. Reviews of tai chi suggest benefits for balance and fall prevention in older adults; evidence for other claims is mixed. Side note: many people find that awareness and movement practice feed motivation, since a calm, attentive start makes the next session easier and each session you finish is a small win; research on this is modest and mixed. Learn from a qualified teacher and go at your own pace. Traditional practice, not a treatment. Not medical advice. Check with your doctor (general reference)", "local class or library"),
    ("Source [37]", "Fromm's ideas are philosophy and psychology, not treatments. They support reflection; they do not replace professional care. Not medical advice. Check with your doctor", "n/a"),
]

def _add_fromm(name, g):
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if "0-12" in name:
        rows = [
            ("LISTEN WITH YOUR WHOLE ATTENTION: give the child five minutes of full attention, no phone, once a day [36]", "CARE FOR SOMETHING ALIVE: let the child water a plant or feed a pet and see it grow [31]"),
        ]
        tasks = [T("Prevention A", "Monthly family check: have we been together, not just near each other?", 30, 0.4, "Ask whether each person was really listened to this month. Care and attention are how love is practised [31][36]. [Traditional]", "Parent", "None", 0.0, "None", "Notebook")]
    elif "13-17" in name:
        rows = [
            ("STILL FOR TEN MINUTES: sit quietly, no phone, follow your breathing [31][33]", "THINK FOR YOURSELF: once a day, ask 'do I believe this, or just repeat it?' [36]"),
            ("BEING OR HAVING|Sunday: what did I do this week for its own sake, not to own or impress? [32]", "CARE: do one thing for somebody that nobody will know about [31]"),
        ]
        tasks = [T("Prevention A", "Monthly self-check: what do I want, and who am I becoming?", 30, 0.5, "Write a page on what you want and why. Are you drifting along with the crowd or choosing? [33][36]. [Traditional]", "Teen", "None", 0.0, "None", "Notebook")]
    else:
        rows = [
            ("MORNING STILLNESS: 10-20 minutes at the same time and place; sit, follow the breath, let thoughts pass [31][33]", "EVENING STILLNESS: 10 minutes before bed; follow the breath, no screen [31][33]"),
            ("ONE THING AT A TIME: for one hour today, do a single thing with full attention (a meal, a walk, a conversation) [31][33]", "LISTEN: let one person finish, then ask one more question before you reply [36]"),
            ("AWARENESS WALK: on one walk today, notice five things you can see, hear and feel, without naming or judging them [33][38]", "WHO IS DOING THIS?|Wednesday: when you notice you are on autopilot (eating, scrolling, worrying), stop for one breath and come back [33][38]"),
            ("SELF-OBSERVATION (key practice): three times today, pause and note, without judging, what you are doing, feeling and thinking right now [44]", "NOTICE IDENTIFICATION|Thursday: catch one moment today when you got swallowed by a worry, a screen or an annoyance; just notice it [44]"),
            ("BEING OR HAVING|Sunday: where this week did I live to own, consume or impress, and where to be and to give? [32]", "CARE, RESPONSIBILITY, RESPECT, KNOWLEDGE|Sunday: pick one person and show one of these four to them this week [31]"),
            ("MOVING MEDITATION: 10-20 minutes of slow tai chi, qigong or a martial-arts form; attention on the breath and on each movement, at your own pace [54]", "ONE-MINUTE CHECK-IN: three times today, stop and feel your feet, your breath and your hands; then carry on [44][54]"),
        ]
        tasks = [T("Prevention A", "Monthly self-analysis session (about 30 minutes)", 30, 0.5, "Sit with a notebook. Ask: what did I feel and not say? What patterns repeat? What did I avoid? Write freely, then ask what it might mean. Fromm describes methods such as free association and following a symptom or feeling [33]. Not therapy. [Traditional]"),
                 T("Prevention A", "Monthly self-observation review (about 20 minutes)", 30, 0.35, "Look back over the month: when was I most on autopilot? When did I get absorbed in a worry, a screen or an annoyance (what Ouspensky called identification)? When was I awake and present? Pick one situation to watch next month. Not therapy [44]. [Traditional]"),
                 T("Prevention C", "Quarterly 'having or being' review", 90, 1.0, "Look at spending, time and attention: how much goes to owning, consuming and impressing, and how much to living, giving and learning? Pick one change [32][34]. [Traditional]"),
                 T("Prevention C", "Yearly hope check: what am I ready to do, not just wish for?", 365, 0.5, "Write down one thing you hope for and one step you will take. Hope here means readiness to act [35]. [Traditional]")]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_FROMM if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_fromm(_n, SAMPLE_GROUPS[_n])

# ---- Motivation layer: habits shared by the wisdom traditions (adult Longevity groups) ----
_LNG_REFS_WISDOM = [
    ("Source [55]", "Wisdom traditions, from general knowledge, short quotes and paraphrase only (translations vary): Confucius, Analects 1.4 (Zengzi examines himself three times a day); Psalm 90:12 ('teach us to number our days'); Proverbs 4:23 ('Keep thy heart with all diligence'); Exodus 20:8 (remember the Sabbath day); Pirkei Avot 2:16 (you are not required to finish the work, but you may not walk away from it); a well-known hadith that the most loved deeds are the consistent ones, even if small; the Dhammapada on mindfulness versus heedlessness; the Ignatian Examen (a nightly review of the day). Not scripture study; ask a teacher of your own tradition for more (books)", "library, temple, church, mosque or synagogue"),
    ("Source [57]", "B.F. Skinner's work on operant conditioning and schedules of reinforcement (general knowledge, paraphrased): reward every time to start a behavior, then reward only some of the time on an unpredictable schedule (variable ratio), which tends to keep behavior going longest and makes it hardest to drop. The same mechanism is used by slot machines and some apps, so use harmless rewards, knowingly. Psychology, not treatment. Not medical advice. Check with your doctor or counsellor if you are in recovery from addiction or an eating disorder (general reference)", "library"),
    ("Source [64]", "Empathy: Singer T et al., Science 2004; 303:1157-1162 (watching a loved one in pain activates some of the same brain areas as feeling pain); Weng HY et al., Psychological Science 2013; 24:1171-1180 (short compassion training increased helping behavior); Klimecki OM et al., 2013-2014 (compassion training can protect against 'empathic distress' and burnout); Pettigrew TF, Tropp LR, 2006 meta-analysis (contact between groups tends to reduce prejudice); Kidd DC, Castano E, Science 2013 (literary fiction and social understanding; later replications were mixed). Empathy practices help in studies, with modest effects that vary. Paraphrased (journal articles, summary)", "search: Weng 2013 compassion training Psychological Science"),
    ("Source [69]", "Edwards JJ and colleagues, British Journal of Sports Medicine 2023: a network meta-analysis of 270 randomised trials (about 15,800 people) of exercise and resting blood pressure; isometric training (wall squat, handgrip) ranked highest for systolic pressure and every type of exercise except aerobic interval training lowered pressure. Found through a Prevention magazine item (December 2025) and checked against press coverage of the paper (journal article, summarised)", "journal or library"),
    ("Source [70]", "Sandstrom GM and Dunn EW, Social interactions and well-being: the surprising power of weak ties, Personality and Social Psychology Bulletin 2014: brief friendly contact with acquaintances and strangers was linked with a better mood and a greater sense of belonging. Small studies and an association, from general knowledge (journal article)", "journal or library"),
    ("Source [71]", "Sturm VE and colleagues, Emotion 2022 (online 2020): healthy older adults who took a weekly 15-minute 'awe walk' for eight weeks reported more everyday positive emotion and less distress than ordinary walkers. Small study (about 50 people), self-reported, from general knowledge (journal article)", "journal or library"),
    ("Source [72]", "Levy BR and colleagues, Journal of Personality and Social Psychology 2002: older adults with more positive views of their own ageing lived about seven and a half years longer, after adjusting for age, health, income and loneliness. Observational; a later study (2018) linked positive age beliefs to less dementia in people carrying a risk gene. From general knowledge (journal articles)", "journal or library"),
    ("Source [73]", "C.G. Jung's 1960 interview with Gordon Young on the art of living, in McGuire W and Hull RFC (eds), C.G. Jung Speaking (Princeton, 1977), pp. 450-452: his short list of what makes a person happy (health of body and mind, close relationships, a sense of beauty, reasonable living standard and satisfying work, and a philosophy or faith that copes with life's ups and downs). Paraphrased; read via a secondary summary, not the book", "library: C.G. Jung Speaking"),
    ("Source [62]", "Edward de Bono, Lateral Thinking (1970) and Six Thinking Hats (1985): deliberate sideways moves (random entry, provocation, challenging assumptions) to find new ideas. Widely taught; controlled research is thin, so treat it as a toolkit. Paraphrased in our own words (books, summary)", "library or bookstore"),
    ("Source [63]", "Howard Gardner, Frames of Mind (1983): several kinds of intelligence, used here only as a lens for noticing strengths, not a test; many psychologists doubt the intelligences are separate, measurable abilities (book, summary)", "library or bookstore"),
    ("Source [61]", "Free association (Freud's method of saying whatever comes to mind) and expressive writing (James Pennebaker and later reviews): writing freely about thoughts and feelings helps some people, but the average effect in studies is small. A self-reflection exercise, not therapy. Described in our own words (general knowledge, summary)", "search: expressive writing Pennebaker review"),
    ("Source [56]", "Common thread: Judaism, Christianity, Islam, Confucian thought, Buddhism and Hindu practice all attach daily or weekly habits (prayer or reflection at fixed times, a day of rest, washing, fasting and moderation, giving, gratitude, gathering) to meaning and community. Studies link religious community and regular practice with longer life and better wellbeing, but these are observational and cannot separate faith from social ties and habits. A tradition, not a treatment. No faith is promoted or left out. Not medical advice. Check with your doctor", "n/a"),
]

def _add_wisdom(name, g):
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    rows = [
        ("MOTIVATION|MORNING PAUSE: on waking, one minute: feel your breath, name one thing you will do well today (first of three daily pauses) [55]", "MOTIVATION|MIDDAY PAUSE: stop, stand, walk or stretch for a few minutes and notice how you are, in body and mind (second of three daily pauses) [44][54]"),
        ("MOTIVATION|NIGHTLY REVIEW: before bed, ask 'what did I do today, and what will I do better tomorrow?' (Confucius's three-times-a-day self-check, the Ignatian Examen) [55]", "MOTIVATION|SMALL AND CONSISTENT: do one tiny good habit today, even if small, because consistent deeds count most [55]"),
        ("MOTIVATION|ROLL THE DICE: after something dull or hard today, roll a die and do the matching item from your list of six joys (ideally ones that also make someone else happy); a friend or your AI helper can roll for you. Eyes open: you earned it [57]", "MOTIVATION|SEE THE WIN: tick it off and say 'done'; early on, reward yourself every time, then only some of the time [57]"),
        ("MOTIVATION|THANKS: say one thing you are grateful for before a meal or on waking (grace, blessings, thanks) [55][56]", "MOTIVATION|WASH before meals and after the toilet; the traditions made hygiene a daily ritual [56]"),
        ("EMPATHY: ask one person one real question and really listen; before you answer, guess what they are feeling [64]", "SEE IT THEIR WAY: when someone annoys you, say their best case in your own words before you reply [64]"),
        ("MOTIVATION|THINK SIDEWAYS: once today, ask 'what else could this be?' or 'what if the opposite were true?' about something you are working on (de Bono's lateral thinking) [62]", "MOTIVATION|STRENGTHS: which kinds of smarts did I use today: words, logic, space, music, hands, people, self-knowledge, nature? (Strengths lens, Philosophy page; a lens, not a test) [63]"),
    ]
    tasks = [
        T("Prevention A", "Weekly day of rest (a Sabbath)", 7, 2.0, "Pick one day with no work, no errands and no screens for part of it. Rest, walk, see people. 'Remember the Sabbath day' (Exodus 20:8) is one of the oldest scheduled habits. Rest and a weekly rhythm help keep you going [55][56]. [Traditional]"),
        T("Prevention A", "Refresh my list of six joys (for the dice)", 30, 0.2, "Write or update six things you enjoy that cost little and harm no one: music, a game of crib or a quick game of chess with someone, a call, a hot shower, time with someone you love, a funny video, a walk somewhere pretty. Pick ones that also bring joy to someone else when you can. Not food or anything risky if that is a problem for you. The daily 'roll the dice' reward uses this list [57]. [Traditional]"),
        T("Prevention A", "Weekly empathy practice: walk in their shoes", 7, 0.3, "Pick one person you disagree with or find difficult. Write their best case in three sentences, as they would say it. Then recall a time you were hurting and how you wanted to be treated, and use that as a bridge. Seeing someone you care about in pain activates some of the same brain areas as feeling pain yourself, so your own hard times can help you understand theirs [64]. You do not need to go looking for pain: use what life has already given you. Empathy is a skill that grows with practice; it is not a verdict on anyone. [Moderate]"),
        T("Prevention A", "Weekly compassion minutes (loving-kindness)", 7, 0.2, "Sit quietly for a few minutes and silently wish a person well, then someone neutral, then someone difficult, then yourself: 'may you be safe, may you be well, may you be at ease'. Studies of short compassion training found people became more willing to help others [64]. If it brings up pain, stop and talk with someone you trust. Not medical advice. [Moderate]"),
        T("Prevention A", "Weekly: greet a few neighbours or shopkeepers (weak ties)", 7, 0.1, "Say a real hello, with a smile and a sentence, to a few people you meet but do not know well: a neighbour, a clerk, someone at the bus stop. Short friendly contacts like these are linked with a better mood and a sense of belonging, and they cost nothing. An association from small studies [70]. [Emerging]"),
        T("Prevention A", "Weekly: take an 'awe walk' (15 minutes, look up and out)", 7, 0.25, "Walk for about 15 minutes and deliberately look for something that fills you with wonder: a wide view, the detail of a leaf, light through trees. In a small eight-week study of older adults, awe walkers felt more everyday joy and less distress than people who simply walked [71]. Costs nothing. [Emerging]"),
        T("Prevention A", "Quarterly: check what you believe about growing older", 91, 0.3, "Write down what you tell yourself about ageing ('it is all downhill', 'too late to learn'). Older adults with more positive views of their own ageing lived longer in a long observational study, even after allowing for health [72]. Replace one gloomy belief with a true, useful one, and act on it. This does not mean illness is your fault. [Emerging]"),
        T("Prevention A", "Monthly: do one thing that will outlast you", 30, 1.0, "Teach a skill, mentor someone in your trade, write down a family story, repair something for a neighbour. Erik Erikson called caring for what outlasts you the task of later adulthood ('generativity'); a stronger sense of purpose goes with longer life in several large observational studies. Jung also kept making things to the end [73]. [Emerging]"),
        T("Prevention B", "Quarterly: ask your doctor about isometric exercise for blood pressure", 91, 0.3, "Isometric exercise (holding a position without moving, such as a wall sit or a hand grip) lowered blood pressure at least as well as other kinds in a large review of trials [69]. Ask your doctor whether it suits you before starting, especially if your pressure is high or you have heart disease. Breathe normally, never hold your breath, and stop if you feel dizzy or have chest pain. [Moderate]", "Me", "Ask a doctor first if you have high blood pressure or heart disease; do not hold your breath"),
        T("Prevention B", "Monthly: spend time with someone outside your usual circle, or give your time", 30, 1.0, "Talk with, or volunteer alongside, someone of a different age, background or life from yours, and ask about their life. Contact between groups tends to reduce prejudice [64]. [Moderate]"),
        T("Prevention B", "Monthly: read a story from another life", 30, 2.0, "A novel, memoir or biography about someone unlike you. Readers of fiction tend to score higher on empathy, but the claim that reading raises empathy is mixed in the research, so enjoy it and treat the benefit as possible, not proven [64]. [Emerging]"),
        T("Prevention A", "Monthly review with a thinking partner (optional)", 30, 0.5, "Once a month, sit down with a thinking partner (a friend, a mentor, a counsellor or an AI) and review the month. Bring your habit counts, your strengths chart and your goals, and use the Monthly review prompt on the Philosophy page (Talk it over). Ask: what patterns do you see, what should I keep, shrink or drop, and what am I not seeing? Ask it to push back and disagree. Do not paste Private journal text into any online service. Take the advice as input, not a verdict, and finish with one real action, ideally involving a real person. Optional: skip a month if you like. Finish with a reward from your six joys. [Emerging]"),
        T("Prevention A", "Weekly think-sideways session (lateral thinking)", 7, 0.3, "Pick one problem you are stuck on. Spend ten minutes on the Think sideways box (Philosophy page): a random word, a provocation, or the six thinking hats. List ten alternatives before choosing, then sleep on it. Creativity is a habit: the more often you step sideways, the easier it gets. A toolkit, not a guarantee; research on it is thin [62]. [Traditional]"),
        T("Prevention A", "Weekly free association (private journal)", 7, 0.2, "Write whatever comes to mind for five to ten minutes without stopping, correcting or judging it, then read it back and note one surprise. Part of knowing yourself. Use the locked Private journal on the Philosophy page so nobody else can read it. Self-reflection, not therapy: if something painful comes up, stop and talk with a counsellor or someone you trust. Not medical advice [61]. [Traditional]", "Me", "If distress rises, stop and talk to a doctor or counsellor", 0.0, "None", "Notebook or Private journal"),
        T("Prevention A", "Weekly act of giving", 7, 0.5, "Give time, food, money or a visit to someone (tzedakah, zakat, tithe, alms in the traditions). Giving ties you to others and gives the daily habits a reason [55][56]. [Traditional]"),
        T("Prevention A", "Monthly motivation check: why am I doing this?", 30, 0.4, "Write one line on why these habits matter to you (the people, the work, the years you want). Is it still true? Pick one habit to restart. You are not required to finish the work, but you may not walk away from it (Pirkei Avot 2:16) [55]. [Traditional]"),
        T("Prevention C", "Yearly fast or simple-living week (optional)", 365, 1.0, "Many traditions set aside a time of fasting or moderation (Ramadan, Yom Kippur, Lent). Do something modest and safe, such as a week of plainer food or fewer screens. Do not fast if you have diabetes, take medication, are pregnant or have had an eating disorder, and ask your doctor first [56]. Not medical advice. [Traditional]", "Me", "Fasting can be unsafe with some conditions; ask your doctor", 0.0, "None", "None"),
    ]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_WISDOM if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity") and any(s in k for s in ("18-39", "40-59", "60-74", "75"))]:
    SAMPLE_GROUPS[_n] = _add_wisdom(_n, SAMPLE_GROUPS[_n])

# ---- Checked-claims layer: items from the 2025 claim review that are Moderate or better, or sensible and low risk, and can be done on a schedule (adults and seniors only) ----
_LNG_REFS_CHECKED = [
    ("Source [74]", "CANMAT 2016 clinical guidelines for major depressive disorder (Lam RW et al., Canadian Journal of Psychiatry): bright light therapy is a first-line option for seasonal affective disorder. From general knowledge, not re-read tonight (clinical guidance)", "journal or library"),
    ("Source [75]", "Morris MC et al., Neurology 2018 (Rush Memory and Aging Project): older adults who ate about a serving of leafy greens a day showed slower decline in thinking skills. Observational, so an association (journal article, from general knowledge)", "journal or library"),
    ("Source [76]", "Short bouts of brisk walking and other exercise are linked to lower anxiety in small trials and reviews. Early evidence, from general knowledge (reviews)", "journal or library"),
    ("Source [77]", "Osteoporosis Canada vitamin D recommendations 2010 (Hanley DA et al., CMAJ 2010; 182:E610): 400-1000 IU a day for healthy adults under 50, 800-2000 IU a day over 50. Read through a clinic summary; confirm the current guidance with your pharmacist or doctor. Winter sunlight at Canadian latitudes lacks the UVB needed to make vitamin D", "osteoporosis.ca; your pharmacist"),
    ("Source [78]", "Manson JE et al., the VITAL trial, New England Journal of Medicine 2019; 380:33-44: about 25,000 healthy US adults taking 2000 IU a day of vitamin D3 had no fewer cancers or cardiovascular events than placebo. Martineau AR et al., BMJ 2017;356:i6583 (pooled data from 25 trials): regular vitamin D lowered the risk of acute respiratory infection, with the clearest benefit in people who were deficient at the start; later trials in people with adequate levels found little. A commonly cited adult upper limit is 4000 IU a day (general knowledge; confirm with your pharmacist)", "journal or library"),
    ("Source [79]", "Dietary Reference Intakes (Health Canada and the US National Academies): each vitamin and mineral has a 'tolerable upper intake level'. Fat-soluble vitamins (A, D, E, K) can build up; high doses of B6 over long periods can damage nerves; beta-carotene supplements raised lung cancer in smokers in two large trials (ATBC and CARET). From general knowledge; confirm amounts with your pharmacist", "Health Canada Dietary Reference Intakes; your pharmacist"),
]

def _add_checked(name, g):
    if not any(x in name for x in ("18-39", "40-59", "60-74", "75")): return g
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    tasks = [
        T("Prevention A", "Winter weeks: 30 minutes of bright morning light (low winter mood)", 7, 0.5, "From autumn to spring, spend about half an hour in bright light soon after waking: outdoors on a bright morning, or at a 10,000 lux light box if your doctor agrees. Bright light is a first-line option for seasonal low mood in clinical guidance [74]. Seek help if low mood is severe or lasts. [Moderate]", "Me", "Ask a doctor first if you have eye disease, bipolar disorder or take medicines that make you sun-sensitive"),
        T("Prevention A", "Weekly: leafy greens most days (about a serving a day)", 7, 0.1, "Spinach, kale, lettuce, chard, collards. Older adults who ate about a serving a day showed slower decline in thinking skills, an association and not proof [75]. They are also good for the heart and gut. [Emerging]", "Me", "If you take warfarin (a blood thinner), keep your leafy greens steady and ask your doctor, because vitamin K affects it"),
        T("Prevention A", "Weekly: a brisk 10-minute walk when anxious or stuck", 7, 0.2, "When your mind is racing, walk briskly for ten minutes. Short bouts of walking and exercise are linked to lower anxiety in small trials [76]. It does not replace care when anxiety is severe or lasting. [Emerging]"),
        T("Prevention C", "Yearly: add up everything you take (vitamins, minerals, supplements)", 365, 0.3, "Write every pill, powder and fortified product on one list and add up the vitamin A, vitamin D, vitamin E, B6, zinc, iron and calcium across all of them. More is not better: fat-soluble vitamins can build up, long-term high B6 can damage nerves, and beta-carotene supplements raised lung cancer in smokers [79]. Staying near the daily value from a multivitamin and food is the sensible default. Take the list to your pharmacist or doctor. [Moderate]", "Me", "Do not exceed the upper limits; ask a pharmacist or doctor, especially in pregnancy, with kidney or liver disease, or on blood thinners"),
        T("Prevention C", "Yearly (October): review vitamin D with your doctor or pharmacist", 365, 0.3, "From about October to March the sun at our latitude is too weak to make vitamin D in your skin, so many Canadians use a supplement. Osteoporosis Canada's guidance (2010) is 400-1000 IU a day for healthy adults under 50 and 800-2000 IU a day over 50 [77]. A large trial in healthy adults found 2000 IU a day did not prevent cancer or heart disease, so it is for bones and for people who are low, not a cure-all [78]. Pooled trials found fewer chest and respiratory infections with regular doses, mostly in people who started with low levels, and little effect in people who were already replete [78]. Do not go over about 4000 IU a day without medical advice. Ask whether a blood test is worth it for you. [Moderate for avoiding deficiency; not shown to prevent heart disease or cancer in healthy adults]", "Me", "Ask your doctor or pharmacist about the dose, especially with kidney disease, high calcium or sarcoidosis; do not exceed the upper limit"),
    ]
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_CHECKED if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_checked(_n, SAMPLE_GROUPS[_n])

# ---- Back and neck layer (adult Longevity groups): walking, exercise, workshop posture, headache diary, red flags ----
_LNG_REFS_SPINE = [
    ("Source [65]", "Foster NE et al. Prevention and treatment of low back pain: evidence, challenges, and promising directions. The Lancet 2018; 391:2368-2383: first-line care is education, staying active and exercise, with routine imaging and opioids discouraged. Vanti C et al., Disability and Rehabilitation 2019 (systematic review): walking helped chronic low back pain about as well as other exercise (journal articles, summary)", "search: Foster 2018 Lancet low back pain"),
    ("Source [66]", "Blanpied PR et al. Neck Pain: Revision 2017, Clinical Practice Guidelines. Journal of Orthopaedic and Sports Physical Therapy 2017; 47(7):A1-A83: exercise (stretching and strengthening), education and, for some people, manual therapy are recommended for neck pain (guideline, summary)", "search: Blanpied 2017 neck pain clinical practice guideline"),
    ("Source [67]", "Jull G et al. A randomized controlled trial of exercise and manipulative therapy for cervicogenic headache. Spine 2002; 27:1835-1843: exercise and manipulative therapy each reduced the frequency and intensity of headaches that come from the neck, and the benefit lasted at 12 months (journal article, summary)", "search: Jull 2002 cervicogenic headache exercise manipulative therapy"),
    ("Source [68]", "Cochrane reviews of traction (Graham N et al. on neck pain; Wegner I et al., 2013, on low back pain with or without sciatica) found little clear benefit, from low-quality evidence. Traction should be tried only after a doctor or physiotherapist has checked you (reviews, summary)", "search: Cochrane traction neck pain low back pain"),
]

def _add_spine(name, g):
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    rows = [
        ("WALK: a short walk every day; walking is one of the best-supported things for a sore back, and it costs nothing [65]", "CHIN TUCKS: 10 slow chin tucks (draw your head straight back, like making a double chin) every few hours at the desk [66]"),
        ("NECK AND SHOULDER LOOSENING: 2 minutes of slow neck turns and shoulder-blade squeezes; gentle, never into sharp pain [66]", "HIP HINGE: bend from the hips with a straight back to pick things up, not from the waist [45]"),
        ("WORKSHOP POSTURE: when welding, grinding or working overhead, set the work at elbow height or use a stool or stand so your neck is not craned; change position often [66]", "SLEEP: a pillow that keeps your neck level; if you wake stiff, change your sleeping position or pillow [45]"),
        ("CORE AND BACK STRENGTH: 10 minutes of bird-dog, side plank and glute bridge, a few slow reps; stop at sharp or radiating pain [65]|Monday", "NECK STRENGTH: gentle holds, pressing your head into your hand for 5 seconds in each direction, 5 times; stop if dizzy or in pain [66]|Thursday"),
    ]
    tasks = [
        T("Prevention A", "Weekly back and neck routine (about 20 minutes)", 7, 0.4, "A walk, chin tucks, neck and shoulder loosening, then core work (bird-dog, side plank, glute bridge). Exercise and staying active are first-line for back and neck pain and work better than rest [65][66]. Start small, add a little each week, and stop at sharp pain, numbness or tingling. Not medical advice. [Strong]", "Me", "Stop at sharp, radiating or worsening pain", 0.0, "None", "Mat"),
        T("Prevention A", "Monthly workstation and workshop posture check", 30, 0.5, "Desk: screen at eye level, feet flat, chair supports your lower back. Workshop: set welding, grinding and bench work at elbow height; use a stool, stand or lift for heavy or overhead work; keep loads close; do not lift and twist [45][66]. Change position every 30 minutes. [Moderate]"),
        T("Prevention A", "Monthly neck-headache diary", 30, 0.3, "For a month, note when headaches start, what your neck was doing before (long screen time, welding, sleeping position), and how bad they were. Headaches that start in the neck often respond to exercise and manual therapy [67]. Take the diary to a physiotherapist or doctor. See the red flags below. [Moderate]", "Me", "Seek urgent care for a sudden severe headache, new numbness or weakness, trouble speaking or seeing, fever with back or neck pain, loss of bladder or bowel control, or pain after a fall or injury"),
        T("Prevention B", "Quarterly: have a physiotherapist or doctor look at recurring back or neck pain", 91, 1.0, "If back or neck pain, or neck-related headaches, keep coming back, get them assessed. Ask what exercises fit you and whether anything else is going on [65][66]. Not medical advice. [Moderate]", "Physiotherapist / doctor"),
        T("Prevention C", "Yearly: pillow, mattress and chair check", 365, 0.5, "Is your pillow still keeping your neck level? Does the mattress sag? Does your chair still support you? Replace what has worn out [45]. [Moderate]"),
        T("Prevention C", "Ask about: neck or back traction devices (information only)", 730, 0.3, "Home traction devices (over-door, inflatable collar, lying-down) are sold widely, but Cochrane reviews found little clear benefit, from low-quality evidence [68]. Some people say short sessions feel good. Ask a physiotherapist or doctor before using one, and never use traction after an injury or with numbness, weakness or dizziness. Not medical advice. [Traditional]", "Me", "Never use traction after an injury or with numbness, weakness or dizziness; ask first"),
    ]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_SPINE if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity") and any(s in k for s in ("18-39", "40-59", "60-74", "75"))]:
    SAMPLE_GROUPS[_n] = _add_spine(_n, SAMPLE_GROUPS[_n])

# ---- Encyclopedia layer: back care, stroke awareness, nuts and berries, appreciation, giving time (adult Longevity groups) ----
_LNG_REFS_ENC = [
    ("Source [45]", "The Encyclopedia of the Back and Spine Systems and Disorders (reference book): short bed rest only (a day or two) then normal activity; lift with a straight back, bend the knees, keep the load close, no lifting and twisting together; firm mattress and a supportive pillow; change positions; desk slump adds load on neck and shoulders. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [46]", "The Gale Encyclopedia of Neurological Disorders, entry on stroke (reference book): stroke risk rises with age (doubling each decade after 55), high blood pressure, diabetes, atrial fibrillation, smoking, inactivity and heavy drinking; know the warning signs and call 911 at once. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [47]", "Carlsen MH, Halvorsen BL, et al. The total antioxidant content of more than 3100 foods, beverages, spices, herbs and supplements used worldwide. Nutrition Journal 2010; 9:3. A food database: berries, nuts (walnuts highest), dark chocolate and many vegetables are rich in antioxidants. It measures antioxidant content, not health outcomes (open-access paper)", "nutritionj.com"),
    ("Source [48]", "An Encyclopedia of Small Fruit (reference book): berry and bush fruits for cold climates. Used only as a general guide to growing and choosing berries. Paraphrased (book)", "library or bookstore"),
    ("Source [49]", "The Encyclopedia of Mental Health (reference book): happiness needs conscious attention and the ability to see beyond disappointment and appreciate life; volunteering and reaching out help with loneliness during life transitions; mental health information is not a substitute for professional care. Paraphrased, not quoted (book)", "library or bookstore"),
]

def _add_enc(name, g):
    g = dict(g)
    if "0-12" in name or "13-17" in name:
        return g
    T = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    rows = [
        ("BREAK UP THE LYING DOWN: after resting your back, get up and walk a few minutes; long bed rest weakens the back [45]", "LIFT SMART: bend your knees, keep the load close, never lift and twist at once [45]"),
        ("DESK SLUMP CHECK: once an hour, head over shoulders, shoulders back, stand and change position [45]", "APPRECIATION: stop once today and notice something beautiful or something you are grateful for [49]"),
        ("KNOW THE STROKE WARNING SIGNS|Wednesday: sudden weakness or numbness of face, arm or leg; trouble speaking or seeing; sudden severe headache. Call 911 at once, do not wait [46]", "NUTS AND BERRIES|Wednesday: a handful of walnuts or other nuts, and some berries (saskatoons, blueberries) this week [47][48]"),
    ]
    tasks = [
        T("Prevention A", "Monthly back-care check: mattress, pillow, workstation, lifting habits", 30, 0.5, "Lie on your bed: is it firm enough, is your neck level on the pillow? Check chair height, screen at eye level, feet flat. Practise one lift the safe way. If you often rest your back, keep rests short and follow with a short walk [45]. Not medical advice. Back pain with numbness, weakness or bladder trouble needs a doctor right away. [Moderate]", "Me", "Stop if pain increases; see a doctor for numbness or weakness", 0.0, "None", "Notebook"),
        T("Prevention A", "Monthly 'give time' check: reach out or volunteer", 30, 1.0, "Once a month give an hour to someone or something: phone a lonely friend, help a neighbour, volunteer. Reaching out is helpful in life transitions such as retirement or loss [49]. [Moderate]", "Me", "None", 0.0, "None", "Notebook"),
        T("Prevention B", "Quarterly stroke-risk check: blood pressure, weight, smoking, alcohol, activity", 90, 0.5, "Check your blood pressure (home cuff or pharmacy). Note weight, smoking, alcohol (more than two drinks a day raises risk) and weekly activity. Ask your doctor about blood pressure, diabetes and irregular heartbeat. Risk rises with age, doubling each decade after 55 [46]. Not medical advice. Check with your doctor. [Strong]", "Me", "Seek emergency help for stroke signs", 0.0, "None", "Blood pressure cuff"),
        T("Prevention C", "Yearly: plan a berry patch or buy local berries in season", 365, 2.0, "Choose berries suited to your climate zone (for example saskatoon, haskap, currants on the prairies) and plant or buy them. Freeze extra for winter. Berries and nuts rank high in antioxidant content, but that table measures the food, not your health outcome [47][48]. [Emerging]", "Me", "None", 40.0, "Plants or berries", "Shovel"),
    ]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_ENC if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity")]:
    SAMPLE_GROUPS[_n] = _add_enc(_n, SAMPLE_GROUPS[_n])

# ---- Encyclopedia layer for the younger groups (kids and teens): backpacks, posture, bedroom screens, loud sound, sleep ----
_LNG_REFS_YOUNG = [
    ("Source [45]", "The Encyclopedia of the Back and Spine Systems and Disorders (reference book): posture, safe lifting, changing positions, and growing-spine care. Paraphrased, not quoted (book)", "library or bookstore"),
    ("Source [50]", "The Encyclopedia of the Back and Spine Systems and Disorders, entry on backpack safety (reference book): a backpack should not weigh more than about 10 to 15 percent of the child's body weight; carry it on both shoulders. Paraphrased (book)", "library or bookstore"),
    ("Source [51]", "Encyclopedia of Children, Adolescents, and the Media (reference book): screens in the bedroom; a Johns Hopkins and Stanford study of 8- and 9-year-olds found lower test scores in children with a TV in the bedroom. Paraphrased (book)", "library or bookstore"),
    ("Source [52]", "The Five Senses and Beyond: The Encyclopedia of Perception (reference book): sounds under 75 dB do not harm hearing; 85 dB and above can cause hearing loss; headphones can reach about 105 dB and damage hearing within minutes. Paraphrased (book)", "library or bookstore"),
    ("Source [53]", "Adolescence in America: An Encyclopedia (reference book): younger teens need about 9 to 10 hours of sleep, older teens about 7 to 8, and teens who sleep enough are less drowsy in the day. Paraphrased (book)", "library or bookstore"),
]

def _add_enc_young(name, g):
    g = dict(g)
    T = lambda tab, nm, days, hrs, desc, who="Parent", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
    if "0-12" in name:
        rows = [
            ("BACKPACK: weigh it on school days; no more than 10-15% of your child's weight, worn on both shoulders [50]", "SITTING: feet flat, back supported, move every 30 minutes; keep screens at eye level [45]"),
            ("BEDROOM: no TV, tablet or phone in the bedroom at night [51]|Monday", "LOUD SOUNDS: keep headphone volume low, and give ears a break; loud sound can damage hearing within minutes [52]|Monday"),
            ("WASH UP: hands washed after the bathroom, before eating and after outdoor play|Tuesday", "LOOK AT THE SKY: 10 minutes outside in daylight, no screens, once a day|Wednesday"),
        ]
        tasks = [
            T("Prevention A", "Monthly backpack, posture and sitting check", 30, 0.3, "Weigh the packed backpack and check it is under 10-15% of body weight. Check both straps are used, heavy items are close to the back, and your child can sit with feet flat. Ask your doctor at checkups whether the spine should be checked in the growth years [45][50]. [Moderate]", "Parent", "None", 0.0, "None", "Bathroom scale"),
            T("Prevention B", "Twice-yearly bedroom-screen and hearing-safety check", 180, 0.5, "Move screens out of the bedroom at night. Test headphone volume: you should be able to hear someone talking beside you. Sounds at 85 dB and above can cause hearing loss, so use ear protection near loud tools and events [51][52]. [Moderate]", "Parent", "None", 0.0, "Ear protection", "Earplugs"),
            T("Prevention B", "Concussion plan: know the signs and what to do", 180, 0.4, "After any knock to the head: stop play, watch for headache, vomiting, confusion, sleepiness or unusual behaviour, and see a doctor or call 911 if severe. Keep helmets fitted. Not medical advice. Check with your doctor. [Moderate]", "Parent", "Seek emergency help for severe symptoms", 0.0, "None", "Helmet"),
        ]
    else:
        rows = [
            ("BACKPACK: keep it under 10-15% of your body weight, both straps on, heavy items close to your back [50]", "BEDROOM: phone and screens out of the bedroom for the night; charge them elsewhere [51]"),
            ("EARS: keep headphone volume where you can still hear someone next to you; use earplugs at concerts and around loud tools [52]|Monday", "POSTURE: head over shoulders, feet flat, stand and stretch once an hour; strengthen your back and core with your strength work [45]|Monday"),
            ("SLEEP: younger teens need about 9-10 hours, older teens about 7-8; keep your wake time steady [53]|Sunday", "WASH UP: hands before eating; do not share vapes, bottles or towels|Tuesday"),
        ]
        tasks = [
            T("Prevention A", "Monthly backpack, posture and neck check", 30, 0.3, "Weigh your backpack (under 10-15% of body weight), check posture at your desk, and ask yourself whether your neck or back hurt after screens or bags. Stretch and strengthen your back and core [45][50]. [Moderate]", "Teen", "None", 0.0, "None", "Bathroom scale"),
            T("Prevention B", "Twice-yearly hearing-protection check", 180, 0.4, "Headphones can reach about 105 dB and damage hearing within minutes; anything 85 dB or above can cause hearing loss. Check volume limits, and keep earplugs for concerts and loud tools [52]. [Moderate]", "Teen", "None", 15.0, "Earplugs", "Earplugs"),
            T("Prevention B", "Quarterly sleep and bedroom-screen reset", 90, 0.5, "Track sleep for one week. Younger teens need about 9-10 hours, older teens 7-8. Move phones out of the bedroom and keep a steady wake time [51][53]. [Moderate]", "Teen", "None", 0.0, "None", "Notebook"),
            T("Prevention B", "Concussion plan: know the signs and what to do", 180, 0.4, "After a head knock: stop play, watch for headache, vomiting, confusion or drowsiness, and see a doctor, or call 911 if severe. Keep your helmet fitted. Not medical advice. Check with your doctor. [Moderate]", "Teen", "Seek emergency help for severe symptoms", 0.0, "None", "Helmet"),
        ]
    g["checklist"] = list(g["checklist"]) + rows
    g["tasks"] = list(g["tasks"]) + tasks
    have = {a[0] for a in g["attrs"]}
    g["attrs"] = list(g["attrs"]) + [r for r in _LNG_REFS_YOUNG if r[0] not in have]
    return g

for _n in [k for k in SAMPLE_GROUPS if k.startswith("Longevity") and ("0-12" in k or "13-17" in k)]:
    SAMPLE_GROUPS[_n] = _add_enc_young(_n, SAMPLE_GROUPS[_n])

# ---- Preparedness: home and family readiness for the prairies (power cuts, blizzards, floods, smoke) ----
_PREP_NAME = "Preparedness: Home & Family"
_prep_t = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
SAMPLE_GROUPS[_PREP_NAME] = dict(
    prefix="PRP",
    model="Home Preparedness Plan {i}",
    labels=("People Covered", "Water Stored", "Food Stored", "Heat / Power Backup", "Emergency Contact"),
    parts=("Water & Food:", "First Aid & Medicines:", "Light, Power & Heat:", "Tools & Fire Safety:", "Documents & Cash:", "Vehicle Kit:"),
    attrs=[("People covered", "2 adults, 1 pet", "Change to match your home"),
           ("Plan length", "At least 72 hours, working toward 2 weeks", "Government of Canada advice is 72 hours as a minimum. The longer goal is your choice [39]"),
           ("Source [39]", "Government of Canada, Get Prepared: 72-hour emergency kit and family emergency plan. Described from general knowledge, not quoted (website: getprepared.gc.ca)", "getprepared.gc.ca"),
           ("Source [40]", "Prudent Food Storage FAQ (food storage and rotation). Paraphrased, not quoted (document)", "from the document you sent"),
           ("Source [41]", "Survival Bible (general preparedness reference). Paraphrased, not quoted (book)", "from the book you sent"),
           ("Source [42]", "Tappan on Survival (general preparedness reference). Paraphrased, not quoted (book)", "from the book you sent"),
           ("Source [43]", "Preparedness advice varies with your home, health and region. Not medical or legal advice. Check local rules and with your doctor", "n/a")],
    checklist=[
        ("Check smoke and carbon monoxide alarm lights are working", "Check flashlight is where it belongs [39]"),
        ("Phone charged and charger or power bank ready", "Check the car has at least half a tank of fuel in winter [39]"),
        ("Check the first-aid kit is stocked and easy to reach", "Check you have a few days of your medicines on hand [39]"),
        ("Check stored water is sealed and in date [39][40]|Monday", "Rotate the oldest food to the front of the shelf [40]|Monday"),
        ("Walk the house: any water leak, space heater or cord problem?|Tuesday", "Check the furnace filter and the outdoor vents are clear of snow|Tuesday"),
        ("Check battery lantern, radio and spare batteries work [39]|Wednesday", "Check the winter car kit is in the vehicle (blanket, candle, shovel, jumper cables) [39]|Wednesday"),
        ("Check you know where the main water shut-off and electrical panel are|Thursday", "Check you know how to use the fire extinguisher|Thursday"),
        ("Check cash on hand (small bills) and a paper list of key phone numbers [39]|Friday", "Check pet food, litter and any pet medicines for a week [39]|Friday"),
        ("Check you have a plan to stay warm for 72 hours without power [39]|Sunday", "Talk to your household or a neighbour about one 'what if' [39]|Sunday"),
    ],
    tasks=[
        _prep_t("Prevention A", "Test smoke and carbon monoxide alarms", 30, 0.3, "Press the test button on every alarm. Replace weak batteries. Alarms usually need replacing after about 10 years; check the date on the back. [Strong]", "Me", "Use a stable step stool", 10.0, "Batteries", "Step stool"),
        _prep_t("Prevention A", "Check and rotate stored food and water", 30, 1.0, "Eat the oldest food first and replace it. Date new items with a marker. Check cans for dents or swelling and throw out any that are damaged. Keep water in clean, sealed food-grade containers; replace it on a schedule you set [39][40]. [Moderate]", "Me", "Throw out swollen or leaking cans", 40.0, "Food, water", "Marker, labels"),
        _prep_t("Prevention A", "Power-outage test: run the house on the backup plan for an evening", 90, 2.0, "Turn off the main breaker or just use only the backup light and heat for a few hours. Note what you wished you had. Never run a fuel heater, barbecue or generator indoors or in an attached garage; carbon monoxide can kill. [Strong]", "Me", "Carbon monoxide; keep a working CO alarm", 0.0, "None", "Lanterns, radio"),
        _prep_t("Prevention A", "Review the winter car kit", 30, 0.5, "Blanket, warm clothes, boots, candle and matches in a tin, shovel, jumper cables, flashlight, snacks, water, first-aid kit, phone charger. Check the spare tire. Tell someone your route in bad weather [39]. [Moderate]", "Me", "None", 20.0, "Snacks", "Car kit"),
        _prep_t("Prevention B", "Check medicines and first-aid kit dates", 90, 0.5, "Replace expired items. Keep a few days of prescriptions on hand if your pharmacy and doctor allow it. Keep a printed list of your medicines and allergies. Not medical advice. Check with your doctor. [Moderate]", "Me", "None", 25.0, "First-aid items", "Notebook"),
        _prep_t("Prevention B", "Check fire extinguisher, flashlights and batteries", 90, 0.5, "Check the extinguisher gauge is in the green and the pin is in place. Replace flashlight batteries. Keep spares dated. [Strong]", "Me", "None", 15.0, "Batteries", "Flashlight"),
        _prep_t("Prevention B", "Update the family emergency plan and contact list", 180, 1.0, "Write who to call, where to meet if you can't get home, who has a spare key, and where your documents are. Share it with a neighbour or relative [39]. [Moderate]", "Me", "None", 0.0, "None", "Notebook"),
        _prep_t("Prevention C", "Yearly: documents, cash and backups", 365, 1.5, "Keep copies of ID, insurance, will and key records in a waterproof pouch or safe, and a digital copy in a second place. Keep a little cash in small bills [39]. [Moderate]", "Me", "None", 10.0, "Folder, pouch", "Scanner"),
        _prep_t("Prevention C", "Yearly: heating and flood readiness", 365, 2.0, "Have the furnace serviced. Clear eavestroughs and drains before freeze-up. Know the safe way to shut off water, gas and power. Check your insurance covers sewer backup and overland water if that matters where you live. [Moderate]", "Me", "Gas and electrical hazards; call a qualified tradesperson", 150.0, "None", "Ladder"),
        _prep_t("Prevention C", "Yearly: build up one more day of food and water", 365, 1.0, "Goal: add one day of food and water to your reserve each year until you reach the number of days you want. Store only what you will eat, and rotate it [40]. [Traditional]", "Me", "None", 40.0, "Food, water", "Shelf"),
        _prep_t("Prevention C", "Yearly: practise one skill (first aid, fire, navigation, cooking without power)", 365, 3.0, "Take a first-aid course, light a fire safely, read a map, or cook a meal on a camp stove outdoors. Skills weigh nothing and are never used up [41][42]. [Traditional]", "Me", "Use a stove outdoors only", 80.0, "None", "Course"),
    ],
)
SAMPLE_GROUPS[_PREP_NAME]["checklist"] = list(SAMPLE_GROUPS[_PREP_NAME]["checklist"])

# ==========================================================================================
# TOWNS / RMs: one asset for a small town, village or rural municipality.
# Covers water, sewer and lagoon, electrical, fleet and roads, buildings, and regulatory reminders.
# The intervals are EXAMPLES based on general practice and on Saskatchewan Water Security Agency guidance
# (WSA 545 Municipal Drinking Water Quality Monitoring Guidelines, Edition 6). Each system's Permit to Operate can
# change them, so always follow the permit, the manufacturer's manuals and current Saskatchewan rules.
# These are reminders only. They are not legal advice and do not say any system meets a rule.
# ==========================================================================================
_TWN_NAME = "Towns / RMs"
_tw = lambda tab, nm, days, hrs, desc, who="Operator", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)
SAMPLE_GROUPS[_TWN_NAME] = dict(
    prefix="TWN",
    model="Town / RM {i}",
    units=1,
    unit_names={1: "Town / RM"},
    labels=("Population Served", "Water Source", "Sewage System", "Permit to Operate No.", "Lead Operator"),
    parts=("Water Wells, Treatment & Chlorination:", "Reservoir, Mains, Hydrants & Valves:", "Sewer, Lift Stations & Lagoon:",
           "Electrical, Panels & Standby Generators:", "Fleet, Roads, Culverts & Public Works:", "Buildings, Arena, Fire Hall & Playgrounds:"),
    attrs=[("Population served", "1,200 (change to match your town or RM)", "Sampling rules depend on the number of people served"),
           ("Water source", "Groundwater wells, chlorinated (example)", "Surface or blended sources have stricter sampling [1]"),
           ("Sewage system", "Gravity sewer, 1 lift station, 2-cell lagoon (example)", "Lagoon release rules are in your Permit to Operate [2]"),
           ("Permits", "Waterworks and sewage works Permits to Operate", "Keep copies where the operator can find them [3]"),
           ("Source [1]", "Water Security Agency, WSA 545 Municipal Drinking Water Quality Monitoring Guidelines, Edition 6 (June 2026). Summarised, not quoted (wsask.ca)", "wsask.ca"),
           ("Source [2]", "Water Security Agency wastewater page and documents it lists: EPB 310 two-cell lagoon O&M, EPB 338 compliance monitoring, EPB 267 upset reporting, WSA 531 monitoring wells (wsask.ca)", "wsask.ca"),
           ("Source [3]", "Water Security Agency drinking water page and documents it lists: WSA 523 permit, EPB 258 monthly records review, EPB 536 annual consumer notice, EPB 540 emergency response planning, EPB 505 adverse results (wsask.ca)", "wsask.ca"),
           ("Source [4]", "Government of Saskatchewan, municipal financial reporting: audited statements due July 1 (cities September 1) (saskatchewan.ca)", "saskatchewan.ca"),
           ("Source [5]", "General municipal practice (hydrants, valves, generators, fleet, playgrounds). Intervals are examples. Follow your manuals and local rules. Not legal advice", "n/a")],
    checklist=[
        ("Read free chlorine at the water plant outlet and write it down [1]", "Check turbidity and the water looks clear [1]"),
        ("Check wells, pumps and reservoir level: anything running too long or alarming?", "Check chlorine feed pump and chlorine supply"),
        ("Check the lift station: pumps cycling, no alarm, wet well level normal", "Walk the lagoon fence, gate and inlet: anything unusual? [2]"),
        ("Check the standby generator has fuel and shows no fault", "Check heat and lights at the water plant, fire hall and town office"),
        ("Check town trucks, grader and mower: fuel, fluids and lights", "Any hazards on the streets, sidewalks or playground today?"),
        ("Take the weekly bacteriological sample and send it to the lab [1]|Monday", "Read free and total chlorine at the same spot as the sample [1]|Monday"),
        ("Walk the hydrants and valve boxes: snow, damage or leaks?|Tuesday", "Check the reservoir hatch, vents and screens are secure|Tuesday"),
        ("Run the standby generator for 15 to 30 minutes|Wednesday", "Check emergency lights and exit signs in the hall and arena|Wednesday"),
        ("Check the lagoon dikes, burrowing animals and water level [2]|Thursday", "Check the sewer lift station float switches and alarm light|Thursday"),
        ("Check the bulk water station and meters for leaks or damage|Friday", "Write the week's water and sewer notes in the operator log|Friday"),
        ("Check that today's calendar has no sampling or reporting due [1][3]|Monday", "Check phone numbers for the WSA and the lab are posted [3]|Monday"),
    ],
    tasks=[
        # ----- Prevention A: monthly routines -----
        _tw("Prevention A", "Monthly review of waterworks operating records", 30, 2.0, "Review the month's records: chlorine, turbidity, pump hours, alarms and sample results. Sign and file them. This matches the WSA's monthly review of operational records (EPB 258). Check your Permit to Operate for exact requirements [3].", "Qualified waterworks operator", "None", 0.0, "None", "Operator log"),
        _tw("Prevention A", "Check chlorine supply and feed pump", 14, 0.5, "Count chlorine on hand and order more before you run low. Check the feed pump, tubing and injection point for leaks or wear.", "Qualified waterworks operator", "Chlorine hazard: ventilate, wear gloves and eye protection", 40.0, "Chlorine, tubing", "PPE, spare tubing"),
        _tw("Prevention A", "Run backup generator under load and log it", 30, 1.0, "Run the standby generator for at least 30 minutes with the load on. Check fuel, oil, coolant, battery, transfer switch and exhaust. Log hours.", "Electrician or operator", "Carbon monoxide; keep doors open", 30.0, "Fuel, oil", "Log book"),
        _tw("Prevention A", "Lift station pump run, float and alarm test", 30, 1.5, "Check both pumps run in turn, float switches work and the high-level alarm sounds and calls out. Look for grease, rags and odours.", "Utility operator", "Confined space: never enter the wet well without proper training and equipment", 20.0, "None", "Hand tools, gloves"),
        _tw("Prevention A", "Lagoon walk-around: dikes, inlet, outlet and fence", 30, 1.0, "Look for erosion, burrowing animals, cattails and trees on the dikes, blocked inlet or outlet, and damaged fences or signs. Note levels. See the two-cell lagoon guide (EPB 310) [2].", "Utility operator", "Slippery slopes and deep water", 0.0, "None", "Gauge, camera"),
        _tw("Prevention A", "Hydrant and valve box visual check", 30, 1.5, "Walk the hydrants and valve boxes. Clear snow and weeds. Note leaks, damage and hydrants that are hard to find.", "Public works", "Traffic and lifting hazards", 0.0, "None", "Shovel, hydrant wrench"),
        _tw("Prevention A", "Emergency lights, exit signs and extinguisher tags", 30, 1.0, "In the town office, hall, arena and fire hall: press the test button on emergency lights, check exit signs and extinguisher gauges, pins and tags.", "Facility staff", "None", 10.0, "Batteries, tags", "Ladder"),
        _tw("Prevention A", "Fleet check: trucks, grader, mower, plow", 30, 2.0, "Check fluids, tires, lights, brakes, belts, blades and cutting edges. Grease fittings. Record meter readings.", "Mechanic or public works", "Parking brake and wheel chocks", 60.0, "Grease, oil, filters", "Grease gun, hand tools"),
        _tw("Prevention A", "Playground and skate park inspection (in season)", 30, 1.0, "Check for loose bolts, broken parts, sharp edges, cracked surfacing and hazards on swings, slides and climbing equipment. Remove or fence off anything unsafe. Keep a dated log. Playground guidance in Canada follows the CSA standard for playgrounds.", "Public works", "Close any equipment that is unsafe", 20.0, "Hardware", "Checklist"),
        _tw("Prevention A", "Bulk water station, meters and curb stops check", 30, 1.0, "Check the bulk water fill station, meters and any known leaking curb stops. Compare water pumped to water billed and look for losses.", "Utility operator", "None", 0.0, "None", "Meter log"),
        # ----- Prevention B: quarterly or twice a year -----
        _tw("Prevention B", "Quarterly valve exercising (one quarter of the valves each time)", 90, 4.0, "Operate one quarter of the main valves fully open and closed, count turns and log any that are stuck or damaged. Over the year every valve gets exercised (general practice).", "Public works", "Traffic control; watch for water hammer", 30.0, "Grease", "Valve key, exerciser"),
        _tw("Prevention B", "Quarterly trihalomethane (THM) sampling reminder (if your permit requires it)", 90, 1.0, "Under WSA 545, surface, blended and some groundwater systems have THM sampling rules; for surface systems serving under 5,000 people it is quarterly. Check your Permit to Operate and the table in WSA 545 for your system [1].", "Qualified waterworks operator", "None", 60.0, "Sample bottles", "Cooler"),
        _tw("Prevention B", "Quarterly safety meeting and toolbox talk", 90, 1.0, "Hold a short safety meeting with the crew: confined spaces, chlorine, trenching, traffic control, lifting. Write down who attended.", "Safety lead or CAO", "None", 0.0, "None", "Sign-in sheet"),
        _tw("Prevention B", "Well pump, booster pump and motor check", 180, 2.0, "Check amps, vibration, noise, seals and leaks. Compare with last readings. Check pump start/stop controls.", "Qualified waterworks operator", "LOTO", 40.0, "Grease, seals", "Amp meter"),
        _tw("Prevention B", "Lagoon spring and fall inspection and release planning", 180, 3.0, "After thaw and before freeze-up, inspect the lagoon, record depth and plan any release. Release, sampling and reporting rules are in your Permit to Operate and the Saskatchewan Environmental Code. Notify the WSA when and how the permit says to [2].", "Utility operator", "Never release without checking the permit", 0.0, "None", "Sample bottles, depth gauge"),
        _tw("Prevention B", "Electrical panel visual and thermal check", 180, 2.0, "Look for heat marks, loose lugs, noise or corrosion in panels at the wells, lift station, hall and arena. A thermal camera helps. A licensed electrician does the work inside panels.", "Licensed electrician", "Electrical hazard, qualified person only", 80.0, "None", "Thermal camera"),
        _tw("Prevention B", "Culvert, road and ditch inspection (spring and fall)", 180, 4.0, "Check culverts, approaches, ditches and bridges for blockage, washouts and damage. Note priorities for the grader and the budget. Especially important for RMs.", "Public works", "Traffic; ice and high water", 0.0, "None", "Camera, shovel"),
        _tw("Prevention B", "Fire hall: truck pump check and hose test", 180, 4.0, "Run the pump, check pressure, hoses, nozzles and tank. Check SCBA and tools. Log results for the fire chief.", "Fire chief", "Fire hall safety", 100.0, "Fuel, hose", "Pump log"),
        # ----- Prevention C: yearly or longer -----
        _tw("Prevention C", "Yearly hydrant flushing and flow test", 365, 16.0, "Flush each hydrant, check flow and pressure, look for broken parts, leaks and drains. Notify residents before flushing. Flush at a time that avoids freezing and dirty water complaints (general practice).", "Public works", "Traffic control; hot or cold weather", 150.0, "Gaskets, grease", "Hydrant wrench, pitot gauge"),
        _tw("Prevention C", "Yearly reservoir and clearwell inspection", 365, 6.0, "Inspect the reservoir roof, hatches, vents and screens, overflow, ladder and coating from outside. Plan cleaning and a full inspection every few years with trained, equipped people.", "Qualified waterworks operator", "Confined space: do not enter without proper training and rescue", 100.0, "None", "Flashlight, camera"),
        _tw("Prevention C", "Yearly backflow preventer testing", 365, 4.0, "Test backflow preventers on the arena, hall, plant, bulk fill and any commercial connections. Keep the test records. Check the local requirements for who may test.", "Qualified backflow tester", "None", 200.0, "Seals, kits", "Test kit"),
        _tw("Prevention C", "Yearly generator service and full-load test", 365, 6.0, "Change oil and filters, check coolant and batteries, and run a full-load test (load bank if needed). Check the transfer switch. Test fuel quality.", "Electrician", "LOTO; carbon monoxide", 400.0, "Oil, filters, fuel", "Load bank"),
        _tw("Prevention C", "Yearly electrical thermal scan and breaker check", 365, 6.0, "Thermal scan of main panels, motor controls and transformers. Tighten connections and replace parts that are overheating.", "Licensed electrician", "Electrical hazard, qualified person only", 300.0, "None", "Thermal camera"),
        _tw("Prevention C", "Fall freeze-up prep: hydrants, lines, heat tape and plow gear", 365, 8.0, "Before winter: check heat tape and insulation on exposed pipes, drain hydrants as needed, service the plow, sander and snowblower, stock salt and sand.", "Public works", "Cold-weather and ladder safety", 400.0, "Salt, sand, blades", "Hand tools"),
        _tw("Prevention C", "Yearly fleet service: grader, trucks, mower", 365, 16.0, "Full service: oil, filters, hydraulic fluid, cutting edges and brakes. Check steering and tires. Replace parts before they fail.", "Mechanic", "LOTO and blocking", 1500.0, "Oil, filters, edges", "Shop tools"),
        _tw("Prevention C", "Arena refrigeration, boiler and pressure vessel inspection check", 365, 4.0, "Check that arena refrigeration, boilers and pressure vessels are inspected as the Technical Safety Authority of Saskatchewan (TSASK) requires. Confirm the dates and keep the paperwork. Check with TSASK for what applies to you.", "Facility manager", "Ammonia and pressure hazards: qualified people only", 500.0, "None", "Inspection paperwork"),
        _tw("Prevention C", "Yearly extinguisher service, SCBA and fire pump test", 365, 6.0, "Service extinguishers and SCBA, and run the annual pump test on fire trucks. Keep dated records.", "Fire chief and service company", "None", 400.0, "Tags, agent", "Service kit"),
        _tw("Prevention C", "Yearly detailed playground inspection", 365, 3.0, "Do a detailed check, including surfacing depth, footings and fasteners. Repair or remove anything unsafe. File the report.", "Public works", "Close unsafe equipment", 100.0, "Surfacing, hardware", "Checklist"),
        _tw("Prevention C", "Update the asset list, condition notes and replacement years", 365, 4.0, "Update your list of pipes, pumps, vehicles and buildings with condition and expected replacement year. It feeds the budget and any grant application.", "CAO", "None", 0.0, "None", "This program"),
        # ----- Compliance: reminders for rules and reports -----
        _tw("Compliance", "Audited financial statements to Government Relations (due July 1)", 365, 6.0, "Municipalities other than cities must submit audited financial statements and the auditor's report to the Ministry of Government Relations by July 1 (cities by September 1). Appoint the auditor early. Check saskatchewan.ca for any change [4].", "CAO", "None", 0.0, "None", "Audit package"),
        _tw("Compliance", "Annual Notification to Consumers on drinking water", 365, 2.0, "The WSA provides guidelines and templates (EPB 536) for the annual notice to water users. Prepare it and send it as your permit and the guideline say [3].", "CAO and operator", "None", 50.0, "Printing", "Template"),
        _tw("Compliance", "Review the sampling plan against your Permit to Operate and WSA 545", 365, 2.0, "WSA 545 sets minimum frequencies by population and source: for example, bacteriological sampling is weekly for groundwater systems serving 501 to 2,000 people, and free chlorine should be read daily at the entry to the distribution system. Your permit can change these. Confirm the plan each year [1].", "Qualified waterworks operator", "None", 0.0, "None", "WSA 545"),
        _tw("Compliance", "General chemical and health/toxicity sampling reminder", 365, 1.0, "For groundwater systems serving up to 5,000 people, WSA 545 lists general chemical and health/toxicity sampling as every 2 years (every year for surface sources serving 501 to 5,000). Check the table and your permit, then schedule the lab [1].", "Qualified waterworks operator", "None", 400.0, "Sample bottles", "Cooler"),
        _tw("Compliance", "Lead and copper sampling reminder", 365, 2.0, "WSA 545 asks for routine lead and copper sampling at least once a year, starting with homes with lead service lines, plus schools and daycares. Reduced sampling is possible under conditions in the document. Check it and your permit [1].", "Qualified waterworks operator", "None", 200.0, "Sample bottles", "Sampling kit"),
        _tw("Compliance", "Check operator qualifications and renewals", 365, 1.0, "Confirm every operator's certification level, expiry and any training needed, using the Saskatchewan Operator Certification Board. Keep copies on file [2][3].", "CAO", "None", 0.0, "None", "Operator files"),
        _tw("Compliance", "Check Permit to Operate conditions, renewals and amendments", 365, 2.0, "Read your waterworks and sewage works Permits to Operate (WSA 523 and WSA 524 are the forms for changes). Note conditions, deadlines and changes you plan, such as new wells or a lagoon upgrade [2][3].", "CAO and operator", "None", 0.0, "None", "Permits"),
        _tw("Compliance", "Review and update the emergency response plan and contact list", 365, 3.0, "Review the waterworks emergency response plan (EPB 540 and the template EPB 541B), the boil water advisory steps and the WSA emergency and upset contact list (EPB 365). Practise the phone tree [3].", "CAO and operator", "None", 0.0, "None", "ERP binder"),
        _tw("Compliance", "Lagoon sampling, release records and annual wastewater reporting", 365, 4.0, "Collect lagoon sampling and release records and report as your Permit to Operate says. Check the Saskatchewan Environmental Code and WSA compliance monitoring guidance (EPB 338). Keep upset reports (EPB 267) [2].", "Utility operator and CAO", "None", 300.0, "Sample bottles", "Lab"),
        _tw("Compliance", "Groundwater monitoring wells at the lagoon: sampling reminder (if required)", 365, 3.0, "If your permit requires monitoring wells at the sewage works, sample them as WSA 531 describes and file the results [2].", "Utility operator", "None", 250.0, "Sample bottles", "Sampling pump"),
        _tw("Compliance", "Check what is due: sampling, reports, inspections and permits", 365, 2.0, "Once a year, list every report, sample, inspection and permit renewal due in the next 12 months and put the dates on the calendar. Rules change, so confirm with the WSA at 1-866-727-5420 and with Government Relations. This is a reminder, not legal advice [1][3][4].", "CAO", "None", 0.0, "None", "Calendar"),
    ],
)
SAMPLE_GROUPS[_TWN_NAME]["checklist"] = list(SAMPLE_GROUPS[_TWN_NAME]["checklist"])

FULL_CATEGORIES_LIST = []
DEFAULT_CATEGORY_LABELS = {}
CATEGORY_CHECKLIST_SEED_TASKS = {}
CATEGORY_TASK_TEMPLATES = {}
SAMPLE_ATTRIBUTES = {}
SAMPLE_PART_LABELS = {}
SAMPLE_CAT_PREFIXES = {}
SAMPLE_MODEL_PATTERNS = {}
SAMPLE_UNIT_COUNT = {}
SAMPLE_UNIT_NAMES = {}

MIN_SCHEDULE_DAYS = 8     # a task that repeats more often than this belongs on the Daily/Weekly Checklists, not the Scheduled Maintenance list
_WEEKLY_DAY_ROTATION = ["Monday", "Wednesday", "Friday", "Tuesday", "Thursday"]

def short_interval_text(task, days):
    return (f"'{task}' repeats every {days} day(s). Anything that repeats more often than every {MIN_SCHEDULE_DAYS} days belongs on the "
            f"Daily/Weekly Checklists (Checklists screen), not in Scheduled Maintenance. Add it there and remove it here, "
            f"or set the interval to {MIN_SCHEDULE_DAYS} days or more.")

def _move_short_tasks_to_checklist(g):
    """Sample data rule: tasks repeating in fewer than MIN_SCHEDULE_DAYS days become checklist items instead
    (daily ones stay Daily; 7-day ones become weekly items on a weekday)."""
    keep, moved = [], []
    for t in g["tasks"]:
        days = t[2] if len(t) == 11 else t[4]
        try: d = int(float(str(days).replace(",", "")))
        except (TypeError, ValueError): d = 0
        if 0 < d < MIN_SCHEDULE_DAYS: moved.append((str(t[1]), d))
        else: keep.append(t)
    if not moved: return g
    existing = {str(lab).split("|")[0].strip().lower() for pair in g["checklist"] for lab in pair}
    labels, w = [], 0
    for nm, d in moved:
        if nm.lower() in existing: continue
        if d >= 7: labels.append(f"{nm}|{_WEEKLY_DAY_ROTATION[w % len(_WEEKLY_DAY_ROTATION)]}"); w += 1
        else: labels.append(nm)
    g = dict(g)
    g["tasks"] = keep
    g["checklist"] = list(g["checklist"]) + [tuple(labels[i:i + 2]) for i in range(0, len(labels), 2)]
    return g

def _register_group(name, g):
    """Add one group (built-in or private) to the lookup tables the rest of the app uses."""
    g = _move_short_tasks_to_checklist(g)
    today = datetime.now().strftime("%Y-%m-%d")
    FULL_CATEGORIES_LIST.append(name)
    DEFAULT_CATEGORY_LABELS[name] = tuple(g["labels"][:5]) + ("Grease Nipples",)
    CATEGORY_CHECKLIST_SEED_TASKS[name] = list(g["checklist"])
    SAMPLE_ATTRIBUTES[name] = list(g["attrs"])
    SAMPLE_PART_LABELS[name] = tuple(g["parts"])
    SAMPLE_CAT_PREFIXES[name] = g["prefix"]
    SAMPLE_MODEL_PATTERNS[name] = g["model"]
    SAMPLE_UNIT_COUNT[name] = int(g.get("units", 5))
    SAMPLE_UNIT_NAMES[name] = dict(g.get("unit_names", {}))
    rows = []
    for t in g["tasks"]:
        if len(t) == 11:     # compact form -> (tab, name, date, meter_at_last, days, meter_between, tools, hours, description, who, safety, cost, consumables)
            tab, nm, days, meter, hrs, desc, who, safety, cost, cons, tools = t
            rows.append((tab, nm, today, 0, days, meter, tools, hrs, desc, who, safety, cost, cons))
        else:
            rows.append(tuple(t))
    CATEGORY_TASK_TEMPLATES[name] = rows


# ---- Split the child plan into two age bands: 0-5 (intensive, parent-led) and 6-12 (growing independence) ----
# Built from the finished "Longevity 0-12 Kids" group (all add-on layers already applied), so nothing is lost. 00-05 and 06-12 are
# zero-padded so the groups sort in age order (A-Z) next to 13-17, 18-39 ...
_K_EARLY = "Longevity 00-05 Early Years"
_K_KIDS = "Longevity 06-12 Kids"
def _split_kids_group():
    k = SAMPLE_GROUPS.pop("Longevity 0-12 Kids")
    rows, tasks = list(k["checklist"]), list(k["tasks"])
    def pick(idx): return [rows[i] for i in idx]
    # ---- 0-5: every day, parent-led ----
    early_rows = [
        ("SAFETY: car seat fitted right every trip, harness snug; seat belt on", rows[0][1]),
        ("SLEEP: babies 0-3 mo 14-17 h, 4-11 mo 12-16 h, 1-2 yrs 11-14 h, 3-4 yrs 10-13 h [1]", rows[1][1]),
        ("MOVE: ages 1-4, 3 hours of any play across the day, some of it energetic; ages 5, 60 minutes of hard-enough-to-puff play [1][2]", rows[2][1]),
        rows[3],
        ("SCREENS: none under 2; no more than 1 hour at ages 2-4; none at meals or in bedrooms at night [1][5]", rows[4][1]),
        rows[5],
        rows[6],
        rows[7], rows[8], rows[9], rows[10],
        ("SKILLS: one small job (put toys in the bin, help set the table), from about age 2-3", "ROUTINE: same meal, nap, bath and bedtime pattern each day; tell them what comes next"),
        ("WATCH and LOG: if the public health nurse asked, note feeds, wet diapers and sleep; call 811 if you are worried", "DEVELOPMENT: notice first smiles, words, steps and play; write down any worry about speech, movement or behaviour to ask the nurse"),
        ("Check crib, high chair, car seat straps and stair gates are safe and tight|Sunday", "Crawl the floor: small objects, cords, button batteries and magnets out of reach|Sunday"),
    ] + pick([12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 26, 28, 29])
    early_tasks = [tasks[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 17)] + [t for t in tasks[18:] if t[1] not in (
        "Monthly backpack, posture and sitting check", "Concussion plan: know the signs and what to do", "Monthly 'sharpen the saw' family check")]
    early_tasks.append(("Prevention A", "Monthly milestone and worry check", 30, 0, 0.3,
        "Look at what your child can do now (smiling, sitting, walking, words, play) and write down anything that worries you, in any area. Bring the list to the next nurse or doctor visit and ask about developmental screening. Not medical advice. [Moderate]",
        "Parent", "None", 0.0, "None", "Notebook"))
    # ---- 6-12: fewer daily prompts, more independence ----
    kid_rows = [
        ("SAFETY: booster seat until the seat belt fits right (check the seat maker's limits); seat belt on every trip", "SAFETY: know your name, address, a parent's phone number and who to ask for help"),
        ("SLEEP: 9-11 hours at ages 5-12; same bedtime and wake time [2]", rows[1][1]),
        ("MOVE (sweat): 60 minutes a day of hard-enough-to-puff play or sport [2]", rows[2][1]),
        ("SCREENS: no more than 2 hours of fun screen time a day; none at meals or in bedrooms at night [2][5]", rows[4][1]),
        ("FOOD: eat together at the table, no screens; vegetables or fruit at each meal; water and milk; limit juice, sugary drinks, chips and sweets [9]", "FOOD: let them help choose and make a meal or snack; water in the school bottle [9]"),
        ("TEETH: brush twice a day for 2 minutes with fluoride toothpaste (pea size); an adult helps until about age 8 [4]", rows[6][1]),
        rows[7], rows[8], rows[9],
        ("SAFETY: helmet on bike, scooter, skates and sleds; an adult watching near water until they swim well", "SAFETY: medicines and cleaners locked or out of reach of younger children; hot water 49 C or less"),
        rows[11],
    ] + pick([12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29])
    kid_tasks = [tasks[i] for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 15, 16, 17)] + list(tasks[18:])
    kid_tasks.append(("Compliance", "Check the vaccine record and catch up", 365, 0, 0.5,
        "At the yearly checkup, ask the nurse to compare the record with the Saskatchewan schedule [3] and book anything missed. [Strong]",
        "Parent / Public health nurse", "None", 0.0, "None", "Vaccine record"))
    early = dict(k, prefix="L00", model="Longevity Plan 0-5 {i}", unit_names={1: "My Child (0-5)"}, checklist=early_rows, tasks=early_tasks)
    older = dict(k, prefix="L06", model="Longevity Plan 6-12 {i}", unit_names={1: "My Child (6-12)"}, checklist=kid_rows, tasks=kid_tasks)
    SAMPLE_GROUPS[_K_EARLY] = early
    SAMPLE_GROUPS[_K_KIDS] = older
_split_kids_group()

# ==========================================================================================
# PERSONAL DEVELOPMENT groups (category "Longevity and Awareness"): Habits, Goals, Relationships, Skills.
# Each unit is one habit, goal, person or skill. Tasks are reminders for self-reflection and practice, not medical advice.
# ==========================================================================================
_pd_t = lambda tab, nm, days, hrs, desc, who="Me", safety="None", cost=0.0, cons="None", tools="None": (tab, nm, days, 0, hrs, desc, who, safety, cost, cons, tools)

SAMPLE_GROUPS["Habits"] = dict(
    prefix="HAB",
    model="Habit {i}",
    units=3,
    unit_names={1: "Habit: daily walk", 2: "Habit: nightly review", 3: "Habit: morning pause"},
    labels=("Habit", "Tiny Version (week one)", "Full Version", "Start Date", "My Reward"),
    parts=("Cue (after I...):", "Tiny Version:", "Full Version:", "Reward:", "Tracking:", "Support:"),
    attrs=[("Habit", "Daily walk (change to your own)", "One unit per habit. Two at a time is plenty"),
           ("Plan", "After I finish breakfast, I will put on my shoes and step outside", "A habit tied to something you already do is easier to keep [3]"),
           ("Source [1]", "Lally P, van Jaarsveld CHM, Potts HWW, Wardle J. How are habits formed: modelling habit formation in the real world. European Journal of Social Psychology 2010; 40:998-1009. Habits took a median of 66 days to become automatic, with a wide range (18 to 254 days), and missing one day did not materially hurt the process (journal article, summary)", "search: Lally 2010 habit formation 66 days"),
           ("Source [2]", "B.F. Skinner's work on reinforcement: rewarding every time to start a behavior, then only some of the time, keeps it going (general knowledge, paraphrased; see the Philosophy page)", "n/a"),
           ("Source [3]", "BJ Fogg, Tiny Habits (2019): make the habit tiny and anchor it to an existing routine. Peter Gollwitzer's research on if-then 'implementation intentions' (1999 and later reviews) found that specific plans improve follow-through. Paraphrased in our own words (books and journal articles, summary)", "library or bookstore"),
           ("Source [4]", "Stephen R. Covey, The 7 Habits of Highly Effective People, paraphrased in our own words. Not medical advice", "library or bookstore")],
    checklist=[
        ("Do today's tiny version of each habit and tick it off [3]", "Tie each habit to something you already do: 'After I X, I will Y' [3]"),
        ("Feel like skipping? Do the two-minute version instead [3]", "Missed a day? Just do today's. One miss does not undo a habit [1]"),
        ("Weekly review: which habit is easiest, which is hardest? Make the hard one smaller|Sunday", "Kept a habit all week? Roll the dice for a reward (Philosophy page) [2]|Sunday"),
    ],
    tasks=[
        _pd_t("Prevention A", "Weekly habit review", 7, 0.3, "Look back over the week. Which habits did you do, which did you skip, and why? Make the hardest one smaller, or move it to a better time. Reward yourself for what you kept [2][3]. [Moderate]"),
        _pd_t("Prevention A", "Monthly review with a thinking partner (optional)", 30, 0.5, "Once a month, sit down with a thinking partner (a friend, a mentor, a counsellor or an AI) and review the month. Bring your habit counts, your strengths chart and your goals, and use the Monthly review prompt on the Philosophy page (Talk it over). Ask: what patterns do you see, what should I keep, shrink or drop, and what am I not seeing? Ask it to push back and disagree. Do not paste Private journal text into any online service. Take the advice as input, not a verdict, and finish with one real action, ideally involving a real person. Optional: skip a month if you like. Finish with a reward from your six joys. [Emerging]"),
        _pd_t("Prevention A", "Monthly: keep, shrink, swap or retire a habit", 30, 0.4, "Habits take about two months on average to settle, with a wide range [1]. After a month, ask whether this habit is still worth it. Keep it, make it smaller, swap it, or retire it. Two habits at a time is plenty. [Moderate]"),
        _pd_t("Prevention B", "Two-month check: is it automatic yet?", 60, 0.3, "On about day 60 ask whether you do it without deciding to. If yes, it can run on its own and you can start another. If not, keep going; the range is wide, and one slip does not erase progress [1]. [Moderate]"),
        _pd_t("Prevention C", "Yearly habit clean-out", 365, 1.0, "List the habits you have now. Which ones make your life better? Keep those, drop the rest, and choose one new one for the year, thinking about the person you want to be [4]. [Moderate]"),
    ],
)

SAMPLE_GROUPS["Goals"] = dict(
    prefix="GOL",
    model="Goal {i}",
    units=2,
    unit_names={1: "Goal: finish the project I care about", 2: "Goal: a health goal for this year"},
    labels=("Goal", "Why It Matters", "Target Date", "Next Step", "Who Helps"),
    parts=("Why:", "Plan:", "First Next Step:", "Obstacles:", "Support:", "Review:"),
    attrs=[("Goal", "One clear goal (change to your own)", "One unit per goal. Specific goals work better than vague ones [1]"),
           ("Obstacle plan", "If it is raining, then I will do the indoor version", "If-then plans help people follow through [2]"),
           ("Source [1]", "Locke EA, Latham GP. Building a practically useful theory of goal setting and task motivation. American Psychologist 2002; 57:705-717. Specific, challenging goals with feedback tend to lead to better performance than vague 'do your best' goals (journal article, summary)", "search: Locke Latham goal setting theory 2002"),
           ("Source [2]", "Peter Gollwitzer, implementation intentions (if-then plans), and Gabriele Oettingen, 'mental contrasting' (WOOP: wish, outcome, obstacle, plan), Rethinking Positive Thinking (2014). Picturing the obstacle along with the goal tends to help more than positive fantasy alone. Paraphrased (journal articles and book, summary)", "library or bookstore"),
           ("Source [3]", "Stephen R. Covey, The 7 Habits: begin with the end in mind; put first things first. Paraphrased in our own words (book). Not financial, legal or medical advice", "library or bookstore"),
           ("Source [4]", "Edward de Bono, Lateral Thinking (1970) and Six Thinking Hats (1985): deliberate sideways moves (random entry, provocation, challenging assumptions) to find new ideas. Widely taught; controlled research is thin, so treat it as a toolkit (books, summary)", "library or bookstore")],
    checklist=[
        ("Write the one next step for each goal and do it first thing today [3]", "Name the biggest obstacle and make an if-then plan: 'If X happens, I will Y' [2]"),
        ("Weekly: is each goal still moving? What is the next step this week?|Sunday", "Weekly: pick the three most important things, schedule them first, say no to the rest [3]|Sunday"),
    ],
    tasks=[
        _pd_t("Prevention A", "Weekly goal review", 7, 0.4, "For each goal: what did I do this week, what is the next step, what could get in the way (WOOP: wish, outcome, obstacle, plan) [2]? Put the next step in your calendar. [Moderate]"),
        _pd_t("Prevention A", "Monthly review with a thinking partner (optional)", 30, 0.5, "Once a month, sit down with a thinking partner (a friend, a mentor, a counsellor or an AI) and review the month. Bring your habit counts, your strengths chart and your goals, and use the Monthly review prompt on the Philosophy page (Talk it over). Ask: what patterns do you see, what should I keep, shrink or drop, and what am I not seeing? Ask it to push back and disagree. Do not paste Private journal text into any online service. Take the advice as input, not a verdict, and finish with one real action, ideally involving a real person. Optional: skip a month if you like. Finish with a reward from your six joys. [Emerging]"),
        _pd_t("Prevention A", "Monthly progress check", 30, 0.5, "Compare progress with the target date. Break big goals into steps small enough to finish in a week. Adjust the plan, not just the effort [1]. [Moderate]"),
        _pd_t("Prevention A", "Monthly: think sideways about a stuck goal", 30, 0.4, "Pick the goal that is stuck. Use the Think sideways box on the Philosophy page: a random word, a provocation, or the six thinking hats. List ten alternatives before choosing one, then sleep on it. A toolkit, not a guarantee [4]. [Traditional]"),
        _pd_t("Prevention B", "Quarterly: is this still my goal?", 91, 0.8, "Ask whether the goal still matters to you. Drop it, change it, or double down. Letting go of a goal that no longer fits is a healthy choice, not a failure. [Moderate]"),
        _pd_t("Prevention C", "Yearly: write next year's goals", 365, 1.5, "Begin with the end in mind [3]: who do you want to be in a year? Choose a few specific goals, one in each of body, mind, relationships and meaning. Write a first step for each. [Moderate]"),
    ],
)

SAMPLE_GROUPS["Relationships"] = dict(
    prefix="REL",
    model="Relationship {i}",
    units=3,
    unit_names={1: "Person: my closest person", 2: "Person: a parent or elder", 3: "Person: a close friend"},
    labels=("Person", "How We Connect", "Important Dates", "Last Real Conversation", "One Thing They Love"),
    parts=("Time Together:", "Listening:", "Appreciation:", "Repair:", "Shared Plans:", "Boundaries:"),
    attrs=[("Person", "A person who matters to you (use a first name or a role; this stays on your own computer)", "One unit per person. Sample data uses roles, not real people"),
           ("Safety", "If a relationship makes you feel unsafe, contact a local support service, a doctor or a counsellor. In an emergency call 911", "Not therapy, legal or medical advice"),
           ("Source [1]", "Holt-Lunstad J, Smith TB, Layton JB. Social relationships and mortality risk: a meta-analysis. PLoS Medicine 2010; 7(7):e1000316. Across 148 studies (more than 300,000 people), stronger social relationships were linked with about a 50% greater likelihood of survival. An association, not proof of cause (journal article, summary)", "search: Holt-Lunstad 2010 social relationships mortality"),
           ("Source [2]", "Waldinger R, Schulz M. The Good Life (2023), on the Harvard Study of Adult Development: the quality of close relationships was among the strongest predictors of health and happiness in later life. Paraphrased (book)", "library or bookstore"),
           ("Source [3]", "Stephen R. Covey, The 7 Habits: think win-win; seek first to understand, then to be understood. Paraphrased in our own words (book)", "library or bookstore")],
    checklist=[
        ("Listen to one person today until they feel understood, before you give your view [3]", "Tell one person one thing you appreciate about them"),
        ("Real conversation with someone close this week: in person or by phone, not just a text|Wednesday", "Plan something to do together this week, even something small|Saturday"),
        ("Weekly: who have I not spoken with lately? Reach out|Sunday", "Any birthday or anniversary coming up? Plan early|Sunday"),
    ],
    tasks=[
        _pd_t("Prevention A", "Weekly real conversation with someone close", 7, 0.5, "Call or meet, and listen more than you talk. Close relationships are linked with better health and longer life, though that is an association, not proof of cause [1][2]. [Moderate]"),
        _pd_t("Prevention A", "Weekly appreciation", 7, 0.1, "Tell someone one specific thing you value about them. Specific beats general. [Moderate]"),
        _pd_t("Prevention A", "Monthly review with a thinking partner (optional)", 30, 0.5, "Once a month, sit down with a thinking partner (a friend, a mentor, a counsellor or an AI) and review the month. Bring your habit counts, your strengths chart and your goals, and use the Monthly review prompt on the Philosophy page (Talk it over). Ask: what patterns do you see, what should I keep, shrink or drop, and what am I not seeing? Ask it to push back and disagree. Do not paste Private journal text into any online service. Take the advice as input, not a verdict, and finish with one real action, ideally involving a real person. Optional: skip a month if you like. Finish with a reward from your six joys. [Emerging]"),
        _pd_t("Prevention A", "Monthly: who have I neglected, and is there something to repair?", 30, 0.5, "Think of people you have not been in touch with. Is there an apology, a thank-you or an overdue call? Repair early, while it is small [3]. [Moderate]"),
        _pd_t("Prevention B", "Quarterly: plan time together", 91, 0.5, "Book a meal, trip, walk, game night or visit with someone who matters. Put it in the calendar now, or it will not happen. [Moderate]"),
        _pd_t("Prevention C", "Yearly: dates and people", 365, 0.8, "Update birthdays, anniversaries and anyone new in your life. Decide who you want to spend more time with this year, and who may need a boundary. [Moderate]", "Me", "If a relationship feels unsafe, contact a support service"),
    ],
)

SAMPLE_GROUPS["Skills"] = dict(
    prefix="SKL",
    model="Skill {i}",
    units=2,
    unit_names={1: "Skill: a craft (welding, music, writing)", 2: "Skill: a language or a subject"},
    labels=("Skill", "Current Level", "Practice Goal", "Teacher or Resource", "Next Milestone"),
    parts=("Practice:", "Feedback:", "Equipment & Safety:", "Learning Resources:", "Milestones:", "Rest & Recovery:"),
    attrs=[("Skill", "A skill you want to build (change to your own)", "One unit per skill"),
           ("Practice plan", "Three sessions a week of 20 minutes, aimed at one small weak spot", "Short, focused practice beats long, vague sessions [1]"),
           ("Source [1]", "Ericsson KA, Krampe RT, Tesch-Roemer C. The role of deliberate practice in the acquisition of expert performance. Psychological Review 1993; 100:363-406: focused practice aimed at weak spots, with feedback, is how skills grow. Later work (Macnamara et al., Psychological Science 2014) found practice explains much, but only part, of the differences between people. The '10,000 hours' rule is a popular simplification (journal articles, summary)", "search: Ericsson deliberate practice 1993"),
           ("Source [2]", "Mihaly Csikszentmihalyi, Flow (1990): enjoyment is highest when the challenge slightly stretches your skill. Rollo May, The Courage to Create: absorbed engagement with the work itself (encounter). Paraphrased (books)", "library or bookstore"),
           ("Source [3]", "Safety gear and tool care follow each tool's manual and local rules. Not professional advice", "n/a"),
           ("Source [4]", "Howard Gardner, Frames of Mind (1983): several kinds of intelligence (linguistic, logical-mathematical, spatial, musical, bodily-kinesthetic, interpersonal, intrapersonal; later naturalist). Used here only as a lens for noticing strengths, not a test: many psychologists doubt the intelligences are separate, measurable abilities (book, summary)", "library or bookstore")],
    checklist=[
        ("Practice 10 to 20 minutes today, aimed at one small weak spot [1]", "Write down one thing you learned today"),
        ("Weekly: three practice sessions done? Ask for feedback from someone better|Sunday", "Weekly: is the challenge slightly too hard? Adjust so it stretches you without frustrating you [2]|Sunday"),
    ],
    tasks=[
        _pd_t("Prevention A", "Weekly practice sessions (three, about 20 minutes)", 7, 1.0, "Aim each session at one weak spot, slow it down, and get feedback if you can. Stop while you still want more. [Moderate]"),
        _pd_t("Prevention A", "Monthly review with a thinking partner (optional)", 30, 0.5, "Once a month, sit down with a thinking partner (a friend, a mentor, a counsellor or an AI) and review the month. Bring your habit counts, your strengths chart and your goals, and use the Monthly review prompt on the Philosophy page (Talk it over). Ask: what patterns do you see, what should I keep, shrink or drop, and what am I not seeing? Ask it to push back and disagree. Do not paste Private journal text into any online service. Take the advice as input, not a verdict, and finish with one real action, ideally involving a real person. Optional: skip a month if you like. Finish with a reward from your six joys. [Emerging]"),
        _pd_t("Prevention A", "Monthly skill review", 30, 0.5, "What improved? What is the next milestone? Is the challenge slightly beyond your skill (that is where learning and enjoyment meet) [2]? Adjust the plan. [Moderate]"),
        _pd_t("Prevention A", "Monthly strengths balance check (Gardner's lens)", 30, 0.3, "Which kinds of smarts did you use this month: words, logic, space and pictures, music, hands and movement, people, self-knowledge, nature? Notice the ones you neglected and try one small thing to use them. Use the Strengths lens on the Philosophy page. A lens for noticing, not a test [4]. [Traditional]"),
        _pd_t("Prevention B", "Quarterly: get feedback from someone better", 91, 1.0, "Show your work to a teacher, mentor or someone more skilled and ask what to fix first. [Moderate]"),
        _pd_t("Prevention B", "Quarterly: check tools and safety gear", 91, 0.8, "Check tools, guards and personal protective equipment for your craft (for welding: helmet lens, gloves, ventilation, fire safety). Follow each manual [3]. [Strong]", "Me", "Use the right protective equipment; follow the tool manual", 0.0, "None", "Tools and protective gear"),
        _pd_t("Prevention C", "Yearly: pick the skill for the year", 365, 1.0, "Choose one skill that fits who you want to become. Set a milestone you can show someone by year end. [Moderate]"),
    ],
)

for _gname, _g in SAMPLE_GROUPS.items(): _register_group(_gname, _g)

# Optional private groups: a file called private_groups.py next to app.py adds extra sample groups (the vendor's own copy only).
try:
    import private_groups as _private_groups
    for _gname, _g in _private_groups.PRIVATE_GROUPS.items():
        if _gname not in SAMPLE_GROUPS: _register_group(_gname, _g)
except ImportError:
    pass
FULL_CATEGORIES_LIST.sort(key=str.lower)   # asset groups in A-Z order

def get_category_attributes(category, unit_index, asset_id):
    items = SAMPLE_ATTRIBUTES.get(category, [("Operational Scale", "Industrial Standard", "Standard group metric"), ("Primary Operating Base", "Main Site", "Active operational deployment"), ("Commissioned Date", "2021-06-01", "Commissioning record"), ("Design Lifespan", "25 Years", "Full lifecycle maintenance protocol")])
    return [(asset_id, item[0], item[1], item[2]) for item in items]

def get_default_labels_for_category(category):
  return DEFAULT_CATEGORY_LABELS.get(category, ("Attribute 1", "Attribute 2", "Attribute 3", "Attribute 4", "Fuel", "Grease Nipples"))

def get_category_part_labels(category):
  return SAMPLE_PART_LABELS.get(category, ("Primary Mover:", "Transmission:", "Hydraulics:", "Frame / Structure:", "Controls:", "Safety Systems:"))

def get_default_tasks_for_category(category, asset_id):
  base_tasks = CATEGORY_TASK_TEMPLATES.get(category, [("Prevention A", "Primary Inspection", "2026-01-15", 10000, 90, 5000, "Tools", 1.0, "Routine", "Tech", "LOTO", 50.0, "None")])
  return [(asset_id, t[0] if len(t)>0 else "Prevention A", t[1] if len(t)>1 else "Inspection", t[2] if len(t)>2 else "2026-01-15", int(t[3]) if len(t)>3 and str(t[3]).isdigit() else 10000, int(t[4]) if len(t)>4 and str(t[4]).isdigit() else 90, int(t[5]) if len(t)>5 and str(t[5]).isdigit() else 5000, t[6] if len(t)>6 else "Tools", float(t[7]) if len(t)>7 else 1.0, t[8] if len(t)>8 else "Routine", t[9] if len(t)>9 else "Tech", t[10] if len(t)>10 else "LOTO", float(t[11]) if len(t)>11 else 0.0, t[12] if len(t)>12 else "None") for t in base_tasks]

DAY_CHOICES = ["Daily", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def normalize_day(v):
  """'' / 'daily' / None -> 'Daily'; 'fri' or 'Friday' -> 'Friday'; anything else -> None (not understood)."""
  t = re.sub(r"[^a-z]", "", str(v if v is not None else "").lower())
  if t in ("", "daily", "everyday", "nan", "none", "na"): return "Daily"
  for d in DAY_CHOICES[1:]:
    if len(t) >= 3 and d.lower().startswith(t): return d
  return None

def today_weekday_name(when=None):
  return DAY_CHOICES[1 + (when or datetime.now()).weekday()]

def get_default_checklist_df(category):
  seed_tasks = CATEGORY_CHECKLIST_SEED_TASKS.get(category)
  if not seed_tasks:
      for key, tasks in CATEGORY_CHECKLIST_SEED_TASKS.items():
          if key in category or category in key:
              seed_tasks = tasks
              break
  if not seed_tasks:
      seed_tasks = [("General Inspection Check", "Safety Audit Check")] * 5
      
  def _split_day(lab):      # a seed item may carry a weekday after a bar: "Weekly no-load run|Monday"
      if lab is None: return "[ N/A ]", "Daily"
      text, _, day = str(lab).partition("|")
      if day and normalize_day(day) is None:
          # "HEADER|text" or "HEADER|Sunday: text": the bar is a heading separator, not a weekday, so keep the whole label
          _m = re.match(r"\s*(mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)(?:day)?\s*:\s*(.*)$", day, re.I | re.S)
          if _m and normalize_day(_m.group(1)):
              _d, _rest = normalize_day(_m.group(1)), _m.group(2).strip()
          else:
              _d, _rest = "Daily", day.strip()
          _head = text.strip()
          text = _rest if _head.upper() == "MOTIVATION" else f"{_head}: {_rest}"
          return text.strip(), _d
      return text.strip(), (normalize_day(day) or "Daily") if day else "Daily"
  default_rows = []
  for pair in seed_tasks:
      l1, d1 = _split_day(pair[0] if len(pair) > 0 else None)
      l2, d2 = _split_day(pair[1] if len(pair) > 1 else None)
      default_rows.append({"ChK1": False, "ItemLabel1": l1, "Day1": d1, "ChK2": False, "ItemLabel2": l2, "Day2": d2})
  while len(default_rows) < 5: default_rows.append({"ChK1": False, "ItemLabel1": "[ N/A ]", "Day1": "Daily", "ChK2": False, "ItemLabel2": "[ N/A ]", "Day2": "Daily"})
  return pd.DataFrame(default_rows)

DEFAULT_LABOR_RATE = 85.0   # $/hr, used until it is changed under Settings
DEFAULT_BACKUP_KEEP = 60    # newest backups to keep, until changed under Settings
APP_VERSION = "1.0.7"

def get_setting(key, default=""):
    """Read one value from App_Settings. Never raises; returns default when missing or unreadable."""
    try:
        conn = _sqlite3_real.connect(DB_PATH, timeout=10.0)
        try:
            row = conn.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', (key,)).fetchone()
        finally:
            conn.close()
        return default if row is None or row[0] is None else row[0]
    except Exception:
        return default

def set_setting(key, value):
    """Save one value. Goes through the guarded connection, so it is refused politely when the app is read-only."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', (key, str(value)))
        conn.commit()

# ---- The seven categories that organise the Asset Group list in the sidebar ----
SECTORS = ["Longevity and Awareness", "Inventions", "Government and Municipal", "Factory, Fleet and Industry",
           "Oil Patch and Heavy Equipment", "Fire, Life Safety and Buildings", "Power Production"]
SECTOR_UNSORTED = "Unsorted"
# First match wins, so the order matters. A group the rules do not recognise lands in "Unsorted" until you move it.
_SECTOR_RULES = [
    ("Inventions", [r"\bgem\b", r"green energy machine", r"hydro-?terran", r"\bhtd\b", r"light ?shield", r"\(ls\)", r"irony"]),
    ("Longevity and Awareness", [r"longevity", r"awareness", r"\bhumans?\b", r"preparedness", r"^(habits|goals|relationships|skills)$"]),
    ("Power Production", [r"\bpp\b", r"power", r"reactor", r"candu", r"coal", r"\bwind\b", r"microgrid", r"solar", r"generator", r"\bhydro\b", r"thermal"]),
    ("Fire, Life Safety and Buildings", [r"fire", r"life safety", r"hvac", r"boiler", r"refrigerat", r"building", r"elevator"]),
    ("Oil Patch and Heavy Equipment", [r"drill", r"\brigs?\b", r"fracking", r"\boil\b", r"mining", r"construction", r"agricultur", r"crane", r"hoist", r"pump", r"compressor"]),
    ("Government and Municipal", [r"\btowns?\b", r"\brms?\b", r"public works", r"highway", r"\bports?\b", r"railroad", r"municipal", r"government", r"\bit\b", r"network"]),
    ("Factory, Fleet and Industry", [r"factory", r"forklift", r"material", r"machine tool", r"manufactur", r"production", r"vehicle", r"fleet", r"aircraft", r"marine", r"amph"]),
]

def _sector_overrides():
    """Groups you moved by hand: {group name: category}. Saved in the app settings. Never raises."""
    import json
    try: d = json.loads(get_setting("sector_map", "{}"))
    except Exception: d = {}
    return d if isinstance(d, dict) else {}

MAX_CUSTOM_SECTORS = 10

def custom_sectors():
    """Categories you made yourself: a list of names saved in the app settings. Never raises."""
    import json
    try: d = json.loads(get_setting("custom_sectors", "[]"))
    except Exception: d = []
    return [str(x) for x in d if str(x).strip()] if isinstance(d, list) else []

def all_sectors():
    """The seven built-in categories followed by any you made yourself."""
    return SECTORS + [c for c in custom_sectors() if c not in SECTORS]

def sector_of(group, overrides=None):
    """Which category a group belongs to: your own choice first, then the keyword rules, else Unsorted."""
    import re
    ov = _sector_overrides() if overrides is None else overrides
    if ov.get(group) in all_sectors() or ov.get(group) == SECTOR_UNSORTED: return ov[group]
    low = str(group).lower()
    for sec, pats in _SECTOR_RULES:
        if any(re.search(pt, low) for pt in pats): return sec
    return SECTOR_UNSORTED

def get_labor_rate():
    try: v = float(get_setting("labor_rate", DEFAULT_LABOR_RATE))
    except (TypeError, ValueError): return DEFAULT_LABOR_RATE
    return v if v >= 0 else DEFAULT_LABOR_RATE

def get_backup_keep():
    try: v = int(float(get_setting("backup_keep", DEFAULT_BACKUP_KEEP)))
    except (TypeError, ValueError): return DEFAULT_BACKUP_KEEP
    return v if 1 <= v <= 1000 else DEFAULT_BACKUP_KEEP

def get_company_name():
    """Company name for printouts and new work orders: the Settings value, else the licensee, else blank."""
    # A licensed copy always uses the name on the licence (the name the customer gave when they bought it); it cannot be changed here.
    if LICENSE_INFO.get("state") in ("valid", "expired") and str(LICENSE_INFO.get("licensee", "") or "").strip():
        return str(LICENSE_INFO.get("licensee", "")).strip()
    return str(get_setting("company_name", "") or "").strip()

# ---------------- CSV import (assets and maintenance tasks) ----------------
ASSET_IMPORT_COLUMNS = ["AssetID", "Description", "Category", "SerialNumber", "Color", "Motor", "Transmission", "Fuel", "Maintenance_Protocol", "Current_Meter"]
TASK_IMPORT_COLUMNS = ["AssetID", "TabGroup", "TaskName", "Days_Between", "Meter_Between", "ManHours", "EstimatedPartsCost", "ToolsNeeded",
                       "TaskDescription", "PersonnelQualifications", "SafetyPrecautions", "RequiredConsumables", "Date_Last_Done", "Meter_At_Last"]
TASK_TAB_GROUPS = ["Prevention A", "Prevention B", "Prevention C", "Compliance"]
IMPORT_MAX_ROWS = 5000

def import_template_csv(kind):
    """CSV with the right headings and example rows. kind is 'assets', 'checklist', 'tasks' or 'parts'."""
    if kind == "assets":
        return (",".join(ASSET_IMPORT_COLUMNS) + "\n"
                "PUMP-101,Centrifugal Pump 101,Pumps,SN12345,Blue,Electric,Direct,None,Preventive Maintenance (PM),0\n")
    if kind == "parts":
        return (",".join(PARTS_IMPORT_COLUMNS) + "\n"
                "FLT-0042,Oil filter 4 in.,Shelf A3,Acme Supply,6,2,6,14.50,Pumps/Compressors\n")
    if kind == "checklist":
        return ("AssetID,Category,Item,Day\n"
                "PUMP-101,,Check oil level,\n"
                ",Pumps,Walk around and look for leaks,Daily\n"
                ",Pumps,Grease the bearings,Friday\n")
    return (",".join(TASK_IMPORT_COLUMNS) + "\n"
            "PUMP-101,Prevention A,Grease bearings,30,0,0.5,12.50,Grease gun,Grease both bearings,Mechanic,LOTO,Grease,,\n")

def read_import_csv(data):
    """Turn uploaded CSV bytes into a DataFrame of text. Returns (df, error_message)."""
    import io
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try: text = data.decode("cp1252")
        except Exception: return None, "That file is not readable text. Save it as CSV (comma delimited) and try again."
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as e:
        return None, f"Could not read that file as CSV: {e}"
    return df, None

def guess_import_kind(df):
    """Which kind of file do these headings look like? Returns 'assets', 'checklist', 'tasks', 'parts' or None."""
    norm = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
    have = {norm(c) for c in df.columns}
    kinds = {"assets": ASSET_IMPORT_COLUMNS, "tasks": TASK_IMPORT_COLUMNS, "parts": PARTS_IMPORT_COLUMNS, "checklist": CHECKLIST_IMPORT_COLUMNS}
    best, best_n = None, 1
    for k, cols in kinds.items():
        n = len({norm(c) for c in cols} & have)
        if n > best_n: best, best_n = k, n
    return best

def _canon_columns(df, canon, aliases=None):
    """Rename columns to the standard names, ignoring case, spaces and underscores."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    want = {norm(c): c for c in canon}
    for a, c in (aliases or {}).items(): want[norm(a)] = c
    df = df.rename(columns={col: want[norm(col)] for col in df.columns if norm(col) in want})
    return df.loc[:, ~df.columns.duplicated()]

def _num(text, default=None, as_int=False):
    """Parse a number from CSV text. Returns default when blank; raises ValueError when not a number."""
    s = str(text).replace(",", "").replace("$", "").strip()
    if s == "": return default
    v = float(s)
    return int(v) if as_int else v

def get_existing_asset_meters():
    try:
        conn = _sqlite3_real.connect(DB_PATH, timeout=10.0)
        try: return {str(a): m for a, m in conn.execute('SELECT AssetID, Current_Meter FROM "Trucks"')}
        finally: conn.close()
    except Exception:
        return {}

def get_existing_task_keys():
    try:
        conn = _sqlite3_real.connect(DB_PATH, timeout=10.0)
        try: return {(str(a), str(g), str(t)) for a, g, t in conn.execute('SELECT AssetID, TabGroup, TaskName FROM "Preventive_Schedules"')}
        finally: conn.close()
    except Exception:
        return set()

def validate_asset_rows(df, existing_ids):
    """Check an assets CSV. Returns (rows, errors, skipped). Any error means nothing should be imported."""
    df = _canon_columns(df, ASSET_IMPORT_COLUMNS, {"Year_Make_Model": "Description", "Model": "Description", "Asset": "AssetID",
                                                    "Asset Group": "Category", "Serial": "SerialNumber", "Meter": "Current_Meter", "Protocol": "Maintenance_Protocol"})
    errors = [f"Missing column: {c}" for c in ("AssetID", "Description", "Category") if c not in df.columns]
    if errors: return [], errors, []
    if len(df) == 0: return [], ["The file has no data rows."], []
    if len(df) > IMPORT_MAX_ROWS: return [], [f"The file has {len(df)} rows; the limit is {IMPORT_MAX_ROWS} at a time."], []
    protos = {p.lower(): p for p in MAINTENANCE_PROTOCOLS}
    rows, skipped, seen = [], [], set()
    for i, r in df.iterrows():
        line = i + 2   # line 1 is the header
        g = lambda c, d="": str(r.get(c, d)).strip()
        aid, desc, cat = g("AssetID"), g("Description"), g("Category")
        bad = [n for n, v in (("AssetID", aid), ("Description", desc), ("Category", cat)) if not v]
        if bad: errors.append(f"Line {line}: {', '.join(bad)} is empty."); continue
        if aid in seen: errors.append(f"Line {line}: AssetID {aid} appears more than once in this file."); continue
        seen.add(aid)
        if aid in existing_ids: skipped.append(aid); continue
        try: meter = _num(g("Current_Meter"), 0, as_int=True)
        except ValueError: errors.append(f"Line {line}: Current_Meter '{g('Current_Meter')}' is not a number."); continue
        proto = g("Maintenance_Protocol")
        if proto and proto.lower() not in protos:
            errors.append(f"Line {line}: Maintenance_Protocol must be one of: {', '.join(MAINTENANCE_PROTOCOLS)}."); continue
        rows.append({"AssetID": aid, "Description": desc, "Category": cat, "SerialNumber": g("SerialNumber") or f"SN-{aid}",
                     "Color": g("Color") or "Standard", "Motor": g("Motor") or "None", "Transmission": g("Transmission") or "None",
                     "Fuel": g("Fuel") or "Various", "Maintenance_Protocol": protos.get(proto.lower(), MAINTENANCE_PROTOCOLS[0]),
                     "Current_Meter": meter})
    return rows, errors, skipped

def validate_task_rows(df, asset_meters, existing_keys):
    """Check a tasks CSV. asset_meters maps AssetID to its current meter. Returns (rows, errors, skipped)."""
    df = _canon_columns(df, TASK_IMPORT_COLUMNS, {"Task": "TaskName", "Asset": "AssetID", "Tab": "TabGroup", "Days": "Days_Between",
                                                   "Hours Between": "Meter_Between", "Meter Interval": "Meter_Between"})
    errors = [f"Missing column: {c}" for c in ("AssetID", "TaskName") if c not in df.columns]
    if errors: return [], errors, []
    if len(df) == 0: return [], ["The file has no data rows."], []
    if len(df) > IMPORT_MAX_ROWS: return [], [f"The file has {len(df)} rows; the limit is {IMPORT_MAX_ROWS} at a time."], []
    tabs = {t.lower(): t for t in TASK_TAB_GROUPS}
    today = datetime.now().strftime("%Y-%m-%d")
    rows, skipped, seen = [], [], set()
    for i, r in df.iterrows():
        line = i + 2
        g = lambda c, d="": str(r.get(c, d)).strip()
        aid, task = g("AssetID"), g("TaskName")
        if not aid or not task: errors.append(f"Line {line}: AssetID and TaskName are both required."); continue
        if aid not in asset_meters: errors.append(f"Line {line}: AssetID {aid} is not in the database. Import the assets first."); continue
        tab = g("TabGroup")
        if tab and tab.lower() not in tabs: errors.append(f"Line {line}: TabGroup must be one of: {', '.join(TASK_TAB_GROUPS)}."); continue
        tab = tabs.get(tab.lower(), TASK_TAB_GROUPS[0])
        try:
            days = _num(g("Days_Between"), 0, as_int=True); meter_b = _num(g("Meter_Between"), 0)
            hours = _num(g("ManHours"), 0.0); parts = _num(g("EstimatedPartsCost"), 0.0)
        except ValueError:
            errors.append(f"Line {line}: Days_Between, Meter_Between, ManHours and EstimatedPartsCost must be numbers."); continue
        if min(days, meter_b, hours, parts) < 0: errors.append(f"Line {line}: numbers cannot be negative."); continue
        if days <= 0 and meter_b <= 0: errors.append(f"Line {line}: give Days_Between or Meter_Between (or both), otherwise the task would never come due."); continue
        if 0 < days < MIN_SCHEDULE_DAYS: errors.append(f"Line {line}: " + short_interval_text(task, days)); continue
        done = g("Date_Last_Done") or today
        try: datetime.strptime(done, "%Y-%m-%d")
        except ValueError: errors.append(f"Line {line}: Date_Last_Done must look like 2026-10-08."); continue
        try: meter_last = _num(g("Meter_At_Last"), None)
        except ValueError: errors.append(f"Line {line}: Meter_At_Last '{g('Meter_At_Last')}' is not a number."); continue
        if meter_last is None:
            try: meter_last = int(float(asset_meters.get(aid) or 0))
            except (TypeError, ValueError): meter_last = 0
        key = (aid, tab, task)
        if key in seen: errors.append(f"Line {line}: {aid} / {tab} / {task} appears more than once in this file."); continue
        seen.add(key)
        if key in existing_keys: skipped.append(f"{aid} / {task}"); continue
        rows.append({"AssetID": aid, "TabGroup": tab, "TaskName": task, "Date_Last_Done": done, "Meter_At_Last": str(int(meter_last)) if float(meter_last).is_integer() else str(meter_last),
                     "Days_Between": str(days), "Meter_Between": str(int(meter_b)) if float(meter_b).is_integer() else str(meter_b),
                     "ToolsNeeded": g("ToolsNeeded") or "None", "ManHours": hours, "TaskDescription": g("TaskDescription"),
                     "PersonnelQualifications": g("PersonnelQualifications"), "SafetyPrecautions": g("SafetyPrecautions") or "None",
                     "EstimatedPartsCost": parts, "RequiredConsumables": g("RequiredConsumables") or "None"})
    return rows, errors, skipped

def import_asset_rows(rows):
    """Write validated asset rows in one transaction. Returns how many were added."""
    if DEMO_BUILD and DEMO.get("active"):
        _fp0, _cats0 = _demo_sample_reference()
        _have = {r[2] for r in _demo_rows()}
        demo_cap_gate(len(rows), len({r["Category"] for r in rows if r["Category"] not in _have and r["Category"] not in _cats0}))
    chk = json.dumps([{"ChK1": False, "ItemLabel1": "[ N/A ]", "ChK2": False, "ItemLabel2": "[ N/A ]"}] * 5)
    data = [(r["AssetID"], r["Description"], r["SerialNumber"], r["Color"], r["Motor"], r["Transmission"], r["Fuel"], r["Category"],
             r["Maintenance_Protocol"], r["Current_Meter"], 0, chk) for r in rows]
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.executemany('''INSERT INTO "Trucks" ("AssetID", "Year_Make_Model", "SerialNumber", "Color", "Motor", "Transmission", "Fuel", "Category",
                            "Maintenance_Protocol", "Current_Meter", "Disregard_Dates", "Checklist_Data_V2") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', data)
        conn.commit()
    return len(data)

def import_task_rows(rows):
    """Write validated task rows in one transaction. Returns how many were added."""
    data = [(r["AssetID"], r["TabGroup"], r["TaskName"], r["Date_Last_Done"], r["Meter_At_Last"], r["Days_Between"], r["Meter_Between"],
             r["ToolsNeeded"], r["ManHours"], r["TaskDescription"], r["PersonnelQualifications"], r["SafetyPrecautions"],
             r["EstimatedPartsCost"], r["RequiredConsumables"]) for r in rows]
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.executemany('''INSERT INTO "Preventive_Schedules" ("AssetID", "TabGroup", "TaskName", "Date_Last_Done", "Meter_At_Last", "Days_Between",
                            "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", "PersonnelQualifications", "SafetyPrecautions",
                            "EstimatedPartsCost", "RequiredConsumables") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', data)
        conn.commit()
    return len(data)

CHECKLIST_IMPORT_COLUMNS = ["AssetID", "Category", "Item", "Day"]
_CHK_PLACEHOLDERS = ("", "[ N/A ]", "nan", "None")

def get_existing_checklists():
    """AssetID -> (Category, saved checklist text) for every asset."""
    try:
        conn = _sqlite3_real.connect(DB_PATH, timeout=10.0)
        try: return {str(a): (str(c or ""), j) for a, c, j in conn.execute('SELECT AssetID, Category, Checklist_Data_V2 FROM "Trucks"')}
        finally: conn.close()
    except Exception:
        return {}

def validate_checklist_rows(df, assets):
    """Check a daily-checklist CSV: one item per line, for one asset (AssetID) or every asset in a group (Category).
    assets is get_existing_checklists(). Returns (plan, errors, skipped); any error means nothing should be imported."""
    df = _canon_columns(df, CHECKLIST_IMPORT_COLUMNS, {"ItemLabel": "Item", "Checklist Item": "Item", "Check": "Item",
                                                        "Asset": "AssetID", "Asset Group": "Category", "Weekday": "Day", "Day of Week": "Day"})
    errors = []
    if "Item" not in df.columns: errors.append("Missing column: Item")
    if "AssetID" not in df.columns and "Category" not in df.columns: errors.append("Missing column: AssetID (one asset) or Category (every asset in a group)")
    if errors: return [], errors, []
    if len(df) == 0: return [], ["The file has no data rows."], []
    if len(df) > IMPORT_MAX_ROWS: return [], [f"The file has {len(df)} rows; the limit is {IMPORT_MAX_ROWS} at a time."], []
    by_cat = {}
    for aid, (cat, _) in assets.items(): by_cat.setdefault(cat.lower(), []).append(aid)
    wanted = {}
    for i, r in df.iterrows():
        line = i + 2
        g = lambda c: str(r.get(c, "")).strip()
        aid, cat, item = g("AssetID"), g("Category"), g("Item")
        if not item or item in _CHK_PLACEHOLDERS: errors.append(f"Line {line}: Item is empty."); continue
        if len(item) > 200: errors.append(f"Line {line}: Item is longer than 200 characters."); continue
        day = normalize_day(g("Day") if "Day" in df.columns else "")
        if day is None: errors.append(f"Line {line}: Day '{g('Day')}' is not understood. Leave it blank (or Daily) or use a day of the week such as Friday."); continue
        if aid:
            if aid not in assets: errors.append(f"Line {line}: AssetID {aid} is not in the database. Import the assets first."); continue
            targets = [aid]
        elif cat:
            targets = by_cat.get(cat.lower())
            if not targets: errors.append(f"Line {line}: no assets in the group '{cat}'. Import the assets first."); continue
        else:
            errors.append(f"Line {line}: give an AssetID or a Category."); continue
        for t in targets: wanted.setdefault(t, []).append((item, day))
    if errors: return [], errors, []
    plan, skipped = [], []
    for aid, items in wanted.items():
        cat, saved = assets[aid]
        try:
            base = json.loads(saved)
            if not isinstance(base, list): raise ValueError
        except Exception:
            base = get_default_checklist_df(cat).to_dict(orient="records")   # what the Checklists screen shows for this unit
        base = [{"ChK1": bool(b.get("ChK1", False)), "ItemLabel1": str(b.get("ItemLabel1", "[ N/A ]")), "Day1": normalize_day(b.get("Day1")) or "Daily",
                 "ChK2": bool(b.get("ChK2", False)), "ItemLabel2": str(b.get("ItemLabel2", "[ N/A ]")), "Day2": normalize_day(b.get("Day2")) or "Daily"} for b in base]
        have = {x.strip().lower() for b in base for x in (b["ItemLabel1"], b["ItemLabel2"]) if x.strip() not in _CHK_PLACEHOLDERS}
        added = []
        for item, day in items:
            if item.lower() in have: skipped.append(f"{aid} / {item}"); continue
            have.add(item.lower()); added.append((item, day))
        if not added: continue
        queue = list(added)
        for b in base:                                   # fill empty "[ N/A ]" slots first, keeping the existing layout
            for slot in ("ItemLabel1", "ItemLabel2"):
                if queue and b[slot].strip() in _CHK_PLACEHOLDERS:
                    b[slot], b["Day" + slot[-1]] = queue.pop(0)
        while queue:                                     # then add new rows, two items per row
            first = queue.pop(0); second = queue.pop(0) if queue else ("[ N/A ]", "Daily")
            base.append({"ChK1": False, "ItemLabel1": first[0], "Day1": first[1], "ChK2": False, "ItemLabel2": second[0], "Day2": second[1]})
        plan.append({"AssetID": aid, "Added": len(added), "Preview": "; ".join(a[0] for a in added[:3]) + ("..." if len(added) > 3 else ""),
                     "new_json": json.dumps(base)})
    return plan, [], skipped

def import_checklist_rows(plan):
    """Save the updated checklists in one transaction. Returns how many assets were updated."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.executemany('UPDATE "Trucks" SET Checklist_Data_V2 = ? WHERE AssetID = ?', [(p["new_json"], p["AssetID"]) for p in plan])
        conn.commit()
    return len(plan)

# ---------------- Overdue dashboard ----------------
def _to_float(v, default=0.0):
    s = str(v if v is not None else "").replace(",", "").strip()
    if s in ("", "None", "nan"): return default
    try: return float(s)
    except ValueError: return default

def _parse_day(v):
    s = str(v if v is not None else "").strip()
    if not s or s.lower() in ("none", "nan"): return None
    try: return datetime.strptime(s.split()[0], "%Y-%m-%d").date()
    except ValueError: return None

DUE_ORDER = {"Overdue": 0, "Due today": 1, "Due soon": 2, "OK": 3}
_NO_TASK_NAMES = ("", "n/a", "[ n/a ]", "none", "nan")

def compute_due_rows(rows, today=None, soon_days=7):
    """rows: dicts with AssetID, Year_Make_Model, Category, TabGroup, TaskName, Date_Last_Done, Meter_At_Last,
    Days_Between, Meter_Between, ManHours, Current_Meter, Disregard_Dates.
    A task is DUE under the same rule the work-order generator uses: days since last done >= Days_Between (when Days_Between > 0
    and the asset is not set to disregard dates), or meter since last done >= Meter_Between (when Meter_Between > 0).
    Overdue = past that point; Due today = exactly at it; Due soon = within soon_days (or the last 10% of the meter interval)."""
    today = today or datetime.now().date()
    out = []
    for r in rows:
        name = str(r.get("TaskName") or "").strip()
        if name.lower() in _NO_TASK_NAMES: continue
        days_b = int(_to_float(r.get("Days_Between")))
        if 0 < days_b < 7: continue   # daily / every-few-days items belong on the Checklists, not the overdue list
        meter_b = _to_float(r.get("Meter_Between"))
        ignore_dates = bool(_to_float(r.get("Disregard_Dates")))
        last = _parse_day(r.get("Date_Last_Done"))
        due_date = days_left = None
        if days_b > 0 and last and not ignore_dates:
            due_date = last + _timedelta(days=days_b)
            days_left = (due_date - today).days
        meter_left = None
        if meter_b > 0:
            meter_left = _to_float(r.get("Meter_At_Last")) + meter_b - _to_float(r.get("Current_Meter"))
        due_now = (days_left is not None and days_left <= 0) or (meter_left is not None and meter_left <= 0)
        strictly = (days_left is not None and days_left < 0) or (meter_left is not None and meter_left < 0)
        near = (days_left is not None and days_left <= soon_days) or (meter_left is not None and meter_left <= 0.10 * meter_b)
        status = ("Overdue" if strictly else "Due today") if due_now else ("Due soon" if near else "OK")
        out.append({"Status": status, "Asset": str(r.get("AssetID") or ""), "Description": str(r.get("Year_Make_Model") or ""),
                    "Group": str(r.get("Category") or ""), "Tab": str(r.get("TabGroup") or ""), "Task": name,
                    "Last Done": last.isoformat() if last else "", "Due Date": due_date.isoformat() if due_date else "",
                    "Day": due_date.strftime("%A") if (due_date and days_b == 7) else "",
                    "Days Left": days_left, "Meter Left": meter_left, "Hours": _to_float(r.get("ManHours")),
                    "_rank": DUE_ORDER[status]})
    df = pd.DataFrame(out, columns=["Status", "Asset", "Description", "Group", "Tab", "Task", "Last Done", "Due Date", "Day",
                                    "Days Left", "Meter Left", "Hours", "_rank"])
    if df.empty: return df.drop(columns=["_rank"])
    df["_d"] = df["Days Left"].fillna(10**9)
    df = df.sort_values(["_rank", "_d", "Asset", "Task"]).drop(columns=["_rank", "_d"]).reset_index(drop=True)
    return df

def fetch_due_tasks(category=None, soon_days=7, today=None):
    q = '''SELECT t.AssetID, t.Year_Make_Model, t.Category, p.TabGroup, p.TaskName, p.Date_Last_Done, p.Meter_At_Last,
                  p.Days_Between, p.Meter_Between, p.ManHours, t.Current_Meter, t.Disregard_Dates
           FROM "Preventive_Schedules" p JOIN "Trucks" t ON p.AssetID = t.AssetID'''
    params = []
    if category: q += " WHERE t.Category = ?"; params.append(category)
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.row_factory = _sqlite3_real.Row
        rows = [dict(r) for r in conn.execute(q, params)]
    return compute_due_rows(rows, today, soon_days)

def build_table_pdf(title, subtitle, headers, rows, col_widths, bold_rows=(), footer=""):
    """Generic landscape table PDF. Title, subtitle, column headings and page numbers repeat on every page."""
    import io
    from xml.sax.saxutils import escape as xml_esc
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer
    page = landscape(letter)
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('tcell', parent=styles['Normal'], fontSize=8.5, leading=10.5)

    def draw_page_header(canvas, doc):
        w, h = page
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(30, h - 34, title)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30, h - 47, f"{subtitle}   |   Generated: {generated}")
        canvas.setLineWidth(0.75)
        canvas.line(30, h - 53, w - 30, h - 53)
        canvas.restoreState()
        draw_licensee_line(canvas)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=page, leftMargin=30, rightMargin=30, topMargin=66, bottomMargin=30)
    doc.addPageTemplates([PageTemplate(id="main", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")], onPage=draw_page_header)])
    def para(v, bold=False):
        s = "" if v is None else str(v)
        s = xml_esc(s).replace("\n", "<br/>")
        return Paragraph(f"<b>{s}</b>" if bold else s, cell)
    data = [[para(h, True) for h in headers]]
    for i, r in enumerate(rows):
        data.append([para(c, i in bold_rows) for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey), ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
                           ('BOX', (0, 0), (-1, -1), 1, colors.black), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story = [t]
    if footer: story += [Spacer(1, 12), Paragraph(footer, styles['Normal'])]
    doc.build(story, canvasmaker=make_numbered_canvas())
    return buf.getvalue()

def _fmt_num(v, nd=0):
    if v is None or (isinstance(v, float) and pd.isna(v)): return ""
    return f"{v:,.{nd}f}"

def build_overdue_pdf(df, scope_text, soon_days):
    rows = [[r["Status"], r["Asset"], r["Description"], r["Group"], r["Task"], r["Last Done"], (r["Due Date"] + (" " + r["Day"][:3] if r["Day"] else "")),
             _fmt_num(r["Days Left"]), _fmt_num(r["Meter Left"])] for _, r in df.iterrows()]
    bold = {i for i, (_, r) in enumerate(df.iterrows()) if r["Status"] in ("Overdue", "Due today")}
    n_over = int((df["Status"] == "Overdue").sum()); n_today = int((df["Status"] == "Due today").sum()); n_soon = int((df["Status"] == "Due soon").sum())
    return build_table_pdf("Overdue and Due-Soon Maintenance", f"{scope_text}   |   Due soon = within {soon_days} days",
                           ["Status", "Asset", "Description", "Group", "Task", "Last Done", "Due", "Days Left", "Meter Left"],
                           rows, [58, 66, 130, 90, 176, 58, 58, 45, 51], bold_rows=bold,
                           footer=f"<b>{n_over}</b> overdue &nbsp;&mdash;&nbsp; <b>{n_today}</b> due today &nbsp;&mdash;&nbsp; <b>{n_soon}</b> due soon. "
                                  "Negative Days Left / Meter Left means overdue by that much.")

# ---------------- Parts inventory ----------------
INVENTORY_KINDS = ["Received", "Used", "Adjusted"]
PART_GENERAL = "General (all groups)"   # parts used by more than one asset group (oil, filters, fasteners...)

def part_group_choices():
    """Dropdown choices for a part's asset group: General first, then every group the app knows about."""
    return [PART_GENERAL] + [g for g in FULL_CATEGORIES_LIST if g != PART_GENERAL]

def part_status(qty, reorder_point):
    if _to_float(qty) <= 0: return "OUT"
    rp = _to_float(reorder_point)
    return "LOW" if rp > 0 and _to_float(qty) <= rp else "OK"

def fetch_parts():
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        df = pd.read_sql('SELECT PartID, PartNumber, Description, AssetGroup, Location, Supplier, QtyOnHand, ReorderPoint, ReorderQty, UnitCost FROM "Inventory_Parts" ORDER BY PartNumber COLLATE NOCASE', conn)
    df["AssetGroup"] = df["AssetGroup"].fillna("").astype(str).str.strip().replace("", PART_GENERAL)
    for c in ("QtyOnHand", "ReorderPoint", "ReorderQty", "UnitCost"): df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["Status"] = [part_status(q, rp) for q, rp in zip(df["QtyOnHand"], df["ReorderPoint"])]
    df["Value"] = (df["QtyOnHand"] * df["UnitCost"]).round(2)
    return df

def needs_reorder(df):
    """Parts at or below their reorder point (parts with no reorder point set are never listed)."""
    d = df[(df["ReorderPoint"] > 0) & (df["QtyOnHand"] <= df["ReorderPoint"])].copy()
    d["Suggested"] = [rq if rq > 0 else max(rp * 2 - q, 1.0) for q, rp, rq in zip(d["QtyOnHand"], d["ReorderPoint"], d["ReorderQty"])]
    d["EstCost"] = (d["Suggested"] * d["UnitCost"]).round(2)
    return d

def _clean_qty(v, label, allow_zero=True):
    try: x = float(str(v).replace(",", "").strip() or 0)
    except ValueError: return None, f"{label} must be a number."
    if x != x or x in (float("inf"), float("-inf")): return None, f"{label} must be a number."
    if x < 0 or (x == 0 and not allow_zero): return None, f"{label} cannot be negative." if allow_zero else f"{label} must be more than zero."
    return x, None

def add_part(part_number, description, location="", supplier="", qty=0, reorder_point=0, reorder_qty=0, unit_cost=0, asset_group=PART_GENERAL):
    pn, desc = (part_number or "").strip(), (description or "").strip()
    if not pn or not desc: return False, "Part number and description are both required."
    vals = []
    for v, lbl in ((qty, "Quantity on hand"), (reorder_point, "Reorder point"), (reorder_qty, "Reorder quantity"), (unit_cost, "Unit cost")):
        x, err = _clean_qty(v, lbl)
        if err: return False, err
        vals.append(x)
    qty, rp, rq, uc = vals
    try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            if conn.execute('SELECT 1 FROM "Inventory_Parts" WHERE lower(PartNumber) = lower(?)', (pn,)).fetchone():
                return False, f"Part number {pn} already exists."
            cur = conn.execute('INSERT INTO "Inventory_Parts" (PartNumber, Description, AssetGroup, Location, Supplier, QtyOnHand, ReorderPoint, ReorderQty, UnitCost) VALUES (?,?,?,?,?,?,?,?,?)',
                               (pn, desc, (asset_group or PART_GENERAL).strip(), (location or "").strip(), (supplier or "").strip(), qty, rp, rq, uc))
            if qty > 0:
                conn.execute('INSERT INTO "Inventory_Moves" (PartID, MoveDate, Kind, Qty, BalanceAfter, AssetID, Note, UserName) VALUES (?,?,?,?,?,?,?,?)',
                             (cur.lastrowid, datetime.now().strftime("%Y-%m-%d %H:%M"), "Received", qty, qty, "", "Opening balance", current_user_name()))
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was saved: {e}"
    return True, f"Added part {pn}."

def record_move(part_id, kind, qty, asset_id="", note=""):
    """Received adds, Used subtracts (never below zero), Adjusted sets the on-hand count to qty. Logged with who and when."""
    if kind not in INVENTORY_KINDS: return False, "Unknown action."
    q, err = _clean_qty(qty, "Quantity", allow_zero=(kind == "Adjusted"))
    if err: return False, err
    try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            row = conn.execute('SELECT PartNumber, QtyOnHand FROM "Inventory_Parts" WHERE PartID = ?', (int(part_id),)).fetchone()
            if not row: return False, "That part no longer exists."
            pn, on_hand = row[0], _to_float(row[1])
            if kind == "Received": new, delta = on_hand + q, q
            elif kind == "Used":
                if q > on_hand: return False, f"Only {on_hand:g} of {pn} on hand, so {q:g} cannot be used."
                new, delta = on_hand - q, -q
            else: new, delta = q, q - on_hand
            conn.execute('UPDATE "Inventory_Parts" SET QtyOnHand = ? WHERE PartID = ?', (new, int(part_id)))
            conn.execute('INSERT INTO "Inventory_Moves" (PartID, MoveDate, Kind, Qty, BalanceAfter, AssetID, Note, UserName) VALUES (?,?,?,?,?,?,?,?)',
                         (int(part_id), datetime.now().strftime("%Y-%m-%d %H:%M"), kind, delta, new, (asset_id or "").strip(), (note or "").strip(), current_user_name()))
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was saved: {e}"
    verb = {"Received": f"received {q:g}", "Used": f"used {q:g}", "Adjusted": "counted"}[kind]
    return True, f"{pn}: {verb}. On hand was {on_hand:g}, now {new:g}."

def save_part_details(df):
    """Save edited Description / Asset group / Location / Supplier / ReorderPoint / ReorderQty / UnitCost. Stock quantities change only through record_move."""
    updates = []
    for _, r in df.iterrows():
        desc = str(r["Description"] or "").strip()
        if not desc: return False, f"Part {r['PartNumber']}: description cannot be empty."
        vals = []
        for c, lbl in (("ReorderPoint", "Reorder point"), ("ReorderQty", "Reorder quantity"), ("UnitCost", "Unit cost")):
            x, err = _clean_qty(r[c], f"Part {r['PartNumber']}: {lbl}")
            if err: return False, err
            vals.append(x)
        updates.append((desc, str(r["AssetGroup"] or PART_GENERAL).strip() or PART_GENERAL, str(r["Location"] or "").strip(), str(r["Supplier"] or "").strip(), vals[0], vals[1], vals[2], int(r["PartID"])))
    try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            conn.executemany('UPDATE "Inventory_Parts" SET Description=?, AssetGroup=?, Location=?, Supplier=?, ReorderPoint=?, ReorderQty=?, UnitCost=? WHERE PartID=?', updates)
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was saved: {e}"
    return True, f"Saved {len(updates)} part(s)."

def fetch_moves(part_id=None, limit=500):
    q = '''SELECT m.MoveDate AS "When", p.PartNumber AS "Part", p.Description AS "Description", m.Kind AS "Action", m.Qty AS "Change",
                  m.BalanceAfter AS "Balance", m.AssetID AS "Asset", m.Note AS "Note", m.UserName AS "By"
           FROM "Inventory_Moves" m LEFT JOIN "Inventory_Parts" p ON m.PartID = p.PartID'''
    params = []
    if part_id: q += " WHERE m.PartID = ?"; params.append(int(part_id))
    q += " ORDER BY m.MoveID DESC LIMIT ?"; params.append(int(limit))
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        return pd.read_sql(q, conn, params=params)

def build_reorder_pdf(df):
    d = needs_reorder(df)
    rows = [[r["PartNumber"], r["Description"], r["AssetGroup"], r["Location"], r["Supplier"], f"{r['QtyOnHand']:g}", f"{r['ReorderPoint']:g}",
             f"{r['Suggested']:g}", f"${r['EstCost']:,.2f}"] for _, r in d.sort_values(["Supplier", "PartNumber"]).iterrows()]
    return build_table_pdf("Parts Reorder List", f"{len(d)} part(s) at or below their reorder point",
                           ["Part #", "Description", "Asset Group", "Location", "Supplier", "On Hand", "Reorder At", "Order Qty", "Est. Cost"],
                           rows, [80, 170, 90, 70, 115, 45, 52, 50, 60],
                           footer=f"<b>Estimated total:</b> ${d['EstCost'].sum():,.2f}")

# ---------------- Warranty tracking ----------------
WARRANTY_ACTION = "Extend the warranty, or make sure spare parts are on hand"
WARRANTY_GRACE_DAYS = 30   # a warranty that ran out within this many days still counts as needing attention

def add_months(d, months):
    """d plus a whole number of months; the day is clamped to the end of a shorter month (Feb 29 + 1 year = Feb 28)."""
    import calendar
    m0 = d.month - 1 + int(months)
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))

def warranty_end_from_years(bought, years):
    """Purchase date (YYYY-MM-DD text) plus warranty length in years (halves and months allowed, e.g. 1.5). None if it cannot be worked out."""
    d = _parse_day(bought)
    try: months = round(float(years) * 12)
    except (TypeError, ValueError): return None
    if d is None or months <= 0: return None
    return add_months(d, months)

def warranty_status(expires, today=None, soon_days=60, limit_meter=None, current_meter=None):
    """Returns (status, days_left, meter_left). A warranty that ends at a date, at a meter reading, or whichever comes first.
    Status: None / Active / Expiring soon / Just expired / Expired (long ago)."""
    parts = []
    d = _parse_day(expires)
    days_left = None
    if d is not None:
        days_left = (d - (today or datetime.now().date())).days
        parts.append("Just expired" if -WARRANTY_GRACE_DAYS <= days_left < 0 else "Expired" if days_left < 0 else "Expiring soon" if days_left <= soon_days else "Active")
    meter_left = None
    lim = _to_float(limit_meter)
    if lim > 0:
        meter_left = lim - _to_float(current_meter)
        band = 0.10 * lim
        parts.append("Active" if meter_left > band else "Expiring soon" if meter_left >= 0 else "Just expired" if -meter_left <= band else "Expired")
    if not parts: return "None", None, None
    for st_ in ("Expired", "Just expired", "Expiring soon", "Active"):
        if st_ in parts: return st_, days_left, meter_left

WARRANTY_COLS = ["Asset", "Description", "Group", "Bought", "Years", "Hours Limit", "Expires", "Provider", "Notes", "Status", "Days Left", "Meter Left"]

def fetch_warranties(category=None, soon_days=60, today=None):
    q = '''SELECT AssetID, Year_Make_Model, Category, Date_Acquired, Warranty_Years, Warranty_Hours, Warranty_Expires, Warranty_Provider,
                  Warranty_Notes, Current_Meter FROM "Trucks"'''
    params = []
    if category: q += " WHERE Category = ?"; params.append(category)
    q += " ORDER BY Category, AssetID"
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        rows = conn.execute(q, params).fetchall()
    out = []
    for aid, model, cat, bought, yrs, hrs, exp, prov, notes, meter in rows:
        st_, left, mleft = warranty_status(exp, today, soon_days, hrs, meter)
        yv, hv = _to_float(yrs), _to_float(hrs)
        out.append({"Asset": str(aid), "Description": str(model or ""), "Group": str(cat or ""), "Bought": str(bought or "").strip(),
                    "Years": yv if yv > 0 else None, "Hours Limit": hv if hv > 0 else None, "Expires": str(exp or "").strip(),
                    "Provider": str(prov or ""), "Notes": str(notes or ""), "Status": st_, "Days Left": left, "Meter Left": mleft})
    df = pd.DataFrame(out, columns=WARRANTY_COLS)
    df["Years"] = pd.to_numeric(df["Years"], errors="coerce"); df["Hours Limit"] = pd.to_numeric(df["Hours Limit"], errors="coerce")
    return df

def warranties_needing_action(df):
    d = df[df["Status"].isin(["Expiring soon", "Just expired"])].copy()
    d["_k"] = pd.to_numeric(d["Days Left"], errors="coerce").fillna(10**9)
    d = d.sort_values(["_k", "Asset"]).drop(columns=["_k"])
    d["Action"] = WARRANTY_ACTION
    return d

def _norm_w(vals):
    out = []
    for v in vals:
        if v is None or (isinstance(v, float) and v != v): out.append("")
        else:
            t = str(v).strip()
            try: t = f"{float(t):g}" if t not in ("",) and t.replace(".", "", 1).replace("-", "", 1).isdigit() else t
            except ValueError: pass
            out.append("" if t.lower() in ("none", "nan", "0") else t)
    return tuple(out)

def save_warranties(df):
    """Save the warranty fields by asset. If you give Years and a purchase date, the end date is worked out for you; typing an end date
    yourself always wins. Dates must look like 2027-03-31. Nothing is saved if any row is wrong."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        stored = {str(a): (str(b or "").strip(), _to_float(y), str(e or "").strip()) for a, b, y, e in
                  conn.execute('SELECT AssetID, Date_Acquired, Warranty_Years, Warranty_Expires FROM "Trucks"')}
        before = {str(r[0]): _norm_w(r[1:]) for r in conn.execute(
            'SELECT AssetID, Date_Acquired, Warranty_Years, Warranty_Hours, Warranty_Expires, Warranty_Provider, Warranty_Notes FROM "Trucks"')}
    def blank(v): return "" if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip().lower() in ("none", "nan") else str(v).strip()
    def datefix(v, aid, label):
        t = blank(v)
        if not t: return "", None
        d = _parse_day(t)
        if d is None or len(t.split()[0]) != 10: return None, f"Asset {aid}: {label} '{t}' must look like 2027-03-31."
        return d.isoformat(), None
    updates = []
    for _, r in df.iterrows():
        aid = str(r["Asset"])
        bought, err = datefix(r["Bought"], aid, "purchase date")
        if err: return False, err
        exp, err = datefix(r["Expires"], aid, "warranty end date")
        if err: return False, err
        try:
            yrs = float(blank(r["Years"]) or 0); hrs = float(blank(r["Hours Limit"]) or 0)
        except ValueError: return False, f"Asset {aid}: Years and Hours Limit must be numbers."
        if yrs < 0 or hrs < 0 or yrs > 100: return False, f"Asset {aid}: Years must be between 0 and 100, and Hours Limit cannot be negative."
        old_b, old_y, old_e = stored.get(aid, ("", 0.0, ""))
        # end date not typed by hand, and years/purchase date are new or changed (or there is no end date yet): work it out
        if yrs > 0 and (exp == old_e or not exp) and (not exp or yrs != old_y or bought != old_b):
            end = warranty_end_from_years(bought, yrs)
            if end is not None: exp = end.isoformat()
            else: return False, f"Asset {aid}: enter the purchase date (like 2024-05-30) so the end date can be worked out from {yrs:g} year(s)."
        updates.append((bought, yrs or None, hrs or None, exp, blank(r["Provider"]), blank(r["Notes"]), aid))
    try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            conn.executemany('UPDATE "Trucks" SET Date_Acquired = ?, Warranty_Years = ?, Warranty_Hours = ?, Warranty_Expires = ?, Warranty_Provider = ?, Warranty_Notes = ? WHERE AssetID = ?', updates)
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was saved: {e}"
    changed = sum(1 for u in updates if _norm_w(u[:6]) != before.get(u[6], ()))
    return True, (f"Saved. {changed} asset(s) changed." if changed else "Nothing had changed, so nothing was updated.")

def build_warranty_pdf(df, scope_text, soon_days):
    rows = [[r["Status"], r["Asset"], r["Description"], r["Group"], r["Expires"], _fmt_num(r["Days Left"]), _fmt_num(r["Meter Left"]), r["Provider"], WARRANTY_ACTION] for _, r in df.iterrows()]
    return build_table_pdf("Warranties Expiring or Just Expired", f"{scope_text}   |   Expiring soon = within {soon_days} days",
                           ["Status", "Asset", "Description", "Group", "Ends", "Days Left", "Meter Left", "Provider", "Action"],
                           rows, [66, 60, 110, 80, 56, 38, 44, 90, 188], bold_rows=set(range(len(rows))),
                           footer="Negative Days Left or Meter Left means the warranty has already ended. A warranty ends at whichever limit comes first.")

def dashboard_alert_counts(groups=None):
    """(tasks overdue or due today, parts needing reorder, warranties needing action) for the Switchboard banner. Never raises.
    groups: if given, only tasks in those asset groups are counted (the category being viewed)."""
    try:
        d = fetch_due_tasks(None, 7)
        if groups is not None and not d.empty: d = d[d["Group"].isin(list(groups))]
        n_tasks = int(d["Status"].isin(["Overdue", "Due today"]).sum()) if not d.empty else 0
    except Exception:
        n_tasks = 0
    try: n_parts = len(needs_reorder(fetch_parts()))
    except Exception: n_parts = 0
    try: n_warr = len(warranties_needing_action(fetch_warranties()))
    except Exception: n_warr = 0
    return n_tasks, n_parts, n_warr

PARTS_IMPORT_COLUMNS = ["PartNumber", "Description", "Location", "Supplier", "QtyOnHand", "ReorderPoint", "ReorderQty", "UnitCost", "AssetGroup"]

def get_existing_part_numbers():
    try:
        conn = _sqlite3_real.connect(DB_PATH, timeout=10.0)
        try: return {str(r[0]).lower() for r in conn.execute('SELECT PartNumber FROM "Inventory_Parts"')}
        finally: conn.close()
    except Exception:
        return set()

def validate_part_rows(df, existing):
    """Check a parts CSV. existing = lower-case part numbers already stored. Returns (rows, errors, skipped)."""
    df = _canon_columns(df, PARTS_IMPORT_COLUMNS, {"Part Number": "PartNumber", "Part #": "PartNumber", "Part No": "PartNumber", "Part": "PartNumber",
                                                    "Qty": "QtyOnHand", "Quantity": "QtyOnHand", "On Hand": "QtyOnHand", "Min": "ReorderPoint",
                                                    "Reorder Level": "ReorderPoint", "Cost": "UnitCost", "Price": "UnitCost", "Bin": "Location", "Group": "AssetGroup", "Asset Group": "AssetGroup", "Category": "AssetGroup"})
    errors = [f"Missing column: {c}" for c in ("PartNumber", "Description") if c not in df.columns]
    if errors: return [], errors, []
    if len(df) == 0: return [], ["The file has no data rows."], []
    if len(df) > IMPORT_MAX_ROWS: return [], [f"The file has {len(df)} rows; the limit is {IMPORT_MAX_ROWS} at a time."], []
    rows, skipped, seen = [], [], set()
    for i, r in df.iterrows():
        line = i + 2
        g = lambda c: str(r.get(c, "")).strip()
        pn, desc = g("PartNumber"), g("Description")
        if not pn or not desc: errors.append(f"Line {line}: PartNumber and Description are both required."); continue
        if pn.lower() in seen: errors.append(f"Line {line}: part number {pn} appears more than once in this file."); continue
        seen.add(pn.lower())
        if pn.lower() in existing: skipped.append(pn); continue
        nums, bad = [], False
        for c in ("QtyOnHand", "ReorderPoint", "ReorderQty", "UnitCost"):
            try: x = _num(g(c), 0.0)
            except ValueError: errors.append(f"Line {line}: {c} '{g(c)}' is not a number."); bad = True; break
            if x < 0: errors.append(f"Line {line}: {c} cannot be negative."); bad = True; break
            nums.append(x)
        if bad: continue
        rows.append({"PartNumber": pn, "Description": desc, "Location": g("Location"), "Supplier": g("Supplier"),
                     "QtyOnHand": nums[0], "ReorderPoint": nums[1], "ReorderQty": nums[2], "UnitCost": nums[3],
                     "AssetGroup": g("AssetGroup") or PART_GENERAL})
    return rows, errors, skipped

def import_part_rows(rows):
    """Insert parts in one transaction, with an 'Opening balance' log entry for any stock on hand. Returns how many were added."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        for r in rows:
            cur = conn.execute('INSERT INTO "Inventory_Parts" (PartNumber, Description, AssetGroup, Location, Supplier, QtyOnHand, ReorderPoint, ReorderQty, UnitCost) VALUES (?,?,?,?,?,?,?,?,?)',
                               (r["PartNumber"], r["Description"], r.get("AssetGroup") or PART_GENERAL, r["Location"], r["Supplier"], r["QtyOnHand"], r["ReorderPoint"], r["ReorderQty"], r["UnitCost"]))
            if r["QtyOnHand"] > 0:
                conn.execute('INSERT INTO "Inventory_Moves" (PartID, MoveDate, Kind, Qty, BalanceAfter, AssetID, Note, UserName) VALUES (?,?,?,?,?,?,?,?)',
                             (cur.lastrowid, now, "Received", r["QtyOnHand"], r["QtyOnHand"], "", "Opening balance (import)", current_user_name()))
        conn.commit()
    return len(rows)

def _sync_asset_table(conn, table, pk, cols, asset_id, df):
    """Make the rows for one asset in `table` match the edited grid: existing rows (known id) are updated, rows with no id are added,
    rows that were removed from the grid are deleted, and completely blank rows are ignored. Only this asset's rows are touched."""
    clean = lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    have = {r[0] for r in conn.execute(f'SELECT "{pk}" FROM "{table}" WHERE AssetID = ?', (asset_id,))}
    keep = set()
    for _, r in df.iterrows():
        vals = [clean(r.get(c)) for c in cols]
        rid = r.get(pk)
        try: rid = None if rid is None or pd.isna(rid) else int(rid)
        except (TypeError, ValueError): rid = None
        if rid is not None and rid in have:
            keep.add(rid)
            conn.execute(f'UPDATE "{table}" SET ' + ", ".join(f'"{c}" = ?' for c in cols) + f' WHERE "{pk}" = ? AND AssetID = ?', vals + [rid, asset_id])
        elif any(v.strip() for v in vals):
            conn.execute(f'INSERT INTO "{table}" (AssetID, ' + ", ".join(f'"{c}"' for c in cols) + ') VALUES (?' + ", ?" * len(cols) + ')', [asset_id] + vals)
    for gone in have - keep:
        conn.execute(f'DELETE FROM "{table}" WHERE "{pk}" = ? AND AssetID = ?', (gone, asset_id))

def save_bom_tables(conn, asset_id, attr_df, parts_df, comp_df):
    """Save the three Subs/Parts grids for one asset (any that is None is left alone)."""
    if attr_df is not None: _sync_asset_table(conn, "Asset_Attributes", "AttrID", ["AttributeName", "Value", "Notes"], asset_id, attr_df)
    if parts_df is not None: _sync_asset_table(conn, "Asset_Parts", "PartID", ["PartHeading", "PartDescription", "Supplier", "PowerUsage", "Inventory", "Status"], asset_id, parts_df)
    if comp_df is not None: _sync_asset_table(conn, "Asset_Components", "ComponentID", ["ComponentName", "PartNumber", "ConditionStatus", "Notes"], asset_id, comp_df)

# ---------------- Start fresh / reset / restore ----------------
DATA_KEEP_TABLES = ("Users", "App_Settings", "Glossary")   # never cleared or replaced: logins, licence, settings, reference glossary

def _data_tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'") if r[0] not in DATA_KEEP_TABLES]

def reset_data(mode):
    """Clear all equipment, tasks, parts, work orders and history (users, licence and settings are kept).
    mode 'empty' leaves a blank program; 'sample' then loads the built-in sample data. A full backup is made first.
    Returns (ok, message)."""
    if mode not in ("empty", "sample"): return False, "Unknown action."
    try: bk = os.path.basename(backup_database())
    except Exception as e: return False, f"Backup failed, nothing was changed: {e}"
    try:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cur = conn.cursor()
            tables = _data_tables(conn)
            for t in tables: cur.execute(f'DELETE FROM "{t}"')
            try: cur.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" * len(tables)), tables)
            except sqlite3.Error: pass
            cur.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("seed_mode", mode))
            if mode == "sample": seed_sample_data(cur)
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was changed (your backup {bk} is safe): {e}"
    return True, ("Started fresh: the program is now empty." if mode == "empty" else "Reset to the sample data.") + f" A backup was saved first: {bk}."

def restore_backup_data(filename):
    """Put the equipment, tasks, parts, work orders and history back the way they were in a saved backup.
    Users, licence and settings are kept as they are now. A safety backup of the current data is made first.
    Returns (ok, message)."""
    if filename not in list_backups(): return False, "That backup is not in the list."
    path = os.path.join(get_backup_dir(), filename)
    try: safety = os.path.basename(backup_database())
    except Exception as e: return False, f"Backup failed, nothing was changed: {e}"
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("ATTACH DATABASE ? AS bk", (path,))
        bk_tables = {r[0] for r in conn.execute("SELECT name FROM bk.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        for t in _data_tables(conn):
            conn.execute(f'DELETE FROM main."{t}"')
            if t in bk_tables:
                have = {r[1] for r in conn.execute(f'PRAGMA bk.table_info("{t}")')}
                common = [r[1] for r in conn.execute(f'PRAGMA main.table_info("{t}")') if r[1] in have]
                if common:
                    cl = ", ".join(f'"{c}"' for c in common)
                    conn.execute(f'INSERT INTO main."{t}" ({cl}) SELECT {cl} FROM bk."{t}"')
        conn.commit()
    except sqlite3.Error as e:
        try: conn.rollback()
        except Exception: pass
        return False, f"Database error, nothing was changed (a backup of your current data, {safety}, is safe): {e}"
    finally:
        if conn is not None:
            try: conn.execute("DETACH DATABASE bk")
            except Exception: pass
            conn.close()
    return True, f"Restored the data from {filename}. A backup of the data you had just before was saved first: {safety}."

def get_backup_dir():
    return os.path.join(os.path.dirname(DB_PATH), "backups")

def list_backups():
    d = get_backup_dir()
    if not os.path.isdir(d): return []
    return sorted([f for f in os.listdir(d) if f.startswith("OunceOfPrevention_") and f.endswith(".db")], reverse=True)

def backup_database():
    """Copy the live database to a timestamped file in a 'backups' folder next to it.
    Uses SQLite's own backup API, so it is safe even while the app is running. Returns the new file's path."""
    d = get_backup_dir()
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"OunceOfPrevention_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    src_conn = _sqlite3_real.connect(DB_PATH, timeout=30.0)   # real module: backups work even in read-only mode
    dst_conn = _sqlite3_real.connect(dest)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close(); src_conn.close()
    for old in list_backups()[get_backup_keep():]:       # prune the oldest beyond the "backups to keep" setting
        try: os.remove(os.path.join(d, old))
        except OSError: pass
    return dest

def auto_backup_daily():
    """One backup per calendar day, made the first time the app runs that day. Never raises."""
    try:
        today = datetime.now().strftime("%Y%m%d")
        if any(f.startswith(f"OunceOfPrevention_{today}") for f in list_backups()): return None
        return backup_database()
    except Exception:
        return None

def log_change(action, table, key="", detail=""):
    """Add a line to the audit trail (who, when, what). Best effort: never raises and never blocks the real work."""
    try:
        if get_setting("audit_features", "0") != "1": return
        with sqlite3.connect(DB_PATH, timeout=20.0) as _c:
            _c.execute('INSERT INTO "Audit_Log" ("WhenTS","UserName","Action","TableName","RecordKey","Detail") VALUES (?,?,?,?,?,?)',
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), current_user_name() or "(login off)", str(action), str(table), str(key), str(detail)[:500]))
            _c.commit()
    except Exception:
        pass

def commit_signoff(task_id, hours, initials):
    """Record a signed-off task: add a row to Completed_Work_Orders and reset the task's
    Date_Last_Done / Meter_At_Last so it stops showing as due. Returns (ok, message)."""
    initials = (initials or "").strip()
    if not initials: return False, "Enter the technician's initials before committing."
    try: hours = float(hours)
    except (TypeError, ValueError): return False, "Hours must be a number."
    if hours < 0: return False, "Hours cannot be negative."
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            row = conn.execute('''SELECT p.AssetID, p.TaskName, p.EstimatedPartsCost, p.RequiredConsumables, t.Current_Meter
                                   FROM "Preventive_Schedules" p JOIN "Trucks" t ON p.AssetID = t.AssetID
                                   WHERE p.TaskID = ?''', (int(task_id),)).fetchone()
            if not row: return False, "That task no longer exists."
            asset_id, task_name, parts_cost, consumables, meter = row
            if conn.execute('SELECT 1 FROM "Completed_Work_Orders" WHERE AssetID = ? AND TaskName = ? AND substr(DateCompleted,1,10) = ?',
                            (asset_id, task_name, today)).fetchone():
                return False, f"{asset_id} / {task_name} was already signed off today."
            try: parts_cost = float(parts_cost or 0)
            except (TypeError, ValueError): parts_cost = 0.0
            try: meter_txt = str(int(float(meter or 0)))
            except (TypeError, ValueError): meter_txt = "0"
            conn.execute('''INSERT INTO "Completed_Work_Orders" ("AssetID","TaskName","DateCompleted","TechnicianName","LaborHours","PartsUsed","TotalCost","Notes")
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (asset_id, task_name, today, initials, hours, consumables or "", parts_cost + hours * get_labor_rate(), "Signed off in app" + (f" by {current_user_name()}" if current_user_name() else "")))
            conn.execute('UPDATE "Preventive_Schedules" SET Date_Last_Done = ?, Meter_At_Last = ? WHERE TaskID = ?', (today, meter_txt, int(task_id)))
            conn.commit()
    except sqlite3.Error as e:
        return False, f"Database error, nothing was saved: {e}"
    log_change("Task signed off", "Completed_Work_Orders", f"{asset_id} / {task_name}", f"initials {initials}, {hours:g} hrs")
    return True, f"Signed off and archived: {asset_id} / {task_name} ({today}, {initials}, {hours:g} hrs)."

def fetch_history(category, start_date, end_date, asset_ids=None):
    """Completed work orders for one asset group between two dates (inclusive), newest first."""
    q = '''SELECT substr(c.DateCompleted,1,10) AS "Date", c.AssetID AS "Asset", c.TaskName AS "Task", c.TechnicianName AS "Technician",
                    c.LaborHours AS "Hours", c.TotalCost AS "Cost", c.PartsUsed AS "Parts Used", c.Notes AS "Notes"
             FROM "Completed_Work_Orders" c JOIN "Trucks" t ON c.AssetID = t.AssetID
             WHERE t.Category = ? AND substr(c.DateCompleted,1,10) BETWEEN ? AND ?'''
    params = [category, start_date.isoformat(), end_date.isoformat()]
    if asset_ids:
        q += " AND c.AssetID IN (%s)" % ",".join("?" * len(asset_ids))
        params += list(asset_ids)
    q += ' ORDER BY c.DateCompleted DESC, c.AssetID, c.TaskName'
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        return pd.read_sql(q, conn, params=params)

def build_history_pdf(category, df, start_date, end_date, asset_ids=None):
    """Landscape PDF of completed work orders. Title, date range, asset filter and page numbers repeat on every page."""
    import io
    from xml.sax.saxutils import escape as xml_esc
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer

    page = landscape(letter)
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    assets_txt = "All assets" if not asset_ids else ", ".join(asset_ids)
    if len(assets_txt) > 60: assets_txt = f"{len(asset_ids)} assets selected"
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('hcell', parent=styles['Normal'], fontSize=8.5, leading=10.5)
    cell_r = ParagraphStyle('hcell_r', parent=cell, alignment=2)

    def draw_page_header(canvas, doc):
        w, h = page
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(30, h - 34, f"Completed Work Order History: {category}")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30, h - 47, f"Date range: {start_date} to {end_date}   |   Assets: {assets_txt}   |   Generated: {generated}")
        canvas.setLineWidth(0.75)
        canvas.line(30, h - 53, w - 30, h - 53)
        canvas.restoreState()
        draw_licensee_line(canvas)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=page, leftMargin=30, rightMargin=30, topMargin=66, bottomMargin=30)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page_header)])

    def txt(v):
        s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
        return Paragraph(xml_esc(s).replace("\n", "<br/>"), cell)
    def num(v, fmt):
        try: return Paragraph(fmt.format(float(v)), cell_r)
        except (TypeError, ValueError): return Paragraph("", cell_r)

    rows = [[Paragraph(f"<b>{h}</b>", cell_r if h in ("Hours", "Cost") else cell)
             for h in ("Date", "Asset", "Task", "Technician", "Hours", "Cost", "Notes")]]
    for _, r in df.iterrows():
        rows.append([txt(r["Date"]), txt(r["Asset"]), txt(r["Task"]), txt(r["Technician"]),
                     num(r["Hours"], "{:g}"), num(r["Cost"], "${:,.2f}"), txt(r["Notes"])])
    t = Table(rows, colWidths=[58, 62, 200, 80, 38, 58, 236], repeatRows=1)   # repeatRows=1 repeats column headers
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    hours_total = pd.to_numeric(df["Hours"], errors="coerce").fillna(0).sum()
    cost_total = pd.to_numeric(df["Cost"], errors="coerce").fillna(0).sum()
    doc.build([t, Spacer(1, 12), Paragraph(f"<b>Total:</b> {len(df)} completed work orders &nbsp;&mdash;&nbsp; {hours_total:,.1f} labor hours &nbsp;&mdash;&nbsp; ${cost_total:,.2f}", styles['Normal'])],
              canvasmaker=make_numbered_canvas())
    return buf.getvalue()

def make_numbered_canvas():
    """Returns a ReportLab canvas class that prints 'Page X of Y' on every page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages = []
        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()
        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self.setFont("Helvetica", 9)
                self.drawRightString(self._pagesize[0] - 30, self._pagesize[1] - 34, f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()
    return NumberedCanvas

def build_signoff_pdf(category, df):
    """Printable sign-off sheet (Asset/Task, Hours, Date, Tech Initials). Header and the Shop Supervisor signature line repeat on every page."""
    import io
    from xml.sax.saxutils import escape as xml_esc
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Table, TableStyle, Paragraph, Spacer

    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=9.5, leading=12)

    def draw_page_header(canvas, doc):
        w, h = letter
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(30, h - 34, f"Completed & Signed-Off Work Orders Archive: {category}")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30, h - 47, f"Date and Time Generated: {generated}")
        canvas.drawRightString(w - 30, h - 47, "(Historical Compliance Record)")
        canvas.setLineWidth(0.75)
        canvas.line(30, h - 53, w - 30, h - 53)
        # Shop Supervisor signature on every page (each page is a signed record on its own)
        canvas.setFont("Helvetica-Bold", 9.5)
        canvas.drawString(30, 40, "Shop Supervisor Signature:")
        canvas.setLineWidth(0.5)
        canvas.line(180, 40, 380, 40)
        canvas.drawString(392, 40, "Date:")
        canvas.line(424, 40, w - 30, 40)
        canvas.restoreState()
        draw_licensee_line(canvas)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=30, rightMargin=30, topMargin=66, bottomMargin=62)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page_header)])

    rows = [[Paragraph("<b>Final Signoff - each Asset.</b>", cell), Paragraph("<b>Hours</b>", cell),
             Paragraph("<b>Date</b>", cell), Paragraph("<b>Tech Initials</b>", cell)]]
    for _, r in df.iterrows():
        rows.append([Paragraph(f"<b>{xml_esc(str(r['AssetID']))}</b> &mdash; {xml_esc(str(r['TaskName']))}", cell), "", "", ""])

    # Hours / Date / Tech Initials only as wide as their headings need, so task lines rarely wrap
    t = Table(rows, colWidths=[390, 44, 46, 72], repeatRows=1)  # repeatRows=1 repeats the column header
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 1), (-1, -1), 6), ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    elements = [t]
    doc.build(elements, canvasmaker=make_numbered_canvas())
    return buf.getvalue()

# ---------------------------------------------------------------------------------------------------------------------
# Regulators: a starter list of the agencies an incident is usually reported to, by country (and province / state / region).
# Names only. Rules, deadlines and thresholds differ by place and change, so this is a starting point to confirm with your own
# regulator or safety officer. Everything here can be corrected or added to on the Incident Reports screen.
# ---------------------------------------------------------------------------------------------------------------------
# ---- Photo protection (supervisor passphrase). Standard-library only: scrypt key stretching, a keyed BLAKE2 stream, and an HMAC tag. ----
ENC_MAGIC = b"OOPENC1"
ENC_TIMEOUT_SEC = 600

def _kdf(secret, salt):
    raw = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
    return raw[:32], raw[32:]

def _keystream(ek, nonce, n):
    out = bytearray()
    for i in range((n + 63) // 64):
        out += hashlib.blake2b(nonce + i.to_bytes(8, "big"), key=ek, digest_size=64).digest()
    return bytes(out[:n])

def enc_blob(ek, mk, data):
    nonce = os.urandom(16)
    ks = _keystream(ek, nonce, len(data))
    ct = (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(data), "big") if data else b""
    body = ENC_MAGIC + nonce + ct
    return body + hmac.new(mk, body, hashlib.sha256).digest()

def dec_blob(ek, mk, blob):
    """Returns the original bytes, or raises ValueError if the key is wrong or the file was altered."""
    if len(blob) < len(ENC_MAGIC) + 16 + 32 or not blob.startswith(ENC_MAGIC): raise ValueError("not an encrypted file")
    body, tag = blob[:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(mk, body, hashlib.sha256).digest()): raise ValueError("wrong key or damaged file")
    nonce, ct = body[len(ENC_MAGIC):len(ENC_MAGIC) + 16], body[len(ENC_MAGIC) + 16:]
    ks = _keystream(ek, nonce, len(ct))
    return (int.from_bytes(ct, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(ct), "big") if ct else b""

def _norm_secret(s, recovery=False):
    s = (s or "").strip()
    return re.sub(r"[\s-]+", "", s).upper() if recovery else s

def enc_is_set_up():
    return bool(get_setting("enc_wrap_p", ""))

def enc_setup(passphrase):
    """Creates the photo key, locks it with the passphrase and with a printed recovery code. Returns the recovery code (shown once)."""
    import base64 as _b64
    dk = os.urandom(64)
    code_raw = _b64.b32encode(os.urandom(15)).decode().rstrip("=")[:24]
    code = "-".join(code_raw[i:i + 4] for i in range(0, 24, 4))
    for tag, secret in (("p", _norm_secret(passphrase)), ("r", _norm_secret(code, True))):
        salt = os.urandom(16); ek, mk = _kdf(secret, salt)
        set_setting(f"enc_salt_{tag}", salt.hex()); set_setting(f"enc_wrap_{tag}", enc_blob(ek, mk, dk).hex())
    return code

def enc_new_recovery(dk):
    """Makes a fresh recovery code for an already unlocked photo key. The old code stops working. Returns the new code (shown once)."""
    import base64 as _b64
    code_raw = _b64.b32encode(os.urandom(15)).decode().rstrip("=")[:24]
    code = "-".join(code_raw[i:i + 4] for i in range(0, 24, 4))
    salt = os.urandom(16); ek, mk = _kdf(_norm_secret(code, True), salt)
    set_setting("enc_salt_r", salt.hex()); set_setting("enc_wrap_r", enc_blob(ek, mk, dk).hex())
    return code

def enc_unlock(secret):
    """Returns the 64-byte photo key if the passphrase (or recovery code) is right, else None."""
    for tag, rec in (("p", False), ("r", True)):
        wrap, salt = get_setting(f"enc_wrap_{tag}", ""), get_setting(f"enc_salt_{tag}", "")
        if not wrap or not salt: continue
        try:
            ek, mk = _kdf(_norm_secret(secret, rec), bytes.fromhex(salt))
            return dec_blob(ek, mk, bytes.fromhex(wrap))
        except ValueError: continue
    return None

def enc_change_passphrase(dk, new_passphrase):
    salt = os.urandom(16); ek, mk = _kdf(_norm_secret(new_passphrase), salt)
    set_setting("enc_salt_p", salt.hex()); set_setting("enc_wrap_p", enc_blob(ek, mk, dk).hex())

def enc_key_now():
    """The photo key if this session has been unlocked in the last ENC_TIMEOUT_SEC seconds, else None (and locks)."""
    dk, t = st.session_state.get("inc_dk"), st.session_state.get("inc_dk_time", 0)
    if dk and time.time() - t <= ENC_TIMEOUT_SEC:
        st.session_state["inc_dk_time"] = time.time(); return dk
    st.session_state.pop("inc_dk", None); return None

# ---- One small photo per asset (printed once on the work order) ----
def asset_photo_path(asset_id, plate=False):
    """Where an asset's thumbnail lives: an 'asset_photos' folder next to the database. Does not create the file. plate=True is the optional ID-plate close-up."""
    aid = str(asset_id)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", aid).strip("_")[:40] or "asset"
    return os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "asset_photos", f"{safe}_{hashlib.md5(aid.encode('utf-8')).hexdigest()[:6]}{'_plate' if plate else ''}.jpg")

def asset_photo_exists(asset_id, plate=False):
    try: return os.path.exists(asset_photo_path(asset_id, plate))
    except Exception: return False

def save_asset_photo(asset_id, data, plate=False):
    """Shrinks any phone photo or screenshot to a small JPEG (colour for the unit photo, grayscale for the ID-plate close-up) and replaces the asset's old one."""
    from PIL import Image, ImageOps
    import io
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im = im.convert("RGB")                                   # the unit photo keeps its colour
    if plate: im = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=1)   # the ID-plate close-up stays grayscale so the model number prints crisp
    im.thumbnail((1100, 825) if plate else (640, 640))   # the plate close-up keeps more detail so the model number stays readable
    path = asset_photo_path(asset_id, plate)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "JPEG", quality=72, optimize=True)

def asset_photo_boxed(path, size=(640, 480)):
    """The photo centred in a fixed 4:3 box (standard phone shape), so every photo shows at the same size on screen."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        _k = min(size[0] / im.size[0], size[1] / im.size[1])   # scale up or down so the photo fills the box, aspect ratio kept
        im = im.resize((max(1, round(im.size[0] * _k)), max(1, round(im.size[1] * _k))), Image.LANCZOS)
        box = Image.new("RGB", size, (240, 242, 246))
        box.paste(im, ((size[0] - im.size[0]) // 2, (size[1] - im.size[1]) // 2))
    return box

def delete_asset_photo(asset_id, plate=None):
    """plate=None removes both photos; True / False removes just that one."""
    for pl in ((False, True) if plate is None else (plate,)):
        try: os.remove(asset_photo_path(asset_id, pl))
        except OSError: pass

INCIDENT_FILE_KINDS = ["Filled-out incident form", "Signed / scanned copy", "Photo of evidence", "Witness statement", "Report from an agency", "Other"]
INCIDENT_FILE_MAX_MB = 25

def incident_files_dir(incident_id):
    """Folder holding the files for one incident: an 'incident_files' folder next to the database, one subfolder per incident ID."""
    d = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "incident_files", f"INC-{int(incident_id)}")
    os.makedirs(d, exist_ok=True)
    return d

def add_incident_file(incident_id, filename, data, kind, note, dk=None):
    """Saves a file for an incident. With dk (the photo key) the file is stored encrypted."""
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", os.path.basename(filename or "file")).strip() or "file"
    stored = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}" + (".enc" if dk else "")
    with open(os.path.join(incident_files_dir(incident_id), stored), "wb") as fh: fh.write(enc_blob(dk[:32], dk[32:], data) if dk else data)
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.execute('INSERT INTO "IncidentFiles" ("IncidentID", "FileName", "StoredName", "Kind", "Note", "Uploaded", "Encrypted") VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (int(incident_id), safe, stored, kind, note, datetime.now().strftime('%Y-%m-%d %H:%M'), 1 if dk else 0))
        conn.commit()

def delete_incident_file(file_id):
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        row = conn.execute('SELECT IncidentID, StoredName FROM "IncidentFiles" WHERE FileID = ?', (int(file_id),)).fetchone()
        conn.execute('DELETE FROM "IncidentFiles" WHERE FileID = ?', (int(file_id),)); conn.commit()
    if row:
        try: os.remove(os.path.join(incident_files_dir(row[0]), row[1]))
        except OSError: pass

REG_CODES = {"I": "INJ", "N": "NEAR", "E": "ENV", "F": "FIRE", "C": "COLL", "P": "PROP", "H": "HARASS", "G": "GEN"}
INCIDENT_TYPE_CODE = {"Injury / Illness / Fatality": "INJ", "Near Miss / Hazard": "NEAR", "Environmental Release / Spill": "ENV", "Fire / Explosion": "FIRE",
                      "Vehicle / Equipment Collision": "COLL", "Property / Equipment Damage or Failure": "PROP",
                      "Harassment / Violence / Bullying (Confidential)": "HARASS", "General / Other Incident": "GEN"}
REG_DISCLAIMER = ("Starter list from general knowledge, not legal advice. Agency names, thresholds and deadlines change, and some rules depend on your industry "
                  "and whether you are federally or provincially / state regulated. Confirm with your regulator, insurer or safety officer. You can correct or add agencies below.")

def _canada_rows():
    rows = [("Canada", "Federally regulated", "Employment and Social Development Canada - Labour Program", "Federally regulated workplaces (banks, airlines, interprovincial trucking, telecom): health and safety", "I F C H"),
            ("Canada", "All", "Transportation Safety Board of Canada (TSB)", "Air, marine, rail and pipeline accidents", "C"),
            ("Canada", "All", "Transport Canada", "Transportation accidents and dangerous-goods incidents", "C E"),
            ("Canada", "Federally regulated", "Canada Energy Regulator", "Federally regulated pipelines and power lines", "I F C E"),
            ("Canada", "All", "Environment and Climate Change Canada", "Environmental emergencies (federal)", "E"),
            ("Canada", "Federally regulated", "Canadian Human Rights Commission", "Federally regulated employers: discrimination and harassment", "H")]
    prov = [  # province, workers' comp, OHS regulator (None = same body), environment, human rights
        ("Alberta", "Workers' Compensation Board - Alberta (WCB-Alberta)", "Alberta Occupational Health and Safety", "Alberta Environment and Protected Areas", "Alberta Human Rights Commission"),
        ("British Columbia", "WorkSafeBC", None, "BC Ministry of Environment and Climate Change Strategy", "BC Human Rights Tribunal"),
        ("Saskatchewan", "Saskatchewan Workers' Compensation Board", "Saskatchewan Occupational Health and Safety Division (Ministry of Labour Relations and Workplace Safety)", "Saskatchewan Ministry of Environment", "Saskatchewan Human Rights Commission"),
        ("Manitoba", "Workers Compensation Board of Manitoba", "Manitoba Workplace Safety and Health", "Manitoba Environment and Climate Change", "Manitoba Human Rights Commission"),
        ("Ontario", "Workplace Safety and Insurance Board (WSIB)", "Ontario Ministry of Labour, Immigration, Training and Skills Development", "Ontario Ministry of the Environment, Conservation and Parks (Spills Action Centre)", "Ontario Human Rights Commission"),
        ("Quebec", "CNESST (Commission des normes, de l'equite, de la sante et de la securite du travail)", None, "Quebec Ministere de l'Environnement (Urgence-Environnement)", "Commission des droits de la personne et des droits de la jeunesse"),
        ("New Brunswick", "WorkSafeNB", None, "New Brunswick Department of Environment and Local Government", "New Brunswick Human Rights Commission"),
        ("Nova Scotia", "Workers' Compensation Board of Nova Scotia", "Nova Scotia Occupational Health and Safety Division", "Nova Scotia Environment and Climate Change", "Nova Scotia Human Rights Commission"),
        ("Prince Edward Island", "Workers Compensation Board of PEI", "PEI Occupational Health and Safety", "PEI Department of Environment, Energy and Climate Action", "PEI Human Rights Commission"),
        ("Newfoundland and Labrador", "WorkplaceNL", "Newfoundland and Labrador Occupational Health and Safety Division", "NL Department of Environment and Climate Change", "NL Human Rights Commission"),
        ("Yukon", "Yukon Workers' Safety and Compensation Health and Safety Board", None, "Yukon Department of Environment", "Yukon Human Rights Commission"),
        ("Northwest Territories", "Workers' Safety and Compensation Commission (NWT and Nunavut)", None, "NWT Department of Environment and Climate Change", "NWT Human Rights Commission"),
        ("Nunavut", "Workers' Safety and Compensation Commission (NWT and Nunavut)", None, "Nunavut Department of Environment", "Nunavut Human Rights Tribunal")]
    for p, comp, ohs, env, hr in prov:
        if ohs: rows += [("Canada", p, comp, "Workers\' compensation: report a workplace injury or illness (if a worker is hurt)", "I C F"), ("Canada", p, ohs, "Occupational health and safety regulator: serious incidents, injuries, harassment and violence rules", "I F C H")]
        else: rows += [("Canada", p, comp, "Workers' compensation AND occupational health and safety regulator: injuries, serious incidents", "I F C H")]
        rows += [("Canada", p, env, "Spills and environmental releases", "E"), ("Canada", p, hr, "Discrimination and harassment complaints", "H")]
    return rows

def _australia_rows():
    st_ = [  # state, WHS regulator, workers' comp, environment, equal opportunity
        ("New South Wales", "SafeWork NSW", "icare (workers' insurance) / SIRA", "NSW Environment Protection Authority", "Anti-Discrimination NSW"),
        ("Victoria", "WorkSafe Victoria", None, "EPA Victoria", "Victorian Equal Opportunity and Human Rights Commission"),
        ("Queensland", "WorkSafe Queensland", "WorkCover Queensland", "Queensland Department of Environment, Tourism, Science and Innovation", "Queensland Human Rights Commission"),
        ("Western Australia", "WorkSafe Western Australia", "WorkCover WA", "WA Department of Water and Environmental Regulation", "WA Equal Opportunity Commission"),
        ("South Australia", "SafeWork SA", "ReturnToWorkSA", "SA Environment Protection Authority", "SA Equal Opportunity Commission"),
        ("Tasmania", "WorkSafe Tasmania", "WorkCover Tasmania", "Tasmania Environment Protection Authority", "Equal Opportunity Tasmania"),
        ("Australian Capital Territory", "WorkSafe ACT", None, "ACT Environment Protection Authority", "ACT Human Rights Commission"),
        ("Northern Territory", "NT WorkSafe", None, "NT Environment Protection Authority", "NT Anti-Discrimination Commission")]
    rows = [("Australia", "Commonwealth employer", "Comcare", "Commonwealth (federal) employees and licensed self-insurers: workers' compensation and WHS", "I F C H"),
            ("Australia", "All", "Australian Transport Safety Bureau (ATSB)", "Air, marine and rail accidents", "C"),
            ("Australia", "All", "Civil Aviation Safety Authority (CASA)", "Aviation safety", "C"),
            ("Australia", "All", "Australian Maritime Safety Authority (AMSA)", "Marine incidents", "C E"),
            ("Australia", "All", "Australian Human Rights Commission", "Discrimination and harassment", "H"),
            ("Australia", "All", "Fair Work Commission", "Workplace bullying and sexual harassment orders", "H")]
    for s, whs, comp, env, eo in st_:
        rows.append(("Australia", s, whs, "Work health and safety regulator: notifiable incidents, serious injury, death, dangerous incidents" + (" and workers' compensation" if not comp else ""), "I F C H"))
        if comp: rows.append(("Australia", s, comp, "Workers\' compensation: report a workplace injury or illness (if a worker is hurt)", "I C F"))
        rows += [("Australia", s, env, "Pollution and environmental incidents", "E"), ("Australia", s, eo, "Discrimination and harassment complaints", "H")]
    return rows

def _simple(country, items):
    """items: (agency, why, applies [, region]); region defaults to All."""
    return [(country, (it[3] if len(it) > 3 else "All"), it[0], it[1], it[2]) for it in items]

REGULATOR_SEED = (
    [("*", "All", "Police (local or national)", "If a crime, threat, serious injury or death is involved", "C H G"),
     ("*", "All", "Fire department / emergency services", "If they attended or the incident involved fire, explosion or a release", "F E"),
     ("*", "All", "Your insurance company", "Notify as your policy requires (property, liability, vehicle)", "C F P E G")]
    + _canada_rows()
    + _simple("United States", [
        ("Occupational Safety and Health Administration (OSHA)", "Work-related fatalities, hospitalizations, amputations, eye loss; also your state OSHA plan if you have one", "I F C"),
        ("State workers' compensation agency / insurer", "Report a workplace injury or illness (differs by state)", "I C F"),
        ("National Transportation Safety Board (NTSB)", "Aviation, rail, marine, highway and pipeline accidents", "C"),
        ("Federal Aviation Administration (FAA)", "Aircraft accidents and incidents", "C"),
        ("Federal Railroad Administration (FRA)", "Railroad accidents", "C"),
        ("Pipeline and Hazardous Materials Safety Administration (PHMSA)", "Pipeline and hazardous-materials incidents", "C E F"),
        ("U.S. Coast Guard", "Marine casualties and oil / chemical spills on water", "C E"),
        ("Federal Motor Carrier Safety Administration (FMCSA)", "Commercial motor vehicle crashes", "C"),
        ("Mine Safety and Health Administration (MSHA)", "Mining accidents", "I F C"),
        ("National Response Center", "Oil and hazardous-substance spills (federal reporting line)", "E"),
        ("Environmental Protection Agency (EPA) / state environmental agency", "Spills, releases and pollution", "E"),
        ("U.S. Chemical Safety Board (CSB)", "Serious industrial chemical accidents", "F E"),
        ("Bureau of Alcohol, Tobacco, Firearms and Explosives (ATF)", "Explosions and explosives incidents", "F"),
        ("Equal Employment Opportunity Commission (EEOC)", "Workplace discrimination and harassment", "H")])
    + _simple("United Kingdom", [
        ("Health and Safety Executive (HSE) - RIDDOR", "Reportable injuries, diseases and dangerous occurrences (Great Britain)", "I F C", "England;Scotland;Wales"),
        ("HSE Northern Ireland (HSENI)", "Reportable injuries and dangerous occurrences (Northern Ireland)", "I F C", "Northern Ireland"),
        ("Local authority environmental health", "Health and safety enforcement for offices, shops and hospitality", "I F"),
        ("Air Accidents Investigation Branch (AAIB)", "Aircraft accidents", "C"),
        ("Marine Accident Investigation Branch (MAIB)", "Marine accidents", "C"),
        ("Rail Accident Investigation Branch (RAIB)", "Rail accidents", "C"),
        ("Office of Rail and Road (ORR)", "Railway safety", "C I"),
        ("Environment Agency (England)", "Pollution incidents", "E", "England"),
        ("Scottish Environment Protection Agency (SEPA)", "Pollution incidents", "E", "Scotland"),
        ("Natural Resources Wales", "Pollution incidents", "E", "Wales"),
        ("Northern Ireland Environment Agency (NIEA)", "Pollution incidents", "E", "Northern Ireland"),
        ("Equality and Human Rights Commission (EHRC)", "Discrimination and harassment (Great Britain)", "H", "England;Scotland;Wales"),
        ("Equality Commission for Northern Ireland", "Discrimination and harassment (Northern Ireland)", "H", "Northern Ireland")])
    + _simple("Ireland", [
        ("Health and Safety Authority (HSA)", "Workplace accidents and dangerous occurrences", "I F C"),
        ("Department of Social Protection", "Occupational injury and illness benefit claims", "I"),
        ("Air Accident Investigation Unit (AAIU)", "Aircraft accidents", "C"),
        ("Marine Casualty Investigation Board (MCIB)", "Marine casualties", "C"),
        ("Railway Accident Investigation Unit (RAIU)", "Rail accidents", "C"),
        ("Environmental Protection Agency (EPA) / local authority", "Pollution and environmental incidents", "E"),
        ("Irish Human Rights and Equality Commission (IHREC)", "Discrimination and harassment", "H"),
        ("Workplace Relations Commission (WRC)", "Employment and equality complaints", "H")])
    + _australia_rows()
    + _simple("New Zealand", [
        ("WorkSafe New Zealand", "Notifiable work-related deaths, injuries, illnesses and incidents", "I F C"),
        ("Accident Compensation Corporation (ACC)", "Injury claims", "I"),
        ("Transport Accident Investigation Commission (TAIC)", "Air, rail and marine accidents", "C"),
        ("Civil Aviation Authority of NZ", "Aviation incidents", "C"),
        ("Maritime New Zealand", "Maritime incidents and spills", "C E"),
        ("NZ Transport Agency (Waka Kotahi)", "Road and land-transport safety", "C"),
        ("Fire and Emergency New Zealand", "Fires and hazardous-substance emergencies", "F E"),
        ("Regional council", "Pollution and spills", "E"),
        ("Environmental Protection Authority (EPA NZ)", "Hazardous substances", "E"),
        ("NZ Human Rights Commission", "Discrimination and harassment", "H"),
        ("Employment New Zealand / Employment Relations Authority", "Bullying and personal grievances", "H")])
    + _simple("Germany", [
        ("Berufsgenossenschaft / Unfallkasse (statutory accident insurance)", "Workplace accidents and occupational illness", "I C F"),
        ("State occupational safety authority (Gewerbeaufsicht / Arbeitsschutzbehorde)", "Serious workplace accidents", "I F C"),
        ("BFU - Federal Bureau of Aircraft Accident Investigation", "Aircraft accidents", "C"),
        ("BSU - Federal Bureau of Maritime Casualty Investigation", "Marine casualties", "C"),
        ("EUB - Federal Railway Accident Investigation Board", "Rail accidents", "C"),
        ("State environmental authority (Umweltbehorde)", "Spills and releases", "E"),
        ("Federal Anti-Discrimination Agency", "Discrimination and harassment", "H")])
    + _simple("France", [
        ("Inspection du travail (DREETS)", "Workplace accidents, harassment and safety", "I F C H"),
        ("Assurance Maladie - Risques professionnels (CPAM)", "Declaration of workplace accidents and occupational illness", "I"),
        ("BEA - Bureau d'Enquetes et d'Analyses (aviation)", "Aircraft accidents", "C"),
        ("BEAmer / BEA-TT", "Marine and land-transport accidents", "C"),
        ("DREAL (environment inspection)", "Industrial and environmental incidents", "E F"),
        ("Defenseur des droits", "Discrimination and harassment", "H")])
    + _simple("Netherlands", [
        ("Nederlandse Arbeidsinspectie (Inspectie SZW)", "Serious workplace accidents", "I F C"),
        ("Dutch Safety Board (Onderzoeksraad voor Veiligheid)", "Serious accidents in transport and industry", "C F"),
        ("Human Environment and Transport Inspectorate (ILT)", "Transport and environmental incidents", "C E"),
        ("Regional environment agency (Omgevingsdienst)", "Spills and releases", "E"),
        ("College voor de Rechten van de Mens", "Discrimination and harassment", "H")])
    + _simple("Switzerland", [
        ("SUVA or other accident insurer", "Occupational accidents and illness", "I C F"),
        ("Cantonal labour inspectorate / SECO", "Workplace safety", "I F C"),
        ("Swiss Transportation Safety Investigation Board (STSB)", "Aviation, rail and marine accidents", "C"),
        ("Cantonal environment office / FOEN", "Spills and releases", "E"),
        ("Cantonal equality offices / Federal Office for Gender Equality", "Discrimination and harassment (no single national body)", "H")])
    + _simple("Austria", [
        ("AUVA (accident insurance)", "Workplace accidents", "I C F"),
        ("Arbeitsinspektorat (labour inspectorate)", "Workplace safety", "I F C"),
        ("Federal Safety Investigation Authority (SUB)", "Aviation, rail and marine accidents", "C"),
        ("State environmental authority (Landesregierung)", "Spills and releases", "E"),
        ("Gleichbehandlungsanwaltschaft", "Discrimination and harassment", "H")])
    + _simple("Sweden", [
        ("Swedish Work Environment Authority (Arbetsmiljoverket)", "Serious accidents, near misses and occupational illness", "I N F C H"),
        ("Swedish Social Insurance Agency (Forsakringskassan)", "Work injury claims", "I"),
        ("Swedish Accident Investigation Authority (SHK)", "Transport accidents", "C"),
        ("County Administrative Board (Lansstyrelsen) / Swedish EPA", "Spills and releases", "E"),
        ("Equality Ombudsman (Diskrimineringsombudsmannen)", "Discrimination and harassment", "H")])
    + _simple("Norway", [
        ("Norwegian Labour Inspection Authority (Arbeidstilsynet)", "Serious accidents and workplace harassment", "I F C H"),
        ("NAV (work injury claims)", "Occupational injury claims", "I"),
        ("Norwegian Safety Investigation Authority (NSIA)", "Transport accidents", "C"),
        ("Directorate for Civil Protection (DSB)", "Fire and hazardous-substance incidents", "F E"),
        ("Norwegian Environment Agency", "Pollution and spills", "E"),
        ("Equality and Anti-Discrimination Ombud", "Discrimination and harassment", "H")])
    + _simple("Denmark", [
        ("Danish Working Environment Authority (Arbejdstilsynet)", "Serious accidents and workplace harassment", "I F C H"),
        ("Danish Labour Market Insurance (Arbejdsskadestyrelsen)", "Work injury claims", "I"),
        ("Danish Safety Investigation Authority (Havarikommissionen)", "Transport accidents", "C"),
        ("Danish Environmental Protection Agency (Miljostyrelsen)", "Pollution and spills", "E"),
        ("Danish Institute for Human Rights", "Discrimination and harassment", "H")])
    + _simple("Finland", [
        ("Regional State Administrative Agency (AVI) - occupational safety", "Serious workplace accidents", "I F C H"),
        ("Workers' compensation insurer (Finnish Workers' Compensation Center)", "Work injury claims", "I"),
        ("Safety Investigation Authority (OTKES)", "Major accidents", "C F"),
        ("ELY Centre / Finnish Environment Institute (SYKE)", "Spills and releases", "E"),
        ("Non-Discrimination Ombudsman", "Discrimination and harassment", "H")])
    + _simple("Iceland", [
        ("Administration of Occupational Safety and Health (Vinnueftirlitid)", "Workplace accidents and harassment", "I F C H"),
        ("Icelandic Health Insurance (Sjukratryggingar)", "Work injury claims", "I"),
        ("Transportation Safety Board (Rannsoknarnefnd samgongusysa)", "Transport accidents", "C"),
        ("Environment Agency of Iceland", "Pollution and spills", "E"),
        ("Centre for Gender Equality / Equality Complaints Committee", "Discrimination and harassment", "H")])
    + _simple("Spain", [
        ("Inspeccion de Trabajo y Seguridad Social", "Workplace accidents and harassment", "I F C H"),
        ("Mutua colaboradora con la Seguridad Social", "Work accident declaration (via the employer)", "I"),
        ("CIAIAC / CIAIM / CIAF (accident investigation commissions)", "Aviation, marine and rail accidents", "C"),
        ("Regional environment department / SEPRONA", "Spills and environmental offences", "E"),
        ("Defensor del Pueblo", "Rights complaints and discrimination", "H")])
    + _simple("Italy", [
        ("INAIL (workplace injury insurance)", "Workplace accidents and occupational illness", "I C F"),
        ("Ispettorato Nazionale del Lavoro / ASL", "Workplace safety and harassment", "I F C H"),
        ("ANSV - National Agency for Flight Safety / rail investigations", "Aviation and rail accidents", "C"),
        ("ARPA / ISPRA (environmental protection)", "Spills and releases", "E"),
        ("UNAR (anti-discrimination office)", "Discrimination", "H")])
    + _simple("Portugal", [
        ("Autoridade para as Condicoes do Trabalho (ACT)", "Workplace accidents and harassment", "I F C H"),
        ("Employer's workplace-accident insurer", "Work accident claims", "I"),
        ("GPIAAF (accident investigation)", "Aviation and rail accidents", "C"),
        ("Portuguese Environment Agency (APA)", "Pollution and spills", "E"),
        ("CITE / CIG (equality commissions)", "Discrimination and harassment", "H")])
    + _simple("Japan", [
        ("Labour Standards Inspection Office (Ministry of Health, Labour and Welfare)", "Workplace accidents and workers' accident compensation", "I F C"),
        ("Japan Transport Safety Board (JTSB)", "Aviation, rail and marine accidents", "C"),
        ("Fire and Disaster Management Agency / local fire department", "Fires and hazardous materials", "F E"),
        ("Ministry of the Environment / prefectural government", "Pollution and spills", "E"),
        ("Human Rights Bureau (Ministry of Justice)", "Harassment and discrimination", "H")])
    + _simple("South Korea", [
        ("Ministry of Employment and Labor (MOEL)", "Serious industrial accidents and workplace harassment", "I F C H"),
        ("Korea Workers' Compensation and Welfare Service (COMWEL)", "Work injury claims", "I"),
        ("Aviation and Railway Accident Investigation Board (ARAIB)", "Aviation and rail accidents", "C"),
        ("Ministry of Environment", "Pollution and spills", "E"),
        ("National Human Rights Commission of Korea", "Discrimination and harassment", "H")])
)

REGULATOR_URLS = {
 "Occupational Safety and Health Administration (OSHA)": "https://www.osha.gov", "National Transportation Safety Board (NTSB)": "https://www.ntsb.gov",
 "Federal Aviation Administration (FAA)": "https://www.faa.gov", "Federal Railroad Administration (FRA)": "https://railroads.dot.gov",
 "Pipeline and Hazardous Materials Safety Administration (PHMSA)": "https://www.phmsa.dot.gov", "U.S. Coast Guard": "https://www.uscg.mil",
 "Federal Motor Carrier Safety Administration (FMCSA)": "https://www.fmcsa.dot.gov", "Mine Safety and Health Administration (MSHA)": "https://www.msha.gov",
 "National Response Center": "https://nrc.uscg.mil", "Environmental Protection Agency (EPA) / state environmental agency": "https://www.epa.gov",
 "U.S. Chemical Safety Board (CSB)": "https://www.csb.gov", "Bureau of Alcohol, Tobacco, Firearms and Explosives (ATF)": "https://www.atf.gov",
 "Equal Employment Opportunity Commission (EEOC)": "https://www.eeoc.gov",
 "Transportation Safety Board of Canada (TSB)": "https://www.tsb.gc.ca", "Transport Canada": "https://tc.canada.ca", "Canada Energy Regulator": "https://www.cer-rec.gc.ca",
 "Canadian Human Rights Commission": "https://www.chrc-ccdp.gc.ca", "Environment and Climate Change Canada": "https://www.canada.ca/en/environment-climate-change.html",
 "Employment and Social Development Canada - Labour Program": "https://www.canada.ca/en/employment-social-development.html",
 "WorkSafeBC": "https://www.worksafebc.com", "Workplace Safety and Insurance Board (WSIB)": "https://www.wsib.ca",
 "Workers' Compensation Board - Alberta (WCB-Alberta)": "https://www.wcb.ab.ca", "Saskatchewan Workers' Compensation Board": "https://www.wcbsask.com",
 "Health and Safety Executive (HSE) - RIDDOR": "https://www.hse.gov.uk", "HSE Northern Ireland (HSENI)": "https://www.hseni.gov.uk",
 "Air Accidents Investigation Branch (AAIB)": "https://www.gov.uk/aaib", "Marine Accident Investigation Branch (MAIB)": "https://www.gov.uk/maib",
 "Rail Accident Investigation Branch (RAIB)": "https://www.gov.uk/raib", "Office of Rail and Road (ORR)": "https://www.orr.gov.uk",
 "Scottish Environment Protection Agency (SEPA)": "https://www.sepa.org.uk", "Natural Resources Wales": "https://naturalresources.wales",
 "Equality and Human Rights Commission (EHRC)": "https://www.equalityhumanrights.com", "Equality Commission for Northern Ireland": "https://www.equalityni.org",
 "Comcare": "https://www.comcare.gov.au", "Australian Transport Safety Bureau (ATSB)": "https://www.atsb.gov.au", "Civil Aviation Safety Authority (CASA)": "https://www.casa.gov.au",
 "Australian Maritime Safety Authority (AMSA)": "https://www.amsa.gov.au", "Australian Human Rights Commission": "https://humanrights.gov.au", "Fair Work Commission": "https://www.fwc.gov.au",
}

def _apply_regulator_urls(cursor):
    """Adds the Website column if needed and fills in home pages that are still blank. Never overwrites a link the user typed."""
    cols = [r[1] for r in cursor.execute('PRAGMA table_info("Regulators")').fetchall()]
    if "Website" not in cols: cursor.execute('ALTER TABLE "Regulators" ADD COLUMN "Website" TEXT')
    for agency, url in REGULATOR_URLS.items():
        cursor.execute('UPDATE "Regulators" SET Website = ? WHERE Agency = ? AND (Website IS NULL OR Website = \'\')', (url, agency))

def regulator_sites(country):
    """agency name -> web address for this country (and the generic rows)."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        return {a: (w or "") for a, w in conn.execute('SELECT Agency, Website FROM "Regulators" WHERE Country IN (?, \'*\')', (country,)).fetchall()}

def _seed_regulators(cursor):
    """Fills the Regulators table the first time it is empty."""
    cursor.execute('SELECT COUNT(*) FROM "Regulators"')
    if cursor.fetchone()[0] == 0:
        rows = [(c, r, a, role, ",".join(REG_CODES[ch] for ch in letters.split())) for c, r, a, role, letters in REGULATOR_SEED]
        cursor.executemany('INSERT INTO "Regulators" ("Country", "Region", "Agency", "Role", "AppliesTo") VALUES (?, ?, ?, ?, ?)', rows)

def regulator_countries():
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        names = [r[0] for r in conn.execute('SELECT DISTINCT Country FROM "Regulators" WHERE Country <> \'*\'').fetchall()]
    first = [c for c in ("Canada", "United States") if c in names]
    return first + sorted(c for c in names if c not in first) + ["Other country (not listed)"]

# Every province / state / region by country, so the Province / State box is complete even where the starter regulator list has no region-specific rows.
SUBDIVISIONS = {
 "Canada": ["Alberta", "British Columbia", "Manitoba", "New Brunswick", "Newfoundland and Labrador", "Northwest Territories", "Nova Scotia", "Nunavut", "Ontario", "Prince Edward Island", "Quebec", "Saskatchewan", "Yukon"],
 "United States": ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Puerto Rico", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"],
 "Australia": ["Australian Capital Territory", "New South Wales", "Northern Territory", "Queensland", "South Australia", "Tasmania", "Victoria", "Western Australia"],
 "United Kingdom": ["England", "Northern Ireland", "Scotland", "Wales"],
 "Ireland": ["Connacht", "Leinster", "Munster", "Ulster (Republic of Ireland part)"],
 "New Zealand": ["Auckland", "Bay of Plenty", "Canterbury", "Gisborne", "Hawke's Bay", "Manawatu-Whanganui", "Marlborough", "Nelson", "Northland", "Otago", "Southland", "Taranaki", "Tasman", "Waikato", "Wellington", "West Coast"],
 "Germany": ["Baden-Wuerttemberg", "Bavaria", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hesse", "Lower Saxony", "Mecklenburg-Western Pomerania", "North Rhine-Westphalia", "Rhineland-Palatinate", "Saarland", "Saxony", "Saxony-Anhalt", "Schleswig-Holstein", "Thuringia"],
 "Austria": ["Burgenland", "Carinthia", "Lower Austria", "Salzburg", "Styria", "Tyrol", "Upper Austria", "Vienna", "Vorarlberg"],
 "Switzerland": ["Aargau", "Appenzell Ausserrhoden", "Appenzell Innerrhoden", "Basel-Landschaft", "Basel-Stadt", "Bern", "Fribourg", "Geneva", "Glarus", "Graubuenden", "Jura", "Lucerne", "Neuchatel", "Nidwalden", "Obwalden", "Schaffhausen", "Schwyz", "Solothurn", "St. Gallen", "Thurgau", "Ticino", "Uri", "Valais", "Vaud", "Zug", "Zurich"],
 "France": ["Auvergne-Rhone-Alpes", "Bourgogne-Franche-Comte", "Brittany", "Centre-Val de Loire", "Corsica", "Grand Est", "Hauts-de-France", "Ile-de-France", "Normandy", "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire", "Provence-Alpes-Cote d'Azur", "Overseas departments and territories"],
 "Italy": ["Abruzzo", "Aosta Valley", "Apulia", "Basilicata", "Calabria", "Campania", "Emilia-Romagna", "Friuli Venezia Giulia", "Lazio", "Liguria", "Lombardy", "Marche", "Molise", "Piedmont", "Sardinia", "Sicily", "Trentino-South Tyrol", "Tuscany", "Umbria", "Veneto"],
 "Spain": ["Andalusia", "Aragon", "Asturias", "Balearic Islands", "Basque Country", "Canary Islands", "Cantabria", "Castile and Leon", "Castile-La Mancha", "Catalonia", "Extremadura", "Galicia", "La Rioja", "Madrid", "Murcia", "Navarre", "Valencia"],
 "Portugal": ["Aveiro", "Azores", "Beja", "Braga", "Braganca", "Castelo Branco", "Coimbra", "Evora", "Faro", "Guarda", "Leiria", "Lisbon", "Madeira", "Portalegre", "Porto", "Santarem", "Setubal", "Viana do Castelo", "Vila Real", "Viseu"],
 "Netherlands": ["Drenthe", "Flevoland", "Friesland", "Gelderland", "Groningen", "Limburg", "North Brabant", "North Holland", "Overijssel", "South Holland", "Utrecht", "Zeeland"],
 "Sweden": ["Blekinge", "Dalarna", "Gavleborg", "Gotland", "Halland", "Jamtland", "Jonkoping", "Kalmar", "Kronoberg", "Norrbotten", "Orebro", "Ostergotland", "Skane", "Sodermanland", "Stockholm", "Uppsala", "Varmland", "Vasterbotten", "Vasternorrland", "Vastmanland", "Vastra Gotaland"],
 "Norway": ["Agder", "Akershus", "Buskerud", "Finnmark", "Innlandet", "More og Romsdal", "Nordland", "Oslo", "Ostfold", "Rogaland", "Telemark", "Troms", "Trondelag", "Vestfold", "Vestland"],
 "Denmark": ["Capital Region", "Central Denmark", "North Denmark", "Region Zealand", "Southern Denmark"],
 "Finland": ["Central Finland", "Central Ostrobothnia", "Kainuu", "Kymenlaakso", "Lapland", "North Karelia", "North Ostrobothnia", "Northern Savonia", "Ostrobothnia", "Paijat-Hame", "Pirkanmaa", "Satakunta", "South Karelia", "Southern Ostrobothnia", "Southern Savonia", "Uusimaa", "Varsinais-Suomi", "Aland", "Kanta-Hame"],
 "Iceland": ["Capital Region", "Southern Peninsula", "Western Region", "Westfjords", "Northwest", "Northeast", "Eastern Region", "Southern Region"],
 "Japan": ["Hokkaido", "Aomori", "Iwate", "Miyagi", "Akita", "Yamagata", "Fukushima", "Ibaraki", "Tochigi", "Gunma", "Saitama", "Chiba", "Tokyo", "Kanagawa", "Niigata", "Toyama", "Ishikawa", "Fukui", "Yamanashi", "Nagano", "Gifu", "Shizuoka", "Aichi", "Mie", "Shiga", "Kyoto", "Osaka", "Hyogo", "Nara", "Wakayama", "Tottori", "Shimane", "Okayama", "Hiroshima", "Yamaguchi", "Tokushima", "Kagawa", "Ehime", "Kochi", "Fukuoka", "Saga", "Nagasaki", "Kumamoto", "Oita", "Miyazaki", "Kagoshima", "Okinawa"],
 "South Korea": ["Seoul", "Busan", "Daegu", "Incheon", "Gwangju", "Daejeon", "Ulsan", "Sejong", "Gyeonggi", "Gangwon", "North Chungcheong", "South Chungcheong", "North Jeolla", "South Jeolla", "North Gyeongsang", "South Gyeongsang", "Jeju"],
}

def regulator_regions(country):
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        vals = [r[0] for r in conn.execute('SELECT DISTINCT Region FROM "Regulators" WHERE Country = ?', (country,)).fetchall()]
    out = list(SUBDIVISIONS.get(country, []))
    for v in vals:      # extras from the regulator list, such as "Federally regulated"
        for p in str(v or "").split(";"):
            p = p.strip()
            if p and p != "All" and p not in out: out.append(p)
    return out

def regulators_for(country, region, code):
    """[(agency, role)] to report to for this country, region and incident type code: the country-wide rows, plus the rows for the chosen region, then the general ones."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        rows = conn.execute('SELECT Country, Region, Agency, Role, AppliesTo FROM "Regulators" WHERE Country IN (?, \'*\') ORDER BY (Country = \'*\'), RegID', (country,)).fetchall()
    out = []
    for c, reg, agency, role, applies in rows:
        if code not in [a.strip() for a in str(applies or "").split(",")] and "ALL" not in str(applies or ""): continue
        regs = [x.strip() for x in str(reg or "All").split(";") if x.strip()] or ["All"]
        if "All" in regs or region in regs: out.append((agency, role))
    return out

def _tick_line_count(items, width):
    """How many lines ticks_row will use for these items (mirrors its wrapping)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    x, lines = 4, 1
    for t in items:
        w = 14 + stringWidth(t, "Helvetica", 8.5) + 16
        if t == "Other:":
            if x + w + 90 > width: lines += 1
            x = width
            continue
        if x + w > width: x, lines = 4, lines + 1
        x += w
    return lines

INCIDENT_FORM_TYPES = {
    "Injury / Illness / Fatality": dict(
        blocks=[("ticks", "Type of Incident", "tick all that apply", ["Fatality", "Injury", "Lost time (missed work)", "Medical aid (doctor / hospital)", "First aid only", "Occupational illness", "Other:"]),
                ("fields", "Injury Details", [[("Number of fatalities", 100), ("Number of injuries", 100), ("Estimated days lost", 100), ("Returned to work?  (full / modified / not yet)", None)]]),
                ("persons", "Person(s) Injured or Involved", ["Name", "Job / role", "Injury and part of body", "Treatment (first aid / doctor / hospital)"], 3)],
        what="what the person was doing, what went wrong, and the conditions",
        agencies=["WCB / workers' compensation board", "OSHA", "NTSB", "Ministry of labour / OHS", "Other:"],
        attach=["Photos", "Witness statements", "Medical / first-aid record", "Equipment records", "Training records"],
        signoffs=["Completed by (signature)", "Injured person (signature, if able)", "Supervisor (signature)", "Safety / management review (signature)"]),
    "Near Miss / Hazard": dict(
        blocks=[("ticks", "Type", "tick all that apply", ["Near miss (no injury or damage)", "Unsafe condition", "Unsafe act", "Equipment defect", "Missing guard / protection", "Poor housekeeping", "Other:"]),
                ("fields", "What Could Have Happened?", [[("Worst realistic outcome", None)]]),
                ("ticks", "Potential Severity", "", ["Minor", "Serious", "Fatal / catastrophic"]),
                ("ticks", "Likelihood of It Happening Again", "", ["Unlikely", "Possible", "Likely"]),
                ("persons", "Person(s) Involved, or Who Noticed It", ["Name", "Job / role", "Where / doing what", "Contact"], 2)],
        what="what was seen or happened, and where",
        agencies=["Internal safety committee", "OSHA / OHS (if required)", "Other:"],
        attach=["Photos", "Witness statements", "Equipment records"],
        signoffs=["Completed by (signature)", "Supervisor (signature)", "Safety / management review (signature)"]),
    "Environmental Release / Spill": dict(
        blocks=[("ticks", "Type of Release", "tick all that apply", ["Oil / fuel spill", "Chemical release", "Gas / vapour release", "Wastewater / runoff", "Waste / dumping", "Dust / noise / odour", "Other:"]),
                ("ticks", "What Was Affected", "tick all that apply", ["Soil", "Water / waterway", "Air", "Drain / sewer", "Contained on site", "Left the site"]),
                ("fields", "Release Details", [[("Substance released", 200), ("Estimated quantity", 100), ("Units", 60), ("Source (equipment / tank)", None)],
                                               [("Cleanup done by", 200), ("Cleanup completed (date)", 120), ("Waste disposal method", None)]]),
                ("persons", "Person(s) Exposed or Involved (if any)", ["Name", "Job / role", "Exposure / symptoms", "Treatment"], 2)],
        what="what was released, how, and where it went",
        agencies=["Environment ministry / EPA", "Environment Canada", "Fire department", "Local authority", "Other:"],
        attach=["Photos", "Lab / sample results", "Safety data sheets", "Cleanup records", "Waste manifests"],
        signoffs=["Completed by (signature)", "Supervisor (signature)", "Environmental / safety review (signature)"]),
    "Fire / Explosion": dict(
        blocks=[("ticks", "Type of Incident", "tick all that apply", ["Fire", "Explosion", "Smoke only", "Electrical fire", "Chemical / fuel fire", "Hot work related", "Other:"]),
                ("fields", "Fire Details", [[("Fire department called?  (yes / no)", 170), ("Time called", 90), ("Extinguished by", None)],
                                            [("Alarm / sprinklers worked?  (yes / no)", 170), ("Estimated damage ($)", 110), ("Suspected cause", None)]]),
                ("persons", "Person(s) Injured or Evacuated", ["Name", "Job / role", "Injury or location", "Treatment"], 2)],
        what="where it started, how it spread, how it was put out",
        agencies=["Fire department / fire marshal", "OSHA / OHS", "Insurance company", "Other:"],
        attach=["Photos", "Fire department report", "Insurance notice", "Equipment records"],
        signoffs=["Completed by (signature)", "Supervisor (signature)", "Safety / management review (signature)"]),
    "Vehicle / Equipment Collision": dict(
        blocks=[("ticks", "Type of Incident", "tick all that apply", ["Collision with vehicle", "Collision with object / structure", "Rollover", "Struck a person", "Backing incident", "Mobile equipment / forklift", "Other:"]),
                ("fields", "Collision Details", [[("Vehicle / unit ID", 130), ("Driver / operator", 200), ("Licence / operator ticket #", None)],
                                                 [("Other party's name", 200), ("Other vehicle / plate", 150), ("Other party's insurance (company, policy #)", None)],
                                                 [("Police called?  (yes / no)", 120), ("Police file number", 150), ("Road / weather / site conditions", None)],
                                                 [("Estimated damage ($)", 110), ("Towed?  (yes / no)", 90), ("Damage description", None)]]),
                ("persons", "Person(s) Injured", ["Name", "Role (driver / passenger / other)", "Injury and part of body", "Treatment"], 2)],
        what="direction of travel, speed, what each party did, and the conditions",
        agencies=["Police", "Insurance company", "Motor vehicle authority", "WCB / workers' compensation board", "Other:"],
        attach=["Photos", "Police report", "Witness statements", "Insurance claim", "Dash-cam / video"],
        signoffs=["Completed by (signature)", "Driver / operator (signature)", "Supervisor (signature)", "Safety / management review (signature)"]),
    "Property / Equipment Damage or Failure": dict(
        blocks=[("ticks", "Type of Incident", "tick all that apply", ["Equipment failure", "Impact damage", "Water damage", "Electrical failure", "Vandalism", "Weather related", "Other:"]),
                ("fields", "Damage Details", [[("Asset ID", 120), ("Asset description", None)],
                                              [("Damage description", None)],
                                              [("Estimated repair cost ($)", 140), ("Estimated downtime (hours / days)", 170), ("Under warranty?  (yes / no)", None)]])],
        what="what failed or was damaged, and how it was found",
        agencies=["Insurance company", "Warranty / manufacturer", "Other:"],
        attach=["Photos", "Equipment records", "Repair quote", "Warranty documents"],
        signoffs=["Completed by (signature)", "Supervisor (signature)", "Maintenance review (signature)"]),
    "Harassment / Violence / Bullying (Confidential)": dict(
        note="CONFIDENTIAL.  Keep this form with the person responsible for investigations and share it only with those who need to know.",
        details=[[("Date(s) of incident", 140), ("Time", 80), ("Location", None)],
                 [("Reported by (optional)", 250), ("Received by", None)],
                 [("Date and time reported", 150), ("Person(s) the report is about", None)]],
        blocks=[("ticks", "Nature of Concern", "tick all that apply", ["Verbal abuse", "Bullying", "Discrimination", "Sexual harassment", "Threat", "Physical violence", "Cyber / online", "Retaliation", "Other:"]),
                ("persons", "People Involved", ["Name", "Role / department", "Involvement (reporter / named / witness)", "Contact"], 3)],
        what="what happened, in the person's own words; include dates and exact words where possible",
        actions="Immediate Action Taken, Support Offered, and Witnesses",
        cause=("Investigation Notes and Outcome", "Findings, decision and follow-up"),
        agencies=["Human rights commission", "OSHA / OHS", "Police", "Union representative", "Other:"],
        attach=["Written statements", "Messages / emails", "Prior reports", "Other"],
        signoffs=["Person reporting (signature, optional)", "Investigator (signature)", "Management / HR review (signature)"]),
    "General / Other Incident": dict(
        blocks=[("ticks", "Type of Incident", "tick all that apply", ["Security / trespass", "Theft", "Utility / power outage", "Customer / public incident", "Data / IT incident", "Other:"]),
                ("persons", "Person(s) Involved", ["Name", "Job / role", "Involvement", "Contact"], 3)],
        what="what happened, where, and who was affected",
        agencies=["Police", "Insurance company", "Other:"],
        attach=["Photos", "Witness statements", "Records"],
        signoffs=["Completed by (signature)", "Supervisor (signature)", "Management review (signature)"]),
}
INCIDENT_FORM_DETAILS = [[("Date of incident", 120), ("Time", 90), ("Location (site / area)", None)],
                         [("Asset involved (Asset ID and description)", 250), ("Reported by", None)],
                         [("Date and time reported", 150), ("Supervisor notified (name)", None)]]

def build_incident_form_pdf(kind="Injury / Illness / Fatality", agencies=None, jurisdiction=""):
    """Blank, two-page Incident Report form for the chosen kind of incident. Every box is a fillable PDF field (type into it) and prints with clear
    lines and boxes (write by hand). Stamped with the date and time it was generated, and ends with sign-off lines."""
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth

    spec = dict(INCIDENT_FORM_TYPES.get(kind) or INCIDENT_FORM_TYPES["General / Other Incident"])
    if agencies: spec["agencies"] = list(agencies)[:14] + ["Other:"]
    W, H = letter
    L, R = 36, W - 36
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Incident Report - {kind}")
    form = c.acroForm
    cnt = [0]
    sec = [0]
    def nm(prefix):
        cnt[0] += 1
        return f"{prefix}_{cnt[0]}"
    def txt(x, y, w, h, tip="", multi=False, size=9):
        form.textfield(name=nm("f"), tooltip=tip, x=x, y=y, width=w, height=h, fontName="Helvetica", fontSize=size,
                       borderStyle="solid" if multi else "underlined", borderWidth=0.6, borderColor=colors.black,
                       fillColor=colors.white, textColor=colors.black, forceBorder=True, fieldFlags="multiline" if multi else "")
    def box(x, y, size=10, tip=""):
        form.checkbox(name=nm("cb"), tooltip=tip, x=x, y=y, size=size, buttonStyle="check", borderWidth=0.8,
                      borderColor=colors.black, fillColor=colors.white, textColor=colors.black, forceBorder=True)
    def label(x, y, t, size=7, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size); c.setFillGray(0.25); c.drawString(x, y, t); c.setFillGray(0)
    def bar(y, title, hint=""):
        sec[0] += 1
        c.setFillGray(0.85); c.rect(L, y - 3, R - L, 14, stroke=0, fill=1); c.setFillGray(0)
        c.setFont("Helvetica-Bold", 9.5); c.drawString(L + 4, y + 1, f"{sec[0]}.  {title}")
        if hint:
            c.setFont("Helvetica-Oblique", 7.5); c.setFillGray(0.3); c.drawRightString(R - 4, y + 1, hint); c.setFillGray(0)
    def fields_rows(y, rows):
        for row in rows:
            gap = 10
            fixed = sum(w for _, w in row if w)
            free = (R - L) - fixed - gap * (len(row) - 1)
            x = L
            for cap, w in row:
                w = w if w else free
                label(x, y, cap); txt(x, y - 17, w, 15, cap)
                x += w + gap
            y -= 36
        return y
    def ticks_row(y, items):
        """Check-boxes flowing left to right and wrapping; an item called 'Other:' ends with a write-in line."""
        x = L + 4
        for t in items:
            w = 14 + stringWidth(t, "Helvetica", 8.5) + 16
            if t == "Other:":
                if x + w + 90 > R: x, y = L + 4, y - 17
                box(x, y - 2, 10, t); c.setFont("Helvetica", 8.5); c.drawString(x + 14, y + 1, t)
                txt(x + w - 6, y - 3, R - (x + w - 6), 14, "Other (describe)")
                x = R
                continue
            if x + w > R:
                x, y = L + 4, y - 17
            box(x, y - 2, 10, t); c.setFont("Helvetica", 8.5); c.drawString(x + 14, y + 1, t)
            x += w
        return y - 22
    def persons(y, caps, nrows):
        widths = [0.26, 0.19, 0.28, 0.27]
        xs, ws, x = [], [], L
        for f in widths:
            w = (R - L) * f - 6; xs.append(x); ws.append(w); x += (R - L) * f
        for x, cap in zip(xs, caps): label(x, y, cap)
        y -= 4
        for _ in range(nrows):
            for x, w in zip(xs, ws): txt(x, y - 15, w, 15, "Person")
            y -= 19
        return y - 8
    def sigline(x, y, w, cap):
        c.setLineWidth(0.6); c.line(x, y, x + w, y); label(x, y - 9, cap)
    def header(page):
        draw_licensee_line(c)
        c.setFont("Helvetica-Bold", 16); c.drawString(L, H - 46, "Incident Report")
        c.setFont("Helvetica-Bold", 9.5); c.setFillGray(0.25); c.drawString(L + 112, H - 46, f"-  {kind}"); c.setFillGray(0)
        c.setFont("Helvetica", 9); c.drawString(L, H - 59, f"Date and Time Generated: {generated}")
        c.drawRightString(R, H - 46, f"Page {page} of 2")
        label(R - 150, H - 59, "Report No.:", 8, True); txt(R - 100, H - 63, 100, 14, "Report number")
        c.setLineWidth(0.9); c.line(L, H - 68, R, H - 68)
        if jurisdiction:
            c.setFont("Helvetica", 8); c.setFillGray(0.3); c.drawRightString(R, H - 78, f"Jurisdiction: {jurisdiction}"); c.setFillGray(0)

    # ---------------- page 1 ----------------
    header(1)
    y = H - 90
    if spec.get("note"):
        c.setFont("Helvetica-Bold", 8.5); c.setFillColorRGB(0.6, 0.1, 0.1); c.drawString(L, y, spec["note"]); c.setFillGray(0); y -= 16
    bar(y, "Incident Details"); y -= 24
    y = fields_rows(y, spec.get("details") or INCIDENT_FORM_DETAILS)
    for blk in spec["blocks"]:
        if blk[0] == "ticks":
            _, title, hint, items = blk
            bar(y, title, hint); y -= 20; y = ticks_row(y, items); y -= 4
        elif blk[0] == "fields":
            _, title, rows = blk
            bar(y, title); y -= 24; y = fields_rows(y, rows)
        elif blk[0] == "persons":
            _, title, caps, nrows = blk
            bar(y, title); y -= 22; y = persons(y, caps, nrows)
    act_h = 100
    what_h = max(70, y - 188)
    bar(y, "What Happened", spec["what"]); y -= 6
    txt(L, y - what_h, R - L, what_h, "What happened", multi=True); y -= what_h + 14
    bar(y, spec.get("actions") or "Immediate Action Taken, and Witnesses (names and contact)"); y -= 6
    txt(L, y - act_h, R - L, act_h, "Immediate action and witnesses", multi=True)
    c.setFont("Helvetica-Oblique", 8); c.setFillGray(0.3); c.drawRightString(R, 46, "Continued on page 2"); c.setFillGray(0)
    c.showPage()

    # ---------------- page 2 ----------------
    header(2)
    y = H - 92
    ctitle, chint = spec.get("cause") or ("Cause and Corrective Action", "Why did it happen? (root cause)")
    bar(y, ctitle); y -= 6
    label(L, y - 8, chint, 7.5, True); y -= 10
    nsig = len(spec["signoffs"])
    fixed = 12 + 4 + 4 * 19 + 8 + 34 + 34 + 34 + 30 + 36 + nsig * 46 + 60
    ticks_extra = 17 * (_tick_line_count(spec["agencies"], R - L) - 1)
    cause_h = max(50, min(130, (y - 60) - fixed - ticks_extra))
    txt(L, y - cause_h, R - L, cause_h, "Root cause", multi=True); y -= cause_h + 12
    capx = [L, L + 330, L + 440]; capw = [324, 104, R - L - 440]
    for x, cap in zip(capx, ["Corrective action (what will be done so it does not happen again)", "Assigned to", "Due date"]): label(x, y, cap)
    y -= 4
    for _ in range(4):
        for x, w in zip(capx, capw): txt(x, y - 15, w, 15, "Corrective action")
        y -= 19
    y -= 8
    bar(y, "Reported To", "tick all that apply"); y -= 20; y = ticks_row(y, spec["agencies"]) - 2
    y = fields_rows(y, [[("Report / claim number", 170), ("Date reported", 130), ("Reported by (name)", None)]]) + 2
    bar(y, "Attachments", "tick what is attached"); y -= 20; y = ticks_row(y, spec["attach"]) - 2
    bar(y, "Sign-Off"); y -= 34
    half = (R - L - 20) / 2
    for cap in spec["signoffs"]:
        sigline(L, y, half, cap); sigline(L + half + 20, y, half, "Date"); y -= 46
    c.showPage()
    c.save()
    return buf.getvalue()

def incident_form_preview_html(kind, agencies=None, jurisdiction=""):
    """On-screen picture of the printable incident form for the chosen type: the same sections and wording as the PDF, as a plain HTML page.
    Look only; the fillable version is the PDF."""
    from html import escape as _e
    spec = dict(INCIDENT_FORM_TYPES.get(kind) or INCIDENT_FORM_TYPES["General / Other Incident"])
    if agencies: spec["agencies"] = list(agencies)[:14] + ["Other:"]
    try: company = get_company_name()
    except Exception: company = ""
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sec = [0]
    css = ("<style>.ir-page{background:#fff;color:#111;border:1px solid #b5b5b5;box-shadow:0 2px 10px rgba(0,0,0,.28);padding:26px 32px 30px;margin:6px auto 22px;max-width:900px;"
           "font-family:Helvetica,Arial,sans-serif;font-size:13px;line-height:1.3}"
           ".ir-co{font-size:11px;font-weight:700;color:#444}.ir-top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #111;padding-bottom:6px;margin-bottom:8px}"
           ".ir-title{font-size:25px;font-weight:700}.ir-type{font-size:14px;font-weight:700;color:#444;margin-left:8px}.ir-stamp{font-size:12px}"
           ".ir-pg{text-align:right;font-size:12px}.ir-rep{display:flex;align-items:flex-end;gap:6px;font-weight:700;font-size:11px;margin-top:6px}"
           ".ir-rep span{display:inline-block;width:110px;border-bottom:1px solid #111;height:14px}"
           ".ir-bar{background:#dcdcdc;font-weight:700;font-size:14px;padding:3px 7px;margin:14px 0 8px;display:flex;justify-content:space-between}"
           ".ir-hint{font-weight:400;font-style:italic;font-size:11px;color:#555}"
           ".ir-row{display:flex;gap:12px;margin-bottom:9px}.ir-f{min-width:0}.ir-cap{font-size:10.5px;color:#444;margin-bottom:1px}.ir-line{border-bottom:1.5px solid #111;height:20px}"
           ".ir-ticks{margin:0 0 8px 4px;line-height:2.1}.ir-it{display:inline-block;margin-right:20px;white-space:nowrap}"
           ".ir-cb{display:inline-block;width:12px;height:12px;border:1.5px solid #111;margin-right:6px;vertical-align:-2px}"
           ".ir-oth{display:inline-block;width:190px;border-bottom:1.5px solid #111;height:14px;margin-left:5px}"
           ".ir-box{border:1.5px solid #111;margin-bottom:6px}.ir-note{color:#9b1c1c;font-weight:700;font-size:12px;margin:2px 0 4px}"
           ".ir-sig{display:flex;gap:26px;margin-top:26px}.ir-sig div{flex:1;border-top:1.5px solid #111;font-size:10.5px;color:#444;padding-top:2px}"
           ".ir-foot{font-size:10px;color:#666;margin-top:14px}</style>")
    def bar(title, hint=""):
        sec[0] += 1
        return f"<div class='ir-bar'><span>{sec[0]}.&nbsp; {_e(title)}</span><span class='ir-hint'>{_e(hint)}</span></div>"
    def fields(rows):
        out = ""
        for row in rows:
            out += "<div class='ir-row'>" + "".join(f"<div class='ir-f' style='flex:{w or 300} 1 0'><div class='ir-cap'>{_e(cap)}</div><div class='ir-line'></div></div>" for cap, w in row) + "</div>"
        return out
    def ticks(items):
        out = "<div class='ir-ticks'>"
        for t in items:
            out += f"<span class='ir-it'><span class='ir-cb'></span>{_e(t)}" + ("<span class='ir-oth'></span>" if t == "Other:" else "") + "</span>"
        return out + "</div>"
    def persons(caps, n):
        widths = [26, 19, 28, 27]
        out = "<div class='ir-row' style='margin-bottom:2px'>" + "".join(f"<div class='ir-f ir-cap' style='flex:{w} 1 0'>{_e(c)}</div>" for c, w in zip(caps, widths)) + "</div>"
        for _ in range(n):
            out += "<div class='ir-row' style='margin-bottom:4px'>" + "".join(f"<div class='ir-f' style='flex:{w} 1 0'><div class='ir-line'></div></div>" for w in widths) + "</div>"
        return out
    def box(h): return f"<div class='ir-box' style='height:{h}px'></div>"
    def head(page):
        co = f"<div class='ir-co'>{_e(company)}</div>" if company else ""
        return (f"{co}<div class='ir-top'><div><span class='ir-title'>Incident Report</span><span class='ir-type'>{_e(kind)}</span>"
                f"<div class='ir-stamp'>Date and Time Generated: {stamp}</div></div>"
                f"<div><div class='ir-pg'>Page {page} of 2</div><div class='ir-rep'>Report No.:<span></span></div></div></div>"
                + (f"<div class='ir-foot' style='text-align:right;margin:-4px 0 4px'>Jurisdiction: {_e(jurisdiction)}</div>" if jurisdiction else ""))
    # page 1
    p1 = head(1)
    if spec.get("note"): p1 += f"<div class='ir-note'>{_e(spec['note'])}</div>"
    p1 += bar("Incident Details") + fields(spec.get("details") or INCIDENT_FORM_DETAILS)
    for blk in spec["blocks"]:
        if blk[0] == "ticks": p1 += bar(blk[1], blk[2]) + ticks(blk[3])
        elif blk[0] == "fields": p1 += bar(blk[1]) + fields(blk[2])
        elif blk[0] == "persons": p1 += bar(blk[1]) + persons(blk[2], blk[3])
    p1 += bar("What Happened", spec["what"]) + box(190)
    p1 += bar(spec.get("actions") or "Immediate Action Taken, and Witnesses (names and contact)") + box(110)
    p1 += "<div class='ir-foot'>Continued on page 2</div>"
    # page 2
    ctitle, chint = spec.get("cause") or ("Cause and Corrective Action", "Why did it happen? (root cause)")
    p2 = head(2) + bar(ctitle) + f"<div class='ir-cap' style='font-weight:700'>{_e(chint)}</div>" + box(110)
    p2 += ("<div class='ir-row' style='margin-bottom:2px'><div class='ir-f ir-cap' style='flex:60 1 0'>Corrective action (what will be done so it does not happen again)</div>"
           "<div class='ir-f ir-cap' style='flex:19 1 0'>Assigned to</div><div class='ir-f ir-cap' style='flex:17 1 0'>Due date</div></div>")
    for _ in range(3):
        p2 += "<div class='ir-row' style='margin-bottom:4px'><div class='ir-f' style='flex:60 1 0'><div class='ir-line'></div></div><div class='ir-f' style='flex:19 1 0'><div class='ir-line'></div></div><div class='ir-f' style='flex:17 1 0'><div class='ir-line'></div></div></div>"
    p2 += bar("Reported To", "tick all that apply") + ticks(spec["agencies"]) + fields([[("Report / claim number", 170), ("Date reported", 130), ("Reported by (name)", None)]])
    p2 += bar("Attachments", "tick what is attached") + ticks(spec["attach"])
    p2 += bar("Sign-Off")
    for cap in spec["signoffs"]:
        p2 += f"<div class='ir-sig'><div style='flex:3'>{_e(cap)}</div><div style='flex:1.4'>Date</div></div>"
    p2 += f"<div class='ir-foot'>Licensed to: {_e(LICENSED_TO)}</div>"
    return css + f"<div class='ir-page'>{p1}</div><div class='ir-page'>{p2}</div>"

def build_checklist_pdf(category, units):
    """Build a printable daily checklist PDF. units = [{"AssetID", "Model", "Meter", "df"}, ...]
    Each unit starts on a new page. Title/date/page numbers repeat on every page."""
    import io
    from xml.sax.saxutils import escape as xml_esc
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak, Flowable)

    class UnitMarker(Flowable):
        """Zero-size flowable: records which unit is on the current page for the page header."""
        def __init__(self, label):
            super().__init__()
            self.label = label
        def wrap(self, aw, ah): return (0, 0)
        def draw(self): self.canv._unit_label = self.label

    class CheckBox(Flowable):
        def __init__(self, size=11):
            super().__init__()
            self.size = size
            self.hAlign = 'CENTER'
        def wrap(self, aw, ah): return (self.size, self.size)
        def draw(self):
            self.canv.setLineWidth(0.9)
            self.canv.rect(0, 0, self.size, self.size)

    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today_name = today_weekday_name()
    styles = getSampleStyleSheet()
    item_style = ParagraphStyle('item', parent=styles['Normal'], fontSize=9.5, leading=12)

    def draw_page_header(canvas, doc):
        w, h = letter
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(30, h - 34, f"Daily Inspection Checklist: {category}")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30, h - 47, f"Date and Time Generated: {generated}")
        unit_label = getattr(canvas, "_unit_label", "")
        if unit_label:
            canvas.drawRightString(w - 30, h - 47, unit_label[:70])
        canvas.setLineWidth(0.75)
        canvas.line(30, h - 53, w - 30, h - 53)
        canvas.restoreState()
        draw_licensee_line(canvas)

    def clean(v):
        s = "" if v is None else str(v).strip()
        return "" if s in ("", "[ N/A ]", "nan", "None") else s

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=30, rightMargin=30, topMargin=66, bottomMargin=30)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPageEnd=draw_page_header)])

    elements = []
    for n, u in enumerate(units):
        if n > 0: elements.append(PageBreak())
        aid, model = str(u["AssetID"]), str(u["Model"])
        elements.append(UnitMarker(f"Unit: {aid} - {model}"))
        elements.append(Paragraph(
            f"<b>Unit ID#:</b> {xml_esc(aid)} &nbsp;&nbsp; <b>Model:</b> {xml_esc(model)} &nbsp;&nbsp; "
            f"<b>Last Recorded Kms/Hrs:</b> {xml_esc(str(u['Meter']))}", styles['Normal']))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(
            "<b>Inspector:</b> _______________________ &nbsp;&nbsp; <b>Date:</b> _______________ &nbsp;&nbsp; "
            "<b>Current Kms/Hrs:</b> _______________", styles['Normal']))
        elements.append(Spacer(1, 12))

        rows = [[Paragraph("<b>OK</b>", item_style), Paragraph("<b>Inspection Item</b>", item_style),
                 Paragraph("<b>OK</b>", item_style), Paragraph("<b>Inspection Item</b>", item_style)]]
        due_cells = []
        def item_para(label, day):
            if not label: return ""
            if day == today_name:   # weekly item due today: bold + underlined + shaded, so it cannot be skipped
                return Paragraph(f"<b><u>{xml_esc(label)}</u></b> <b>&nbsp;&gt;&gt; DUE TODAY ({day.upper()})</b>", item_style)
            if day != "Daily":
                return Paragraph(f"{xml_esc(label)} <font size=7.5 color='#555555'>({day} item)</font>", item_style)
            return Paragraph(xml_esc(label), item_style)
        for _, r in u["df"].iterrows():
            l1, l2 = clean(r.get("ItemLabel1")), clean(r.get("ItemLabel2"))
            if not l1 and not l2: continue
            d1, d2 = normalize_day(r.get("Day1")) or "Daily", normalize_day(r.get("Day2")) or "Daily"
            ri = len(rows)
            if l1 and d1 == today_name: due_cells += [(0, ri), (1, ri)]
            if l2 and d2 == today_name: due_cells += [(2, ri), (3, ri)]
            rows.append([CheckBox() if l1 else "", item_para(l1, d1), CheckBox() if l2 else "", item_para(l2, d2)])
        t = Table(rows, colWidths=[28, 248, 28, 248], repeatRows=1)  # repeatRows=1 repeats the column header
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ] + [('BACKGROUND', c, c, colors.HexColor('#d9f2d9')) for c in due_cells]))
        elements.append(t)
        elements.append(Spacer(1, 14))
        elements.append(Paragraph("<b>Defects / Notes:</b>", styles['Normal']))
        notes = Table([[""]] * 3, colWidths=[doc.width], rowHeights=[22] * 3)
        notes.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.black)]))
        elements.append(notes)
        elements.append(Spacer(1, 22))
        sig = Table([[Paragraph("<b>Inspector Signature:</b>", styles['Normal']), "", Paragraph("<b>Supervisor:</b>", styles['Normal']), ""]],
                    colWidths=[110, 160, 70, 160])
        sig.setStyle(TableStyle([('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black), ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
                                 ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]))
        elements.append(sig)

    doc.build(elements, canvasmaker=make_numbered_canvas())
    return buf.getvalue()

def build_group_checklist_pdf(category, units, max_units_per_sheet=10):
    """One compact landscape daily sheet for a whole asset group: items down the side, units across the top,
    a tick box where a unit has that item. Same units = [{"AssetID","Model","Meter","df"}, ...] as build_checklist_pdf.
    Groups with more than max_units_per_sheet units are split into several sheets of that many units each."""
    import io
    from xml.sax.saxutils import escape as xml_esc
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak, Flowable)

    class CheckBox(Flowable):
        def __init__(self, size=11):
            super().__init__(); self.size = size; self.hAlign = 'CENTER'
        def wrap(self, aw, ah): return (self.size, self.size)
        def draw(self):
            self.canv.setLineWidth(0.9); self.canv.rect(0, 0, self.size, self.size)

    def clean(v):
        s = "" if v is None else str(v).strip()
        return "" if s in ("", "[ N/A ]", "nan", "None") else s

    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today_name = today_weekday_name()
    styles = getSampleStyleSheet()
    item_style = ParagraphStyle('gitem', parent=styles['Normal'], fontSize=9, leading=11)
    head_style = ParagraphStyle('ghead', parent=styles['Normal'], fontSize=8, leading=9.5, alignment=1)
    small = ParagraphStyle('gsmall', parent=styles['Normal'], fontSize=8, leading=10)
    page_w, page_h = landscape(letter)

    def draw_page_header(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(30, page_h - 34, f"Daily Inspection Checklist (Group Sheet): {category}")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30, page_h - 47, f"Date and Time Generated: {generated}")
        canvas.setLineWidth(0.75)
        canvas.line(30, page_h - 53, page_w - 30, page_h - 53)
        canvas.restoreState()
        draw_licensee_line(canvas)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=landscape(letter), leftMargin=30, rightMargin=30, topMargin=66, bottomMargin=30)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPageEnd=draw_page_header)])

    def item_para(label, day):
        if day == today_name:
            return Paragraph(f"<b><u>{xml_esc(label)}</u></b> <b>&gt;&gt; DUE TODAY ({day.upper()})</b>", item_style)
        if day != "Daily":
            return Paragraph(f"{xml_esc(label)} <font size=7 color='#555555'>({day} item)</font>", item_style)
        return Paragraph(xml_esc(label), item_style)

    elements = []
    chunks = [units[i:i + max_units_per_sheet] for i in range(0, len(units), max_units_per_sheet)] or [[]]
    for ci, chunk in enumerate(chunks):
        if ci > 0: elements.append(PageBreak())
        # Items: union across the units on this sheet, in order of first appearance.
        order, day_of, has = [], {}, {}
        for ui, u in enumerate(chunk):
            for _, r in u["df"].iterrows():
                for n in (1, 2):
                    lab = clean(r.get(f"ItemLabel{n}"))
                    if not lab: continue
                    key = lab.lower()
                    if key not in day_of:
                        order.append((key, lab)); day_of[key] = normalize_day(r.get(f"Day{n}")) or "Daily"
                    has.setdefault(key, set()).add(ui)
        if len(chunks) > 1:
            elements.append(Paragraph(f"<b>Sheet {ci + 1} of {len(chunks)}</b> &nbsp; (units {chunk[0]['AssetID']} to {chunk[-1]['AssetID']})", styles['Normal']))
            elements.append(Spacer(1, 4))
        elements.append(Paragraph("<b>Inspector:</b> _______________________ &nbsp;&nbsp; <b>Date:</b> _______________ &nbsp;&nbsp; "
                                  "<b>Shift:</b> _______________", styles['Normal']))
        elements.append(Spacer(1, 8))

        nu = max(1, len(chunk))
        item_w = 230
        unit_w = min(60, (doc.width - item_w) / nu)
        header = [Paragraph("<b>Inspection Item</b>", item_style)] + [Paragraph(f"<b>{xml_esc(str(u['AssetID']))}</b>", head_style) for u in chunk]
        rows, due_rows, grey_cells = [header], [], []
        for key, lab in order:
            ri = len(rows)
            if day_of[key] == today_name: due_rows.append(ri)
            row = [item_para(lab, day_of[key])]
            for ui in range(len(chunk)):
                if ui in has[key]: row.append(CheckBox())
                else:
                    row.append(""); grey_cells.append((ui + 1, ri))
            rows.append(row)
        rows.append([Paragraph("<b>Current Kms/Hrs</b>", item_style)] + [""] * len(chunk))
        rows.append([Paragraph("<b>Initials</b>", item_style)] + [""] * len(chunk))
        row_heights = [None] + [None] * len(order) + [26, 26]
        t = Table(rows, colWidths=[item_w] + [unit_w] * len(chunk), rowHeights=row_heights, repeatRows=1)
        style = [('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                 ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
                 ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                 ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                 ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
        style += [('BACKGROUND', (0, r), (-1, r), colors.HexColor('#d9f2d9')) for r in due_rows]
        style += [('BACKGROUND', (c, r), (c, r), colors.HexColor('#e6e6e6')) for c, r in grey_cells]
        t.setStyle(TableStyle(style))
        elements.append(t)
        elements.append(Spacer(1, 8))
        # Legend: unit ID -> model
        legend = [Paragraph(f"<b>{xml_esc(str(u['AssetID']))}</b> {xml_esc(str(u['Model']))}", small) for u in chunk]
        half = (len(legend) + 1) // 2
        left, right = legend[:half], legend[half:]
        lrows = [[left[i], right[i] if i < len(right) else ""] for i in range(len(left))]
        if lrows:
            lt = Table(lrows, colWidths=[doc.width / 2] * 2)
            lt.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
            elements.append(lt)
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>Defects / Notes (write the unit ID):</b>", styles['Normal']))
        notes = Table([[""]] * 2, colWidths=[doc.width], rowHeights=[20] * 2)
        notes.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.black)]))
        elements.append(notes)
        elements.append(Spacer(1, 12))
        sig = Table([[Paragraph("<b>Inspector Signature:</b>", styles['Normal']), "", Paragraph("<b>Supervisor:</b>", styles['Normal']), ""]],
                    colWidths=[110, 200, 70, 200])
        sig.setStyle(TableStyle([('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black), ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
                                 ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]))
        elements.append(sig)

    doc.build(elements, canvasmaker=make_numbered_canvas())
    return buf.getvalue()

def new_checklist_items(orig_df, edited_df):
    """Items the user ADDED on a unit's checklist (a new row, or a blank slot that was filled in).
    Reworded existing items are edits and are NOT returned, so they stay with that one unit.
    Rows are matched by their index. Returns [(label, day), ...]."""
    def clean(v):
        t = "" if v is None else str(v).strip()
        return "" if t in _CHK_PLACEHOLDERS else t
    added = []
    for idx, row in edited_df.iterrows():
        for n in (1, 2):
            lab = clean(row.get(f"ItemLabel{n}"))
            if not lab: continue
            old = clean(orig_df.at[idx, f"ItemLabel{n}"]) if idx in orig_df.index and f"ItemLabel{n}" in orig_df.columns else ""
            if old: continue          # there was already an item in this slot: it was an edit (or unchanged)
            added.append((lab, normalize_day(row.get(f"Day{n}")) or "Daily"))
    return added

def add_items_to_other_units(category, source_aid, items):
    """Give each new item to every OTHER unit in the asset group that does not already have it.
    Units with no saved checklist start from the group's default items. Returns the number of units changed."""
    if not items: return 0
    changed = 0
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        rows = conn.execute('SELECT AssetID, Checklist_Data_V2 FROM "Trucks" WHERE Category = ? AND AssetID <> ?', (category, source_aid)).fetchall()
        for aid, js in rows:
            try: recs = json.loads(js) if js else []
            except Exception: recs = []
            labs = [str(r.get(f"ItemLabel{n}", "")).strip() for r in recs for n in (1, 2)]
            if not recs or all(x in _CHK_PLACEHOLDERS for x in labs):
                recs = get_default_checklist_df(category).to_dict(orient="records")
            have = {str(r.get(f"ItemLabel{n}", "")).strip().lower() for r in recs for n in (1, 2)}
            touched = False
            for lab, day in items:
                if lab.lower() in have: continue
                placed = False
                for r in recs:
                    for n in (1, 2):
                        if str(r.get(f"ItemLabel{n}", "")).strip() in _CHK_PLACEHOLDERS:
                            r[f"ItemLabel{n}"] = lab; r[f"Day{n}"] = day; r[f"ChK{n}"] = False
                            placed = True; break
                    if placed: break
                if not placed:
                    recs.append({"ChK1": False, "ItemLabel1": lab, "Day1": day, "ChK2": False, "ItemLabel2": "[ N/A ]", "Day2": "Daily"})
                have.add(lab.lower()); touched = True
            if touched:
                conn.execute('UPDATE "Trucks" SET Checklist_Data_V2 = ? WHERE AssetID = ?', (json.dumps(recs), aid)); changed += 1
        conn.commit()
    return changed

def _chk_step(where):
    """Checklists navigation buttons (first / previous / next / last unit). Runs as a button callback, i.e. BEFORE the
    page is redrawn, so it may set the Select Unit ID box directly."""
    opts = st.session_state.get("chk_asset_opts") or []
    if not opts: return
    cur = st.session_state.get("chk_unit_idx", 0)
    new = {"first": 0, "prev": max(0, cur - 1), "next": min(len(opts) - 1, cur + 1), "last": len(opts) - 1}[where]
    st.session_state.chk_unit_idx = new
    st.session_state["chk_asset_selector"] = opts[new]

def duplicate_asset(source_asset_id):
    demo_cap_gate(1)
    new_id = f"{source_asset_id}-C{str(int(time.time()))[-4:]}"
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM "Trucks" WHERE AssetID = ?', (source_asset_id,))
        row = cursor.fetchone()
        if not row: return None
        row_dict = dict(row)
        row_dict['AssetID'], row_dict['Year_Make_Model'], row_dict['SerialNumber'] = new_id, f"[COPY] {row_dict.get('Year_Make_Model', '')}", f"SN-{new_id}"
        cols, vals = ", ".join([f'"{k}"' for k in row_dict.keys()]), ", ".join(["?"] * len(row_dict))
        cursor.execute(f'INSERT INTO "Trucks" ({cols}) VALUES ({vals})', list(row_dict.values()))
        tables_pks = {"Preventive_Schedules": "TaskID", "Asset_Attributes": "AttrID", "Asset_Parts": "PartID", "Asset_Components": "ComponentID"}
        for tbl, pk in tables_pks.items():
            cursor.execute(f'SELECT * FROM "{tbl}" WHERE AssetID = ?', (source_asset_id,))
            for r in cursor.fetchall():
                r_dict = dict(r)
                r_dict['AssetID'] = new_id
                if pk in r_dict: del r_dict[pk]
                c, v = ", ".join([f'"{k}"' for k in r_dict.keys()]), ", ".join(["?"] * len(r_dict))
                cursor.execute(f'INSERT INTO "{tbl}" ({c}) VALUES ({v})', list(r_dict.values()))
        conn.commit()
        return new_id


def sample_asset_ids():
    """The AssetIDs the built-in sample data creates (and no others)."""
    return [f"{prefix}-{i:02d}" for cat, prefix in SAMPLE_CAT_PREFIXES.items() for i in range(1, SAMPLE_UNIT_COUNT.get(cat, 5) + 1)]

def staggered_values(key, days_between, meter_between, current_meter, today=None):
    """Believable 'last done' values for demo data, the same every time for the same key.
    About 85% of tasks are comfortably in date, 11% are due within the week, 1.5% are due today and 2.5% are overdue.
    Returns (Date_Last_Done ISO text, Meter_At_Last as int or None to leave the meter alone)."""
    import zlib
    today = today or datetime.now().date()
    u = (zlib.crc32(key.encode()) % 10000) / 10000.0
    v = (zlib.crc32((key + "#2").encode()) % 10000) / 10000.0
    cat = "ok" if u < 0.85 else "soon" if u < 0.96 else "today" if u < 0.975 else "over"
    D, M = int(days_between or 0), float(meter_between or 0)
    if D > 0:
        if cat == "ok": dl = D if D <= 8 else 8 + int((D - 8) * v); elapsed = D - dl
        elif cat == "soon": elapsed = D - min(D, 1 + int(6 * v))
        elif cat == "today": elapsed = D
        else: elapsed = D + 1 + int(v * min(max(D * 0.25, 3), 30))
        frac = elapsed / D
        frac = min(frac, 0.85) if cat == "ok" else min(frac, 0.99) if cat == "soon" else frac
        frac = 1.0 if cat == "today" else min(frac, 1.3)
    else:
        elapsed = 0
        frac = {"ok": 0.05 + 0.8 * v, "soon": 0.91 + 0.08 * v, "today": 1.0, "over": 1.01 + 0.2 * v}[cat]
    last = today - _timedelta(days=elapsed)
    meter_last = max(0, int(round(float(current_meter or 0) - frac * M))) if M > 0 else None
    return last.isoformat(), meter_last

def stagger_task_dates(cursor, asset_ids=None, today=None):
    """Reset Date_Last_Done / Meter_At_Last on tasks to the staggered demo values. Returns how many tasks were changed."""
    q = '''SELECT p.TaskID, p.AssetID, p.TabGroup, p.TaskName, p.Days_Between, p.Meter_Between, t.Current_Meter
           FROM "Preventive_Schedules" p JOIN "Trucks" t ON p.AssetID = t.AssetID'''
    params = []
    if asset_ids is not None:
        ids = list(asset_ids)
        if not ids: return 0
        q += " WHERE p.AssetID IN (%s)" % ",".join("?" * len(ids)); params = ids
    n = 0
    for tid, aid, tab, name, days_b, meter_b, cur in cursor.execute(q, params).fetchall():
        last, mlast = staggered_values(f"{aid}|{tab}|{name}", _to_float(days_b), _to_float(meter_b), _to_float(cur), today)
        if mlast is None: cursor.execute('UPDATE "Preventive_Schedules" SET Date_Last_Done = ? WHERE TaskID = ?', (last, tid))
        else: cursor.execute('UPDATE "Preventive_Schedules" SET Date_Last_Done = ?, Meter_At_Last = ? WHERE TaskID = ?', (last, str(mlast), tid))
        n += 1
    return n

# (part number, description, bin, supplier, on hand, reorder at, order qty, unit cost). A few sit at or below their reorder point on purpose,
# so the Reorder List has something to show.
SAMPLE_PARTS = {
    PART_GENERAL: [("GEN-OIL-15W40", "Engine oil 15W-40, 20 L pail", "Shelf A1", "Northern Lubricants", 8, 4, 8, 96.00),
                   ("GEN-GREASE-EP2", "EP2 grease cartridge, 400 g", "Shelf A2", "Northern Lubricants", 24, 12, 24, 5.25),
                   ("GEN-FAST-KIT", "Assorted nuts, bolts & washers kit", "Bin B1", "Prairie Fastener", 3, 2, 4, 64.00),
                   ("GEN-RAGS-BOX", "Shop rags, 10 lb box", "Shelf A4", "Prairie Fastener", 2, 2, 6, 18.50)],
    "Vehicles": [("VEH-OF-1042", "Engine oil filter, 6.7 L diesel", "Shelf C1", "Fleet Parts Depot", 10, 4, 10, 18.75),
                 ("VEH-FF-2210", "Fuel filter / water separator", "Shelf C1", "Fleet Parts Depot", 3, 4, 8, 32.40),
                 ("VEH-BRK-5530", "Brake lining set, drive axle", "Rack C3", "Fleet Parts Depot", 2, 1, 2, 210.00)],
    "Mining": [("MIN-BKT-TOOTH", "Bucket tooth, heavy duty", "Rack D1", "Western Wear Parts", 12, 6, 12, 85.00),
               ("MIN-HYD-HOSE", "Hydraulic hose assembly, 1 in. x 2 m", "Rack D2", "Western Wear Parts", 4, 2, 4, 145.00),
               ("MIN-TRK-PAD", "Track pad, 600 mm", "Yard Y1", "Western Wear Parts", 0, 4, 8, 310.00)],
    "Marine": [("MAR-ANODE-ZN", "Zinc anode, hull", "Locker M1", "Harbour Marine Supply", 8, 4, 8, 22.00),
               ("MAR-IMP-8800", "Raw-water pump impeller", "Locker M1", "Harbour Marine Supply", 2, 2, 4, 48.00),
               ("MAR-FF-3105", "Marine fuel filter element", "Locker M2", "Harbour Marine Supply", 6, 3, 6, 26.50)],
    "Aircraft": [("AIR-OF-48108", "Engine oil filter, piston aircraft", "Cage 1", "Aero Supply Co.", 6, 3, 6, 24.00),
                 ("AIR-SP-REM37", "Spark plug, massive electrode", "Cage 1", "Aero Supply Co.", 8, 6, 12, 38.00),
                 ("AIR-ELT-BATT", "ELT battery pack", "Cage 2", "Aero Supply Co.", 1, 1, 2, 160.00)],
    "Drilling Rigs": [("DRL-MP-LINER", "Mud pump liner", "Rack R1", "Rigsite Supply", 4, 2, 4, 420.00),
                      ("DRL-MP-VALVE", "Mud pump valve & seat set", "Rack R1", "Rigsite Supply", 3, 3, 6, 180.00),
                      ("DRL-WL-CLAMP", "Wire rope clip set", "Bin R4", "Rigsite Supply", 12, 6, 12, 9.50)],
    "Thermal Plant": [("THP-GSKT-SW", "Spiral wound gasket, 6 in.", "Rack P1", "Plant Industrial", 10, 4, 10, 17.00),
                      ("THP-VALVE-PK", "Valve packing set, graphite", "Rack P1", "Plant Industrial", 6, 3, 6, 21.50),
                      ("THP-SENS-RTD", "RTD temperature sensor", "Cabinet P3", "Plant Industrial", 2, 2, 4, 95.00)],
    "HVAC & Boilers": [("HVC-FLT-20X25", "Pleated air filter 20x25x4", "Rack H1", "Climate Supply", 24, 12, 24, 14.00),
                       ("HVC-BELT-B68", "V-belt B68", "Rack H1", "Climate Supply", 4, 2, 4, 16.50),
                       ("HVC-IGN-ELEC", "Boiler ignition electrode", "Cabinet H2", "Climate Supply", 1, 2, 4, 42.00)],
    "Pumps/Compressors": [("PMP-SEAL-MECH", "Mechanical seal, 1.5 in.", "Rack M1", "Flowline Industrial", 3, 2, 4, 130.00),
                          ("PMP-BRG-6309", "Bearing 6309-2RS", "Rack M1", "Flowline Industrial", 6, 4, 8, 19.00),
                          ("CMP-OF-AIR", "Compressor air/oil separator element", "Rack M2", "Flowline Industrial", 2, 2, 3, 175.00)],
    "Agriculture": [("AGR-KNIFE-SEC", "Sickle section, combine header", "Shed G1", "Farm Parts Direct", 40, 20, 40, 3.20),
                    ("AGR-CHAIN-RC", "Roller chain #60, 10 ft", "Shed G1", "Farm Parts Direct", 5, 3, 6, 38.00),
                    ("AGR-TINE-BALE", "Baler pickup tine", "Shed G2", "Farm Parts Direct", 30, 20, 40, 2.10)],
    "Cranes & Hoists": [("CRN-WIRE-ROPE", "Hoist wire rope, per metre", "Rack N1", "Lift & Rigging Co.", 60, 30, 60, 11.50),
                        ("CRN-HOOK-LATCH", "Hook safety latch", "Bin N2", "Lift & Rigging Co.", 6, 3, 6, 14.00),
                        ("CRN-LIM-SW", "Limit switch assembly", "Cabinet N3", "Lift & Rigging Co.", 1, 1, 2, 220.00)],
    "Factory Measuring & Test Equipment": [("MTE-LBL-CAL", "Calibration due labels, roll of 500", "Drawer Q1", "Machinists Supply", 2, 1, 3, 12.00),
                                           ("MTE-CASE-S", "Instrument storage case", "Shelf Q1", "Machinists Supply", 2, 1, 2, 25.00),
                                           ("MTE-TAG-OOS", "Out-of-service tags (pack of 100)", "Drawer Q1", "Machinists Supply", 1, 1, 2, 18.00)],
    "Machine Tools": [("MCH-COOL-5G", "Cutting coolant concentrate, 20 L", "Shelf L1", "Machinists Supply", 3, 2, 4, 145.00),
                      ("MCH-WAY-OIL", "Way lube oil, 20 L", "Shelf L1", "Machinists Supply", 2, 2, 3, 110.00),
                      ("MCH-INS-CNMG", "Carbide insert CNMG 432 (box of 10)", "Cabinet L2", "Machinists Supply", 8, 4, 8, 72.00)],
    "Longevity 60-74": [("LNG-MVI-90", "Multivitamin for adults 50+, 90 tablets", "Kitchen shelf", "Local pharmacy", 2, 1, 3, 22.00),
                  ("LNG-D3-1000", "Vitamin D3 1,000 IU, 180 softgels", "Kitchen shelf", "Local pharmacy", 1, 1, 2, 14.00),
                  ("LNG-OMG-3", "Fish oil, EPA + DHA, 120 softgels", "Kitchen shelf", "Local pharmacy", 1, 1, 2, 26.00),
                  ("LNG-BPCUFF", "Home blood pressure monitor (validated, upper arm)", "Bedroom drawer", "Local pharmacy", 1, 1, 1, 65.00),
                  ("LNG-BAND", "Resistance bands, light to heavy set", "Exercise corner", "Sporting goods", 1, 1, 1, 30.00),
                  ("LNG-TEA", "Green tea, loose or bags", "Kitchen shelf", "Grocery", 2, 1, 3, 8.00)],
    "Fire & Life Safety": [("FLS-EXT-ABC10", "ABC extinguisher 10 lb, recharged", "Rack Z1", "Safety First Supply", 4, 2, 4, 78.00),
                           ("FLS-SMK-DET", "Smoke detector head", "Rack Z2", "Safety First Supply", 10, 4, 10, 23.00),
                           ("FLS-EMG-LAMP", "Emergency light battery pack", "Rack Z2", "Safety First Supply", 3, 2, 4, 34.00)],
    "IT & Network": [("IT-UPS-BATT", "UPS replacement battery pack", "Shelf N1", "Office Tech Supply", 2, 1, 2, 95.00),
                     ("IT-CAT6-3M", "Network patch cable, 3 m (pack of 10)", "Shelf N1", "Office Tech Supply", 4, 2, 4, 28.00),
                     ("IT-AIR-CAN", "Compressed air duster (case of 6)", "Shelf N2", "Office Tech Supply", 3, 1, 2, 34.00),
                     ("IT-BKP-2TB", "External backup drive, 2 TB", "Shelf N2", "Office Tech Supply", 2, 1, 2, 89.00),
                     ("IT-SSD-500", "Solid-state drive, 500 GB", "Shelf N3", "Office Tech Supply", 2, 1, 2, 68.00)],
}
for _lg, _lp in (("Longevity 18-39 Adults", "L18"),
                 ("Longevity 40-59 Adults", "L40"), ("Longevity 75 Plus", "L75")):
    SAMPLE_PARTS[_lg] = [(_r[0].replace("LNG-", _lp + "-"),) + tuple(_r[1:]) for _r in SAMPLE_PARTS["Longevity 60-74"]]
SAMPLE_PARTS["Longevity 00-05 Early Years"] = [("L00-VITD", "Vitamin D drops 400 IU (infants)", "Kitchen shelf", "Local pharmacy", 1, 1, 2, 16.00),
                                      ("L00-TBRUSH", "Child toothbrush and fluoride toothpaste", "Bathroom", "Local pharmacy", 2, 1, 3, 7.00),
                                      ("L00-HELMET", "Bike or tricycle helmet, correct size", "Entry closet", "Sporting goods", 1, 1, 1, 45.00),
                                      ("L00-SUNSCR", "Sunscreen SPF 30+ for children", "Entry closet", "Local pharmacy", 1, 1, 2, 14.00)]
SAMPLE_PARTS["Longevity 06-12 Kids"] = [("L06-TBRUSH", "Child toothbrush and fluoride toothpaste", "Bathroom", "Local pharmacy", 2, 1, 3, 7.00),
                                      ("L06-HELMET", "Bike helmet, correct size", "Entry closet", "Sporting goods", 1, 1, 1, 45.00),
                                      ("L06-SUNSCR", "Sunscreen SPF 30+ for children", "Entry closet", "Local pharmacy", 1, 1, 2, 14.00)]
SAMPLE_PARTS["Longevity 13-17 Teens"] = [("L13-TBRUSH", "Toothbrush, floss and mouthguard", "Bathroom", "Local pharmacy", 2, 1, 3, 20.00),
                                        ("L13-HELMET", "Helmet for bike, skate or snow sports", "Entry closet", "Sporting goods", 1, 1, 1, 60.00),
                                        ("L13-SUNSCR", "Sunscreen SPF 30+", "Entry closet", "Local pharmacy", 1, 1, 2, 14.00)]

SAMPLE_PARTS["Preparedness: Home & Family"] = [("PRP-WATER-4L", "Drinking water, 4 L jug", "Basement shelf", "Grocery store", 12, 6, 12, 4.00),
                                               ("PRP-BATT-AA", "AA batteries, pack of 24", "Utility drawer", "Hardware store", 2, 1, 2, 14.00),
                                               ("PRP-BATT-D", "D batteries, pack of 8", "Utility drawer", "Hardware store", 2, 1, 2, 16.00),
                                               ("PRP-FIRSTAID", "First-aid kit, family size", "Kitchen cupboard", "Pharmacy", 1, 1, 2, 45.00),
                                               ("PRP-LANTERN", "LED lantern", "Utility drawer", "Hardware store", 2, 1, 2, 22.00),
                                               ("PRP-CANDLE", "Emergency candles, pack", "Utility drawer", "Hardware store", 2, 1, 2, 8.00),
                                               ("PRP-RADIO", "Crank or battery weather radio", "Utility drawer", "Hardware store", 1, 1, 1, 40.00),
                                               ("PRP-FOOD-RICE", "Rice, 10 kg bag", "Basement shelf", "Grocery store", 2, 1, 2, 18.00),
                                               ("PRP-FOOD-BEANS", "Canned beans (case)", "Basement shelf", "Grocery store", 2, 1, 2, 24.00),
                                               ("PRP-BLANKET", "Wool or emergency blanket", "Entry closet", "Sporting goods", 3, 2, 3, 25.00),
                                               ("PRP-EXT-ABC", "ABC fire extinguisher, 5 lb", "Kitchen", "Safety supply", 1, 1, 2, 60.00),
                                               ("PRP-CO-ALARM", "Carbon monoxide alarm", "Hallway", "Hardware store", 2, 1, 2, 40.00)]

def _seed_sample_parts(cursor):
    """Sample parts for each sample group. Added only while the parts list is completely empty, so a part you delete or change is never put back."""
    cursor.execute('SELECT COUNT(*) FROM "Inventory_Parts"')
    if cursor.fetchone()[0] > 0: return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for grp, items in SAMPLE_PARTS.items():
        if grp != PART_GENERAL and grp not in SAMPLE_GROUPS: continue
        for pn, desc, loc, sup, qty, rp, rq, uc in items:
            cursor.execute('INSERT OR IGNORE INTO "Inventory_Parts" (PartNumber, Description, AssetGroup, Location, Supplier, QtyOnHand, ReorderPoint, ReorderQty, UnitCost) VALUES (?,?,?,?,?,?,?,?,?)',
                           (pn, desc, grp, loc, sup, qty, rp, rq, uc))
            if qty > 0 and cursor.rowcount:
                cursor.execute('INSERT INTO "Inventory_Moves" (PartID, MoveDate, Kind, Qty, BalanceAfter, AssetID, Note, UserName) VALUES (?,?,?,?,?,?,?,?)',
                               (cursor.lastrowid, now, "Received", qty, qty, "", "Opening balance (sample data)", ""))

def seed_sample_data(cursor):
    """Insert the built-in sample asset groups (units, tasks, parts, attributes).
    Safe to run repeatedly: existing rows are left alone."""
    cat_prefixes = SAMPLE_CAT_PREFIXES

    for cat, prefix in cat_prefixes.items():
      def_l1, def_l2, def_l3, def_l4, def_l5, _ = get_default_labels_for_category(cat)
      unit_range = range(1, SAMPLE_UNIT_COUNT.get(cat, 5) + 1)
      for i in unit_range:
        aid = f"{prefix}-{i:02d}"
        model = SAMPLE_UNIT_NAMES.get(cat, {}).get(i) or SAMPLE_MODEL_PATTERNS.get(cat, "Industrial Unit {i}").format(i=i, i2=i + 10)
        if cat == 'Aircraft' and SAMPLE_UNIT_NAMES.get(cat, {}).get(i):
          cursor.execute('UPDATE "Trucks" SET Year_Make_Model = ? WHERE AssetID = ? AND Year_Make_Model LIKE ?', (model, aid, 'Light Aircraft N%'))
        chk_json = json.dumps(get_default_checklist_df(cat).to_dict(orient="records"))
        assigned_protocol = MAINTENANCE_PROTOCOLS[i % 3]
        cursor.execute("""INSERT OR IGNORE INTO "Trucks" ("AssetID", "Year_Make_Model", "SerialNumber", "Color", "Motor", "Transmission", "Fuel", "Category", "Maintenance_Protocol", "Current_Meter", "Disregard_Dates", "Checklist_Data_V2", "Attr1_Label", "Attr2_Label", "Attr3_Label", "Attr4_Label", "Attr5_Label") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""", (aid, model, f"SN-{aid}", "Standard", "Primary", "Standard", "Various", cat, assigned_protocol, 25000 + (100 * i), chk_json, def_l1, def_l2, def_l3, def_l4, def_l5))
        cursor.execute('SELECT COUNT(*) FROM "Preventive_Schedules" WHERE AssetID = ?', (aid,))
        if cursor.fetchone()[0] == 0:
          string_tasks = [(t[0], t[1], t[2], t[3], str(t[4]), str(t[5]), str(t[6]), str(t[7]), float(t[8]), str(t[9]), str(t[10]), str(t[11]), float(t[12]), str(t[13])) for t in get_default_tasks_for_category(cat, aid)]
          cursor.executemany("""INSERT INTO "Preventive_Schedules" ("AssetID", "TabGroup", "TaskName", "Date_Last_Done", "Meter_At_Last", "Days_Between", "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", "PersonnelQualifications", "SafetyPrecautions", "EstimatedPartsCost", "RequiredConsumables") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", string_tasks)
          stagger_task_dates(cursor, [aid])
        cursor.execute('SELECT COUNT(*) FROM "Asset_Components" WHERE AssetID = ?', (aid,))
        if cursor.fetchone()[0] <= 3:
          cursor.execute('DELETE FROM "Asset_Components" WHERE AssetID = ?', (aid,))
          cursor.executemany("""INSERT INTO "Asset_Components" ("AssetID", "ComponentName", "PartNumber", "ConditionStatus", "Notes") VALUES (?, ?, ?, ?, ?)""", [(aid, f"Precision Sub-Component {j}", f"PN-{prefix}-{(j):03d}", "Operational", "Factory sealed.") for j in range(1, 10)])
        cursor.execute('SELECT COUNT(*) FROM "Asset_Attributes" WHERE AssetID = ?', (aid,))
        if cursor.fetchone()[0] == 0: cursor.executemany("""INSERT INTO "Asset_Attributes" ("AssetID", "AttributeName", "Value", "Notes") VALUES (?, ?, ?, ?)""", get_category_attributes(cat, i, aid))
        cursor.execute('SELECT COUNT(*) FROM "Asset_Parts" WHERE AssetID = ?', (aid,))
        if cursor.fetchone()[0] <= 3:
          cursor.execute('DELETE FROM "Asset_Parts" WHERE AssetID = ?', (aid,))
          p1, p2, p3, p4, p5, p6 = get_category_part_labels(cat)
          cursor.executemany("""INSERT INTO "Asset_Parts" ("AssetID", "PartHeading", "PartDescription", "Supplier", "PowerUsage", "Inventory", "Status") VALUES (?, ?, ?, ?, ?, ?, ?)""", [(aid, lbl, "Module", "Supplier", "450 kW", "In Stock (2)", "Operational") for lbl in [p1, p2, p3, p4, p5, p6]])
    
    
    _seed_sample_parts(cursor)

    # Retroactive database clean-up for legacy protocols
    cursor.execute('SELECT AssetID FROM "Trucks" WHERE Maintenance_Protocol = "Standard Protocol" OR Maintenance_Protocol = "Preventative Maintenance (PM)" OR Maintenance_Protocol IS NULL')
    for idx, (t_aid,) in enumerate(cursor.fetchall()):
        cursor.execute('UPDATE "Trucks" SET Maintenance_Protocol = ? WHERE AssetID = ?', (MAINTENANCE_PROTOCOLS[idx % 3], t_aid))

def load_sample_data():
    """Switch this database to 'sample' mode and load the sample data (used by the first-run button)."""
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cur = conn.cursor()
        cur.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("seed_mode", "sample"))
        seed_sample_data(cur)
        conn.commit()

def is_empty_install():
    """True when no assets exist yet (a brand-new database)."""
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        return conn.execute('SELECT COUNT(*) FROM "Trucks"').fetchone()[0] == 0

# ==========================================
# USERS & LOGIN
# ==========================================
PBKDF2_ITERS = 200_000
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5
MIN_PASSWORD_LEN = 8
ROLES = ["admin", "technician", "viewer"]
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")

def _auth_conn():
    # Auth tables use the real sqlite3 module so a read-only user can still change their own password.
    conn = _sqlite3_real.connect(DB_PATH, timeout=20.0)
    conn.execute('CREATE TABLE IF NOT EXISTS "App_Settings" ("Key" TEXT PRIMARY KEY, "Value" TEXT)')
    conn.execute('''CREATE TABLE IF NOT EXISTS "Users" (
        "UserID" INTEGER PRIMARY KEY AUTOINCREMENT, "Username" TEXT UNIQUE NOT NULL, "FullName" TEXT,
        "Role" TEXT NOT NULL DEFAULT 'technician', "Salt" TEXT NOT NULL, "PasswordHash" TEXT NOT NULL,
        "Active" INTEGER NOT NULL DEFAULT 1, "FailedAttempts" INTEGER NOT NULL DEFAULT 0,
        "LockedUntil" TEXT, "Created" TEXT, "LastLogin" TEXT)''')
    return conn

def get_login_mode():
    """'on' = sign-in required, 'off' = no login, 'unset' = brand-new install still to decide."""
    with _auth_conn() as conn:
        row = conn.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', ("login_mode",)).fetchone()
    return row[0] if row and row[0] in ("on", "off", "unset") else "off"

def set_login_mode(mode):
    with _auth_conn() as conn:
        conn.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("login_mode", mode))
        conn.commit()

def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return salt.hex(), digest.hex()

def validate_new_user(username, password, confirm=None):
    """Returns an error message, or '' if the username and password are acceptable."""
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3 to 32 characters: lowercase letters, numbers, dot, dash or underscore."
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if confirm is not None and password != confirm:
        return "The two passwords do not match."
    return ""

def create_user(username, full_name, role, password):
    username = (username or "").strip().lower()
    err = validate_new_user(username, password)
    if err: return False, err
    if role not in ROLES: return False, "Unknown role."
    salt, digest = hash_password(password)
    try:
        with _auth_conn() as conn:
            conn.execute('INSERT INTO "Users" ("Username","FullName","Role","Salt","PasswordHash","Active","Created") VALUES (?,?,?,?,?,1,?)',
                         (username, (full_name or "").strip(), role, salt, digest, datetime.now().isoformat(timespec="seconds")))
            conn.commit()
    except _sqlite3_real.IntegrityError:
        return False, "That username is already taken."
    return True, f"User '{username}' created."

def attempt_login(username, password):
    """Returns (ok, user_dict_or_message). Five wrong passwords lock the account for five minutes."""
    username = (username or "").strip().lower()
    generic = "Invalid username or password."
    with _auth_conn() as conn:
        conn.row_factory = _sqlite3_real.Row
        row = conn.execute('SELECT * FROM "Users" WHERE Username = ?', (username,)).fetchone()
        if row is None or not row["Active"]:
            hash_password(password or "")   # similar timing whether or not the user exists
            return False, generic
        locked = row["LockedUntil"]
        if locked:
            try:
                remaining = datetime.fromisoformat(locked) - datetime.now()
                if remaining.total_seconds() > 0:
                    return False, f"Too many failed attempts. Try again in {int(remaining.total_seconds() // 60) + 1} minute(s)."
            except ValueError:
                pass
        _, digest = hash_password(password or "", row["Salt"])
        if hmac.compare_digest(digest, row["PasswordHash"]):
            conn.execute('UPDATE "Users" SET FailedAttempts = 0, LockedUntil = NULL, LastLogin = ? WHERE UserID = ?',
                         (datetime.now().isoformat(timespec="seconds"), row["UserID"]))
            conn.commit()
            return True, {"UserID": row["UserID"], "Username": row["Username"], "FullName": row["FullName"] or row["Username"], "Role": row["Role"]}
        fails = int(row["FailedAttempts"] or 0) + 1
        if fails >= MAX_FAILED_LOGINS:
            until = (datetime.now() + _timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
            conn.execute('UPDATE "Users" SET FailedAttempts = 0, LockedUntil = ? WHERE UserID = ?', (until, row["UserID"]))
        else:
            conn.execute('UPDATE "Users" SET FailedAttempts = ? WHERE UserID = ?', (fails, row["UserID"]))
        conn.commit()
        return False, generic

def list_users():
    with _auth_conn() as conn:
        return pd.read_sql('SELECT Username, FullName, Role, Active, LastLogin, Created FROM "Users" ORDER BY Username', conn)

def _active_admin_count(conn, excluding=None):
    q, params = 'SELECT COUNT(*) FROM "Users" WHERE Role = "admin" AND Active = 1', []
    if excluding:
        q += ' AND Username != ?'
        params.append(excluding)
    return conn.execute(q, params).fetchone()[0]

def set_password(username, new_password):
    if len(new_password or "") < MIN_PASSWORD_LEN:
        return False, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    salt, digest = hash_password(new_password)
    with _auth_conn() as conn:
        n = conn.execute('UPDATE "Users" SET Salt = ?, PasswordHash = ?, FailedAttempts = 0, LockedUntil = NULL WHERE Username = ?', (salt, digest, username)).rowcount
        conn.commit()
    return (True, "Password changed.") if n else (False, "No such user.")

def change_own_password(username, old_password, new_password):
    ok, res = attempt_login(username, old_password)
    if not ok: return False, "Current password is incorrect."
    return set_password(username, new_password)

def update_user(username, role=None, active=None):
    """Change role and/or active flag, never leaving the system without an active administrator."""
    with _auth_conn() as conn:
        row = conn.execute('SELECT Role, Active FROM "Users" WHERE Username = ?', (username,)).fetchone()
        if not row: return False, "No such user."
        new_role = role if role is not None else row[0]
        new_active = int(active) if active is not None else row[1]
        if row[0] == "admin" and row[1] == 1 and (new_role != "admin" or not new_active) and _active_admin_count(conn, excluding=username) == 0:
            return False, "There must be at least one active administrator."
        conn.execute('UPDATE "Users" SET Role = ?, Active = ? WHERE Username = ?', (new_role, new_active, username))
        conn.commit()
    return True, "User updated."

def delete_user(username):
    with _auth_conn() as conn:
        row = conn.execute('SELECT Role, Active FROM "Users" WHERE Username = ?', (username,)).fetchone()
        if not row: return False, "No such user."
        if row[0] == "admin" and row[1] == 1 and _active_admin_count(conn, excluding=username) == 0:
            return False, "There must be at least one active administrator."
        conn.execute('DELETE FROM "Users" WHERE Username = ?', (username,))
        conn.commit()
    return True, f"User '{username}' deleted."

def current_user_name():
    u = st.session_state.get("auth_user")
    return u["Username"] if u else ""

def sign_out():
    for k in ("auth_user", "auth_role"):
        st.session_state.pop(k, None)

def require_login():
    """Gate for the whole app. Returns once the visitor is allowed in; otherwise draws the
    setup or sign-in screen and stops the script."""
    mode = get_login_mode()
    if mode == "off":
        st.session_state["auth_role"] = "admin"   # no login: full access, as before
        return
    if mode == "unset":
        st.title("Welcome to An Ounce of Prevention")
        st.markdown("Choose how this installation is protected. You can change this later under **Users & Security**.")
        st.markdown("**Recommended if more than one person will use it:** create an administrator account. "
                    "Everyone then signs in with their own username and password.")
        with st.form("first_run_admin_form"):
            fn = st.text_input("Your full name")
            un = st.text_input("Administrator username (lowercase)")
            pw = st.text_input("Password (8 or more characters)", type="password")
            pw2 = st.text_input("Confirm password", type="password")
            go = st.form_submit_button("Create Administrator")
        if go:
            un = (un or "").strip().lower()
            err = validate_new_user(un, pw, pw2)
            if err:
                st.error(err)
            else:
                ok, msg = create_user(un, fn, "admin", pw)
                if ok:
                    set_login_mode("on")
                    ok2, res = attempt_login(un, pw)
                    if ok2:
                        st.session_state["auth_user"], st.session_state["auth_role"] = res, res["Role"]
                    st.rerun()
                else:
                    st.error(msg)
        st.markdown("---")
        st.caption("Working alone on one computer? You can skip this and add accounts later.")
        if st.button("Continue Without Login", key="btn_skip_login"):
            set_login_mode("off")
            st.rerun()
        st.stop()
    # mode == "on"
    if st.session_state.get("auth_user"):
        st.session_state["auth_role"] = st.session_state["auth_user"]["Role"]
        return
    st.title("An Ounce of Prevention")
    st.caption(f"Licensed to: {LICENSED_TO}")
    with st.form("login_form"):
        un = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign In")
    if go:
        ok, res = attempt_login(un, pw)
        if ok:
            st.session_state["auth_user"], st.session_state["auth_role"] = res, res["Role"]
            st.rerun()
        else:
            st.error(res)
    st.stop()

# ==========================================
# LICENSE CODES (offline, signed with Ed25519)
# ==========================================
# The vendor tool make_license.py signs each licence with a PRIVATE key that never leaves the vendor.
# This app holds only the matching PUBLIC key, so it can check a code but cannot create one.
LICENSE_PUBLIC_KEY_HEX = ""   # set by: python make_license.py init --app app.py
LICENSE_PREFIX = "OOP1-"

# --- Ed25519 signature verification (RFC 8032), pure Python, no extra packages needed ---
_ED_P = 2**255 - 19
_ED_Q = 2**252 + 27742317777372353535851937790883648493
_ED_D = -121665 * pow(121666, _ED_P - 2, _ED_P) % _ED_P
_ED_SQRT_M1 = pow(2, (_ED_P - 1) // 4, _ED_P)

def _ed_add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % _ED_P, (P[1] + P[0]) * (Q[1] + Q[0]) % _ED_P
    C, D = 2 * P[3] * Q[3] * _ED_D % _ED_P, 2 * P[2] * Q[2] % _ED_P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _ED_P, G * H % _ED_P, F * G % _ED_P, E * H % _ED_P)

def _ed_mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1: Q = _ed_add(Q, P)
        P = _ed_add(P, P)
        s >>= 1
    return Q

def _ed_equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _ED_P == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _ED_P == 0

def _ed_recover_x(y, sign):
    if y >= _ED_P: return None
    x2 = (y * y - 1) * pow(_ED_D * y * y + 1, _ED_P - 2, _ED_P)
    if x2 == 0: return None if sign else 0
    x = pow(x2, (_ED_P + 3) // 8, _ED_P)
    if (x * x - x2) % _ED_P != 0: x = x * _ED_SQRT_M1 % _ED_P
    if (x * x - x2) % _ED_P != 0: return None
    if (x & 1) != sign: x = _ED_P - x
    return x

_ED_GY = 4 * pow(5, _ED_P - 2, _ED_P) % _ED_P
_ED_GX = _ed_recover_x(_ED_GY, 0)
_ED_G = (_ED_GX, _ED_GY, 1, _ED_GX * _ED_GY % _ED_P)

def _ed_decompress(s):
    if len(s) != 32: return None
    y = int.from_bytes(s, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _ed_recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _ED_P)

def ed25519_verify(public, message, signature):
    """True only if 'signature' is a valid Ed25519 signature of 'message' under 'public'."""
    try:
        if len(public) != 32 or len(signature) != 64: return False
        A, R = _ed_decompress(public), _ed_decompress(signature[:32])
        if A is None or R is None: return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _ED_Q: return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _ED_Q
        return _ed_equal(_ed_mul(s, _ED_G), _ed_add(R, _ed_mul(h, A)))
    except Exception:
        return False

def _b64u_decode(text):
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

def parse_license(code, public_key_hex=None, today=None):
    """Check one licence code. Returns a dict:
       state: 'valid' | 'expired' | 'invalid' | 'unconfigured'
       plus licensee, edition, sites, issued, expires, id, message."""
    pub_hex = LICENSE_PUBLIC_KEY_HEX if public_key_hex is None else public_key_hex
    out = {"state": "invalid", "licensee": "", "edition": "", "sites": 0, "issued": "", "expires": "", "id": "", "message": ""}
    code = "".join((code or "").split())            # tolerate line breaks and spaces from copy and paste
    if not pub_hex:
        out.update(state="unconfigured", message="Licence checking is not set up in this copy.")
        return out
    try:
        if not code.startswith(LICENSE_PREFIX) or "." not in code:
            raise ValueError("That does not look like a licence code.")
        body, sig = code[len(LICENSE_PREFIX):].split(".", 1)
        payload, signature = _b64u_decode(body), _b64u_decode(sig)
        if not ed25519_verify(bytes.fromhex(pub_hex), payload, signature):
            raise ValueError("The licence code is not valid (signature check failed).")
        data = json.loads(payload.decode("utf-8"))
        if data.get("v") != 1: raise ValueError("Unsupported licence version.")
        out.update(licensee=str(data.get("licensee", "")).strip(), edition=str(data.get("edition", "")),
                   sites=int(data.get("sites", 1) or 1), issued=str(data.get("issued", "")),
                   expires=str(data.get("expires") or ""), id=str(data.get("id", "")))
        if not out["licensee"]: raise ValueError("The licence has no licensee name.")
        out["state"] = "valid"
        if out["expires"]:
            today = today or _date.today()
            if today > _date.fromisoformat(out["expires"]):
                out["state"] = "expired"
                out["message"] = f"This licence expired on {out['expires']}."
    except Exception as e:
        out.update(state="invalid", message=str(e) if isinstance(e, ValueError) else "The licence code could not be read.")
    return out

def _license_candidates():
    """Where a licence code may be stored, in priority order."""
    cands = []
    env_val = os.environ.get("OUNCE_LICENSE", "").strip()
    if env_val: cands.append(("environment", env_val))
    cfg_val = _config_value("license_code")
    if cfg_val: cands.append(("config file", cfg_val))
    try:
        lic_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "license.txt")
        if os.path.isfile(lic_file):
            with open(lic_file, "r", encoding="utf-8") as fh: cands.append(("license.txt", fh.read().strip()))
    except Exception:
        pass
    try:
        with _auth_conn() as conn:
            row = conn.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', ("license_code",)).fetchone()
        if row and row[0]: cands.append(("database", row[0]))
    except Exception:
        pass
    return cands

def effective_today():
    """Today's date, but never earlier than the latest date this database has seen, so winding the
    computer's clock back does not revive an expired licence."""
    today = _date.today()
    try:
        with _auth_conn() as conn:
            row = conn.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', ("last_run_date",)).fetchone()
            last = _date.fromisoformat(row[0]) if row and row[0] else None
            if last and last > today: return last
            if last is None or last < today:
                conn.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("last_run_date", today.isoformat()))
                conn.commit()
    except Exception:
        pass
    return today

def load_license():
    """Pick the licence this copy runs under. A code that checks out wins; otherwise the first code found is reported as invalid."""
    cands = _license_candidates()
    today = effective_today()
    first_bad = None
    for where, code in cands:
        info = parse_license(code, today=today)
        info["source"] = where
        if info["state"] in ("valid", "expired"): return info
        first_bad = first_bad or info
    return first_bad or {"state": "none", "licensee": "", "edition": "", "sites": 0, "issued": "", "expires": "", "id": "", "message": "", "source": ""}

def save_license_code(code):
    """Validate a pasted code and, if good, store it in the database. Returns (ok, message)."""
    info = parse_license(code, today=effective_today())
    if info["state"] == "unconfigured": return False, info["message"]
    if info["state"] == "invalid": return False, info["message"]
    with _auth_conn() as conn:
        conn.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("license_code", "".join(code.split())))
        conn.commit()
    name = info["licensee"]
    if info["state"] == "expired":
        text = f"Code accepted for {name}, but the licence expired on {info['expires']}."
        return True, text.replace("..", ".")
    text = f"Licence activated for {name}."
    return True, text.replace("..", ".")

def license_display(info):
    """Text for the 'Licensed to:' line on screens and printouts."""
    if info["state"] == "valid": return info["licensee"]
    if info["state"] == "expired": return f"{info['licensee']} (licence expired {info['expires']})"
    manual = _config_value("licensed_to") or os.environ.get("OUNCE_LICENSED_TO", "").strip()
    if manual: return f"{manual} (unverified)"
    return "Evaluation copy - not licensed"

def _refresh_license():
    """Run once per page load, after the database is ready."""
    global LICENSE_INFO, LICENSED_TO, LICENSE_READ_ONLY
    LICENSE_INFO = load_license()
    LICENSED_TO = license_display(LICENSE_INFO)
    LICENSE_READ_ONLY = LICENSE_INFO["state"] == "expired"
    DEMO.update({"active": False, "expired": False, "days_left": 0, "start": "", "end": ""})
    if DEMO_BUILD and LICENSE_INFO["state"] not in ("valid", "expired"):
        today = effective_today()          # never earlier than the latest date seen, so winding the clock back does not extend the demo
        start = None
        try:
            with _auth_conn() as conn:
                row = conn.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', ("demo_start",)).fetchone()
                if row and row[0]:
                    try: start = _date.fromisoformat(row[0])
                    except ValueError: start = None
                if start is None:
                    start = today
                    conn.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("demo_start", today.isoformat()))
                    conn.commit()
        except Exception:
            start = today
        end = start + _timedelta(days=DEMO_DAYS)
        left = (end - today).days
        DEMO.update({"start": start.isoformat(), "end": end.isoformat(), "days_left": max(left, 0)})
        if left > 0:
            DEMO["active"] = True
            LICENSED_TO = f"DEMO copy - not licensed ({left} day{'s' if left != 1 else ''} left)"
        else:
            DEMO["expired"] = True
            LICENSE_READ_ONLY = True
            LICENSED_TO = "DEMO copy - ended"

def _demo_fp(ymm, cat, sn):
    return hashlib.sha1(f"{ymm}|{cat}|{sn}".encode("utf-8")).hexdigest()[:12]

def demo_record_sample_fingerprints(cursor):
    """Called once, right after the sample data is first loaded: remember what each sample unit looks like,
    so that editing, renaming or re-creating one is recognised as 'your own' asset."""
    rows = cursor.execute('SELECT "AssetID", "Year_Make_Model", "Category", "SerialNumber" FROM "Trucks"').fetchall()
    fp = {r[0]: _demo_fp(r[1], r[2], r[3]) for r in rows}
    cats = sorted({r[2] for r in rows if r[2]})
    cursor.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("demo_sample_fp", json.dumps(fp)))
    cursor.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("demo_sample_cats", json.dumps(cats)))

def _demo_sample_reference():
    try: fp = json.loads(get_setting("demo_sample_fp", "") or "{}")
    except Exception: fp = {}
    try: cats = set(json.loads(get_setting("demo_sample_cats", "") or "[]"))
    except Exception: cats = set()
    if not fp:       # older database without fingerprints: fall back to the sample ID list
        fp = None
        cats = set(SAMPLE_CAT_PREFIXES.keys())
    return fp, cats

def _demo_rows():
    with _sqlite3_real.connect(DB_PATH, timeout=10.0) as conn:
        return conn.execute('SELECT "AssetID", "Year_Make_Model", "Category", "SerialNumber" FROM "Trucks"').fetchall()

def _demo_is_pristine(row, fp):
    if fp is None: return row[0] in set(sample_asset_ids())
    return fp.get(row[0]) == _demo_fp(row[1], row[2], row[3])

def demo_usage():
    """(units of your own, asset groups of your own). A sample unit that has been edited or renamed counts as your own."""
    try:
        fp, cats = _demo_sample_reference()
        own = [r for r in _demo_rows() if not _demo_is_pristine(r, fp)]
        groups = {r[2] for r in own if r[2] and r[2] not in cats}
        return len(own), len(groups)
    except Exception:
        return 0, 0

def demo_assets_used():
    return demo_usage()[0]

def demo_groups_used():
    return demo_usage()[1]

def demo_pristine_in_group(group):
    """How many untouched sample units are in this group (they would become 'yours' if the group were renamed)."""
    fp, cats = _demo_sample_reference()
    return len([r for r in _demo_rows() if r[2] == group and _demo_is_pristine(r, fp)])

def demo_would_convert(asset_id, new_ymm=None, new_sn=None):
    """True if saving these values turns an untouched sample unit into one of your own."""
    fp, cats = _demo_sample_reference()
    for r in _demo_rows():
        if r[0] == asset_id:
            if not _demo_is_pristine(r, fp): return False
            return _demo_fp(r[1] if new_ymm is None else new_ymm, r[2], r[3] if new_sn is None else new_sn) != _demo_fp(r[1], r[2], r[3])
    return False

def demo_cap_message(n_new=1, new_groups=0):
    """Text to show when this change would pass the demo limits, else ''."""
    if not (DEMO_BUILD and DEMO.get("active")): return ""
    used, gused = demo_usage()
    if used + n_new > DEMO_MAX_ASSETS:
        return (f"The demo allows {DEMO_MAX_ASSETS} assets of your own (you have {used}; room for {max(DEMO_MAX_ASSETS - used, 0)} more). "
                f"Editing, renaming or copying a sample unit counts as one of yours; the untouched sample data does not. "
                f"A licence from {DEMO_URL} removes the limits and keeps everything you've entered.")
    if gused + new_groups > DEMO_MAX_GROUPS:
        return (f"The demo allows {DEMO_MAX_GROUPS} asset groups of your own (you have {gused}). "
                f"A licence from {DEMO_URL} removes the limits and keeps everything you've entered.")
    return ""

def demo_cap_gate(n_new=1, new_groups=0):
    """Stop the page with a plain message if the demo limits would be passed."""
    _m = demo_cap_message(n_new, new_groups)
    if _m:
        # Show the message in the full-width slot at the top of the page (made below the DEMO banner), not inside a narrow column
        _slot = globals().get("_DEMO_SLOT")
        try:
            if _slot is not None: _slot.error(_m)
            else: st.error(_m)
            st.toast("Demo limit reached. The message is at the top of the page.")
        except Exception:
            st.error(_m)
        st.stop()


def render_license_panel():
    """Licence status and activation box (shown on the Users & Security page)."""
    info = LICENSE_INFO
    st.markdown("#### Licence")
    flash = st.session_state.pop("license_flash", None)
    if flash: (st.success if flash[0] == "ok" else st.error)(flash[1])
    if info["state"] in ("valid", "expired"):
        (st.success if info["state"] == "valid" else st.warning)(
            f"Licensed to **{info['licensee']}**  |  {info['edition'] or 'standard'} edition  |  up to {info['sites']} site(s)  |  "
            + (f"expires {info['expires']}" if info["expires"] else "perpetual") + f"  |  ID {info['id']}"
            + (f"  |  {info['message']}" if info["state"] == "expired" else ""))
    elif info["state"] == "invalid":
        st.error(f"A licence code was found ({info['source']}) but it was not accepted: {info['message']}")
    elif DEMO.get("active"):
        st.info(f"**DEMO copy.** {DEMO['days_left']} day(s) left (ends {DEMO['end']}). Up to {DEMO_MAX_ASSETS} assets and {DEMO_MAX_GROUPS} asset groups of your own. "
                f"Bought a licence at {DEMO_URL}? Paste the code below: the limits go away and all your data stays.")
    elif DEMO.get("expired"):
        st.warning(f"The {DEMO_DAYS}-day demo ended on {DEMO['end']}. Your data is safe: you can still view, print and back up. "
                   f"Get a licence at {DEMO_URL} and paste the code below to carry on with everything you entered.")
    else:
        st.info("This copy is running as an evaluation copy. Paste your licence code below to activate it.")
    if not LICENSE_PUBLIC_KEY_HEX:
        st.caption("Licence checking is not set up in this copy (no public key installed).")
    _code = st.text_area("Paste licence code", key="license_code_input", height=110)
    if st.button("Activate Licence", key="btn_activate_license"):
        _ok, _msg = save_license_code(_code)
        st.session_state["license_flash"] = ("ok" if _ok else "err", _msg)
        st.rerun()

# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def init_db():
  os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
  with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Trucks';")
    if cursor.fetchone():
      cursor.execute("PRAGMA table_info('Trucks');")
      columns = [col[1] for col in cursor.fetchall()]
      if "TruckID" in columns and "AssetID" not in columns:
        cursor.execute('ALTER TABLE "Trucks" RENAME COLUMN "TruckID" TO "AssetID";')
        conn.commit()
    else:
      cursor.execute('CREATE TABLE "Trucks" ("AssetID" TEXT PRIMARY KEY, "Year_Make_Model" TEXT, "SerialNumber" TEXT, "Color" TEXT, "Motor" TEXT, "Transmission" TEXT, "Fuel" TEXT, "Category" TEXT, "Maintenance_Protocol")')

    conn.commit()


    cursor.execute('CREATE TABLE IF NOT EXISTS "Glossary" ("TermID" INTEGER PRIMARY KEY AUTOINCREMENT, "Term" TEXT, "Acronym" TEXT, "Definition" TEXT, "AssetGroup" TEXT)')
    cursor.execute('SELECT COUNT(*) FROM "Glossary"')
    if cursor.fetchone()[0] == 0:
        seed_glossary = [("Airworthiness, Registration, Operating, Weight", "AROW", "The mandatory documents onboard an aircraft before flight.", "Aircraft"), ("Blowout Preventer", "BOP", "Specialized valve to seal, control and monitor wellbores.", "Drilling Rigs"), ("Commercial Vehicle Inspection Program", "CVIP", "Mandatory heavy vehicle safety certification in Alberta.", "Service Rigs"), ("Non-Destructive Testing", "NDT", "Techniques like Ultrasonic or Magnetic Particle testing to find micro-fractures in load-bearing steel.", "Universal / All")]
        cursor.executemany('INSERT INTO "Glossary" ("Term", "Acronym", "Definition", "AssetGroup") VALUES (?, ?, ?, ?)', seed_glossary)
        conn.commit()

    cursor.execute('SELECT COUNT(*) FROM "Glossary" WHERE Term = ?', ("Mean Time Between Failures",))
    if cursor.fetchone()[0] == 0:
        _gx = [
            ("Mean Time Between Failures", "MTBF", "The average running time between failures of a repairable item. A higher number means fewer breakdowns, but it is an average, not a promise for any one machine.", "Universal / All"),
            ("Mean Time To Repair", "MTTR", "The average time it takes to get a failed item working again, including finding the fault, getting parts and testing.", "Universal / All"),
            ("Reliability", "", "The chance that an item does its job without failing for a stated time under stated conditions.", "Universal / All"),
            ("Maintainability", "", "How easily and quickly an item can be kept working or put right. Good access, simple parts and clear manuals make a machine more maintainable.", "Universal / All"),
            ("Availability", "", "The share of time an item is ready to work. It depends on both how often it fails and how fast it is repaired.", "Universal / All"),
            ("Preventive Maintenance", "PM", "Work done on a schedule (by time or use) before a failure, such as oil changes, inspections and replacing worn parts.", "Universal / All"),
            ("Condition-Based Maintenance", "CBM", "Maintenance done when a measurement shows it is needed, such as rising vibration, temperature or oil contamination, instead of on a fixed calendar.", "Universal / All"),
            ("Corrective Maintenance", "", "Repair done after something has failed or is found faulty.", "Universal / All"),
            ("Run to Failure", "", "A deliberate decision to fix something only when it breaks, sensible only when failure is cheap, safe and easy to fix.", "Universal / All"),
            ("Reliability-Centred Maintenance", "RCM", "A way of choosing maintenance for each machine by asking what it must do, how it can fail and what the failure would cost, with safety first. It uses time-based tasks, condition-based tasks, failure-finding tasks, or a deliberate run to failure.", "Universal / All"),
            ("Failure-Finding Task", "", "A test that checks a hidden protective function still works, such as an emergency stop, relief valve, low-water cut-off or backup pump, because its failure gives no warning until you need it.", "Universal / All"),
            ("Bathtub Curve", "", "A picture of how failure rates often behave: high early on (infant failures), low and steady in the middle, and rising again as parts wear out.", "Universal / All"),
            ("Failure Modes and Effects Analysis", "FMEA", "A step-by-step review of each part: how it could fail, what happens when it does, and what to do about the worst cases first.", "Universal / All"),
            ("Fault Tree Analysis", "FTA", "A diagram that starts from an unwanted event and works backward to the combinations of causes that could produce it.", "Universal / All"),
            ("Root Cause Analysis", "RCA", "Digging past the obvious trigger of a failure to the underlying reason, so the fix prevents a repeat.", "Universal / All"),
            ("Lockout / Tagout", "LOTO", "Isolating energy sources and locking and tagging them off so equipment cannot start while someone is working on it.", "Universal / All"),
            ("Job Hazard Analysis", "JHA", "Breaking a task into steps, spotting the hazards in each, and deciding the controls before the work starts.", "Universal / All"),
            ("Hierarchy of Controls", "", "The order of preference for handling a hazard: remove it, replace it with something safer, guard or engineer it away, change how people work, and only then rely on protective equipment.", "Universal / All"),
            ("Near Miss", "", "An event that could have caused injury or damage but did not. Recording near misses shows where the next accident would have happened.", "Universal / All"),
            ("Working Load Limit", "WLL", "The most load a piece of lifting gear is rated to carry in normal use. Also called safe working load (SWL).", "Cranes & Hoists"),
            ("Competent Person", "", "Someone with the training, experience and authority to spot hazards and defects and to order them corrected. Local regulations define who qualifies.", "Universal / All"),
            ("Condition Monitoring", "", "Measuring a machine while it runs (vibration, temperature, oil analysis, current) to catch trouble early.", "Universal / All"),
        ]
        cursor.executemany('INSERT INTO "Glossary" ("Term", "Acronym", "Definition", "AssetGroup") VALUES (?, ?, ?, ?)', _gx)
        conn.commit()

    cursor.execute('SELECT COUNT(*) FROM "Glossary" WHERE Term = ?', ("Calibration",))
    if cursor.fetchone()[0] == 0:
        _gq = [
            ("Calibration", "", "Comparing an instrument with a more accurate reference standard and recording how far off it is, adjusting it if needed. Done at set intervals so readings can be trusted.", "Universal / All"),
            ("Traceability (measurement)", "", "An unbroken chain of comparisons linking an instrument's reading back to a recognised national or international standard, usually shown on a calibration certificate.", "Universal / All"),
            ("Verification (of an instrument)", "", "A quick check that an instrument still reads correctly against a known reference between formal calibrations. It does not replace calibration.", "Universal / All"),
            ("Out of Tolerance", "", "A reading that falls outside the allowed error for an instrument. Anything measured with it since its last good check may need reviewing.", "Universal / All"),
            ("Nonconformity", "", "A requirement that was not met: a part, job or record that does not match what was specified.", "Universal / All"),
            ("Corrective Action", "", "Action taken to remove the cause of a problem so it does not happen again, after finding the root cause. Not the same as a quick repair.", "Universal / All"),
            ("Preventive Action", "", "Action taken to remove the cause of a possible problem before it happens, such as adding a task to the schedule after a near miss.", "Universal / All"),
            ("Failure Mode", "", "How a failure shows itself, such as fails to start, external leak, vibration or overheating. Not the same as the cause.", "Universal / All"),
            ("Failure Mechanism", "", "The physical or chemical process behind a failure, such as wear, fatigue, corrosion or erosion.", "Universal / All"),
            ("Criticality", "", "A ranking of how much trouble it would cause if an asset failed (safety, production, cost, environment). Used to decide which assets get the most attention.", "Universal / All"),
            ("Management Review", "", "A regular meeting where the people in charge look at results, problems and resources and decide what to change. Minutes are kept.", "Universal / All"),
            ("Audit Trail", "", "A record of who changed what and when, so changes to records can be traced.", "Universal / All"),
        ]
        cursor.executemany('INSERT INTO "Glossary" ("Term", "Acronym", "Definition", "AssetGroup") VALUES (?, ?, ?, ?)', _gq)
        conn.commit()

    cursor.execute('CREATE TABLE IF NOT EXISTS "IncidentReports" ("IncidentID" INTEGER PRIMARY KEY AUTOINCREMENT, "Date" TEXT, "Location" TEXT, "AssetInvolved" TEXT, "Fatalities" INTEGER, "Agency" TEXT, "Description" TEXT, "Status" TEXT)')
    for _col, _typ in (("Injuries", "INTEGER DEFAULT 0"), ("LostTime", "TEXT DEFAULT 'No'"), ("ReportNo", "TEXT"), ("IncidentType", "TEXT"), ("Country", "TEXT"), ("Region", "TEXT")):
        try: cursor.execute(f'ALTER TABLE "IncidentReports" ADD COLUMN "{_col}" {_typ}')
        except sqlite3.OperationalError: pass
    cursor.execute('SELECT COUNT(*) FROM "IncidentReports"')
    if cursor.fetchone()[0] == 0:
        seed_incidents = [("1979-05-25", "Chicago, IL", "McDonnell Douglas DC-10", 273, 0, "No", "NTSB", "", "American Airlines Flight 191. Engine separation during takeoff.", "Closed - ADs Issued", "Injury / Illness / Fatality"),
                          ("2026-03-12", "Regina, SK", "Forklift FORK-02", 0, 1, "Yes", "WCB", "SAMPLE-0001", "Sample entry: operator strained a wrist when a mast chain slipped. Chain replaced; added to the monthly inspection.", "Open - claim filed", "Injury / Illness / Fatality")]
        cursor.executemany('INSERT INTO "IncidentReports" ("Date", "Location", "AssetInvolved", "Fatalities", "Injuries", "LostTime", "Agency", "ReportNo", "Description", "Status", "IncidentType") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', seed_incidents)
        conn.commit()

    cursor.execute('CREATE TABLE IF NOT EXISTS "Regulators" ("RegID" INTEGER PRIMARY KEY AUTOINCREMENT, "Country" TEXT, "Region" TEXT, "Agency" TEXT, "Role" TEXT, "AppliesTo" TEXT)')
    _seed_regulators(cursor)
    _apply_regulator_urls(cursor)
    cursor.execute('CREATE TABLE IF NOT EXISTS "IncidentFiles" ("FileID" INTEGER PRIMARY KEY AUTOINCREMENT, "IncidentID" INTEGER, "FileName" TEXT, "StoredName" TEXT, "Kind" TEXT, "Note" TEXT, "Uploaded" TEXT)')
    try: cursor.execute('ALTER TABLE "IncidentFiles" ADD COLUMN "Encrypted" INTEGER DEFAULT 0')
    except sqlite3.OperationalError: pass
    conn.commit()

    cursor.execute('CREATE TABLE IF NOT EXISTS "ServiceCompanies" ("CompanyID" INTEGER PRIMARY KEY AUTOINCREMENT, "CompanyName" TEXT, "ContactPerson" TEXT, "Phone" TEXT, "Email" TEXT, "Specialty" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Suppliers" ("SupplierID" INTEGER PRIMARY KEY AUTOINCREMENT, "SupplierName" TEXT, "Category" TEXT, "LeadTimeDays" INTEGER, "Phone" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Employees" ("EmpID" INTEGER PRIMARY KEY AUTOINCREMENT, "EmpName" TEXT, "Role" TEXT, "Specialty" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Completed_Work_Orders" ("HistoryID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "TaskName" TEXT, "DateCompleted" TEXT, "TechnicianName" TEXT, "LaborHours" REAL, "PartsUsed" TEXT, "TotalCost" REAL, "Notes" TEXT)')
    for _col, _typ in (("FailureMode", "TEXT"), ("FailureCause", "TEXT"), ("FailureMechanism", "TEXT"), ("DowntimeHours", "REAL"), ("MeterReading", "TEXT")):
        try: cursor.execute(f'ALTER TABLE "Completed_Work_Orders" ADD COLUMN "{_col}" {_typ}')
        except sqlite3.OperationalError: pass   # already there
    cursor.execute('CREATE TABLE IF NOT EXISTS "Audit_Log" ("LogID" INTEGER PRIMARY KEY AUTOINCREMENT, "WhenTS" TEXT, "UserName" TEXT, "Action" TEXT, "TableName" TEXT, "RecordKey" TEXT, "Detail" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "WorkOrders" ("WorkOrderID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "ServiceDate" TEXT, "MyCompany" TEXT, "Description" TEXT, "TotalCost" REAL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Asset_Attributes" ("AttrID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "AttributeName" TEXT, "Value" TEXT, "Notes" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Asset_Parts" ("PartID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "PartHeading" TEXT, "PartDescription" TEXT, "Supplier" TEXT, "PowerUsage" TEXT, "Inventory" TEXT, "Status" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Inventory_Parts" ("PartID" INTEGER PRIMARY KEY AUTOINCREMENT, "PartNumber" TEXT UNIQUE, "Description" TEXT, "Location" TEXT, "Supplier" TEXT, "QtyOnHand" REAL DEFAULT 0, "ReorderPoint" REAL DEFAULT 0, "ReorderQty" REAL DEFAULT 0, "UnitCost" REAL DEFAULT 0, "AssetGroup" TEXT)')
    try: cursor.execute('ALTER TABLE "Inventory_Parts" ADD COLUMN "AssetGroup" TEXT')
    except sqlite3.OperationalError: pass
    cursor.execute('CREATE TABLE IF NOT EXISTS "Inventory_Moves" ("MoveID" INTEGER PRIMARY KEY AUTOINCREMENT, "PartID" INTEGER, "MoveDate" TEXT, "Kind" TEXT, "Qty" REAL, "BalanceAfter" REAL, "AssetID" TEXT, "Note" TEXT, "UserName" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Asset_Components" ("ComponentID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "ComponentName" TEXT, "PartNumber" TEXT, "ConditionStatus" TEXT, "Notes" TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS "Preventive_Schedules" ("TaskID" INTEGER PRIMARY KEY AUTOINCREMENT, "AssetID" TEXT, "TabGroup" TEXT, "TaskName" TEXT, "Date_Last_Done" TEXT, "Meter_At_Last" TEXT, "Days_Between" TEXT, "Meter_Between" TEXT)')

    cursor.execute("PRAGMA table_info('Preventive_Schedules');")
    existing_sched_cols = [col[1] for col in cursor.fetchall()]
    for col, col_type in [("ToolsNeeded", "TEXT"), ("ManHours", "REAL DEFAULT 0.0"), ("TaskDescription", "TEXT"), ("PersonnelQualifications", "TEXT"), ("SafetyPrecautions", "TEXT"), ("EstimatedPartsCost", "REAL DEFAULT 0.0"), ("RequiredConsumables", "TEXT")]:
      if col not in existing_sched_cols:
        cursor.execute(f'ALTER TABLE "Preventive_Schedules" ADD COLUMN "{col}" {col_type}')

    for col, col_type in [("Current_Meter", "INTEGER DEFAULT 0"), ("Disregard_Dates", "INTEGER DEFAULT 0"), ("Attr1_Label", "TEXT"), ("Attr1_Val", "REAL DEFAULT 0"), ("Attr2_Label", "TEXT"), ("Attr2_Val", "REAL DEFAULT 0"), ("Attr3_Label", "TEXT"), ("Attr3_Val", "REAL DEFAULT 0"), ("Attr4_Label", "TEXT"), ("Attr4_Val", "REAL DEFAULT 0"), ("Attr5_Label", "TEXT"), ("Attr5_Val", "REAL DEFAULT 0"), ("Grease_Nipples", "INTEGER DEFAULT 0"), ("Major_Motor", "TEXT"), ("Major_Transmission", "TEXT"), ("Major_RearEnd", "TEXT"), ("Major_Winch", "TEXT"), ("Major_TransferCase", "TEXT"), ("Major_Tires", "TEXT"), ("Part1_Label", "TEXT"), ("Part2_Label", "TEXT"), ("Part3_Label", "TEXT"), ("Part4_Label", "TEXT"), ("Part5_Label", "TEXT"), ("Part6_Label", "TEXT"), ("Date_Acquired", "TEXT"), ("Warranty_Expires", "TEXT"), ("Warranty_Years", "REAL"), ("Warranty_Hours", "REAL"), ("Warranty_Provider", "TEXT"), ("Warranty_Notes", "TEXT"), ("Current_Value", "REAL DEFAULT 0"), ("Purchase_Price", "REAL DEFAULT 0"), ("Deprec_Method", "TEXT"), ("Depreciable_Life", "TEXT"), ("Plate_Number", "TEXT"), ("Incident_Memo", "TEXT"), ("Insurance_Policy", "TEXT"), ("Insurance_Premium", "REAL DEFAULT 0.0"), ("Salvage_Value", "REAL DEFAULT 0.0"), ("Lease_Or_Owned", "TEXT DEFAULT 'Owned'"), ("Total_Maintenance_Spend", "REAL DEFAULT 0.0"), ("Checklist_JSON", "TEXT"), ("Checklist_Data_V2", "TEXT"), ("ParentID", "TEXT"), ("NodeLevel", "TEXT")]:   # ParentID / NodeLevel: reserved for the future "tree" (an item can sit under another item); unused for now
      try: cursor.execute(f'ALTER TABLE "Trucks" ADD COLUMN "{col}" {col_type}')
      except sqlite3.OperationalError: pass

    # First run: a brand-new database starts EMPTY. A database that already holds assets
    # keeps the original behavior ("sample" mode) so existing installs are unchanged.
    cursor.execute('CREATE TABLE IF NOT EXISTS "App_Settings" ("Key" TEXT PRIMARY KEY, "Value" TEXT)')
    cursor.execute('SELECT Value FROM "App_Settings" WHERE Key = ?', ("seed_mode",))
    _row = cursor.fetchone()
    if _row is None:
        cursor.execute('SELECT COUNT(*) FROM "Trucks"')
        _mode = "sample" if cursor.fetchone()[0] > 0 else "empty"
        if DEMO_BUILD and _mode == "empty": _mode = "sample"      # the demo starts with the sample data already loaded, and no login screen
        cursor.execute('INSERT INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("seed_mode", _mode))
        # new empty install: ask whether to use logins; existing populated database: logins stay off
        cursor.execute('INSERT OR IGNORE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("login_mode", "unset" if _mode == "empty" else "off"))
    else:
        _mode = _row[0]
    if _mode == "sample":
        if DEMO_BUILD:
            # Demo: load the sample data ONCE. (Re-seeding on every page load would bring deleted sample units straight back.)
            cursor.execute('SELECT 1 FROM "App_Settings" WHERE Key = ?', ("sample_seeded",))
            if cursor.fetchone() is None:
                seed_sample_data(cursor)
                demo_record_sample_fingerprints(cursor)
                cursor.execute('INSERT OR REPLACE INTO "App_Settings" ("Key", "Value") VALUES (?, ?)', ("sample_seeded", "1"))
        else:
            seed_sample_data(cursor)

    conn.commit()

init_db()
_refresh_license()
auto_backup_daily()
require_login()
if DEMO.get("active"):
    st.markdown("<div class='demo-mark'>DEMO</div>", unsafe_allow_html=True)
    st.info(f"**DEMO copy** - {DEMO['days_left']} day(s) left (ends {DEMO['end']}). The sample data is for exploring; "
            f"you can have up to {DEMO_MAX_ASSETS} assets and {DEMO_MAX_GROUPS} asset groups of your own ({demo_assets_used()} and {demo_groups_used()} used). "
            f"A licence from {DEMO_URL} removes the limits and keeps your data.")
elif DEMO.get("expired"):
    st.markdown("<div class='demo-mark'>DEMO</div>", unsafe_allow_html=True)
    st.warning(f"**The {DEMO_DAYS}-day demo has ended.** The app is now **read-only**: your data is safe and you can still view, print and back up. "
               f"To carry on, get a licence at {DEMO_URL} and paste the code under **Users & Security**; everything you entered stays.")
elif LICENSE_READ_ONLY:
    st.warning(f"{LICENSE_INFO['message']} The app is now **read-only**: your data is safe and you can still view, print and back up, "
               "but changes are not saved. Enter a renewed licence code under **Users & Security**.")
_DEMO_SLOT = st.empty()   # full-width place for the demo limit message (see demo_cap_gate)

# --- SIDEBAR ROUTING & LOGIC ---
if "view_mode_override" not in st.session_state: 
    st.session_state.view_mode_override = "Switchboard"

visible_options = ["Switchboard", "Overdue Dashboard", "Checklists", "Sched. Maint.", "WorkOrders (W/O)", "Completed (W/O)", "Warranty Tracking", "Reports/Queries", "Asset Groups", "Parts Inventory", "Suppliers", "Service Co.", "Incident Reports", "Glossary", "Import Data"]
if st.session_state.get("auth_role") == "admin":
    visible_options.extend(["Users & Security", "Settings"])
current_idx = visible_options.index(st.session_state.view_mode_override) if st.session_state.view_mode_override in visible_options else None
if st.session_state.view_mode_override in visible_options and st.session_state.get("main_nav_radio") != st.session_state.view_mode_override:
    st.session_state.main_nav_radio = st.session_state.view_mode_override   # keep the side menu in step with the green buttons
elif st.session_state.view_mode_override not in visible_options:
    # a page reached by a green button but not listed in the side menu (Philosophy, A Pound of Cure, Audit Readiness...):
    # show no selection, so clicking "Switchboard" (or any item) in the side menu always counts as a change
    st.session_state.main_nav_radio = None

# 1. Control Function (Moved to Top)
def nav_callback():
    if st.session_state.main_nav_radio: st.session_state.view_mode_override = st.session_state.main_nav_radio

selected_view = st.sidebar.radio(
    "Control Function", 
    visible_options, 
    key="main_nav_radio",      # its value is set through session state above, so no index= here (it caused a console warning)
    on_change=nav_callback
)

view_mode = st.session_state.view_mode_override

if st.session_state.get("auth_user"):
    _au = st.session_state["auth_user"]
    st.sidebar.caption(f"Signed in as **{_au['FullName']}** ({_au['Role']})")
    if _au["Role"] == "viewer":
        st.sidebar.caption("Read-only account: changes are not saved.")
    with st.sidebar.expander("My account"):
        _op = st.text_input("Current password", type="password", key="acct_old_pw")
        _np = st.text_input("New password", type="password", key="acct_new_pw")
        if st.button("Change Password", key="btn_acct_pw"):
            _ok, _msg = change_own_password(_au["Username"], _op, _np)
            (st.success if _ok else st.error)(_msg)
    if st.sidebar.button("Sign Out", key="btn_sign_out"):
        sign_out()
        st.rerun()

# 2. Acoustics (Managed Playlist)
if "playlist" not in st.session_state:
    # Only tracks that actually exist next to the app; with none, the whole music block stays hidden
    st.session_state.playlist = [t for t in FLAC_TRACKS if os.path.exists(t)]
    st.session_state.current_track_idx = 0

if st.session_state.playlist:
    st.sidebar.markdown("<hr style='margin-top: 5px; margin-bottom: 10px;'>", unsafe_allow_html=True)
    
    c_prev, c_shuf, c_next = st.sidebar.columns(3)
    with c_prev:
        if st.button("⏮️ Prev", use_container_width=True):
            st.session_state.current_track_idx = (st.session_state.current_track_idx - 1) % len(st.session_state.playlist)
            st.rerun()
    with c_shuf:
        if st.button("🔀 Shuffle", use_container_width=True):
            random.shuffle(st.session_state.playlist)
            st.session_state.current_track_idx = 0
            st.rerun()
    with c_next:
        if st.button("⏭ Next", use_container_width=True):
            st.session_state.current_track_idx = (st.session_state.current_track_idx + 1) % len(st.session_state.playlist)
            st.rerun()

    current_file = st.session_state.playlist[st.session_state.current_track_idx]
    st.sidebar.caption(f"🎵 Track {st.session_state.current_track_idx + 1}/{len(st.session_state.playlist)}: {current_file.replace('.flac', '')}")
    
    if os.path.exists(current_file):
        st.sidebar.audio(current_file, format="audio/flac")
    else:
        st.sidebar.warning(f"Audio file not found: {current_file}")

# 3. Asset Group (Moved to Bottom)
st.sidebar.markdown("---")
with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT Category FROM "Trucks" WHERE Category IS NOT NULL AND Category != ""')
    db_cats = sorted([row[0] for row in cursor.fetchall() if row[0]], key=str.lower)

active_categories = db_cats if db_cats else FULL_CATEGORIES_LIST

if "active_asset_group" not in st.session_state or st.session_state.active_asset_group not in active_categories:
    # On start-up, open on Longevity and Awareness (it applies to everybody); otherwise the first group in the list
    _ov0 = _sector_overrides()
    _lon0 = [_g for _g in active_categories if sector_of(_g, _ov0) == "Longevity and Awareness"]
    st.session_state.active_asset_group = ("Humans" if "Humans" in _lon0 else _lon0[0]) if _lon0 else active_categories[0]

def _short_group(_g):
    """Shorter sidebar labels only (the real group names in the database are unchanged)."""
    if _g.startswith("Preparedness"): return "Preparedness"
    if _g.startswith("Longevity "): return _g[len("Longevity "):]
    return _g
def _short_sector(_s):
    return "Longevity/Awareness" if _s == "Longevity and Awareness" else _s

_ov = _sector_overrides()
_sec_of = {_g: sector_of(_g, _ov) for _g in active_categories}
_sec_opts = all_sectors() + ([SECTOR_UNSORTED] if SECTOR_UNSORTED in _sec_of.values() else [])
if st.session_state.get("active_sector") not in _sec_opts:
    st.session_state.active_sector = _sec_of.get(st.session_state.active_asset_group, _sec_opts[0])
    st.session_state["sector_select"] = st.session_state.active_sector
_w = st.session_state.get("sector_select")
if _w is None or _w == st.session_state.active_sector:
    # No category change by the user this run. If the active group was changed by the program (new, renamed or opened group), follow it.
    _gs = _sec_of.get(st.session_state.active_asset_group)
    if _gs in _sec_opts and _gs != st.session_state.active_sector:
        st.session_state.active_sector = _gs
        st.session_state["sector_select"] = _gs
if st.session_state.get("sector_select") not in _sec_opts: st.session_state["sector_select"] = st.session_state.active_sector
selected_sector = st.sidebar.selectbox("Category", _sec_opts, key="sector_select", format_func=_short_sector)
if selected_sector != st.session_state.active_sector:
    st.session_state.active_sector = selected_sector
    _first = [_g for _g in active_categories if _sec_of.get(_g) == selected_sector]
    if _first: st.session_state.active_asset_group = _first[0]
_groups_here = [_g for _g in active_categories if _sec_of.get(_g) == selected_sector]
if _groups_here:
    selected_category = st.sidebar.radio("Asset Group", _groups_here, format_func=_short_group,
        index=_groups_here.index(st.session_state.active_asset_group) if st.session_state.active_asset_group in _groups_here else 0,
        key="asset_group_radio_" + selected_sector)
else:
    st.sidebar.caption("No groups in this category yet.")
    selected_category = st.session_state.active_asset_group
st.session_state.active_asset_group = selected_category
with st.sidebar.expander("Move this group to another category"):
    _dest_opts = all_sectors() + [SECTOR_UNSORTED]
    if st.session_state.get("move_sector_to") not in _dest_opts:
        st.session_state.pop("move_sector_to", None)   # first time, or that category was removed
    _dest = st.selectbox("Move to", _dest_opts, key="move_sector_to")   # one shared key, so it remembers your last choice
    def _after_move(_grp, _to):
        """After a move: stay in the category you were working in while it still has groups (on the next one); when it is empty, follow the group."""
        _old = st.session_state.get("active_sector")
        _left = [g for g in active_categories if _sec_of.get(g) == _old and g != _grp]
        if _left and _old != _to:
            st.session_state.active_sector = _old
            st.session_state["sector_select"] = _old
            st.session_state.active_asset_group = _left[0]
            st.toast(f"Moved '{_grp}' to {_to}. {len(_left)} left in {_short_sector(_old)}.")
        else:
            st.session_state.active_sector = _to
            st.session_state["sector_select"] = _to
            st.toast(f"Moved '{_grp}' to {_to}.")
    def _do_move_group(_grp, _to):
        import json as _json
        try:
            _ov2 = _sector_overrides(); _ov2[_grp] = _to
            set_setting("sector_map", _json.dumps(_ov2))
            _after_move(_grp, _to)
            st.session_state.pop("move_err", None)
        except Exception as _e:
            st.session_state["move_err"] = f"Could not save: {_e}"
    st.button("Move", key="btn_move_sector", on_click=_do_move_group, args=(selected_category, _dest))
    st.markdown("**Make New Category?**")
    _newcat = st.text_input("New Categ. <22", key="new_sector_name", max_chars=22)
    def _do_new_category(_grp):
        import json as _json
        _nm = st.session_state.get("new_sector_name", "").strip()
        _have = [c.lower() for c in all_sectors()] + [SECTOR_UNSORTED.lower()]
        if not _nm:
            st.session_state["move_err"] = "Type a name for the new category first."
        elif _nm.lower() in _have:
            st.session_state["move_err"] = f"A category called '{_nm}' already exists. Pick it in the Move to list instead."
        elif len(custom_sectors()) >= MAX_CUSTOM_SECTORS:
            st.session_state["move_err"] = f"You can make up to {MAX_CUSTOM_SECTORS} categories of your own."
        else:
            try:
                set_setting("custom_sectors", _json.dumps(custom_sectors() + [_nm]))
                _ov3 = _sector_overrides(); _ov3[_grp] = _nm
                set_setting("sector_map", _json.dumps(_ov3))
                _after_move(_grp, _nm)
                st.session_state["move_sector_to"] = _nm
                st.session_state["new_sector_name"] = ""
                st.session_state.pop("move_err", None)
            except Exception as _e:
                st.session_state["move_err"] = f"Could not save: {_e}"
    st.button("Create category and move group", key="btn_new_sector", on_click=_do_new_category, args=(selected_category,))
    if selected_sector in custom_sectors():
        st.caption(f"Your category '{selected_sector}' can be renamed or removed. The seven built-in categories cannot.")
        _ren = st.text_input("Rename to <22", value=selected_sector, key="ren_sector_" + selected_sector, max_chars=22)
        def _do_rename_category(_old, _new):
            import json as _json
            _new = (_new or "").strip()
            _others = [c.lower() for c in all_sectors() if c != _old] + [SECTOR_UNSORTED.lower()]
            if not _new:
                st.session_state["move_err"] = "Type a name first."
            elif _new.lower() in _others:
                st.session_state["move_err"] = f"A category called '{_new}' already exists."
            elif _new != _old:
                try:
                    set_setting("custom_sectors", _json.dumps([(_new if c == _old else c) for c in custom_sectors()]))
                    _ov4 = {g: (_new if s == _old else s) for g, s in _sector_overrides().items()}
                    set_setting("sector_map", _json.dumps(_ov4))
                    st.session_state.active_sector = _new
                    st.session_state["sector_select"] = _new
                    st.session_state.pop("move_err", None)
                except Exception as _e:
                    st.session_state["move_err"] = f"Could not save: {_e}"
        def _do_remove_category(_old):
            import json as _json
            try:
                set_setting("custom_sectors", _json.dumps([c for c in custom_sectors() if c != _old]))
                _ov5 = {g: s for g, s in _sector_overrides().items() if s != _old}
                set_setting("sector_map", _json.dumps(_ov5))
                st.session_state.pop("active_sector", None)
                st.session_state.pop("sector_select", None)
                st.session_state.pop("move_err", None)
            except Exception as _e:
                st.session_state["move_err"] = f"Could not save: {_e}"
        st.button("Rename category", key="btn_ren_sector", on_click=_do_rename_category, args=(selected_sector, _ren))
        st.button("Remove category", key="btn_rem_sector", on_click=_do_remove_category, args=(selected_sector,))
        st.caption("Removing a category does not delete any groups. They go back to the category the app would choose, or Unsorted.")
    if st.session_state.get("move_err"): st.error(st.session_state["move_err"])

# One standard button width on every screen except the Switchboard (which was sized separately). 230px fits the usual labels on one line; a longer
# label wraps to a second line. The cap never widens a button beyond its own column, and the small arrow buttons (primary) are left as they are.
# The style is written into the sidebar so it takes no room in the main area.
if view_mode != "Switchboard":
    with st.sidebar:
        st.markdown("<style>div.stButton > button:not([kind='primary']), div.stDownloadButton > button, div.stFormSubmitButton > button "
                    "{ width: 230px !important; max-width: 100% !important; }</style>", unsafe_allow_html=True)

if "last_category" not in st.session_state or st.session_state.last_category != selected_category:
  st.session_state.last_category = selected_category
  st.session_state.unit_idx = 0
  st.session_state.chk_unit_idx = 0

# Gives every drop-down box a pale green fill, a green border and the same 44px height as the buttons. This looks the box up on the page itself,
# so it keeps working however Streamlit builds the inside of its drop-downs. Harmless if it cannot reach the page.
components.html("""<script>
(function () {
  try {
    var P = window.parent, d = P.document;
    if (P.__oopSelectStyler) return;
    P.__oopSelectStyler = true;
    var queued = false;
    function fix() {
      queued = false;
      d.querySelectorAll('[data-testid="stSelectbox"]').forEach(function (sb) {
        if (sb.querySelector('[data-oop-sel]')) return;
        var els = sb.querySelectorAll('div');
        for (var i = 0; i < els.length; i++) {
          var r = els[i].getBoundingClientRect();
          if (r.height < 24 || r.width < 60) continue;
          var bg = P.getComputedStyle(els[i]).backgroundColor;
          if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
            var e = els[i];
            e.setAttribute('data-oop-sel', '1');
            e.style.setProperty('background-color', '#f4f8f4', 'important');
            e.style.setProperty('border', '1px solid #1b5e20', 'important');
            e.style.setProperty('border-radius', '6px', 'important');
            e.style.setProperty('min-height', '44px', 'important');
            e.style.setProperty('box-sizing', 'border-box', 'important');
            e.style.setProperty('align-items', 'center', 'important');
            e.style.setProperty('text-align', 'center', 'important');
            e.querySelectorAll('div').forEach(function (c) { c.style.setProperty('text-align', 'center', 'important'); });
            break;
          }
        }
      });
    }
    function queue() { if (!queued) { queued = true; P.requestAnimationFrame(fix); } }
    new P.MutationObserver(queue).observe(d.body, { childList: true, subtree: true });
    queue();
  } catch (err) {}
})();
</script>""", height=0)

ARCH_HTML = r'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body { font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 14px; background: #fcfcfc; color: #222; }
  .wrap { max-width: 980px; margin: 0 auto; }
  .layer { margin: 0 0 4px 0; }
  .layer h4 { margin: 0 0 6px 4px; font-size: 13px; letter-spacing: .04em; text-transform: uppercase; color: #555; }
  .row { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
  .box { background: #fff; border: 2px solid #4472c4; border-radius: 8px; padding: 9px 14px; font-size: 15px; font-weight: bold; text-align: center; min-width: 120px; cursor: help; }
  .edge { border-color: #d9534f; } .plant { border-color: #7030a0; } .erp { border-color: #0275d8; }
  .planned { border-style: dashed; }
  .arrow { text-align: center; color: #666; font-size: 14px; line-height: 1.25; margin: 6px 0; }
  .arrow b { font-size: 22px; display: block; color: #444; }
  .ounce { border: 4px solid #d4af37; background: #fff7d6; border-radius: 12px; padding: 12px 16px; margin: 4px auto; max-width: 760px; text-align: center; }
  .ounce .t { font-size: 22px; font-weight: bold; }
  .ounce .m { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 10px; }
  .ounce .m span { background: #fff; border: 1px solid #c9a227; border-radius: 6px; padding: 5px 10px; font-size: 13px; font-weight: bold; }
  .ounce .n { font-size: 13px; margin-top: 10px; color: #444; }
  .legend { margin: 14px 0 6px; font-size: 13px; color: #444; text-align: center; }
  .legend i { display: inline-block; width: 34px; border-top: 3px solid #555; vertical-align: middle; margin: 0 6px 0 14px; }
  .legend i.d { border-top-style: dashed; }
  .cols { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 16px; }
  .card { flex: 1 1 280px; background: #fff; border: 1px solid #d3d3d3; border-radius: 8px; padding: 12px 14px; font-size: 14px; line-height: 1.45; }
  .card h3 { margin: 0 0 6px 0; font-size: 16px; }
  .qr { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 8px; }
  .qr .box { border-color: #1b5e20; border-style: dashed; font-weight: normal; font-size: 14px; max-width: 220px; }
</style></head><body><div class="wrap">

<div class="layer"><h4>1. On the equipment (sensors)</h4>
 <div class="row">
  <div class="box" title="Monitors physical limits and mechanical engagement.">Contact sensor</div>
  <div class="box" title="Tracks hydraulic and pneumatic pressures.">Pressure transmitter</div>
  <div class="box" title="Monitors temperatures and coolant loops.">Temperature probe</div>
  <div class="box" title="Detects bearing wear and abnormal vibration.">Vibration sensor</div>
  <div class="box" title="Monitors fluid and inventory levels.">Level sensor</div>
 </div></div>
<div class="arrow"><b>&darr;</b></div>

<div class="layer"><h4>2. At the machine (edge)</h4>
 <div class="row">
  <div class="box edge" title="Wiring and signal conditioning.">Electrical circuits</div>
  <div class="box edge" title="A local controller (PLC or RTU) that processes signals before sending them on.">Onboard logic (PLC / RTU)</div>
  <div class="box edge" title="A gateway that turns serial signals into network data.">Communications gateway</div>
  <div class="box edge" title="Encryption, firewalls and secure tunnels protect the connection.">Cyber security</div>
 </div></div>
<div class="arrow"><b>&darr;</b>secure data stream</div>

<div class="layer"><h4>3. Plant systems you may already have</h4>
 <div class="row">
  <div class="box plant" title="Supervisory Control and Data Acquisition: real-time monitoring and alarms.">SCADA</div>
  <div class="box plant" title="A time-series database that archives sensor readings.">Historian</div>
  <div class="box plant" title="Manufacturing Execution System: tracks production.">MES</div>
 </div></div>
<div class="arrow"><b style="color:#999">&#8675;</b>planned: live meter and run-hour readings, and &ldquo;this reading is out of range&rdquo; alerts, passed to Ounce</div>

<div class="ounce">
  <div class="t">&#11088; An Ounce of Prevention &#11088;</div>
  <div class="m"><span>Checklists</span><span>Scheduled maintenance</span><span>Work orders</span><span>Overdue dashboard</span><span>Parts inventory</span><span>Warranty tracking</span><span>Reports</span></div>
  <div class="n"><b>Today:</b> meter readings and checklist results are entered by your people (or imported from a spreadsheet). No sensors or network are needed.</div>
</div>
<div class="arrow"><b style="color:#999">&#8675;</b>planned: maintenance spend and parts costs sent to accounting</div>

<div class="layer"><h4>4. Business systems</h4>
 <div class="row"><div class="box erp planned" title="Accounting and enterprise planning: payroll, finance and supply chain.">Accounting / ERP</div></div></div>

<div class="legend"><i></i>works today &nbsp;&nbsp;<i class="d"></i>planned, not part of version 1</div>

<div class="cols">
 <div class="card"><h3>Start simple</h3>Ounce works like a digital clipboard. Your people do the rounds, tick the checklist and enter meter readings, and Ounce tells you what is due, overdue or expiring. Nothing else has to be in place.</div>
 <div class="card"><h3>Grow when you are ready</h3>If your plant already has SCADA or a historian, meter readings and out-of-range alerts could one day feed Ounce automatically, so the schedule follows real running time and real condition instead of the calendar alone.</div>
 <div class="card"><h3>Why the order matters</h3>Preventive maintenance (the schedule) is the foundation. Condition monitoring (sensors) builds on it. Ounce is designed so you can add the second without redoing the first.</div>
</div>

<div class="layer" style="margin-top:18px"><h4>Planned: QR-code checklists</h4>
 <div class="qr">
  <div class="box">1. A tough QR tag is fixed to the machine</div>
  <div class="box">2. The operator scans it with their own phone</div>
  <div class="box">3. That machine&rsquo;s checklist opens, ready to tick</div>
 </div>
 <div class="arrow" style="margin-top:8px">Not part of version 1. It would remove the need for a rugged tablet at the machine.</div>
</div>

</div></body></html>
'''

_CLAIMS_CHECKED = [
    ('Drinking about 1.5 to 3.5 cups of coffee a day goes with up to 30% lower risk of dying from any cause (Annals of Internal Medicine, 2022).', 'Emerging', 'Mostly accurate', 'Real study: over 170,000 UK adults, about 7 years of follow-up, observational, so it cannot show coffee causes the lower risk. Decaf did about the same as caffeinated. Benefit tapered above about 4.5 cups. The sugar in the coffee studied was low (about one teaspoon).', 'Web'),
    ('A review of more than 1,000 studies found the chemicals made in roasting coffee were not a significant cancer risk.', 'Moderate', 'Accurate', "Matches the 2016 IARC reassessment, which moved coffee off the 'possibly carcinogenic' list. Very hot drinks are a separate issue.", 'General knowledge'),
    ('People on GLP-1 weight-loss drugs should eat up to about 0.68 g of protein per pound of body weight (a 2024 study in Obesity).', 'Emerging', 'Unverified', 'I could not find a 2024 Obesity paper with that figure. A 2025 joint advisory from several obesity and nutrition societies calls for adequate protein plus strength training but gives no number on the page I read, and describes itself as consensus-based. The figure is well above ordinary adult advice, so it is not for people with kidney disease or without a dietitian.', 'Web'),
    ('Patients who walked more than 7,500 steps a day before surgery cut their risk of complications by half (attributed to the Journal of the American College of Surgeons).', 'Emerging', 'Partly misattributed', 'A 2023 American College of Surgeons congress study reported 51% lower complication risk with more than 7,500 steps a day before surgery, a presentation of observational data. The Journal of the American College of Surgeons paper that press coverage links to looked at steps after surgery (18% lower odds of complications per extra 1,000 steps, 1,965 patients). Both are associations.', 'Web'),
    ('Women who vacation at least twice a year are about eight times less likely to have a heart attack than women who go once every six years.', 'Emerging', 'Overstated', "The old finding is from the Framingham women: those who took a vacation once every six years or less were almost eight times MORE likely to develop heart disease than those who vacationed twice a year. That is a relative risk from an observational study, and it is likely confounded by income, health and stress. The magazine's 'eight times less likely' is the same finding turned around. Vacations are good for you, but this number is not a promise.", 'Web'),
    ('Cold-water immersion benefits add up, with as few as 11 total minutes in a cold bath a week.', 'Emerging', 'Unverified', 'The best-known source is a small 2021 study of eight experienced winter swimmers against eight controls, all men, which shows differences but not cause. I could not confirm the 11-minute figure in the source I read. The magazine itself warns about cold shock and heart strain, which is right: skip it with heart disease, high blood pressure or on your own.', 'Web'),
    ('The MIND diet (greens, berries, beans, poultry, nuts, fish) was designed to keep your brain sharp, with blueberries, beans and poultry singled out.', 'Emerging', 'Overstated', "Observational studies linked the MIND diet to slower decline, but the first large randomised trial (New England Journal of Medicine, 2023, three years) found no better cognitive result than a comparison diet; both groups improved a little and both ate somewhat fewer calories. Fruits, vegetables, beans and fish are still sensible, but 'proven brain diet' is too strong.", 'Web'),
    ('Isometric exercise (holding a position) may lower blood pressure more than aerobic exercise.', 'Moderate', 'Accurate', 'A 2023 network meta-analysis in the British Journal of Sports Medicine (270 randomised trials, about 15,800 people) ranked isometric training best for systolic pressure. Check with a doctor first if your pressure is high; do not hold your breath.', 'Web'),
    ('People diagnosed with dementia had up to 10 times as much microplastic in their brains (Nature Medicine).', 'Emerging', 'Uncertain', 'The February 2025 paper measured about 4.9 mg of micro and nanoplastics per gram in 24 brains. After publication, outside experts questioned the method (possible false positives from brain fat, possibly overestimated mass), and duplicated supplementary images were flagged (the lead author called it clerical). I did not confirm the dementia comparison in the source I read. Treat it as an early signal.', 'Web'),
    ('Microwaving some plastic containers can release more than 2 billion nanoplastic particles per square centimetre (Environmental Science and Technology, 2023).', 'Emerging', 'Accurate', 'Lab study at the University of Nebraska on polypropylene baby-food containers and a polyethylene pouch, three minutes at full power with water or a weak acid. Health effects are unclear; the cell-culture result was in kidney cells, not people. A precaution (glass or ceramic for heating) is cheap.', 'Web'),
    ('About 17 million US adults who were advised to take a statin no longer need one (JAMA Internal Medicine, June 2024).', 'Moderate', 'Mostly accurate', "The study modelled eligibility with the newer PREVENT risk calculator: eligible adults fell from about 45.4 million to 28.3 million, a drop of about 17.3 million. It is cross-sectional and a calculator change, not proof that stopping statins is safe. I did not confirm the '4 million currently on statins' figure. Never stop a statin without your doctor.", 'Web'),
    ('A review of 63 studies from 22 countries (1994 to 2022) found no rise in brain cancer from cell phone use (WHO-commissioned).', 'Moderate', 'Accurate', "Karipidis and colleagues' systematic review for the WHO included 63 observational studies and found no association with head cancers. Observational and long-term effects are still being watched; the article's cautious tone is fair.", 'Web'),
    ('Zinc (found in oatmeal) may shorten a cold, and selenium in Brazil nuts is a powerful antioxidant.', 'Moderate (for zinc lozenges), Traditional (for food zinc)', 'Misleading', "The evidence for shorter colds is for zinc lozenges or syrup started within a day or so of symptoms, with mixed results and side effects such as nausea. Food zinc has not been shown to shorten colds. The app's Home remedies box says the same.", 'General knowledge'),
    ('Local honey has not been proven to relieve pollen allergies.', 'Dropped (for allergies)', 'Accurate', 'Trials have not shown a benefit for allergy symptoms. Honey for cough in older children and adults has better support (see Home remedies box).', 'General knowledge'),
    ('No reputable study has found a link between vaccines and autism.', 'Strong', 'Accurate', 'Large studies across many countries agree.', 'General knowledge'),
    ('Bright light for 30 minutes each morning can help seasonal affective disorder.', 'Moderate', 'Accurate', 'Standard first-line option for seasonal depression, usually a 10,000 lux lamp. Check with a doctor if you have bipolar disorder or eye disease.', 'General knowledge'),
    ('Doctors no longer recommend breast self-exams because studies showed they did not reduce deaths.', 'Moderate', 'Accurate', 'Matches current screening guidance. Knowing what is normal for you and reporting changes is still advised.', 'General knowledge'),
    ('Decades of research have proven the health benefits of seed oils.', 'Moderate', 'Mostly accurate', "Replacing saturated fat with unsaturated oils lowers heart risk in trials. 'Proven' overstates how fine the evidence is for specific oils, and what you eat them with matters.", 'General knowledge'),
    ('Intermittent fasting works about the same as ordinary calorie cutting for weight loss, and may be easier for some people.', 'Strong', 'Accurate', 'Trials show similar weight loss; longevity benefits are not shown in people.', 'General knowledge'),
    ('Ten minutes of brisk walking can lower anxiety; mindful walking and novelty may help anxiety and mood.', 'Emerging', 'Mostly accurate', 'Exercise in general reduces anxiety in trials; the ten-minute and novelty details come from small studies.', 'General knowledge'),
    ('Saying hello to up to six people in your neighbourhood increases well-being.', 'Emerging', 'Mostly accurate', "Fits the research on 'weak ties' (brief contact with acquaintances and strangers is linked to better mood). Small studies, association. Added to the app as a weekly checklist item.", 'General knowledge'),
    ('Doing a weekly act of kindness and gratitude strengthens connection (a study of more than 4,000 people in three countries; a 2024 meta-analysis).', 'Emerging', 'Not checked', 'Plausible and consistent with the wider research, but I did not read the studies. The app already has a weekly appreciation habit.', 'Not checked'),
    ('A weighted silk eye pillow or blanket (deep-pressure therapy) may help you fall asleep.', 'Emerging', 'Not checked', 'Weighted blankets have mixed, small trials, mostly in specific groups. I could not open the review I searched for.', 'Not checked'),
    ('Fidget rings and fidgeting may ease anxiety and boost focus.', 'Emerging', 'Not checked', 'Research on fidgeting is mixed (some help for attention, some distraction). Not checked in detail.', 'Not checked'),
    ('Red-light therapy research is limited and large randomised studies are needed.', 'Emerging', 'Accurate', 'The magazine itself is appropriately cautious.', 'General knowledge'),
    ('GLP-1 drugs may also reduce risk of heart attack, stroke and more, but over a third quit within a year (JAMA Network Open).', 'Moderate (heart outcomes in people with obesity and heart disease), Emerging (others)', 'Not checked', 'The heart benefit has a large randomised trial behind it for semaglutide; the other benefits are early. The dropout figure was not checked.', 'Not checked'),
    ('Organic tampons are not safer: a study found 12 metals, including lead and arsenic, in popular tampons.', 'Emerging', 'Not checked', 'A real 2024 study; the health meaning of the amounts is unknown. Not checked in detail.', 'Not checked'),
    ('Bacteria move onto dropped food in less than a second (so the five-second rule is a myth).', 'Moderate', 'Accurate', 'Matches the Rutgers research.', 'General knowledge'),
    ('Studies show vocabulary, verbal reasoning and math stay the same or improve as we age.', 'Moderate', 'Overstated', 'The Seattle Longitudinal Study (Schaie) found vocabulary and verbal ability hold up or rise into the 60s and beyond, but reasoning, spatial skills and speed decline from midlife. Math is not a safe fit on that list.', 'General knowledge'),
    ('A Princeton study found people do tasks better in organised spaces than chaotic ones.', 'Emerging', 'Mostly accurate', 'A real 2011 imaging study, small, showing clutter competes for attention. It says nothing about long-term brain health.', 'General knowledge'),
    ('Eating one to two servings of leafy greens a day goes with a slower mental decline (Neurology).', 'Emerging', 'Mostly accurate', 'Observational (Rush Memory and Aging Project, 2018), so it cannot prove greens are the cause. Eating more vegetables is sensible anyway.', 'General knowledge'),
    ('Listening to classical music boosts the brain at any age (University of Helsinki, Scientific Reports).', 'Emerging', 'Overstated', "A small gene-expression study of listeners, not a test of memory or thinking. Music is pleasant and may help mood; 'boosts the brain' goes further than the data.", 'General knowledge'),
    ('Brain training and puzzles can lower dementia risk (ACTIVE trial).', 'Moderate', 'Overstated', 'The 20-year follow-up found a benefit only for speed-of-processing training with booster sessions: about 25% lower risk of a dementia diagnosis. Memory and reasoning training showed none. The trainer was commercially linked. It does not show crosswords or general puzzles help.', 'Web'),
    ('A structured lifestyle programme (exercise, diet, social and mental activity, health checks) protects thinking skills (US POINTER).', 'Moderate', 'Mostly accurate', 'The two-year US POINTER trial found a modest cognitive gain, larger with the structured, coached programme than the self-guided one. Modest, short, and it does not show dementia is prevented.', 'Web'),
    ('Colouring mandala-like designs reduces stress.', 'Emerging', 'Overstated', 'Small studies show lower anxiety after colouring, but it is similar to other simple calming activities. Pleasant, cheap, harmless; not a special treatment.', 'General knowledge'),
    ('Overwhelming research shows the Mediterranean diet helps the heart, weight and cancer prevention.', 'Moderate', 'Overstated', 'Heart benefit is the strong part (PREDIMED: about 30% fewer heart events; the trial was retracted and republished in 2018 after randomisation problems, with similar results). Weight and cancer evidence is weaker and mostly observational.', 'Web'),
    ('Swapping saturated fats such as butter for olive oil goes with lower heart disease deaths (JACC).', 'Moderate', 'Mostly accurate', 'A large 2022 cohort found about 19% lower cardiovascular mortality with more olive oil. Observational, but it fits trials on replacing saturated fat.', 'General knowledge'),
    ('A review in Oncotarget found people in Mediterranean countries have lower cancer rates, credited to the diet.', 'Emerging', 'Overstated', 'Comparing countries cannot separate diet from smoking, income, screening and genes. Diet may help, but this design cannot show it.', 'General knowledge'),
    ('Whole grains and their B vitamins protect memory.', 'Emerging', 'Overstated', 'Observational links only. B-vitamin trials have mostly failed to protect thinking in people who are not deficient.', 'General knowledge'),
    ('Beta-carotene from squash reduces the risk of macular degeneration.', 'Emerging', 'Overstated', 'The proven eye result is for the AREDS supplement mix, not food beta-carotene (and beta-carotene supplements raise lung cancer risk in smokers). Orange vegetables are healthy; the eye claim is a stretch.', 'General knowledge'),
]

# --- MAIN SCREEN RENDERING ---
if view_mode != "Monty Python":
    st.session_state.pop("hb_open", None); st.session_state.pop("hb_scroll", None)
if view_mode != "Monty Python": st.session_state.pop("pj_key", None)   # the private journal locks itself when you leave its page
# "Back to A Pound of Cure": offered only on the three pages you can reach from it, and forgotten as soon as you go anywhere else
if view_mode not in ("WorkOrders (W/O)", "Incident Reports", "Parts Inventory"): st.session_state.pop("from_pound", None)
elif st.session_state.get("from_pound"):
    _bp1, _bp2 = st.columns([1.3, 4])
    with _bp1:
        if st.button("← Back to A Pound of Cure", key="btn_back_pound", use_container_width=True):
            st.session_state.pop("from_pound", None); st.session_state.view_mode_override = "Pound of Cure"; st.rerun()
if view_mode == "Switchboard":
  if os.path.exists("BlackMarble_2016_3km.jpg"): st.image("BlackMarble_2016_3km.jpg", use_container_width=True)
  st.markdown("<h2 style='text-align: center; margin-bottom: 25px;'>An Ounce of Prevention — Switchboard</h2>", unsafe_allow_html=True)
  _al_tasks, _al_parts, _al_warr = dashboard_alert_counts([_g for _g in active_categories if _sec_of.get(_g) == selected_sector])
  if _al_tasks or _al_parts or _al_warr:
    _hl = ([f"<b>{_al_tasks}</b> task(s) overdue or due today in {selected_sector}."] if _al_tasks else []) + (["Parts need to be reordered."] if _al_parts else []) \
          + ([f"<b>{_al_warr}</b> warranty(ies) expiring."] if _al_warr else [])
    _open = "Open " + (" or ".join((["Parts"] if _al_parts else []) + ["Overdue Dashboard"])) + "."
    st.markdown("<div style='text-align:center; border:2px solid #c0392b; color:#c0392b; border-radius:6px; padding:8px 10px; margin-bottom:18px; font-weight:bold; font-size:13pt;'>⚠ "
                + " &nbsp;".join(_hl) + " &nbsp;" + _open + "</div>", unsafe_allow_html=True)
  col_sw1, col_sw2, col_sw3 = st.columns(3, gap="large")
  
  with col_sw1:
    st.markdown("<div style='text-align: center; font-size: 13.5pt; font-weight: bold; margin-bottom: 12px;'>Daily Operations</div>", unsafe_allow_html=True)
    if selected_sector == "Longevity and Awareness":
        if st.button("🌱 Habit Builder", key="sw_habit", use_container_width=True):
            st.session_state.view_mode_override = "Monty Python"; st.session_state["hb_open"] = True; st.session_state["hb_scroll"] = True; st.rerun()
    if st.button("Overdue Dashboard", use_container_width=True): st.session_state.view_mode_override = "Overdue Dashboard"; st.rerun()
    if st.button("Checklists", use_container_width=True): st.session_state.view_mode_override = "Checklists"; st.rerun()
    if st.button("Sched. Maint.", use_container_width=True): st.session_state.view_mode_override = "Sched. Maint."; st.rerun()
    if st.button("WorkOrders (W/O)", use_container_width=True): st.session_state.view_mode_override = "WorkOrders (W/O)"; st.rerun()
    if st.button("Completed (W/O)", use_container_width=True): st.session_state.view_mode_override = "Completed (W/O)"; st.rerun()
    if st.button("Incident Reports", use_container_width=True): st.session_state.view_mode_override = "Incident Reports"; st.rerun()
    
  with col_sw2:
    st.markdown("<div style='text-align: center; font-size: 13.5pt; font-weight: bold; margin-bottom: 12px;'>Equipment & Lists</div>", unsafe_allow_html=True)
    if st.button("Asset Groups", use_container_width=True): st.session_state.view_mode_override = "Asset Groups"; st.rerun()
    if st.button("Parts Inventory", use_container_width=True): st.session_state.view_mode_override = "Parts Inventory"; st.rerun()
    if st.button("Suppliers", use_container_width=True): st.session_state.view_mode_override = "Suppliers"; st.rerun()
    if st.button("Service Co.", use_container_width=True): st.session_state.view_mode_override = "Service Co."; st.rerun()
    if st.button("Warranty Tracking", use_container_width=True): st.session_state.view_mode_override = "Warranty Tracking"; st.rerun()
    if st.button("Glossary", use_container_width=True): st.session_state.view_mode_override = "Glossary"; st.rerun()
    if st.button("How Ounce Fits In", use_container_width=True): st.session_state.view_mode_override = "System Architecture"; st.rerun()
    
  with col_sw3:
    st.markdown("<div style='text-align: center; font-size: 13.5pt; font-weight: bold; margin-bottom: 12px;'>Reports & System</div>", unsafe_allow_html=True)
    if st.button("Reports/Queries", use_container_width=True): st.session_state.view_mode_override = "Reports/Queries"; st.rerun()
    if st.button("Philosophy", use_container_width=True): st.session_state.view_mode_override = "Monty Python"; st.rerun()
    if st.button("A Pound of Cure", use_container_width=True): st.session_state.view_mode_override = "Pound of Cure"; st.rerun()
    if st.button("Audit Readiness", use_container_width=True): st.session_state.view_mode_override = "Audit Road"; st.rerun()
    if st.button("Back Up Database", use_container_width=True):
        try: st.success(f"Backup saved: {os.path.basename(backup_database())}")
        except Exception as e: st.error(f"Backup failed: {e}")
    if st.button("Exit Program", use_container_width=True):
        st.success("Session Terminated. It is now safe to close this browser tab.")
        st.stop()

  # First-run welcome: shown only while the database has no assets at all
  if is_empty_install():
    st.info("**Welcome to An Ounce of Prevention.** Your database is empty. Add your own equipment under "
            "**Asset Groups**, or load the sample data (dozens of asset groups and example units with "
            "checklists and maintenance tasks) to see how everything works. You can start fresh later by "
            "using a new, empty data folder.")
    if st.button("Load Sample Data", key="btn_load_sample"):
        load_sample_data()
        st.success("Sample data loaded.")
        st.rerun()

  # Backup notice sits under the whole button grid, centered, instead of inside one column
  _bk = list_backups()
  if _bk:
    st.markdown(
        f"<div style='text-align: center; color: #6b6b6b; font-size: 0.85rem; margin-top: 18px;'>"
        f"Latest backup: {_bk[0]} &nbsp;|&nbsp; Folder: {get_backup_dir()} &nbsp;|&nbsp; "
        f"a backup is also made automatically once a day</div>",
        unsafe_allow_html=True)

elif view_mode == "System Architecture":
  title_row("🏭 How Ounce Fits In", "btn_sw_page1")
  st.markdown("A picture of where **An Ounce of Prevention** sits between the equipment on the floor and the business systems around it. "
              "Solid boxes work today; dashed items are planned and are **not** part of version 1. Hover over any box for a short explanation.")
  components.html(ARCH_HTML, height=1180, scrolling=True)
  st.markdown("---")
  st.markdown("**Preparing for audits?** See *Audit Readiness* on the Switchboard (Reports & System column).")
  if st.button("Open Audit Readiness", key="arch_to_road"): st.session_state.view_mode_override = "Audit Road"; st.rerun()
elif view_mode == "Fleet Health":
  st.subheader("📊 Industrial Asset Health and Maintenance")
  
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      trucks_df = pd.read_sql('SELECT Maintenance_Protocol, Total_Maintenance_Spend FROM "Trucks"', conn)
      
  total_assets = len(trucks_df)
  total_spend = pd.to_numeric(trucks_df['Total_Maintenance_Spend'], errors='coerce').sum() if 'Total_Maintenance_Spend' in trucks_df.columns else 0.0
  
  pm_count = len(trucks_df[trucks_df['Maintenance_Protocol'] == "Preventive Maintenance (PM)"])
  rx_count = len(trucks_df[trucks_df['Maintenance_Protocol'] == "Corrective / Reactive Maintenance"])
  pdm_count = len(trucks_df[trucks_df['Maintenance_Protocol'] == "Predictive Maintenance (PdM)"])
  
  dash_c1, dash_c2, dash_c3, dash_c4, dash_c5 = st.columns(5)
  dash_c1.metric("Total Active Assets", total_assets)
  dash_c2.metric("Total YTD Spend", f"${total_spend:,.2f}")
  dash_c3.metric("Preventive (PM)", pm_count)
  dash_c4.metric("Predictive (PdM)", pdm_count)
  dash_c5.metric("Reactive (Run-to-Failure)", rx_count, delta="- High Risk", delta_color="inverse")
  
  st.markdown("---")
  
  with st.container():
      st.markdown("### Industrial Maintenance Protocols: Strategic Overview")
      st.info("**An Ounce of Prevention Strategy Mapping:**\n* **Checklists** serve as the front-line for **Predictive Maintenance (PdM)**—gathering condition data and identifying anomalies before failure.\n* **Sched. Maint.** drives our **Preventive Maintenance (PM)** engine—executing highly structured time and usage-based workflows to minimize long-term degradation.")
      st.markdown("""
| Attribute | Preventive Maintenance (PM) | Corrective / Reactive Maintenance | Predictive Maintenance (PdM) |
| :--- | :--- | :--- | :--- |
| **Core Approach** | Time or usage-based scheduling. | Run-to-failure emergency repair. | Condition-based real-time monitoring. |
| **Primary Trigger** | Calendar dates, operational hours, or mileage milestones. | A machine stops working, breaks down, or behaves unsafely. | Sensor data anomalies (e.g., heat spikes, abnormal vibrations). |
| **Workflow State** | Highly planned and structured. | Unplanned, urgent, and high-stress. | Highly planned based on early warning indicators. |
| **Primary Goal** | Minimize asset degradation through regular upkeep. | Restore an offline asset to production as fast as possible. | Fix an asset exactly *before* it fails, maximizing component life. |
| **Typical Tasks** | Oil changes, filter replacements, routine calibrations, belt tightening. | Rebuilding broken gearboxes, patching leaks, replacing blown fuses. | Laser alignments, thermal imaging scans, oil analysis, sensor replacement. |
| **Key Advantage** | Drastically reduces catastrophic failures at a predictable cost. | Low upfront costs; requires no advanced planning or software. | Eliminates unnecessary maintenance; drastically cuts downtime. |
| **Key Disadvantage** | Can lead to "over-maintenance" (replacing perfectly good parts). | High costs due to lost production, rush shipping, and overtime pay. | Expensive upfront investment in IoT sensors, software, and training. |
| **Best Used For** | High-value, critical assets with known wear-and-tear lifespans. | Low-cost, non-critical assets that do not stop production if they fail. | High-criticality, bottleneck assets where downtime costs thousands per minute. |
      """)
  
  st.markdown("---")
  _fl1, _fl2 = st.columns([5, 1.3], gap="small")
  with _fl2:
    if st.button("Switchboard", key="btn_sw_fleet", use_container_width=True):
      st.session_state.view_mode_override = "Switchboard"; st.rerun()

elif view_mode == "Users & Security":
  title_row("🔐 Users & Security", "btn_sw_page2")
  _mode = get_login_mode()
  if _mode != "on" or st.session_state.get("auth_role") == "admin":
    render_license_panel()
  if (_mode != "on" or st.session_state.get("auth_role") == "admin") and get_setting("audit_features", "0") != "1":
    st.caption("An optional audit trail (who did what, and when) is available. Turn it on under Audit Readiness on the Switchboard.")
  if (_mode != "on" or st.session_state.get("auth_role") == "admin") and get_setting("audit_features", "0") == "1":
    with st.expander("🧾 Audit trail: who did what, and when (latest 300 entries)", expanded=False):
      st.caption("Records task sign-offs, breakdown records and incident log saves, with the user and the time. Edits to assets, task schedules and parts are not logged yet. "
                 "With login off, the user shows as '(login off)'. This helps you show auditors what changed; it does not make anyone certified.")
      try:
        with sqlite3.connect(DB_PATH, timeout=20.0) as _ac:
          _alog = pd.read_sql('SELECT WhenTS AS "When", UserName AS "User", Action, TableName AS "Table", RecordKey AS "Record", Detail FROM "Audit_Log" ORDER BY LogID DESC LIMIT 300', _ac)
        if _alog.empty: st.caption("Nothing logged yet.")
        else:
          st.dataframe(_alog, use_container_width=True, hide_index=True)
          st.download_button("Download audit trail (CSV)", data=_alog.to_csv(index=False).encode("utf-8"), file_name="audit_trail.csv", mime="text/csv", key="dl_audit_trail")
      except Exception as _ae:
        st.caption(f"The audit trail could not be read: {_ae}")
  if _mode == "on" and st.session_state.get("auth_role") != "admin":
    st.error("Only administrators can manage users.")
  elif _mode != "on":
    st.info("Login is currently **off**: anyone who opens the app has full access. Create an administrator account to turn it on.")
    with st.form("enable_login_form"):
      _fn = st.text_input("Your full name")
      _un = st.text_input("Administrator username (lowercase)")
      _pw = st.text_input("Password (8 or more characters)", type="password")
      _pw2 = st.text_input("Confirm password", type="password")
      _go = st.form_submit_button("Create Administrator")
    if _go:
      _un = (_un or "").strip().lower()
      _err = validate_new_user(_un, _pw, _pw2)
      if _err: st.error(_err)
      else:
        _ok, _msg = create_user(_un, _fn, "admin", _pw)
        if _ok:
          set_login_mode("on")
          _ok2, _res = attempt_login(_un, _pw)
          if _ok2: st.session_state["auth_user"], st.session_state["auth_role"] = _res, _res["Role"]
          st.rerun()
        else: st.error(_msg)
  else:
    st.markdown("**Roles:** *admin* manages users and can do everything; *technician* uses all the maintenance screens; *viewer* is read-only.")
    _udf = list_users()
    st.dataframe(_udf, use_container_width=True, hide_index=True, row_height=30)
    st.markdown("#### Add a user")
    _aun = st.session_state.get("add_user_n", 0)
    with st.form(f"add_user_form_{_aun}", clear_on_submit=False):
      _c1, _c2 = st.columns(2)
      with _c1:
        _nu = st.text_input("Username (lowercase)")
        _nf = st.text_input("Full name")
      with _c2:
        _nr = st.selectbox("Role", ROLES, index=1)
        _npw = st.text_input("Temporary password (8 or more characters)", type="password")
      _add = st.form_submit_button("Add User")
    if _add:
      _ok, _msg = create_user(_nu, _nf, _nr, _npw)
      (st.success if _ok else st.error)(_msg)
      if _ok: st.session_state["add_user_n"] = _aun + 1; st.rerun()
    st.markdown("#### Manage a user")
    _names = list(_udf["Username"]) if not _udf.empty else []
    if _names:
      _sel = st.selectbox("User", _names, key="manage_user_sel")
      _row = _udf[_udf["Username"] == _sel].iloc[0]
      _m1, _m2 = st.columns(2)
      with _m1:
        _newrole = st.selectbox("Role", ROLES, index=ROLES.index(_row["Role"]) if _row["Role"] in ROLES else 1, key="manage_role")
        if st.button("Save Role", key="btn_save_role"):
          _ok, _msg = update_user(_sel, role=_newrole); (st.success if _ok else st.error)(_msg)
        if int(_row["Active"]):
          if st.button("Deactivate", key="btn_deactivate"):
            _ok, _msg = update_user(_sel, active=False); (st.success if _ok else st.error)(_msg)
            if _ok: st.rerun()
        else:
          if st.button("Reactivate", key="btn_reactivate"):
            _ok, _msg = update_user(_sel, active=True); (st.success if _ok else st.error)(_msg)
            if _ok: st.rerun()
      with _m2:
        _rp = st.text_input("New password for this user", type="password", key="manage_new_pw")
        if st.button("Reset Password", key="btn_reset_pw"):
          _ok, _msg = set_password(_sel, _rp); (st.success if _ok else st.error)(_msg)
        _confirm_del = st.checkbox(f"Yes, permanently delete {_sel}", key="manage_del_confirm")
        if st.button("Delete User", key="btn_delete_user", disabled=not _confirm_del):
          if _sel == current_user_name(): st.error("You cannot delete the account you are signed in with.")
          else:
            _ok, _msg = delete_user(_sel); (st.success if _ok else st.error)(_msg)
            if _ok: st.rerun()
    st.markdown("#### Turn login off")
    st.caption("Everyone who opens the app will then have full access. User accounts are kept.")
    _off_ok = st.checkbox("I understand", key="login_off_confirm")
    if st.button("Turn Login Off", key="btn_login_off", disabled=not _off_ok):
      set_login_mode("off"); sign_out(); st.rerun()

elif view_mode == "Settings":
  title_row("⚙️ Settings", "btn_sw_settings")
  st.caption(f"An Ounce of Prevention, version {APP_VERSION}")
  with st.form("settings_form"):
    _locked = LICENSE_INFO.get("state") in ("valid", "expired") and bool(str(LICENSE_INFO.get("licensee", "") or "").strip())
    if _locked:
        _co = st.text_input("Company name (set by your licence; printed on every printout and new work order)", value=get_company_name(), disabled=True)
        st.caption("This is the name your licence was issued to. To change it, contact BioShip Inc. for a corrected licence.")
    else:
        _co = st.text_input("Company name (printed at the top of every printout and used on new work orders)", value=str(get_setting("company_name", "")))
    _lr = st.number_input("Labor rate ($ per hour)", min_value=0.0, max_value=100000.0, value=float(get_labor_rate()), step=1.0, format="%.2f")
    _bk = st.number_input("Backups to keep (the newest are kept, older ones are deleted)", min_value=1, max_value=1000, value=int(get_backup_keep()), step=1)
    _save = st.form_submit_button("Save Settings")
  if _save:
    if not _locked: set_setting("company_name", (_co or "").strip())
    set_setting("labor_rate", f"{_lr:.2f}")
    set_setting("backup_keep", int(_bk))
    st.success("Settings saved.")
  if str(get_setting("seed_mode", "")) == "sample":
    st.markdown("---")
    st.markdown("#### Demo data")
    st.caption("This database holds the built-in sample equipment. **Refresh sample dates** resets the last-done dates on those sample tasks so the "
               "dashboard shows a believable mix (mostly up to date, some due soon, a few overdue). It touches only the built-in sample assets, never your own, "
               "and makes a backup first. Anything you signed off on the sample assets goes back to the demo schedule.")
    _ok_demo = st.checkbox("Yes, refresh the dates on the sample assets", key="demo_refresh_ok")
    if st.button("Refresh Sample Dates", key="btn_demo_refresh", disabled=not _ok_demo):
      try: _bkp = os.path.basename(backup_database())
      except Exception as _e: _bkp = None; st.error(f"Backup failed, nothing was changed: {_e}")
      if _bkp:
        with sqlite3.connect(DB_PATH, timeout=30.0) as _c:
          _n = stagger_task_dates(_c.cursor(), sample_asset_ids()); _c.commit()
        st.success(f"Refreshed {_n} sample tasks. Backup saved first: {_bkp}.")

  st.markdown("---")
  st.markdown("#### Data: start fresh, reset, or restore")
  st.caption("Every action here saves a full backup first. Your users, passwords, licence code and settings are always kept.")
  _fl = st.session_state.pop("data_flash", None)
  if _fl: (st.success if _fl[0] else st.error)(_fl[1])
  _data_actions = {"Start fresh (empty)": "empty", "Reset to sample data": "sample", "Restore a backup": "restore"}
  _da = _data_actions[st.radio("What do you want to do?", list(_data_actions), key="data_action")]
  if _da == "empty":
    st.caption("Wipes the equipment, tasks, parts, work orders and history, leaving a blank program, as if just installed.")
  elif _da == "sample":
    st.caption("Wipes everything, then loads the built-in sample equipment again with fresh, staggered dates. Handy before recording a demo.")
  else:
    st.caption("Puts the equipment, tasks, parts, work orders and history back the way they were in a saved backup. Work done since then is lost, "
               "but the current data is saved as a backup first, so you can undo this too.")
  with st.form("data_form", clear_on_submit=True):
    _bk_pick = None
    if _da == "restore":
      _blist = list_backups()
      if _blist: _bk_pick = st.selectbox("Backup to restore (newest first)", _blist)
      else: st.info("There are no backups yet.")
    _word = "RESTORE" if _da == "restore" else "RESET"
    _typed = st.text_input(f"Type {_word} to confirm")
    _go = st.form_submit_button("Go")
  if _go:
    if _typed.strip().upper() != _word:
      st.error(f"Nothing was changed. Type {_word} in the box to confirm.")
    elif _da == "restore" and not _bk_pick:
      st.error("Choose a backup to restore.")
    else:
      _ok, _msg = restore_backup_data(_bk_pick) if _da == "restore" else reset_data(_da)
      if _ok:
        st.session_state.unit_idx = 0; st.session_state.chk_unit_idx = 0
      st.session_state["data_flash"] = (_ok, _msg); st.rerun()

elif view_mode == "Import Data":
  title_row("📥 Import Data from CSV", "btn_sw_import")
  st.caption("Load your own equipment, daily checklists, scheduled maintenance and parts from spreadsheets saved as CSV. For equipment, do them in this order: "
             "assets, then checklist items, then scheduled tasks (parts can be loaded any time). Nothing is written until you click Import, and a file with any problem "
             "is rejected as a whole, so you never end up with half a list.")
  _kinds = {"Assets (equipment)": "assets", "Daily checklist items": "checklist", "Scheduled maintenance tasks": "tasks", "Parts (inventory)": "parts"}
  _kind = _kinds[st.radio("What are you importing?", list(_kinds), horizontal=True, key="import_kind")]
  st.download_button("Download Template", data=import_template_csv(_kind),
                     file_name=f"{_kind}_template.csv", mime="text/csv", key=f"imp_tpl_{_kind}")
  with st.expander("Column guide"):
    if _kind == "assets":
      st.markdown("**Required:** AssetID (your unique code), Description, Category.  \n"
                  "**Asset groups:** the Category column is the asset group. A new name creates a new group, so there is no separate file for groups.  \n"
                  "**Optional:** SerialNumber, Color, Motor, Transmission, Fuel, Maintenance_Protocol "
                  f"(one of: {', '.join(MAINTENANCE_PROTOCOLS)}), Current_Meter (hours or distance).  \n"
                  "Assets whose AssetID already exists are skipped, never overwritten.")
    elif _kind == "parts":
      st.markdown("**Parts inventory.** **Required:** PartNumber, Description.  \n"
                  "**Optional:** Location, Supplier, QtyOnHand, ReorderPoint (alert at or below this), ReorderQty, UnitCost, AssetGroup "
                  "(the group the part belongs to, such as Pumps/Compressors; leave blank for General).  \n"
                  "Quantities on hand are recorded as an opening balance. A part number that already exists is skipped, never overwritten.")
    elif _kind == "checklist":
      st.markdown("**Daily inspection checklist.** One item per line.  \n"
                  "**Required:** Item, plus either AssetID (that one asset) or Category (every asset in that group, handy for a group-wide checklist).  \n"
                  "**Optional:** Day. Leave it blank (or Daily) for an every-day item, or put a day of the week (Friday, or Fri) for a weekly item. "
                  "Weekly items appear on every printout, but on their day they print in bold and underlined so nobody skips them.  \n"
                  "Items are added to what each asset already has, filling empty [ N/A ] slots first. An item the asset already has is skipped.")
    else:
      st.markdown("**Scheduled maintenance.** **Required:** AssetID (must already exist), TaskName, and at least one of Days_Between or Meter_Between.  \n"
                  f"**Optional:** TabGroup (one of: {', '.join(TASK_TAB_GROUPS)}; default Prevention A), ManHours, EstimatedPartsCost, ToolsNeeded, "
                  "TaskDescription, PersonnelQualifications, SafetyPrecautions, RequiredConsumables, "
                  "Date_Last_Done (like 2026-10-08; blank starts the clock today), Meter_At_Last (blank uses the asset's current meter).  \n"
                  "A task that already exists for that asset and tab is skipped, never overwritten.")
  _flash = st.session_state.pop("import_flash", None)
  if _flash: st.success(_flash)
  st.caption("Caution: make sure the choice above (what you are importing) matches the kind of CSV file you upload.")
  _up = st.file_uploader("Choose a CSV file", type=["csv"], key=f"import_file_{_kind}")
  if _up is not None:
    _df, _err = read_import_csv(_up.getvalue())
    if _err:
      st.error(_err)
    else:
      if _kind == "assets":
        _rows, _errors, _skipped = validate_asset_rows(_df, set(get_existing_asset_meters().keys())); _what = "assets"
      elif _kind == "parts":
        _rows, _errors, _skipped = validate_part_rows(_df, get_existing_part_numbers()); _what = "parts"
      elif _kind == "checklist":
        _rows, _errors, _skipped = validate_checklist_rows(_df, get_existing_checklists()); _what = "checklist(s)"
      else:
        _rows, _errors, _skipped = validate_task_rows(_df, get_existing_asset_meters(), get_existing_task_keys()); _what = "tasks"
      if _errors:
        _g = guess_import_kind(_df)
        if _g and _g != _kind:
          _names = {v: k for k, v in _kinds.items()}
          st.warning(f"This file looks like **{_names[_g]}**, but **{_names[_kind]}** is selected above. Pick the matching choice above and upload the file again.")
        st.error(f"{len(_errors)} problem(s) found. Nothing was imported. Fix the file and choose it again.")
        for _e in _errors[:30]: st.write("•", _e)
        if len(_errors) > 30: st.write(f"...and {len(_errors) - 30} more.")
      else:
        st.success(f"Ready to import {len(_rows)} {_what}." + (f" {len(_skipped)} already exist and will be skipped." if _skipped else ""))
        if _rows:
          _show = pd.DataFrame(_rows)
          if _kind == "checklist": _show = _show[["AssetID", "Added", "Preview"]]
          st.dataframe(_show.head(20), use_container_width=True, hide_index=True, row_height=30)
          if len(_rows) > 20: st.caption(f"Showing the first 20 of {len(_rows)}.")
          if st.button(f"Import {len(_rows)} {_what}", key=f"btn_do_import_{_kind}", use_container_width=True):
            _n = (import_asset_rows(_rows) if _kind == "assets" else import_checklist_rows(_rows) if _kind == "checklist"
                  else import_part_rows(_rows) if _kind == "parts" else import_task_rows(_rows))
            st.session_state["import_flash"] = f"Imported {_n} {_what}. Choose the file again if you want to confirm it is now recognised as already imported."
            st.rerun()

elif view_mode == "Overdue Dashboard":
  title_row("🚨 Overdue & Due-Soon Dashboard", "btn_sw_dash")
  st.caption("Every scheduled task that is overdue, due today, or coming due, worst first. It uses the same rule as the work-order generator, "
             "so what you see here is what Generate W/O will pick up. Daily and every-few-days items are left off (they live on the Checklists); "
             "weekly items are listed with their day of the week.")
  _d1, _d2, _d3 = st.columns([1.3, 1.6, 2.1])
  with _d1: _soon = st.number_input("Due soon = within (days)", min_value=1, max_value=365, value=7, step=1, key="dash_soon")
  with _d2: _scope = st.radio("Show", ["All asset groups", f"Only {selected_category}"], key="dash_scope")
  _all = fetch_due_tasks(None if _scope == "All asset groups" else selected_category, int(_soon))
  _n_over = int((_all["Status"] == "Overdue").sum()) if not _all.empty else 0
  _n_today = int((_all["Status"] == "Due today").sum()) if not _all.empty else 0
  _n_soon = int((_all["Status"] == "Due soon").sum()) if not _all.empty else 0
  try: _n_reorder = len(needs_reorder(fetch_parts()))
  except Exception: _n_reorder = 0
  _wdash = warranties_needing_action(fetch_warranties(None if _scope == "All asset groups" else selected_category, 60))
  _m1, _m2, _m3, _m4, _m5 = st.columns(5)
  _m1.metric("Overdue", _n_over); _m2.metric("Due today", _n_today); _m3.metric("Due soon", _n_soon); _m4.metric("Parts to reorder", _n_reorder)
  _m5.metric("Warranties expiring", len(_wdash))
  _act = _all[_all["Status"] != "OK"] if not _all.empty else _all
  if _act.empty:
    st.success("Nothing is overdue or due soon." if not _all.empty else "No scheduled tasks yet. Add them under Sched. Maint. or Import Data.")
  else:
    _view = _act.drop(columns=["Tab"]).copy()
    _tint = {"Overdue": "background-color: #f8c9c9", "Due today": "background-color: #fde0b8", "Due soon": "background-color: #fff6bf"}
    st.dataframe(_view.style.apply(lambda r: [_tint.get(r["Status"], "")] * len(r), axis=1), use_container_width=True, hide_index=True,
                 height=min(700, 33 + 30 * len(_view)), row_height=30)
    _pc1, _pc2, _pc3 = st.columns([1.4, 1.4, 2.2])
    with _pc1:
      st.download_button("🖨️ Print This List (PDF)", data=build_overdue_pdf(_act, _scope, int(_soon)),
                         file_name=f"Overdue_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", use_container_width=True)
    with _pc2:
      if st.button("Go to WorkOrders (W/O)", key="btn_dash_wo", use_container_width=True): st.session_state.view_mode_override = "WorkOrders (W/O)"; st.rerun()
    with st.expander("By asset group"):
      _g = _act.pivot_table(index="Group", columns="Status", values="Task", aggfunc="count", fill_value=0)
      st.dataframe(_g, use_container_width=True, row_height=30)
  if not _wdash.empty:
    st.markdown("#### Warranties expiring (next 60 days) or just expired")
    st.dataframe(_wdash[["Status", "Asset", "Description", "Group", "Expires", "Days Left", "Meter Left", "Provider", "Action"]], use_container_width=True, hide_index=True, row_height=30)
    if st.button("Open Warranty Tracking", key="btn_dash_warr"): st.session_state.view_mode_override = "Warranty Tracking"; st.rerun()

elif view_mode == "Warranty Tracking":
  title_row("🛡️ Warranty Tracking", "btn_sw_warr")
  st.caption("Record when each asset's warranty ends. Anything ending soon, or that ended in the last 30 days, shows up here, on the Overdue Dashboard and on the Switchboard "
             "with the action: " + WARRANTY_ACTION.lower() + ".")
  _fl = st.session_state.pop("warr_flash", None)
  if _fl: (st.success if _fl[0] else st.error)(_fl[1])
  _w1, _w2 = st.columns([1.3, 2.2])
  with _w1: _wsoon = st.number_input("Expiring soon = within (days)", min_value=1, max_value=730, value=60, step=1, key="warr_soon")
  with _w2: _wscope = st.radio("Show", ["All asset groups", f"Only {selected_category}"], horizontal=True, key="warr_scope")
  _wall = fetch_warranties(None if _wscope == "All asset groups" else selected_category, int(_wsoon))
  _wact = warranties_needing_action(_wall)
  _wm1, _wm2, _wm3 = st.columns(3)
  _wm1.metric("Under warranty", int(_wall["Status"].isin(["Active", "Expiring soon"]).sum())); _wm2.metric("Expiring soon", int((_wall["Status"] == "Expiring soon").sum()))
  _wm3.metric("Just expired", int((_wall["Status"] == "Just expired").sum()))
  if _wall.empty:
    st.info("No assets yet.")
  else:
    if not _wact.empty:
      st.markdown("**Needs attention: " + WARRANTY_ACTION + "**")
      st.dataframe(_wact[["Status", "Asset", "Description", "Group", "Expires", "Days Left", "Meter Left", "Provider"]], use_container_width=True, hide_index=True, row_height=30)
      st.download_button("🖨️ Print This List (PDF)", data=build_warranty_pdf(_wact, _wscope, int(_wsoon)),
                         file_name=f"Warranties_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else:
      st.success("No warranties are expiring soon.")
    st.markdown("#### All assets")
    st.caption("**Shortcut:** enter the purchase date (Bought) and the warranty length in Years (1.5 is fine), leave the end date blank, and click Save: the end date is worked out for you. "
               "A date you type yourself always wins. **Hours Limit** is for warranties that also end at a meter reading (like 2,000 hours): enter the meter reading where coverage ends; "
               "the warranty then ends at whichever comes first. Dates look like 2027-03-31.")
    _wed = st.data_editor(_wall, hide_index=True, use_container_width=True, key="warr_editor", num_rows="fixed",
                          disabled=["Asset", "Description", "Group", "Status", "Days Left", "Meter Left"], height=min(600, 33 + 30 * len(_wall)),
                          column_config={"Expires": st.column_config.TextColumn("Warranty ends", help="2027-03-31, or leave blank and fill in Bought + Years"),
                                         "Bought": st.column_config.TextColumn("Bought", help="Purchase date, like 2024-05-30"),
                                         "Years": st.column_config.NumberColumn("Years", min_value=0.0, max_value=100.0, step=0.5, format="%g", help="Warranty length in years"),
                                         "Hours Limit": st.column_config.NumberColumn("Ends at meter", min_value=0.0, format="%g", help="Meter reading (hours or km) where coverage ends"),
                                         "Meter Left": st.column_config.NumberColumn("Meter left", format="%g"),
                                         "Notes": st.column_config.TextColumn("Terms / notes", help="What it covers, claim number, who to call")}, row_height=30)
    if st.button("Save Warranty Details", key="btn_save_warr"):
      _ok, _msg = save_warranties(_wed)
      st.session_state["warr_flash"] = (_ok, _msg); st.rerun()

elif view_mode == "Parts Inventory":
  _ph1, _ph2, _ph3 = st.columns([3.3, 1.5, 1.5], gap="small")   # title | Save Part Details | Switchboard; the two buttons are the same size
  with _ph1: st.subheader("📦 Parts Inventory")
  _save_slot = _ph2.container()   # the Save button is drawn here once the table below has been built
  with _ph3:
    if st.button("Switchboard", key="btn_sw_parts", use_container_width=True): st.session_state.view_mode_override = "Switchboard"; st.rerun()
  _fl = st.session_state.pop("parts_flash", None)
  if _fl: (st.success if _fl[0] else st.error)(_fl[1])
  _parts = fetch_parts()
  _low = needs_reorder(_parts)
  _pm1, _pm2, _pm3, _pm4 = st.columns(4)
  _pm1.metric("Parts on file", len(_parts)); _pm2.metric("Stock value", f"${_parts['Value'].sum():,.2f}")
  _pm3.metric("Need reordering", len(_low)); _pm4.metric("Out of stock", int((_parts["Status"] == "OUT").sum()))
  _t_stock, _t_move, _t_reord, _t_hist = st.tabs(["Stock", "Receive / Use / Adjust", "Reorder List", "History"])

  with _t_stock:
    with st.expander("➕ Add a new part", expanded=_parts.empty):
      _apn = st.session_state.get("add_part_n", 0)   # bumping this gives a fresh blank form after a successful add; a failed add keeps what was typed
      with st.form(f"form_add_part_{_apn}", clear_on_submit=False):
        _a1, _a2 = st.columns(2)
        with _a1:
          _pn = st.text_input("Part number *"); _pdsc = st.text_input("Description *")
          _pgrp = st.selectbox("Asset group", part_group_choices(), help="Which asset group uses this part. Choose General for things every group uses, like oil, grease or fasteners.")
          _ploc = st.text_input("Location / bin"); _psup = st.text_input("Supplier")
        with _a2:
          _pq = st.number_input("Quantity on hand now", min_value=0.0, value=0.0, step=1.0)
          _prp = st.number_input("Reorder point (alert at or below this; 0 = no alert)", min_value=0.0, value=0.0, step=1.0)
          _prq = st.number_input("Usual reorder quantity (0 = suggest automatically)", min_value=0.0, value=0.0, step=1.0)
          _puc = st.number_input("Unit cost ($)", min_value=0.0, value=0.0, step=0.5, format="%.2f")
        if st.form_submit_button("Add Part"):
          _ok, _msg = add_part(_pn, _pdsc, _ploc, _psup, _pq, _prp, _prq, _puc, _pgrp)
          if _ok: st.session_state["add_part_n"] = _apn + 1
          st.session_state["parts_flash"] = (_ok, _msg); st.rerun()
    if _parts.empty:
      st.info("No parts yet. Add one above, or load many at once under Import Data (Parts).")
    else:
      _gopts = ["All groups"] + part_group_choices() + sorted(g for g in _parts["AssetGroup"].unique() if g not in part_group_choices())
      _gc1, _gc2 = st.columns([1, 2])
      with _gc1: _gsel = st.selectbox("Show parts for", _gopts, key="parts_group_filter", help="Pick an asset group to see only its parts. 'General' shows the parts every group shares.")
      with _gc2: _q = st.text_input("Search (part number, description, location or supplier)", key="parts_search")
      _show = _parts if _gsel == "All groups" else _parts[_parts["AssetGroup"] == _gsel]
      _grp_low = needs_reorder(_show)   # the warning below follows the group chosen above
      if _q.strip():
        _s = _q.strip().lower()
        _show = _show[_show[["PartNumber", "Description", "Location", "Supplier"]].astype(str).apply(lambda c: c.str.lower().str.contains(_s, regex=False)).any(axis=1)]
      _only_low = st.checkbox("Show only parts that are LOW or OUT", key="parts_only_low")
      if _only_low: _show = _show[_show["Status"] != "OK"]
      if len(_grp_low):
        _where = "" if _gsel == "All groups" else f" in {_gsel}"
        st.error(f"🔴 {len(_grp_low)} part(s){_where} at or below their reorder point. They are flagged in the Status column and listed on the Reorder List tab.")
      # the table editor cannot colour rows, so the warning goes in the Status text itself
      _show = _show.copy()
      _show["Status"] = _show["Status"].map({"OUT": "🔴 OUT", "LOW": "🔴 LOW"}).fillna("OK")
      _edited = st.data_editor(_show, hide_index=True, use_container_width=True, key="parts_editor", num_rows="fixed", height=560,   # about 15 rows visible; scrolls inside for the rest
                               disabled=["PartID", "PartNumber", "QtyOnHand", "Status", "Value"],
                               column_config={"PartID": None,
                                              "PartNumber": st.column_config.TextColumn("Part #", width=105),
                                              "Description": st.column_config.TextColumn("Description", width=210),
                                              "AssetGroup": st.column_config.SelectboxColumn("Group", options=_gopts[1:], required=True, width=120),
                                              "Location": st.column_config.TextColumn("Location", width=80),
                                              "Supplier": st.column_config.TextColumn("Supplier", width=140),
                                              "QtyOnHand": st.column_config.NumberColumn("On hand", format="%g", width=62),
                                              "ReorderPoint": st.column_config.NumberColumn("Trigger", min_value=0.0, format="%g", width=58, help="Reorder when stock falls to this number (0 = no alert)"),
                                              "ReorderQty": st.column_config.NumberColumn("Qty", min_value=0.0, format="%g", width=45, help="Usual quantity to order"),
                                              "UnitCost": st.column_config.NumberColumn("Unit $", min_value=0.0, format="$%.2f", width=65, help="Cost of one"),
                                              "Status": st.column_config.TextColumn("Status", width=72),
                                              "Value": st.column_config.NumberColumn("Value", format="$%.2f", width=80, help="On hand x unit cost")}, row_height=30)
      st.caption("Description, asset group, location, supplier, reorder point, order quantity and cost can be edited here. Quantities change only under Receive / Use / Adjust, so every change is logged.")
      with _save_slot:
        if st.button("Save Part Details", key="btn_save_parts", use_container_width=True):
          _ok, _msg = save_part_details(_edited)
          st.session_state["parts_flash"] = (_ok, _msg); st.rerun()

  with _t_move:
    if _parts.empty:
      st.info("Add a part first (Stock tab).")
    else:
      _labels = {int(r["PartID"]): f"{r['PartNumber']} — {r['Description']} [{r['AssetGroup']}] (on hand {r['QtyOnHand']:g})" for _, r in _parts.iterrows()}
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        _aids = [str(r[0]) for r in conn.execute('SELECT AssetID FROM "Trucks" ORDER BY AssetID')]
      with st.form("form_move", clear_on_submit=True):
        _mp = st.selectbox("Part", list(_labels), format_func=lambda k: _labels[k])
        _mk = st.radio("What happened?", ["Received", "Used", "Adjusted"], horizontal=True,
                       format_func=lambda k: {"Received": "Received (add to stock)", "Used": "Used (take from stock)", "Adjusted": "Counted (set the on-hand number)"}[k])
        _mq = st.number_input("Quantity (for 'Counted', the number actually on the shelf)", min_value=0.0, value=1.0, step=1.0)
        _ma = st.selectbox("Used on asset (optional)", ["(none)"] + _aids)
        _mn = st.text_input("Note (optional: PO number, work order, reason)")
        if st.form_submit_button("Record"):
          _ok, _msg = record_move(_mp, _mk, _mq, "" if _ma == "(none)" else _ma, _mn)
          st.session_state["parts_flash"] = (_ok, _msg); st.rerun()

  with _t_reord:
    if _low.empty:
      st.success("Nothing needs reordering right now. Parts only appear here once a reorder point is set and stock falls to it.")
    else:
      _r = _low.sort_values(["Supplier", "PartNumber"])[["PartNumber", "Description", "AssetGroup", "Supplier", "Location", "QtyOnHand", "ReorderPoint", "Suggested", "EstCost"]]
      st.dataframe(_r, use_container_width=True, hide_index=True,
                   column_config={"PartNumber": "Part #", "AssetGroup": "Group", "QtyOnHand": "On hand", "ReorderPoint": "Trigger", "Suggested": "Qty",
                                  "EstCost": st.column_config.NumberColumn("Est. cost", format="$%.2f")}, row_height=30)
      st.write(f"**Estimated total: ${_low['EstCost'].sum():,.2f}**")
      _rc1, _rc2, _ = st.columns([1.4, 1.4, 2.2])
      with _rc1: st.download_button("🖨️ Print Reorder List (PDF)", data=build_reorder_pdf(_parts), file_name=f"Reorder_List_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", use_container_width=True)
      with _rc2: st.download_button("Download as CSV", data=_r.to_csv(index=False), file_name=f"Reorder_List_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

  with _t_hist:
    _opts = {0: "All parts"}
    for _, r in _parts.iterrows(): _opts[int(r["PartID"])] = f"{r['PartNumber']} — {r['Description']}"
    _hp = st.selectbox("Show history for", list(_opts), format_func=lambda k: _opts[k], key="hist_part")
    _mv = fetch_moves(_hp or None)
    if _mv.empty: st.info("No stock movements recorded yet.")
    else:
      st.dataframe(_mv, use_container_width=True, hide_index=True, height=min(650, 33 + 30 * len(_mv)), row_height=30)
      st.download_button("Download as CSV", data=_mv.to_csv(index=False), file_name=f"Parts_History_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
      st.caption("Newest first; the most recent 500 movements are shown.")

elif view_mode == "Monty Python":
  title_row("🧭 Philosophy and Laughter", "btn_sw_page7")
  def _mp_video(url, caption, start=0):
    _va, _vb, _vc = st.columns([1, 2, 1])
    with _vb:
      st.video(url, start_time=start)
      st.caption(caption)

  _MP_VIDS = [
    ("https://www.youtube.com/watch?v=cOKR2m1URe8", "The Romans", 0),
    ("https://www.youtube.com/watch?v=-8bqQ-C1PSE", "Anarcho-Syndicalist Commune", 0),
    ("https://www.youtube.com/watch?v=uyVPAlQQp5k", "Argument Clinic", 0),
    ("https://www.youtube.com/watch?v=kRwCPUEND1U", "The Black Knight", 40),
    ("https://www.youtube.com/watch?v=XgchpzSaYJA", "Life of Brian", 0),
  ]
  _SIX_DEFAULT = ("A favorite song, played loud\nA game of crib or a quick game of chess with someone\n"
                  "A call or a text to someone\nOne funny video\nA hot shower\nA short stretch, or tea on the porch")
  with st.expander("🎲 Roll the dice: pick your reward after something dull or hard", expanded=False):
    st.caption("Keep a list of six things that bring you joy, ideally ones that also make someone else happy. Edit the list any time; it is saved.")
    _six_saved = get_setting("six_joys", _SIX_DEFAULT)
    _six_txt = st.text_area("My six joys (one per line)", value=_six_saved, height=170, key="six_joys_txt")
    if _six_txt != _six_saved:
      try: set_setting("six_joys", _six_txt)
      except Exception: st.caption("Could not save the list right now.")
    _rc1, _rc2 = st.columns(2)
    with _rc1:
      if st.button("🎲 Roll the dice", key="btn_roll_dice", use_container_width=True):
        _items = [_l.strip() for _l in _six_txt.splitlines() if _l.strip()][:6]
        if _items:
          _n = random.randint(1, len(_items))
          st.session_state["dice_result"] = (_n, _items[_n - 1])
        else:
          st.session_state["dice_result"] = None
    with _rc2:
      if st.button("🎬 Pick a random video", key="btn_roll_video", use_container_width=True):
        st.session_state["dice_video"] = random.choice(_MP_VIDS)
    _dr = st.session_state.get("dice_result")
    if _dr: st.success(f"You rolled a {_dr[0]}: {_dr[1]}. Eyes open: you earned it.")
    _dv = st.session_state.get("dice_video")
    if _dv:
      st.caption(f"Today's pick: {_dv[1]}")
      st.video(_dv[0], start_time=_dv[2])

  # ---- Habit builder: pick a habit, start tiny, count the days ----
  _HABITS = [
    ("Morning pause", "One minute of quiet before the day. Three slow breaths, then name one thing you will do well today.", "Five minutes of quiet, prayer or reflection, then name your one priority for the day."),
    ("Midday pause", "Stop for one minute at midday. Put the work down and breathe.", "Three minutes away from the work: step outside, breathe, check how you are doing."),
    ("Nightly review", "Three lines before bed: one thing that went well, one thing to fix, one thing you are thankful for.", "Review the day for five minutes, keep the log short and honest, then set tomorrow's top three."),
    ("Daily walk", "Put on your shoes and step outside. That counts.", "Walk 20 to 30 minutes, outside if you can."),
    ("Water first thing", "Drink one glass of water before anything else.", "A glass of water on waking and another with each meal."),
    ("Stretch or mobility", "Two minutes of gentle stretching.", "Ten minutes of stretching or easy movement."),
    ("Moving meditation", "Three slow, deliberate movements with full attention: a stretch, a tai chi form, a slow kata.", "Ten to twenty minutes of tai chi, qigong, yoga or a martial-arts form, with full attention."),
    ("Sitting meditation", "One minute, eyes closed, counting breaths to ten.", "Ten minutes of quiet sitting. When the mind wanders, return to the breath."),
    ("Learn something", "Read or study for five minutes.", "Fifteen to thirty minutes of study, or practice of a skill you care about."),
    ("Reach out", "Send one text or make one call to someone you care about.", "A proper conversation with someone each day, in person if you can."),
    ("Three good things", "Write down one thing that went well today.", "Write three things that went well, and why."),
    ("Tidy up", "Clear one surface.", "Ten minutes to tidy your workspace or home."),
    ("Screens off, early bed", "Put the phone down ten minutes earlier than usual.", "Screens off an hour before bed, and a regular bedtime."),
    ("One more vegetable", "Add one vegetable or piece of fruit to a meal.", "Vegetables with two meals a day."),
    ("Act of kindness", "Do one small kind thing for someone, unasked.", "One real act of giving each day: time, help or a kind word."),
    ("Plan the day", "Write down the one thing that must get done.", "Write your top three at the start of the day and check them off at the end."),
    ("Craft or skill practice", "Ten minutes on a craft or skill, such as welding, music or writing.", "Fifteen to thirty minutes of focused practice, with a small goal each time."),
    ("Sentence completion", "Finish one sentence stem three ways in the Private journal.", "Five to ten minutes each morning: one stem, six or more endings, no editing. Do not reread until the weekend."),
    ("Free association", "Write for two minutes without stopping or editing.", "Five to ten minutes of free writing, then read it back and note one surprise. If it stirs up something painful, stop and talk with someone you trust."),
    ("Strengths check-in", "Tick which kinds of smarts you used today (Strengths lens, Philosophy page).", "Each evening, tick them, and once a week look at the least-used one and try something small with it."),
    ("Listen to understand", "Ask one person one real question and listen without fixing or advising.", "One conversation a day where you reflect back what you heard before you reply, and guess what the other person feels."),
    ("Compassion minute", "Three slow breaths while silently wishing someone well.", "Five to ten minutes of loving-kindness: wish well to someone you love, someone neutral, someone difficult, and yourself."),
    ("Back and neck routine", "Ten chin tucks at your desk, slowly.", "Ten to fifteen minutes: a walk, chin tucks, neck and shoulder loosening, then bird-dog, side plank and glute bridge. Stop at sharp pain, numbness or tingling."),
    ("Think sideways", "Once today, ask 'what else could this be?' about something you are working on.", "Ten minutes a week on a stuck problem: random word, provocation or the six hats (Philosophy page), then sleep on it."),
    ("Think it through with a partner", "Once a day, take one question or stuck point to a thinking partner (a friend, a mentor or an AI) and write one line on what you took from it.", "Take one real question a day to a thinking partner. Ask them to push back, not just agree. Write one line on what you will do differently, and do it. Thinking partners supplement people, they do not replace them."),
    ("Mood check-in", "Rate your mood from 1 to 10 and pick one word for it.", "Rate mood, sleep and energy from 1 to 10 each day and look for patterns each week. If you stay low for two weeks, talk to a doctor."),
    ("Urge pause", "When an urge hits (a drink, a smoke, a scroll), wait ten minutes and do something else first.", "Name the urge, wait ten minutes, move your body, then decide. This is a coping skill, not a treatment: if you are fighting an addiction, get medical help."),
  ]
  _BIG_HABITS = {"Daily walk", "Learn something", "Stretch or mobility", "Tidy up", "Reach out"}   # everything else is a tiny habit
  _BUDGET, _BIG_COST, _BIG_MAX = 7, 2, 3   # a tiny habit costs 1 point, a bigger one 2; 7 points in all, and no more than 3 bigger

  def _habit_load():
    try: _d = json.loads(get_setting("habit_tracker", "[]"))
    except Exception: _d = []
    return _d if isinstance(_d, list) else []

  def _habit_save(_d):
    try: set_setting("habit_tracker", json.dumps(_d))
    except Exception: st.caption("Could not save right now.")

  _hb_open = bool(st.session_state.get("hb_open", False))   # stays True while you are on this page, cleared when you leave
  if _hb_open and st.session_state.pop("hb_scroll", False):
    components.html("""<script>
      setTimeout(function(){ try { var d = window.parent.document; var els = d.querySelectorAll('summary');
        for (var i = 0; i < els.length; i++) { if (els[i].textContent.indexOf('Habit builder') > -1) { els[i].scrollIntoView({behavior:'smooth', block:'start'}); break; } } } catch(e) {} }, 600);
    </script>""", height=0)
  with st.expander("🌱 Habit builder: pick a habit and grow it, one small day at a time", expanded=_hb_open):
    st.markdown("<span class='hb-marker'></span>", unsafe_allow_html=True)
    st.caption("Habits take about two months to settle on average, with a wide range from person to person. "
               "So start tiny: week one is the smallest version, then the full version. Think of it as seven points: a tiny habit costs one, a bigger one costs two (so, for example, seven tiny, or three bigger plus one tiny). "
               "Miss a day? Just do the next one; one miss does not undo it.")
    from datetime import date as _hdate
    _hab = _habit_load()
    _today_hs = _hdate.today().isoformat()
    def _hgrp(_hh): return _hh.get("grp") or ("big" if _hh.get("name") in _BIG_HABITS else "tiny")
    _n_big = sum(1 for _hh in _hab if _hgrp(_hh) == "big")
    _n_tiny = len(_hab) - _n_big
    _load = _n_tiny + _BIG_COST * _n_big
    st.markdown(f"**Habit load {_load} of {_BUDGET}** · {_n_tiny} tiny (1 point each) · {_n_big} bigger (2 points each)")
    for _hi, _h in enumerate(_hab):
      try: _hday = (_hdate.today() - _hdate.fromisoformat(_h.get("start", _today_hs))).days + 1
      except Exception: _hday = 1
      _hdone = _h.get("done", [])
      _hname = _h.get("name", "Habit")
      _hc0, _hcp, _hc1, _hc2 = st.columns([4, 3, 2, 1])
      with _hc0:
        st.markdown(f"**{_hname}** · day {_hday} · done on {len(_hdone)} day{"" if len(_hdone)==1 else "s"}")
        st.caption(("Tiny version: " + _h.get("tiny", "")) if _hday <= 7 else ("Full version: " + _h.get("full", _h.get("tiny", ""))))
      with _hcp:
        _hpct = min(len(_hdone), 60) / 60 * 100
        _hfill = max(_hpct, 4) if _hdone else 0
        st.markdown(f"<div style='margin-top:6px; height:20px; background:#e9ecef; border:2px solid #1e8449; border-radius:10px; overflow:hidden;'>"
                    f"<div style='width:{_hfill:.1f}%; height:100%; background:linear-gradient(90deg,#27ae60,#1e8449);'></div></div>"
                    f"<div style='font-size:0.85rem; text-align:center; margin-top:2px;'>{len(_hdone)} of 60 days</div>", unsafe_allow_html=True)
        if _hday > 60: st.caption("Past two months. Keep it or swap it.")
      with _hc1:
        if _today_hs in _hdone:
          st.markdown("<div style='text-align:center; padding:6px; background:#d4edda; border-radius:6px; color:#155724; font-weight:600;'>Done today ✓</div>", unsafe_allow_html=True)
        elif st.button("✅ Done today", key=f"hab_done_{_hi}", use_container_width=True):
          _hdone.append(_today_hs)
          _h["done"] = _hdone
          _cnt = len(_hdone)
          _rew = _h.get("rewarded", [])
          if _cnt in (7, 21, 60) and _cnt not in _rew:
            _joys = [_l.strip() for _l in get_setting("six_joys", _SIX_DEFAULT).splitlines() if _l.strip()][:6]
            if _joys:
              _hn = random.randint(1, len(_joys))
              _h["last_reward"] = f"{_cnt} days of {_hname}! You rolled a {_hn}: {_joys[_hn - 1]}. Eyes open: you earned it."
            else:
              _h["last_reward"] = f"{_cnt} days of {_hname}! Well done."
            _rew.append(_cnt)
            _h["rewarded"] = _rew
          _hab[_hi] = _h
          _habit_save(_hab)
          st.rerun()
      with _hc2:
        if st.button("✕", key=f"hab_rm_{_hi}", help="Remove this habit", use_container_width=True):
          _hab.pop(_hi)
          _habit_save(_hab)
          st.rerun()
      if _h.get("last_reward"): st.info(_h["last_reward"])
    _tiny_ok, _big_ok = _load + 1 <= _BUDGET, (_load + _BIG_COST <= _BUDGET and _n_big < _BIG_MAX)
    if _tiny_ok or _big_ok:
      _taken = [_h.get("name") for _h in _hab]
      _gopts = (["Tiny habit (a minute or two)"] if _tiny_ok else []) + (["Bigger habit (takes real time or effort)"] if _big_ok else [])
      _gpick = st.radio("Kind of habit", _gopts, horizontal=True, key="hab_grp")
      _gkey = "big" if _gpick.startswith("Bigger") else "tiny"
      _hopts = [_x[0] for _x in _HABITS if _x[0] not in _taken and ((_x[0] in _BIG_HABITS) == (_gkey == "big"))] + ["My own habit"]
      _hpick = st.selectbox("Choose a habit", _hopts, key="hab_pick")
      _hmatch = [_x for _x in _HABITS if _x[0] == _hpick]
      if _hmatch:
        _hnm, _htiny, _hfull = _hmatch[0]
        st.caption("Tiny version: " + _htiny)
        st.caption("Full version: " + _hfull)
      else:
        _hnm = st.text_input("Name your habit", key="hab_own_name")
        _htiny = st.text_input("The tiniest version of it (so small it feels silly not to do it)", key="hab_own_tiny")
        _hfull = "Your habit, in the full version you want."
      if st.button("Start this habit", key="hab_start", use_container_width=True):
        if str(_hnm).strip():
          _hab.append({"name": str(_hnm).strip(), "tiny": str(_htiny).strip() or "Do the smallest version.", "full": _hfull, "start": _today_hs, "done": [], "rewarded": [], "grp": _gkey})
          _habit_save(_hab)
          st.rerun()
        else:
          st.warning("Give the habit a name first.")
    else:
      st.caption("You are at the limit. Remove a habit to add another.")

  # ---- Strengths lens (Gardner) and Think sideways (de Bono) ----
  _INTEL = [
    ("Linguistic (words)", "Write a page, read aloud, learn a new word, tell a story."),
    ("Logical-mathematical", "Solve a puzzle, estimate a number, plan with a spreadsheet, test an idea."),
    ("Spatial", "Sketch it, build a model, read a map, imagine it turned around."),
    ("Musical", "Listen closely, hum or play, notice rhythm in work and speech."),
    ("Bodily-kinesthetic (hands and movement)", "Build, weld, walk, dance, practise a craft or sport."),
    ("Interpersonal (people)", "Listen until someone feels understood, teach, help, work with others."),
    ("Intrapersonal (self-knowledge)", "Nightly review, journal, sit quietly, ask why you did it."),
    ("Naturalist (living things and patterns)", "Walk outside, name plants or birds, garden, notice the seasons."),
  ]
  with st.expander("🧠 Strengths lens: which kinds of smarts did I use today?", expanded=False):
    st.caption("Howard Gardner (Frames of Mind, 1983) [B4] described several kinds of intelligence. Use this as a lens for noticing your strengths and the ones you neglect, "
               "not as a test or a score: many psychologists doubt the intelligences are separate, measurable abilities, and the theory is debated. "
               "Skills grow with practice. Tick what you used today and look at the last 30 days.")
    try: _il = json.loads(get_setting("intel_log", "[]"))
    except Exception: _il = []
    if not isinstance(_il, list): _il = []
    _il_today = _date.today().isoformat()
    _il_names = [_n for _n, _h in _INTEL]
    _il_pick = st.multiselect("Used today (pick any)", _il_names, key="intel_pick")
    if st.button("Save today", key="intel_save"):
      _il = [_e for _e in _il if isinstance(_e, dict) and _e.get("d") != _il_today] + [{"d": _il_today, "u": list(_il_pick)}]
      _il = _il[-120:]
      try: set_setting("intel_log", json.dumps(_il))
      except Exception: st.caption("Could not save right now.")
      st.success("Saved.")
    _il_cut = (_date.today() - _timedelta(days=30)).isoformat()
    _il_recent = [_e for _e in _il if isinstance(_e, dict) and str(_e.get("d", "")) >= _il_cut]
    if _il_recent:
      _il_counts = {_n: sum(1 for _e in _il_recent if _n in _e.get("u", [])) for _n in _il_names}
      st.bar_chart(pd.Series(_il_counts))
      _il_least = min(_il_counts, key=lambda _k: _il_counts[_k])
      _il_hint = dict(_INTEL).get(_il_least, "")
      st.write(f"Least used in the last 30 days: **{_il_least}**. A small idea: {_il_hint}")
    else:
      st.caption("Nothing logged yet. Save a day to see your 30-day picture.")
    if st.checkbox("Show the eight, and one way to use each", key="intel_show"):
      for _n, _h in _INTEL: st.markdown(f"- **{_n}:** {_h}")
      st.caption("Gardner's first list had seven (the first seven above); he later added the naturalist and has considered an existential one. A lens, not a measurement.")

  _RANDOM_WORDS = ["anchor", "bridge", "candle", "compass", "drum", "engine", "feather", "gate", "harbour", "island", "kettle", "ladder", "magnet", "needle",
                   "orchard", "pendulum", "quilt", "river", "spring", "tide", "umbrella", "valve", "windmill", "zipper", "balloon", "bucket", "clock", "dam",
                   "elevator", "fence", "glacier", "hammer", "ice", "jar", "key", "lighthouse", "mirror", "net", "ocean", "paddle", "radio", "sieve", "teapot",
                   "ant", "bee", "cloud", "dice", "echo", "fountain", "garden", "honey", "kite", "lantern", "map", "nest", "oven", "parachute"]
  _PO = ["PO: what if the problem were the opposite of what it is?", "PO: what if the most important part were removed?",
         "PO: what if it had to work with no money?", "PO: what if a child had to solve it?",
         "PO: what if it had to be ten times bigger, or ten times smaller?", "PO: what if the person it is for did the work instead?",
         "PO: what if it had to happen in one hour?", "PO: what if we did it backwards, from the end to the start?",
         "PO: what if the rule everyone follows did not exist?", "PO: what if nature already solved this? How?"]
  _HATS = [("White hat: facts", "What do I actually know? What do I still need to find out?"),
           ("Red hat: feelings", "What does my gut say? Say it without having to justify it."),
           ("Black hat: caution", "What could go wrong? What are the risks and the weak points?"),
           ("Yellow hat: benefits", "What is good about this? Why might it work?"),
           ("Green hat: new ideas", "What else could it be? What are some different ways, however odd?"),
           ("Blue hat: the process", "What are we trying to do? What is the next step in the thinking?")]
  _TALK = {
    "Habits": ["I am trying to build this habit: [habit]. It keeps failing at [point]. What is a smaller version, and what could I attach it to?",
               "Here is my habit log for the last month: [counts]. What patterns do you see, and what would you change? Please push back if my plan is unrealistic."],
    "Goals": ["My goal is [goal]. What am I not seeing? Ask me three hard questions before giving advice.",
              "Argue the other side: why might this goal be the wrong one for me? Then help me break the right one into steps small enough to finish in a week."],
    "Relationships": ["I need to have a hard conversation with [person] about [topic]. Play that person, push back realistically, and then tell me what I could say better.",
                      "Here is a conflict from my side: [story]. Now tell me how the other person might see it, with no taking sides."],
    "Skills": ["I want to get better at [skill]. I have [time] per week. Design a practice plan aimed at my weakest spot and tell me how I will know I am improving.",
               "Which of Gardner's eight kinds of smarts do I use least ([your chart])? Suggest one small way to use it this week, and be honest that it is a lens, not a test."],
    "Monthly review": ["Here is my month: habits done [counts], strengths used most and least [chart], goals and progress [notes]. Do not just agree with me. What patterns do you see, what should I keep, shrink or drop, and what am I not seeing? End with one small action involving a real person."],
  }
  with st.expander("💬 Talk it over: questions to take to a thinking partner", expanded=False):
    ask_claude("Ask Claude to be your thinking partner", "I would like to talk something over with a thinking partner. Please ask me one question at a time, listen, and help me see my options without telling me what to do. The topic is: ")
    st.caption("A thinking partner can be a friend, a mentor, a counsellor or an AI. These are copy-and-paste starters: fill in the [brackets] and ask it to push back, not just agree. "
               "It can be wrong or flattering, so you decide what to do with its answer. It supplements real people, it does not replace them. "
               "Do not paste your Private journal into any online service, and do not paste passwords or account numbers. Not medical advice: for health or mood problems, see a doctor or counsellor first.")
    _talk_pick = st.selectbox("What do you want to talk over?", list(_TALK.keys()), index=len(_TALK) - 1, key="talk_pick")
    for _tp in _TALK[_talk_pick]: st.code(_tp, language=None)
    st.caption("Once a month is plenty for the review, and you can skip a month. Finish with a small reward from your six joys.")

  with st.expander("💡 Think sideways: spark an idea (de Bono's lateral thinking)", expanded=False):
    st.caption("Edward de Bono (Lateral Thinking, 1970; Six Thinking Hats, 1985) [B3] taught that the usual way of thinking digs deeper in the same hole, and that "
               "creativity needs deliberate sideways moves: random entry, provocation and challenging assumptions. It is widely taught and many people find it useful; "
               "controlled research on it is thin, so treat it as a toolkit, not a guarantee. Pair it with immersion in the problem and then a rest: insights often arrive after.")
    st.text_input("The problem, or the thing you are stuck on", key="lat_problem")
    _lat_c1, _lat_c2 = st.columns(2)
    with _lat_c1:
      if st.button("🎲 Random word", key="lat_rand", use_container_width=True):
        _w = random.choice(_RANDOM_WORDS)
        st.session_state["lat_out"] = f"Random word: **{_w}**. How could '{_w}' be like your problem, or help with it? List three ways, however silly. Then pick the one with a real seed in it."
    with _lat_c2:
      if st.button("🔀 Provocation (PO)", key="lat_po", use_container_width=True):
        st.session_state["lat_out"] = random.choice(_PO) + " Do not judge it. Ask: what does this lead to?"
    if st.session_state.get("lat_out"): st.info(st.session_state["lat_out"])
    _hat = st.selectbox("Or look at it through one of the six thinking hats", [_h[0] for _h in _HATS], key="lat_hat")
    for _hn, _ht in _HATS:
      if _hn == _hat: st.write(_ht)
    st.caption("Also try: challenge an assumption (why is it done this way?), list ten alternatives before choosing, and sleep on it.")
    st.markdown("**Try the opposite when you are trying too hard.** The psychiatrist Viktor Frankl [B22] noticed that fear can bring about what we fear, and that trying too hard blocks what we want. "
                "His technique, *paradoxical intention*, is to aim, for a moment and with a smile, at the very thing you dread. For nights when you lie awake worrying about not sleeping, "
                "that means giving up the effort to fall asleep and simply staying quietly awake and relaxed; the pressure often eases. "
                "A version of this is used in treatment for insomnia, with modest evidence for it. *Emerging.* It is a short-term trick, not a cure, and long-lasting sleep trouble, severe anxiety or panic deserves a doctor.")

  # ---- Private journal: locked with your passphrase, kept in its own encrypted file, never in the main database ----
  _PJ_STEMS = [
    "Living consciously to me means...",
    "If I bring 5 percent more awareness to my day...",
    "If any of what I wrote this week is true, it would be helpful if I...",
    "If I paid a little more attention to how I feel today, I would...",
    "One thing I keep avoiding looking at is...",
    "If I took a little more responsibility for my day, I would...",
    "Something I am proud of but rarely admit is...",
    "If I spoke up honestly more often, I might...",
    "What I would do if I were not afraid of looking foolish is...",
    "The kind of person I am becoming is...",
    "One small promise I could keep to myself this week is...",
    "When I get angry, underneath it I often feel...",
    "If I treated myself the way I treat a good friend, I would...",
    "What gives my work meaning is...",
  ]
  try:
    from cryptography.fernet import Fernet as _Fernet
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    _PJ_OK = True
  except Exception:
    _PJ_OK = False
  _PJ_FILE = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "private_journal.enc")

  def _pj_key(_pw, _salt):
    _raw = hashlib.scrypt(_pw.encode("utf-8"), salt=_salt, n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return base64.urlsafe_b64encode(_raw)

  _PJ_AAD = b"ounce-journal-v2"
  def _pj_enc(_k, _data, _v):
    """Version 2 = AES-256-GCM (the session key is the 32-byte scrypt output, base64 encoded). Version 1 (older test files) = Fernet (AES-128)."""
    if _v >= 2:
      _n = os.urandom(12)
      return base64.b64encode(_n + _AESGCM(base64.urlsafe_b64decode(_k)).encrypt(_n, _data, _PJ_AAD)).decode()
    return _Fernet(_k).encrypt(_data).decode()
  def _pj_dec(_k, _tok, _v):
    if _v >= 2:
      _raw = base64.b64decode(_tok)
      return _AESGCM(base64.urlsafe_b64decode(_k)).decrypt(_raw[:12], _raw[12:], _PJ_AAD)
    return _Fernet(_k).decrypt(_tok.encode())

  def _pj_read():
    try:
      with open(_PJ_FILE, "r", encoding="utf-8") as _f: return json.load(_f)
    except Exception: return None

  def _pj_write(_d):
    _tmp = _PJ_FILE + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as _f: json.dump(_d, _f)
    os.replace(_tmp, _PJ_FILE)

  def _pj_create():
    _pw = st.session_state.get("pj_new_pw", ""); _pw2 = st.session_state.get("pj_new_pw2", "")
    if len(_pw) < 8: st.session_state["pj_msg"] = "Use at least 8 characters."; return
    if _pw != _pw2: st.session_state["pj_msg"] = "The two passphrases do not match."; return
    if not st.session_state.get("pj_ack"): st.session_state["pj_msg"] = "Please tick the box to confirm you understand."; return
    try:
      _salt = os.urandom(16); _k = _pj_key(_pw, _salt)
      _pj_write({"v": 2, "salt": base64.b64encode(_salt).decode(), "check": _pj_enc(_k, b"ok", 2), "entries": []})
    except Exception as _e:
      st.session_state["pj_msg"] = f"Could not create the journal: {_e}"; return
    st.session_state["pj_key"] = _k
    st.session_state["pj_new_pw"] = ""; st.session_state["pj_new_pw2"] = ""; st.session_state["pj_msg"] = ""

  def _pj_unlock():
    _d = _pj_read(); _pw = st.session_state.get("pj_pw", "")
    try:
      _k = _pj_key(_pw, base64.b64decode(_d["salt"]))
      _v = _d.get("v", 1)
      _pj_dec(_k, _d["check"], _v)
      if _v < 2:   # upgrade an older journal (AES-128) to AES-256, checking every entry reads back before the file is replaced
        _new = {"v": 2, "salt": _d["salt"], "check": _pj_enc(_k, b"ok", 2), "entries": []}
        for _t in _d.get("entries", []):
          _plain = _pj_dec(_k, _t, 1)
          _tok2 = _pj_enc(_k, _plain, 2)
          if _pj_dec(_k, _tok2, 2) != _plain: raise ValueError("upgrade check failed")
          _new["entries"].append(_tok2)
        _pj_write(_new)
    except Exception:
      time.sleep(1)
      st.session_state["pj_msg"] = "That passphrase did not open the journal."; st.session_state["pj_pw"] = ""; return
    st.session_state["pj_key"] = _k; st.session_state["pj_pw"] = ""; st.session_state["pj_msg"] = ""

  def _pj_lock():
    st.session_state.pop("pj_key", None)
    for _k in ("pj_sc_txt", "pj_fa_txt", "pj_pw"): st.session_state[_k] = ""
    st.session_state["pj_msg"] = ""

  def _pj_save(_kind, _txt_key, _stem_key=None):
    _txt = st.session_state.get(_txt_key, "").strip(); _k = st.session_state.get("pj_key"); _d = _pj_read()
    if not _txt: st.session_state["pj_msg"] = "Nothing to save yet."; return
    if _k is None or _d is None: st.session_state["pj_msg"] = "The journal is locked."; return
    try:
      _payload = {"kind": _kind, "when": datetime.now().isoformat(timespec="minutes"),
                  "stem": st.session_state.get(_stem_key, "") if _stem_key else "", "text": _txt}
      _d["entries"].append(_pj_enc(_k, json.dumps(_payload).encode("utf-8"), _d.get("v", 1)))
      _pj_write(_d)
    except Exception as _e:
      st.session_state["pj_msg"] = f"Could not save: {_e}"; return
    st.session_state[_txt_key] = ""; st.session_state["pj_msg"] = "Saved and locked away."

  def _pj_delete(_i):
    _d = _pj_read()
    try:
      if _d is not None and 0 <= _i < len(_d["entries"]):
        _d["entries"].pop(_i); _pj_write(_d)
    except Exception as _e:
      st.session_state["pj_msg"] = f"Could not delete: {_e}"

  with st.expander("🔒 Private journal: sentence completion and free association (passphrase protected)", expanded=False):
    st.caption("Know thyself. Two classic self-reflection exercises, kept private. Each entry is encrypted with a key made from your passphrase and saved "
               "in its own file (private_journal.enc, beside your database), never in the main database, so exports, copies and demo builds do not contain it. "
               "This is self-reflection, not therapy and not medical advice. If something painful comes up, stop and talk with a counsellor or someone you trust.")
    st.markdown("**Why this is locked, and why that matters.** Free association only works if you can write whatever comes, "
                "including the unfair, angry, silly or frightening thoughts, without editing yourself. That takes knowing nobody else can read it. "
                "So the journal stays **on your own computer**, is **never sent anywhere**, and is **encrypted** with a key made from your passphrase. "
                "Entries are encrypted with **AES-256**, the same cipher that PGP/GnuPG commonly uses for the data itself and that banks and governments rely on, with the key stretched from your passphrase by scrypt. "
                "(PGP adds public-key tools for sharing messages, which a private journal does not need.) "
                "Without the passphrase, no known method can read it: the encryption itself is not the weak point. The realistic ways in are a short or guessable passphrase "
                "(use several random words), or someone sitting at your screen while it is unlocked, so lock it when you finish. "
                "Writing a thought down and seeing it on the page is itself a kind of prevention: it is hard to act on something you have looked at honestly first. "
                "**Odd thoughts are normal.** Most people have strange, unwelcome or even alarming thoughts that come out of nowhere now and then (surveys across many countries find it is almost everyone), "
                "and having one says nothing bad about your character. Writing it down is not a confession. It often looks smaller, and a bit absurd, once it is on the page, and "
                "writing about what is on your mind has modest benefits for many people. *Emerging.* "
                "If thoughts of harming yourself or someone else keep coming back, or frighten you, talk to a doctor or counsellor; in Canada you can call or text 988 any time, and in an emergency call 911.")
    if not _PJ_OK:
      st.warning("The private journal needs one extra Python package. Close the app, open a command window and run: pip install cryptography. "
                 "Then start the app again. Until then nothing can be saved here, so nothing is ever stored unprotected.")
    else:
      _pj_exists = os.path.exists(_PJ_FILE); _pj_data = _pj_read()
      if _pj_exists and _pj_data is None:
        st.error("The journal file exists but could not be read. Do not create a new one. Copy private_journal.enc somewhere safe first, then ask for help.")
      elif _pj_data is None:
        st.markdown("**Set up your private journal.** Choose a passphrase you will remember.")
        st.warning("If you forget the passphrase, the entries cannot be recovered by anyone, including me. Do not type it into a chat. "
                   "Keep a copy somewhere safe, such as a sealed note in a safe place.")
        st.text_input("Passphrase (at least 8 characters)", type="password", key="pj_new_pw")
        st.text_input("Type it again", type="password", key="pj_new_pw2")
        st.checkbox("I understand that a lost passphrase cannot be recovered.", key="pj_ack")
        st.button("Create my private journal", key="pj_create", on_click=_pj_create)
        if st.session_state.get("pj_msg"): st.info(st.session_state["pj_msg"])
      elif st.session_state.get("pj_key") is None:
        st.text_input("Passphrase", type="password", key="pj_pw")
        st.button("🔓 Unlock", key="pj_unlock", on_click=_pj_unlock)
        if st.session_state.get("pj_msg"): st.info(st.session_state["pj_msg"])
      else:
        _pjc1, _pjc2 = st.columns([3, 1])
        with _pjc1: st.success("Unlocked. It locks again when you leave this page, refresh, or press Lock.")
        with _pjc2: st.button("🔒 Lock now", key="pj_lock", on_click=_pj_lock, use_container_width=True)
        if st.session_state.get("pj_msg"): st.info(st.session_state["pj_msg"])
        _pj_mode = st.radio("What would you like to do?", ["Sentence completion", "Free association", "Read my entries"], horizontal=True, key="pj_mode")
        if _pj_mode == "Sentence completion":
          st.selectbox("Pick a sentence stem", _PJ_STEMS, key="pj_stem")
          st.caption("Finish the sentence at least six different ways, quickly, one ending per line. Do not think and do not edit. "
                     "Odd or contradictory endings are fine. Method after Nathaniel Branden [B1], in our own stems.")
          st.text_area("Your endings (one per line)", height=200, key="pj_sc_txt")
          st.button("Save to my private journal", key="pj_sc_save", on_click=_pj_save, args=("Sentence completion", "pj_sc_txt", "pj_stem"))
          st.caption("Then read them back. Which ending surprised you? Pick one small action.")
        elif _pj_mode == "Free association":
          st.caption("Write whatever comes to mind for five to ten minutes. Do not stop, correct or judge it. Nobody reads this. "
                     "Afterwards, read it back and note one thing that surprised you.")
          st.text_area("Write freely", height=260, key="pj_fa_txt")
          st.button("Save to my private journal", key="pj_fa_save", on_click=_pj_save, args=("Free association", "pj_fa_txt"))
        else:
          _ents = []
          for _ei, _tok in enumerate(_pj_data.get("entries", [])):
            try: _ents.append((_ei, json.loads(_pj_dec(st.session_state["pj_key"], _tok, _pj_data.get("v", 1)).decode("utf-8"))))
            except Exception: continue
          if not _ents: st.caption("No entries yet.")
          for _ei, _en in reversed(_ents):
            st.markdown(f"**{_en.get('when', '')} · {_en.get('kind', '')}**")
            if _en.get("stem"): st.caption(_en["stem"])
            st.text(_en.get("text", ""))
            st.button("Delete this entry", key=f"pj_del_{_ei}", on_click=_pj_delete, args=(_ei,))
            st.markdown("---")

  with st.expander("🌿 Recovery, mental health and the search for a better self: what the evidence says", expanded=False):
    st.caption("Not medical advice. This is information with honest labels, not a treatment plan. If you or someone you know is struggling with alcohol, "
               "drugs or low mood, start with a doctor or an addiction service. Withdrawal from alcohol and some drugs can be dangerous, so do not go it alone. "
               "In Saskatchewan the HealthLine is 811; in the US the SAMHSA helpline is 1-800-662-4357.")
    st.markdown("""
Addiction and despair do a great deal of damage, and people are searching hard for what works. Here is where things stand, ranked by how good the evidence is.

**1. Proven (the strongest evidence).** Medications for opioid addiction (methadone, buprenorphine, naltrexone), medications for alcohol (naltrexone, acamprosate), counselling such as cognitive behavioural therapy and motivational interviewing, peer support groups, and contingency management (small rewards for staying clean, which works especially well for stimulants and is Skinner's reinforcement idea put to good use). These are not glamorous, but they are what the best studies back. A doctor or addiction clinic can set them up.

**2. Emerging (promising, still being tested).**
- *Brain stimulation.* Deep transcranial magnetic stimulation was cleared by the US FDA in 2020 as an aid to quitting smoking, after a 262-person sham-controlled trial. The effect was modest. For opioid addiction, a 2020 review found only five small studies.
- *Psychedelics.* Psilocybin, MDMA and ibogaine are all over the media and YouTube right now, with many personal stories of better mood, insight and even recovery from depression, trauma and addiction. Early trials of some are promising, but they are small, hard to run blind (people know when they have had a psychedelic), and the field has had setbacks: the FDA declined to approve MDMA-assisted therapy in 2024. Ibogaine is the most closely watched for addiction. In April 2026 an executive order directed US agencies to speed research and review of certain psychedelic therapies, including ibogaine, with 50 million US dollars for state-run research, and the FDA has allowed an early study of noribogaine, a relative of ibogaine, for alcohol use disorder to go ahead ([Newsweek](https://www.newsweek.com/what-is-ibogaine-trump-admin-fast-tracks-psychoactive-drug-for-approval-12239530)). That is a push to *study* it faster, not an approval. The experts quoted there warn that the evidence is still limited, that ibogaine can affect heart rhythm and has been linked to deaths, that its effects last more than a day, and that it belongs in a hospital with cardiac monitoring, never a do-it-yourself setting.

**3. Unproven, not disproven.** Neuro-electric therapy (NET) is a small device with electrodes behind the ears, developed by the Scottish surgeon Dr Meg Patterson for addiction. Musicians including Pete Townshend and Eric Clapton were reported to have been helped, and those are personal accounts, not trials. Omni magazine's January 1983 article [B9] on her "black box" reported her claim that all but four of about 300 patients completed detox drug-free, which is a detox result, not a long-term one. Only half answered her follow-up survey, she herself warned the figures were probably too favourable, and a researcher asked for the missing test: electrodes fitted with the current off. When that kind of placebo-controlled trial was done (Gariti 1992, 18 patients) [B10], it found no difference. Better trials have never been run, so the honest label is *unproven, not disproven*. A consumer relaxation device descended from it, the SOTA Bio Tuner, is sold in Canada, and the maker's own guide [B15] says it is not a medical device, is not approved by any government agency, and does not claim to treat addiction.

**An old idea about why people reach for drink and drugs.** The existential psychologist Rollo May (*Freedom and Destiny*) [B5] argued that many people use alcohol and drugs to escape the anxiety that comes with freedom, with having to choose and become someone, and that used as a crutch they close off imagination and possibility. He also criticised the idea that we have a right to feel good all the time. This is a philosophical and clinical view, not a trial result, but it fits what many people in recovery say: the hard part is the emptiness or pain underneath, which is still there when the substance goes.

**Fromm's version: running from freedom into something that gives orders.** The psychoanalyst Erich Fromm [B20] argued in *Escape from Freedom* (1941) that freedom brings isolation and anxiety, and that many people cope by handing themselves over: to a strong leader or group, to conformity (becoming what everyone else is), or to anger. In *The Art of Loving* (1956) he added that people also try to ease the aloneness with drink, drugs, thrills or crowd excitement, which work for a while and leave the separateness unchanged. His answer was care, responsibility and real connection with other people, plus work and creating something of your own. Another theory, not a trial result, and a useful warning sign: if something promises to take your choices away, ask what it is asking you to stop feeling.

**Frankl's version: the empty Sunday.** The psychiatrist Viktor Frankl [B22] described an "existential vacuum": a feeling that life has no content, which shows up first as boredom. He saw it when the busy week stopped (the "Sunday neurosis") and in people facing retirement or old age, and he argued that restlessness, depression, aggression and addiction often sit on top of it. People then chase power, money or pleasure instead of meaning. This is clinical observation and theory, not a trial result, and not every depression is a lack of meaning. The practical point matches the rest of this page: do not wait for the feeling to pass. Give the empty hours something that needs you.

**The other half: becoming someone who can say no.** Medicine can help you stop. What makes stopping stick is a life worth staying clear for: a purpose, people who count on you, a body that feels better, something to do with your hands and mind. Saying no to a drug is easier when there is a *yes* behind it, and a sense of self is built out of small promises kept. That is what the rest of this page is for: the morning and midday pauses, the nightly review, the six joys, and the habit builder above. Start tiny and keep going.
""")
    st.caption("Sources: Newsweek, on the April 2026 executive order and ibogaine safety; Omni magazine, January 1983 (Patterson and NET); "
               "Gariti et al. 1992 (placebo-controlled NET trial); Aberdeen review of NET (Fingleton and Matheson, 2012); SOTA Instruments Wellness Program Guide (2026); Rollo May, Freedom and Destiny (1981). "
               "More detail is under Source [58] to [60] in the adult Longevity groups.")

  with st.expander("🍵 Home remedies: how much evidence is there?", expanded=False):
    st.caption("Not medical advice. Many home remedies have been used for centuries, and long use counts for something, especially for mild, short-lived problems. But long use is not the same as proof, so we label each one on the same scale as the rest of this page. "
               "The labels are our own summary of published reviews, not the claims of the booklet that listed many of them [B18]. Herbs and supplements are not tightly regulated, so strength varies, and some interact with medicines: tell your pharmacist what you take.")
    st.markdown("""
**Moderate (reasonable trials or reviews)**
- *Saline nasal rinse* for chronic congestion and sinus trouble; for colds it may ease symptoms a little. Use distilled, boiled-and-cooled or filtered water, never plain tap water (rare but serious amoeba infections have been traced to it), and wash the device after each use.
- *Honey* for cough, ages 1 and up. Reviews found it better than no treatment. Never give honey to a baby under 12 months (botulism risk).
- *Ginger* for nausea.
- *Enteric-coated peppermint oil* for irritable bowel symptoms. It can worsen heartburn.
- *Melatonin* for jet lag after eastward flights, taken near bedtime at the destination. Ask your doctor first, and know that products vary.
- *Fibre, fluids and walking* for constipation; *probiotics* to cut diarrhea after antibiotics.
- *A short nap* (about 20 minutes) for afternoon sleepiness, and a brisk walk for fatigue.

**Emerging or mixed (some trials, results uneven)**
- *Zinc lozenges* may shorten a cold if started early. Expect a bad taste or nausea in some people. Skip nasal zinc sprays, which have been linked to loss of smell.
- *Echinacea and andrographis* for colds: mixed results and variable products. Echinacea can cause allergic reactions.
- *Salt-water gargle* for a sore throat (and perhaps fewer colds). Low risk.
- *Valerian and chamomile* for sleep: small, mixed studies. Valerian has rare liver reports. Skip chamomile if you are allergic to ragweed.
- *Lavender aroma* for relaxation: a small effect at most.
- *Cold packs, warm compresses and peppermint oil on the temples* for tension headaches: small studies, low risk. Keep oil out of your eyes.
- *Sleeping on your side* for snoring that is worse on your back.

**Traditional (long use, little formal testing)**
- *Chicken soup and warm fluids* for colds: comfort and hydration, with some hints from lab studies.
- *Lemon and honey drinks, thyme or ginger tea, fennel seed, hot milk*: soothing and low risk.
- *Hiccup tricks* (holding your breath, a spoonful of sugar, a fright): no proof, and harmless.
- *Clove oil or a spice paste for toothache*: may numb for a while. Clove oil can irritate and is poisonous to children if swallowed. See a dentist.

**Dropped (the evidence says not worth it, or unsafe)**
- *Bowl-of-boiling-water steam for colds.* Trials show no clear benefit, and scalds happen, especially to children.
- *Oils or drops in the ear without a doctor's okay.* Not if the eardrum might be damaged; earache with fever or discharge needs a doctor.
- *Fasting for a day or a strict bananas-rice-applesauce-toast diet for diarrhea.* That is old advice. Current advice is fluids, an oral rehydration solution if there is a lot of diarrhea or vomiting, and normal food as you can manage it.

**See a doctor instead of home treatment** for trouble breathing, chest pain, a sudden severe or "worst ever" headache, headache with fever and a stiff neck, fever lasting more than three days, diarrhea lasting more than two days or with blood (or in babies and older people), blood in the stool, hoarseness for more than three weeks, earache with fever or discharge, snoring with pauses in breathing (possible sleep apnea), or tiredness that will not lift. In Saskatchewan, HealthLine is 811.
""")

  st.markdown("#### Our philosophy: small daily habits, kept for a lifetime")
  st.markdown("""
**The idea in one line.** Good daily habits are preventive maintenance for a person. You service a machine before it breaks, so you do not have to repair it after. You can do the same for your body, your attention and your relationships: a little, every day, until the habit carries itself.

**Why habits first.** Most of what goes wrong (an accident, a missed warning sign, a bad month) does not begin with a big decision. It begins with a small lapse in attention that repeats. Most of what goes right is the same: small things done regularly. A habit costs little each day. One well-known study of habit formation found it took people about two months on average for a new habit to feel automatic, with a wide range from person to person, so the early weeks are the hard part. That is when reminders and a checklist help most.

**Habits build self-awareness.** Repeating a small check teaches you to notice what you are doing while you are doing it. Gurdjieff called this self-observation, and Ouspensky described how easily we run on autopilot [44]. Erich Fromm wrote about being awake and aware, about concentrating on one thing at a time, and about listening with full attention [31][33][36]. Buddhist practice trains the same skill and calls it mindfulness. Self-awareness is the thing that lets you catch the mistake or the mood before it costs you. That is why the checklist asks you to pause, look and note, and not just to tick boxes.

**Slow sculpture.** A useful picture for all of this comes from Theodore Sturgeon's science-fiction story "Slow Sculpture" (1970) [B7]. In it, a reclusive inventor has spent half his life shaping a fifteen-foot bonsai with water, light and wire. The shaping is always a cooperation: the tree refuses what it cannot do and answers back in its own way, until it is hard to say whether the man or the tree is the one being sculpted. A frightened woman who wanders into his orchard takes the same lesson to people: how you treat someone matters as much as what you do, and the twisted, damaged ones can turn out the most beautiful. The story is built around healing and belief, and it ends with the hint that two damaged people might shape each other. That is the whole program in one image: nobody is forced into a new shape; you are nudged, a little each day, working with your own nature and not against it, and the shape arrives. Research on habits points the same way, since small repeated steps tend to stick better than big dramatic ones. It is fiction and a metaphor, not evidence, and the cure in the story is invented. The story is worth reading for itself.

Two plain rules of thumb go with it. First, measure yourself against who you were yesterday, not against someone else today: comparing upward with other people tends to sour mood, while comparing with your own past shows real progress. Second, start with your own house: put your own habits in order first, a small piece at a time, before trying to fix everyone else. You control that part, and others tend to follow what you do more than what you say.

**You are what you repeatedly do.** In his 1945 lecture "Existentialism Is a Humanism" [B16], Jean-Paul Sartre argued that a person is not handed a fixed nature to live out. You exist first and become who you are through what you choose and do. In his view, unused potential does not count the way real deeds do: there is no love apart from loving acts, and a person is the sum of their actions. He also said that someone who gives in again and again makes himself a coward by doing so, and so can stop being one, because it is the acts and not a built-in temperament that define him. Feelings, he added, are formed through the actions we take, so we cannot wait for the right feeling before we act. That is very close to how habits work: character is built from small, repeated choices, and starting before you feel ready is part of the method. Therapies for low mood such as behavioural activation use a similar idea, acting first and letting mood follow [Moderate]. Two honest cautions. This is philosophy, not science, and Sartre's view is stronger than the evidence supports: temperament, upbringing, illness and circumstances matter too, and nobody chooses all of them. So use it as a push toward the next small action, never as a way to blame yourself or someone else, and especially not for depression or addiction, where getting help is part of acting. Read it for yourself if you can: it is short.

**A purpose bigger than your complaints.** George Bernard Shaw put it this way in 1903, in the preface to *Man and Superman* [B17]: "This is the true joy in life, the being used for a purpose recognized by yourself as a mighty one; the being thoroughly worn out before you are thrown on the scrap heap; the being a force of Nature instead of a feverish selfish little clod of ailments and grievances complaining that the world will not devote itself to making you happy." Shaw's work is in the public domain, so we can quote it. It is a statement of values, not a research finding, but it fits what the studies of meaning and wellbeing keep pointing to: people do better with something worth working for.
""")
  _mp_video("https://www.youtube.com/watch?v=cOKR2m1URe8", "What have daily habits ever done for us? Apart from the health, the focus, the calm and the fewer accidents...")
  st.markdown("""
#### The same pattern in every tradition

People have worked this out many times, in cultures that never met:

- **Daily self-examination.** Confucius's student Zengzi examined himself three times a day (Analects 1.4). The Ignatian Examen is a nightly review of the day. Buddhist and Stoic practice include an evening look back [55].
- **Fixed times for pause and prayer.** Muslims pray five times a day and observant Jews three. Monasteries ran the whole day by the Hours. These are scheduled reminders, backed by a community that keeps you at it [55][56].
- **A weekly day of rest.** The Sabbath, Sunday and Friday prayers [55].
- **Washing and hygiene.** Ritual washing before meals and prayer, and the Torah's rules on quarantine and on burying waste away from the camp [56].
- **Moderation and fasting.** Ramadan, Yom Kippur, Lent, and food rules in several traditions [56].
- **Giving.** Tzedakah, zakat, tithes and alms: charity as a routine, not an impulse [56].
- **Gratitude.** Blessings, grace at meals, thanks on waking [55][56].
- **Meeting together.** Weekly gatherings, visiting the sick, caring for strangers and widows [56].
- **Movement.** Yoga, tai chi, qigong, the slow forms of the martial arts, and pilgrimage and walking in the West [54].
- **Small and consistent beats big and rare.** A well-known hadith says the most loved deeds are the consistent ones, even if small. Pirkei Avot says you are not required to finish the work, but you may not walk away from it [55].
""")
  _mp_video("https://www.youtube.com/watch?v=XgchpzSaYJA", "Life of Brian: think for yourself, and do not take every sermon on faith, this one included.")
  st.markdown("""
#### Motivation: the hard part

A reminder helps you remember. It cannot make you want to. What seems to help is the same thing the traditions use:

1. **Meaning.** Know why you are doing it: the people, the work, the years you want. Covey called it beginning with the end in mind [28].
2. **Start tiny.** Two minutes counts. Starting is the hard part and momentum does the rest.
3. **See your wins.** Tick the box and watch the streak.
4. **Other people.** A partner, a group, a teacher, a class. The traditions rarely ask you to do this alone.
5. **Identity.** Not "I should walk" but "I am someone who walks."

Awareness practice and movement practice can feed each other. A calm, attentive start makes the next session easier, and each session you finish is a small win. Research on meditation and motivation is modest and mixed, so treat this as a good bet and not a promise [54].


**Courage, and showing up.** The psychologist Rollo May, in *The Courage to Create* [B5], argues that courage is not the absence of despair but the ability to move ahead in spite of it, and that it rests on being centred in your own being: a commitment that does not come from the middle of you is not really yours. People become who they are through the many small decisions of ordinary days. He adds that commitment and honest doubt belong together: believe fully, and stay open to being wrong. He also describes creative work as *encounter*, deep absorption in the thing in front of you, and warns that enjoying the idea of being about to do something is not the same as doing it. In habit terms: show up, do the small thing, and let who you are follow from what you repeatedly do. (Philosophy and clinical observation, not trial evidence.)

**Empathy: understanding one another.** Empathy is feeling *with* someone; compassion is caring enough to help. Both grow with practice. Listen until the other person feels understood. State the best case of someone you disagree with before you answer. Spend time with people whose lives differ from yours. Take a few quiet minutes to wish people well. Your own hard times can be a bridge: remember how you wanted to be treated when you were hurting. You do not need to go looking for pain, and too much of it can numb a person instead of opening them. The studies are encouraging but modest, so call it a habit worth building, not a guarantee. It also keeps the rest honest: if we understand each other a little better, we argue a little less.

""")
  _mp_video("https://www.youtube.com/watch?v=kRwCPUEND1U", "The Black Knight: persistence, and a warning about ignoring the warning signs.", 40)
  st.markdown("""
#### Rewards, with your eyes open

Some good habits are simply not fun. For those, a reward helps. B.F. Skinner's work on reinforcement [B6] found that a reward given every time teaches fast, but one given only some of the time, on an unpredictable schedule, keeps a habit going the longest, and the habit is the hardest to drop when the rewards stop [57]. That unpredictable schedule is the strongest of the common ones.

How to use it, lightly:

- **Early on, reward every time**, so the habit gets started.
- **Make a list of six.** Write down six things you enjoy, ideally ones that also bring joy to someone else: a favorite song played loud, a game of crib or a quick game of chess (a 10-minute chess clock keeps it short), a call with a friend, a hot shower, time with someone you love, a funny video. After something dull or hard, **roll the dice** and do what comes up. Ask a friend, your partner or your AI helper to roll for you if you like. A reward that makes two people happy is the best kind.
- **Then thin it out.** Once the habit is steady, reward only some of the rolls (say a one or a two) and give a plain "well done" on the rest, so the treat stays a pleasant surprise.
- **Keep it harmless.** Not alcohol, gambling, binge food or money you cannot spare. The same trick is used by slot machines and endless feeds, which is why you do it knowingly and on your own terms.
- **Keep your eyes open.** The point of this program is awareness. You are not tricking yourself; you are using a known quirk of how people learn to help you do things that are good for you. Notice the treat, enjoy it, and notice that you earned it.

If you are in recovery from addiction or an eating disorder, skip food and risky rewards and ask your doctor or counsellor what works for you. Not medical advice.

""")
  _mp_video("https://www.youtube.com/watch?v=uyVPAlQQp5k", "Argument Clinic: your habits are not up for negotiation, but the reward is.")
  st.markdown("""
#### Attention and accidents

Ounce of Prevention began with machines, and the lesson carries over. Most disasters in the accident report had a stretch of ordinary days in which small warnings were seen, put off or not passed on. Attention, habit and a second person checking are cheap compared with the cost of an event. A checklist is a way of paying attention on purpose, even when you do not feel like it. It is also, of course, the time to gather the key data of hours/kms on the machine upon which the scheduled maintenance depends.

For factories, shops and fleets this is also what quality systems such as ISO 9001 ask to see: upkeep schedules kept, measuring tools calibrated, and problems traced to a root cause and fixed. Ounce helps you keep those records (see *Audit Readiness* on the Switchboard), and using it does not by itself make anyone certified. We make no claims about hospitals, clinics or medical-device certification.

""")
  _mp_video("https://www.youtube.com/watch?v=-8bqQ-C1PSE", "Anarcho-Syndicalist Commune: oversight, taking turns, and checking each other's work.")
  st.markdown("""
#### How we label what we tell you

Ounce of Prevention organizes knowledge. It does not sell products or promise results. Every health tip carries a label that says how well it is supported:

- **Strong:** several good randomized trials or reviews, or current guidelines agree.
- **Moderate:** some trials, or consistent large observational studies.
- **Emerging:** early or small trials, or a plausible mechanism with a few results.
- **Traditional:** long use, case reports and expert experience, but no good trials. Case reports carry some weight, because they flag rare effects and ideas worth testing, but they cannot show that something works.
- **Dropped:** contradicted by better evidence, or the risks outweigh the benefit.

The more harm a tip could do, the higher the bar. Diet and exercise cannot be double-blinded, so for those we go by the best trials, reviews and guidelines available. Evidence changes, so treat the labels as our best reading today. Not medical advice: talk to your doctor.

**What we do, and what we don't claim.** We try to base every health item on published, peer-reviewed research, preferring randomised trials, systematic reviews and national guidelines, and each item carries a label so you can see at a glance how strong the evidence is. Many items are Emerging or Traditional, meaning early, mixed or based on long use rather than proven by double-blind trials, and a lot of lifestyle questions cannot be tested that way. We check the information against the published sources ourselves; it has not been reviewed or approved by a doctor, professor or regulator, and science keeps changing. So it is our honest best reading of the evidence, not a guarantee. Not medical advice: talk to your doctor or pharmacist before changing treatment, supplements or exercise.

#### Using AI as a thinking partner

An AI helper can be a patient partner for the habits here: ask it to run your nightly review, roll the dice for your reward, challenge an assumption, draft a reminder, or help you think sideways about a stuck problem. Two cautions. AI makes mistakes and can sound sure when it is wrong, so check anything that matters, especially health claims. And keep private things private: your Private journal is encrypted on your own computer, so paste anything from it into an online AI service only if you choose to. Treat it like a good colleague: useful, not infallible, and you stay in charge. A small monthly review with a thinking partner (see Talk it over, above) is a good way to keep refining your habits, skills and goals; it is optional, and you can skip a month.

#### From one person to the whole world

The same idea works at every size. "An ounce of prevention is worth a pound of cure" comes from Benjamin Franklin, who wrote it in 1735 about preventing house fires [B8]. A person who checks small things daily stays well. A crew that inspects its machines before they fail stays safe and keeps the lights on. A town that tests its water and fixes its pipes on schedule keeps its people healthy. Some of the biggest gains in public health, such as clean water, sanitation and vaccination, came from prevention built into ordinary routines. Organizations have habits too, good and bad, and the habits are what you actually get. The cycle is the same each time: notice, check, fix it while it is small, and repeat. That is why this program covers people, machines, factories and towns with one set of tools. It starts where you have the most say: your own house, in order a bit at a time, before you try to fix the world. A healthy world is not built in one big leap. It is built from healthy routines, kept by a great many people, one small day at a time.

#### What this is not

It is not medicine, and it is not a religion. No faith is promoted or left out, and you may take what is useful from your own tradition or from none. Studies link regular practice and community with better wellbeing and longer life, but they are observational and cannot separate faith from social ties and habits. This page is a tool to keep you steady. Not medical advice. Check with your doctor. See Sources [28], [31], [33], [44], [54], [55], [56] and [57] in the Longevity plans.
""")
  st.markdown(
    "**And laughter matters too.** Laughing with other people lightens the day, loosens tension and keeps you connected, "
    "and many traditions and thinkers treated humor as part of a sane life. The research on laughter and health is modest, "
    "so call it good company and a better mood, not a cure. Rollo May (*Man's Search for Himself*) [B5] tied humor to the sense of self: to laugh is to stand back from a problem and see it with some distance, instead of being swallowed up by it, and while you can laugh, fear does not fully own you. Viktor Frankl [B22], writing about his years in the camps, made the same point: humour was a trick of the spirit for standing back from your own situation, even for a few seconds. Hence this page: take a few minutes a day, a couple of times if you can, "
    "to laugh. Preventive too."
  )
  st.caption("Further reading, paraphrased and not quoted: Rollo May, The Courage to Create (1975), Freedom and Destiny (1981) and Man's Search for Himself (1953). "
             "These are philosophy and clinical observation, not trial evidence. Also: Howard Gardner, Frames of Mind (1983); Edward de Bono, Lateral Thinking (1970) and Six Thinking Hats (1985); a lens and a toolkit, both debated.")
  with st.expander("🔎 Claims we checked: health headlines from 2025, with verdicts", expanded=False):
    st.caption("A first pass through the 2025 monthly issues and two special issues of one popular US health magazine (not named here and not affiliated with us). "
               "Claims are restated in our own words and checked against the research where we could. 'Web' means we read a source; 'General knowledge' means it matches what we know of the literature but was not re-checked; "
               "'Not checked' means exactly that. It is not every claim in the magazines, and nothing here is medical advice: re-check anything that matters.")
    _cc_df = pd.DataFrame(_CLAIMS_CHECKED, columns=["Claim", "Evidence", "Verdict", "What the research says", "Checked"])
    _cc_pick = st.selectbox("Show", ["All"] + sorted(_cc_df["Verdict"].unique()), key="cc_pick")
    if _cc_pick != "All": _cc_df = _cc_df[_cc_df["Verdict"] == _cc_pick]
    st.dataframe(_cc_df, use_container_width=True, hide_index=True)

  with st.expander("📚 Bibliography: the works behind this page", expanded=False):
    st.caption("Where we draw on a book or article, we paraphrase it in our own words and cite it. We do not reproduce passages. Being listed here is not an endorsement by any author or publisher, "
               "and these are philosophy, clinical observation and journalism as much as trial evidence, so read the evidence labels. Items marked [B1], [B2] and so on in the text refer to this list; the numbered sources like [28] for the health items are in the Sources rows of each plan.")
    st.markdown("""
**Books and stories**

[B1] Branden, Nathaniel. *The Six Pillars of Self-Esteem* (1994). Sentence completion.

[B2] Covey, Stephen R. *The 7 Habits of Highly Effective People* (1989). Also Sean Covey, *The 7 Habits of Highly Effective Teens* (1998) and *The 7 Habits of Happy Kids* (2008).

[B3] de Bono, Edward. *Lateral Thinking* (1970) and *Six Thinking Hats* (1985).

[B4] Gardner, Howard. *Frames of Mind* (1983).

[B5] May, Rollo. *Man's Search for Himself* (1953), *The Courage to Create* (1975) and *Freedom and Destiny* (1981).

[B6] Skinner, B. F. *Science and Human Behavior* (1953), on reinforcement.

[B7] Sturgeon, Theodore. "Slow Sculpture" (short story, 1970). Read in *Slow Sculpture*, Volume XII of *The Complete Stories of Theodore Sturgeon* (North Atlantic Books, 2009).

[B8] Franklin, Benjamin. The 1735 newspaper letter on preventing house fires that gave us "an ounce of prevention".

[B16] Sartre, Jean-Paul. *Existentialism Is a Humanism* (lecture given in 1945, published 1946). Read in the Yale University Press edition, translated by Carol Macomber (2007).

[B17] Shaw, George Bernard. *Man and Superman* (1903), the Epistle Dedicatory. Public domain.

[B18] National Geographic Society. *88 Natural Remedies: Ancient Healing Traditions for Modern Times* (National Geographic Shorts e-book, 2013). Read; the evidence labels in the Home remedies box are ours, not the booklet's.
[B19] McGuire W and Hull RFC (eds). *C.G. Jung Speaking: Interviews and Encounters* (Princeton University Press, 1977), pp. 450-452, the 1960 Gordon Young interview. Paraphrased from a secondary summary (Jungian Center) and a video talk; the book itself not read. Matches plan Source [73].
[B20] Fromm, Erich. *Escape from Freedom* (1941) and *The Art of Loving* (1956). Paraphrased from general knowledge and from the Fromm works read earlier (plan Sources [12], [31]-[33]); no quotation. A psychoanalytic theory, so labelled as such.
[B21] Regulator notices and statutes behind A Pound of Cure: Health Canada, marketing authorization of Casgevy for sickle cell disease and transfusion-dependent beta thalassemia (September 2024); US Food and Drug Administration, 2019 safety communication on young donor plasma infusions (no proven clinical benefit); Assisted Human Reproduction Act (Canada, S.C. 2004, c. 2), section 5 (prohibits human cloning). Checked by web search, November 2026; statements paraphrased.
[B22] Frankl, Viktor E. *Man's Search for Meaning* (Beacon Press edition with the 1984 postscript on tragic optimism; originally 1946). Read in full from the e-book and paraphrased; no quotation. Theory and personal testimony, so labelled Traditional or Emerging, not as trial evidence. Matches plan Source [10].
[B23] Published summaries of ISO 9001:2015 (clauses on infrastructure, monitoring and measuring resources, documented information, nonconformity and corrective action), ISO 55001 (asset management records) and ISO 14224 (reliability and maintenance data), read through secondary sources in November 2026; the standards themselves were not purchased or read. Used only for the Audit Readiness page and the calibration sample group.

**Articles, studies and reports**

[B9] *Omni* magazine, January 1983: article on Dr Meg Patterson and neuro-electric therapy (the "black box").

[B10] Gariti and colleagues (1992): placebo-controlled trial of neuro-electric therapy.

[B11] Fingleton and Matheson (2012): Aberdeen review of neuro-electric therapy.

[B12] *Neuromodulation* 2020; 23(3): systematic review of noninvasive brain stimulation for opioid use disorder.

[B13] Singer T et al., *Science* 2004; 303:1157-1162: watching a loved one in pain activates some of the same brain areas as feeling pain.

[B14] Newsweek: report on the April 2026 US executive order and ibogaine research.

[B15] SOTA Instruments, *Wellness Program Guide* (2026).

**Video**
- The Monty Python clips on this page belong to their owners and are linked, not copied.
""")
elif view_mode == "Audit Road":
  title_row("🛣️ Audit Readiness", "btn_sw_page_road")
  st.markdown("Customers and auditors often ask a shop, plant or fleet to show that its equipment is looked after and that problems get fixed. "
              "This page is a simple road toward that, one step at a time, with Ounce doing the record keeping. "
              "**Using Ounce does not make anyone certified or compliant with any standard; the auditor decides.**")
  st.markdown("**Which ISO number?** It depends on who is asking, so ask your customer or auditor which one they mean. In short: "
              "**ISO 9001** (quality management) is the one customers most often ask manufacturers and shops for. "
              "**ISO 55001** (asset management) is the most directly about looking after physical assets over their life, and suits plants, utilities and fleets. "
              "**ISO 45001** (occupational health and safety) is where incident reports, inspections and corrective action count. "
              "**ISO 14224** is not a certificate but a guide to collecting equipment failure data, mostly used in oil, gas and process industries.")
  st.markdown("#### The road, step by step")
  st.markdown("""
1. **Start:** enter your assets and let Ounce schedule the upkeep (*Asset Groups*, *Checklists*, *Sched. Maint.*).
2. **Keep records:** sign off the work as it is done (*Completed (W/O)*) and keep the history.
3. **Control your measuring tools:** use the *Factory Measuring & Test Equipment* group for before-use checks, verification and calibration.
4. **Handle problems properly:** log incidents with a root cause and a corrective action (*Incident Reports*), and use the *A Pound of Cure* page.
5. **Turn on the extras when you are comfortable:** failure fields and the audit trail (switch below).
6. **Review and improve:** management review, training records and document control stay in your own quality system for now (see the list at the bottom).
""")
  _aud_now = get_setting("audit_features", "0") == "1"
  st.markdown("<style>.st-key-aud_feat_box [data-baseweb='checkbox'] > span:first-child, .st-key-aud_feat_box label > span:first-child { border: 3px solid #1b5e20 !important; "
              "background-color: #ffffff; transform: scale(1.25); margin-right: 10px; } .st-key-aud_feat_box p { font-weight: 700 !important; font-size: 1.05rem !important; }</style>", unsafe_allow_html=True)
  _aud_new = st.checkbox("Turn on failure fields and the audit trail", value=_aud_now, key="aud_feat_box",
                         help="Adds a Record a Breakdown tab to Completed (W/O) and an Audit trail under Users & Security. Off by default so the program stays simple.")
  if _aud_new != _aud_now:
    set_setting("audit_features", "1" if _aud_new else "0"); st.rerun()
  if _aud_new:
    st.success("On. You will now find: **Record a Breakdown** (Switchboard > Completed (W/O) > third tab) and **Audit trail** (Switchboard > Users & Security).")
  st.caption("Off by default so the program stays simple. When on, breakdowns can be recorded with failure mode, cause, downtime and meter reading, "
             "and sign-offs, breakdown records and incident log saves are written to an audit trail (who, when, what). Turning it off hides them and stops new logging; nothing is deleted.")
  st.markdown("---")
  st.markdown("### Helping you prepare for audits")
  st.markdown(
    "An audit looks for evidence that equipment is looked after and that problems get fixed. Ounce helps you keep many of those records. "
    "**Using it does not make an organization certified or compliant with any standard; the auditor decides.** "
    "The table below is based on published summaries of ISO 9001:2015, ISO 55001 and ISO 14224 (we have not read the standards themselves), so check the wording with your own auditor.")
  st.markdown("""
| What auditors commonly ask for | Where it lives in Ounce |
|---|---|
| Upkeep schedules and inspection results (ISO 9001, infrastructure) | Sched. Maint., Checklists, Completed (W/O) |
| Calibration or verification of measuring equipment, with status (ISO 9001, monitoring and measuring resources) | The *Factory Measuring & Test Equipment* sample group: before-use checks, verification, calibration and certificate notes, out-of-tolerance review |
| Records that are kept and can be found (ISO 9001, documented information) | Completed work orders, printable reports, Back Up Database |
| Problems and corrective action with root cause (ISO 9001, nonconformity) | Incident Reports (root cause and corrective action sections), Work Orders, the *A Pound of Cure* page |
| An asset register with identity, location and importance (ISO 55001) | Asset Groups and their attributes |
| Parts used and stock held | Parts Inventory and its movement history |
| Who did the work | Technician name on completed orders; users and roles under Users & Security |
| Failure data: mode, cause, downtime, repair time (ISO 14224) | Completed (W/O), *Record a Breakdown* tab, with a summary of common causes and modes |
| Who changed what, and when | The *Audit trail* under Users & Security (sign-offs, breakdown records, incident log saves) |
""")
  st.markdown("**What Ounce does not do yet:** a record of every edit to assets, task schedules and parts (only sign-offs, breakdowns and incident saves are logged so far); "
              "training and competence records; a risk register, management-of-change forms and management review minutes; KPI trend pages such as PM compliance and MTBF; version control for procedures; and a data-retention policy template. "
              "Until those exist, keep them alongside Ounce in your own quality system.")

elif view_mode == "Pound of Cure":
  title_row("🩹 A Pound of Cure", "btn_sw_page_cure")
  st.markdown(
    "*An ounce of prevention is worth a pound of cure* [B8]. This page is the other half: what to do **after** something breaks anyway. "
    "In maintenance language that is **corrective** maintenance (fix it after it fails), next to **preventive** (on a schedule), "
    "**predictive** (when the readings say it is about to fail) and **run to failure** (on purpose, for cheap, safe parts). "
    "Nobody gets through life without a breakdown, so the aim is to be ready, spend wisely, and learn from it. "
    "**Not medical advice: talk to your doctor. In an emergency call 911; in Saskatchewan, HealthLine 811 is the nurse line.** "
    "I'm not a lawyer, accountant or doctor.")

  with st.expander("🧍 When a person breaks: be ready before the bad day", expanded=False):
    st.markdown("""
**1. Keep a one-page health sheet.** Your name and birth date, health card number, allergies, every medicine with its dose, conditions, past operations, your doctor and pharmacy, and who to call. Add who speaks for you if you cannot, and what you would want. Keep a paper copy in your wallet or on the fridge. Keep it off shared computers and out of online chats.

**2. Go to appointments with a list.** Write down your symptoms with dates, bring every medicine, and take a second person to listen and write. Good questions, in plain words:
- What is the most likely cause, and what else could it be?
- What are my options, including waiting or doing nothing?
- What are the benefits and risks of each, in real numbers ("1 in 20") and not just "small"?
- What should make me call back or go to Emergency?
- Can I have a copy of my test results?

**3. A second opinion is normal.** For a serious diagnosis, major surgery or unclear options, doctors expect it. Ask for your records and book it before deciding, unless it is an emergency. *Common sense, not a trial result.*

**4. Know who pays.** In Canada, the provincial plan generally covers medically necessary doctor and hospital care, while many other costs vary by province or plan: prescriptions outside hospital, dental, vision, physio, ambulance and equipment. Check your workplace or private plan **before** you need it. An injury at work goes to the workers' compensation board, and the sooner it is reported the better. Keep receipts: medical expenses may be claimable on a tax return, so ask the Canada Revenue Agency or an accountant. A small cash cushion for the unexpected helps more than almost any product.

**5. The after-care is half the cure.** Rehab, physio, follow-up visits and the boring exercises decide a lot of the outcome. Ask for a plan with dates, and put the tasks in the app.

**6. Then go back to prevention.** After every breakdown ask what the body was telling you, and what ounce of prevention would have caught it earlier. That is the same loop as for machines.
""")
    ask_claude("Ask Claude to help prepare for an appointment", "Help me prepare for a medical appointment. Ask me about my symptoms and questions one at a time, then give me a short list to bring. This is for preparing, not diagnosing. The reason for the visit is: ")

  with st.expander("⚙️ When a machine breaks: repair, replace or run on?", expanded=False):
    st.markdown("""
**First, safety.** Stop, lock out and tag out the energy sources before anyone reaches in (see *LOTO* in the Glossary), and make sure nobody is hurt or exposed.

**Then, record it.** Open a work order and, if anyone was hurt or it was a near miss, an incident report. A breakdown that is not written down gets repeated.

**Ask why, not just what.** Keep asking "why?" until you reach something you can fix: not "the bearing failed" but "the grease point was never on the schedule". Then do the part most people skip: **add or adjust a preventive task so it is caught next time**. That is how the pound of cure pays for the next ounce.

**Repair, replace or run on?** Rules of thumb, not laws:
- Compare the repair with the cost of replacing, **and** with the cost of downtime while you wait.
- The same part failing a third time usually means the cause is somewhere else.
- Old equipment near the end of its expected life, with parts getting scarce, leans toward replacing.
- A safety-critical failure leans toward doing it properly, not cheaply.
- Keep the critical spare parts on the shelf. The Parts Inventory shows which ones.
""")
    _pc1, _pc2, _pc3 = st.columns(3)
    with _pc1:
      if st.button("Open WorkOrders", key="pc_wo", use_container_width=True): st.session_state.view_mode_override = "WorkOrders (W/O)"; st.session_state["from_pound"] = True; st.rerun()
    with _pc2:
      if st.button("Open Incident Reports", key="pc_ir", use_container_width=True): st.session_state.view_mode_override = "Incident Reports"; st.session_state["from_pound"] = True; st.rerun()
    with _pc3:
      if st.button("Open Parts Inventory", key="pc_pi", use_container_width=True): st.session_state.view_mode_override = "Parts Inventory"; st.session_state["from_pound"] = True; st.rerun()
    ask_claude("Ask Claude: repair or replace?", "Help me decide whether to repair or replace a piece of equipment. Ask me about its age, repair history, repair quote, replacement cost, downtime cost and safety, then compare the options. The equipment is: ")

  with st.expander("🔭 Horizon watch: the edge of medicine, honestly labelled (dated November 2026)", expanded=False):
    st.markdown("""
This changes fast and it is the favourite hunting ground of people selling hope, so every line carries our usual label, and **nothing here is a recommendation or an endorsement of any clinic or product.** Check anything that matters with your doctor, and look for newer information.

- **Blood-forming stem cell (bone marrow) transplants.** Established treatment for certain blood cancers and blood disorders, and the reason "stem cell" sounds so promising. *Strong, for those specific uses.*
- **Approved gene therapies.** In 2023 and later, a CRISPR-based treatment for sickle cell disease and transfusion-dependent beta thalassemia was approved in several countries, including Canada in September 2024. Real, but for narrow groups, complex to deliver and very costly [B21]. *Moderate: proven for those diseases only.*
- **Lab-grown tissue and "reprogrammed" (iPS) cells.** Early human trials for some eye and nerve conditions. Promising but early. *Emerging.*
- **Stem-cell injections sold by clinics for joints, ageing, pain or "anti-ageing".** Regulators in several countries have warned about unapproved products and serious harms. *Not supported by good trials for most uses; treat with great caution.*
- **"Young blood" plasma infusions.** The US FDA warned in 2019 that there is no proven benefit and that it carries risks [B21]. *Dropped.*
- **Cloning.** Cloning a human is **not a medical treatment**, and it is prohibited in Canada under the Assisted Human Reproduction Act [B21]. Growing tissue matched to a patient is laboratory research, not a standard therapy. *Research only.*
- **Longevity drugs and supplements** (for example rapamycin, metformin, senolytics, NAD boosters). Interesting in animals and some early human work, but none is proven to extend healthy human life. *Emerging.*
- **"Biological age" blood and epigenetic clock tests.** Useful for research; not reliable enough to steer your own decisions. *Emerging.*

**Five red flags when someone sells a breakthrough:**
1. The proof is testimonials and before-and-after stories, not a trial.
2. There is no registered trial (look up the name at ClinicalTrials.gov) and no published results in humans.
3. The seller profits, and the price is high and paid upfront.
4. It claims to treat many unrelated conditions.
5. You are told to hurry, or to stop your other treatment.

A cheaper, safer way to reach the frontier: ask your doctor whether a registered clinical trial for your condition is open near you.
""")
  st.markdown("---")
  st.caption("Sources: [B8] Franklin; [B21] regulator notices and statutes, checked November 2026 (see the bibliography on the Philosophy page). Evidence labels as used throughout the app.")

elif view_mode == "Glossary":
  title_row("📖 Universal Maintenance Glossary & Acronyms", "btn_sw_page8")
  ask_claude("Ask Claude to explain a maintenance term", "Please explain this maintenance or reliability term in plain words, with a short example from industry: ")
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    glossary_df = pd.read_sql('SELECT TermID, Term, Acronym, Definition, AssetGroup FROM "Glossary"', conn)
  if not glossary_df.empty:
    glossary_df["TermID"] = glossary_df["TermID"].astype(str)
    edited_glossary = st.data_editor(glossary_df, key="glossary_editor", use_container_width=True, height=650, num_rows="dynamic", hide_index=True, row_height=30)
    if st.button("Save", key="btn_save_glossary", use_container_width=True):
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        for idx, row in edited_glossary.iterrows():
          tid, term = str(row["TermID"]).strip(), str(row["Term"]).strip()
          acro, defn, grp = str(row["Acronym"]).strip(), str(row["Definition"]).strip(), str(row["AssetGroup"]).strip()
          if not tid or not tid.isdigit():
            conn.execute('INSERT INTO "Glossary" ("Term", "Acronym", "Definition", "AssetGroup") VALUES (?, ?, ?, ?)', (term, acro, defn, grp))
          else:
            conn.execute('UPDATE "Glossary" SET Term = ?, Acronym = ?, Definition = ?, AssetGroup = ? WHERE TermID = ?', (term, acro, defn, grp, int(float(tid))))
        conn.commit()
      st.success("Glossary updated successfully!"); st.rerun()

elif view_mode == "Incident Reports":
  st.subheader("🚨 Incident & Compliance Reporting (NTSB / OSHA / WCB)")
  ask_claude("Ask Claude to help find the root cause", "Help me find the root cause of an equipment failure using the five whys. Ask me questions one at a time. Please do not include names or personal details. What happened: ")
  st.caption("Writing up a problem for an audit? Record the root cause and the corrective action in each incident. Optional extras (failure fields, audit trail) are on the Audit Readiness page.")
  st.markdown("<style>.st-key-btn_sw_incidents, .st-key-incident_form_type, .st-key-dl_incident_form, .st-key-reg_country, .st-key-reg_region, .st-key-btn_save_incidents"
              " { width: 250px !important; max-width: 100% !important; }"
              ".st-key-incident_form_type, .st-key-reg_region { margin-left: auto !important; margin-right: auto !important; }"
              ".st-key-dl_incident_form, .st-key-btn_save_incidents { margin-left: auto !important; }</style>", unsafe_allow_html=True)
  _ib1, _ib2, _ib3 = st.columns(3)
  _countries = regulator_countries()
  _saved_c = get_setting("country", "Canada")
  if st.session_state.get("reg_country") not in _countries:
    st.session_state["reg_country"] = _saved_c if _saved_c in _countries else _countries[0]
  def _on_country():
    set_setting("country", st.session_state["reg_country"])
    st.session_state["reg_region"] = get_setting("region_" + st.session_state["reg_country"], "All regions")
  def _on_region():
    set_setting("region_" + st.session_state["reg_country"], st.session_state["reg_region"])
  _ropts = ["All regions"] + regulator_regions(st.session_state["reg_country"])
  if st.session_state.get("reg_region") not in _ropts:
    _sr = get_setting("region_" + st.session_state["reg_country"], "All regions")
    st.session_state["reg_region"] = _sr if _sr in _ropts else "All regions"
  with _ib1:
    if st.button("Switchboard", key="btn_sw_incidents", use_container_width=True): st.session_state.view_mode_override = "Switchboard"; st.rerun()
  with _ib2:
    _ftype = st.selectbox("Incident form type", list(INCIDENT_FORM_TYPES), key="incident_form_type", label_visibility="collapsed",
                          help="Choose the kind of incident, then print the matching blank form.")
  _cc1, _cc2, _cc3 = st.columns(3)
  with _cc1:
    _country = st.selectbox("Country", _countries, key="reg_country", on_change=_on_country,
                            help="Where this incident happened. Sets which agencies the form lists. Switch it any time if you operate in more than one country.")
  with _cc2:
    if _country.startswith("Other"):
      _other_txt = st.text_input("Region (optional)", value=get_setting("other_region", ""), key="reg_other_text", max_chars=60,
                                 help="Type your country and region. It prints on the form in the Jurisdiction line.").strip()
      if _other_txt != get_setting("other_region", ""): set_setting("other_region", _other_txt)
      _region = "All regions"
    else:
      _other_txt = ""
      _region = st.selectbox("Province / State", _ropts, key="reg_region", on_change=_on_region, disabled=len(_ropts) == 1)
  with _cc3:
    st.markdown("<div style='height:36px'></div>", unsafe_allow_html=True)   # lines the button up with the drop-downs beside it
    _save_holder = st.container()
  _jur = _other_txt if _country.startswith("Other") else _country + ("" if _region == "All regions" else f" - {_region}")
  _code = INCIDENT_TYPE_CODE.get(_ftype, "GEN")
  _agency_rows = [] if _country.startswith("Other") else regulators_for(_country, _region, _code)
  _agency_names = [a for a, _r in _agency_rows]
  with _ib3:
    try:
      _fslug = re.sub(r"[^A-Za-z0-9]+", "_", _ftype.split("(")[0]).strip("_")
      st.download_button("🖨️ Print Report (PDF)", data=build_incident_form_pdf(_ftype, _agency_names, _jur), file_name=f"Incident_Report_{_fslug}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                         mime="application/pdf", key="dl_incident_form", use_container_width=True,
                         help="A blank two-page form for the incident type chosen at the left, to fill in by hand or by typing. Lists the agencies for the country chosen below. Stamped with today's date and time.")
    except ImportError:
      st.error("ReportLab not installed. Run: python -m pip install reportlab")
  _tab_form, _tab_who, _tab_log, _tab_files = st.tabs(["📄 Form preview", "🌍 Who to report to", "📋 Incident log", "📎 Photos & files"])
  with _tab_form:
    st.caption("This is the printable form. Use the Print Report (PDF) button for the fillable, printable version. Then take a photo of the printed and signed copy and upload it in the Photos & files tab, along with any other visual evidence.")
    st.markdown(incident_form_preview_html(_ftype, _agency_names, _jur), unsafe_allow_html=True)
  with _tab_who:
    st.markdown(f"**{_ftype}**  ·  **{_jur or 'Other country'}**")
    if _agency_rows:
      _sites = regulator_sites(_country)
      _who_df = pd.DataFrame(_agency_rows, columns=["Agency", "Why / when"])
      def _acronym(name):
          _m = re.findall(r"\(([A-Za-z0-9\-]{2,12})\)", name)
          if _m: return _m[-1]
          _w = [x for x in re.split(r"[\s/,]+", name) if x]
          if len(_w) == 1: return _w[0]
          _ini = "".join(x[0].upper() for x in _w if x[0].isupper())
          return _ini if 2 <= len(_ini) <= 6 else "Link"
      _who_df["Website"] = [((_sites.get(a, "") + "#" + _acronym(a)) if _sites.get(a, "") else None) for a in _who_df["Agency"]]
      st.dataframe(_who_df, hide_index=True, use_container_width=True,
                   column_config={"Agency": st.column_config.TextColumn("Agency", width=300), "Why / when": st.column_config.TextColumn("Why / when", width=380),
                                  "Website": st.column_config.LinkColumn("Link", width=120, display_text=r"#(.*)$", help="Opens the agency's home page. From general knowledge, so check it.")}, row_height=30)
      st.caption("These same agencies are ticked-box options on the Reported To section of the form.")
    elif _country.startswith("Other"):
      st.info("This country is not in the starter list. Add your regulators below under any country name you like, and they will appear on the forms.")
    else:
      st.info("No outside agency is normally listed for this kind of incident here. Record it internally (the form's own sign-off is the record), and add an agency below if one applies to you.")
    if _region == "All regions" and len(_ropts) > 1:
      st.warning(f"Choose a province / state / region above to add its agencies (workers' compensation, safety and environment). Showing only the {_country}-wide agencies.")
    st.caption(REG_DISCLAIMER)
    with st.expander("Add or correct agencies for this country"):
      if _country.startswith("Other"):
        _country_edit = st.text_input("Country name", key="reg_other_country", placeholder="Type a country name")
      else:
        _country_edit = _country
      if _country_edit:
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
          reg_df = pd.read_sql('SELECT RegID, Region, Agency, Role, AppliesTo, Website FROM "Regulators" WHERE Country = ? ORDER BY RegID', conn, params=(_country_edit,))
        reg_df["RegID"] = reg_df["RegID"].astype(str)
        _sel_region = "All" if (_country.startswith("Other") or _region == "All regions") else _region
        def _row_applies(v):
            _rs = [x.strip() for x in str(v or "All").split(";") if x.strip()] or ["All"]
            return "All" in _rs or _sel_region in _rs
        reg_df = reg_df[reg_df["Region"].apply(_row_applies)].reset_index(drop=True)
        _where = _country_edit + ("" if (_country.startswith("Other") or _region == "All regions") else f" - {_region}")
        st.markdown(f"**Agencies for {_where}**")
        st.caption("This list shows the agencies for the country and the province / state chosen above. An agency you add here is added to that province / state "
                   "(or to the whole country if no province / state is chosen). Applies to: any of INJ, NEAR, ENV, FIRE, COLL, PROP, HARASS, GEN, separated by commas (ALL = every type).")
        edited_reg = st.data_editor(reg_df, key=f"regulators_editor_{_country_edit}_{_sel_region}", use_container_width=True, height=360, num_rows="dynamic", hide_index=True,
                                    column_config={"RegID": None, "Region": None,
                                                   "Agency": st.column_config.TextColumn("Agency", width=300), "Role": st.column_config.TextColumn("Why / when", width=330),
                                                   "AppliesTo": st.column_config.TextColumn("Applies to", width=150), "Website": st.column_config.TextColumn("Link", width=220)}, row_height=30)
        if st.button("Save agencies", key="btn_save_regs", use_container_width=True):
          _blank = ("", "nan", "None")
          _t = lambda v: "" if v is None or str(v).strip() in _blank else str(v).strip()
          with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            keep = set()
            for _i, row in edited_reg.iterrows():
              rid = _t(row["RegID"]); vals = (_t(row["Region"]) or _sel_region, _t(row["Agency"]), _t(row["Role"]), _t(row["AppliesTo"]).upper() or "ALL", _t(row["Website"]))
              if not rid.isdigit():
                if not vals[1]: continue
                conn.execute('INSERT INTO "Regulators" ("Country", "Region", "Agency", "Role", "AppliesTo", "Website") VALUES (?, ?, ?, ?, ?, ?)', (_country_edit,) + vals)
              else:
                keep.add(int(rid))
                conn.execute('UPDATE "Regulators" SET Region = ?, Agency = ?, Role = ?, AppliesTo = ?, Website = ? WHERE RegID = ?', vals + (int(rid),))
            for (old_id,) in conn.execute('SELECT RegID FROM "Regulators" WHERE Country = ?', (_country_edit,)).fetchall():
              if int(old_id) not in keep and str(old_id) in set(reg_df["RegID"]): conn.execute('DELETE FROM "Regulators" WHERE RegID = ?', (int(old_id),))
            conn.commit()
          st.success("Agencies updated."); st.rerun()
  with _tab_log:
    st.caption("A record of incidents (injuries, fatalities, near-misses, spills, fires, collisions, harassment and more), and the agency report filed for each (for example NTSB, OSHA or a provincial Workers' Compensation Board). "
               "This is your own log. Which incidents must be reported, and how soon, depends on where you operate, so check your local rules. A new incident is filed under the form type, Country and Province / State chosen at the top, unless you type something else in the row.")
    _icols = ["IncidentID", "Date", "Location", "AssetInvolved", "Fatalities", "Injuries", "LostTime", "Agency", "ReportNo", "Description", "Status"]
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      incident_df = pd.read_sql('SELECT IncidentID, Date, Location, AssetInvolved, Fatalities, Injuries, LostTime, Agency, ReportNo, Description, Status, IncidentType, Country, Region, (SELECT COUNT(*) FROM "IncidentFiles" f WHERE f.IncidentID = r.IncidentID) AS Files FROM "IncidentReports" r ORDER BY Date DESC', conn)
    incident_df["IncidentID"] = incident_df["IncidentID"].astype(str)
    incident_df["Date"] = pd.to_datetime(incident_df["Date"], errors="coerce").dt.date
    for _c in ("Fatalities", "Injuries"): incident_df[_c] = pd.to_numeric(incident_df[_c], errors="coerce").fillna(0).astype(int)
    incident_df["LostTime"] = incident_df["LostTime"].fillna("No").replace("", "No")
    incident_df["IncidentType"] = incident_df["IncidentType"].fillna("").astype(str)
    for _c in ("Country", "Region"): incident_df[_c] = incident_df[_c].fillna("").astype(str)
    # a ready-to-fill row that follows the drop-downs at the top: change the type, country or province / state and it changes with them
    _dflt_country = (_other_txt or "Other country") if _country.startswith("Other") else _country
    _dflt_region = "" if (_country.startswith("Other") or _region == "All regions") else _region
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:      # the number the database will give the next incident
      _sq = conn.execute('SELECT seq FROM sqlite_sequence WHERE name = ?', ("IncidentReports",)).fetchone()
      _mx = conn.execute('SELECT COALESCE(MAX(IncidentID), 0) FROM "IncidentReports"').fetchone()[0]
    _next_id = max(int(_sq[0]) if _sq else 0, int(_mx or 0)) + 1
    _blank_row = {c: "" for c in incident_df.columns}
    _blank_row["IncidentID"] = f"{_next_id} (new)"
    _blank_row.update({"Date": None, "Fatalities": 0, "Injuries": 0, "LostTime": "No", "Files": 0, "IncidentType": _ftype, "Country": _dflt_country, "Region": _dflt_region})
    incident_df = pd.concat([incident_df, pd.DataFrame([_blank_row])], ignore_index=True)
    incident_df["Date"] = incident_df["Date"].astype(object)
    edited_incidents = st.data_editor(incident_df, key="incidents_editor", use_container_width=True, height=450, num_rows="dynamic", hide_index=True,
                                      column_order=["IncidentID", "Date", "IncidentType", "Country", "Region", "Location", "AssetInvolved", "Fatalities", "Injuries", "LostTime", "Agency", "ReportNo", "Description", "Status", "Files"],
                                      disabled=["IncidentID", "Files"],
                                      column_config={"IncidentID": st.column_config.TextColumn("ID", width=72), "Files": st.column_config.NumberColumn("📎", width=44, help="Photos and files attached to this incident (Photos & files tab)"),
                                                     "IncidentType": st.column_config.SelectboxColumn("Type", options=list(INCIDENT_FORM_TYPES), width=170),
                                                     "Date": st.column_config.DateColumn("Date", width=95),
                                                     "Country": st.column_config.TextColumn("Country", width=95, help="Filled in from the Country chosen at the top when you add a new incident"),
                                                     "Region": st.column_config.TextColumn("Prov / State", width=95, help="Filled in from the Province / State chosen at the top when you add a new incident"),
                                                     "Location": st.column_config.TextColumn("Location", width=110),
                                                     "AssetInvolved": st.column_config.TextColumn("Asset involved", width=160),
                                                     "Fatalities": st.column_config.NumberColumn("Deaths", min_value=0, step=1, format="%d", width=62),
                                                     "Injuries": st.column_config.NumberColumn("Injuries", min_value=0, step=1, format="%d", width=68),
                                                     "LostTime": st.column_config.SelectboxColumn("Lost time", options=["No", "Yes"], width=78, help="Did anyone miss work because of this?"),
                                                     "Agency": st.column_config.TextColumn("Agency", width=85, help="Who the report went to, for example NTSB, OSHA or WCB"),
                                                     "ReportNo": st.column_config.TextColumn("Report / claim #", width=115),
                                                     "Description": st.column_config.TextColumn("Description", width=320),
                                                     "Status": st.column_config.TextColumn("Status", width=130)}, row_height=30)
    with _save_holder:
      _save_clicked = st.button("Save Incident Log", key="btn_save_incidents", use_container_width=True)
    if _save_clicked:
      _blank = ("", "nan", "None", "NaT")
      _t = lambda v: "" if v is None or str(v).strip() in _blank else str(v).strip()
      def _n(v):
        try: return max(0, int(float(v)))
        except (TypeError, ValueError): return 0
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        keep_ids = set(); _gone = []
        for idx, row in edited_incidents.iterrows():
          iid = _t(row["IncidentID"])
          vals = (_t(row["Date"])[:10], _t(row["Location"]), _t(row["AssetInvolved"]), _n(row["Fatalities"]), _n(row["Injuries"]),
                  "Yes" if _t(row["LostTime"]) == "Yes" else "No", _t(row["Agency"]), _t(row["ReportNo"]), _t(row["Description"]), _t(row["Status"]), _t(row["IncidentType"]),
                  _t(row["Country"]), _t(row["Region"]))
          if not iid.isdigit():
            if not any(str(v).strip() for v in (vals[0], vals[1], vals[2], vals[6], vals[8])): continue   # an empty new row is ignored
            # a new incident is filed under the form type, country and province / state chosen at the top, unless typed in the row
            vals = (vals[0] or datetime.now().strftime("%Y-%m-%d"),) + vals[1:10] + (vals[10] or _ftype, vals[11] or (_other_txt or "Other country" if _country.startswith("Other") else _country),
                                vals[12] or ("" if (_country.startswith("Other") or _region == "All regions") else _region))
            conn.execute('INSERT INTO "IncidentReports" ("Date", "Location", "AssetInvolved", "Fatalities", "Injuries", "LostTime", "Agency", "ReportNo", "Description", "Status", "IncidentType", "Country", "Region") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', vals)
          else:
            keep_ids.add(int(iid))
            conn.execute('UPDATE "IncidentReports" SET Date = ?, Location = ?, AssetInvolved = ?, Fatalities = ?, Injuries = ?, LostTime = ?, Agency = ?, ReportNo = ?, Description = ?, Status = ?, IncidentType = ?, Country = ?, Region = ? WHERE IncidentID = ?', vals + (int(iid),))
        for (old_id,) in conn.execute('SELECT IncidentID FROM "IncidentReports"').fetchall():
          if int(old_id) not in keep_ids and str(old_id) in set(incident_df["IncidentID"]):
            conn.execute('DELETE FROM "IncidentReports" WHERE IncidentID = ?', (int(old_id),))
            _gone.append(int(old_id))
        conn.commit()
      for _g in _gone:
        for (_fid,) in sqlite3.connect(DB_PATH, timeout=20.0).execute('SELECT FileID FROM "IncidentFiles" WHERE IncidentID = ?', (_g,)).fetchall(): delete_incident_file(_fid)
      log_change("Incident log saved", "IncidentReports", "", f"{len(edited_incidents)} rows on screen; deleted incident IDs: {_gone or 'none'}")
      st.success("Incident log updated successfully!"); st.rerun()

  with _tab_files:
    st.caption("Keep everything about an incident together: a photo or screenshot of the filled-out (and signed) form, plus photos of the scene, damage or any other evidence. "
               "Files are saved in an incident_files folder next to your database, filed under the incident's ID. Photos can be locked with a supervisor passphrase.")
    _dk = enc_key_now()
    with st.container(border=True):
      if st.session_state.get("inc_recovery"):
        st.success("Photo protection is on. Write down this recovery code and keep it somewhere safe and separate (for example with the company's important papers).")
        st.code(st.session_state["inc_recovery"])
        st.warning("If the passphrase AND this code are both lost, locked photos cannot be opened by anyone, including us.")
        if st.button("I have saved the recovery code", key="btn_rec_ack"): st.session_state.pop("inc_recovery", None); st.rerun()
      elif not enc_is_set_up():
        st.markdown("🔓 **Photo protection is not set up.** Set a supervisor passphrase to lock photos so that only someone with the passphrase can open them.")
        with st.form("enc_setup_form"):
          _p1 = st.text_input("Supervisor passphrase (at least 8 characters)", type="password")
          _p2 = st.text_input("Type it again", type="password")
          if st.form_submit_button("Set up photo protection"):
            if len(_p1) < 8: st.error("Use at least 8 characters.")
            elif _p1 != _p2: st.error("The two entries do not match.")
            else:
              _rc = enc_setup(_p1)
              if enc_is_set_up(): st.session_state["inc_recovery"] = _rc; st.rerun()
              else: st.error("Could not save the setting (the database may be read-only).")
      elif _dk:
        _l1, _l2 = st.columns([3, 1])
        with _l1: st.markdown("🔓 **Photos unlocked** (locks itself after 10 minutes of no use).")
        with _l2:
          if st.button("Lock now", key="btn_enc_lock", use_container_width=True): st.session_state.pop("inc_dk", None); st.rerun()
        with st.expander("Make a new recovery code"):
          st.caption("Use this if you never saw or have lost the recovery code. The old code stops working. Your locked photos stay readable.")
          if st.button("Make a new recovery code", key="btn_new_rec"):
            st.session_state["inc_recovery"] = enc_new_recovery(_dk); st.rerun()
        with st.expander("Change the supervisor passphrase"):
          with st.form("enc_change_form"):
            _n1 = st.text_input("New passphrase (at least 8 characters)", type="password"); _n2 = st.text_input("Type it again", type="password")
            if st.form_submit_button("Change passphrase"):
              if len(_n1) < 8: st.error("Use at least 8 characters.")
              elif _n1 != _n2: st.error("The two entries do not match.")
              else: enc_change_passphrase(_dk, _n1); st.success("Passphrase changed. Locked photos stay readable with the new one.")
      else:
        with st.form("enc_unlock_form"):
          _u1, _u2 = st.columns([3, 1])
          with _u1: _pw = st.text_input("🔒 Photos are locked. Supervisor passphrase (or recovery code)", type="password")
          with _u2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            _go = st.form_submit_button("Unlock", use_container_width=True)
          if _go:
            _k = enc_unlock(_pw)
            if _k: st.session_state["inc_dk"] = _k; st.session_state["inc_dk_time"] = time.time(); st.rerun()
            else: st.error("That passphrase or code is not right.")
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      _inc = conn.execute('SELECT IncidentID, Date, IncidentType, Location FROM "IncidentReports" ORDER BY Date DESC, IncidentID DESC').fetchall()
    if not _inc:
      st.info("Add an incident on the Incident log tab and click Save first. Then attach files to it here.")
    else:
      _labels = {i: f"#{i}  ·  {str(d)[:10]}  ·  {t or 'Incident'}  ·  {loc or ''}" for i, d, t, loc in _inc}
      _sel = st.selectbox("Incident", list(_labels), format_func=lambda i: _labels[i], key="inc_file_sel")
      _fu1, _fu2 = st.columns([1, 1])
      with _fu1: _fkind = st.selectbox("What is it?", INCIDENT_FILE_KINDS, key="inc_file_kind")
      with _fu2: _fnote = st.text_input("Note (optional)", key="inc_file_note", placeholder="For example: damage to left fork, taken 10:15")
      _lock_pics = st.checkbox("🔒 Lock photos with the supervisor passphrase (recommended)", value=True, key="inc_lock_pics",
                               help="Photos (JPG, PNG and so on) are stored encrypted. PDFs are stored as they are.") if enc_is_set_up() else False
      _ups = st.file_uploader("Add photos or files (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png", "heic", "webp"], accept_multiple_files=True, key=f"inc_file_up_{st.session_state.get('inc_file_gen', 0)}")
      if _ups and st.button("Attach to this incident", key="btn_attach_inc", use_container_width=True):
        _is_pic = lambda n: n.lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".webp"))
        if _lock_pics and not _dk and any(_is_pic(_u.name) for _u in _ups):
          st.error("Unlock the photos first (box at the top), or untick the lock option.")
        else:
          _added = 0
          for _u in _ups:
            _data = _u.getvalue()
            if len(_data) > INCIDENT_FILE_MAX_MB * 1024 * 1024: st.error(f"{_u.name} is over {INCIDENT_FILE_MAX_MB} MB and was skipped."); continue
            add_incident_file(_sel, _u.name, _data, _fkind, _fnote.strip(), _dk if (_lock_pics and _is_pic(_u.name)) else None); _added += 1
          st.session_state["inc_file_gen"] = st.session_state.get("inc_file_gen", 0) + 1
          st.session_state["inc_file_msg"] = f"Attached {_added} file(s) to incident #{_sel}."
          st.rerun()
      if st.session_state.get("inc_file_msg"): st.success(st.session_state.pop("inc_file_msg"))
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        _files = conn.execute('SELECT FileID, FileName, StoredName, Kind, Note, Uploaded, COALESCE(Encrypted, 0) FROM "IncidentFiles" WHERE IncidentID = ? ORDER BY FileID', (int(_sel),)).fetchall()
      st.markdown(f"**Files for incident #{_sel}** ({len(_files)})")
      if not _files: st.caption("Nothing attached yet.")
      for fid, fname, stored, kind, note, up, encd in _files:
        _fpath = os.path.join(incident_files_dir(_sel), stored)
        _c1, _c2, _c3 = st.columns([4, 1.2, 0.8])
        with _c1: st.markdown(("🔒 " if encd else "") + f"**{fname}**  \n{kind}  ·  {up}" + (f"  ·  {note}" if note else ""))
        _bytes = None
        if os.path.exists(_fpath) and (not encd or _dk):
          try:
            with open(_fpath, "rb") as _fh: _raw = _fh.read()
            _bytes = dec_blob(_dk[:32], _dk[32:], _raw) if encd else _raw
          except ValueError: _bytes = None
        with _c2:
          if not os.path.exists(_fpath): st.caption("file missing")
          elif encd and not _dk: st.caption("🔒 locked")
          elif _bytes is None: st.caption("cannot be read")
          else: st.download_button("Download", _bytes, file_name=fname, key=f"dl_incfile_{fid}", use_container_width=True)
        with _c3:
          if st.button("Remove", key=f"rm_incfile_{fid}", use_container_width=True, disabled=bool(encd and not _dk), help="Locked photos need the passphrase to remove." if encd and not _dk else None):
            delete_incident_file(fid); st.rerun()
        if _bytes is not None and fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
          with st.expander("Preview"): st.image(_bytes, width=420)

elif view_mode == "Checklists":
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    assets_in_cat = pd.read_sql('SELECT AssetID, Year_Make_Model, Current_Meter, Checklist_Data_V2 FROM "Trucks" WHERE Category = ?', conn, params=(selected_category,))
  
  h_col, _btn_area = st.columns([2.0, 4.6])
  with h_col: st.markdown(f"### Inspection Checklist: {selected_category}")
  with _btn_area:
    # Six buttons at the top, three columns of two: Save / Copy Record / Switchboard, and the three Print buttons underneath.
    # The Print buttons are filled in further down (the PDF needs the checklist as edited), but they appear here.
    b1, b2, b3 = st.columns(3)
    with b1:
      save_chk_clicked = st.button("Save", key="btn_save_chk", use_container_width=True)
      print_slot_group = st.container()
    with b2:
      copy_chk_clicked = st.button("Copy Record", key="btn_copy_chk", use_container_width=True)
      print_slot_unit = st.container()
    with b3:
      if st.button("Switchboard", key="btn_sw_chk", use_container_width=True): st.session_state.view_mode_override = "Switchboard"; st.rerun()
      print_slot_all = st.container()

  if selected_sector == "Longevity and Awareness":      # reminder of your active habits (tick them in the Habit Builder)
    try: _ch_list = json.loads(get_setting("habit_tracker", "[]"))
    except Exception: _ch_list = []
    if isinstance(_ch_list, list) and _ch_list:
      _ch_today = _date.today().isoformat()
      _ch_lines = [("✅ " if _ch_today in _x.get("done", []) else "⬜ ") + str(_x.get("name", "Habit")) for _x in _ch_list if isinstance(_x, dict)]
      _chh0, _chh_r = st.columns([2.0, 4.6])      # same split as the button area above, so the button lines up under Switchboard
      with _chh0:
        st.markdown("**Your habits today:**")
      with _chh_r:
        _chh1, _chh2 = st.columns([2, 1])
        with _chh1:
          st.markdown(" &nbsp;·&nbsp; ".join(_ch_lines))
      with _chh2:
        if st.button("🌱 Habit Builder", key="chk_to_hab", use_container_width=True):
          st.session_state.view_mode_override = "Monty Python"; st.session_state["hb_open"] = True; st.session_state["hb_scroll"] = True; st.rerun()

  if not assets_in_cat.empty:
    asset_options = assets_in_cat.apply(lambda r: f"{r['AssetID']} — {r['Year_Make_Model']}", axis=1).tolist()
    
    if "chk_unit_idx" not in st.session_state: st.session_state.chk_unit_idx = 0
    st.session_state.chk_unit_idx = max(0, min(st.session_state.chk_unit_idx, len(asset_options)-1))
    st.session_state["chk_asset_opts"] = asset_options
    if st.session_state.get("chk_asset_selector") not in asset_options:      # e.g. after switching asset group
        st.session_state["chk_asset_selector"] = asset_options[st.session_state.chk_unit_idx]
    
    head_sel_col1, head_sel_col2, nav_col = st.columns([2.5, 1.5, 2.0])
    with head_sel_col1:
      selected_asset_str = st.selectbox("Select Unit ID:", asset_options, key="chk_asset_selector")
      selected_aid = selected_asset_str.split(" — ")[0].strip()
      if selected_asset_str in asset_options:
          st.session_state.chk_unit_idx = asset_options.index(selected_asset_str)
          
    current_asset_row = assets_in_cat[assets_in_cat["AssetID"] == selected_aid].iloc[0]
    current_meter_val = int(current_asset_row["Current_Meter"]) if pd.notnull(current_asset_row["Current_Meter"]) else 10000
    json_data_str = current_asset_row["Checklist_Data_V2"] if "Checklist_Data_V2" in current_asset_row else None

    with head_sel_col2:
      updated_daily_meter = st.number_input("Current Kms/Hrs:", value=current_meter_val, format="%d", step=1)
      
    with nav_col:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        n1, n2, n3, n4 = st.columns(4)
        with n1: 
            st.button("⏮", key="chk_n_f", type="primary", use_container_width=True, on_click=_chk_step, args=("first",))
        with n2: 
            st.button("◀", key="n_p", type="primary", use_container_width=True, on_click=_chk_step, args=("prev",))
        with n3: 
            st.button("▶", key="n_n", type="primary", use_container_width=True, on_click=_chk_step, args=("next",))
        with n4: 
            st.button("⏭", key="n_l", type="primary", use_container_width=True, on_click=_chk_step, args=("last",))

    if copy_chk_clicked and selected_aid:
        new_id = duplicate_asset(selected_aid)
        if new_id: st.success(f"Asset successfully cloned! New ID: {new_id}"); time.sleep(1.5); st.rerun()

    chk_is_default = False
    try: checklist_df = pd.DataFrame(json.loads(json_data_str))
    except:
        checklist_df = get_default_checklist_df(selected_category)
        chk_is_default = True
    else:
        _labels = [str(v).strip() for c in ("ItemLabel1", "ItemLabel2") if c in checklist_df.columns for v in checklist_df[c]]
        if all(x in _CHK_PLACEHOLDERS for x in _labels):
            checklist_df = get_default_checklist_df(selected_category)
            chk_is_default = True
    
    checklist_df["ChK1"] = checklist_df.get("ChK1", False).astype(bool)
    checklist_df["ItemLabel1"] = checklist_df.get("ItemLabel1", "[ N/A ]").astype(str)
    checklist_df["ChK2"] = checklist_df.get("ChK2", False).astype(bool)
    checklist_df["ItemLabel2"] = checklist_df.get("ItemLabel2", "[ N/A ]").astype(str)
    for _dc in ("Day1", "Day2"):
        checklist_df[_dc] = checklist_df[_dc].map(lambda v: normalize_day(v) or "Daily") if _dc in checklist_df.columns else "Daily"
    checklist_df = checklist_df[["ChK1", "ItemLabel1", "Day1", "ChK2", "ItemLabel2", "Day2"]]
    _today = today_weekday_name()
    _due = [str(r[f"ItemLabel{n}"]).strip() for _, r in checklist_df.iterrows() for n in (1, 2)
            if r[f"Day{n}"] == _today and str(r[f"ItemLabel{n}"]).strip() not in _CHK_PLACEHOLDERS]
    if _due:
        st.markdown(f"<div style='border:2px solid #1b8a3a;padding:6px 10px;border-radius:6px;color:#1b8a3a;'>"
                    f"<b><u>Today is {_today}. Weekly items due today:</u></b> <b>" + "; ".join(x.replace("<", "&lt;") for x in _due) + "</b></div>",
                    unsafe_allow_html=True)

    if chk_is_default:
        st.info("⚠️ This unit has no saved checklist yet. The items below are the default template for this asset group. Click **Save** to store them for this unit.")
    chk_orig_df = checklist_df.copy()
    edited_checklist = st.data_editor(checklist_df, hide_index=True, use_container_width=True, height=850, num_rows="dynamic",
        column_config={"Day1": st.column_config.SelectboxColumn("Day", options=DAY_CHOICES, default="Daily", help="Daily, or the day of the week this item is due"),
                       "Day2": st.column_config.SelectboxColumn("Day", options=DAY_CHOICES, default="Daily", help="Daily, or the day of the week this item is due")}, row_height=30)

    # --- Printable PDF checklists (header + page numbers on every page) ---
    try:
        this_unit = [{"AssetID": selected_aid, "Model": current_asset_row["Year_Make_Model"], "Meter": updated_daily_meter, "df": edited_checklist}]
        all_units = []
        for _, ar in assets_in_cat.iterrows():
            if ar["AssetID"] == selected_aid:
                all_units.append(this_unit[0]); continue
            try:
                adf = pd.DataFrame(json.loads(ar["Checklist_Data_V2"]))
                _lbls = [str(v).strip() for c in ("ItemLabel1", "ItemLabel2") if c in adf.columns for v in adf[c]]
                if all(x in _CHK_PLACEHOLDERS for x in _lbls): adf = get_default_checklist_df(selected_category)   # same fallback as the screen
            except Exception: adf = get_default_checklist_df(selected_category)
            all_units.append({"AssetID": ar["AssetID"], "Model": ar["Year_Make_Model"],
                              "Meter": int(ar["Current_Meter"]) if pd.notnull(ar["Current_Meter"]) else 0, "df": adf})
        with print_slot_group:   # the main printout: one sheet for the whole asset group
            st.download_button("🖨️ Print Group Sheet", data=build_group_checklist_pdf(selected_category, all_units),
                               file_name=f"GroupChecklist_{selected_category.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                               mime="application/pdf", use_container_width=True, key="dl_group_sheet_top",
                               help="PDF of the daily checklist for the whole asset group on one sheet: items down the side, units across the top.")
        with print_slot_unit:
            st.download_button("🖨️ Print This Unit", data=build_checklist_pdf(selected_category, this_unit),
                               file_name=f"Checklist_{selected_aid}_{datetime.now().strftime('%Y%m%d')}.pdf",
                               mime="application/pdf", use_container_width=True)
        if len(all_units) > 1:
            with print_slot_all:
                st.download_button("🖨️ Print All Units", data=build_checklist_pdf(selected_category, all_units),
                                   file_name=f"Checklists_{selected_category.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", use_container_width=True,
                                   help="One page per unit.")
    except ImportError:
        st.error("ReportLab not installed. Run: python -m pip install reportlab")

    if save_chk_clicked:
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        # Tidy before saving: blank labels become the standard placeholder, and rows with no item at all are removed.
        _tidy = edited_checklist.copy()
        for _n in (1, 2):
            _tidy[f"ItemLabel{_n}"] = _tidy[f"ItemLabel{_n}"].map(lambda v: "[ N/A ]" if str(v).strip() in _CHK_PLACEHOLDERS else str(v).strip())
        _tidy = _tidy[(_tidy["ItemLabel1"] != "[ N/A ]") | (_tidy["ItemLabel2"] != "[ N/A ]")]
        if _tidy.empty:
            _tidy = pd.DataFrame([{"ChK1": False, "ItemLabel1": "[ N/A ]", "Day1": "Daily", "ChK2": False, "ItemLabel2": "[ N/A ]", "Day2": "Daily"}])
        conn.execute('UPDATE "Trucks" SET Current_Meter = ?, Checklist_Data_V2 = ? WHERE AssetID = ?', (updated_daily_meter, json.dumps(_tidy.to_dict(orient="records")), selected_aid))
        conn.commit()
      # New items go to every unit in the group; reworded items stay with this unit only.
      _added = new_checklist_items(chk_orig_df, edited_checklist)
      _n_other = add_items_to_other_units(selected_category, selected_aid, _added)
      if _added and _n_other:
          st.success(f"Checklist updated! {len(_added)} new item(s) also added to {_n_other} other unit(s) in {selected_category}. Items you reworded stay with this unit only.")
          time.sleep(2.5)
      else:
          st.success("Checklist updated!")
      st.rerun()

elif view_mode == "Sched. Maint.":
    if sector_of(selected_category) == "Longevity and Awareness":
        ask_claude("Ask Claude to help write a health routine",
                   "Help me write a clear, realistic routine health and wellness task for the group of people I am planning for: what to do, how often, what I need, any safety cautions, "
                   "and how I will know it is working. This is general information, not medical advice. The group is: " + _short_group(selected_category))
    else:
        ask_claude("Ask Claude to help write a maintenance task", "Help me write a clear preventive maintenance task for a piece of equipment: what to check, how often, what tools and safety steps, and what a good result looks like. The equipment is: ")
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        trucks_df = pd.read_sql('SELECT * FROM "Trucks" WHERE Category = ?', conn, params=(selected_category,))
        
    if not trucks_df.empty:
        if "target_sched_aid" in st.session_state and st.session_state.target_sched_aid:
            target_aid = st.session_state.target_sched_aid
            st.session_state.target_sched_aid = None
            match_idx = trucks_df.index[trucks_df["AssetID"] == target_aid].tolist()
            if match_idx: 
                st.session_state.unit_idx = match_idx[0]

        st.session_state.unit_idx = max(0, min(st.session_state.get("unit_idx", 0), len(trucks_df) - 1))
        current_unit = trucks_df.iloc[st.session_state.unit_idx]
        asset_id_clean = current_unit["AssetID"]

        if st.session_state.get("sched_from_wo"):
            # Arrived from the Work Orders screen: say why, point to the right tab, and offer a way back.
            _wo_df = st.session_state.get("wo_triggered_df")
            _due_txt = ""
            if _wo_df is not None and not _wo_df.empty and "AssetID" in _wo_df.columns:
                _mine = _wo_df[_wo_df["AssetID"] == asset_id_clean]
                import html as _html_mod
                _due_txt = "; ".join("<b>" + _html_mod.escape(str(r["TaskName"])) + "</b> (tab: " + _html_mod.escape(str(r["TabGroup"])) + ")" for _, r in _mine.iterrows())
            _bw1, _bw2 = st.columns([1, 3.15])      # first column the same width as each of the four buttons below
            with _bw1:
                if st.button("← Back to W/O's", key="btn_back_to_wo", use_container_width=True):
                    st.session_state.sched_from_wo = False
                    st.session_state.view_mode_override = "WorkOrders (W/O)"
                    st.rerun()
            with _bw2:
                st.markdown(f"<div style='padding-top:10px'>Opened from Work Orders. Due on this unit: {_due_txt or 'nothing listed in the current work order'}.</div>", unsafe_allow_html=True)

        top1, top2, top3, top4 = st.columns([1.0, 1.0, 1.0, 1.0])
        with top1: 
            if st.button("Copy Record", key="btn_copy_pm", use_container_width=True):
                new_id = duplicate_asset(asset_id_clean)
                if new_id: 
                    st.success(f"Cloned! New ID: {new_id}")
                    time.sleep(1.5)
                    st.rerun()
        with top2: 
            save_btn = st.button("Save", key="btn_save_pm", use_container_width=True)
        with top3:
            if st.button("Generate W/O", key=f"btn_gen_single_wo_{asset_id_clean}", use_container_width=True):
                with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                    query = """SELECT t.AssetID, t.Year_Make_Model, t.Category, t.Maintenance_Protocol, t.Disregard_Dates, 
                               p.TabGroup, p.TaskName, p.Date_Last_Done, p.Meter_At_Last, p.Days_Between, p.Meter_Between, 
                               p.ToolsNeeded, p.ManHours, p.TaskDescription, p.PersonnelQualifications, p.SafetyPrecautions, 
                               p.EstimatedPartsCost, p.RequiredConsumables, t.Current_Meter 
                               FROM "Preventive_Schedules" p 
                               JOIN "Trucks" t ON p.AssetID = t.AssetID 
                               WHERE p.AssetID = ?"""
                    all_tasks = pd.read_sql(query, conn, params=(asset_id_clean,))
                
                triggered_tasks = []
                for idx, row in all_tasks.iterrows():
                    try: meter_at_last = float(str(row["Meter_At_Last"]).replace(',', '').strip()) if str(row["Meter_At_Last"]).strip() else 0.0
                    except: meter_at_last = 0.0
                    
                    try: meter_between = float(str(row["Meter_Between"]).replace(',', '').strip()) if str(row["Meter_Between"]).strip() else 0.0
                    except: meter_between = 0.0
                    
                    try: days_between = int(str(row["Days_Between"]).replace(',', '').strip()) if str(row["Days_Between"]).strip() else 0
                    except: days_between = 0
                    
                    ignore_dates = bool(row["Disregard_Dates"])
                    current_m = float(current_unit['Current_Meter']) if pd.notnull(current_unit['Current_Meter']) else 0.0
                    meter_triggered = (meter_between > 0) and ((current_m - meter_at_last) >= meter_between)
                    days_triggered = False
                    
                    date_str = str(row["Date_Last_Done"]).strip()
                    if date_str and date_str.lower() != "none" and date_str != "":
                        try: days_triggered = days_between > 0 and (datetime.now() - datetime.strptime(date_str.split()[0], "%Y-%m-%d")).days >= days_between
                        except: days_triggered = False
                        
                    is_due = meter_triggered if ignore_dates else (meter_triggered or days_triggered)
                    if is_due: 
                        triggered_tasks.append(row)
                        
                triggered_df = pd.DataFrame(triggered_tasks)
                st.session_state.wo_triggered_df = triggered_df
                
                if not triggered_df.empty:
                    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                        for aid_uniq in triggered_df["AssetID"].unique():
                            uinfo = triggered_df[triggered_df["AssetID"] == aid_uniq]
                            total_cost = uinfo["EstimatedPartsCost"].astype(float).sum() + (uinfo["ManHours"].astype(float).sum() * get_labor_rate())
                            conn.execute("""INSERT INTO "WorkOrders" ("AssetID", "ServiceDate", "MyCompany", "Description", "TotalCost") 
                                            VALUES (?, ?, ?, ?, ?)""", 
                                         (aid_uniq, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), get_company_name(), 
                                          f"Generated Work Order: {', '.join(uinfo['TaskName'].tolist())}", total_cost))
                        conn.commit()
                    st.session_state.view_mode_override = "WorkOrders (W/O)"
                    st.rerun()
                else: 
                    st.info(f"Unit {asset_id_clean} is fully up to date.")
        with top4:
            if st.button("Switchboard", key="btn_sw_pm", use_container_width=True): 
                st.session_state.view_mode_override = "Switchboard"
                st.rerun()

        st.markdown(f"<div style='padding-top: 5px; margin-bottom: 10px;'><span style='font-size: 15.5pt;'><b>Asset ID:</b> {asset_id_clean} &nbsp;|&nbsp; <b>Model:</b> {current_unit['Year_Make_Model']}</span></div>", unsafe_allow_html=True)
        db_disregard = bool(current_unit["Disregard_Dates"]) if "Disregard_Dates" in current_unit and pd.notnull(current_unit["Disregard_Dates"]) else False

        nav1, nav2, nav4 = st.columns([1.7, 1.8, 2.1])      # Disregard Dates sits centred between the meter box and the arrows
        st.markdown("<style>[class*='st-key-chk_disregard_'] {display:flex; justify-content:center;} [class*='st-key-chk_disregard_'] [data-baseweb='checkbox'] > span:first-of-type {transform: translateY(4px);}</style>", unsafe_allow_html=True)
        with nav1: 
            updated_meter = st.number_input("Current Kms/Hrs:", value=int(current_unit['Current_Meter']) if pd.notnull(current_unit['Current_Meter']) else 10000, format="%d", step=1, key=f"sm_meter_{asset_id_clean}")
        with nav2: 
            st.markdown("<div style='height: 41px;'></div>", unsafe_allow_html=True)   # lines the checkbox up with the middle of the arrow buttons
            disregard_dates = st.checkbox("Disregard Dates?", value=db_disregard, key=f"chk_disregard_{asset_id_clean}")
        with nav4:
            st.markdown("<div style='height: 32px;'></div>", unsafe_allow_html=True)   # arrows level with the Kms/Hrs box, top and bottom
            n1, n2, n3, n4 = st.columns(4)
            with n1: 
                if st.button("⏮", key="n_f", type="primary", use_container_width=True): 
                    st.session_state.unit_idx = 0
                    st.rerun()
            with n2: 
                if st.button("◀", key="n_p", type="primary", use_container_width=True) and st.session_state.unit_idx > 0: 
                    st.session_state.unit_idx -= 1
                    st.rerun()
            with n3: 
                if st.button("▶", key="n_n", type="primary", use_container_width=True) and st.session_state.unit_idx < len(trucks_df)-1: 
                    st.session_state.unit_idx += 1
                    st.rerun()
            with n4: 
                if st.button("⏭", key="n_l", type="primary", use_container_width=True): 
                    st.session_state.unit_idx = len(trucks_df)-1
                    st.rerun()

        _msg_slot = st.container()   # save messages show here, right under the buttons, not below the tall table
        tab_a, tab_b, tab_c, tab_comp, tab_bom, tab_fin = st.tabs(["Prevention A", "Prevention B", "Prevention C", "Compliance", "Subs/Parts", "ID/Finance"])
        updated_dfs = {}
        # Hide the table's little toolbar (show/hide columns, search, download) so nobody can hide the trigger columns by accident
        st.markdown("<style>[data-testid='stElementToolbar'] { display: none !important; }</style>", unsafe_allow_html=True)
        
        for active_tab_obj, tab_choice in {tab_a: "Prevention A", tab_b: "Prevention B", tab_c: "Prevention C", tab_comp: "Compliance"}.items():
            with active_tab_obj:
                if tab_choice == "Compliance":
                    st.caption("Keeping records for audits or inspections? See the optional steps on the Audit Readiness page (save your changes here first).")
                    if st.button("Audit Readiness", key="comp_to_road"): st.session_state.view_mode_override = "Audit Road"; st.rerun()
                st.markdown("<div style='display:flex; white-space:nowrap; font-weight:900; color:#000080; font-size:12pt; margin-bottom:4px;'>"
                            "<div style='width:335px; flex:none;'></div>"
                            "<div style='width:168px; flex:none; text-align:center; border-bottom:2px solid #000080;'>Last Done</div>"
                            "<div style='width:148px; flex:none; text-align:center; border-bottom:2px solid #000080; margin-left:2px;'>Trigger Interval</div>"
                            "</div>", unsafe_allow_html=True)
                with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                    tasks_df = pd.read_sql('SELECT TaskName, Date_Last_Done, Meter_At_Last, Days_Between, Meter_Between, ToolsNeeded, ManHours, TaskDescription, PersonnelQualifications, SafetyPrecautions, EstimatedPartsCost, RequiredConsumables FROM "Preventive_Schedules" WHERE AssetID = ? AND TabGroup = ?', conn, params=(asset_id_clean, tab_choice))
                
                if tasks_df.empty: 
                    seed_tasks = [t[1:] for t in CATEGORY_TASK_TEMPLATES.get(selected_category, []) if t[0] == tab_choice]
                    if seed_tasks:
                        _cm0 = int(current_unit["Current_Meter"]) if pd.notnull(current_unit["Current_Meter"]) else 0
                        seed_tasks = [(t[0], datetime.now().strftime("%Y-%m-%d"), _cm0) + tuple(t[3:]) for t in seed_tasks]
                        tasks_df = pd.DataFrame(seed_tasks, columns=["TaskName", "Date_Last_Done", "Meter_At_Last", "Days_Between", "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", "PersonnelQualifications", "SafetyPrecautions", "EstimatedPartsCost", "RequiredConsumables"])
                    else:
                        tasks_df = pd.DataFrame([["N/A", "", "0", "30", "1000", "Standard Tools", 1.0, "Routine", "Tech", "LOTO", 0.0, "None"]]*12, columns=["TaskName", "Date_Last_Done", "Meter_At_Last", "Days_Between", "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", "PersonnelQualifications", "SafetyPrecautions", "EstimatedPartsCost", "RequiredConsumables"])
                
                # --- BUG FIX: Force these columns to string before applying TextColumn formatting ---
                tasks_df["Meter_At_Last"] = tasks_df["Meter_At_Last"].astype(str)
                tasks_df["Days_Between"] = tasks_df["Days_Between"].astype(str)
                tasks_df["Meter_Between"] = tasks_df["Meter_Between"].astype(str)
                
                updated_dfs[tab_choice] = st.data_editor(
                    tasks_df, 
                    use_container_width=True, 
                    height=786, row_height=30, 
                    num_rows="dynamic", 
                    hide_index=True, 
                    key=f"editor2_{tab_choice}_{asset_id_clean}", 
                    column_config={
                        "TaskName": st.column_config.TextColumn("Maintenance Tasks", width=300, pinned=True), 
                        "Date_Last_Done": st.column_config.TextColumn("Date", width=84), 
                        "Meter_At_Last": st.column_config.TextColumn("Kms/Hrs", width=84), 
                        "Days_Between": st.column_config.TextColumn("Days", width=64), 
                        "Meter_Between": st.column_config.TextColumn("Kms/Hrs", width=84), 
                        "ToolsNeeded": st.column_config.TextColumn("Tools & Equip"), 
                        "ManHours": st.column_config.NumberColumn("ManHours", format="%.1f", width="small"), 
                        "TaskDescription": st.column_config.TextColumn("TaskDescription"), 
                        "PersonnelQualifications": st.column_config.TextColumn("Qualifications"), 
                        "SafetyPrecautions": st.column_config.TextColumn("Safety/LOTO"), 
                        "EstimatedPartsCost": st.column_config.NumberColumn("Cost ($)", format="%.2f", width="small"), 
                        "RequiredConsumables": st.column_config.TextColumn("Consumables")
                    }
                )

        with tab_bom:
             with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                attr_df = pd.read_sql('SELECT AttrID, AttributeName, Value, Notes FROM "Asset_Attributes" WHERE AssetID = ?', conn, params=(asset_id_clean,))
                parts_tbl_df = pd.read_sql('SELECT PartID, PartHeading, PartDescription, Supplier, PowerUsage, Inventory, Status FROM "Asset_Parts" WHERE AssetID = ?', conn, params=(asset_id_clean,))
                comp_df = pd.read_sql('SELECT ComponentID, ComponentName, PartNumber, ConditionStatus, Notes FROM "Asset_Components" WHERE AssetID = ?', conn, params=(asset_id_clean,))
             
             st.markdown(f"### Asset Structure & Bill of Materials (BOM) for Asset {asset_id_clean}")
             st.caption("Edit any cell, or add and delete rows (click the empty row at the bottom to add one), then click **Save** at the top of the page.")
             _id_col = lambda: st.column_config.NumberColumn("ID", width="small", disabled=True)
             st.markdown("**Attributes** (facts about this asset)")
             bom_attr_edit = st.data_editor(attr_df, key=f"attr_editor_{asset_id_clean}", use_container_width=True, height=200, hide_index=True, num_rows="dynamic", column_config={"AttrID": _id_col()}, row_height=30)
             st.markdown("**Parts** (the main assemblies and systems)")
             bom_parts_edit = st.data_editor(parts_tbl_df, key=f"parts_tbl_editor_{asset_id_clean}", use_container_width=True, height=250, hide_index=True, num_rows="dynamic", column_config={"PartID": _id_col()}, row_height=30)
             st.markdown("**Components** (the smaller numbered pieces inside the parts, with their condition)")
             bom_comp_edit = st.data_editor(comp_df, key=f"comp_editor_{asset_id_clean}", use_container_width=True, height=250, hide_index=True, num_rows="dynamic", column_config={"ComponentID": _id_col()}, row_height=30)
             
        with tab_fin:
             with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                 fin_row = conn.execute('SELECT * FROM "Trucks" WHERE AssetID = ?', (asset_id_clean,)).fetchone()
                 fin_cols = [description[0] for description in conn.execute('PRAGMA table_info("Trucks")').fetchall()]
             fin_dict = dict(zip(fin_cols, fin_row)) if fin_row else {}
             
             purch_price = float(fin_dict.get("Purchase_Price", 50000.0) or 50000.0)
             salvage = float(fin_dict.get("Salvage_Value", 5000.0) or 5000.0)
             dep_life = float(fin_dict.get("Depreciable_Life", 15) or 15)
             cur_val = float(fin_dict.get("Current_Value", 45000.0) or 45000.0)
             
             st.markdown(f"### Financial & Asset Valuation Suite for Asset {asset_id_clean}")
             f_c1, f_c2, f_c3, f_c4 = st.columns(4)
             f_c1.metric("Net Book Value (NBV)", f"${cur_val:,.2f}")
             f_c2.metric("Accumulated Deprec.", f"${purch_price - cur_val:,.2f}")
             f_c3.metric("Total Cost (TCO)", f"${purch_price + 500.0:,.2f}")
             f_c4.metric("YTD Maint. Spend", f"${float(fin_dict.get('Total_Maintenance_Spend', 0.0) or 0.0):,.2f}")
             
             ledger_col1, ledger_col2 = st.columns(2, gap="large")
             with ledger_col1: 
                 st.text_input("Date Acquired:", value=str(fin_dict.get("Date_Acquired", "2021-06-01")), key=f"fin_acq_{asset_id_clean}")
                 st.text_input("Purchase Price ($):", value=f"{purch_price:,.2f}", key=f"fin_price_{asset_id_clean}")
                 st.text_input("Current Book Value ($):", value=f"{cur_val:,.2f}", key=f"fin_val_{asset_id_clean}")
             with ledger_col2: 
                 st.text_input("Depreciation Method:", value=str(fin_dict.get("Deprec_Method", "Straight-Line")), key=f"fin_dep_{asset_id_clean}")
                 st.text_input("Insurance Policy #:", value=str(fin_dict.get("Insurance_Policy", "POL-99281-MX")), key=f"fin_pol_{asset_id_clean}")
                 st.text_input("Annual Premium ($):", value="500.00", key=f"fin_prem_{asset_id_clean}")
                 
             bot_col1, bot_col2 = st.columns(2, gap="large")
             with bot_col1: 
                 st.text_input("Serial # / Asset Tag:", value=str(fin_dict.get("SerialNumber", f"SN-{asset_id_clean}")), key=f"fin_sn_{asset_id_clean}")
                 st.text_input("Plate # / Registration:", value=str(fin_dict.get("Plate_Number", "")), key=f"fin_plate_{asset_id_clean}")
                 st.text_input("Color:", value=str(fin_dict.get("Color", "Standard")), key=f"fin_color_{asset_id_clean}")
             with bot_col2: 
                 st.text_area("Audit Notes:", value=str(fin_dict.get("Incident_Memo", "Asset fully operational and compliant.")), height=115, key=f"fin_memo_{asset_id_clean}")

        if save_btn:
            validation_error = False
            _short = []
            _baddate = []
            for tab_choice in ["Prevention A", "Prevention B", "Prevention C", "Compliance"]:
                for _, _r in updated_dfs[tab_choice].iterrows():
                    if str(_r.get("TaskName", "")).strip() in ["", "N/A", "None"]: continue
                    try: _d = int(float(str(_r.get("Days_Between", 0)).replace(",", "").strip() or 0))
                    except (TypeError, ValueError): _d = 0
                    if 0 < _d < MIN_SCHEDULE_DAYS: _short.append(short_interval_text(str(_r.get("TaskName")).strip(), _d))
                    _dtxt = str(_r.get("Date_Last_Done", "")).strip()
                    if _dtxt and _dtxt.lower() not in ("none", "nan"):
                        _pday = _parse_day(_dtxt)
                        _tn = str(_r.get("TaskName")).strip()
                        if _pday is None: _baddate.append(f"⚠️ {_tn}: \"{_dtxt}\" is not a valid date. Use year-month-day, like 2026-10-08.")
                        elif _pday > _date.today(): _baddate.append(f"⚠️ {_tn}: {_dtxt} is in the future. A job can't have been done on a day that hasn't happened yet.")
            for tab_choice in ["Prevention A", "Prevention B", "Prevention C", "Compliance"]:
                for _, row in updated_dfs[tab_choice].iterrows():
                    try: 
                        mal = float(str(row.get("Meter_At_Last", 0)).replace(',', '').strip())
                    except: 
                        mal = 0.0
                    if mal > updated_meter: 
                        validation_error = True
                        break
                if validation_error: 
                    break
                    
            if _short or _baddate:
                for _m in _short: _msg_slot.error("⚠️ " + _m)
                for _m in _baddate: _msg_slot.error(_m)
            elif validation_error: 
                _msg_slot.error(f"⚠️ Validation Error: A task 'Last Done' meter cannot exceed the unit's Current Kms/Hrs ({updated_meter:,}). Time doesn't flow backwards!")
            else:
                with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                    conn.execute('UPDATE "Trucks" SET Disregard_Dates = ?, Current_Meter = ? WHERE AssetID = ?', 
                                 (1 if disregard_dates else 0, updated_meter, asset_id_clean))
                    save_bom_tables(conn, asset_id_clean, bom_attr_edit, bom_parts_edit, bom_comp_edit)
                    
                    for tab_choice in ["Prevention A", "Prevention B", "Prevention C", "Compliance"]:
                        conn.execute('DELETE FROM "Preventive_Schedules" WHERE AssetID = ? AND TabGroup = ?', (asset_id_clean, tab_choice))
                        for _, row in updated_dfs[tab_choice].iterrows():
                            if str(row.get("TaskName", "")).strip() not in ["", "N/A", "None"]:
                                conn.execute("""INSERT INTO "Preventive_Schedules" 
                                                ("AssetID", "TabGroup", "TaskName", "Date_Last_Done", "Meter_At_Last", 
                                                 "Days_Between", "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", 
                                                 "PersonnelQualifications", "SafetyPrecautions", "EstimatedPartsCost", "RequiredConsumables") 
                                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                                             (asset_id_clean, tab_choice, str(row.get("TaskName")), str(row.get("Date_Last_Done")), 
                                              str(row.get("Meter_At_Last")), str(row.get("Days_Between")), str(row.get("Meter_Between")), 
                                              str(row.get("ToolsNeeded")), float(row.get("ManHours", 1.0)), str(row.get("TaskDescription")), 
                                              str(row.get("PersonnelQualifications")), str(row.get("SafetyPrecautions")), 
                                              float(row.get("EstimatedPartsCost", 0.0)), str(row.get("RequiredConsumables"))))
                    conn.commit()
                _msg_slot.success("Schedules updated!")
                time.sleep(1.0)
                st.rerun()
    else: 
        st.warning("No asset units found in this category.")
elif view_mode == "Completed (W/O)":
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        tasks_df = pd.read_sql('''
            SELECT p.TaskID, p.AssetID, p.TaskName, p.ManHours
            FROM "Preventive_Schedules" p
            JOIN "Trucks" t ON p.AssetID = t.AssetID
            WHERE t.Category = ?
            ORDER BY p.AssetID, p.TaskName
        ''', conn, params=(selected_category,))
        cat_assets = [r[0] for r in conn.execute('SELECT AssetID FROM "Trucks" WHERE Category = ? ORDER BY AssetID', (selected_category,)).fetchall()]
        first_done = conn.execute('''SELECT MIN(substr(c.DateCompleted,1,10)) FROM "Completed_Work_Orders" c
                                   JOIN "Trucks" t ON c.AssetID = t.AssetID WHERE t.Category = ?''', (selected_category,)).fetchone()[0]

    # Header: title and time stamp on the left, the two buttons stacked at the top right, same size.
    c_head, c_btns = st.columns([3.2, 1])
    with c_head:
        st.subheader("Completed & Signed-Off Work Orders Archive", anchor=False)
        st.markdown("*(Interactive Sign-Off and Historical Compliance Record)*")
        if get_setting("audit_features", "0") != "1":
            st.markdown("*(Optional extras: failure fields and an audit trail. See Audit Readiness on the Switchboard.)*")
        st.markdown(f"<p style='margin-top:-6px;'><b>Date and Time Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", unsafe_allow_html=True)
    with c_btns:
        st.markdown("<style></style>", unsafe_allow_html=True)
        if st.button("Switchboard", key="btn_sw_cwo", use_container_width=True):
            st.session_state.view_mode_override = "Switchboard"
            st.rerun()
        if not tasks_df.empty:
            try:
                st.download_button("🖨️ Download PDFs", data=build_signoff_pdf(selected_category, tasks_df),
                                   file_name=f"SignOff_{selected_category.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", key="dl_signoff_pdf", use_container_width=True)
            except ImportError:
                st.error("ReportLab not installed. Run: python -m pip install reportlab")

    _AUD_ON = get_setting("audit_features", "0") == "1"
    tab_sign, tab_hist, *_tab_more = st.tabs(["Sign-Off Sheet", "History"] + (["Record a Breakdown"] if _AUD_ON else []))
    tab_fail = _tab_more[0] if _tab_more else None

    # ---------------- TAB 1: sign-off sheet ----------------
    with tab_sign:
        if not tasks_df.empty:
            st.markdown("""
                <div class="screen-only-header" style='display: flex; margin-top: 20px; font-weight: bold; border-bottom: 1px solid #ccc; padding-bottom: 5px;'>
                    <div style='flex: 3;'>Select and Execute Sign-Off for Due Tasks:</div>
                    <div style='flex: 1; text-align: center;'>Hours</div>
                    <div style='flex: 1; text-align: center;'>Tech Initials</div>
                </div>
            """, unsafe_allow_html=True)

            st.markdown("<style>div[data-testid='stExpander'] { margin-bottom: -0.7rem; } div[data-testid='stExpander'] summary { padding-top: 0.3rem; padding-bottom: 0.3rem; }</style>", unsafe_allow_html=True)
            for _, row in tasks_df.iterrows():
                tid = int(row['TaskID'])
                _done_set = st.session_state.setdefault("signed_done", set())
                _mark = "✅ " if tid in _done_set else ""
                with st.expander(f"{_mark}{row['AssetID']} — {row['TaskName']}"):
                    ec1, ec2, ec3 = st.columns([3, 1, 1])
                    with ec1:
                        st.write(f"**Sign off completed work for:** {row['TaskName']}")
                        st.caption("Enter the hours and the technician's initials from the paper sheet, then click Commit.")
                    with ec2:
                        st.number_input("Log Hours:", value=float(row['ManHours'] or 0), min_value=0.0, step=0.5, key=f"hr_{tid}")
                    with ec3:
                        st.text_input("Tech Initials:", key=f"sig_{tid}", placeholder="Type initials, e.g. JD", help="Type the technician's initials from the paper work order, then press Enter and click Commit.")
                        if st.button("Commit", key=f"commit_{tid}", use_container_width=True):
                            ok, msg = commit_signoff(tid, st.session_state.get(f"hr_{tid}", row['ManHours']), st.session_state.get(f"sig_{tid}", ""))
                            if ok:
                                st.success(msg)
                                time.sleep(3)
                                _done_set.add(tid)
                                st.rerun()
                            else:
                                st.error(msg)
                                if "already signed off today" in msg:
                                    time.sleep(3)
                                    _done_set.add(tid)
                                    st.rerun()
        else:
            st.info("No active tasks found for this asset group.")

    # ---------------- TAB 2: history ----------------
    with tab_hist:
        try: default_from = _date.fromisoformat(first_done) if first_done else _date.today() - _timedelta(days=90)
        except ValueError: default_from = _date.today() - _timedelta(days=90)
        hf1, hf2, hf3 = st.columns([1, 1, 2])
        with hf1: from_d = st.date_input("From", value=default_from, key=f"hist_from_{selected_category}")
        with hf2: to_d = st.date_input("To", value=_date.today(), key=f"hist_to_{selected_category}")
        with hf3: sel_assets = st.multiselect("Assets (leave blank for all)", cat_assets, key=f"hist_assets_{selected_category}")

        if from_d > to_d:
            st.error("'From' date must not be after 'To' date.")
        else:
            hist_df = fetch_history(selected_category, from_d, to_d, sel_assets)
            if hist_df.empty:
                st.info("No completed work orders match these filters.")
            else:
                h_hours = pd.to_numeric(hist_df["Hours"], errors="coerce").fillna(0).sum()
                h_cost = pd.to_numeric(hist_df["Cost"], errors="coerce").fillna(0).sum()
                st.caption(f"{len(hist_df)} completed work orders  |  {h_hours:,.1f} labor hours  |  ${h_cost:,.2f}")
                try:
                    st.download_button("🖨️ Download History (PDF)", data=build_history_pdf(selected_category, hist_df, from_d, to_d, sel_assets),
                                       file_name=f"History_{selected_category.replace(' ', '_')}_{from_d:%Y%m%d}-{to_d:%Y%m%d}.pdf",
                                       mime="application/pdf", key="dl_history_pdf")
                except ImportError:
                    st.error("ReportLab not installed. Run: python -m pip install reportlab")
                st.dataframe(hist_df, use_container_width=True, hide_index=True, row_height=30)

    if _AUD_ON and tab_fail is not None:
        # ---------------- TAB 3: record a breakdown (failure data) ----------------
        with tab_fail:
            st.caption("Pound of cure: when something breaks, record it here with the failure details. Over time this shows which failures and causes keep coming back, "
                       "and how much downtime they cost. The fields follow the ideas in the reliability data standard ISO 14224 (we worked from published summaries, not the standard itself). "
                       "Then ask why it failed, and add or adjust a preventive task so it is caught next time.")
            _FMODES = ["Fail to start", "Spurious stop", "External leak", "Internal leak", "Vibration", "Overheating", "Abnormal noise", "Low output or poor performance", "Electrical fault", "Structural damage or crack", "Other"]
            _FMECHS = ["Not known", "Wear", "Corrosion", "Fatigue", "Erosion", "Overload", "Overheating", "Contamination", "Lack of lubrication", "Loose or vibration", "Electrical breakdown", "Impact damage", "Ageing or degradation", "Other"]
            _FCAUSES = ["Wear or age", "Design or manufacture", "Installation", "Operation or misuse", "Maintenance missed or poor", "External (weather, power, damage)", "Not known yet"]
            if not cat_assets:
                st.info("No assets in this group yet.")
            else:
                with st.form("fail_form", clear_on_submit=True):
                    _fa1, _fa2, _fa3 = st.columns(3)
                    with _fa1:
                        _f_asset = st.selectbox("Asset", cat_assets, key="fail_asset")
                        _f_date = st.date_input("Date of failure", value=_date.today(), key="fail_date")
                    with _fa2:
                        _f_mode = st.selectbox("How it failed (failure mode)", _FMODES, key="fail_mode")
                        _f_cause = st.selectbox("Why it failed (cause)", _FCAUSES, key="fail_cause")
                    with _fa3:
                        _f_mech = st.selectbox("Mechanism", _FMECHS, key="fail_mech")
                        _f_meter = st.text_input("Meter reading", key="fail_meter", help="Hours, km or whatever the machine's meter counts")
                    _fb1, _fb2, _fb3, _fb4 = st.columns(4)
                    with _fb1: _f_down = st.number_input("Downtime (hours)", min_value=0.0, step=0.5, key="fail_down")
                    with _fb2: _f_hrs = st.number_input("Repair labor (hours)", min_value=0.0, step=0.5, key="fail_hrs")
                    with _fb3: _f_cost = st.number_input("Total cost", min_value=0.0, step=10.0, key="fail_cost")
                    with _fb4: _f_init = st.text_input("Technician initials", key="fail_init")
                    _f_parts = st.text_input("Parts used", key="fail_parts")
                    _f_notes = st.text_area("What was done, and what will stop it happening again (corrective action)", key="fail_notes")
                    _f_go = st.form_submit_button("Save breakdown record")
                if _f_go:
                    if not (_f_init or "").strip():
                        st.error("Enter the technician's initials.")
                    else:
                        try:
                            with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                                _cur = conn.execute('''INSERT INTO "Completed_Work_Orders" ("AssetID","TaskName","DateCompleted","TechnicianName","LaborHours","PartsUsed","TotalCost","Notes",
                                                "FailureMode","FailureCause","FailureMechanism","DowntimeHours","MeterReading") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                             (_f_asset, "Breakdown repair", _f_date.isoformat(), _f_init.strip(), float(_f_hrs), (_f_parts or "").strip(), float(_f_cost), (_f_notes or "").strip(),
                                              _f_mode, _f_cause, (_f_mech if _f_mech != "Not known" else ""), float(_f_down), (_f_meter or "").strip()))
                                conn.commit()
                            _new_id = _cur.lastrowid
                            log_change("Breakdown recorded", "Completed_Work_Orders", f"BD_ID {_new_id}: {_f_asset}", f"{_f_mode}; cause: {_f_cause}; downtime {_f_down:g} h")
                            st.success(f"Breakdown recorded as BD_ID {_new_id}. Now ask why, and add or adjust a preventive task so it is caught next time.")
                        except sqlite3.Error as _e:
                            st.error(f"Database error, nothing was saved: {_e}")
                with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                    _fdf = pd.read_sql('''SELECT c.HistoryID AS "BD_ID", substr(c.DateCompleted,1,10) AS "Date", c.AssetID AS "Asset", c.FailureMode AS "Failure mode", c.FailureCause AS "Cause",
                                               c.FailureMechanism AS "Mechanism", c.DowntimeHours AS "Downtime (h)", c.LaborHours AS "Repair (h)", c.TotalCost AS "Cost", c.MeterReading AS "Meter",
                                               c.TechnicianName AS "Tech", c.PartsUsed AS "Parts", c.Notes AS "Notes"
                                        FROM "Completed_Work_Orders" c JOIN "Trucks" t ON c.AssetID = t.AssetID
                                        WHERE t.Category = ? AND c.FailureMode IS NOT NULL AND c.FailureMode <> ""
                                        ORDER BY c.DateCompleted DESC, c.HistoryID DESC''', conn, params=(selected_category,))
                if _fdf.empty:
                    st.caption("No breakdowns recorded for this group yet.")
                else:
                    _fm1, _fm2, _fm3 = st.columns(3)
                    _fm1.metric("Breakdowns recorded", len(_fdf))
                    _fm2.metric("Downtime (hours)", f"{pd.to_numeric(_fdf['Downtime (h)'], errors='coerce').fillna(0).sum():,.1f}")
                    _fm3.metric("Repair cost", f"${pd.to_numeric(_fdf['Cost'], errors='coerce').fillna(0).sum():,.2f}")
                    _fc1, _fc2 = st.columns(2)
                    with _fc1:
                        st.markdown("**Most common causes**")
                        st.dataframe(_fdf["Cause"].value_counts().rename_axis("Cause").reset_index(name="Count"), use_container_width=True, hide_index=True)
                    with _fc2:
                        st.markdown("**Most common failure modes**")
                        st.dataframe(_fdf["Failure mode"].value_counts().rename_axis("Failure mode").reset_index(name="Count"), use_container_width=True, hide_index=True)
                    st.markdown("**Breakdown records**")
                    st.dataframe(_fdf.drop(columns=["Parts", "Notes"]), use_container_width=True, hide_index=True)
                    st.markdown("**Memo for a record** (the full notes and parts stay with the record)")
                    _memo_opts = {f"BD_ID {int(r['BD_ID'])}  {r['Date']}  {r['Asset']}  {r['Failure mode']}": r for _, r in _fdf.iterrows()}
                    _memo_pick = st.selectbox("Pick a BD_ID to read its memo", list(_memo_opts.keys()), key="fail_memo_pick")
                    _mr = _memo_opts[_memo_pick]
                    st.text_area("Parts used", value=str(_mr["Parts"] or ""), disabled=True, key=f"fail_memo_parts_{int(_mr['BD_ID'])}")
                    st.text_area("What was done, and what will stop it happening again", value=str(_mr["Notes"] or ""), height=140, disabled=True, key=f"fail_memo_notes_{int(_mr['BD_ID'])}")
elif view_mode == "WorkOrders (W/O)":
    wo_head = st.empty()      # heading is filled in below, once we know which scope is showing
    
    btn_col_wo1, btn_col_wo2, btn_col_wo3 = st.columns(3)
    with btn_col_wo1: 
        btn_gen_batch = st.button("Generate All W/O's", key="btn_gen_batch_wo", use_container_width=True)
    with btn_col_wo3: 
        btn_sw_wo = st.button("Switchboard", key="btn_sw_wo", use_container_width=True)
    btn_row2 = st.columns(3)
    with btn_row2[0]:
        btn_gen_group = st.button(f"W/O's {selected_category} Only", key="btn_gen_group_wo", use_container_width=True)

    if btn_sw_wo: 
        st.session_state.view_mode_override = "Switchboard"
        st.rerun()

    st.session_state["sched_from_wo"] = False   # arriving here clears the "opened from Work Orders" note on the schedule screen
    if "wo_triggered_df" not in st.session_state: 
        st.session_state.wo_triggered_df = None
    if "wo_scope" not in st.session_state: 
        st.session_state.wo_scope = "all"
    if "last_wo_category" not in st.session_state: 
        st.session_state.last_wo_category = selected_category
    if st.session_state.last_wo_category != selected_category: 
        st.session_state.last_wo_category = selected_category
        if st.session_state.wo_scope != "all":      # a one-group list no longer matches; the all-groups list still does
            st.session_state.wo_triggered_df = None

    if btn_gen_batch or btn_gen_group:
        st.session_state.wo_scope = "all" if btn_gen_batch else selected_category
        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            query = """SELECT t.AssetID, t.Year_Make_Model, t.Category, t.Maintenance_Protocol, t.Disregard_Dates, 
                       p.TabGroup, p.TaskName, p.Date_Last_Done, p.Meter_At_Last, p.Days_Between, p.Meter_Between, 
                       p.ToolsNeeded, p.ManHours, p.TaskDescription, p.PersonnelQualifications, p.SafetyPrecautions, 
                       p.EstimatedPartsCost, p.RequiredConsumables, t.Current_Meter 
                       FROM "Preventive_Schedules" p 
                       JOIN "Trucks" t ON p.AssetID = t.AssetID """
            if btn_gen_batch:
                all_tasks = pd.read_sql(query + "ORDER BY t.Category, t.AssetID, p.TaskID", conn)
            else:
                all_tasks = pd.read_sql(query + "WHERE t.Category = ? ORDER BY t.AssetID, p.TaskID", conn, params=(selected_category,))
            
        triggered_tasks = []
        for idx, row in all_tasks.iterrows():
            try: meter_at_last = float(str(row["Meter_At_Last"]).replace(',', '').strip()) if str(row["Meter_At_Last"]).strip() else 0.0
            except: meter_at_last = 0.0
            try: meter_between = float(str(row["Meter_Between"]).replace(',', '').strip()) if str(row["Meter_Between"]).strip() else 0.0
            except: meter_between = 0.0
            try: days_between = int(str(row["Days_Between"]).replace(',', '').strip()) if str(row["Days_Between"]).strip() else 0
            except: days_between = 0
            current_m = float(row["Current_Meter"]) if pd.notnull(row["Current_Meter"]) else 0.0
            meter_triggered = (meter_between > 0) and ((current_m - meter_at_last) >= meter_between)
            days_triggered = False
            date_str = str(row["Date_Last_Done"]).strip()
            if date_str and date_str.lower() != "none" and date_str != "":
                try: days_triggered = days_between > 0 and (datetime.now() - datetime.strptime(date_str.split()[0], "%Y-%m-%d")).days >= days_between
                except: pass
            is_due = (meter_triggered) if bool(row["Disregard_Dates"]) else (meter_triggered or days_triggered)
            if is_due: 
                triggered_tasks.append(row)
                
        triggered_df = pd.DataFrame(triggered_tasks)
        st.session_state.wo_triggered_df = triggered_df

        if not triggered_df.empty:
            with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                for aid_uniq in triggered_df["AssetID"].unique():
                    uinfo = triggered_df[triggered_df["AssetID"] == aid_uniq]
                    total_cost = uinfo["EstimatedPartsCost"].astype(float).sum() + (uinfo["ManHours"].astype(float).sum() * get_labor_rate())
                    task_names = ', '.join(uinfo['TaskName'].tolist())
                    _desc = f"Generated Batch Work Order: {task_names}"
                    _today_s = datetime.now().strftime("%Y-%m-%d")
                    if conn.execute('SELECT 1 FROM "WorkOrders" WHERE AssetID = ? AND substr(ServiceDate, 1, 10) = ? AND Description = ?', (aid_uniq, _today_s, _desc)).fetchone():
                        continue      # already generated today: do not record the same work order twice
                    conn.execute("""INSERT INTO "WorkOrders" ("AssetID", "ServiceDate", "MyCompany", "Description", "TotalCost") 
                                    VALUES (?, ?, ?, ?, ?)""", 
                                 (aid_uniq, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), get_company_name(), _desc, total_cost))
                conn.commit()
            st.success(f"Active work orders successfully generated: {triggered_df['AssetID'].nunique()} unit(s) in {triggered_df['Category'].nunique()} asset group(s).")

    _scope_label = "All Asset Groups" if st.session_state.wo_scope == "all" else selected_category
    wo_head.markdown(f"<h3 style='margin-bottom:0;'>Periodic Maintenance & Work Orders: {_scope_label}</h3><p style='margin-top:5px; margin-bottom: 20px;'><b>Date and Time Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", unsafe_allow_html=True)

    if st.session_state.wo_triggered_df is not None:
        triggered_df = st.session_state.wo_triggered_df
        if not triggered_df.empty:
            
            # ==========================================
            # REPORTLAB PDF GENERATOR (Replaces HTML Print)
            # ==========================================
            import io
            try:
                from reportlab.lib.pagesizes import letter
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib import colors

                from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame
                from reportlab.pdfgen import canvas as rl_canvas
                from xml.sax.saxutils import escape as _xml_esc

                def _esc(v):
                    return _xml_esc(str(v)).replace('\n', '<br/>')

                class NumberedCanvas(rl_canvas.Canvas):
                    """Two-pass canvas so every page can show 'Page X of Y'."""
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self._saved_pages = []
                    def showPage(self):
                        self._saved_pages.append(dict(self.__dict__))
                        self._startPage()
                    def save(self):
                        total = len(self._saved_pages)
                        for state in self._saved_pages:
                            self.__dict__.update(state)
                            self.setFont("Helvetica", 9)
                            self.drawRightString(letter[0] - 30, letter[1] - 34, f"Page {self._pageNumber} of {total}")
                            super().showPage()
                        super().save()

                def generate_pdf(df, category):
                    buf = io.BytesIO()
                    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    styles = getSampleStyleSheet()

                    # Page header: drawn by the page template, so it appears on EVERY page
                    def draw_page_header(canvas, doc):
                        w, h = letter
                        canvas.saveState()
                        canvas.setFont("Helvetica-Bold", 12)
                        canvas.drawString(30, h - 34, f"Periodic Maintenance & Work Orders: {category}")
                        canvas.setFont("Helvetica", 9)
                        canvas.drawString(30, h - 47, f"Date and Time Generated: {generated}")
                        canvas.setLineWidth(0.75)
                        canvas.line(30, h - 53, w - 30, h - 53)
                        # Shop Supervisor sign-off at the bottom of every sheet (each unit's sheet is a signed record on its own)
                        canvas.setFont("Helvetica-Bold", 9.5)
                        canvas.drawString(30, 40, "Shop Supervisor Signature:")
                        canvas.setLineWidth(0.5)
                        canvas.line(180, 40, 380, 40)
                        canvas.drawString(392, 40, "Date:")
                        canvas.line(424, 40, w - 30, 40)
                        canvas.restoreState()
                        draw_licensee_line(canvas)

                    doc = BaseDocTemplate(buf, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=66, bottomMargin=62)
                    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
                    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_page_header)])
                    elements = []

                    # One sheet per unit: every asset starts on its own page with its own signature line, so it can be handed to the mechanic.
                    _first_sheet = True
                    for cat_name in df["Category"].unique():
                        cat_df = df[df["Category"] == cat_name]
                        for asset_id in cat_df["AssetID"].unique():
                            if not _first_sheet: elements.append(PageBreak())
                            _first_sheet = False
                            _n_tasks = int((cat_df["AssetID"] == asset_id).sum())
                            elements.append(Paragraph(f"<b>Asset Group: {_esc(cat_name)}</b> &nbsp;&nbsp; ({_n_tasks} task(s))", styles['Normal']))
                            elements.append(Spacer(1, 6))

                            # Build Table Data (First row is the repeating column header)
                            table_data = [[
                                Paragraph("<b>Task & Asset</b>", styles['Normal']),
                                Paragraph("<b>Requirements & Instructions</b>", styles['Normal'])
                            ]]
                            asset_row_idxs = []

                            unit_info = cat_df[cat_df["AssetID"] == asset_id]
                            year_make = _esc(unit_info['Year_Make_Model'].iloc[0])

                            asset_row_idxs.append(len(table_data))
                            _head_par = Paragraph(f"<b>{_esc(asset_id)}</b> &nbsp;&mdash;&nbsp; <b>{year_make}</b>", styles['Normal'])
                            _head_cell = _head_par
                            # the unit photo goes in the empty space under the first task's name (not in the header row, which would make it tall)
                            _photo_flow = None
                            if asset_photo_exists(asset_id, False):
                                try:
                                    from reportlab.platypus import Image as RLImage
                                    from PIL import Image as _PILImage
                                    _pp = asset_photo_path(asset_id, False)
                                    with _PILImage.open(_pp) as _pi: _pw, _ph = _pi.size
                                    _sc = min(142.0 / _pw, 94.0 / _ph)
                                    _photo_flow = RLImage(_pp, width=_pw * _sc, height=_ph * _sc, hAlign="LEFT")
                                except Exception:
                                    _photo_flow = None
                            table_data.append([_head_cell, ""])

                            _first_task = True
                            for _, row in unit_info.iterrows():
                                left_col = Paragraph(f"<b>{_esc(row['TaskName'])}</b>", styles['Normal'])
                                if _first_task and _photo_flow is not None:
                                    left_col = [left_col, Spacer(1, 5), _photo_flow]
                                _first_task = False
                                try: cost = float(row['EstimatedPartsCost'])
                                except: cost = 0.0
                                right_col = Paragraph(
                                    f"<b>Tools:</b> {_esc(row['ToolsNeeded'])}<br/>"
                                    f"<b>Quals:</b> {_esc(row['PersonnelQualifications'])}<br/>"
                                    f"<b>Hours:</b> {_esc(row['ManHours'])}<br/>"
                                    f"<b>Instructions:</b> {_esc(row['TaskDescription'])}<br/>"
                                    f"<b>Safety:</b> {_esc(row['SafetyPrecautions'])}<br/>"
                                    f"<b>Cost:</b> ${cost:,.2f}<br/>"
                                    f"<i>Last Done: [{_esc(row['Date_Last_Done'])} @ {_esc(row['Meter_At_Last'])}]</i>",
                                    styles['Normal'])
                                table_data.append([left_col, right_col])

                            # repeatRows=2 repeats the column header and the asset line on every page of a long sheet
                            t = Table(table_data, colWidths=[160, 390], repeatRows=2)
                            style_cmds = [
                                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                                ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                                ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                            ]
                            for r in asset_row_idxs:
                                style_cmds.append(('BACKGROUND', (0, r), (-1, r), colors.whitesmoke))
                                style_cmds.append(('SPAN', (0, r), (-1, r)))
                            t.setStyle(TableStyle(style_cmds))
                            elements.append(t)



                    doc.build(elements, canvasmaker=NumberedCanvas)
                    return buf.getvalue()

                pdf_bytes = generate_pdf(triggered_df, _scope_label)

                with btn_col_wo2:
                    st.download_button(
                        label="🖨️ Download & Print",
                        data=pdf_bytes,
                        file_name=f"WorkOrders_{_scope_label.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
            except ImportError:
                with btn_col_wo2:
                    st.error("ReportLab not installed. Run: pip install reportlab")

            # ==========================================
            # VIEW 2: SCREEN-ONLY UI
            # ==========================================
            _last_cat = None
            for asset_id in triggered_df["AssetID"].unique():
                unit_info = triggered_df[triggered_df["AssetID"] == asset_id]
                _cat_here = str(unit_info["Category"].iloc[0])
                if _cat_here != _last_cat:
                    st.markdown(f"<div style='background:#1b5e20;color:#fff;padding:6px 12px;border-radius:4px;margin:18px 0 8px 0;font-size:14pt;font-weight:bold;'>Asset Group: {_cat_here}</div>", unsafe_allow_html=True)
                    _last_cat = _cat_here
                
                _has_u, _has_p = asset_photo_exists(asset_id, False), asset_photo_exists(asset_id, True)
                tasks_html = "".join([
                    f"<div style='margin-bottom: 12px;'>"
                    f"<span style='font-size: 12pt; font-weight: bold;'>• {row['TaskName']}</span> "
                    f"<br>"
                    f"<div style='margin-left: 20px; line-height: 1.6; font-size: 11pt;'>"
                    f"<b>Tools & Equipment Needed:</b> {str(row['ToolsNeeded']).replace(chr(10), '<br>')}<br>"
                    f"<b>Minimum Personnel Qualifications:</b> {str(row['PersonnelQualifications']).replace(chr(10), '<br>')}<br>"
                    f"<b>Projected Man-Hours:</b> {row['ManHours']} hrs<br>"
                    f"<b>Step-by-Step Instructions:</b> {str(row['TaskDescription']).replace(chr(10), '<br>')}<br>"
                    f"<b>Safety Precautions / LOTO:</b> {str(row['SafetyPrecautions']).replace(chr(10), '<br>')}<br>"
                    f"<b>Estimated Parts Cost:</b> ${float(row['EstimatedPartsCost']):,.2f}<br>"
                    f"<i style='color: #444;'>Trigger Status: Last Done [{row['Date_Last_Done']} @ {row['Meter_At_Last']} Kms/Hrs]</i>"
                    f"</div></div>" 
                    for _, row in unit_info.iterrows()
                ])
                
                _title_html = f"<span style='font-size: 14.5pt; font-weight: bold;'>{asset_id}</span> &nbsp;&mdash;&nbsp; <span style='font-size: 14.5pt; font-weight: bold;'>{unit_info['Year_Make_Model'].iloc[0]}</span>"
                if _has_u:
                    import base64, io as _io
                    _imgs_html = ""
                    for _pl, _has in ((False, _has_u),):      # unit photo only; the plate close-up stays on the Asset Groups screen
                        if _has:
                            _bio = _io.BytesIO(); asset_photo_boxed(asset_photo_path(asset_id, _pl), (300, 225)).save(_bio, "JPEG", quality=80)
                            _imgs_html += f"<img src='data:image/jpeg;base64,{base64.b64encode(_bio.getvalue()).decode()}' style='width:176px;height:132px;border-radius:4px;margin-left:8px;display:block;'>"
                    # photos float at the top right, so the text flows up beside them and wraps back to full width underneath
                    st.markdown(f"""<div style="overflow:hidden; padding-bottom: 0; margin-bottom: 0;"><div style="float:right; margin:0 0 2px 12px;">{_imgs_html}</div><div style="margin-bottom:10px;">{_title_html}</div>{tasks_html}</div>""", unsafe_allow_html=True)
                else:
                    c_card1, c_card2 = st.columns([2.6, 2.4], gap="small")
                    with c_card1:
                        st.markdown(_title_html, unsafe_allow_html=True)
                        st.caption("📷 No photo yet. Add one under Asset Groups (Add Photo button) and it will print beside this unit on the work order.")
                    with c_card2:
                        if st.button("Add Photo", key=f"btn_addphoto_{asset_id}", use_container_width=True, type="secondary"):
                            st.session_state.view_mode_override = "Asset Groups"
                            st.rerun()
                    st.markdown(f"""<div style="padding-bottom: 0; margin-bottom: 0;">{tasks_html}</div>""", unsafe_allow_html=True)
                # View Unit sits at the right, tucked up into the white space under the Step-by-Step line
                st.markdown("<style>[class*='st-key-btn_jump_sched_'] {width:176px; margin-left:auto; margin-top:-94px; margin-bottom:12px;}</style>", unsafe_allow_html=True)
                if True:
                    if st.button("View Unit", key=f"btn_jump_sched_{asset_id}", use_container_width=True):
                        with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
                            cat_res = conn.execute('SELECT Category FROM "Trucks" WHERE AssetID = ?', (asset_id,)).fetchone()
                        if cat_res and cat_res[0]: 
                            st.session_state.active_asset_group = cat_res[0]
                        st.session_state.target_sched_aid = asset_id
                        st.session_state.sched_from_wo = True
                        st.session_state.view_mode_override = "Sched. Maint."
                        st.rerun()
                st.markdown("<div style='border-bottom: 2px solid #888; margin-bottom: 0;'></div>", unsafe_allow_html=True)
                
        else: 
            with btn_col_wo2:
                st.button("🖨️ Download & Print", disabled=True, use_container_width=True)
            st.info(f"All assets under '{_scope_label}' are completely up to date!")
    else: 
        with btn_col_wo2:
            st.button("🖨️ Download & Print", disabled=True, use_container_width=True)
        st.info("Click **'Generate All W/O's'** above to evaluate maintenance triggers for every asset group at once, or use the smaller button for just the group selected on the left.")
        
elif view_mode == "Reports/Queries":
  if "query_view" not in st.session_state: 
      st.session_state.query_view = "Asset Group"
  _rq1, _rq2 = st.columns([4, 1.4])
  with _rq2:
    if st.button("Asset Health and Maintenance", key="rq_to_fleet", use_container_width=True): st.session_state.view_mode_override = "Fleet Health"; st.rerun()
  with _rq1:
    st.caption("Looking for the old Fleet Health page (maintenance mix, spend and maintenance strategies)? It is now called Industrial Asset Health and Maintenance: use the button on the right.")
  
  if os.path.exists("world.jpg"): 
      st.image("world.jpg", use_container_width=True)
  
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      df_filter_source = pd.read_sql('SELECT AssetID, Category, Maintenance_Protocol FROM "Trucks"', conn)
      
      # --- Stable One-Way Sync ---
      if st.session_state.get("rq_last_sidebar") != selected_category:
          st.session_state.rq_last_sidebar = selected_category
          st.session_state.rq_group_filter_ui = selected_category
          st.session_state.rq_aid_filter_ui = "All Assets"

      curr_group = st.session_state.get("rq_group_filter_ui", selected_category)
      curr_aid = st.session_state.get("rq_aid_filter_ui", "All Assets")
      curr_proto = st.session_state.get("rq_proto_filter_ui", "All")
      curr_detail = st.session_state.get("rq_detail_filter_ui", "All")

      groups_list = ["All Groups"] + sorted(df_filter_source["Category"].astype(str).unique().tolist())
      if curr_group not in groups_list: 
          curr_group = "All Groups"

      if curr_group != "All Groups": 
          valid_aids = df_filter_source[df_filter_source["Category"] == curr_group]["AssetID"].astype(str).unique().tolist()
      else: 
          valid_aids = df_filter_source["AssetID"].astype(str).unique().tolist()
          
      aids_list = ["All Assets"] + sorted(valid_aids)
      if curr_aid not in aids_list: 
          curr_aid = "All Assets"
      
      proto_list = ["All"] + sorted(df_filter_source["Maintenance_Protocol"].astype(str).unique().tolist())
      if curr_proto not in proto_list: 
          curr_proto = "All"
      
      detail_opts = PROTOCOL_DETAILS.get(curr_proto, ["All"])
      if curr_detail not in detail_opts: 
          curr_detail = "All"

      def apply_filters(df_to_filter):
          if "AssetID" in df_to_filter.columns:
              if curr_aid != "All Assets": 
                  df_to_filter = df_to_filter[df_to_filter["AssetID"] == curr_aid]
              elif curr_group != "All Groups": 
                  df_to_filter = df_to_filter[df_to_filter["AssetID"].isin(valid_aids)]
          if curr_proto != "All" and "Maintenance_Protocol" in df_to_filter.columns:
              df_to_filter = df_to_filter[df_to_filter["Maintenance_Protocol"] == curr_proto]
          return df_to_filter

      if st.session_state.query_view == "Asset Group":
          df_export = pd.read_sql('SELECT AssetID, Year_Make_Model, Category, Maintenance_Protocol, Current_Meter, Motor, Fuel FROM "Trucks"', conn)
          df_export = apply_filters(df_export)
          if "Category" in df_export.columns: 
              df_export = df_export.drop(columns=["Category"])
          df_export = df_export.rename(columns={"Current_Meter": "Meter", "Motor": "Turbine"})
      elif st.session_state.query_view == "Work Orders":
          df_export = pd.read_sql('SELECT * FROM "WorkOrders"', conn)
          df_export = apply_filters(df_export)
      elif st.session_state.query_view == "Completed History":
          df_export = pd.read_sql('SELECT * FROM "Completed_Work_Orders"', conn)
          df_export = apply_filters(df_export)
          if "LaborHours" in df_export.columns: 
              df_export.rename(columns={"LaborHours": "Hrs."}, inplace=True)
      elif st.session_state.query_view == "Checklists":
          df_export = pd.read_sql('SELECT AssetID, Year_Make_Model, Category AS AssetGroup, Date_Acquired AS Date, Current_Meter AS "Meter/Odo." FROM "Trucks"', conn)
          df_export = apply_filters(df_export)
      elif st.session_state.query_view == "Service Companies":
          df_export = pd.read_sql('SELECT * FROM "ServiceCompanies"', conn)
          
      csv_data = df_export.to_csv(index=False)

  rq_col1, rq_col2, rq_col3, rq_col4 = st.columns([3.5, 1.5, 1.5, 1.5])
  with rq_col1: 
      st.subheader("Reports & Queries Center")
  with rq_col2: 
      btn_save_q = st.button("Save Changes", key="btn_save_top", use_container_width=True)
  with rq_col3: 
      st.download_button("Export to CSV", data=csv_data, file_name=f"{st.session_state.query_view.lower().replace(' ', '_')}.csv", mime="text/csv", use_container_width=True)
  with rq_col4: 
      if st.button("Switchboard", key="btn_sw_rq", use_container_width=True): 
          st.session_state.view_mode_override = "Switchboard"
          st.rerun()

  st.markdown("<span style='color: #8b0000; font-size: 10pt; font-style: italic;'>*Note: Data modified in queries will update the underlying master database table(s).*</span>", unsafe_allow_html=True)
  
  q_b1, q_b2, q_b3, q_b4, q_b5 = st.columns(5)
  with q_b1: 
      if st.button("Asset Group", use_container_width=True): 
          st.session_state.query_view = "Asset Group"
          st.rerun()
  with q_b2: 
      if st.button("Work Orders", use_container_width=True): 
          st.session_state.query_view = "Work Orders"
          st.rerun()
  with q_b3: 
      if st.button("Completed History", use_container_width=True): 
          st.session_state.query_view = "Completed History"
          st.rerun()
  with q_b4: 
      if st.button("Checklists", use_container_width=True): 
          st.session_state.query_view = "Checklists"
          st.rerun()
  with q_b5: 
      if st.button("Service Companies", use_container_width=True): 
          st.session_state.query_view = "Service Companies"
          st.rerun()

  st.markdown(f"<div style='background-color: #e0e0e0; padding: 8px; border: 1px solid #ccc; font-weight: bold; margin-bottom: 15px;'>🔍 Interactive Query Parameter Selectors for: {st.session_state.query_view}</div>", unsafe_allow_html=True)

  f1, f2, f3, f4 = st.columns([1, 1, 1.5, 1.5])
  with f1: 
      st.selectbox("Asset Group", groups_list, index=groups_list.index(curr_group), key="rq_group_filter_ui")
  with f2: 
      st.selectbox("Asset ID", aids_list, index=aids_list.index(curr_aid), key="rq_aid_filter_ui")
  with f3: 
      st.selectbox("Service Protocol", proto_list, index=proto_list.index(curr_proto), key="rq_proto_filter_ui")
  with f4: 
      st.selectbox("Protocol Detail", detail_opts, index=detail_opts.index(curr_detail), key="rq_detail_filter_ui")
          
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      if st.session_state.query_view == "Asset Group":
          edited_df = st.data_editor(df_export, use_container_width=True, height=500, key="editor_asset_list", hide_index=True, row_height=30)
          if btn_save_q:
              _conv = len([1 for _i, _r in edited_df.iterrows() if demo_would_convert(_r["AssetID"], _r["Year_Make_Model"])])
              if _conv: demo_cap_gate(_conv)
              for idx, row in edited_df.iterrows():
                  conn.execute('UPDATE "Trucks" SET Year_Make_Model=?, Maintenance_Protocol=?, Current_Meter=?, Motor=?, Fuel=? WHERE AssetID=?', (row["Year_Make_Model"], row["Maintenance_Protocol"], row["Meter"], row["Turbine"], row["Fuel"], row["AssetID"]))
              conn.commit()
              st.success("Master database table(s) updated successfully!")
              time.sleep(1.0)
              st.rerun()
              
      elif st.session_state.query_view == "Service Companies":
          edited_df = st.data_editor(df_export, use_container_width=True, height=500, num_rows="dynamic", key="editor_service", hide_index=True, row_height=30)
          if btn_save_q:
              for idx, row in edited_df.iterrows():
                  cid, c_name = str(row["CompanyID"]).strip(), str(row["CompanyName"]).strip()
                  c_contact, c_phone, c_email, c_spec = str(row.get("ContactPerson", "")).strip(), str(row.get("Phone", "")).strip(), str(row.get("Email", "")).strip(), str(row.get("Specialty", "")).strip()
                  if not cid or not cid.isdigit() or cid == "nan":
                      if c_name and c_name != "nan": 
                          conn.execute('INSERT INTO "ServiceCompanies" ("CompanyName", "ContactPerson", "Phone", "Email", "Specialty") VALUES (?, ?, ?, ?, ?)', (c_name, c_contact, c_phone, c_email, c_spec))
                  else: 
                      conn.execute('UPDATE "ServiceCompanies" SET CompanyName = ?, ContactPerson = ?, Phone = ?, Email = ?, Specialty = ? WHERE CompanyID = ?', (c_name, c_contact, c_phone, c_email, c_spec, int(float(cid))))
              conn.commit()
              st.success("Service Companies updated successfully!")
              time.sleep(1.0)
              st.rerun()
      else:
          st.data_editor(df_export, use_container_width=True, height=500, hide_index=True, row_height=30)
          if btn_save_q: 
              st.info("Direct saving is only enabled for the 'Asset Group' and 'Service Companies' queries.")
              
elif view_mode == "Asset Groups":
  _tt1, _tt2 = st.columns([5, 1.3], gap="small")
  with _tt1: st.subheader("Asset Group & Single Asset Management")
  with _tt2:
    if st.button("Switchboard", key="btn_sw_ag_top", use_container_width=True):
      st.session_state.view_mode_override = "Switchboard"; st.rerun()
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT Category FROM "Trucks" WHERE Category IS NOT NULL AND Category != ""')
    existing_groups = sorted([r[0] for r in cursor.fetchall()], key=str.lower)

  if not existing_groups:
    existing_groups = FULL_CATEGORIES_LIST

  st.caption("Tip: keep group names to 22 characters or fewer so they fit neatly in the side menu and on the Switchboard.")
  _g1, _g2, _g3, _g4 = st.columns([2.3, 2.3, 1.2, 1.5], gap="small")
  with _g1:
    sel_group_to_mod = st.selectbox("Asset group to modify / delete", existing_groups, key="sel_group_to_mod")
  with _g2:
    rename_val = st.text_input("Rename the selected group to", value=sel_group_to_mod, key="rename_group_input", max_chars=22)
  with _g3:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    btn_rename = st.button("Rename", key="btn_rename_group", use_container_width=True)
  with _g4:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    btn_delete = st.button("Delete group", key="btn_delete_group", use_container_width=True)

  if btn_rename:
    new_name = rename_val.strip()
    if new_name and new_name != sel_group_to_mod:
      _pr = demo_pristine_in_group(sel_group_to_mod) if (DEMO_BUILD and DEMO.get("active")) else 0
      if _pr: demo_cap_gate(_pr, 1)
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE "Trucks" SET Category = ? WHERE Category = ?', (new_name, sel_group_to_mod))
        cursor.execute('SELECT AssetID, Year_Make_Model FROM "Trucks" WHERE Category = ?', (new_name,))
        for aid, model in cursor.fetchall():
          if model:
            updated_model = model
            if sel_group_to_mod in model:
              updated_model = updated_model.replace(sel_group_to_mod, new_name)
            elif sel_group_to_mod.endswith('s') and sel_group_to_mod[:-1] in model:
              updated_model = updated_model.replace(sel_group_to_mod[:-1], new_name)
            if updated_model != model:
              cursor.execute('UPDATE "Trucks" SET Year_Make_Model = ? WHERE AssetID = ?', (updated_model, aid))
        conn.commit()
      st.success(f"Successfully renamed '{sel_group_to_mod}' to '{new_name}'!")
      st.session_state.active_asset_group = new_name
      time.sleep(1.0)
      st.rerun()
    else:
      st.warning("Please enter a valid, distinct new name for the group.")


  if btn_delete:
    if len(existing_groups) > 1:
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT AssetID FROM "Trucks" WHERE Category = ?', (sel_group_to_mod,))
        aids = [r[0] for r in cursor.fetchall()]
        for t_aid in aids:
            delete_asset_photo(t_aid)
            for tbl in ["Preventive_Schedules", "Asset_Attributes", "Asset_Parts", "Asset_Components"]:
                cursor.execute(f'DELETE FROM "{tbl}" WHERE AssetID = ?', (t_aid,))
        cursor.execute('DELETE FROM "Trucks" WHERE Category = ?', (sel_group_to_mod,))
        conn.commit()
      st.success(f"Deleted asset group '{sel_group_to_mod}' and all associated units.")
      st.session_state.active_asset_group = [g for g in existing_groups if g != sel_group_to_mod][0]
      time.sleep(1.0)
      st.rerun()
    else:
      st.error("Cannot delete the final remaining asset group.")

  st.markdown("---")
  st.markdown("### Add New Asset Group")
  _n1, _n2 = st.columns([3.0, 1.5], gap="medium")   # same widths as the Single Asset select box below
  with _n1:
    new_group_name = st.text_input("New asset group name (22 characters or fewer)", key="new_group_name_input", max_chars=22)
  with _n2:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    btn_create = st.button("Create group", key="btn_create_group", use_container_width=True)
  if btn_create:
    ng = new_group_name.strip()
    if ng and ng not in existing_groups:
      demo_cap_gate(1, 1)
      aid = f"GRP-{str(int(time.time()))[-4:]}"
      chk_json = json.dumps([{"ChK1": False, "ItemLabel1": "[ N/A ]", "ChK2": False, "ItemLabel2": "[ N/A ]"}] * 5)
      with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
        cursor = conn.cursor()
        cursor.execute("""
          INSERT INTO "Trucks" ("AssetID", "Year_Make_Model", "SerialNumber", "Color", "Motor", "Transmission", "Fuel", "Category", "Maintenance_Protocol", "Current_Meter", "Disregard_Dates", "Checklist_Data_V2")
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (aid, f"New {ng} Model 1", f"SN-{aid}", "Standard", "None", "None", "Various", ng, MAINTENANCE_PROTOCOLS[0], 25100, 0, chk_json))
        string_tasks = [(aid, "Prevention A", "Initial Inspection", "2026-01-01", "1000", "90", "5000", "None", 1.0, "Routine", "Tech", "LOTO", 0.0, "None")]
        cursor.executemany("""INSERT INTO "Preventive_Schedules" ("AssetID", "TabGroup", "TaskName", "Date_Last_Done", "Meter_At_Last", "Days_Between", "Meter_Between", "ToolsNeeded", "ManHours", "TaskDescription", "PersonnelQualifications", "SafetyPrecautions", "EstimatedPartsCost", "RequiredConsumables") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", string_tasks)
        conn.commit()
      st.success(f"Asset group '{ng}' created successfully!")
      st.session_state.active_asset_group = ng
      time.sleep(1.0)
      st.rerun()
    else:
      st.warning("Please provide a unique, non-empty name for the new asset group.")

  st.markdown("---")
  st.markdown("### Single Asset Modification & Deletion")
  st.markdown("*(Select any specific asset record across the database to edit its specifications or delete it permanently)*")
  
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    all_units_df = pd.read_sql('SELECT AssetID, Year_Make_Model, SerialNumber, Color, Motor, Transmission, Fuel, Maintenance_Protocol, Category FROM "Trucks" ORDER BY AssetID', conn)
  
  if not all_units_df.empty:
    unit_opts = all_units_df.apply(lambda r: f"{r['AssetID']} — {r['Year_Make_Model']}", axis=1).tolist()
    st.markdown("<style>[class*='st-key-mod_'] [data-testid='stWidgetLabel'] p {font-size: 0.95rem !important;}</style>", unsafe_allow_html=True)
    # Start on the first asset of the currently selected group (and again whenever that group changes)
    if st.session_state.get("sel_unit_to_mod") not in unit_opts:
      st.session_state.pop("sel_unit_to_mod", None)
      st.session_state.pop("_mod_grp_seen", None)
    _act_grp = st.session_state.get("active_asset_group")
    if st.session_state.get("_mod_grp_seen") != _act_grp:
      st.session_state["_mod_grp_seen"] = _act_grp
      _grp_units = all_units_df[all_units_df["Category"] == _act_grp]
      if not _grp_units.empty:
        _r0 = _grp_units.iloc[0]
        st.session_state["sel_unit_to_mod"] = f"{_r0['AssetID']} — {_r0['Year_Make_Model']}"
    _top_l, _top_r = st.columns([3.0, 1.5], gap="medium")
    with _top_l:
      st.markdown("**Select Asset to Modify or Delete:**")
      selected_unit_str = st.selectbox("Unit", unit_opts, label_visibility="collapsed", key="sel_unit_to_mod")
      selected_aid = selected_unit_str.split(" — ")[0].strip()
      unit_row = all_units_df[all_units_df["AssetID"] == selected_aid].iloc[0]
      _m1, _m2 = st.columns(2, gap="medium")
      with _m1:
        mod_desc = st.text_input("**Model / Description:**", value=str(unit_row["Year_Make_Model"]), key=f"mod_desc_{selected_aid}")
        mod_color = st.text_input("**Color / Finish:**", value=str(unit_row["Color"]), key=f"mod_color_{selected_aid}")
        mod_trans = st.text_input("**Transmission:**", value=str(unit_row["Transmission"]), key=f"mod_trans_{selected_aid}")
      with _m2:
        mod_sn = st.text_input("**Serial Number:**", value=str(unit_row["SerialNumber"]), key=f"mod_sn_{selected_aid}")
        mod_motor = st.text_input("**Primary Mover:**", value=str(unit_row["Motor"]), key=f"mod_motor_{selected_aid}")
        mod_fuel = st.text_input("**Fuel Type:**", value=str(unit_row["Fuel"]), key=f"mod_fuel_{selected_aid}")
      _b1, _b2 = st.columns(2, gap="medium")
      with _b1:      # same width as the left column of fields above
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<style>.st-key-asset_btn_stack {display:flex; flex-direction:column; justify-content:space-between; height:208px;}</style>", unsafe_allow_html=True)
        _stack = st.container(key="asset_btn_stack")
      with _stack:   # top button level with the top upload box, bottom button level with the bottom one
        if st.button("Save Asset Modifications", key=f"btn_save_mod_{selected_aid}", use_container_width=True):
          if demo_would_convert(selected_aid, mod_desc, mod_sn): demo_cap_gate(1)
          with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            conn.execute("""
                UPDATE "Trucks" 
                SET Year_Make_Model=?, SerialNumber=?, Color=?, Motor=?, Transmission=?, Fuel=? 
                WHERE AssetID=?
            """, (mod_desc, mod_sn, mod_color, mod_motor, mod_trans, mod_fuel, selected_aid))
            conn.commit()
          st.success("Asset modifications saved successfully!")
          time.sleep(1.0)
          st.rerun()
        if st.button(f"📋 Copy Asset {selected_aid}", key=f"btn_copy_mod_{selected_aid}", use_container_width=True):
          new_id = duplicate_asset(selected_aid)
          if new_id:
            st.success(f"Asset successfully cloned! New ID: {new_id}")
            time.sleep(1.0)
            st.rerun()
        if st.button(f"🗑️ Delete Asset {selected_aid}", key=f"btn_del_mod_{selected_aid}", use_container_width=True):
          with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
            for tbl in ["Trucks", "Preventive_Schedules", "Asset_Attributes", "Asset_Parts", "Asset_Components"]:
              conn.execute(f'DELETE FROM "{tbl}" WHERE AssetID = ?', (selected_aid,))
            conn.commit()
          delete_asset_photo(selected_aid)
          st.success("Asset permanently deleted.")
          time.sleep(1.0)
          st.rerun()
      with _b2:      # the two upload boxes sit beside the Save / Copy / Delete buttons
        _gen = st.session_state.get("asset_photo_gen", 0)
        for _pl, _name in ((False, "Unit photo (whole unit)"), (True, "ID / model plate close-up (optional)")):
          st.caption(("Replace " if asset_photo_exists(selected_aid, _pl) else "Add ") + _name.lower())
          _pu = st.file_uploader(_name, type=["jpg", "jpeg", "png", "webp"], key=f"asset_photo_up_{selected_aid}_{int(_pl)}_{_gen}", label_visibility="collapsed")
          if _pu is not None and st.button("Use this photo", key=f"btn_use_photo_{selected_aid}_{int(_pl)}", use_container_width=True):
            try:
              save_asset_photo(selected_aid, _pu.getvalue(), _pl); st.session_state["asset_photo_gen"] = _gen + 1; st.rerun()
            except Exception:
              st.error("That file could not be read as a picture. Try a JPG or PNG.")
    with _top_r:
      st.markdown("**Photos** *(printed on work order)*")
      _gen = st.session_state.get("asset_photo_gen", 0)
      _kinds = ((False, "Unit photo (whole unit)"), (True, "ID / model plate close-up (optional)"))
      for _pl, _name in _kinds:       # the pictures first, as large as the column allows
        if asset_photo_exists(selected_aid, _pl):
          st.caption(_name)
          st.image(asset_photo_boxed(asset_photo_path(selected_aid, _pl)), use_container_width=True)
          if st.button("Remove", key=f"btn_rm_photo_{selected_aid}_{int(_pl)}", use_container_width=True): delete_asset_photo(selected_aid, _pl); st.rerun()


elif view_mode == "Suppliers":
  title_row("Suppliers Management Form", "btn_sw_page9")
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    suppliers_df = pd.read_sql('SELECT SupplierID, SupplierName, Category, LeadTimeDays, Phone FROM "Suppliers"', conn)
  suppliers_df["SupplierID"] = suppliers_df["SupplierID"].astype(str)
  edited_suppliers = st.data_editor(suppliers_df, key="suppliers_editor", use_container_width=True, height=500, num_rows="dynamic", hide_index=True, row_height=30)
  if st.button("Save", key="btn_save_suppliers", use_container_width=True):
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      for idx, row in edited_suppliers.iterrows():
        sid, s_name = str(row["SupplierID"]).strip(), str(row["SupplierName"]).strip()
        s_cat, s_lead, s_phone = str(row.get("Category", "")).strip(), str(row.get("LeadTimeDays", "")).strip(), str(row.get("Phone", "")).strip()
        try: i_lead = int(s_lead) if s_lead and s_lead.isdigit() else 0
        except: i_lead = 0
        if not sid or not sid.isdigit() or sid == "nan":
          if s_name and s_name != "nan":
            conn.execute('INSERT INTO "Suppliers" ("SupplierName", "Category", "LeadTimeDays", "Phone") VALUES (?, ?, ?, ?)', (s_name, s_cat, i_lead, s_phone))
        else:
          conn.execute('UPDATE "Suppliers" SET SupplierName = ?, Category = ?, LeadTimeDays = ?, Phone = ? WHERE SupplierID = ?', (s_name, s_cat, i_lead, s_phone, int(float(sid))))
      conn.commit()
    st.success("Suppliers updated successfully!"); st.rerun()

elif view_mode == "Service Co.":
  title_row("Service Companies Management Form", "btn_sw_page10")
  with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
    service_df = pd.read_sql('SELECT CompanyID, CompanyName, ContactPerson, Phone, Email, Specialty FROM "ServiceCompanies"', conn)
  service_df["CompanyID"] = service_df["CompanyID"].astype(str)
  edited_service = st.data_editor(service_df, key="service_editor", use_container_width=True, height=500, num_rows="dynamic", hide_index=True, row_height=30)
  if st.button("Save", key="btn_save_service", use_container_width=True):
    with sqlite3.connect(DB_PATH, timeout=20.0) as conn:
      for idx, row in edited_service.iterrows():
        cid, c_name = str(row["CompanyID"]).strip(), str(row["CompanyName"]).strip()
        c_contact, c_phone, c_email, c_spec = str(row.get("ContactPerson", "")).strip(), str(row.get("Phone", "")).strip(), str(row.get("Email", "")).strip(), str(row.get("Specialty", "")).strip()
        if not cid or not cid.isdigit() or cid == "nan":
          if c_name and c_name != "nan":
            conn.execute('INSERT INTO "ServiceCompanies" ("CompanyName", "ContactPerson", "Phone", "Email", "Specialty") VALUES (?, ?, ?, ?, ?)', (c_name, c_contact, c_phone, c_email, c_spec))
        else:
          conn.execute('UPDATE "ServiceCompanies" SET CompanyName = ?, ContactPerson = ?, Phone = ?, Email = ?, Specialty = ? WHERE CompanyID = ?', (c_name, c_contact, c_phone, c_email, c_spec, int(float(cid))))
      conn.commit()
    st.success("Service Companies updated successfully!"); st.rerun()

from html import escape as _html_escape
st.markdown(f"""<div class="app-footer">&copy; 2026 BioShip Inc. All rights reserved. An Ounce of Prevention v{APP_VERSION}.<br>Licensed to: {_html_escape(LICENSED_TO)}</div>""", unsafe_allow_html=True)
# --- END OF FILE ---