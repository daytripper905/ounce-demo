"""Smoke test for the demo bundle. Run with the BUNDLE's own python:  python ci_smoke.py "<bundle folder>"
Starts the real app headlessly in a throw-away data folder and checks that it opens without errors,
shows the DEMO banner, has the sample data, and becomes read-only once the 30 days are up."""
import os, sys, sqlite3, tempfile
from datetime import date, timedelta

bundle = sys.argv[1]
app = os.path.join(bundle, "app.py")
data = tempfile.mkdtemp()
os.environ["OUNCE_DB_PATH"] = data
os.chdir(bundle)
from streamlit.testing.v1 import AppTest

def run():
    at = AppTest.from_file(app, default_timeout=180)
    at.run()
    return at

def problems(at):
    return [str(e.value)[:300] for e in at.exception]

at = run()
assert not problems(at), f"errors on first start: {problems(at)}"
texts = [i.value for i in at.info]
assert any("DEMO copy" in t for t in texts), f"no DEMO banner on first start. info boxes: {texts[:3]}"
db = [os.path.join(data, f) for f in os.listdir(data) if f.endswith(".db")][0]
c = sqlite3.connect(db)
n = c.execute('SELECT COUNT(*) FROM "Trucks"').fetchone()[0]
assert n > 50, f"sample data missing (only {n} assets)"
print("first start OK, sample assets:", n)

c.execute("UPDATE App_Settings SET Value=? WHERE Key='demo_start'", ((date.today() - timedelta(days=31)).isoformat(),))
c.commit()
at = run()
assert not problems(at), f"errors after expiry: {problems(at)}"
warns = [w.value for w in at.warning]
assert any("demo has ended" in w for w in warns), f"no expiry notice. warnings: {warns[:3]}"
assert c.execute('SELECT COUNT(*) FROM "Trucks"').fetchone()[0] == n, "data changed after expiry"
print("expiry OK: read-only notice shown, data intact")
print("SMOKE TEST PASSED")
