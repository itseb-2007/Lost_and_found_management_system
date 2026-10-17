# Lost and Found Management System (CampusFind)

A modern, enterprise-grade campus lost and found web platform built with **Flask**, **SQLite**, **Bootstrap 5**, and a custom **SaaS UI Design System**.

---

## ✨ Key Features & Architectural Modules

### 1. 🤖 Smart Auto-Match Suggestions Engine
- Automatically compares approved **Found** items against active **Lost** reports across campus.
- Evaluates similarities using a weighted heuristic:
  - **Category Match**: +35%
  - **Campus Location Match**: +25%
  - **Color Similarity**: +15%
  - **Title & Keyword Tokenization**: +25%
- Surfaces real-time **Possible Matches** cards with match percentages (`85% Match`), matched factor chips, photo previews, and one-click case comparisons.

### 2. 🔒 Claim Verification Flow (Challenge Question)
- When reporting a found belonging, the finder can specify a **Secret Verification Question** (e.g. *"What is the lock-screen wallpaper?"* or *"What stickers are on the back?"*) and a **Confidential Answer** (e.g. *"Golden retriever photo"*).
- Claimants are prompted to answer this hidden challenge when filing a claim.
- The Admin Moderation desk displays the **Finder's Confidential Answer** side-by-side with the **Claimant's Submitted Answer** to verify authentic ownership before approval.
- Upon approval, the case transitions to `Ready for Handover`, unlocking the official physical collection step.

### 3. 📝 Structured Handover Step & Official Certificate
- When releasing an approved belonging, campus administrators record:
  - **Collector Full Name**
  - **Identification Document Type** (Student ID Card, Faculty ID, National ID, Driver's License)
  - **ID Document Number** (e.g. `STU-2026-9912`)
  - **Handover Staff Officer**
  - **Release Remarks & Acknowledgement**
- Generates a permanent **Official Handover Certificate** on the case page and archives the case as `Successfully Recovered`.

### 4. 📜 Case History & Comprehensive Audit Trail (`case_history`)
- Dedicated audit table `case_history(case_id, old_status, new_status, changed_by, note, timestamp)`.
- Full accountability log tracking every status transition (`Pending Review` ➔ `Open` ➔ `Claim Pending` ➔ `Ready for Handover` ➔ `Successfully Recovered`).
- Interactive visual timeline on each case displaying chronological status pills, operator tags, timestamps, and decision notes. Ideal evidence for viva and administrative audits.

### 5. 🔔 In-App Notifications with Topbar Bell Dropdown
- Real-time in-app notification center via `notifications(user_id, title, message, link, is_read, created_at)`.
- Topbar bell icon with an animated unread badge counter.
- Interactive dropdown featuring:
  - Direct links to relevant cases and claim decisions.
  - "Mark all as read" control.
  - Automatic alerts for report approvals/rejections, new claims, verification decisions, auto-matches, and handover releases.

---

## 🚀 Quick Start

### 1. Prerequisites
Ensure you have Python 3.10+ installed.

### 2. Setup Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python app.py
```
Open your browser and navigate to:
👉 **[http://localhost:5000](http://localhost:5000)** (or **[http://127.0.0.1:5000](http://127.0.0.1:5000)**)

---

## 🔑 Default Credentials

### Administrator Portal
- **URL**: [http://localhost:5000/admin/login](http://localhost:5000/admin/login)
- **Email**: `admin@college.edu`
- **Password**: `admin123`

### Student Portal
- **URL**: [http://localhost:5000/login](http://localhost:5000/login)
- **Institutional Domain**: `@college.edu` (e.g. `alex@college.edu`)

---

## 📁 Database Schema

```sql
-- Core users table
CREATE TABLE users(
  id INTEGER PRIMARY KEY,
  name TEXT,
  email TEXT UNIQUE,
  password TEXT,
  role TEXT DEFAULT 'student',
  created_at TEXT
);

-- Belongings table with secret challenge & handover records
CREATE TABLE items(
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

-- Ownership claims
CREATE TABLE claims(
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  user_id INTEGER,
  description TEXT,
  claim_answer TEXT,
  status TEXT DEFAULT 'Under Review',
  admin_note TEXT,
  created_at TEXT
);

-- Status history & accountability audit log
CREATE TABLE case_history(
  id INTEGER PRIMARY KEY,
  item_id INTEGER,
  case_id TEXT,
  old_status TEXT,
  new_status TEXT,
  changed_by TEXT,
  note TEXT,
  timestamp TEXT
);

-- In-app notifications
CREATE TABLE notifications(
  id INTEGER PRIMARY KEY,
  user_id INTEGER,
  title TEXT,
  message TEXT,
  link TEXT,
  is_read INTEGER DEFAULT 0,
  created_at TEXT
);
```

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
