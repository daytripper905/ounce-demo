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
    .block-container, [data-testid="block-container"], .main .block-container { padding-top: 3.0rem !important; padding-bottom: 2rem !important; }
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
    'Service Rigs': dict(
        prefix='SVC',
        model='Class III Mobile Service Rig {i}',
        labels=('Mast Height (m)', 'Pulling Capacity (daN)', 'Carrier Axles', 'BOP Class', 'Fuel Type'),
        parts=('Powerplant / Prime Mover:', 'High Pressure Fluid End:', 'Hydraulic / Power End:', 'Mast / Structural Frame:', 'Control Cab / Instrumentation:', 'BOP / Pressure Control:'),
        attrs=[('Mast Height', '30 meters', 'Double mast'), ('Carrier', '5-Axle', 'Custom frame'), ('Drawworks', '500 HP', 'Mechanical')],
        checklist=[('Inspect hydraulic power tongs & dies', 'Check carrier air ride suspension'), ('Verify BOP actuation & remote panel', 'Inspect guy lines, anchors & turnbuckles'), ('Check pump valves & seats', 'Test engine emergency air intake shutoff'), ('Verify drawworks brake holding', 'Inspect tubing elevators & bails'), ('Check accumulator fluid level & pressure', 'Verify escape line & fall arrest gear')],
        tasks=[
            ('Prevention A', 'Pre-job rig inspection', 1, 24, 1.0, 'Walk around the rig: guy lines, mast pins, brakes, BOP controls and fluid levels.', 'Rig Operator', 'Rig anchored and chocked', 0.0, 'None', 'Checklist'),
            ('Prevention A', 'Wire rope & sheave inspection', 7, 100, 1.0, 'Inspect drilling line for broken wires and wear; check sheaves.', 'Rig Operator', 'Mast lowered or locked out', 0.0, 'None', 'Gauges'),
            ('Prevention B', 'Carrier engine & transmission service', 90, 500, 3.0, 'Change oil, filters and fluids on the carrier; inspect suspension and air system.', 'Mechanic', 'Hot fluids', 450.0, 'Oil, filters', 'Drain pans'),
            ('Prevention B', 'Hydraulic system & power tong service', 90, 500, 2.5, 'Change hydraulic filters, check hoses and fittings, inspect tong dies.', 'Mechanic', 'Pressure bled off', 250.0, 'Filters, hydraulic oil', 'Hand tools'),
            ('Prevention C', 'Mast, anchors & drawworks inspection', 365, 3000, 12.0, 'Inspect mast structure, anchors, drawworks and brake system.', 'Master Mechanic', 'Fall protection', 900.0, 'As required', 'Heavy tools'),
            ('Compliance', 'Annual rig certification & BOP test', 365, 0, 6.0, 'Third-party rig inspection and BOP pressure test; keep certificates on file.', 'Certified Inspector', 'High pressure', 800.0, 'Test fluid', 'Test pump'),
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
    'Renewables': dict(
        prefix='RENEW',
        model='Renewable Generating Site {i} (Wind / Solar)',
        labels=('Rated Power (MW)', 'Technology (Wind/Solar)', 'Inverter / Generator Type', 'Tracker / Pitch System', 'Grid Voltage (kV)'),
        parts=('Turbine / Array:', 'Gearbox, Generator & Inverters:', 'Tracker / Pitch & Yaw Systems:', 'Transformer & Switchgear:', 'SCADA & Communications:', 'Tower, Foundation & Fencing:'),
        attrs=[('Rated power', '2.5 MW', 'Per site'), ('Technology', 'Wind and solar', 'Hybrid example'), ('Grid connection', '34.5 kV', 'Via pad-mount transformer')],
        checklist=[('Inspect inverter cooling fans & filters', 'Verify SCADA output vs. weather'), ('Check yaw drive gearbox oil level', 'Inspect rotor brake pad wear'), ('Check string combiner box fuses', 'Inspect panel & rack connections (visual)'), ('Test emergency stop & rotor lock', 'Check tower base for oil leaks & loose bolts'), ('Verify transformer oil temperature & level', 'Inspect fencing, signage & cameras')],
        tasks=[
            ('Prevention A', 'SCADA review & alarm check', 7, 168, 0.5, 'Review production against weather data, clear alarms and note under-performing strings or turbines.', 'Technician', 'None', 0.0, 'None', 'Laptop'),
            ('Prevention A', 'Site walk-round: fencing, access & visible damage', 30, 0, 1.0, 'Walk the site; check fencing, signage, vegetation, visible damage and animal activity.', 'Technician', 'Site hazard awareness', 0.0, 'None', 'Checklist'),
            ('Prevention B', 'Inverter & combiner box service', 180, 4000, 3.0, 'Clean filters and fans, torque terminations, thermal scan combiners and inverters.', 'Electrician', 'Arc flash PPE; LOTO', 100.0, 'Filters', 'IR camera, torque tools'),
            ('Prevention B', 'Gearbox oil, yaw & pitch system check', 180, 4000, 5.0, 'Sample gearbox oil, check yaw and pitch drives, grease main bearing.', 'Wind Technician', 'Climb safety; lockout rotor', 350.0, 'Oil, grease', 'Grease gun'),
            ('Prevention C', 'Annual bolt torque & transformer service', 365, 8000, 16.0, 'Torque tower and blade bolts, service the pad-mount transformer, test protection.', 'Master Technician', 'Climb safety; LOTO', 1200.0, 'Oil, hardware', 'Torque tools'),
            ('Compliance', 'Electrical protection & grounding test', 365, 0, 6.0, 'Test relays, breakers and grounding; update the single-line records.', 'Certified Electrician', 'Arc flash PPE', 800.0, 'None', 'Relay test set'),
        ]),
    'HVAC & Boilers': dict(
        prefix='HVAC',
        model='Rooftop Unit RTU-{i} (25-ton)',
        labels=('Cooling Capacity (tons)', 'Heating Input (MBH)', 'Airflow (CFM)', 'Refrigerant Type', 'Control System'),
        parts=('Compressors / Burners:', 'Supply & Return Fans:', 'Coils & Heat Exchangers:', 'Controls & Thermostats:', 'Electrical & Starters:', 'Ductwork & Piping:'),
        attrs=[('Cooling capacity', '25 tons', 'Two scroll compressors'), ('Heating', '400 MBH gas', 'Two-stage burner'), ('Controls', 'BAS connected', 'Economizer fitted')],
        checklist=[('Check thermostat & building temperatures', 'Listen for unusual noise or vibration'), ('Check air filters for dirt (visual)', 'Inspect condensate drain for blockage'), ('Check boiler pressure & temperature gauges', 'Look for water or refrigerant leaks'), ('Verify outside air dampers move freely', 'Check belts & pulleys (visual)'), ('Confirm no fault codes on controller', 'Check unit access panels are secured')],
        tasks=[
            ('Prevention A', 'Replace or clean air filters', 30, 720, 0.5, 'Replace pleated filters per the unit schedule and record the pressure drop.', 'Technician', 'LOTO', 40.0, 'Filters', 'Hand tools'),
            ('Prevention A', 'Check condensate drains & pans', 30, 0, 0.5, 'Clear drain lines, check pans and float switches.', 'Technician', 'LOTO', 5.0, 'Treatment tablets', 'Wet vac'),
            ('Prevention B', 'Belt, bearing & blower inspection', 90, 2000, 1.5, 'Check belt tension and wear, bearings, pulley alignment and blower wheel.', 'Technician', 'LOTO', 60.0, 'Belts, grease', 'Tension gauge'),
            ('Prevention B', 'Clean condenser & evaporator coils', 180, 4000, 3.0, 'Wash coils, straighten fins, check airflow and refrigerant pressures.', 'Technician', 'LOTO; chemical PPE', 40.0, 'Coil cleaner', 'Coil comb, sprayer'),
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
    'Forklifts': dict(
        prefix='FORK',
        model='Forklift FL-{i} (2.5-tonne)',
        labels=('Capacity (kg)', 'Lift Height (m)', 'Power Type', 'Mast Type', 'Serial / Fleet No.'),
        parts=('Engine / Battery & Motor:', 'Mast & Lift Chains:', 'Hydraulics:', 'Brakes & Steering:', 'Tires & Axles:', 'Safety Devices & Lights:'),
        attrs=[('Capacity', '2,500 kg', 'Rated load plate on mast'), ('Power', 'LPG / electric', 'Per unit'), ('Mast', '3-stage, 4.5 m', 'Chains lubricated every PM')],
        checklist=[('Check forks, carriage & load backrest', 'Inspect mast & lift chains'), ('Test brakes & parking brake', 'Check steering & hydraulic leaks'), ('Check tires & wheels', 'Test horn, lights & backup alarm'), ('Check seat belt & operator restraint', 'Check fluid levels or battery charge'), ('Check overhead guard & safety decals', 'Check fire extinguisher / LPG tank mounting')],
        tasks=[
            ('Prevention A', 'Operator pre-use inspection record', 1, 8, 0.2, 'Complete the daily forklift inspection sheet and tag out any unit with a defect.', 'Operator', 'Truck off and chocked', 0.0, 'None', 'Checklist'),
            ('Prevention A', 'Lift chain lubrication & fork inspection', 30, 200, 0.5, 'Lubricate chains and check forks for cracks, wear and heel dimensions.', 'Mechanic', 'Mast lowered', 10.0, 'Chain lube', 'Fork gauge'),
            ('Prevention B', '250-hour service: oil, filters, grease', 90, 250, 2.0, 'Change engine oil and filters; grease mast, steering and axle points; check coolant.', 'Mechanic', 'Truck blocked', 90.0, 'Oil, filters, grease', 'Hand tools'),
            ('Prevention B', 'Brake, hydraulic & tire inspection', 180, 500, 2.0, 'Inspect brakes and hoses, check hydraulic fluid, measure tire wear.', 'Mechanic', 'Truck blocked', 80.0, 'Hydraulic fluid', 'Gauges'),
            ('Prevention C', 'Annual mast & chain overhaul', 365, 2000, 6.0, 'Measure chain stretch, inspect rollers, rails and cylinders; replace worn parts.', 'Mechanic', 'Mast blocked', 500.0, 'Chains, bushings', 'Chain gauge'),
            ('Compliance', 'Annual forklift safety inspection', 365, 0, 1.5, 'Certified annual inspection including load test; keep the record with the truck.', 'Certified Inspector', 'Load test area clear', 150.0, 'None', 'Test weights'),
        ]),
    'Construction': dict(
        prefix='CONST',
        model='Excavator / Loader CE-{i}',
        labels=('Operating Weight (kg)', 'Engine Power (HP)', 'Bucket Capacity (m3)', 'Track / Wheel Type', 'Fleet No.'),
        parts=('Engine & Cooling:', 'Hydraulic Pumps & Valves:', 'Undercarriage / Axles:', 'Boom, Stick & Attachments:', 'Cab & Controls:', 'Safety & Lighting:'),
        attrs=[('Operating weight', '20 tonnes', 'Tracked excavator example'), ('Engine', '150 HP diesel', 'Tier-rated'), ('Attachments', 'Bucket, thumb, hammer', 'Pins greased daily')],
        checklist=[('Check engine oil, coolant & hydraulic oil', 'Inspect tracks / tires & undercarriage'), ('Grease boom, stick & bucket pins', 'Check hoses & cylinders for leaks'), ('Inspect bucket teeth & cutting edge', 'Test lights, alarm & camera'), ('Check air filter restriction indicator', 'Clean cab glass, mirrors & steps'), ('Verify fire extinguisher & first aid kit', 'Check fuel level & drain water separator')],
        tasks=[
            ('Prevention A', 'Daily walk-around & greasing', 1, 10, 0.5, 'Grease pins and bushings, check fluids, hoses and ground-engaging tools.', 'Operator', 'Machine parked, bucket down', 8.0, 'Grease', 'Grease gun'),
            ('Prevention A', 'Air filter & radiator cleaning', 14, 100, 0.5, 'Clean or replace the air filter element, blow out radiator and coolers.', 'Operator', 'Engine off', 20.0, 'Filter as needed', 'Compressed air'),
            ('Prevention B', '250-hour service: oil & filters', 90, 250, 2.0, 'Change engine oil and filters, fuel filters, check coolant and belts, take oil sample.', 'Mechanic', 'Machine locked out', 220.0, 'Oil, filters', 'Hand tools'),
            ('Prevention B', 'Undercarriage & final drive check', 90, 500, 2.0, 'Measure track wear, check rollers, idlers, sprockets and final drive oil.', 'Mechanic', 'Machine blocked', 100.0, 'Gear oil', 'Measuring gauge'),
            ('Prevention C', '1000-hour hydraulic & final drive service', 365, 1000, 5.0, 'Change hydraulic oil and filters, swing and final drive oils, test pump pressures.', 'Mechanic', 'Pressure released', 800.0, 'Oil, filters', 'Pressure gauges'),
            ('Compliance', 'Annual safety & ROPS/FOPS inspection', 365, 0, 2.0, 'Annual documented inspection of structure, guarding, brakes and safety devices.', 'Certified Inspector', 'None', 150.0, 'None', 'Checklist'),
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
    'Generators': dict(
        prefix='GEN',
        model='Standby Generator SG-{i} (150 kW)',
        labels=('Rated Output (kW)', 'Engine (HP)', 'Fuel Type', 'Transfer Switch', 'Fuel Tank (L)'),
        parts=('Engine & Cooling:', 'Alternator:', 'Fuel System:', 'Starting & Batteries:', 'Transfer Switch & Controls:', 'Exhaust & Enclosure:'),
        attrs=[('Output', '150 kW standby', '480 V three-phase'), ('Fuel', 'Diesel, 400 L tank', 'Fuel quality tested yearly'), ('Transfer switch', 'Automatic', 'Tested under load')],
        checklist=[('Check coolant & oil levels', 'Check battery charger status & voltage'), ('Verify controller shows AUTO, no alarms', 'Inspect for fluid or fuel leaks'), ('Check fuel level & tank vents', 'Check block heater operation'), ('Inspect belts & hoses', 'Check air intake & louvers are clear'), ('Verify transfer switch position & indicators', 'Check enclosure, exhaust & signage')],
        tasks=[
            ('Prevention A', 'Weekly no-load exercise run', 7, 0, 0.5, 'Run the generator under no load for 10 to 20 minutes; record voltage, frequency and oil pressure.', 'Operator', 'Exhaust ventilation', 5.0, 'Fuel', 'Log sheet'),
            ('Prevention A', 'Fluid, battery & block heater check', 30, 0, 0.5, 'Check coolant, oil, battery charger and block heater operation.', 'Technician', 'None', 10.0, 'Coolant as needed', 'Hand tools'),
            ('Prevention B', 'Monthly loaded run test', 30, 5, 1.0, 'Run under at least 30% load for 30 minutes; record readings.', 'Technician', 'Exhaust ventilation', 20.0, 'Fuel', 'Load bank if needed'),
            ('Prevention B', 'Oil, fuel & air filter change', 180, 100, 2.5, 'Change engine oil and filters, fuel filters and air filter; check belts and hoses.', 'Mechanic', 'Hot fluids', 200.0, 'Oil, filters', 'Hand tools'),
            ('Prevention C', 'Annual load bank test & transfer switch test', 365, 0, 4.0, 'Run at full load for the required time; test automatic transfer.', 'Certified Technician', 'Electrical hazard; LOTO', 400.0, 'Fuel', 'Load bank'),
            ('Compliance', 'Annual fuel quality test & battery replacement review', 365, 0, 1.5, 'Test stored fuel for water and microbial growth; replace batteries at the recommended age.', 'Technician', 'None', 150.0, 'Fuel polishing / batteries', 'Test kit'),
        ]),
    'Cranes & Hoists': dict(
        prefix='CRANE',
        model='Overhead Bridge Crane OC-{i} (10-tonne)',
        labels=('Rated Capacity (tonnes)', 'Span (m)', 'Hoist Type', 'Control Type', 'Serial No.'),
        parts=('Hoist & Wire Rope / Chain:', 'Trolley & Bridge Drives:', 'Hook, Block & Latch:', 'Runway & Rails:', 'Pendant / Radio Controls:', 'Limit Switches & Brakes:'),
        attrs=[('Capacity', '10 tonnes', 'Rated load plate on bridge'), ('Span', '18 m', 'Runway beams inspected yearly'), ('Hoist', 'Electric wire rope', 'Pendant control')],
        checklist=[('Test pendant / remote buttons & e-stop', 'Check hook latch & hook condition'), ('Inspect wire rope or chain visually', 'Test hoist upper limit switch'), ('Test brakes by lifting a light load', 'Check runway for obstructions'), ('Listen for noise in hoist, trolley & bridge', 'Check load rating label is legible'), ('Check warning horn / lights', 'Check power festoon / conductor bar condition')],
        tasks=[
            ('Prevention A', 'Operator pre-shift inspection', 1, 8, 0.2, 'Frequent inspection: controls, limit switches, hook latch, rope and brakes before use.', 'Operator', 'Crane tagged out if a defect is found', 0.0, 'None', 'Checklist'),
            ('Prevention A', 'Wire rope & chain lubrication', 30, 100, 0.5, 'Lubricate wire rope or load chain and inspect for broken wires or stretch.', 'Mechanic', 'Crane locked out', 15.0, 'Rope lube', 'Brush'),
            ('Prevention B', 'Brake & limit switch inspection', 90, 400, 2.0, 'Inspect and adjust hoist brake, test upper and lower limits and overload device.', 'Electrician / Mechanic', 'LOTO; fall protection', 80.0, 'Brake parts', 'Hand tools'),
            ('Prevention B', 'Gearbox oil & wheel inspection', 180, 800, 2.5, 'Check gearbox oil, wheels, rails and end trucks.', 'Mechanic', 'LOTO; fall protection', 100.0, 'Gear oil', 'Hand tools'),
            ('Prevention C', 'Periodic inspection with load test', 365, 0, 6.0, 'Documented periodic inspection of the whole crane including a rated load test.', 'Qualified Inspector', 'Test area clear; fall protection', 500.0, 'None', 'Test weights'),
            ('Compliance', 'Annual certification of crane & runway', 365, 0, 3.0, 'Third-party inspection and certification; post or file the certificate.', 'Certified Inspector', 'Fall protection', 400.0, 'Tags', 'Inspection kit'),
        ]),
    'Refrigeration': dict(
        prefix='REFRIG',
        model='Walk-in Cooler / Freezer WR-{i}',
        labels=('Box Size (m3)', 'Compressor (HP)', 'Refrigerant Type', 'Defrost Type', 'Design Temperature (C)'),
        parts=('Compressor & Condenser:', 'Evaporator & Fans:', 'Refrigerant Lines & Valves:', 'Controls & Sensors:', 'Door, Gaskets & Box:', 'Alarm & Monitoring:'),
        attrs=[('Box', '40 m3 walk-in', 'Freezer or cooler'), ('Compressor', '5 HP semi-hermetic', 'Refrigerant leak checks per code'), ('Monitoring', 'Temperature alarm', 'Call-out configured')],
        checklist=[('Record box temperature & check alarm', 'Check door gaskets & closing'), ('Check for ice build-up on evaporator', 'Listen for unusual compressor noise'), ('Check condenser for dirt (visual)', 'Check drain line & heater tape'), ('Verify door strip curtains & lights', 'Check for oil stains at fittings'), ('Check product stacking clear of airflow', 'Test temperature alarm button')],
        tasks=[
            ('Prevention A', 'Temperature log & alarm test', 7, 0, 0.3, 'Record temperatures, test the high-temperature alarm and check door seals.', 'Operator', 'None', 0.0, 'None', 'Thermometer'),
            ('Prevention A', 'Check defrost cycle & drain lines', 30, 0, 0.5, 'Confirm defrost terminates, drain line is clear and heater tape works.', 'Technician', 'Slip hazard', 5.0, 'None', 'Hand tools'),
            ('Prevention B', 'Clean condenser coil & check fan motors', 90, 0, 1.5, 'Brush and wash the condenser, check fan motors, blades and amp draw.', 'Refrigeration Technician', 'LOTO', 30.0, 'Coil cleaner', 'Brush, gauges'),
            ('Prevention B', 'Refrigerant leak check & pressure review', 90, 0, 1.5, 'Electronic leak check on joints and valves; record suction and head pressures.', 'Refrigeration Technician', 'Refrigerant handling certification', 40.0, 'None', 'Leak detector'),
            ('Prevention C', 'Annual compressor oil, contactor & controls service', 365, 0, 4.0, 'Check oil level and colour, test contactors, sensors and defrost controls.', 'Refrigeration Technician', 'LOTO', 250.0, 'Oil, contactors', 'Gauges'),
            ('Compliance', 'Annual refrigerant leak inspection record', 365, 0, 2.0, 'Complete the documented leak inspection and keep the refrigerant log current.', 'Certified Technician', 'Refrigerant handling certification', 150.0, 'None', 'Leak detector'),
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
}

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

for _gname, _g in SAMPLE_GROUPS.items(): _register_group(_gname, _g)

# Optional private groups: a file called private_groups.py next to app.py adds extra sample groups (the vendor's own copy only).
try:
    import private_groups as _private_groups
    for _gname, _g in _private_groups.PRIVATE_GROUPS.items():
        if _gname not in SAMPLE_GROUPS: _register_group(_gname, _g)
except ImportError:
    pass

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
APP_VERSION = "1.0.5"

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

def dashboard_alert_counts():
    """(tasks overdue or due today, parts needing reorder, warranties needing action) for the Switchboard banner. Never raises."""
    try:
        d = fetch_due_tasks(None, 7)
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
    "Service Rigs": [("SRV-SL-PACK", "Stripper rubber, 2-7/8 in.", "Rack S1", "Rigsite Supply", 5, 2, 4, 120.00),
                     ("SRV-HYD-FLT", "Hydraulic return filter", "Rack S2", "Rigsite Supply", 4, 2, 4, 55.00),
                     ("SRV-BRK-BAND", "Drawworks brake band lining", "Rack S3", "Rigsite Supply", 1, 1, 2, 390.00)],
    "Thermal Plant": [("THP-GSKT-SW", "Spiral wound gasket, 6 in.", "Rack P1", "Plant Industrial", 10, 4, 10, 17.00),
                      ("THP-VALVE-PK", "Valve packing set, graphite", "Rack P1", "Plant Industrial", 6, 3, 6, 21.50),
                      ("THP-SENS-RTD", "RTD temperature sensor", "Cabinet P3", "Plant Industrial", 2, 2, 4, 95.00)],
    "Renewables": [("REN-GBX-OIL", "Gearbox oil, synthetic ISO VG 320, 20 L", "Shelf W1", "Prairie Wind Services", 3, 2, 4, 210.00),
                   ("REN-BRK-PAD", "Yaw brake pad set", "Shelf W2", "Prairie Wind Services", 2, 2, 4, 340.00),
                   ("REN-SLIP-RING", "Slip ring brush set", "Shelf W2", "Prairie Wind Services", 5, 2, 4, 78.00)],
    "HVAC & Boilers": [("HVC-FLT-20X25", "Pleated air filter 20x25x4", "Rack H1", "Climate Supply", 24, 12, 24, 14.00),
                       ("HVC-BELT-B68", "V-belt B68", "Rack H1", "Climate Supply", 4, 2, 4, 16.50),
                       ("HVC-IGN-ELEC", "Boiler ignition electrode", "Cabinet H2", "Climate Supply", 1, 2, 4, 42.00)],
    "Pumps/Compressors": [("PMP-SEAL-MECH", "Mechanical seal, 1.5 in.", "Rack M1", "Flowline Industrial", 3, 2, 4, 130.00),
                          ("PMP-BRG-6309", "Bearing 6309-2RS", "Rack M1", "Flowline Industrial", 6, 4, 8, 19.00),
                          ("CMP-OF-AIR", "Compressor air/oil separator element", "Rack M2", "Flowline Industrial", 2, 2, 3, 175.00)],
    "Forklifts": [("FRK-MAST-CHAIN", "Mast lift chain, per metre", "Rack F1", "Lift Truck Parts", 10, 4, 10, 34.00),
                  ("FRK-PNEU-TIRE", "Solid cushion tire, 21x7x15", "Yard F2", "Lift Truck Parts", 2, 2, 4, 150.00),
                  ("FRK-FORK-PIN", "Fork positioner pin set", "Bin F3", "Lift Truck Parts", 5, 2, 4, 28.00)],
    "Construction": [("CON-BKT-CUT", "Bucket cutting edge", "Rack K1", "Prairie Equipment Parts", 3, 2, 4, 240.00),
                     ("CON-HYD-OIL", "Hydraulic oil AW46, 20 L pail", "Shelf K2", "Prairie Equipment Parts", 6, 3, 6, 88.00),
                     ("CON-AIR-FLT", "Engine air filter, primary", "Shelf K2", "Prairie Equipment Parts", 4, 2, 4, 52.00)],
    "Agriculture": [("AGR-KNIFE-SEC", "Sickle section, combine header", "Shed G1", "Farm Parts Direct", 40, 20, 40, 3.20),
                    ("AGR-CHAIN-RC", "Roller chain #60, 10 ft", "Shed G1", "Farm Parts Direct", 5, 3, 6, 38.00),
                    ("AGR-TINE-BALE", "Baler pickup tine", "Shed G2", "Farm Parts Direct", 30, 20, 40, 2.10)],
    "Generators": [("GEN-FILT-KIT", "Generator service filter kit", "Shelf E1", "Standby Power Supply", 3, 2, 4, 78.00),
                   ("GEN-COOLANT", "Extended-life coolant, 20 L", "Shelf E1", "Standby Power Supply", 2, 2, 4, 65.00),
                   ("GEN-BATT-12V", "Starting battery 12 V, 800 CCA", "Rack E2", "Standby Power Supply", 2, 1, 2, 185.00)],
    "Cranes & Hoists": [("CRN-WIRE-ROPE", "Hoist wire rope, per metre", "Rack N1", "Lift & Rigging Co.", 60, 30, 60, 11.50),
                        ("CRN-HOOK-LATCH", "Hook safety latch", "Bin N2", "Lift & Rigging Co.", 6, 3, 6, 14.00),
                        ("CRN-LIM-SW", "Limit switch assembly", "Cabinet N3", "Lift & Rigging Co.", 1, 1, 2, 220.00)],
    "Refrigeration": [("REF-FD-CORE", "Filter drier core", "Cabinet Q1", "Cold Chain Supply", 4, 2, 4, 36.00),
                      ("REF-FAN-MTR", "Evaporator fan motor", "Rack Q2", "Cold Chain Supply", 2, 1, 2, 120.00),
                      ("REF-DEFR-HTR", "Defrost heater element", "Rack Q2", "Cold Chain Supply", 0, 1, 2, 64.00)],
    "Machine Tools": [("MCH-COOL-5G", "Cutting coolant concentrate, 20 L", "Shelf L1", "Machinists Supply", 3, 2, 4, 145.00),
                      ("MCH-WAY-OIL", "Way lube oil, 20 L", "Shelf L1", "Machinists Supply", 2, 2, 3, 110.00),
                      ("MCH-INS-CNMG", "Carbide insert CNMG 432 (box of 10)", "Cabinet L2", "Machinists Supply", 8, 4, 8, 72.00)],
    "Fire & Life Safety": [("FLS-EXT-ABC10", "ABC extinguisher 10 lb, recharged", "Rack Z1", "Safety First Supply", 4, 2, 4, 78.00),
                           ("FLS-SMK-DET", "Smoke detector head", "Rack Z2", "Safety First Supply", 10, 4, 10, 23.00),
                           ("FLS-EMG-LAMP", "Emergency light battery pack", "Rack Z2", "Safety First Supply", 3, 2, 4, 34.00)],
}

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

# --- SIDEBAR ROUTING & LOGIC ---
if "view_mode_override" not in st.session_state: 
    st.session_state.view_mode_override = "Switchboard"

visible_options = ["Switchboard", "Overdue Dashboard", "Checklists", "Sched. Maint.", "WorkOrders (W/O)", "Completed (W/O)", "Warranty Tracking", "Reports/Queries", "Asset Groups", "Parts Inventory", "Suppliers", "Service Co.", "Incident Reports", "Glossary", "Import Data"]
if st.session_state.get("auth_role") == "admin":
    visible_options.extend(["Users & Security", "Settings"])
current_idx = visible_options.index(st.session_state.view_mode_override) if st.session_state.view_mode_override in visible_options else 0
if st.session_state.view_mode_override in visible_options and st.session_state.get("main_nav_radio") != st.session_state.view_mode_override:
    st.session_state.main_nav_radio = st.session_state.view_mode_override   # keep the side menu in step with the green buttons

# 1. Control Function (Moved to Top)
def nav_callback():
    st.session_state.view_mode_override = st.session_state.main_nav_radio

selected_view = st.sidebar.radio(
    "Control Function", 
    visible_options, 
    index=current_idx,
    key="main_nav_radio",
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
    db_cats = [row[0] for row in cursor.fetchall() if row[0]]

active_categories = db_cats if db_cats else FULL_CATEGORIES_LIST

if "active_asset_group" not in st.session_state or st.session_state.active_asset_group not in active_categories:
    st.session_state.active_asset_group = active_categories[0]

selected_category = st.sidebar.radio("Asset Group", active_categories, index=active_categories.index(st.session_state.active_asset_group) if st.session_state.active_asset_group in active_categories else 0, key="asset_group_radio")
st.session_state.active_asset_group = selected_category

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

# --- MAIN SCREEN RENDERING ---
if view_mode == "Switchboard":
  if os.path.exists("BlackMarble_2016_3km.jpg"): st.image("BlackMarble_2016_3km.jpg", use_container_width=True)
  st.markdown("<h2 style='text-align: center; margin-bottom: 25px;'>An Ounce of Prevention — Switchboard</h2>", unsafe_allow_html=True)
  _al_tasks, _al_parts, _al_warr = dashboard_alert_counts()
  if _al_tasks or _al_parts or _al_warr:
    _hl = ([f"<b>{_al_tasks}</b> task(s) overdue or due today."] if _al_tasks else []) + (["Parts need to be reordered."] if _al_parts else []) \
          + ([f"<b>{_al_warr}</b> warranty(ies) expiring."] if _al_warr else [])
    _open = "Open " + (" or ".join((["Parts"] if _al_parts else []) + ["Overdue Dashboard"])) + "."
    st.markdown("<div style='text-align:center; border:2px solid #c0392b; color:#c0392b; border-radius:6px; padding:8px 10px; margin-bottom:18px; font-weight:bold; font-size:13pt;'>⚠ "
                + " &nbsp;".join(_hl) + " &nbsp;" + _open + "</div>", unsafe_allow_html=True)
  col_sw1, col_sw2, col_sw3 = st.columns(3, gap="large")
  
  with col_sw1:
    st.markdown("<div style='text-align: center; font-size: 13.5pt; font-weight: bold; margin-bottom: 12px;'>Daily Operations</div>", unsafe_allow_html=True)
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
    if st.button("Glossary", use_container_width=True): st.session_state.view_mode_override = "Glossary"; st.rerun()
    if st.button("How Ounce Fits In", use_container_width=True): st.session_state.view_mode_override = "System Architecture"; st.rerun()
    
  with col_sw3:
    st.markdown("<div style='text-align: center; font-size: 13.5pt; font-weight: bold; margin-bottom: 12px;'>Reports & System</div>", unsafe_allow_html=True)
    if st.button("Reports/Queries", use_container_width=True): st.session_state.view_mode_override = "Reports/Queries"; st.rerun()
    if st.button("Fleet Health", use_container_width=True): st.session_state.view_mode_override = "Fleet Health"; st.rerun()
    if st.button("Monty Python", use_container_width=True): st.session_state.view_mode_override = "Monty Python"; st.rerun()
    if st.button("Warranty Tracking", use_container_width=True): st.session_state.view_mode_override = "Warranty Tracking"; st.rerun()
    if st.button("Back Up Database", use_container_width=True):
        try: st.success(f"Backup saved: {os.path.basename(backup_database())}")
        except Exception as e: st.error(f"Backup failed: {e}")
    if st.button("Exit Program", use_container_width=True):
        st.success("Session Terminated. It is now safe to close this browser tab.")
        st.stop()

  # First-run welcome: shown only while the database has no assets at all
  if is_empty_install():
    st.info("**Welcome to An Ounce of Prevention.** Your database is empty. Add your own equipment under "
            "**Asset Groups**, or load the sample data (19 asset groups, about 100 example units with "
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
elif view_mode == "Fleet Health":
  st.subheader("📊 Fleet Health & Maintenance Guide")
  
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
  title_row("🎬 Monty Python Viewing Area", "btn_sw_page7")
  st.markdown("#### What have the Romans ever done for us?")
  
  vid_col1, vid_col2, vid_col3 = st.columns(3)
  with vid_col1:
      st.video("https://www.youtube.com/watch?v=cOKR2m1URe8") # The Romans
  with vid_col2:
      st.video("https://www.youtube.com/watch?v=-8bqQ-C1PSE") # Anarcho-Syndicalist Commune
  with vid_col3:
      st.video("https://www.youtube.com/watch?v=uyVPAlQQp5k") # Argument Clinic

  vid_col4, vid_col5, _vid_col6 = st.columns(3)
  with vid_col4:
      st.video("https://www.youtube.com/watch?v=kRwCPUEND1U", start_time=40) # The Black Knight
  with vid_col5:
      st.video("https://www.youtube.com/watch?v=XgchpzSaYJA") # Life of Brian: Beatitudes, Stoning, Lepper

elif view_mode == "Glossary":
  title_row("📖 Universal Maintenance Glossary & Acronyms", "btn_sw_page8")
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
                st.markdown("<div style='display:flex; white-space:nowrap; font-weight:900; color:#000080; font-size:12pt; margin-bottom:4px;'>"
                            "<div style='width:335px; flex:none;'></div>"
                            "<div style='width:190px; flex:none; text-align:center; border-bottom:2px solid #000080;'>Last Done</div>"
                            "<div style='width:190px; flex:none; text-align:center; border-bottom:2px solid #000080; margin-left:2px;'>Trigger Interval</div>"
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
                        "Date_Last_Done": st.column_config.TextColumn("Date", width=90), 
                        "Meter_At_Last": st.column_config.TextColumn("Kms/Hrs", width=100), 
                        "Days_Between": st.column_config.TextColumn("Days", width=80), 
                        "Meter_Between": st.column_config.TextColumn("Kms/Hrs", width=110), 
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

    tab_sign, tab_hist = st.tabs(["Sign-Off Sheet", "History"])

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
    existing_groups = [r[0] for r in cursor.fetchall()]

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