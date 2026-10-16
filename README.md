# Lost and Found Management System (CampusFind)

A modern campus lost and found web application built with **Flask**, **SQLite**, and **Bootstrap 5**.

## 📌 Features

- **User Authentication**: Student and Admin accounts with secure password hashing.
- **Report Lost & Found Items**: Submit reports with photos, category, location, date, and description.
- **Claim Verification**: Users can claim items with proof/verification details.
- **Admin Dashboard**: Manage reports, verify claims, resolve cases, and view audit history.
- **Search & Filters**: Search by item title, category, status, and campus location.

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
Open your browser and navigate to `http://127.0.0.1:5000`.

## 🔑 Admin Access
- **Email**: `admin@college.edu`
- **Password**: `admin123`

> **Note**: You can change `ALLOWED_DOMAIN` and default admin credentials in [app.py](file:///d:/campusfind/app.py).

## 📁 Project Structure

```
├── app.py              # Main Flask application & routes
├── requirements.txt    # Project dependencies
├── README.md           # Documentation
├── static/
│   ├── style.css       # Custom styling
│   └── uploads/        # Uploaded item photos
└── templates/          # HTML templates (Bootstrap 5)
```

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
