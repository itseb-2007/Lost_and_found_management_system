import os, sqlite3, re
from datetime import datetime
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-secret"),
                  MAX_CONTENT_LENGTH=4 * 1024 * 1024,
                  TEMPLATES_AUTO_RELOAD=True)
DB_PATH = os.path.join(BASE, "campusfind.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
ALLOWED_DOMAIN = "college.edu"          # Institutional email domain
CATEGORIES = ["Electronics", "Documents", "Bags", "Books", "Accessories", "Clothing", "Other"]
LOCATIONS = ["Library", "Computer Lab", "Cafeteria", "Auditorium", "Classroom Block", "Sports Ground", "Parking Area", "Other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  name TEXT,
  email TEXT UNIQUE,
  password TEXT,
  role TEXT DEFAULT 'student',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  case_id TEXT,
  type TEXT,
  name TEXT,
  category TEXT,
  description TEXT,
  color TEXT,
  location TEXT,
  date TEXT,
  image TEXT,
  status TEXT,
  user_id INTEGER,
  closure_reason TEXT,
  secret_question TEXT,
  secret_answer TEXT,
  handover_collector TEXT,
  handover_id_type TEXT,
  handover_id_number TEXT,
  handover_timestamp TEXT,
  handover_staff TEXT,
  handover_note TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  user_id INTEGER,
  description TEXT,
  claim_answer TEXT,
  status TEXT DEFAULT 'Under Review',
  admin_note TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  status TEXT,
  note TEXT,
  actor TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS case_history(
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  case_id TEXT,
  old_status TEXT,
  new_status TEXT,
  changed_by TEXT,
  note TEXT,
  timestamp TEXT
);

CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  title TEXT,
  message TEXT,
  link TEXT,
  is_read INTEGER DEFAULT 0,
  created_at TEXT
);
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

def now():
    return datetime.now().strftime("%d %b %Y, %H:%M")

def init_db():
    os.makedirs(UPLOADS, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)

    # Check and dynamically add any missing columns in items table
    item_cols = [r[1] for r in c.execute("PRAGMA table_info(items)").fetchall()]
    new_cols = [
        ("secret_question", "TEXT"),
        ("secret_answer", "TEXT"),
        ("handover_collector", "TEXT"),
        ("handover_id_type", "TEXT"),
        ("handover_id_number", "TEXT"),
        ("handover_timestamp", "TEXT"),
        ("handover_staff", "TEXT"),
        ("handover_note", "TEXT")
    ]
    for col_name, col_type in new_cols:
        if col_name not in item_cols:
            try:
                c.execute(f"ALTER TABLE items ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    claim_cols = [r[1] for r in c.execute("PRAGMA table_info(claims)").fetchall()]
    if "claim_answer" not in claim_cols:
        try:
            c.execute("ALTER TABLE claims ADD COLUMN claim_answer TEXT")
        except Exception:
            pass

    # Ensure admin user exists
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                  ("Admin", "admin@" + ALLOWED_DOMAIN, generate_password_hash("admin123"), "admin", now()))

    # Backfill case_history from history if case_history is empty
    if c.execute("SELECT COUNT(*) FROM case_history").fetchone()[0] == 0:
        old_h = c.execute("SELECT h.*, i.case_id FROM history h LEFT JOIN items i ON i.id=h.item_id").fetchall()
        for h in old_h:
            cid = h[5] if len(h) > 5 and h[5] else f"CF-{h[1]}"
            c.execute("INSERT INTO case_history(item_id, case_id, old_status, new_status, changed_by, note, timestamp) VALUES(?,?,?,?,?,?,?)",
                      (h[1], cid, "Initial", h[2], h[4] or "System", h[3] or "", h[5] if len(h) > 5 else now()))

    c.commit()
    c.close()

# ----------------- History / Audit Logging -----------------
def log_history(item_id, old_status, new_status, note="", changed_by=None):
    actor = changed_by or session.get("name", "System")
    row = db().execute("SELECT case_id FROM items WHERE id=?", (item_id,)).fetchone()
    cid = row["case_id"] if row and row["case_id"] else f"CF-{item_id}"
    db().execute(
        "INSERT INTO case_history(item_id, case_id, old_status, new_status, changed_by, note, timestamp) VALUES(?,?,?,?,?,?,?)",
        (item_id, cid, old_status, new_status, actor, note, now())
    )
    # Legacy table sync
    db().execute(
        "INSERT INTO history(item_id, status, note, actor, created_at) VALUES(?,?,?,?,?)",
        (item_id, new_status, note, actor, now())
    )

# ----------------- In-App Notifications -----------------
def notify(user_id, title, message, link="#"):
    try:
        db().execute(
            "INSERT INTO notifications(user_id, title, message, link, is_read, created_at) VALUES(?,?,?,?,0,?)",
            (user_id, title, message, link, now())
        )
    except Exception:
        pass

def notify_admins(title, message, link="#"):
    try:
        admins = db().execute("SELECT id FROM users WHERE role='admin'").fetchall()
        for a in admins:
            notify(a["id"], title, message, link)
    except Exception:
        pass

@app.context_processor
def inject_notifications():
    if "uid" in session:
        try:
            notifs = db().execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 12",
                (session["uid"],)
            ).fetchall()
            unread = sum(1 for n in notifs if not n["is_read"])
            return {"notifications": notifs, "unread_notifs_count": unread}
        except Exception:
            return {"notifications": [], "unread_notifs_count": 0}
    return {"notifications": [], "unread_notifs_count": 0}

@app.route("/notifications/read/<int:nid>")
@app.route("/notification/read/<int:nid>")
def notification_read(nid):
    if "uid" not in session: return redirect(url_for("login"))
    n = db().execute("SELECT * FROM notifications WHERE id=? AND user_id=?", (nid, session["uid"])).fetchone()
    if n:
        db().execute("UPDATE notifications SET is_read=1 WHERE id=?", (nid,))
        db().commit()
        if n["link"] and n["link"] != "#":
            return redirect(n["link"])
    return redirect(request.referrer or url_for("home"))

@app.route("/notifications/mark-all-read")
def notifications_mark_all_read():
    if "uid" not in session: return redirect(url_for("login"))
    db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["uid"],))
    db().commit()
    flash("All notifications marked as read.", "success")
    return redirect(request.referrer or url_for("home"))

# ----------------- Smart Auto-Match Engine -----------------
def find_matches(item_id):
    it = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it: return []
    
    target_type = "lost" if it["type"] == "found" else "found"
    # Find active counterpart items
    candidates = db().execute(
        "SELECT i.*, u.name as reporter_name FROM items i JOIN users u ON u.id=i.user_id "
        "WHERE i.type=? AND i.status NOT IN ('Closed', 'Rejected', 'Successfully Recovered')",
        (target_type,)
    ).fetchall()
    
    STOPWORDS = {"the", "a", "an", "and", "or", "for", "with", "my", "in", "on", "at", "to", "of", "item", "lost", "found", "case"}
    t_tokens = set(re.findall(r"\b\w{3,}\b", (it["name"] or "").lower())) - STOPWORDS
    t_desc_tokens = set(re.findall(r"\b\w{3,}\b", (it["description"] or "").lower())) - STOPWORDS
    
    matches = []
    for c in candidates:
        score = 0
        reasons = []
        
        # 1. Category exact match (35 pts)
        if it["category"] and c["category"] and it["category"].lower() == c["category"].lower():
            score += 35
            reasons.append(f"Category: {c['category']}")
            
        # 2. Campus Location match (25 pts)
        if it["location"] and c["location"] and it["location"].lower() == c["location"].lower():
            score += 25
            reasons.append(f"Location: {c['location']}")
            
        # 3. Colour similarity (15 pts)
        if it["color"] and c["color"]:
            c1, c2 = it["color"].strip().lower(), c["color"].strip().lower()
            if c1 in c2 or c2 in c1:
                score += 15
                reasons.append(f"Color: {c['color']}")
                
        # 4. Title keywords match (up to 25 pts)
        c_tokens = set(re.findall(r"\b\w{3,}\b", (c["name"] or "").lower())) - STOPWORDS
        common_words = t_tokens.intersection(c_tokens)
        if common_words:
            keyword_score = min(25, len(common_words) * 15)
            score += keyword_score
            reasons.append(f"Keywords: {', '.join(list(common_words)[:2])}")
            
        # 5. Description keywords overlap (up to 10 pts)
        c_desc_tokens = set(re.findall(r"\b\w{3,}\b", (c["description"] or "").lower())) - STOPWORDS
        desc_overlap = (t_tokens | t_desc_tokens).intersection(c_desc_tokens)
        if desc_overlap and not common_words:
            score += 10
            reasons.append("Context overlap")
            
        score = min(100, score)
        if score >= 35:
            matches.append({
                "item": dict(c),
                "score": score,
                "reasons": reasons
            })
            
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:6]

# ----------------- Auth Helpers -----------------
def login_required(role=None):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return redirect(url_for("login"))
            if role and session.get("role") != role: abort(403)
            return f(*a, **k)
        return w
    return deco

@app.template_filter("badge")
def badge(s):
    return {"Pending Review": "warning", "Open": "primary", "Claim Pending": "info", "Ready for Handover": "info",
            "Successfully Recovered": "success", "Rejected": "danger", "Closed": "secondary",
            "Under Review": "warning", "Approved": "success"}.get(s, "secondary")

# ---------- auth routes ----------
@app.route("/")
def home():
    if "uid" in session: return redirect(url_for("admin" if session["role"] == "admin" else "dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, pw = request.form["name"].strip(), request.form["email"].strip().lower(), request.form["password"]
        if not email.endswith("@" + ALLOWED_DOMAIN):
            flash(f"Only institutional @{ALLOWED_DOMAIN} college emails can register.", "danger")
        elif len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("This email address is already registered.", "danger")
        else:
            db().execute("INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",
                         (name, email, generate_password_hash(pw), now()))
            db().commit()
            flash("Account registered successfully! Please sign in with your credentials.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", domain=ALLOWED_DOMAIN)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role=u["role"])
            return redirect(url_for("home"))
        flash("Incorrect college email or password.", "danger")
    return render_template("login.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=? AND role='admin'", (request.form["email"].strip().lower(),)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.clear(); session.update(uid=u["id"], name=u["name"], role="admin")
            return redirect(url_for("admin"))
        flash("Incorrect administrator credentials.", "danger")
    return render_template("admin_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- student routes ----------
@app.route("/dashboard")
@login_required("student")
def dashboard():
    uid, d = session["uid"], db()
    one = lambda q, *a: d.execute(q, a).fetchone()[0]
    mine = one("SELECT COUNT(*) FROM items WHERE user_id=?", uid)
    rec = one("SELECT COUNT(*) FROM items WHERE user_id=? AND status='Successfully Recovered'", uid)
    stats = [("My Reports", mine),
             ("Found Items Available", one("SELECT COUNT(*) FROM items WHERE type='found' AND status='Open'")),
             ("My Active Cases", one("SELECT COUNT(*) FROM items WHERE user_id=? AND status NOT IN ('Successfully Recovered','Closed','Rejected')", uid)),
             ("My Pending Claims", one("SELECT COUNT(*) FROM claims WHERE user_id=? AND status='Under Review'", uid)),
             ("Recovered", rec),
             ("Recovery Rate", f"{round(rec * 100 / mine) if mine else 0}%")]
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

        secret_q = request.form.get("secret_question", "").strip() if kind == "found" else ""
        secret_a = request.form.get("secret_answer", "").strip() if kind == "found" else ""

        cur = db().execute(
            "INSERT INTO items(type,name,category,description,color,location,date,image,status,user_id,"
            "secret_question,secret_answer,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, f["name"], f["category"], f["description"], f.get("color", ""), f["location"], f["date"],
             img, "Pending Review", session["uid"], secret_q, secret_a, now(), now())
        )
        iid = cur.lastrowid
        case_id = f"CF-2026-{iid:04d}"
        db().execute("UPDATE items SET case_id=? WHERE id=?", (case_id, iid))
        log_history(iid, "Initial", "Pending Review", f"Report submitted by {session.get('name')}")
        db().commit()

        # Notify Campus Administrators
        notify_admins(f"New {kind.capitalize()} Report: {f['name']}",
                      f"Case {case_id} submitted by {session.get('name')} is awaiting review.",
                      url_for("item", iid=iid))

        flash(f"Report submitted. Case ID {case_id} is awaiting staff review.", "success")
        return redirect(url_for("my_reports"))
    return render_template("report.html", kind=kind, cats=CATEGORIES, locs=LOCATIONS)

@app.route("/item/<int:iid>")
@login_required()
def item(iid):
    it = db().execute("SELECT i.*, u.name AS reporter FROM items i JOIN users u ON u.id=i.user_id WHERE i.id=?", (iid,)).fetchone()
    if not it: abort(404)
    admin, owner = session["role"] == "admin", it["user_id"] == session["uid"]
    if it["status"] in ("Pending Review", "Rejected") and not (admin or owner): abort(403)
    
    # Audit history using case_history table
    hist = db().execute("SELECT * FROM case_history WHERE item_id=? ORDER BY id ASC", (iid,)).fetchall()
    if not hist:
        # Fallback to history table if case_history has not backfilled yet
        hist = db().execute("SELECT id, item_id, '' as case_id, 'Status Update' as old_status, status as new_status, actor as changed_by, note, created_at as timestamp FROM history WHERE item_id=? ORDER BY id ASC", (iid,)).fetchall()

    claims = []
    approved_claim = None
    if admin or owner:
        claims = db().execute("SELECT c.*, u.name, u.email FROM claims c JOIN users u ON u.id=c.user_id WHERE item_id=? ORDER BY c.id DESC", (iid,)).fetchall()
        for c in claims:
            if c["status"] == "Approved":
                approved_claim = c

    mine = db().execute("SELECT * FROM claims WHERE item_id=? AND user_id=?", (iid, session["uid"])).fetchone()
    can_claim = it["type"] == "found" and it["status"] in ("Open", "Claim Pending") and not owner and not admin and not mine

    # Auto-match suggestions
    matches = find_matches(iid) if (admin or it["status"] in ("Open", "Claim Pending", "Ready for Handover")) else []

    return render_template("item.html", it=it, hist=hist, claims=claims, approved_claim=approved_claim, can_claim=can_claim, admin=admin, owner=owner, mine=mine, matches=matches)

@app.route("/item/<int:iid>/claim", methods=["POST"])
@login_required("student")
def claim(iid):
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not it or it["type"] != "found" or it["status"] not in ("Open", "Claim Pending") or it["user_id"] == session["uid"]:
        abort(403)

    claim_ans = request.form.get("claim_answer", "").strip()
    desc = request.form.get("description", "").strip()

    if not claim_ans and not desc:
        flash("Please provide your answer or verification details.", "danger")
        return redirect(url_for("item", iid=iid))

    old_status = it["status"]
    db().execute("INSERT INTO claims(item_id,user_id,claim_answer,description,created_at) VALUES(?,?,?,?,?)",
                 (iid, session["uid"], claim_ans, desc, now()))
    db().execute("UPDATE items SET status='Claim Pending', updated_at=? WHERE id=?", (now(), iid))
    log_history(iid, old_status, "Claim Pending", f"Ownership claim submitted by {session.get('name')}")
    db().commit()

    # Alert administrators
    notify_admins(f"New Ownership Claim: {it['name']}",
                  f"{session.get('name')} submitted a verification claim on case {it['case_id']}.",
                  url_for("item", iid=iid))

    flash("Ownership claim submitted. Campus staff will verify your answer against the finder's confidential record.", "success")
    return redirect(url_for("my_claims"))

@app.route("/my/reports")
@login_required("student")
def my_reports():
    rows = db().execute("SELECT * FROM items WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return render_template("my_reports.html", rows=rows)

@app.route("/my/claims")
@login_required("student")
def my_claims():
    rows = db().execute(
        "SELECT c.*, i.name, i.case_id, i.image, i.location, i.secret_question "
        "FROM claims c JOIN items i ON i.id=c.item_id WHERE c.user_id=? ORDER BY c.id DESC",
        (session["uid"],)
    ).fetchall()
    return render_template("my_claims.html", rows=rows)

# ---------- admin routes ----------
@app.route("/admin")
@login_required("admin")
def admin():
    d = db(); one = lambda q: d.execute(q).fetchone()[0]
    tot, rec = one("SELECT COUNT(*) FROM items"), one("SELECT COUNT(*) FROM items WHERE status='Successfully Recovered'")
    elig = one("SELECT COUNT(*) FROM items WHERE status NOT IN ('Rejected','Pending Review')")
    stats = [("Total Cases", tot),
             ("Pending Reviews", one("SELECT COUNT(*) FROM items WHERE status='Pending Review'")),
             ("Open Cases", one("SELECT COUNT(*) FROM items WHERE status='Open'")),
             ("Pending Claims", one("SELECT COUNT(*) FROM claims WHERE status='Under Review'")),
             ("Ready for Handover", one("SELECT COUNT(*) FROM items WHERE status='Ready for Handover'")),
             ("Recovered", rec),
             ("Closed", one("SELECT COUNT(*) FROM items WHERE status='Closed'")),
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
    if not it or it["status"] != "Pending Review": abort(400)
    old_status = it["status"]

    action = request.form.get("action", "").strip()
    reason = request.form.get("reason", "").strip()

    if action == "approve" or (not action and not reason):
        new, note = "Open", "Report approved and published to directory"
    else:
        if not reason:
            flash("A reason is required to reject a report.", "danger")
            return redirect(url_for("item", iid=iid))
        new, note = "Rejected", "Rejected: " + reason

    db().execute("UPDATE items SET status=?, updated_at=? WHERE id=?", (new, now(), iid))
    log_history(iid, old_status, new, note)
    db().commit()

    # Notify student reporter
    if new == "Open":
        notify(it["user_id"], "Your Report Was Approved! 🎉",
               f"Your report for '{it['name']}' ({it['case_id']}) has been approved and is now live on the directory.",
               url_for("item", iid=iid))
    else:
        notify(it["user_id"], "Report Update: Rejected",
               f"Your report for '{it['name']}' ({it['case_id']}) was rejected: {note}",
               url_for("item", iid=iid))

    # Auto-match detection trigger
    if new == "Open":
        matches = find_matches(iid)
        if matches:
            flash(f"Report approved! 🤖 Auto-Matcher detected {len(matches)} potential case match(es) for this item.", "success")
            notify_admins(f"Auto-Match: {it['name']}",
                          f"System found {len(matches)} potential match(es) for case {it['case_id']}.",
                          url_for("item", iid=iid))
            return redirect(url_for("item", iid=iid))

    flash(f"Report {new.lower()}.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/claim/<int:cid>/decide", methods=["POST"])
@login_required("admin")
def decide(cid):
    c = db().execute("SELECT c.*, i.name as item_name, i.case_id, i.user_id as finder_id FROM claims c JOIN items i ON i.id=c.item_id WHERE c.id=?", (cid,)).fetchone()
    if not c or c["status"] != "Under Review": abort(400)
    note = request.form.get("note", "").strip()
    iid = c["item_id"]
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    old_status = it["status"]

    action = request.form.get("action", "").strip()
    if action == "approve":
        db().execute("UPDATE claims SET status='Approved', admin_note=? WHERE id=?", (note, cid))
        db().execute("UPDATE claims SET status='Rejected', admin_note='Another claim was verified and approved' WHERE item_id=? AND id!=? AND status='Under Review'", (iid, cid))
        db().execute("UPDATE items SET status='Ready for Handover', updated_at=? WHERE id=?", (now(), iid))
        log_history(iid, old_status, "Ready for Handover", f"Claim by student #{c['user_id']} approved. Staff Note: {note}")

        # Notify approved claimant
        notify(c["user_id"], "Claim Approved! 🎁 Ready for Handover",
               f"Your ownership verification for '{c['item_name']}' was approved! Please visit the Security Desk with your ID to collect.",
               url_for("item", iid=iid))
        # Notify finder
        notify(c["finder_id"], "Claim Verified on Found Item",
               f"The rightful owner of '{c['item_name']}' ({c['case_id']}) has been verified. The item is now ready for handover.",
               url_for("item", iid=iid))
    else:
        if not note: flash("A reason is required to reject a claim.", "danger"); return redirect(url_for("item", iid=iid))
        db().execute("UPDATE claims SET status='Rejected', admin_note=? WHERE id=?", (note, cid))
        left = db().execute("SELECT 1 FROM claims WHERE item_id=? AND status='Under Review'", (iid,)).fetchone()
        new_status = "Open" if not left else "Claim Pending"
        db().execute("UPDATE items SET status=?, updated_at=? WHERE id=?", (new_status, now(), iid))
        log_history(iid, old_status, new_status, f"Claim by student #{c['user_id']} rejected: {note}")

        notify(c["user_id"], "Claim Verification Update",
               f"Your claim for '{c['item_name']}' was not approved: {note}",
               url_for("item", iid=iid))

    db().commit()
    flash("Claim decision recorded.", "success")
    return redirect(url_for("item", iid=iid))

@app.route("/admin/item/<int:iid>/resolve", methods=["POST"])
@login_required("admin")
def resolve(iid):
    it = db().execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    act = request.form.get("action", "").strip()
    old_status = it["status"]

    if act == "recovered" and it["status"] == "Ready for Handover":
        collector = request.form.get("collector_name", "").strip()
        id_type = request.form.get("handover_id_type", "").strip()
        id_num = request.form.get("handover_id_number", "").strip()
        h_note = request.form.get("handover_note", "").strip()

        if not collector or not id_num:
            flash("Collector full name and verified ID number are required to record handover.", "danger")
            return redirect(url_for("item", iid=iid))

        new = "Successfully Recovered"
        note = f"Item handed over to {collector} (Verified {id_type}: #{id_num}) by staff {session.get('name', 'Admin')}. {h_note}"
        db().execute(
            "UPDATE items SET status=?, updated_at=?, handover_collector=?, handover_id_type=?, handover_id_number=?, "
            "handover_timestamp=?, handover_staff=?, handover_note=? WHERE id=?",
            (new, now(), collector, id_type, id_num, now(), session.get("name", "Admin"), h_note, iid)
        )
        log_history(iid, old_status, new, note)

        # Notify reporter
        notify(it["user_id"], "Item Successfully Recovered & Handed Over! 🏆",
               f"Case {it['case_id']} ({it['name']}) handover is officially completed and verified.",
               url_for("item", iid=iid))

        # Notify approved claimant if different
        approved_claim = db().execute("SELECT user_id FROM claims WHERE item_id=? AND status='Approved'", (iid,)).fetchone()
        if approved_claim and approved_claim["user_id"] != it["user_id"]:
            notify(approved_claim["user_id"], "Handover Confirmed!",
                   f"Your collection of '{it['name']}' has been officially verified and archived.",
                   url_for("item", iid=iid))

    elif act == "closed" and it["status"] in ("Open", "Claim Pending", "Ready for Handover"):
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("A closure reason is required to close a case.", "danger")
            return redirect(url_for("item", iid=iid))
        new, note = "Closed", "Closed without recovery: " + reason
        db().execute("UPDATE items SET status=?, updated_at=?, closure_reason=? WHERE id=?", (new, now(), reason, iid))
        log_history(iid, old_status, new, note)
    else:
        flash("This action is not allowed for the current status.", "danger")
        return redirect(url_for("item", iid=iid))

    db().commit()
    flash(f"Case marked: {new}.", "success")
    return redirect(url_for("item", iid=iid))

@app.errorhandler(403)
def forbidden(e): return render_template("error.html", msg="You don't have permission to view this page."), 403
@app.errorhandler(404)
def missing(e): return render_template("error.html", msg="That page doesn't exist."), 404

init_db()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
