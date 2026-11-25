"""Emergency Healthcare Responder System - Flask + SQLite prototype.

Run:  python app.py        (then open http://127.0.0.1:5000)
Demo data is created automatically the first time (see README.md for logins).
"""
import functools
import math
import os
import re
import secrets
import sqlite3
from datetime import datetime

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get("EHRS_DB", os.path.join(BASE_DIR, "ehrs.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
EMERGENCY_TYPES = [
    "Road accident", "Heart attack / chest pain", "Breathing difficulty",
    "Severe bleeding", "Burns", "Stroke symptoms", "Pregnancy emergency",
    "Other medical emergency",
]
URGENCY = ["Critical", "High", "Normal"]
DEFAULT_CENTER = (28.4089, 77.3178)  # Faridabad
ALERT_HOSPITALS = 3        # alert goes to this many nearest hospitals
ALERT_RADIUS_KM = 25       # ...preferring those inside this radius
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s]{7,15}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  phone TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','hospital')),
  blood_group TEXT,
  city TEXT,
  lat REAL, lng REAL,
  donor_available INTEGER NOT NULL DEFAULT 1,
  emergency_contact_name TEXT,
  emergency_contact_phone TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hospitals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  name TEXT NOT NULL,
  address TEXT NOT NULL,
  phone TEXT NOT NULL,
  lat REAL NOT NULL, lng REAL NOT NULL,
  ambulances INTEGER NOT NULL DEFAULT 0,
  beds_available INTEGER NOT NULL DEFAULT 0,
  specialities TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  lat REAL NOT NULL, lng REAL NOT NULL,
  emergency_type TEXT NOT NULL,
  details TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_hospitals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_id INTEGER NOT NULL REFERENCES alerts(id),
  hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
  distance_km REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  updated_at TEXT NOT NULL,
  UNIQUE(alert_id, hospital_id)
);
CREATE TABLE IF NOT EXISTS blood_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
  blood_group TEXT NOT NULL,
  units INTEGER NOT NULL DEFAULT 1,
  urgency TEXT NOT NULL DEFAULT 'High',
  details TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS donor_responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id INTEGER NOT NULL REFERENCES blood_requests(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  availability TEXT NOT NULL,
  message TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(request_id, user_id)
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  message TEXT NOT NULL,
  link TEXT,
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""

# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db(seed=True):
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    db.close()
    if seed and count == 0:
        seed_demo_data()


def seed_demo_data():
    """Fictional demo hospitals/users around Faridabad (coordinates approximate)."""
    db = sqlite3.connect(DATABASE)
    pw = generate_password_hash("demo123")
    hospitals = [
        ("City Care Hospital", "Sector 15, Faridabad", "0129-4000101", 28.3990, 77.3050, 4, 12, "Trauma, Cardiology"),
        ("Lifeline Multispeciality Hospital", "NIT, Faridabad", "0129-4000102", 28.4210, 77.3120, 3, 8, "Emergency, Neurology"),
        ("Sunrise Medical Centre", "Sector 21C, Faridabad", "0129-4000103", 28.4330, 77.3300, 2, 5, "Maternity, Paediatrics"),
        ("Green Valley Hospital", "Ballabgarh, Faridabad", "0129-4000104", 28.3400, 77.3200, 2, 10, "Orthopaedics, Burns"),
        ("Metro Trauma & Heart Institute", "Old Faridabad", "0129-4000105", 28.4050, 77.3000, 5, 6, "Trauma, Cardiology"),
    ]
    for i, h in enumerate(hospitals, 1):
        cur = db.execute(
            "INSERT INTO users(name,email,phone,password_hash,role,city,lat,lng,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (h[0], f"hospital{i}@demo.com", h[2], pw, "hospital", "Faridabad", h[3], h[4], now()))
        db.execute(
            "INSERT INTO hospitals(user_id,name,address,phone,lat,lng,ambulances,beds_available,specialities) VALUES(?,?,?,?,?,?,?,?,?)",
            (cur.lastrowid, h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]))
    users = [
        ("Aarav Sharma", "user1@demo.com", "9000000001", "B+", 28.4100, 77.3150),
        ("Priya Verma", "user2@demo.com", "9000000002", "O+", 28.4000, 77.3100),
        ("Rohan Gupta", "user3@demo.com", "9000000003", "B+", 28.4250, 77.3200),
        ("Neha Singh", "user4@demo.com", "9000000004", "A+", 28.3900, 77.3250),
    ]
    for n, e, p, bg, la, ln in users:
        db.execute(
            "INSERT INTO users(name,email,phone,password_hash,role,blood_group,city,lat,lng,emergency_contact_name,emergency_contact_phone,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (n, e, p, pw, "user", bg, "Faridabad", la, ln, "Family member", "9111111111", now()))
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def haversine(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def valid_coords(lat, lng):
    return (isinstance(lat, (int, float)) and isinstance(lng, (int, float))
            and -90 <= lat <= 90 and -180 <= lng <= 180)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v, default=0, lo=0, hi=10000):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def notify(user_id, message, link=None):
    run("INSERT INTO notifications(user_id,message,link,created_at) VALUES(?,?,?,?)",
        (user_id, message, link, now()))


def nearest_hospitals(lat, lng, limit=None):
    rows = [dict(h) for h in q("SELECT * FROM hospitals")]
    for h in rows:
        h["distance_km"] = round(haversine(lat, lng, h["lat"], h["lng"]), 2)
    rows.sort(key=lambda h: h["distance_km"])
    return rows[:limit] if limit else rows


def current_user():
    if "uid" not in session:
        return None
    if not hasattr(g, "_user"):
        g._user = q("SELECT * FROM users WHERE id=?", (session["uid"],), one=True)
    return g._user


def current_hospital():
    u = current_user()
    if u and u["role"] == "hospital":
        return q("SELECT * FROM hospitals WHERE user_id=?", (u["id"],), one=True)
    return None


def login_required(role=None):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify(error="Please log in first."), 401
                flash("Please log in to continue.", "warn")
                return redirect(url_for("login", next=request.path))
            if role and u["role"] != role:
                if request.path.startswith("/api/") or request.is_json:
                    return jsonify(error="Not allowed."), 403
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


@app.before_request
def csrf_protect():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(token, session["csrf"]):
            if request.is_json:
                return jsonify(error="Session expired. Refresh the page."), 400
            abort(400, "Invalid or missing CSRF token. Refresh the page and try again.")


@app.context_processor
def inject():
    u = current_user()
    unread = 0
    if u:
        unread = q("SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0", (u["id"],), one=True)["c"]
    return dict(me=u, csrf_token=session.get("csrf", ""), unread=unread,
                BLOOD_GROUPS=BLOOD_GROUPS, EMERGENCY_TYPES=EMERGENCY_TYPES, URGENCY=URGENCY,
                DEFAULT_CENTER=DEFAULT_CENTER)


@app.template_filter("ago")
def ago(ts):
    try:
        d = datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ts
    s = int(d.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You don't have access to this page."), 403


@app.errorhandler(404)
def notfound(_e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(400)
def badreq(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request.")), 400


# --------------------------------------------------------------------------
# Public + auth
# --------------------------------------------------------------------------

@app.route("/")
def index():
    stats = dict(
        hospitals=q("SELECT COUNT(*) c FROM hospitals", one=True)["c"],
        donors=q("SELECT COUNT(*) c FROM users WHERE role='user' AND blood_group IS NOT NULL AND donor_available=1", one=True)["c"],
        alerts=q("SELECT COUNT(*) c FROM alerts", one=True)["c"],
    )
    return render_template("index.html", stats=stats)


@app.route("/register", methods=["GET", "POST"])
def register():
    role = request.values.get("role", "user")
    if role not in ("user", "hospital"):
        role = "user"
    if request.method == "POST":
        f = request.form
        name, email, phone = f.get("name", "").strip(), f.get("email", "").strip().lower(), f.get("phone", "").strip()
        password = f.get("password", "")
        errs = []
        if len(name) < 2:
            errs.append("Please enter a name.")
        if not EMAIL_RE.match(email):
            errs.append("Enter a valid email.")
        if not PHONE_RE.match(phone):
            errs.append("Enter a valid phone number.")
        if len(password) < 6:
            errs.append("Password must be at least 6 characters.")
        if q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            errs.append("This email is already registered.")
        lat, lng = to_float(f.get("lat")), to_float(f.get("lng"))
        if role == "user":
            bg = f.get("blood_group", "")
            if bg not in BLOOD_GROUPS:
                errs.append("Select your blood group.")
        else:
            address = f.get("address", "").strip()
            if len(address) < 5:
                errs.append("Enter the hospital address.")
            if lat is None or lng is None or not valid_coords(lat, lng):
                errs.append("Set the hospital location (use the button or click the map).")
        if errs:
            for e in errs:
                flash(e, "error")
            return render_template("register.html", role=role, form=f), 400
        uid = run(
            "INSERT INTO users(name,email,phone,password_hash,role,blood_group,city,lat,lng,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (name, email, phone, generate_password_hash(password), role,
             f.get("blood_group") if role == "user" else None, f.get("city", "").strip() or None,
             lat, lng, now()))
        if role == "hospital":
            run("INSERT INTO hospitals(user_id,name,address,phone,lat,lng,ambulances,beds_available,specialities) VALUES(?,?,?,?,?,?,?,?,?)",
                (uid, name, f.get("address", "").strip(), phone, lat, lng,
                 to_int(f.get("ambulances")), to_int(f.get("beds_available")), f.get("specialities", "").strip()))
        session.clear()
        session["uid"] = uid
        flash("Account created. Welcome!", "ok")
        return redirect(url_for("dashboard"))
    return render_template("register.html", role=role, form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = q("SELECT * FROM users WHERE email=?", (email,), one=True)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            nxt = request.args.get("next", "")
            session.clear()
            session["uid"] = u["id"]
            flash(f"Welcome back, {u['name']}.", "ok")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("dashboard"))
        flash("Wrong email or password.", "error")
        return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required()
def dashboard():
    return redirect(url_for("hospital_home" if current_user()["role"] == "hospital" else "user_home"))


# --------------------------------------------------------------------------
# User panel
# --------------------------------------------------------------------------

@app.route("/user")
@login_required("user")
def user_home():
    u = current_user()
    alerts = q("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC LIMIT 5", (u["id"],))
    reqs = matching_requests(u)
    return render_template("user_home.html", alerts=alerts, reqs=reqs[:4])


def matching_requests(u):
    rows = q("""SELECT r.*, h.name hname, h.address, h.phone hphone, h.lat hlat, h.lng hlng,
                (SELECT availability FROM donor_responses d WHERE d.request_id=r.id AND d.user_id=?) my_response
                FROM blood_requests r JOIN hospitals h ON h.id=r.hospital_id
                WHERE r.status='open' AND r.blood_group=? ORDER BY r.id DESC""",
             (u["id"], u["blood_group"]))
    out = []
    for r in rows:
        r = dict(r)
        if u["lat"] is not None and u["lng"] is not None:
            r["distance_km"] = round(haversine(u["lat"], u["lng"], r["hlat"], r["hlng"]), 1)
        out.append(r)
    return out


@app.route("/blood")
@login_required("user")
def blood_requests():
    u = current_user()
    return render_template("blood.html", reqs=matching_requests(u))


@app.route("/blood/<int:rid>/respond", methods=["POST"])
@login_required("user")
def blood_respond(rid):
    u = current_user()
    req = q("SELECT r.*, h.user_id huid, h.name hname FROM blood_requests r JOIN hospitals h ON h.id=r.hospital_id WHERE r.id=?", (rid,), one=True)
    if not req or req["status"] != "open":
        abort(404)
    if req["blood_group"] != u["blood_group"]:
        abort(403)
    avail = request.form.get("availability")
    if avail not in ("available", "unavailable"):
        abort(400)
    msg = request.form.get("message", "").strip()[:300]
    db = get_db()
    db.execute("""INSERT INTO donor_responses(request_id,user_id,availability,message,created_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(request_id,user_id) DO UPDATE SET availability=excluded.availability,
                  message=excluded.message, created_at=excluded.created_at""",
               (rid, u["id"], avail, msg, now()))
    db.commit()
    if avail == "available":
        notify(req["huid"], f"{u['name']} ({u['blood_group']}) is available to donate for your request #{rid}.", url_for("hospital_home") + "#blood")
        flash(f"Thank you! {req['hname']} can now see that you are available.", "ok")
    else:
        flash("Response saved.", "ok")
    return redirect(request.referrer or url_for("blood_requests"))


@app.route("/profile", methods=["GET", "POST"])
@login_required("user")
def profile():
    u = current_user()
    if request.method == "POST":
        f = request.form
        name, phone = f.get("name", "").strip(), f.get("phone", "").strip()
        bg = f.get("blood_group", "")
        lat, lng = to_float(f.get("lat")), to_float(f.get("lng"))
        if len(name) < 2 or not PHONE_RE.match(phone) or bg not in BLOOD_GROUPS:
            flash("Please check name, phone and blood group.", "error")
            return render_template("profile.html"), 400
        ecp = f.get("emergency_contact_phone", "").strip()
        if ecp and not PHONE_RE.match(ecp):
            flash("Emergency contact phone looks invalid.", "error")
            return render_template("profile.html"), 400
        if (lat is None) != (lng is None) or (lat is not None and not valid_coords(lat, lng)):
            flash("Invalid location.", "error")
            return render_template("profile.html"), 400
        run("""UPDATE users SET name=?, phone=?, blood_group=?, city=?, lat=?, lng=?, donor_available=?,
               emergency_contact_name=?, emergency_contact_phone=? WHERE id=?""",
            (name, phone, bg, f.get("city", "").strip() or None, lat, lng,
             1 if f.get("donor_available") else 0, f.get("emergency_contact_name", "").strip() or None,
             ecp or None, u["id"]))
        flash("Profile updated.", "ok")
        return redirect(url_for("profile"))
    return render_template("profile.html")


@app.route("/hospitals")
@login_required()
def hospitals_page():
    return render_template("hospitals.html")


@app.route("/api/hospitals")
@login_required()
def api_hospitals():
    lat, lng = to_float(request.args.get("lat")), to_float(request.args.get("lng"))
    if lat is None or lng is None or not valid_coords(lat, lng):
        lat, lng = DEFAULT_CENTER
    return jsonify(hospitals=nearest_hospitals(lat, lng), origin=[lat, lng])


# --------------------------------------------------------------------------
# SOS / emergency alerts
# --------------------------------------------------------------------------

@app.route("/sos", methods=["POST"])
@login_required("user")
def sos():
    u = current_user()
    data = request.get_json(silent=True) or {}
    lat, lng = to_float(data.get("lat")), to_float(data.get("lng"))
    if lat is None or lng is None or not valid_coords(lat, lng):
        return jsonify(error="Location is missing or invalid."), 400
    etype = data.get("emergency_type")
    if etype not in EMERGENCY_TYPES:
        etype = "Other medical emergency"
    details = str(data.get("details", "")).strip()[:500]
    # avoid accidental double-taps: reuse an alert raised in the last 60 seconds
    recent = q("SELECT id FROM alerts WHERE user_id=? AND status IN ('pending','acknowledged','ambulance_dispatched') "
               "AND created_at >= datetime('now','localtime','-60 seconds')", (u["id"],), one=True)
    if recent:
        return jsonify(ok=True, alert_id=recent["id"], duplicate=True)
    aid = run("INSERT INTO alerts(user_id,lat,lng,emergency_type,details,created_at) VALUES(?,?,?,?,?,?)",
              (u["id"], lat, lng, etype, details, now()))
    near = nearest_hospitals(lat, lng)
    chosen = [h for h in near if h["distance_km"] <= ALERT_RADIUS_KM][:ALERT_HOSPITALS] or near[:ALERT_HOSPITALS]
    for h in chosen:
        run("INSERT INTO alert_hospitals(alert_id,hospital_id,distance_km,updated_at) VALUES(?,?,?,?)",
            (aid, h["id"], h["distance_km"], now()))
        notify(h["user_id"], f"SOS: {etype} - {u['name']} is {h['distance_km']} km away.", url_for("hospital_home"))
    return jsonify(ok=True, alert_id=aid, hospitals_notified=len(chosen))


def alert_payload(aid):
    a = q("SELECT a.*, u.name uname FROM alerts a JOIN users u ON u.id=a.user_id WHERE a.id=?", (aid,), one=True)
    hs = q("""SELECT ah.status, ah.distance_km, ah.updated_at, h.id hid, h.name, h.phone, h.address, h.lat, h.lng
              FROM alert_hospitals ah JOIN hospitals h ON h.id=ah.hospital_id WHERE ah.alert_id=? ORDER BY ah.distance_km""", (aid,))
    return dict(alert=dict(a), hospitals=[dict(h) for h in hs])


@app.route("/alert/<int:aid>")
@login_required("user")
def alert_view(aid):
    a = q("SELECT * FROM alerts WHERE id=?", (aid,), one=True)
    if not a or a["user_id"] != current_user()["id"]:
        abort(404)
    return render_template("alert.html", aid=aid)


@app.route("/api/alert/<int:aid>")
@login_required("user")
def api_alert(aid):
    a = q("SELECT user_id FROM alerts WHERE id=?", (aid,), one=True)
    if not a or a["user_id"] != current_user()["id"]:
        return jsonify(error="Not found"), 404
    return jsonify(alert_payload(aid))


@app.route("/alert/<int:aid>/cancel", methods=["POST"])
@login_required("user")
def alert_cancel(aid):
    a = q("SELECT * FROM alerts WHERE id=?", (aid,), one=True)
    if not a or a["user_id"] != current_user()["id"]:
        abort(404)
    if a["status"] in ("pending", "acknowledged"):
        run("UPDATE alerts SET status='cancelled' WHERE id=?", (aid,))
        run("UPDATE alert_hospitals SET status='cancelled', updated_at=? WHERE alert_id=? AND status IN ('new','acknowledged')", (now(), aid))
        for h in q("SELECT h.user_id FROM alert_hospitals ah JOIN hospitals h ON h.id=ah.hospital_id WHERE ah.alert_id=?", (aid,)):
            notify(h["user_id"], f"Alert #{aid} was cancelled by the user.", url_for("hospital_home"))
        flash("Alert cancelled.", "ok")
    return redirect(url_for("alert_view", aid=aid))


# --------------------------------------------------------------------------
# Hospital panel
# --------------------------------------------------------------------------

@app.route("/hospital")
@login_required("hospital")
def hospital_home():
    h = current_hospital()
    reqs = q("SELECT * FROM blood_requests WHERE hospital_id=? ORDER BY (status='open') DESC, id DESC LIMIT 20", (h["id"],))
    out = []
    for r in reqs:
        r = dict(r)
        r["responses"] = [dict(x) for x in q(
            """SELECT d.*, u.name, u.phone, u.blood_group FROM donor_responses d JOIN users u ON u.id=d.user_id
               WHERE d.request_id=? ORDER BY (d.availability='available') DESC, d.created_at""", (r["id"],))]
        r["available_count"] = sum(1 for x in r["responses"] if x["availability"] == "available")
        out.append(r)
    return render_template("hospital_home.html", h=h, reqs=out)


@app.route("/api/hospital/alerts")
@login_required("hospital")
def api_hospital_alerts():
    h = current_hospital()
    rows = q("""SELECT ah.id ahid, ah.status hstatus, ah.distance_km, ah.updated_at,
                a.id alert_id, a.lat, a.lng, a.emergency_type, a.details, a.status astatus, a.created_at,
                u.name pname, u.phone pphone, u.blood_group, u.emergency_contact_name ecn, u.emergency_contact_phone ecp
                FROM alert_hospitals ah JOIN alerts a ON a.id=ah.alert_id JOIN users u ON u.id=a.user_id
                WHERE ah.hospital_id=? ORDER BY (ah.status IN ('new','acknowledged','ambulance_dispatched')) DESC, a.id DESC LIMIT 30""",
             (h["id"],))
    return jsonify(alerts=[dict(r) for r in rows], hospital=dict(h))


ACTIONS = {
    "acknowledge": ("acknowledged", ("new",)),
    "dispatch": ("ambulance_dispatched", ("new", "acknowledged")),
    "resolve": ("resolved", ("ambulance_dispatched", "acknowledged")),
    "decline": ("declined", ("new", "acknowledged")),
}


@app.route("/hospital/alert/<int:aid>/<action>", methods=["POST"])
@login_required("hospital")
def hospital_alert_action(aid, action):
    h = current_hospital()
    if action not in ACTIONS:
        return jsonify(error="Unknown action"), 400
    new_status, allowed = ACTIONS[action]
    ah = q("SELECT * FROM alert_hospitals WHERE alert_id=? AND hospital_id=?", (aid, h["id"]), one=True)
    alert = q("SELECT * FROM alerts WHERE id=?", (aid,), one=True)
    if not ah or not alert:
        return jsonify(error="Not found"), 404
    if alert["status"] in ("cancelled", "resolved") or ah["status"] not in allowed:
        return jsonify(error="This alert can no longer be changed."), 409
    if action == "dispatch":
        if alert["status"] == "ambulance_dispatched":
            return jsonify(error="Another hospital has already dispatched an ambulance."), 409
        if h["ambulances"] < 1:
            return jsonify(error="No ambulance available. Update your ambulance count first."), 409
        run("UPDATE hospitals SET ambulances = ambulances - 1 WHERE id=?", (h["id"],))
    run("UPDATE alert_hospitals SET status=?, updated_at=? WHERE id=?", (new_status, now(), ah["id"]))
    if action == "dispatch":
        run("UPDATE alerts SET status='ambulance_dispatched' WHERE id=?", (aid,))
        run("UPDATE alert_hospitals SET status='covered', updated_at=? WHERE alert_id=? AND id!=? AND status IN ('new','acknowledged')",
            (now(), aid, ah["id"]))
        notify(alert["user_id"], f"{h['name']} has dispatched an ambulance to your location.", url_for("alert_view", aid=aid))
    elif action == "acknowledge":
        if alert["status"] == "pending":
            run("UPDATE alerts SET status='acknowledged' WHERE id=?", (aid,))
        notify(alert["user_id"], f"{h['name']} received your alert and is responding.", url_for("alert_view", aid=aid))
    elif action == "resolve":
        run("UPDATE alerts SET status='resolved' WHERE id=?", (aid,))
        run("UPDATE hospitals SET ambulances = ambulances + 1 WHERE id=?", (h["id"],))
        notify(alert["user_id"], f"Your emergency #{aid} was marked resolved by {h['name']}.", url_for("alert_view", aid=aid))
    elif action == "decline":
        left = q("SELECT COUNT(*) c FROM alert_hospitals WHERE alert_id=? AND status IN ('new','acknowledged','ambulance_dispatched')", (aid,), one=True)["c"]
        if left == 0:
            # everyone declined: widen the net to the next nearest hospital not yet alerted
            tried = {r["hospital_id"] for r in q("SELECT hospital_id FROM alert_hospitals WHERE alert_id=?", (aid,))}
            for nh in nearest_hospitals(alert["lat"], alert["lng"]):
                if nh["id"] not in tried:
                    run("INSERT INTO alert_hospitals(alert_id,hospital_id,distance_km,updated_at) VALUES(?,?,?,?)",
                        (aid, nh["id"], nh["distance_km"], now()))
                    notify(nh["user_id"], f"SOS forwarded to you: {alert['emergency_type']}.", url_for("hospital_home"))
                    break
    return jsonify(ok=True)


@app.route("/hospital/settings", methods=["POST"])
@login_required("hospital")
def hospital_settings():
    h = current_hospital()
    run("UPDATE hospitals SET ambulances=?, beds_available=?, specialities=?, phone=? WHERE id=?",
        (to_int(request.form.get("ambulances")), to_int(request.form.get("beds_available")),
         request.form.get("specialities", "").strip()[:200], request.form.get("phone", h["phone"]).strip() or h["phone"], h["id"]))
    flash("Hospital details updated.", "ok")
    return redirect(url_for("hospital_home"))


@app.route("/hospital/blood", methods=["POST"])
@login_required("hospital")
def hospital_blood_new():
    h = current_hospital()
    bg = request.form.get("blood_group", "")
    urgency = request.form.get("urgency", "High")
    if bg not in BLOOD_GROUPS or urgency not in URGENCY:
        flash("Choose a valid blood group and urgency.", "error")
        return redirect(url_for("hospital_home") + "#blood")
    units = to_int(request.form.get("units"), 1, 1, 50)
    details = request.form.get("details", "").strip()[:300]
    rid = run("INSERT INTO blood_requests(hospital_id,blood_group,units,urgency,details,created_at) VALUES(?,?,?,?,?,?)",
              (h["id"], bg, units, urgency, details, now()))
    donors = q("SELECT id FROM users WHERE role='user' AND blood_group=? AND donor_available=1", (bg,))
    for d in donors:
        notify(d["id"], f"{h['name']} urgently needs {units} unit(s) of {bg} blood ({urgency}).", url_for("blood_requests"))
    flash(f"Request posted. {len(donors)} matching donor(s) notified.", "ok")
    return redirect(url_for("hospital_home") + "#blood")


@app.route("/hospital/blood/<int:rid>/<action>", methods=["POST"])
@login_required("hospital")
def hospital_blood_close(rid, action):
    h = current_hospital()
    r = q("SELECT * FROM blood_requests WHERE id=? AND hospital_id=?", (rid, h["id"]), one=True)
    if not r or action not in ("fulfilled", "closed"):
        abort(404)
    run("UPDATE blood_requests SET status=? WHERE id=?", (action, rid))
    flash("Request updated.", "ok")
    return redirect(url_for("hospital_home") + "#blood")


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

@app.route("/notifications")
@login_required()
def notifications():
    u = current_user()
    rows = q("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50", (u["id"],))
    run("UPDATE notifications SET is_read=1 WHERE user_id=?", (u["id"],))
    return render_template("notifications.html", rows=rows)


@app.route("/api/unread")
@login_required()
def api_unread():
    c = q("SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0", (current_user()["id"],), one=True)["c"]
    return jsonify(unread=c)


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
