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

salary_db = []

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
        "active": True,
        "gpay": "7702616245"
    },
    "faculty2": {
        "password": "Faculty2@2026",
        "course": "cbse12",
        "meet_link": "",
        "active": True
    }
}

COURSE_TEACHERS = {

   "cbse9"  : "Balakumar",
   "cbse10" : "Balakumar",
   "cbse11" : "Balakumar",
   "cbse12" : "Balakumar",

   "engg1"  : "Balakumar",
   "engg2"  : "Balakumar",
   "engg3"  : "Balakumar",

   "control" : "Balakumar",
   "AGS"     : "Balakumar",
   "Maths"   : "Balakumar"

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
    "cbse9":  1,
    "cbse10": 300,
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

    user = {
        "name": "",
        "phone": phone,
        "demo_done": {},
        "enrolled": {},
        "hours_used": {},
        "max_hours": {},
    }

    # 🔥 ALWAYS LOAD FROM DB
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("SELECT * FROM students WHERE phone=?", (phone,))
    rows = c.fetchall()

    for r in rows:
        course = r[1]
        user["demo_done"][course] = bool(r[3])
        user["enrolled"][course] = bool(r[4])
        user["hours_used"][course] = r[5]
        user["max_hours"][course] = r[6]

    conn.close()

    return user


def available_seats(course):
    d = seat_data.get(course, {"total": 30, "booked": 0})
    return d["total"] - d["booked"]

# -------------------- AUTH: OTP --------------------

@app.route("/save-user", methods=["POST"])
def save_user():
    data = request.json
    phone = data.get("phone")

    session["phone"] = phone
    user = get_user(phone)

    # 🔥 INSERT BASE RECORD (if not exists)
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})

# -------------------- DEMO --------------------

@app.route("/api/check-demo")
def check_demo():
    phone = request.args.get("phone") 
    course = request.args.get("course")
    
    if not phone:
        return jsonify({"error": "Phone required"}), 401

    if not course:
        return jsonify({"error": "Course missing"}), 400
        
    user = get_user(phone)

    # 🔥 GET SAME LINK
    meet_link = get_active_meet_link(course)

     # 🔥 BLOCK HERE
    if user["demo_done"].get(course):
        return jsonify({
            "error": "Demo already completed",
            "demo_done": True
        }), 403

    return jsonify({
        "demo_done": False,
        "meet_link": meet_link
    })


@app.route("/api/demo-complete", methods=["POST"])
def demo_complete():
    data = request.json

    phone = data.get("phone") or session.get("phone")
    course = data.get("course")
    demo_stage = data.get("demo")  # 🔥 new
    
    if not phone:
        return jsonify({"error": "Unauthorized"}), 401
    
    if not course:
        return jsonify({"error": "Course missing"}), 400
        
    user = get_user(phone)
    # 🔥 DOUBLE PROTECTION
    if user["demo_done"].get(course):
        return jsonify({"error": "Already completed"}), 400

    user["demo_done"][course] = True

    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # 🔍 check existing record
    c.execute("SELECT demo_done FROM students WHERE phone=? AND course=?", (phone, course))
    row = c.fetchone()

    # =====================================================
    # 🔥 1. FREE DEMO CLICK → INSERT (NO)
    # =====================================================
    if demo_stage == "start":

        if row:
            # already exists → do nothing
            return jsonify({"status": "exists"})

        c.execute("""
        INSERT INTO students 
        (phone, course, name, demo_done, enrolled, hours_used, max_hours, payment_amount, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            phone,
            course,
            "",
            0,   # ❌ demo not completed
            0,
            0,
            0,
            0,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        conn.commit()
        conn.close()

        return jsonify({"status": "started"})

    # =====================================================
    # 🔥 2. DEMO COMPLETE → UPDATE (YES)
    # =====================================================
    else:

        if row:
            # already completed?
            if row[0] == 1:
                return jsonify({"error": "Already completed"}), 400

            # update to YES
            c.execute("""
            UPDATE students 
            SET demo_done = 1, last_updated = ?
            WHERE phone = ? AND course = ?
            """, (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                phone,
                course
            ))

        else:
            # row இல்லனா direct insert as completed
            c.execute("""
            INSERT INTO students 
            (phone, course, name, demo_done, enrolled, hours_used, max_hours, payment_amount, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                phone,
                course,
                "",
                1,   # ✅ completed
                0,
                0,
                0,
                0,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ))

        conn.commit()
        conn.close()

        return jsonify({"status": "completed"})


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
        1,   # demo done
        1,   # ✅ enrolled TRUE
        0,
        classes_per_month,
        amount,
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

        # =========================================
    # 🔥 FACULTY PAYMENT SPLIT
    # =========================================

    teacher = COURSE_TEACHERS.get(course, "Unknown")
    amount = price_per_hour.get(course, 0) * classes_per_month
    faculty_share = round(amount * 0.60, 2)
    admin_share   = round(amount * 0.40, 2)

    salary_db.append({

        "student" : user.get("name", "Student"),

        "course"  : course,
        
        "teacher" : teacher,

        "amount"  : amount,

        "faculty_share" : faculty_share,

        "admin_share"   : admin_share,

        "paid_to_faculty" : False,

        "completed": False,

        "class_count": 0,

        "month": datetime.now().strftime("%B"),
        "year": datetime.now().strftime("%Y"),

        "date" : str(datetime.now())

    })
    return jsonify({
        "status": "success",
        "enrolled": True,
        "hours_remaining": user["max_hours"][course]
    })

# -------------------- JOIN CLASS --------------------

@app.route("/api/join-class")
def join_class_api():

    phone = session.get("phone")
    if not phone:
        return jsonify({"error": "Not logged in"}), 401

    course = request.args.get("course")
    if not course:
        return jsonify({"error": "Course missing"}), 400

    user = get_user(phone)

    demo_done = user["demo_done"].get(course, False)
    enrolled  = user["enrolled"].get(course, False)

    # ❌ demo not done
    if not demo_done:
        return jsonify({"error": "Attend demo first"}), 403

    # ✅ enrolled users → check usage
    if enrolled:
        hours_used = user["hours_used"].get(course, 0)
        max_hours  = user["max_hours"].get(course, classes_per_month)

        if hours_used >= max_hours:

            # 🔥 reset enrollment
            user["enrolled"][course] = False
        
            return jsonify({
                "completed": True,
                "show_feedback": True,
                "error": "Plan completed. Please re-enroll."
            }), 403

       # 🔥 SAVE JOIN TIME ONLY
        conn = sqlite3.connect("students.db")
        c = conn.cursor()
        
        join_time = datetime.now().timestamp()
        
        # 🔥 add new column if needed later
        try:
            c.execute("""
            ALTER TABLE students
            ADD COLUMN join_time REAL
            """)
        except:
            pass
        
        c.execute("""
        UPDATE students
        SET join_time=?, last_updated=?
        WHERE phone=? AND course=?
        """, (
            join_time,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            phone,
            course
        ))
        
        conn.commit()
        conn.close()

    # 🔥 SAME LINK for demo + join
    meet_link = get_active_meet_link(course)

    if not meet_link:
        return jsonify({"error": "Class not started yet"}), 404

    return jsonify({
        "status": "ok",
        "meet_link": meet_link,
        "hours_used": user["hours_used"].get(course, 0),
        "hours_remaining": user["max_hours"].get(course, classes_per_month) - user["hours_used"].get(course, 0)
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

def get_active_meet_link(course):
    for t in teachers.values():
        if t["course"] == course and t["active"]:
            return t["meet_link"]
    return None

@app.route("/end-class", methods=["POST"])
def end_class():
    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    # 🔥 ATTENDANCE CALCULATION
    conn = sqlite3.connect("students.db")
    c = conn.cursor()
    
    course = teachers[username]["course"]
    
    c.execute("""
    SELECT phone, join_time, hours_used
    FROM students
    WHERE course=? AND enrolled=1
    """, (course,))
    
    rows = c.fetchall()
    
    for row in rows:
    
        phone = row[0]
        join_time = row[1]
        hours_used = row[2] or 0
    
        if join_time:
    
            attended_minutes = (
                datetime.now().timestamp() - join_time
            ) / 60
    
            # ✅ minimum 50 mins
            if attended_minutes >= 50:
    
                c.execute("""
                UPDATE students
                SET hours_used=?,
                    last_updated=?
                WHERE phone=? AND course=?
                """, (
                    hours_used + 1,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    phone,
                    course
                ))
                # 🔥 update salary class count
                for s in salary_db:
                
                    if s["course"] == course:
                
                        s["class_count"] += 1
                        if s["class_count"] >= classes_per_month:

                            s["completed"] = True

    conn.commit()
    conn.close()

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
   
    total_feedbacks = len(feedbacks)

    low_ratings = [
        f for f in feedbacks
        if f.get("rating", 0) < 3
    ]

    low_count = len(low_ratings)

    warning_msg = ""

    # ⚠️ WARNING AFTER 6 LOW FEEDBACKS
    if low_count >= 6 and total_feedbacks < 10:

        warning_msg = (
            "⚠️ Warning: Multiple low ratings detected. "
            "Improve teaching quality immediately."
        )

    # ❌ DEACTIVATE AFTER 10+ LOW FEEDBACKS
    if total_feedbacks >= 10 and avg_rating < 3:

        teachers[username]["active"] = False

        warning_msg = (
            "❌ Account temporarily deactivated due to "
            "continuous poor student feedback."
        )

        # =====================================
    # 🔥 FACULTY EARNINGS
    # =====================================

    teacher_salary = [

        s for s in salary_db
        if s.get("teacher") == username

    ]

    total_earnings = sum(
        s.get("faculty_share", 0)
        for s in teacher_salary
    )

    pending_salary = sum(

        s.get("faculty_share", 0)

        for s in teacher_salary

        if not s.get("paid_to_faculty")

    )

    paid_salary = sum(

        s.get("faculty_share", 0)

        for s in teacher_salary

        if s.get("paid_to_faculty")

    )
     # =========================
    # BASIC COUNTS
    # =========================

    total_courses = len(seat_data)

    active_classes = len([
        t for t in teachers.values()
        if t.get("active")
    ])

    total_faculties = len(teachers)

    # =========================
    # STUDENT COUNT
    # =========================

    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("""
    SELECT COUNT(DISTINCT phone)
    FROM students
    WHERE enrolled=1
    """)

    total_students = c.fetchone()[0]

    conn.close()

    # =========================
    # REVENUE
    # =========================

    monthly_revenue = 0
    salary_credited = 0
    

    # =========================
    # FACULTY SUMMARY
    # =========================

    summary = {}

    for s in salary_db:

        teacher = s["teacher"]

        if teacher not in summary:

            summary[teacher] = {

                "course": s["course"],
                "students": 0,
                "pending": 0,
                "paid": 0,
                "class_count": 0,
                "strength": seat_data.get(s["course"], {}).get("total", 30),
                "gpay": teachers[teacher].get("gpay", "Not Added"),
                "month": datetime.now().strftime("%B"),
                "year": datetime.now().strftime("%Y"),

            }

        summary[teacher]["students"] += 1
        summary[teacher]["class_count"] += s.get("class_count", 0)
        monthly_revenue += s["amount"]

        salary_credited += s["faculty_share"]

        if s["paid_to_faculty"]:

            summary[teacher]["paid"] += s["faculty_share"]

        else:

            summary[teacher]["pending"] += s["faculty_share"]
            pending_salary += s["faculty_share"]
            
    return render_template(
        "teacher_Dashboard.html",
        teacher_name=username,
        course=teacher.get("course", ""),
        meet_link=teacher.get("meet_link", ""),
        total_courses=total_courses,
        active_classes=active_classes,
        feedbacks=feedbacks,
        total_faculties=total_faculties,
        total_students=total_students,
        monthly_revenue=monthly_revenue,
        salary_credited=salary_credited,
        salary_records=teacher_salary,
        total_earnings=total_earnings,
        pending_salary=pending_salary,
        paid_salary=paid_salary,
        summary=summary,
        avg_rating=avg_rating
       
    )

@app.route("/mark-paid/<teacher>")
def mark_paid(teacher):

    if not session.get("admin"):
        return redirect("/admin")

    for s in salary_db:

        if s["teacher"] == teacher:

            s["paid_to_faculty"] = True

    return redirect("/admin-dashboard")
    
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

    selected_month = request.args.get("month", "")
    
    summary = {}
    months = []
        
    for s in salary_db:
    
        m = f"{s.get('month')} {s.get('year')}"
    
        if m not in months:
    
            months.append(m)

    if not selected_month and months:

        selected_month = months[-1]
        
    for s in salary_db:
        record_month = f"{s.get('month')} {s.get('year')}"
    
        if selected_month and record_month != selected_month:
            continue

        teacher = s["teacher"]

        if teacher not in summary:

            summary[teacher] = {

                "pending": 0,
                "paid": 0,
                "students": 0,
                "course": s["course"],
                "class_count": s.get("class_count", 0),

                "strength": seat_data.get(
                    s["course"], {}
                ).get("total", 30),

                "gpay": teachers[teacher].get(
                    "gpay",
                    "Not Added"
                ),

                "month": datetime.now().strftime("%B"),
                "year": datetime.now().strftime("%Y")
            }

        summary[teacher]["students"] += 1

        if s["paid_to_faculty"]:

            summary[teacher]["paid"] += s["faculty_share"]

        else:

            summary[teacher]["pending"] += s["faculty_share"]

    # 🔥 if no salary data yet
    if not summary:

        for teacher, t in teachers.items():

            summary[teacher] = {

                "pending": 0,
                "paid": 0,
                "students": 0,
                "course": t.get("course", "Not Assigned"),
                "class_count": 0,

                "strength": seat_data.get(
                    t.get("course", ""),
                    {}
                ).get("total", 30),

                "gpay": t.get("gpay", "Not Added"),

                "month": datetime.now().strftime("%B"),
                "year": datetime.now().strftime("%Y")
            }

    active_classes = 0

    for t in teachers.values():

        if t.get("active"):

            active_classes += 1

    return render_template(

        "admin_dashboard.html",

        summary=summary,
        teachers=teachers,
        active_classes=active_classes,
        salary_db=salary_db,
        months=months,
        selected_month=selected_month

    )

@app.route("/download-salary-pdf")
def download_salary_pdf():

    if not session.get("admin"):
        return redirect("/admin")

    month = request.args.get("month", "All Months")

    return f"""

    <h1>Salary PDF Download</h1>

    <p>Month: {month}</p>

    <p>PDF generation next step la add pannalam ✅</p>

    """

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
    phone = request.json.get("phone")
    course = request.json.get("course")
    
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # 🔥 UPDATE ALL ROWS
    c.execute("""
    UPDATE students
    SET demo_done=0, enrolled=0, hours_used=0
    WHERE phone=? AND course=?
    """,(phone,course))

    conn.commit()
    conn.close()

    return jsonify({"status": "reset"})

@app.route("/admin/delete-student", methods=["POST"])
def delete_student():
    data = request.json
    phone = data.get("phone")
    course = data.get("course")

    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("DELETE FROM students WHERE phone=? AND course=?", (phone, course))

    conn.commit()
    conn.close()

    return jsonify({"status": "deleted"})

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
