from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for, abort, jsonify, send_file
import os
import razorpay
import json
import smtplib
import time
import sqlite3
import csv
import random
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from email.message import EmailMessage



def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        phone TEXT,
        course TEXT,
        name TEXT,
        demo_done INTEGER,
        enrolled INTEGER,
        hours_used INTEGER,
        max_hours INTEGER,
        payment_amount INTEGER,
        last_updated TEXT
    )
    """)

     # 🔥 ADD THIS NEW TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS class_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT,
        meet_link TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# -------------------- APP INIT --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# -------------------- IN-MEMORY STORES --------------------
# FIX: otp_store was never initialized — caused NameError crash
otp_store = {}

# FIX: feedback_db was never initialized — caused NameError crash
feedback_db = {}

# FIX: test user had no password field — caused KeyError on login
users = {}  # registered users: {email: {...}}

# Phone-based demo users
demo_users = {}  # {phone: {...}}

# Teacher accounts
teachers = {
    "Balakumar": {
        "password": "M10@2026",
        "course": "cbse10",
        "meet_link": "",
        "active": True
    },
    "faculty2": {
        "password": "Faculty2@2026",
        "course": "cbse12",
        "meet_link": "",
        "active": False
    }
}

# Seat tracking — shared across server (in production use DB/Redis)
seat_data = {
    "cbse10": {"total": 30, "booked": 0},
    "cbse12": {"total": 30, "booked": 0},
    "cbse11": {"total": 30, "booked": 0},
    "cbse9":  {"total": 30, "booked": 0},
}

# Admin phone for testing (demo always available)
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "7702616245")

# -------------------- PRICE CONFIG --------------------
price_per_hour = {
    "cbse9":  2000,
    "cbse10": 1,
    "cbse11": 350,
    "cbse12": 400,
    "engg1":  700,
    "engg2":  700,
    "engg3":  700,
    "control": 800,
}
classes_per_month = 12  # 3 days/week * 4 weeks

# -------------------- HELPERS --------------------

def get_user(phone):
    if phone not in demo_users:
        demo_users[phone] = {
            "name": "",
            "phone": phone,
            "demo_done": {},
            "enrolled": {},
            "hours_used": {},
            "max_hours": {},
        }

        # 🔥 LOAD FROM DB
        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        c.execute("SELECT * FROM students WHERE phone=?", (phone,))
        rows = c.fetchall()

        for r in rows:
            course = r[1]
            demo_users[phone]["demo_done"][course] = bool(r[3])
            demo_users[phone]["enrolled"][course] = bool(r[4])
            demo_users[phone]["hours_used"][course] = r[5]
            demo_users[phone]["max_hours"][course] = r[6]

        conn.close()

    return demo_users[phone]

def is_admin_phone(phone):
    """Admin phone always gets demo access for testing."""
    return phone == ADMIN_PHONE

def available_seats(course):
    d = seat_data.get(course, {"total": 30, "booked": 0})
    return d["total"] - d["booked"]

# -------------------- AUTH: OTP --------------------

@app.route("/save-user", methods=["POST"])
def save_user():
    data = request.json
    phone = data.get("phone")

    session["phone"] = phone
    get_user(phone)

    return jsonify({"status": "ok"})

# -------------------- DEMO --------------------

@app.route("/api/check-demo")
def check_demo():
    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Unauthorized"}), 401

    course = request.args.get("course")   ✅

    if not course:
        return jsonify({"error": "Course missing"}), 400
    user = get_user(phone)

    demo_done = user["demo_done"].get(course, False)
    return jsonify({"demo_done": demo_done, "meet_link":meet_link})


@app.route("/api/demo-complete", methods=["POST"])
def demo_complete():
    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Unauthorized"}), 401

    course = request.json.get("course")
    if not course:
        return jsonify({"error": "Course missing"}), 400
        
    user = get_user(phone)
    user["demo_done"][course] = True

    conn = sqlite3.connect("students.db")
    c = conn.cursor()
    
    c.execute("""
    INSERT OR REPLACE INTO students 
    (phone, course, name, demo_done, enrolled, hours_used, max_hours, payment_amount, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        phone,
        course,
        user.get("name", ""),
        1,
        int(user["enrolled"].get(course, False)),
        user["hours_used"].get(course, 0),
        user["max_hours"].get(course, 0),
        0,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    
    conn.commit()
    conn.close()

    return jsonify({"status": "saved"})


@app.before_request
def force_https():
    if request.headers.get('X-Forwarded-Proto') == 'http':
        return redirect(request.url.replace('http://', 'https://'))

@app.route("/api/seat-count")
def seat_count():
    """Return available seats for all courses."""
    result = {}
    for course, d in seat_data.items():
        result[course] = {
            "available": d["total"] - d["booked"],
            "total": d["total"]
        }
    return jsonify(result)

# -------------------- ENROLL + PAYMENT --------------------

@app.route("/api/enroll-info")
def enroll_info():
    """Return price info for a course."""
    course = request.args.get("course")
    if course not in price_per_hour:
        return jsonify({"error": "Invalid course"}), 400

    monthly = price_per_hour[course] * classes_per_month
    return jsonify({
        "course": course,
        "monthly_amount": monthly,
        "classes_per_month": classes_per_month,
        "meet_link": meet_link
    })


@app.route("/api/create-order", methods=["POST"])
def create_order():
    """Create Razorpay order for enrollment."""
    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Not logged in"}), 401

    data = request.json
    course = data.get("course")
    name   = data.get("name", "").strip()

    if not name:
        return jsonify({"error": "Name required"}), 400
    if course not in price_per_hour:
        return jsonify({"error": "Invalid course"}), 400

    user = get_user(phone)

    # Check demo done
    if not user["demo_done"].get(course) and not is_admin_phone(phone):
        return jsonify({"error": "Attend demo first"}), 403

    # Check seats
    if available_seats(course) <= 0:
        return jsonify({"error": "Seats full"}), 403

   # 50% OFF for first 10 students
    booked = seat_data.get(course, {}).get("booked", 0)
    discount = booked < 10
    base_amount = price_per_hour[course] * classes_per_month
    amount = int(base_amount * 0.5) if discount else base_amount
    discount_applied = discount


    try:
        with open("admin.json") as f:
            keys = json.load(f)
        client = razorpay.Client(auth=(keys["razorpay_key"], keys["razorpay_secret"]))
        order = client.order.create({
            "amount": amount * 100,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {"course": course, "phone": phone, "name": name}
        })
    except Exception as e:
        print("Razorpay error:", e)
        return jsonify({"error": "Payment init failed"}), 500

    # Save name
    user["name"] = name
    session["pending_course"] = course

    return jsonify({
        "order_id": order["id"],
        "amount": amount * 100,
        "razorpay_key": keys["razorpay_key"],
        "name": name,
        "course": course,
        "discount_applied": discount_applied,
        "original_amount": base_amount * 100

    })


@app.route("/api/payment-success", methods=["POST"])
def payment_success_api():
    """Called after successful Razorpay payment."""
    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    course = data.get("course") or session.get("pending_course")

    if not course:
        return jsonify({"error": "No course"}), 400

    user = get_user(phone)
  
    # Mark enrolled + set hours
    user["enrolled"][course] = True
    user["hours_used"][course] = 0
    user["max_hours"][course] = classes_per_month  # 24 classes

    conn = sqlite3.connect("students.db")
    c = conn.cursor()
    
    c.execute("""
    INSERT OR REPLACE INTO students 
    (phone, course, name, demo_done, enrolled, hours_used, max_hours, payment_amount, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        phone,
        course,
        user.get("name", ""),
        int(user["demo_done"].get(course, False)),
        1,
        0,
        classes_per_month,
        price_per_hour.get(course, 0) * classes_per_month,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    
    conn.commit()
    conn.close()

    # Increment seat count
    if course in seat_data:
        seat_data[course]["booked"] = min(
            seat_data[course]["booked"] + 1,
            seat_data[course]["total"]
        )

    # Save to CSV
    try:
        file = "payments.csv"
        write_header = not os.path.exists(file)
        with open(file, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["Date", "Phone", "Name", "Course", "Amount"])
            writer.writerow([
                datetime.now().strftime("%d-%m-%Y %H:%M"),
                phone,
                user.get("name", ""),
                course,
                price_per_hour.get(course, 0) * classes_per_month
            ])
    except Exception as e:
        print("CSV error:", e)

    return jsonify({
        "status": "success",
        "enrolled": True,
        "meet_link": CLASS_MEET_LINK,
        "hours_remaining": user["max_hours"][course]
    })

# -------------------- JOIN CLASS --------------------

@app.route("/api/join-class")
def join_class_api():
    """Check if student can join and return meet link."""
    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Not logged in"}), 401

    user = get_user(phone)

    # 🔥 find enrolled course automatically
    course = None
    for c, status in user["enrolled"].items():
        if status:
            course = c
            break

    # 🔥 DEMO LOGIC
    if not user["enrolled"].get(course):

        # demo already attended?
        if user.get("demo_done", {}).get(course):
            return jsonify({"error": "Demo already used. Please enroll."}), 403

        # mark demo used
        user.setdefault("demo_done", {})[course] = True

    else:
        # 🔥 PAID USER LOGIC
        hours_used = user["hours_used"].get(course, 0)
        max_hours  = user["max_hours"].get(course, classes_per_month)

    if hours_used >= max_hours:
        # Auto-deactivate: mark as not enrolled
        user["enrolled"][course] = False
        return jsonify({"error": "Plan completed. Please re-enroll."}), 403

     # Increment class count
    user["hours_used"][course] = hours_used + 1

     # 🔥 find active teacher class
    meet_link = None

    for t in teachers.values():
        if t["course"] == course and t["active"]:
            meet_link = t["meet_link"]
            break

    if not meet_link:
        return jsonify({"error": "Class not started yet"}), 404

    # AFTER increment
    conn = sqlite3.connect("students.db")
    c = conn.cursor()
    
    c.execute("""
    UPDATE students 
    SET hours_used=?, last_updated=? 
    WHERE phone=? AND course=?
    """, (
        user["hours_used"][course],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        phone,
        course
    ))
    
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "meet_link": meet_link,   # ✅ correct,
        "hours_used": user["hours_used"][course],
        "hours_remaining": max_hours - user["hours_used"][course]
    })

# -------------------- STUDENT STATUS --------------------

@app.route("/api/student-status")
def student_status():
    try:
        phone = session.get("phone")

        if not phone:
            return jsonify({"logged_in": False})

        user = get_user(phone) or {}

        # Seats
        seats = {}
        for course in seat_data:
            seats[course] = available_seats(course)

        # Discounts
        discounts = {}
        for course, d in seat_data.items():
            booked = d.get("booked", 0)
            discounts[course] = booked < 10

        return jsonify({
            "logged_in": True,
            "phone": phone,
            "name": user.get("name", ""),
            "demo_done": user.get("demo_done", {}),
            "enrolled": user.get("enrolled", {}),
            "hours_used": user.get("hours_used", {}),
            "max_hours": user.get("max_hours", {}),
            "available_seats": seats,
            "meet_link": meet_link,
            "is_admin": False,
            "discounts": discounts
        })

    except Exception as e:
        print("🔥 ERROR in student-status:", str(e))
        return jsonify({"logged_in": False})
# -------------------- TEACHER --------------------

@app.route("/teacher-login", methods=["GET", "POST"])
def teacher_login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username in teachers and teachers[username]["password"] == password:
            if not teachers[username].get("active", True):
                error = "Your account is disabled"
            else:
                session["teacher"] = username
                session["course"] = teachers[username]["course"]
                return redirect("/teacher-dashboard")
        else:
            error = "Invalid username or password"
    return render_template("teacher_login.html", error=error)

 

@app.route("/start-class", methods=["POST"])
def start_class():
    data = request.get_json()
    link = data.get("meetLink")

    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    teachers[username]["meet_link"] = link
    teachers[username]["active"] = True

    return jsonify({"status": "Class started"})

@app.route("/end-class", methods=["POST"])
def end_class():
    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    teachers[username]["active"] = False
    teachers[username]["meet_link"] = ""

    return jsonify({"status": "Class ended"})

@app.route("/get-teacher")
def get_teacher():
    course = request.args.get("course")

    for name, t in teachers.items():
        if t["course"] == course:
            return jsonify({"teacher": name})

    return jsonify({"teacher": None})
    
@app.route("/teacher-dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/teacher-login")

    username = session["teacher"]
    teacher = teachers.get(username)

    # 🔥 FIX: handle list properly
    if isinstance(feedback_db, list):
        feedbacks = [f for f in feedback_db if f.get("teacher") == username]
    else:
        feedbacks = feedback_db.get(username, [])

    # ⭐ avg rating calculation safe
    if feedbacks:
        avg_rating = round(
            sum(f.get("rating", 0) for f in feedbacks) / len(feedbacks), 2
        )
    else:
        avg_rating = 0

    return render_template(
        "teacher_Dashboard.html",
        teacher_name=username,
        course=teacher.get("course", ""),
        meet_link=teacher.get("meet_link", ""),
        feedbacks=feedbacks,
        avg_rating=avg_rating
    )

@app.route("/teacher-logout")
def teacher_logout():
    session.pop("teacher", None)
    return redirect("/teacher-login")

# -------------------- FEEDBACK --------------------

@app.route("/submit_feedback", methods=["POST"])
def submit_feedback():
    """Student submits feedback for a teacher."""
    phone = session.get("phone")
    data = request.get_json()

    teacher_name = data.get("teacher")
    course       = data.get("course")
    rating       = int(data.get("rating", 0))
    comment      = data.get("comment", "").strip()

    if not teacher_name or not course or not rating:
        return jsonify({"error": "Missing fields"}), 400

    entry = {
        "phone": phone or "anonymous",
        "course": course,
        "rating": rating,
        "comment": comment,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "approved": False
    }

    if teacher_name not in feedback_db:
        feedback_db[teacher_name] = []
    feedback_db[teacher_name].append(entry)

    # Persist to JSON
    _save_feedback()
    return jsonify({"status": "success"})


@app.route("/get_feedback")
def get_feedback():
    teacher = request.args.get("teacher")
    # If teacher is logged in, show their feedback
    if session.get("teacher"):
        teacher = teacher or session["teacher"]
        return jsonify(feedback_db.get(teacher, []))
    # Public: only approved
    if teacher:
        approved = [f for f in feedback_db.get(teacher, []) if f.get("approved")]
        return jsonify(approved)
    return jsonify([])


@app.route("/submit-teacher-feedback", methods=["POST"])
def submit_teacher_feedback():
    teacher  = request.form.get("teacher")
    rating   = int(request.form.get("rating", 0))
    comment  = request.form.get("comment", "").strip()
    course   = request.form.get("course", "")
    if teacher not in feedback_db:
        feedback_db[teacher] = []
    feedback_db[teacher].append({
        "rating": rating,
        "comment": comment,
        "course": course,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "approved": False
    })
    _save_feedback()
    return jsonify({"status": "submitted"})


def _save_feedback():
    try:
        with open("feedback.json", "w") as f:
            json.dump(feedback_db, f, indent=4)
    except Exception as e:
        print("Feedback save error:", e)


def _load_feedback():
    global feedback_db
    try:
        with open("feedback.json", "r") as f:
            feedback_db = json.load(f)
    except:
        feedback_db = {}

# -------------------- ADMIN --------------------

@app.route("/admin", methods=["GET", "POST"])
def admin():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == os.environ.get("ADMIN_PASSWORD", "admin123"):
            session["admin"] = True
            return redirect("/admin-dashboard")   # 🔥 CHANGE HERE
        else:
            error = "Wrong Password"
    return render_template("admin_login.html", error=error)

@app.route("/admin-dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template("admin_dashboard.html")
    

from werkzeug.utils import secure_filename

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return redirect("/admin-dashboard")

    message = ""

    if request.method == "POST":
        subject = request.form.get("subject")
        cls     = request.form.get("class")
        file    = request.files.get("file")

        if file:
            filename = secure_filename(file.filename)

            # 📁 create folder path
            folder_path = os.path.join(PDF_FOLDER, subject, cls)
            os.makedirs(folder_path, exist_ok=True)

            # 💾 save file
            file.save(os.path.join(folder_path, filename))

            message = "✅ File uploaded successfully!"

    return render_template("upload.html", message=message)


@app.route("/admin/students")
def admin_students():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    # ✅ FETCH FROM DB
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("SELECT phone, course, name, demo_done, enrolled, hours_used FROM students")
    rows = c.fetchall()

    students_list = []
    for r in rows:
        students_list.append({
            "phone": r[0],
            "course": r[1],
            "name": r[2],
            "demo_done": bool(r[3]),
            "enrolled": bool(r[4]),
            "hours_used": r[5]
        })

    conn.close()

    # ✅ RETURN RESPONSE
    return jsonify({
        "students": students_list,
        "seats": {
         course: {
        "total": d["total"],
        "available": available_seats(course),
        "booked": d["total"] - available_seats(course)
    }
    for course, d in seat_data.items()
}
    })

@app.route("/admin/students-view")
def students_view():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template("students.html")
    
@app.route("/admin/reset-demo", methods=["POST"])
def admin_reset_demo():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    # 🔥 extra protection (optional)
    if session.get("admin") != True:
        return jsonify({"error": "Access Denied"}), 403

    data = request.get_json()

    phone  = data.get("phone")
    course = data.get("course")

    if phone in demo_users:
        if course:
            demo_users[phone]["demo_done"].pop(course, None)
        else:
            demo_users[phone]["demo_done"] = {}

    return jsonify({"status": "reset"})


@app.route("/manage-feedback")
def manage_feedback():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template("manage_feedback.html")


@app.route("/admin_feedback")
def admin_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403
    # Flatten all teachers
    all_fb = []
    for teacher, fbs in feedback_db.items():
        for i, fb in enumerate(fbs):
            all_fb.append({**fb, "teacher": teacher, "index": i})
    return jsonify(all_fb)


@app.route("/approve_feedback", methods=["POST"])
def approve_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403
    data    = request.get_json()
    teacher = data.get("teacher")
    index   = data.get("index")
    if teacher in feedback_db and index is not None and index < len(feedback_db[teacher]):
        feedback_db[teacher][index]["approved"] = True
        _save_feedback()
    return jsonify({"status": "approved"})


@app.route("/delete_feedback", methods=["POST"])
def delete_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403
    data    = request.get_json()
    teacher = data.get("teacher")
    index   = data.get("index")
    if teacher in feedback_db and index is not None and index < len(feedback_db[teacher]):
        feedback_db[teacher].pop(index)
        _save_feedback()
    return jsonify({"status": "deleted"})

# -------------------- MATERIALS (PDF) --------------------

PDF_FOLDER = "rsc_download"
os.makedirs(PDF_FOLDER, exist_ok=True)

PRODUCTS = {
    "Linear Programming": {
        "title": "Linear Programming – Class 12",
        "file": "Linear Programming1_merged.pdf",
        "class": "12",
        "board": "CBSE",
        "price": 1,
        "status": "available",
        "paid": True,
        "sample": False,
        "pdf_path": "cbse/class12",
        "cover": "Linear Programming.png"
    }
}

try:
    with open("admin.json") as f:
        _keys = json.load(f)
    razorpay_client = razorpay.Client(auth=(_keys["razorpay_key"], _keys["razorpay_secret"]))
except:
    razorpay_client = None
    _keys = {"razorpay_key": "", "razorpay_secret": ""}


def check_access(key):
    data = session.get(key)
    if not isinstance(data, dict) or "expiry" not in data:
        return False
    try:
        expiry = datetime.fromisoformat(data["expiry"])
    except:
        return False
    if datetime.now() > expiry:
        session.pop(key, None)
        return False
    return True


@app.route("/materials")
def materials():
    board    = request.args.get("board")
    cls      = request.args.get("cls")
    open_id  = request.args.get("open") or request.args.get("product_id")

    access = {}
    for pid in PRODUCTS:
        view_key     = "view_" + pid
        download_key = "download_" + pid
        access[pid]  = {
            "view": check_access(view_key),
            "download": check_access(download_key)
        }

    expiry_time = None
    if open_id:
        product = PRODUCTS.get(open_id)
        if not product:
            abort(403)
        if cls and str(product["class"]) != str(cls):
            abort(403)
        if not access.get(open_id, {}).get("view"):
            abort(403)
        data = session.get("view_" + open_id)
        if data:
            expiry_time = data.get("expiry")

    session["access"] = access
    return render_template(
        "materials.html",
        active_board=board,
        active_class=cls,
        open=open_id,
        products=PRODUCTS,
        access=access,
        expiry_time=expiry_time
    )


@app.route("/secure_view/<product_id>")
def secure_view(product_id):
    if not check_access("view_" + product_id):
        return "Unauthorized", 403
    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid", 404
    return send_file(
        os.path.join(PDF_FOLDER, product["file"]),
        mimetype="application/pdf",
        as_attachment=False
    )


@app.route("/download/<product_id>")
def download(product_id):
    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product", 404
    if not check_access("download_" + product_id):
        return "Download access expired", 403
    return send_from_directory(PDF_FOLDER, product["file"], as_attachment=True)


@app.route("/pay")
def pay():
    product_id = request.args.get("product")
    mode       = request.args.get("mode")
    board      = request.args.get("board", "cbse")
    cls        = request.args.get("cls", "12")
    session.update({"last_board": board, "last_cls": cls,
                    "last_product": product_id, "last_mode": mode})
    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product", 404
    if not razorpay_client:
        return "Payment not configured", 500
    order = razorpay_client.order.create({
        "amount": int(product["price"] * 100),
        "currency": "INR",
        "payment_capture": 1
    })
    return render_template(
        "pay.html", product=product, order_id=order["id"],
        razorpay_key=_keys["razorpay_key"],
        board=board, cls=cls, product_id=product_id, mode=mode
    )


@app.route("/payment_success")
def payment_success():
    product_id = request.args.get("product")
    mode       = request.args.get("mode")
    board      = session.get("last_board", "cbse")
    cls        = session.get("last_cls", "12")

    if not product_id:
        return redirect(url_for("materials"))

    if mode == "view":
        session["view_" + product_id] = {
            "expiry": (datetime.now() + timedelta(hours=1)).isoformat()
        }
    elif mode == "download":
        session["download_" + product_id] = {
            "expiry": (datetime.now() + timedelta(hours=1)).isoformat()
        }

    # FIX: was timedelta(minutes=1) — too short, changed to 1 hour
    session.setdefault("access", {})[product_id] = {"view": True}

    # Save to CSV
    phone = session.get("phone", "")
    try:
        file = "payments.csv"
        write_header = not os.path.exists(file)
        with open(file, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["Date", "Phone", "Product", "Mode"])
            writer.writerow([
                datetime.now().strftime("%d-%m-%Y %H:%M"),
                phone, product_id, mode
            ])
    except Exception as e:
        print("CSV error:", e)

    return redirect(url_for("materials", board=board, cls=cls, paid=1))

# -------------------- GENERAL ROUTES --------------------

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/class")
def courses():
    return render_template("class.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        message = request.form["message"]

        body = f"""
New Enquiry:

Name: {name}
Email: {email}
Phone: {phone}
Message: {message}
"""

        msg = MIMEText(body)
        msg["Subject"] = "New Enquiry from Website - RSC"
        msg["From"] = "ranjithamstudycenter@gmail.com"
        msg["To"] = "ranjithamstudycenter@gmail.com"

        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(
                "ranjithamstudycenter@gmail.com",
                os.environ.get("EMAIL_PASS")   # ✅ correct
            )

            server.send_message(msg)
            server.quit()

            print("Mail sent successfully")

        except Exception as e:
            print("Error:", e)

        return render_template("contact.html", success=True)

    return render_template("contact.html", success=False)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(".", "sitemap.xml")


@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    response.cache_control.no_cache = True
    response.cache_control.must_revalidate = True
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# -------------------- STARTUP --------------------

if __name__ == "__main__":
    _load_feedback()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
