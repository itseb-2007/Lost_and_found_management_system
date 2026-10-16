import os, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret"),
                  MAX_CONTENT_LENGTH=4 * 1024 * 1024)
DB_PATH = os.path.join(BASE, "campusfind.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
ALLOWED_DOMAIN = "college.edu"          # CHANGE to your college email domain
CATEGORIES = ["Electronics", "Documents", "Bags", "Books", "Accessories", "Clothing", "Other"]
LOCATIONS = ["Library", "Computer Lab", "Cafeteria", "Auditorium", "Classroom Block", "Sports Ground", "Parking Area", "Other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT,
  role TEXT DEFAULT 'student', created_at TEXT);
CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, case_id TEXT, type TEXT, name TEXT, category TEXT,
  description TEXT, color TEXT, location TEXT, date TEXT, image TEXT, status TEXT, user_id INTEGER,
  closure_reason TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY, item_id INTEGER, user_id INTEGER, description TEXT,
  status TEXT DEFAULT 'Under Review', admin_note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, item_id INTEGER, status TEXT, note TEXT, actor TEXT, created_at TEXT);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                  ("Admin", "admin@" + ALLOWED_DOMAIN, generate_password_hash("admin123"), "admin", now()))
    c.commit(); c.close()

def now(): return datetime.now().strftime("%d %b %Y, %H:%M")

def log(item_id, status, note=""):
    db().execute("INSERT INTO history(item_id,status,note,actor,created_at) VALUES(?,?,?,?,?)",
                 (item_id, status, note, session.get("name", "System"), now()))

def login_required(role=None):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return redirect(url_for("login"))
            if role and session.get("role") != role: abort(403)   # permissions enforced on the server
            return f(*a, **k)
        return w
    return deco

@app.template_filter("badge")
def badge(s):
    return {"Pending Review": "warning", "Open": "primary", "Claim Pending": "info", "Ready for Handover": "info",
            "Successfully Recovered": "success", "Rejected": "danger", "Closed": "secondary",
            "Under Review": "warning", "Approved": "success"}.get(s, "secondary")

# ---------- auth ----------
@app.route("/")
def home():
    if "uid" in session: return redirect(url_for("admin" if session["role"] == "admin" else "dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, pw = request.form["name"].strip(), request.form["email"].strip().lower(), request.form["password"]
        if not email.endswith("@" + ALLOWED_DOMAIN):
            flash(f"Only @{ALLOWED_DOMAIN} college emails can register.", "danger")
        elif len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("This email is already registered.", "danger")
        else:
            db().execute("INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",
                         (name, email, generate_password_hash(pw), now()))
            db().commit(); flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", domain=ALLOWED_DOMAIN)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role=u["role"])
            return redirect(url_for("home"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=? AND role='admin'", (request.form["email"].strip().lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.clear(); session.update(uid=u["id"], name=u["name"], role="admin")
            return redirect(url_for("admin"))
        flash("Incorrect admin email or password.", "danger")
    return render_template("admin_login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ---------- student ----------
@app.route("/dashboard")
@login_required("student")
def dashboard():
    uid, d = session["uid"], db()
    one = lambda q, *a: d.execute(q, a).fetchone()[0]
    mine = one("SELECT COUNT(*) FROM items WHERE user_id=?", uid)
    rec = one("SELECT COUNT(*) FROM items WHERE user_id=? AND status='Successfully Recovered'", uid)
    stats = [("My Reports", mine), ("Found Items Available", one("SELECT COUNT(*) FROM items WHERE type='found' AND status='Open'")),
             ("My Active Cases", one("SELECT COUNT(*) FROM items WHERE user_id=? AND status NOT IN ('Successfully Recovered','Closed','Rejected')", uid)),
             ("My Pending Claims", one("SELECT COUNT(*) FROM claims WHERE user_id=? AND status='Under Review'", uid)),
             ("Recovered", rec), ("Recovery Rate", f"{round(rec * 100 / mine) if mine else 0}%")]
    recent = d.execute("SELECT * FROM items WHERE status NOT IN ('Pending Review','Rejected') ORDER BY id DESC LIMIT 6").fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent)

@app.route("/items")
@login_required()
def browse():
    q, f = [], []
    sql = "SELECT * FROM items WHERE status NOT IN ('Pending Review','Rejected')"
    s = request.args.get("q", "").strip()
    if s:
        sql += " AND (name LIKE ? OR description LIKE ? OR case_id LIKE ? OR color LIKE ?)"; q += [f"%{s}%"] * 4
    for col in ("type", "category", "location", "status"):
        v = request.args.get(col, "")
        if v: sql += f" AND {col}=?"; q.append(v)
    rows = db().execute(sql + " ORDER BY id DESC", q).fetchall()
    return render_template("browse.html", items=rows, cats=CATEGORIES, locs=LOCATIONS, a=request.args)

@app.route("/report/<kind>", methods=["GET", "POST"])
@login_required("student")
def report(kind):
    if kind not in ("lost", "found"): abort(404)
    if request.method == "POST":
        f, img = request.form, None
        file = request.files.get("image")
        if file and file.filename:
            if file.filename.rsplit(".", 1)[-1].lower() not in ("jpg", "jpeg", "png", "webp"):
                flash("Only JPG, PNG or WEBP images are allowed.", "danger")
                return render_template("report.html", kind=kind, cats=CATEGORIES, locs=LOCATIONS)
            img = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + secure_filename(file.filename)
            file.save(os.path.join(UPLOADS, img))
        cur = db().execute("INSERT INTO items(type,name,category,description,color,location,date,image,status,user_id,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (kind, f["name"], f["category"], f["description"], f.get("color", ""), f["location"], f["date"],
                            img, "Pending Review", session["uid"], now(), now()))
        iid = cur.lastrowid
        db().execute("UPDATE items SET case_id=? WHERE id=?", (f"CF-{2026}-{iid:04d}", iid))
        log(iid, "Pending Review", "Report submitted"); db().commit()
        flash(f"Report submitted. Case ID CF-2026-{iid:04d} is awaiting admin review.", "success")
        return redirect(url_for("my_reports"))
    return render_template("report.html", kind=kind, cats=CATEGORIES, locs=LOCATIONS)

@app.route("/item/<int:iid>")
@login_required()
def item(iid):
    it = db().execute("SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id=i.user_id WHERE i.id=?", (iid,)).fetchone()
    if not it: abort(404)
    admin, owner = session["role"] == "admin", it["user_id"] == session["uid"]
    if it["status"] in ("Pending Review", "Rejected") and not (admin or owner): abort(403)
    hist = db().execute("SELECT * FROM history WHERE item_id=? ORDER BY id", (iid,)).fetchall()
    claims = []
    if admin:
        claims = db().execute("SELECT c.*, u.name, u.email FROM claims c JOIN users u ON u.id=c.user_id WHERE item_id=?", (iid,)).fetchall()
    mine = db().execute("SELECT 1 FROM claims WHERE item_id=? AND user_id=?", (iid, session["uid"])).fetchone()
    can_claim = it["type"] == "found" and it["status"] in ("Open", "Claim Pending") and not owner and not admin and not mine
    return render_template("item.html", it=it, hist=hist, claims=claims, can_claim=can_claim, admin=admin, owner=owner, mine=mine)

@app.route("/item/<int:iid>/claim", methods=["POST"])
@login_required("student")
def claim(iid):
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not it or it["type"] != "found" or it["status"] not in ("Open", "Claim Pending") or it["user_id"] == session["uid"]:
        abort(403)
    db().execute("INSERT INTO claims(item_id,user_id,description,created_at) VALUES(?,?,?,?)",
                 (iid, session["uid"], request.form["description"], now()))
    db().execute("UPDATE items SET status='Claim Pending', updated_at=? WHERE id=?", (now(), iid))
    log(iid, "Claim Pending", "Ownership claim submitted"); db().commit()
    flash("Claim submitted. The admin will verify it.", "success")
    return redirect(url_for("my_claims"))

@app.route("/my/reports")
@login_required("student")
def my_reports():
    rows = db().execute("SELECT * FROM items WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return render_template("my_reports.html", rows=rows)

@app.route("/my/claims")
@login_required("student")
def my_claims():
    rows = db().execute("SELECT c.*, i.name, i.case_id FROM claims c JOIN items i ON i.id=c.item_id WHERE c.user_id=? ORDER BY c.id DESC", (session["uid"],)).fetchall()
    return render_template("my_claims.html", rows=rows)

# ---------- admin ----------
@app.route("/admin")
@login_required("admin")
def admin():
    d = db(); one = lambda q: d.execute(q).fetchone()[0]
    tot, rec = one("SELECT COUNT(*) FROM items"), one("SELECT COUNT(*) FROM items WHERE status='Successfully Recovered'")
    elig = one("SELECT COUNT(*) FROM items WHERE status NOT IN ('Rejected','Pending Review')")
    stats = [("Total Cases", tot), ("Pending Reviews", one("SELECT COUNT(*) FROM items WHERE status='Pending Review'")),
             ("Open Cases", one("SELECT COUNT(*) FROM items WHERE status='Open'")),
             ("Pending Claims", one("SELECT COUNT(*) FROM claims WHERE status='Under Review'")),
             ("Ready for Handover", one("SELECT COUNT(*) FROM items WHERE status='Ready for Handover'")),
             ("Recovered", rec), ("Closed", one("SELECT COUNT(*) FROM items WHERE status='Closed'")),
             ("Recovery Rate", f"{round(rec * 100 / elig) if elig else 0}%")]
    att = d.execute("SELECT * FROM items WHERE status IN ('Pending Review','Claim Pending','Ready for Handover') ORDER BY id").fetchall()
    return render_template("admin.html", stats=stats, att=att)

@app.route("/admin/cases")
@login_required("admin")
def admin_cases():
    st = request.args.get("status", "")
    rows = db().execute("SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id=i.user_id" +
                        (" WHERE i.status=?" if st else "") + " ORDER BY i.id DESC", (st,) if st else ()).fetchall()
    return render_template("admin_cases.html", rows=rows, st=st)

@app.route("/admin/item/<int:iid>/review", methods=["POST"])
@login_required("admin")
def review(iid):
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not it or it["status"] != "Pending Review": abort(400)       # valid transitions only
    if request.form["action"] == "approve": new, note = "Open", "Report approved"
    else:
        reason = request.form.get("reason", "").strip()
        if not reason: flash("A reason is required to reject a report.", "danger"); return redirect(url_for("item", iid=iid))
        new, note = "Rejected", "Rejected: " + reason
    db().execute("UPDATE items SET status=?, updated_at=? WHERE id=?", (new, now(), iid)); log(iid, new, note); db().commit()
    flash(f"Report {new.lower()}.", "success"); return redirect(url_for("admin"))

@app.route("/admin/claim/<int:cid>/decide", methods=["POST"])
@login_required("admin")
def decide(cid):
    c = db().execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
    if not c or c["status"] != "Under Review": abort(400)
    note = request.form.get("note", "").strip()
    if request.form["action"] == "approve":
        db().execute("UPDATE claims SET status='Approved', admin_note=? WHERE id=?", (note, cid))
        db().execute("UPDATE claims SET status='Rejected', admin_note='Another claim was approved' WHERE item_id=? AND id!=? AND status='Under Review'", (c["item_id"], cid))
        db().execute("UPDATE items SET status='Ready for Handover', updated_at=? WHERE id=?", (now(), c["item_id"]))
        log(c["item_id"], "Ready for Handover", "Claim approved. " + note)
    else:
        if not note: flash("A reason is required to reject a claim.", "danger"); return redirect(url_for("item", iid=c["item_id"]))
        db().execute("UPDATE claims SET status='Rejected', admin_note=? WHERE id=?", (note, cid))
        left = db().execute("SELECT 1 FROM claims WHERE item_id=? AND status='Under Review'", (c["item_id"],)).fetchone()
        if not left: db().execute("UPDATE items SET status='Open', updated_at=? WHERE id=?", (now(), c["item_id"]))
        log(c["item_id"], "Open" if not left else "Claim Pending", "Claim rejected: " + note)
    db().commit(); flash("Decision recorded.", "success"); return redirect(url_for("item", iid=c["item_id"]))

@app.route("/admin/item/<int:iid>/resolve", methods=["POST"])
@login_required("admin")
def resolve(iid):
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    act, reason = request.form["action"], request.form.get("reason", "").strip()
    if act == "recovered" and it["status"] == "Ready for Handover":
        new, note = "Successfully Recovered", "Handover confirmed. " + reason
    elif act == "closed" and it["status"] in ("Open", "Claim Pending", "Ready for Handover") and reason:
        new, note = "Closed", "Closed without recovery: " + reason
        db().execute("UPDATE items SET closure_reason=? WHERE id=?", (reason, iid))
    else:
        flash("This action is not allowed for the current status (a reason is required to close).", "danger")
        return redirect(url_for("item", iid=iid))
    db().execute("UPDATE items SET status=?, updated_at=? WHERE id=?", (new, now(), iid)); log(iid, new, note); db().commit()
    flash(f"Case marked: {new}.", "success"); return redirect(url_for("item", iid=iid))

@app.errorhandler(403)
def forbidden(e): return render_template("error.html", msg="You don't have permission to view this page."), 403
@app.errorhandler(404)
def missing(e): return render_template("error.html", msg="That page doesn't exist."), 404

init_db()
if __name__ == "__main__":
    app.run(debug=True)
