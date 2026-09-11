from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for, abort, jsonify, send_file
import uuid
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
from openai import OpenAI
from email.mime.text import MIMEText
from datetime import datetime, timedelta

from email.message import EmailMessage
from PyPDF2 import PdfReader



def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("""
    
    CREATE TABLE IF NOT EXISTS students (

        name TEXT,
        phone TEXT,
        course TEXT,
        otp_verified INTEGER DEFAULT 0,
        demo_allowed INTEGER DEFAULT 0,
        demo_done INTEGER DEFAULT 0,
        enrolled INTEGER DEFAULT 0,
        hours_used INTEGER DEFAULT 0,
        max_hours INTEGER DEFAULT 0,
        payment_amount INTEGER DEFAULT 0,
        last_updated TEXT,
        PRIMARY KEY(phone, course)
    )
    """)
    try:
        c.execute("""
        ALTER TABLE students
        ADD COLUMN join_time REAL
        """)
    except:
        pass

    try:
        c.execute("""
        ALTER TABLE students
        ADD COLUMN demo_allowed INTEGER DEFAULT 0
        """)
    except:
        pass

    try:
        c.execute("""
        ALTER TABLE students
        ADD COLUMN demo_done INTEGER DEFAULT 0
        """)
    except:
        pass
        
     # 🔥 ADD THIS NEW TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS class_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT,
        meet_link TEXT,
        updated_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS syllabi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        board TEXT,
        class_name TEXT,
        subject TEXT,
        filename TEXT,
        syllabus_text TEXT,
        uploaded_at TEXT
    )
    """)

    # =====================================================
    # AI LEARNING - TEST ATTEMPTS
    # =====================================================

    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    
        phone TEXT,
    
        board TEXT,
        class_name TEXT,
        subject TEXT,
        topic TEXT,
        subtopic TEXT,
    
        difficulty TEXT,
    
        total_questions INTEGER DEFAULT 25,
        total_marks INTEGER DEFAULT 50,
    
        correct_answers INTEGER DEFAULT 0,
        incorrect_answers INTEGER DEFAULT 0,
    
        score INTEGER DEFAULT 0,
        percentage REAL DEFAULT 0,
    
        question_data TEXT,
    
        completed_at TEXT
    )
    """)

    # =====================================================
    # AI LEARNING - TOPIC PERFORMANCE
    # =====================================================
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_topic_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    
        phone TEXT,
    
        board TEXT,
        class_name TEXT,
        subject TEXT,
        topic TEXT,
        subtopic TEXT,
    
        difficulty TEXT,
    
        total_questions INTEGER DEFAULT 0,
        correct_answers INTEGER DEFAULT 0,
        incorrect_answers INTEGER DEFAULT 0,
    
        score INTEGER DEFAULT 0,
        percentage REAL DEFAULT 0,
    
        last_attempt TEXT
    )
    """)

    # =====================================================
    # AI QUESTION BANK
    # =====================================================
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_question_bank (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    
        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,
    
        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,
    
        mode TEXT NOT NULL,
        difficulty TEXT NOT NULL,
    
        test_number INTEGER DEFAULT 0,
    
        question TEXT NOT NULL,
        options TEXT NOT NULL,
        correct_answer INTEGER NOT NULL,
    
        explanation TEXT DEFAULT '',
        hint TEXT DEFAULT '',
    
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # =====================================================
    # AI LEARNING - SYLLABUS TOPIC CACHE
    # =====================================================
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_syllabus_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    
        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,
    
        topics_json TEXT NOT NULL,
    
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
        UNIQUE(board, class_name, subject)
    )
    """)
    # =====================================================
    # AI EXAM SESSIONS
    # =====================================================
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_sessions (
    
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT,
        
        board TEXT,
        class_name TEXT,
        subject TEXT,
    
        topic TEXT,
        subtopic TEXT,
    
        difficulty TEXT,
    
        mode TEXT,
    
        test_number INTEGER DEFAULT 0,
    
        total_questions INTEGER DEFAULT 25,
        total_marks INTEGER DEFAULT 50,
    
        question_ids TEXT,
    
        answers TEXT,
    
        current_question INTEGER DEFAULT 0,
    
        status TEXT DEFAULT 'in_progress',
    
        started_at TEXT,
    
        submitted_at TEXT,
    
        score INTEGER DEFAULT 0,
    
        correct_answers INTEGER DEFAULT 0,
    
        incorrect_answers INTEGER DEFAULT 0,
    
        unanswered INTEGER DEFAULT 0,
    
        percentage REAL DEFAULT 0
    
    )
    """)

    # =====================================================
    # AI LEARNING - ANONYMOUS PRACTICE ID
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE ai_attempts
            ADD COLUMN practice_id TEXT
        """)
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("""
            ALTER TABLE ai_topic_performance
            ADD COLUMN practice_id TEXT
        """)
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

init_db()

# -------------------- APP INIT --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    "Balakumar9": {
        "password": "M10@2026",
        "course": "cbse9",
        "meet_link": "",
        "active": True,
        "class_live": False,
        "gpay": "7702616245"
    },
    "Balakumar10": {
        "password": "M10@2026",
        "course": "cbse10",
        "meet_link": "",
        "active": True,
        "class_live": False,
        "gpay": "7702616245"
    },
    "Balakumar12": {
        "password": "M12@2026",
        "course": "cbse12",
        "meet_link": "",
        "active": True,
        "class_live": False,
        "gpay": "7702616245"
    },
    "faculty1": {
        "password": "",
        "course": "cbse12",
        "meet_link": "",
        "enabled": False,
        "class_live": False,
        "gpay": ""
    },
    "faculty2": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False,
            "gpay": ""
    },
    "faculty3": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False,
            "gpay": ""
    },
    "faculty4": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False,
            "gpay": ""
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
# =====================================================
# ANONYMOUS PRACTICE ID
# =====================================================

def get_practice_id():
    practice_id = session.get("practice_id")

    if not practice_id:
        practice_id = str(uuid.uuid4())
        session["practice_id"] = practice_id

    return practice_id
    
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
        course = r[2]
        user["demo_done"][course] = bool(r[5])
        user["enrolled"][course] = bool(r[6])
        user["hours_used"][course] = r[7]
        user["max_hours"][course] = r[8]

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
    name  = data.get("name")
    course = data.get("course")

    session["phone"] = phone
    user = get_user(phone)

    # 🔥 INSERT BASE RECORD (if not exists)
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("""
    INSERT OR REPLACE INTO students
    (
        name,
        phone,
        course,
        otp_verified,
        demo_allowed,
        demo_done,
        enrolled,
        hours_used,
        max_hours,
        payment_amount,
        last_updated
     
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        phone,
        course,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
       
    ))

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})

# -------------------- DEMO --------------------

@app.route("/api/check-demo")
def check_demo():

    phone  = request.args.get("phone")
    course = request.args.get("course")

    # ✅ COURSE CHECK
    if not course:
        return jsonify({
            "error": "Course missing"
        }), 400

    # ✅ PHONE CHECK
    if not phone:
        return jsonify({"error": "Phone required"}), 401

    user = get_user(phone)

    # ✅ GET LIVE MEET LINK
    meet_link = get_active_meet_link(course)

    # ✅ IF DEMO ALREADY COMPLETED
    # still allow reopening link
    if user["demo_done"].get(course):

        return jsonify({
            "error": "Demo already completed",
            "demo_done": True,
            "meet_link": meet_link
        })

    # ✅ NORMAL RESPONSE
    return jsonify({
        "demo_done": False,
        "meet_link": meet_link,
        
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

    # =================================
    # DB CHECK
    # =================================

    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    c.execute("""
    SELECT otp_verified, demo_allowed, demo_done
    FROM students
    WHERE phone=? AND course=?
    """, (phone, course))

    row = c.fetchone()

    # ❌ no record
    if not row:
        conn.close()
        return jsonify({
            "error": "Register first"
        }), 403

    # ❌ OTP not verified
    if row[0] != 1:
        conn.close()
        return jsonify({
            "error": "OTP verification required"
        }), 403

    # ❌ demo not allowed
    if row[1] != 1:
        conn.close()
        return jsonify({
            "error": "Attend free demo registration first"
        }), 403

    # =================================
    # USER STATUS
    # =================================

    demo_done = user["demo_done"].get(course, False)
    enrolled  = user["enrolled"].get(course, False)

    
    
    otp_verified = row[0]

    demo_allowed = row[1]
    
    # 🔥 allow:
    # 1 verified demo student
    # 2 enrolled student
    
    allow_join = (
    (
    otp_verified==1
    and
    demo_allowed==1
    )
    or
    enrolled
    )
    
    if not allow_join:
    
        conn.close()
    
        return jsonify({
    
          "error":
          "Join not allowed"
    
        }),403

    # =================================
    # ENROLLED HOURS CHECK
    # =================================

    if enrolled:

        hours_used = user["hours_used"].get(course, 0)
        max_hours  = user["max_hours"].get(course, classes_per_month)

        if hours_used >= max_hours:

            conn.close()

            return jsonify({
                "completed": True,
                "show_feedback": True,
                "error": "Plan completed. Please re-enroll."
            }), 403

    # =================================
    # SAVE JOIN TIME
    # =================================

    join_time = datetime.now().timestamp()

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

    # =================================
    # LIVE CLASS
    # =================================

    meet_link = get_active_meet_link(course)

    if not meet_link:
        return jsonify({
            "error": "Class not started yet"
        }), 404

    return jsonify({
        "status": "ok",
        "meet_link": meet_link,
        "redirect_url": f"/join-live/{course}",
        "hours_used": user["hours_used"].get(course, 0),
        "hours_remaining": user["max_hours"].get(course, classes_per_month)
                             - user["hours_used"].get(course, 0)
    })
    
@app.route("/join-live/<course>")
def join_live(course):

    phone = session.get("phone")

    if not phone:
        return "Unauthorized"

    meet_link = get_active_meet_link(course)

    if not meet_link:
        return "Class not started"

    return redirect(meet_link)
    
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
            "is_demo_user": user.get("demo_done", {}),
            "is_enrolled_user": user.get("enrolled", {}),
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

    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    meet_link = request.json.get("meetLink")

    if not meet_link:
        return jsonify({"error": "Meet link missing"}), 400

    course = teachers[username]["course"]

    try:

        # =====================================
        # 🔥 SAVE LIVE CLASS TO DB
        # =====================================

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        # 🔥 create table if not exists
        c.execute("""
        CREATE TABLE IF NOT EXISTS live_classes (
            course TEXT PRIMARY KEY,
            meet_link TEXT,
            live INTEGER DEFAULT 0
        )
        """)

        # 🔥 insert or update
        c.execute("""
        INSERT OR REPLACE INTO live_classes
        (course, meet_link, live)
        VALUES (?, ?, 1)
        """, (
            course,
            meet_link
        ))

        conn.commit()
        conn.close()

        # =====================================
        # 🔥 MEMORY UPDATE
        # =====================================

        teachers[username]["class_live"] = True
        teachers[username]["meet_link"] = meet_link

        return jsonify({
            "status": "Class started",
            "success": True,
            "live": True,
            "meet_link": meet_link
        })

    except Exception as e:

        print("START CLASS ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


def get_active_meet_link(course):

    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # 🔥 SAFETY TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS live_classes (
        course TEXT PRIMARY KEY,
        meet_link TEXT,
        live INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    SELECT meet_link
    FROM live_classes
    WHERE course=?
    AND live=1
    """, (course,))

    row = c.fetchone()

    conn.commit()
    conn.close()

    if row:
        return row[0]

    return None
    

@app.route("/api/class-status")
def class_status():

    course = request.args.get("course")

    if not course:

        return jsonify({
            "live": False,
            "meet_link": ""
        })

    meet_link = get_active_meet_link(course)

    return jsonify({

        "live": bool(meet_link),

        "meet_link": meet_link or ""

    })

@app.route("/end-class", methods=["POST"])
def end_class():

    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    try:

        course = teachers[username]["course"]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        # 🔥 GET ENROLLED STUDENTS
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

                    # 🔥 salary update
                    for s in salary_db:

                        if s["course"] == course:

                            s["class_count"] += 1

                            if "classes_per_month" in s:

                                if s["class_count"] >= s["classes_per_month"]:
                                    s["completed"] = True

        # 🔥 VERY IMPORTANT
        # reset join time
        c.execute("""
        UPDATE students
        SET join_time=NULL
        WHERE course=?
        """, (course,))

        conn.commit()
        conn.close()

        # 🔥 CLASS OFF
        teachers[username]["class_live"] = False
        teachers[username]["meet_link"] = ""

        # 🔥 UPDATE LIVE CLASS TABLE
        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        c.execute("""
        UPDATE live_classes
        SET live=0,
            meet_link=''
        WHERE course=?
        """, (course,))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "live": False
        })

    except Exception as e:

        print("END CLASS ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500
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
    course = teacher.get("course", "")

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
    
    # =========================================
    # 🔥 WAITING DEMO STUDENTS
    # =========================================
    
    conn = sqlite3.connect("students.db")
    c = conn.cursor()
    
    c.execute("""
    SELECT name, phone, course,
           otp_verified,
           demo_allowed,
           demo_done
    FROM students
    WHERE course=?
    AND otp_verified=1
    AND demo_allowed=1
    AND demo_done=0
    """, (course,))
    
    rows = c.fetchall()
    
    waiting_students = []
    
    for r in rows:
    
        waiting_students.append({
    
            "name": r[0],
            "phone": r[1],
            "course": r[2],
    
            "otp_verified": bool(r[3]),
            "demo_allowed": bool(r[4]),
            "demo_done": bool(r[5])
    
        })
    conn.close()
    
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
    SELECT *
    FROM students
    WHERE course=?
    """, (teacher.get("course"),))
    
    students = c.fetchall()
    
    conn.close()
    
    return render_template(
        "teacher_Dashboard.html",
        teacher_name=username,
        course=teacher.get("course", ""),
        meet_link=teacher.get("meet_link", ""),
        total_courses=total_courses,
        active_classes=active_classes,
        feedbacks=feedbacks,
        students=students,
        total_faculties=total_faculties,
        total_students=total_students,
        waiting_students=waiting_students,
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

SYLLABUS_FOLDER = "syllabus_files"
os.makedirs(SYLLABUS_FOLDER, exist_ok=True)

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

# =====================================================
# ADMIN - SYLLABUS UPLOAD
# =====================================================

@app.route("/admin/syllabus", methods=["GET", "POST"])
def admin_syllabus():

    if not session.get("admin"):
        return redirect("/admin")

    message = ""
    error = ""

    if request.method == "POST":

        board = request.form.get("board", "").strip()
        class_name = request.form.get("class_name", "").strip()
        subject = request.form.get("subject", "").strip()
        file = request.files.get("syllabus_file")

        if not board or not class_name or not subject or not file:
            error = "Please fill all fields and select a syllabus PDF."

        elif not file.filename.lower().endswith(".pdf"):
            error = "Only PDF syllabus files are supported."

        else:

            try:

                filename = secure_filename(file.filename)

                # Read syllabus PDF
                reader = PdfReader(file.stream)

                pages = []

                for page in reader.pages:

                    page_text = page.extract_text() or ""

                    pages.append(page_text)

                syllabus_text = "\n".join(pages).strip()

                if not syllabus_text:

                    error = (
                        "Could not extract text from this PDF. "
                        "Please upload a text-based PDF."
                    )

                else:

                    # Create syllabus folder
                    folder = os.path.join(
                        SYLLABUS_FOLDER,
                        secure_filename(board),
                        secure_filename(class_name),
                        secure_filename(subject)
                    )

                    os.makedirs(folder, exist_ok=True)

                    file.stream.seek(0)

                    file.save(
                        os.path.join(folder, filename)
                    )

                    # Save syllabus information in database
                    conn = sqlite3.connect("students.db")

                    c = conn.cursor()

                    # Remove previous syllabus
                    # for same board/class/subject
                    c.execute("""
                    DELETE FROM syllabi
                    WHERE board=?
                    AND class_name=?
                    AND subject=?
                    """, (
                        board,
                        class_name,
                        subject
                    ))

                    # Insert new syllabus
                    c.execute("""
                    INSERT INTO syllabi
                    (
                        board,
                        class_name,
                        subject,
                        filename,
                        syllabus_text,
                        uploaded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        board,
                        class_name,
                        subject,
                        filename,
                        syllabus_text,
                        datetime.now().strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    ))

                    c.execute("""
                        DELETE FROM ai_syllabus_topics
                        WHERE board=?
                        AND class_name=?
                        AND subject=?
                    """, (
                        board,
                        class_name,
                        subject
                    ))
                    
                    conn.commit()

                    conn.close()

                    message = (
                        "✅ Syllabus uploaded successfully. "
                        "AI can now use this syllabus."
                    )

            except Exception as e:

                print("SYLLABUS UPLOAD ERROR:", e)

                error = (
                    "Syllabus upload failed: " +
                    str(e)
                )

    # Get uploaded syllabi
    conn = sqlite3.connect("students.db")

    conn.row_factory = sqlite3.Row

    c = conn.cursor()

    c.execute("""
    SELECT
        id,
        board,
        class_name,
        subject,
        filename,
        uploaded_at
    FROM syllabi
    ORDER BY id DESC
    """)

    syllabi = [
        dict(row)
        for row in c.fetchall()
    ]

    conn.close()

    return render_template(
        "syllabus_upload.html",
        message=message,
        error=error,
        syllabi=syllabi
    )

# =====================================================
# ADMIN - DELETE SYLLABUS
# =====================================================

@app.route("/admin/delete-syllabus/<int:syllabus_id>", methods=["POST"])
def delete_syllabus(syllabus_id):

    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    try:

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        # Get syllabus details
        c.execute("""
        SELECT board, class_name, subject, filename
        FROM syllabi
        WHERE id=?
        """, (syllabus_id,))

        row = c.fetchone()

        if not row:
            conn.close()
            return jsonify({
                "error": "Syllabus not found"
            }), 404

        board, class_name, subject, filename = row

        # Delete database record
        c.execute("""
        DELETE FROM syllabi
        WHERE id=?
        """, (syllabus_id,))

        conn.commit()
        conn.close()

        # Delete physical PDF file
        file_path = os.path.join(
            SYLLABUS_FOLDER,
            secure_filename(board),
            secure_filename(class_name),
            secure_filename(subject),
            filename
        )

        if os.path.exists(file_path):
            os.remove(file_path)

        return jsonify({
            "success": True,
            "message": "Syllabus deleted successfully"
        })

    except Exception as e:

        print("DELETE SYLLABUS ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500
        
@app.route("/admin/students")
def admin_students():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    # ✅ FETCH FROM DB
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT name, phone, course, otp_verified, demo_allowed, demo_done, enrolled, hours_used FROM students")
    rows = c.fetchall()

    students_list = []
    for r in rows:
        students_list.append({
            "name": r[0],
            "phone": r[1],
            "course": r[2],
            "otp_verified": bool(r[3]),
            "demo_allowed": bool(r[4]),
            "demo_done": bool(r[5]),
            "enrolled": bool(r[6]),
            "hours_used": r[7]

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

# -------------------- AI LEARNING --------------------

@app.route("/ai_learning")
def ai_learning():
    return render_template("ai_learning.html")
    
@app.route("/courses")
def courses():

    phone = session.get("phone")

    student = {
        "demo_done": {},
        "enrolled": {}
    }

    if phone:
        student = get_user(phone)

    return render_template(
        "class.html",
        student=student
    )


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
# =====================================================
# AI LEARNING - AI QUESTION GENERATOR
# =====================================================
# =====================================================
# AI LEARNING - GET AVAILABLE SYLLABUS OPTIONS
# =====================================================

@app.route("/api/ai-learning-options")
def ai_learning_options():

    try:

        conn = sqlite3.connect("students.db")
        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        c.execute("""
        SELECT DISTINCT
            board,
            class_name,
            subject
        FROM syllabi
        ORDER BY board, class_name, subject
        """)

        rows = c.fetchall()

        conn.close()

        options = []

        for row in rows:

            options.append({
                "board": row["board"],
                "class_name": row["class_name"],
                "subject": row["subject"]
            })

        return jsonify({
            "success": True,
            "options": options
        })

    except Exception as e:

        print(
            "AI LEARNING OPTIONS ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
# =====================================================
# AI LEARNING - AI GENERATED CHAPTERS + SUBTOPICS
# =====================================================

@app.route("/api/ai-learning-topics", methods=["POST"])
def ai_learning_topics():

    conn = None

    try:

        # =================================================
        # 1. GET REQUEST DATA
        # =================================================

        data = request.get_json() or {}

        board = str(
            data.get("board", "")
        ).strip()

        class_name = str(
            data.get("class_name", "")
        ).strip()

        subject = str(
            data.get("subject", "")
        ).strip()


        # =================================================
        # 2. VALIDATION
        # =================================================

        if not board or not class_name or not subject:

            return jsonify({
                "success": False,
                "error":
                    "Board, Class and Subject are required."
            }), 400


        # =================================================
        # 3. DATABASE CONNECTION
        # =================================================

        conn = sqlite3.connect(
            "students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()


        # =================================================
        # 4. MAKE SURE TOPIC CACHE TABLE EXISTS
        # =================================================

        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_syllabus_topics (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                board TEXT NOT NULL,

                class_name TEXT NOT NULL,

                subject TEXT NOT NULL,

                topics_json TEXT NOT NULL,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(board, class_name, subject)

            )
        """)

        conn.commit()


        # =================================================
        # 5. CHECK EXISTING AI GENERATED TOPICS
        # =================================================

        c.execute("""
            SELECT topics_json
            FROM ai_syllabus_topics
            WHERE board=?
            AND class_name=?
            AND subject=?
            ORDER BY id DESC
            LIMIT 1
        """, (
            board,
            class_name,
            subject
        ))

        cached_row = c.fetchone()


        # =================================================
        # 6. IF TOPICS ALREADY EXIST
        #    → DO NOT CALL AI AGAIN
        # =================================================

        if cached_row:

            try:

                topic_data = json.loads(
                    cached_row["topics_json"]
                )

                topics = topic_data.get(
                    "topics",
                    []
                )

                valid_topics = []

                if isinstance(topics, list):

                    for item in topics:

                        if not isinstance(
                            item,
                            dict
                        ):
                            continue

                        topic_name = str(
                            item.get(
                                "topic",
                                ""
                            )
                        ).strip()

                        subtopics = item.get(
                            "subtopics",
                            []
                        )

                        if not topic_name:
                            continue

                        if not isinstance(
                            subtopics,
                            list
                        ):
                            subtopics = []

                        clean_subtopics = []

                        for subtopic in subtopics:

                            subtopic = str(
                                subtopic
                            ).strip()

                            if subtopic:

                                clean_subtopics.append(
                                    subtopic
                                )

                        valid_topics.append({

                            "topic":
                                topic_name,

                            "subtopics":
                                clean_subtopics

                        })


                if valid_topics:

                    print(
                        "AI TOPICS: DATABASE CACHE USED"
                    )

                    conn.close()
                    conn = None

                    return jsonify({

                        "success": True,

                        "source":
                            "database",

                        "ai_generated":
                            True,

                        "topics":
                            valid_topics

                    })


            except Exception as e:

                print(
                    "TOPIC CACHE JSON ERROR:",
                    e
                )


        # =================================================
        # 7. CACHE NOT FOUND
        #    → NOW AI WILL GENERATE TOPICS
        # =================================================

        print(
            "AI TOPICS: CACHE NOT FOUND"
        )

        print(
            "AI TOPICS: STARTING OPENAI GENERATION"
        )


        # =================================================
        # 8. GET UPLOADED SYLLABUS
        # =================================================

        c.execute("""
            SELECT syllabus_text
            FROM syllabi
            WHERE board=?
            AND class_name=?
            AND subject=?
            ORDER BY id DESC
            LIMIT 1
        """, (
            board,
            class_name,
            subject
        ))

        syllabus_row = c.fetchone()


        if not syllabus_row:

            conn.close()
            conn = None

            return jsonify({

                "success": False,

                "error":
                    "Syllabus not found for the selected Board, Class and Subject."

            }), 404


        syllabus_text = (
            syllabus_row["syllabus_text"]
            or ""
        )


        if not syllabus_text.strip():

            conn.close()
            conn = None

            return jsonify({

                "success": False,

                "error":
                    "Uploaded syllabus is empty."

            }), 400


        # =================================================
        # 9. LIMIT SYLLABUS SIZE
        # =================================================

        syllabus_context = (
            syllabus_text[:10000]
        )


        # =================================================
        # 10. AI PROMPT
        # =================================================

        prompt = f"""

You are an expert school curriculum specialist,
Mathematics teacher and syllabus analyst.

Your task is to analyse the supplied official
school syllabus and generate a COMPLETE and
STRUCTURED list of Chapters/Topics and their
Subtopics for an online learning platform.

-----------------------------------------
SELECTED ACADEMIC INFORMATION
-----------------------------------------

Board:
{board}

Class:
{class_name}

Subject:
{subject}

-----------------------------------------
MAIN OBJECTIVE
-----------------------------------------

Read the supplied syllabus carefully.

Extract ALL relevant chapters, units,
topics and subtopics that students should
study for the selected Board, Class and Subject.

The output will be used directly in a student
learning website.

Therefore the chapter structure must be:

Chapter / Topic
    ↓
Subtopics

-----------------------------------------
IMPORTANT RULES
-----------------------------------------

1. Use the supplied syllabus as the PRIMARY
   academic source.

2. Include ALL major chapters/topics that
   are present in the syllabus.

3. Do NOT unnecessarily omit chapters.

4. Do NOT create unrelated chapters.

5. Do NOT introduce concepts that are clearly
   outside the supplied syllabus.

6. Preserve the academic meaning and terminology
   of the syllabus.

7. Break large chapters into meaningful
   student-friendly subtopics.

8. If a chapter contains multiple concepts,
   include each important concept as a separate
   subtopic.

9. Do not create meaningless or duplicate
   subtopics.

10. Avoid duplicate chapter names.

11. Avoid duplicate subtopic names within
    the same chapter.

12. The structure should be comprehensive enough
    for students to practise individual concepts.

13. For Mathematics, include important areas such as
    definitions, theorems, formulas, methods,
    applications and problem-solving concepts
    whenever they are explicitly supported by
    the syllabus.

14. Do not generate questions.
    ONLY generate Chapters and Subtopics.

15. Return ONLY valid JSON.

16. Do NOT use Markdown.

17. Do NOT use code fences.

-----------------------------------------
REQUIRED JSON FORMAT
-----------------------------------------

{{
    "topics": [
        {{
            "topic": "Chapter Name",
            "subtopics": [
                "Subtopic 1",
                "Subtopic 2",
                "Subtopic 3"
            ]
        }}
    ]
}}

-----------------------------------------
SUPPLIED SYLLABUS
-----------------------------------------

{syllabus_context}

-----------------------------------------
FINAL INSTRUCTION
-----------------------------------------

Analyse the complete supplied syllabus and
return the most complete accurate chapter and
subtopic structure possible.

Return ONLY the JSON object.
"""


        # =================================================
        # 11. CLOSE DB BEFORE AI CALL
        # =================================================

        conn.close()
        conn = None


        # =================================================
        # 12. OPENAI AI GENERATION
        # =================================================

        print(
            "AI TOPICS: CALLING GPT-5.6-LUNA"
        )

        response = client.responses.create(

            model="gpt-5.6-luna",

            input=prompt,
            max_output_tokens=1500

        )


        result = (
            response.output_text
            .strip()
        )


        print(
            "AI TOPICS: RESPONSE RECEIVED"
        )


        # =================================================
        # 13. REMOVE CODE FENCES IF ANY
        # =================================================

        if result.startswith("```"):

            result = result.replace(
                "```json",
                ""
            )

            result = result.replace(
                "```",
                ""
            )

            result = result.strip()


        # =================================================
        # 14. PARSE JSON
        # =================================================

        topic_data = json.loads(
            result
        )


        topics = topic_data.get(
            "topics",
            []
        )


        # =================================================
        # 15. VALIDATE AI RESPONSE
        # =================================================

        if not isinstance(
            topics,
            list
        ):

            raise ValueError(
                "AI returned invalid topics structure."
            )


        valid_topics = []


        for item in topics:

            if not isinstance(
                item,
                dict
            ):
                continue


            topic_name = str(
                item.get(
                    "topic",
                    ""
                )
            ).strip()


            subtopics = item.get(
                "subtopics",
                []
            )


            if not topic_name:
                continue


            if not isinstance(
                subtopics,
                list
            ):

                subtopics = []


            clean_subtopics = []


            for subtopic in subtopics:

                subtopic = str(
                    subtopic
                ).strip()


                if not subtopic:
                    continue


                if subtopic.lower() in [
                    x.lower()
                    for x in clean_subtopics
                ]:
                    continue


                clean_subtopics.append(
                    subtopic
                )


            valid_topics.append({

                "topic":
                    topic_name,

                "subtopics":
                    clean_subtopics

            })


        # =================================================
        # 16. FINAL VALIDATION
        # =================================================

        if len(valid_topics) == 0:

            raise ValueError(
                "AI did not generate any valid chapters."
            )


        # =================================================
        # 17. SAVE AI GENERATED TOPICS
        # =================================================

        conn = sqlite3.connect(
            "students.db"
        )

        c = conn.cursor()


        # Remove old cache if any
        c.execute("""
            DELETE FROM ai_syllabus_topics
            WHERE board=?
            AND class_name=?
            AND subject=?
        """, (
            board,
            class_name,
            subject
        ))


        # Insert NEW AI generated topics
        c.execute("""
            INSERT INTO ai_syllabus_topics
            (
                board,
                class_name,
                subject,
                topics_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            board,
            class_name,
            subject,

            json.dumps(
                {
                    "topics":
                        valid_topics
                },
                ensure_ascii=False
            ),

            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ))


        conn.commit()


        print(
            "AI TOPICS: SAVED TO DATABASE"
        )

        print(
            "AI TOPICS: CHAPTER COUNT =",
            len(valid_topics)
        )


        # =================================================
        # 18. CLOSE DATABASE
        # =================================================

        conn.close()
        conn = None


        # =================================================
        # 19. RETURN AI GENERATED TOPICS
        # =================================================

        return jsonify({

            "success": True,

            "source":
                "openai",

            "ai_generated":
                True,

            "topics":
                valid_topics

        })


    # =====================================================
    # RATE LIMIT / OPENAI ERROR
    # =====================================================

    except Exception as e:

        print("========================================")
        print("AI TOPICS ERROR")
        print("ERROR TYPE:", type(e).__name__)
        print("ERROR DETAILS:", str(e))
        print("========================================")

        if conn is not None:

            try:

                conn.close()

            except:

                pass


        error_text = str(e)


        # -----------------------------------------
        # RATE LIMIT
        # -----------------------------------------

       if (
            "429" in error_text
            or
            "rate limit" in error_text.lower()
            or
            "tokens per min" in error_text.lower()
        ):
            return jsonify({
                "success": False,
                "error": "OPENAI ERROR: " + error_text
            }), 429

        # -----------------------------------------
        # GENERAL ERROR
        # -----------------------------------------

        return jsonify({

            "success": False,

            "error":
                "AI topic generation failed: "
                + error_text

        }), 500
        

        
@app.route("/api/ai-question", methods=["POST"])
def ai_question():

    try:

        data = request.get_json() or {}

        board = data.get("board", "").strip()
        subject = data.get("subject", "Mathematics").strip()
        class_name = data.get("class_name", "Class 10").strip()
        topic = data.get("topic", "").strip()
        subtopic = data.get("subtopic", "").strip()
        difficulty = data.get("difficulty", "easy").strip().lower()

        # -----------------------------------------
        # VALIDATION
        # -----------------------------------------

        if not board:
            return jsonify({
                "success": False,
                "error": "Board is required."
            }), 400

        if not subject:
            return jsonify({
                "success": False,
                "error": "Subject is required."
            }), 400

        if not topic:
            return jsonify({
                "success": False,
                "error": "Topic is required."
            }), 400

        if not subtopic:
            return jsonify({
                "success": False,
                "error": "Subtopic is required."
            }), 400

        if difficulty not in ["easy", "medium", "hard"]:
            return jsonify({
                "success": False,
                "error": "Invalid difficulty."
            }), 400

        # -----------------------------------------
        # GET SELECTED SYLLABUS
        # -----------------------------------------

        conn = sqlite3.connect("students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
        SELECT syllabus_text
        FROM syllabi
        WHERE board=?
        AND class_name=?
        AND subject=?
        ORDER BY id DESC
        LIMIT 1
        """, (
            board,
            class_name,
            subject
        ))

        row = c.fetchone()

        conn.close()

        if not row:

            return jsonify({
                "success": False,
                "error":
                    "Syllabus not found for the selected Board, Class and Subject."
            }), 404

        syllabus_text = row["syllabus_text"] or ""

        if not syllabus_text.strip():

            return jsonify({
                "success": False,
                "error": "Uploaded syllabus is empty."
            }), 400

        # -----------------------------------------
        # LIMIT SYLLABUS SIZE
        # -----------------------------------------

        syllabus_context = syllabus_text[:30000]

        # -----------------------------------------
        # AI PROMPT
        # -----------------------------------------

        prompt = f"""

You are an expert school mathematics teacher and assessment designer.

Generate ONE ORIGINAL multiple-choice question for a school
learning platform.

STUDENT SELECTION
-------------------------

Board:
{board}

Class:
{class_name}

Subject:
{subject}

Topic:
{topic}

Subtopic:
{subtopic}

Difficulty:
{difficulty}

SUPPLIED SYLLABUS
-------------------------

{syllabus_context}

IMPORTANT RULES
-------------------------

1. Generate exactly ONE question.

2. The question MUST be directly related to:
   - the selected subject
   - the selected topic
   - the selected subtopic.

3. Use ONLY concepts that are supported by the supplied syllabus.

4. Do NOT introduce an unrelated chapter or concept.

5. The question must be ORIGINAL.
   Do not copy a textbook, website, sample paper,
   or previously published question verbatim.

6. Create exactly FOUR options.

7. Only ONE option must be correct.

8. The correct answer must be mathematically verified.

9. Difficulty must match the selected level.

EASY:
- fundamental concept
- direct application
- simple calculation

MEDIUM:
- concept application
- multi-step reasoning
- moderate calculation

HARD:
- deeper reasoning
- multi-step problem solving
- challenging application

10. Provide a short student-friendly explanation.

11. Provide a useful short hint WITHOUT revealing
    the complete answer.

12. Return ONLY valid JSON.

13. Do NOT use markdown or code fences.

JSON FORMAT
-------------------------

{{
    "question": "Question text",

    "options": [
        "Option 1",
        "Option 2",
        "Option 3",
        "Option 4"
    ],

    "correct_answer": 0,

    "hint": "Short helpful hint",

    "explanation": "Clear student-friendly explanation",

    "topic": "{topic}",

    "subtopic": "{subtopic}",

    "difficulty": "{difficulty}"
}}

"""

        # -----------------------------------------
        # AI CALL
        # -----------------------------------------

        response = client.responses.create(
            model="gpt-5.6-luna",
            input=prompt,
            max_output_tokens=2500
        )

        result = response.output_text.strip()

        # -----------------------------------------
        # REMOVE CODE FENCES IF AI RETURNS THEM
        # -----------------------------------------

        if result.startswith("```"):

            result = result.replace("```json", "")
            result = result.replace("```", "")
            result = result.strip()

        # -----------------------------------------
        # PARSE JSON
        # -----------------------------------------

        question_data = json.loads(result)

        # -----------------------------------------
        # VALIDATE QUESTION
        # -----------------------------------------

        if not question_data.get("question"):
            raise ValueError(
                "AI did not return a question."
            )

        options = question_data.get("options")

        if not isinstance(options, list):
            raise ValueError(
                "AI returned invalid options."
            )

        if len(options) != 4:
            raise ValueError(
                "AI must return exactly 4 options."
            )

        correct_answer = question_data.get(
            "correct_answer"
        )

        if correct_answer not in [0, 1, 2, 3]:
            raise ValueError(
                "Invalid correct answer index."
            )

        if not question_data.get("explanation"):
            raise ValueError(
                "AI did not return an explanation."
            )

        if not question_data.get("hint"):
            question_data["hint"] = (
                "Think about the main concept used "
                "in this question."
            )

        # -----------------------------------------
        # FORCE SELECTED METADATA
        # -----------------------------------------

        question_data["topic"] = topic
        question_data["subtopic"] = subtopic
        question_data["difficulty"] = difficulty

        # -----------------------------------------
        # RETURN QUESTION
        # -----------------------------------------

        return jsonify({
            "success": True,
            "question": question_data
        })

    except Exception as e:

        print(
            "AI QUESTION ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/ai-attempt", methods=["POST"])
def save_ai_attempt():
    try:
        data = request.get_json() or {}

        practice_id = get_practice_id()

        board = data.get("board")
        class_name = data.get("class_name")
        subject = data.get("subject")
        topic = data.get("topic")
        subtopic = data.get("subtopic")
        difficulty = data.get("difficulty")

        correct_answers = int(data.get("correct_answers", 0))
        incorrect_answers = int(data.get("incorrect_answers", 0))
        score = int(data.get("score", 0))
        percentage = float(data.get("percentage", 0))

        question_data = data.get("question_data", [])

        practice_id = get_practice_id()

        if not all([
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty
        ]):
            return jsonify({
                "success": False,
                "error": "Required learning details are missing"
            }), 400

        if not isinstance(question_data, list):
            return jsonify({
                "success": False,
                "error": "Invalid question data"
            }), 400

        # Maximum 25 questions
        question_data = question_data[:25]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        # -------------------------------------------------
        # 1. SAVE COMPLETE ATTEMPT
        # -------------------------------------------------

        c.execute("""
            INSERT INTO ai_attempts
            (
                practice_id,
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                total_questions,
                total_marks,
                correct_answers,
                incorrect_answers,
                score,
                percentage,
                question_data,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
        practice_id,
        board,
        class_name,
        subject,
        topic,
        subtopic,
        difficulty,
        25,
        50,
        correct_answers,
        incorrect_answers,
        score,
        percentage,
        json.dumps(question_data, ensure_ascii=False)
    ))

        # -------------------------------------------------
        # 2. CHECK EXISTING PERFORMANCE RECORD
        # -------------------------------------------------

        c.execute("""
            SELECT
                id,
                total_questions,
                correct_answers,
                incorrect_answers,
                score
            FROM ai_topic_performance
            WHERE practice_id = ?
              AND board = ?
              AND class_name = ?
              AND subject = ?
              AND topic = ?
              AND subtopic = ?
              AND difficulty = ?
        """, (
            practice_id,
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty
        ))

        existing = c.fetchone()

        # -------------------------------------------------
        # 3. UPDATE EXISTING PERFORMANCE
        # -------------------------------------------------

        if existing:

            performance_id = existing[0]

            old_total = existing[1] or 0
            old_correct = existing[2] or 0
            old_incorrect = existing[3] or 0
            old_score = existing[4] or 0

            new_total = old_total + 25
            new_correct = old_correct + correct_answers
            new_incorrect = old_incorrect + incorrect_answers
            new_score = old_score + score

            new_percentage = (
                (new_correct / new_total) * 100
                if new_total > 0 else 0
            )

            c.execute("""
                UPDATE ai_topic_performance
                SET
                    total_questions = ?,
                    correct_answers = ?,
                    incorrect_answers = ?,
                    score = ?,
                    percentage = ?,
                    last_attempt = datetime('now')
                WHERE id = ?
            """, (
                new_total,
                new_correct,
                new_incorrect,
                new_score,
                new_percentage,
                performance_id
            ))

        # -------------------------------------------------
        # 4. CREATE FIRST PERFORMANCE RECORD
        # -------------------------------------------------

        else:

            c.execute("""
                INSERT INTO ai_topic_performance
                (
                    practice_id,
                    board,
                    class_name,
                    subject,
                    topic,
                    subtopic,
                    difficulty,
                    total_questions,
                    correct_answers,
                    incorrect_answers,
                    score,
                    percentage,
                    last_attempt
                                       
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                practice_id,
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                25,
                correct_answers,
                incorrect_answers,
                score,
                percentage,
                datetime.now().isoformat()
            ))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "AI practice attempt saved successfully"
        })

    except Exception as e:

        print("AI ATTEMPT SAVE ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
# =====================================================
# AI 25 QUESTION BATCH
# QUESTION BANK BASED GENERATION
# =====================================================

@app.route("/api/ai-question-batch", methods=["POST"])
def ai_question_batch():

    try:

        data = request.get_json() or {}

        board = data.get("board")
        class_name = data.get("class_name")
        subject = data.get("subject")
        topic = data.get("topic")
        subtopic = data.get("subtopic")

        difficulty = data.get(
            "difficulty",
            "easy"
        )

        # -------------------------------------------------
        # PRACTICE / MOCK MODE
        # -------------------------------------------------

        mode = data.get(
            "mode",
            "practice"
        )

        test_number = data.get(
            "test_number",
            0
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not board or not class_name or not subject:

            return jsonify({

                "success": False,

                "error":
                    "Board, Class and Subject are required."

            }), 400

        if not topic or not subtopic:

            return jsonify({

                "success": False,

                "error":
                    "Chapter and Subtopic are required."

            }), 400

        if difficulty not in [
            "easy",
            "medium",
            "hard"
        ]:

            return jsonify({

                "success": False,

                "error":
                    "Invalid difficulty level."

            }), 400

        if mode not in [
            "practice",
            "mock"
        ]:

            return jsonify({

                "success": False,

                "error":
                    "Invalid mode."

            }), 400

        try:

            test_number = int(test_number)

        except:

            test_number = 0

        # Practice = test_number 0
        # Mock = test_number 1 or 2

        if mode == "practice":

            test_number = 0

        elif test_number not in [1, 2]:

            return jsonify({

                "success": False,

                "error":
                    "Mock Test number must be 1 or 2."

            }), 400

        # -------------------------------------------------
        # DATABASE CONNECTION
        # -------------------------------------------------

        conn = sqlite3.connect(
            "students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # MAKE SURE QUESTION BANK EXISTS
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS ai_question_bank (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            board TEXT NOT NULL,
            class_name TEXT NOT NULL,
            subject TEXT NOT NULL,

            topic TEXT NOT NULL,
            subtopic TEXT NOT NULL,

            mode TEXT NOT NULL,
            difficulty TEXT NOT NULL,

            test_number INTEGER DEFAULT 0,

            question TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_answer INTEGER NOT NULL,

            explanation TEXT DEFAULT '',
            hint TEXT DEFAULT '',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()

        # -------------------------------------------------
        # CHECK EXISTING QUESTION SET
        # -------------------------------------------------

        c.execute("""
        SELECT *
        FROM ai_question_bank

        WHERE board=?
        AND class_name=?
        AND subject=?
        AND topic=?
        AND subtopic=?
        AND mode=?
        AND difficulty=?
        AND test_number=?

        ORDER BY id ASC
        """, (

            board,
            class_name,
            subject,
            topic,
            subtopic,
            mode,
            difficulty,
            test_number

        ))

        existing_rows = c.fetchall()

        # -------------------------------------------------
        # IF 25 QUESTIONS ALREADY EXIST
        # RETURN THEM
        # -------------------------------------------------

        if len(existing_rows) >= 25:

            questions = []

            for row in existing_rows[:25]:

                try:

                    options = json.loads(
                        row["options"]
                    )

                except:

                    options = []

                questions.append({

                    "id":
                        row["id"],

                    "question":
                        row["question"],

                    "options":
                        options,

                    "correct_answer":
                        row["correct_answer"],

                    "explanation":
                        row["explanation"] or "",

                    "hint":
                        row["hint"] or "",

                    "topic":
                        row["topic"],

                    "subtopic":
                        row["subtopic"],

                    "difficulty":
                        row["difficulty"],

                    "mode":
                        row["mode"],

                    "test_number":
                        row["test_number"]

                })

            conn.close()

            return jsonify({

                "success": True,

                "source":
                    "question_bank",

                "mode":
                    mode,

                "test_number":
                    test_number,

                "difficulty":
                    difficulty,

                "questions":
                    questions

            })

        # -------------------------------------------------
        # GET SYLLABUS
        # -------------------------------------------------

        c.execute("""
        SELECT syllabus_text
        FROM syllabi

        WHERE board=?
        AND class_name=?
        AND subject=?

        ORDER BY id DESC

        LIMIT 1
        """, (

            board,
            class_name,
            subject

        ))

        row = c.fetchone()

        if not row:

            conn.close()

            return jsonify({

                "success": False,

                "error":
                    "Syllabus not found for selected subject."

            }), 404

        syllabus_text = (
            row["syllabus_text"] or ""
        )

        if not syllabus_text.strip():

            conn.close()

            return jsonify({

                "success": False,

                "error":
                    "Uploaded syllabus is empty."

            }), 400

        syllabus_context = (
            syllabus_text[:10000]
        )

        # -------------------------------------------------
        # AI PROMPT
        # -------------------------------------------------

        prompt = f"""

You are an expert school Mathematics teacher,
curriculum specialist and professional MCQ
question-paper designer.

Your task is to create EXACTLY 25 ORIGINAL
multiple-choice questions.

-----------------------------------------
SELECTED ACADEMIC INFORMATION
-----------------------------------------

Board: {board}
Class: {class_name}
Subject: {subject}

Chapter / Topic:
{topic}

Subtopic:
{subtopic}

Difficulty:
{difficulty}

Mode:
{mode}

Test Number:
{test_number}

-----------------------------------------
IMPORTANT REQUIREMENTS
-----------------------------------------

1. Generate EXACTLY 25 questions.

2. Every question MUST be directly related
   to the selected Chapter/Topic and Subtopic.

3. Use the provided syllabus as the primary
   academic source.

4. Do NOT generate questions from unrelated
   chapters.

5. Difficulty MUST match:
   {difficulty}

6. Every question must have EXACTLY
   4 options.

7. There must be ONLY ONE correct answer.

8. "correct_answer" MUST be an integer:
   0, 1, 2 or 3.

9. Questions must be mathematically accurate.

10. Calculations must be checked carefully.

11. Questions must be suitable for the
    selected Class and Board.

12. Questions must be ORIGINAL.

13. Do NOT copy textbook questions verbatim.

14. Do NOT repeat the same question.

15. Do NOT create duplicate questions with
    only numbers changed.

16. Avoid ambiguous questions.

17. Avoid two options being mathematically
    equivalent.

18. Every question must contain enough
    information for a student to solve it.

19. Provide a short student-friendly
    explanation.

20. Provide a useful hint.

21. Do NOT reveal the answer inside
    the question text.

22. Return ONLY valid JSON.

23. Do NOT use Markdown.

24. Do NOT use code fences.

-----------------------------------------
JSON FORMAT
-----------------------------------------

{{
    "questions": [

        {{
            "question": "Question text",

            "options": [
                "Option 1",
                "Option 2",
                "Option 3",
                "Option 4"
            ],

            "correct_answer": 0,

            "explanation":
                "Short student-friendly explanation.",

            "hint":
                "Short useful hint."
        }}

    ]
}}

-----------------------------------------
SYLLABUS
-----------------------------------------

{syllabus_context}

-----------------------------------------
FINAL INSTRUCTION
-----------------------------------------

Generate EXACTLY 25 UNIQUE,
ACADEMICALLY CORRECT MCQs.

Return ONLY the JSON object.
"""

        # -------------------------------------------------
        # AI CALL
        # -------------------------------------------------

        response = client.responses.create(

            model="gpt-5.6-luna",

            input=prompt,
            max_output_tokens=2500

        )

        result = (
            response.output_text
            .strip()
        )

        # -------------------------------------------------
        # CLEAN JSON
        # -------------------------------------------------

        if result.startswith("```"):

            result = result.replace(
                "```json",
                ""
            )

            result = result.replace(
                "```",
                ""
            )

            result = result.strip()

        question_data = json.loads(
            result
        )

        questions = (
            question_data.get(
                "questions",
                []
            )
        )

        # -------------------------------------------------
        # BASIC VALIDATION
        # -------------------------------------------------

        if not isinstance(
            questions,
            list
        ):

            raise ValueError(
                "AI returned invalid question structure."
            )

        if len(questions) < 25:

            raise ValueError(

                f"AI generated only "
                f"{len(questions)} questions. "
                f"25 questions are required."

            )

        # -------------------------------------------------
        # VALIDATE QUESTIONS
        # -------------------------------------------------

        validated_questions = []

        question_texts = set()

        for q in questions:

            if not isinstance(
                q,
                dict
            ):
                continue

            question_text = str(
                q.get(
                    "question",
                    ""
                )
            ).strip()

            options = q.get(
                "options"
            )

            correct_answer = q.get(
                "correct_answer"
            )

            explanation = str(
                q.get(
                    "explanation",
                    ""
                )
            ).strip()

            hint = str(
                q.get(
                    "hint",
                    ""
                )
            ).strip()

            # ---------------------------------------------
            # QUESTION VALIDATION
            # ---------------------------------------------

            if not question_text:
                continue

            if question_text in question_texts:
                continue

            if not isinstance(
                options,
                list
            ):
                continue

            if len(options) != 4:
                continue

            if correct_answer not in [
                0,
                1,
                2,
                3
            ]:
                continue

            # ---------------------------------------------
            # OPTION VALIDATION
            # ---------------------------------------------

            cleaned_options = []

            valid_options = True

            for option in options:

                option_text = str(
                    option
                ).strip()

                if not option_text:

                    valid_options = False

                    break

                cleaned_options.append(
                    option_text
                )

            if not valid_options:
                continue

            # ---------------------------------------------
            # SAVE VALID QUESTION
            # ---------------------------------------------

            question_texts.add(
                question_text
            )

            validated_questions.append({

                "question":
                    question_text,

                "options":
                    cleaned_options,

                "correct_answer":
                    correct_answer,

                "explanation":
                    explanation,

                "hint":
                    hint,

                "topic":
                    topic,

                "subtopic":
                    subtopic,

                "difficulty":
                    difficulty,

                "mode":
                    mode,

                "test_number":
                    test_number

            })

            if len(
                validated_questions
            ) == 25:

                break

        # -------------------------------------------------
        # FINAL VALIDATION
        # -------------------------------------------------

        if len(
            validated_questions
        ) < 25:

            conn.close()

            raise ValueError(

                "AI did not return "
                "25 unique valid questions."

            )

        # -------------------------------------------------
        # SAVE QUESTIONS INTO QUESTION BANK
        # -------------------------------------------------

        saved_questions = []

        for q in validated_questions:

            c.execute("""
            INSERT INTO ai_question_bank (

                board,
                class_name,
                subject,

                topic,
                subtopic,

                mode,
                difficulty,

                test_number,

                question,
                options,
                correct_answer,

                explanation,
                hint

            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """, (

                board,
                class_name,
                subject,

                topic,
                subtopic,

                mode,
                difficulty,

                test_number,

                q["question"],

                json.dumps(
                    q["options"],
                    ensure_ascii=False
                ),

                q["correct_answer"],

                q["explanation"],

                q["hint"]

            ))

            question_id = (
                c.lastrowid
            )

            q["id"] = question_id

            saved_questions.append(
                q
            )

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        conn.commit()

        conn.close()

        # -------------------------------------------------
        # RETURN
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "source":
                "ai_generated",

            "mode":
                mode,

            "test_number":
                test_number,

            "difficulty":
                difficulty,

            "questions":
                saved_questions[:25]

        })

    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as e:

        print(
            "AI QUESTION BATCH ERROR:",
            e
        )

        error_message = str(e)

        # -------------------------------------------------
        # RATE LIMIT
        # -------------------------------------------------

        if (
            "429" in error_message
            or
            "rate limit"
            in error_message.lower()
        ):

            return jsonify({

                "success": False,

                "error":
                    "AI service is temporarily busy. "
                    "Please try again after a short while.",

                "rate_limit":
                    True

            }), 429

        return jsonify({

            "success": False,

            "error":
                error_message

        }), 500

# =====================================================
# AI EXAM SESSION
# CREATE / RESUME SESSION
# =====================================================

@app.route("/api/ai-session", methods=["POST"])
def ai_session():

    try:

        data = request.get_json() or {}

        board = data.get("board")
        class_name = data.get("class_name")
        subject = data.get("subject")

        topic = data.get("topic")
        subtopic = data.get("subtopic")

        difficulty = data.get(
            "difficulty",
            "easy"
        )

        mode = data.get(
            "mode",
            "practice"
        )

        test_number = data.get(
            "test_number",
            0
        )
        # -------------------------------------------------
        # ANONYMOUS PRACTICE ID
        # -------------------------------------------------

        practice_id = get_practice_id()
        
        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not board or not class_name or not subject:

            return jsonify({

                "success": False,
                "error":
                    "Board, Class and Subject are required."

            }), 400

        if not topic or not subtopic:

            return jsonify({

                "success": False,
                "error":
                    "Topic and Subtopic are required."

            }), 400

        if difficulty not in [
            "easy",
            "medium",
            "hard"
        ]:

            return jsonify({

                "success": False,
                "error":
                    "Invalid difficulty."

            }), 400

        if mode not in [
            "practice",
            "mock"
        ]:

            return jsonify({

                "success": False,
                "error":
                    "Invalid mode."

            }), 400

        try:

            test_number = int(
                test_number
            )

        except:

            test_number = 0

        # Practice always uses 0
        if mode == "practice":

            test_number = 0

        # Mock must be Test 1 or Test 2
        elif test_number not in [1, 2]:

            return jsonify({

                "success": False,

                "error":
                    "Mock Test number must be 1 or 2."

            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            "students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # MAKE SURE SESSION TABLE EXISTS
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS ai_sessions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            practice_id TEXT,

            board TEXT,
            class_name TEXT,
            subject TEXT,

            topic TEXT,
            subtopic TEXT,

            difficulty TEXT,

            mode TEXT,

            test_number INTEGER DEFAULT 0,

            total_questions INTEGER DEFAULT 25,
            total_marks INTEGER DEFAULT 50,

            question_ids TEXT,

            answers TEXT,

            current_question INTEGER DEFAULT 0,

            status TEXT DEFAULT 'in_progress',

            started_at TEXT,

            submitted_at TEXT,

            score INTEGER DEFAULT 0,

            correct_answers INTEGER DEFAULT 0,

            incorrect_answers INTEGER DEFAULT 0,

            unanswered INTEGER DEFAULT 0,

            percentage REAL DEFAULT 0

        )
        """)

        conn.commit()

        # -------------------------------------------------
        # GET 25 RANDOM QUESTIONS
        # -------------------------------------------------

        c.execute("""
        SELECT id

        FROM ai_question_bank

        WHERE board=?
        AND class_name=?
        AND subject=?
        AND topic=?
        AND subtopic=?
        AND difficulty=?
        AND mode=?
        AND (
            mode='practice'
            OR test_number=?
        )

        ORDER BY RANDOM()

        LIMIT 25
        """, (
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty,
            mode,
            test_number
        ))

        rows = c.fetchall()

        question_ids = [
            row["id"]
            for row in rows
        ]

        # -------------------------------------------------
        # QUESTION COUNT CHECK
        # -------------------------------------------------

        if len(question_ids) != 25:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    f"Only {len(question_ids)} questions are available. "
                    "Exactly 25 questions are required."
            }), 400

        # -------------------------------------------------
        # CHECK FOR EXISTING IN-PROGRESS SESSION
        # -------------------------------------------------

        c.execute("""
        SELECT *

        FROM ai_sessions
  
        WHERE practice_id=?
      
        WHERE board=?
        AND class_name=?
        AND subject=?
        AND topic=?
        AND subtopic=?
        AND difficulty=?
        AND mode=?
        AND test_number=?
        AND status='in_progress'

        ORDER BY id DESC

        LIMIT 1

        """, (
            practice_id,
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty,
            mode,
            test_number

        ))

        existing_session = c.fetchone()

       # -------------------------------------------------
        # RESUME EXISTING SESSION
        # -------------------------------------------------

        if existing_session:

            try:
                question_ids = json.loads(
                    existing_session["question_ids"] or "[]"
                )
            except:
                question_ids = []

            try:
                answers = json.loads(
                    existing_session["answers"] or "{}"
                )
            except:
                answers = {}

            response = {
                "success": True,
                "resumed": True,

                "session_id":
                    existing_session["id"],

                "practice_id":
                    existing_session["practice_id"],

                "board":
                    existing_session["board"],

                "class_name":
                    existing_session["class_name"],

                "subject":
                    existing_session["subject"],

                "topic":
                    existing_session["topic"],

                "subtopic":
                    existing_session["subtopic"],

                "difficulty":
                    existing_session["difficulty"],

                "mode":
                    existing_session["mode"],

                "test_number":
                    existing_session["test_number"],

                "total_questions":
                    existing_session["total_questions"],

                "total_marks":
                    existing_session["total_marks"],

                "question_ids":
                    question_ids,

                "answers":
                    answers,

                "current_question":
                    existing_session["current_question"],

                "status":
                    existing_session["status"],

                "started_at":
                    existing_session["started_at"]
            }

            conn.close()

            return jsonify(response)

            # ---------------------------------------------
            # Return existing session
            # ---------------------------------------------

            conn.close()

            return jsonify({

                "success": True,

                "session_id":
                    existing_ai_session["id"],

                "resumed":
                    True,

                "status":
                    existing_ai_session["status"],

                "question_ids":
                    saved_question_ids,

                "answers":
                    saved_answers,

                "current_question":
                    existing_ai_session["current_question"],

                "started_at":
                    existing_ai_session["started_at"],

                "difficulty":
                    existing_ai_session["difficulty"],

                "mode":
                    existing_ai_session["mode"],

                "test_number":
                    existing_ai_session["test_number"]

            })

        # -------------------------------------------------
        # CREATE NEW SESSION
        # -------------------------------------------------

        started_at = datetime.now().isoformat()

        answers = {}

        c.execute("""
        INSERT INTO ai_sessions (

            practice_id,

            board,
            class_name,
            subject,

            topic,
            subtopic,

            difficulty,

            mode,
            test_number,

            total_questions,
            total_marks,

            question_ids,
            answers,

            current_question,

            status,

            started_at
        )

        VALUES (

            ?,

            ?,
            ?,
            ?,

            ?,
            ?,

            ?,

            ?,
            ?,

            25,
            50,

            ?,
            ?,

            0,

            'in_progress',

            ?
        )
        """, (

            practice_id,

            board,
            class_name,
            subject,

            topic,
            subtopic,

            difficulty,

            mode,
            test_number,

            json.dumps(question_ids),

            json.dumps(answers),

            started_at
        ))

        session_id = c.lastrowid

        conn.commit()

        conn.close()


        # -------------------------------------------------
        # RETURN NEW SESSION
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "session_id":
                session_id,

            "resumed":
                False,

            "status":
                "in_progress",

            "question_ids":
                question_ids,

            "answers":
                initial_answers,

            "current_question":
                0,

            "started_at":
                now,

            "difficulty":
                difficulty,

            "mode":
                mode,

            "test_number":
                test_number,

            "total_questions":
                25,

            "total_marks":
                50

        })
        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "resumed": False,

            "session_id":
                session_id,

            "practice_id":
                practice_id,

            "board":
                board,

            "class_name":
                class_name,

            "subject":
                subject,

            "topic":
                topic,

            "subtopic":
                subtopic,

            "difficulty":
                difficulty,

            "mode":
                mode,

            "test_number":
                test_number,

            "total_questions":
                25,

            "total_marks":
                50,

            "question_ids":
                question_ids,

            "answers":
                answers,

            "current_question":
                0,

            "status":
                "in_progress",

            "started_at":
                started_at
        })

    except Exception as e:

        print(
            "AI SESSION ERROR:",
            str(e)
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as e:

        print(
            "AI SESSION ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500

# =====================================================
# AI SESSION - SAVE ANSWER
# =====================================================

# =====================================================
# AI SESSION - SAVE ANSWER
# =====================================================

@app.route("/api/ai-session/save-answer", methods=["POST"])
def ai_session_save_answer():

    try:

        data = request.get_json() or {}

        session_id = data.get("session_id")
        question_id = data.get("question_id")
        answer = data.get("answer")
        current_question = data.get("current_question")

        practice_id = get_practice_id()

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not session_id:

            return jsonify({
                "success": False,
                "error": "Session ID is required."
            }), 400

        if not question_id:

            return jsonify({
                "success": False,
                "error": "Question ID is required."
            }), 400

        if answer is None:

            return jsonify({
                "success": False,
                "error": "Answer is required."
            }), 400

        try:

            session_id = int(session_id)
            question_id = int(question_id)
            answer = int(answer)

        except:

            return jsonify({
                "success": False,
                "error":
                    "Invalid session, question or answer."
            }), 400

        if answer not in [0, 1, 2, 3]:

            return jsonify({
                "success": False,
                "error":
                    "Invalid answer option."
            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            "students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # GET SESSION
        # -------------------------------------------------

        c.execute("""
        SELECT *
        FROM ai_sessions

        WHERE id=?
        AND practice_id=?

        LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        ai_session = c.fetchone()

        if not ai_session:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Exam session not found."
            }), 404

        # -------------------------------------------------
        # CHECK STATUS
        # -------------------------------------------------

        if ai_session["status"] != "in_progress":

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "This exam session is already completed."
            }), 400

        # -------------------------------------------------
        # GET QUESTION IDS
        # -------------------------------------------------

        try:

            session_question_ids = json.loads(
                ai_session["question_ids"] or "[]"
            )

        except:

            session_question_ids = []

        if question_id not in session_question_ids:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "This question does not belong to this exam session."
            }), 400

        # -------------------------------------------------
        # LOAD EXISTING ANSWERS
        # -------------------------------------------------

        try:

            answers = json.loads(
                ai_session["answers"] or "{}"
            )

        except:

            answers = {}

        # -------------------------------------------------
        # SAVE / UPDATE ANSWER
        # -------------------------------------------------

        answers[str(question_id)] = answer

        # -------------------------------------------------
        # CURRENT QUESTION
        # -------------------------------------------------

        if current_question is not None:

            try:

                current_question = int(
                    current_question
                )

                if current_question < 0:
                    current_question = 0

                if current_question > 24:
                    current_question = 24

            except:

                current_question = (
                    ai_session["current_question"] or 0
                )

        else:

            current_question = (
                ai_session["current_question"] or 0
            )

        # -------------------------------------------------
        # UPDATE
        # -------------------------------------------------

        c.execute("""
        UPDATE ai_sessions

        SET
            answers=?,
            current_question=?

        WHERE id=?
        AND practice_id=?
        """, (

            json.dumps(answers),

            current_question,

            session_id,

            practice_id
        ))

        conn.commit()

        conn.close()

        return jsonify({

            "success": True,

            "session_id":
                session_id,

            "question_id":
                question_id,

            "answer":
                answer,

            "current_question":
                current_question,

            "answers":
                answers
        })

    except Exception as e:

        print(
            "SAVE ANSWER ERROR:",
            str(e)
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

        
# =====================================================
# AI SESSION - GET QUESTIONS
# =====================================================

# =====================================================
# AI SESSION - GET QUESTIONS
# =====================================================

@app.route("/api/ai-session/questions", methods=["GET", "POST"])
def ai_session_questions():

    try:

        data = request.get_json() or {}

        session_id = data.get("session_id")

        practice_id = get_practice_id()

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not session_id:

            return jsonify({
                "success": False,
                "error": "Session ID is required."
            }), 400

        try:

            session_id = int(session_id)

        except:

            return jsonify({
                "success": False,
                "error":
                    "Invalid session ID."
            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            "students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # GET SESSION
        # -------------------------------------------------

        c.execute("""
        SELECT *
        FROM ai_sessions

        WHERE id=?
        AND practice_id=?

        LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        ai_session = c.fetchone()

        if not ai_session:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Exam session not found."
            }), 404

        # -------------------------------------------------
        # GET QUESTION IDS
        # -------------------------------------------------

        try:

            question_ids = json.loads(
                ai_session["question_ids"] or "[]"
            )

        except:

            question_ids = []

        if not isinstance(
            question_ids,
            list
        ):

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Invalid question list in exam session."
            }), 500

        if len(question_ids) != 25:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Exam session does not contain exactly 25 questions."
            }), 500

        # -------------------------------------------------
        # GET SAVED ANSWERS
        # -------------------------------------------------

        try:

            saved_answers = json.loads(
                ai_session["answers"] or "{}"
            )

        except:

            saved_answers = {}

        # -------------------------------------------------
        # GET QUESTIONS
        # -------------------------------------------------

        questions = []

        for question_id in question_ids:

            try:

                question_id = int(
                    question_id
                )

            except:

                continue

            c.execute("""
            SELECT
                id,
                question,
                options,
                topic,
                subtopic,
                difficulty,
                mode,
                test_number

            FROM ai_question_bank

            WHERE id=?

            LIMIT 1
            """, (
                question_id,
            ))

            row = c.fetchone()

            if not row:

                conn.close()

                return jsonify({
                    "success": False,
                    "error":
                        f"Question {question_id} not found."
                }), 500

            try:

                options = json.loads(
                    row["options"] or "[]"
                )

            except:

                options = []

            questions.append({

                "id":
                    row["id"],

                "question":
                    row["question"],

                "options":
                    options,

                "topic":
                    row["topic"],

                "subtopic":
                    row["subtopic"],

                "difficulty":
                    row["difficulty"],

                "mode":
                    row["mode"],

                "test_number":
                    row["test_number"],

                "saved_answer":
                    saved_answers.get(
                        str(row["id"])
                    )
            })

        conn.close()

        # -------------------------------------------------
        # RETURN
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "session_id":
                session_id,

            "practice_id":
                practice_id,

            "questions":
                questions,

            "answers":
                saved_answers,

            "current_question":
                ai_session["current_question"],

            "status":
                ai_session["status"],

            "started_at":
                ai_session["started_at"],

            "total_questions":
                25,

            "total_marks":
                50
        })

    except Exception as e:

        print(
            "GET QUESTIONS ERROR:",
            str(e)
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/ai-session/submit", methods=["POST"])
def ai_session_submit():

    try:

        data = request.get_json() or {}

        session_id = data.get("session_id")
        submitted_answers = data.get("answers", {})

        # -------------------------------------------------
        # GET ANONYMOUS PRACTICE ID
        # -------------------------------------------------

        practice_id = get_practice_id()

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not session_id:

            return jsonify({
                "success": False,
                "error": "Session ID is required."
            }), 400

        try:
            session_id = int(session_id)

        except:

            return jsonify({
                "success": False,
                "error": "Invalid session ID."
            }), 400

        if not isinstance(submitted_answers, dict):

            return jsonify({
                "success": False,
                "error": "Invalid answer data."
            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect("students.db")

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # GET SESSION
        # -------------------------------------------------

        c.execute("""
        SELECT *
        FROM ai_sessions
        WHERE id=?
        LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        ai_session = c.fetchone()

        if not ai_session:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Exam session not found."
            }), 404

        # -------------------------------------------------
        # CHECK SESSION STATUS
        # -------------------------------------------------

        if ai_session["status"] == "completed":

            conn.close()

            return jsonify({
                "success": False,
                "error": "This exam has already been submitted."
            }), 400

        if ai_session["status"] != "in_progress":

            conn.close()

            return jsonify({
                "success": False,
                "error": "This exam session is not active."
            }), 400

        # -------------------------------------------------
        # GET QUESTION IDS
        # -------------------------------------------------

        try:

            question_ids = json.loads(
                ai_session["question_ids"] or "[]"
            )

        except:

            question_ids = []

        if len(question_ids) != 25:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Invalid question set."
            }), 500

        # -------------------------------------------------
        # CLEAN SUBMITTED ANSWERS
        # -------------------------------------------------

        clean_answers = {}

        for question_id, answer in submitted_answers.items():

            try:

                question_id = int(question_id)
                answer = int(answer)

            except:

                continue

            # Only accept questions belonging
            # to this session

            if question_id not in question_ids:
                continue

            # Only options 0,1,2,3 are valid

            if answer not in [0, 1, 2, 3]:
                continue

            clean_answers[str(question_id)] = answer

        # -------------------------------------------------
        # SERVER-SIDE SCORING
        # -------------------------------------------------

        correct_count = 0
        incorrect_count = 0
        unanswered_count = 0

        review_data = []

        for question_id in question_ids:

            c.execute("""
            SELECT
                id,
                question,
                options,
                correct_answer,
                explanation,
                hint
            FROM ai_question_bank
            WHERE id=?
            LIMIT 1
            """, (
                question_id,
            ))

            row = c.fetchone()

            if not row:

                conn.close()

                return jsonify({
                    "success": False,
                    "error":
                        "A question from this session "
                        "could not be found."
                }), 500

            correct_answer = int(
                row["correct_answer"]
            )

            question_key = str(
                question_id
            )

            # -------------------------------------------------
            # CHECK ANSWER
            # -------------------------------------------------

            if question_key not in clean_answers:

                unanswered_count += 1

                student_answer = None

                is_correct = False

            else:

                student_answer = clean_answers[
                    question_key
                ]

                if student_answer == correct_answer:

                    correct_count += 1

                    is_correct = True

                else:

                    incorrect_count += 1

                    is_correct = False

            # -------------------------------------------------
            # PREPARE REVIEW DATA
            # -------------------------------------------------

            try:

                options = json.loads(
                    row["options"]
                )

            except:

                options = []

            review_data.append({

                "id":
                    row["id"],

                "question":
                    row["question"],

                "options":
                    options,

                "student_answer":
                    student_answer,

                "correct_answer":
                    correct_answer,

                "is_correct":
                    is_correct,

                "explanation":
                    row["explanation"] or "",

                "hint":
                    row["hint"] or ""
            })

        # -------------------------------------------------
        # MARK CALCULATION
        # -------------------------------------------------

        total_questions = 25

        total_marks = 50

        score = correct_count * 2

        percentage = round(
            (score / total_marks) * 100,
            2
        )

        # -------------------------------------------------
        # SAVE COMPLETED SESSION
        # -------------------------------------------------

        c.execute("""
        UPDATE ai_sessions

        SET
            answers=?,
            status='completed',
            submitted_at=?,
            score=?,
            correct_answers=?,
            incorrect_answers=?,
            unanswered=?,
            percentage=?

        WHERE id=?
        """, (

            json.dumps(
                clean_answers
            ),

            datetime.now().isoformat(),

            score,

            correct_count,

            incorrect_count,

            unanswered_count,

            percentage,

            session_id
        ))

        # -------------------------------------------------
        # SAVE ATTEMPT HISTORY
        # USING PRACTICE_ID
        # -------------------------------------------------

        try:

            c.execute("""
            INSERT INTO ai_attempts (

                practice_id,

                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,

                total_questions,

                correct_answers,
                incorrect_answers,

                score,
                percentage,

                question_data,

                completed_at
            )

            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )

            """, (

                practice_id,

                ai_session["board"],
                ai_session["class_name"],
                ai_session["subject"],
                ai_session["topic"],
                ai_session["subtopic"],
                ai_session["difficulty"],

                total_questions,

                correct_count,
                incorrect_count,

                score,
                percentage,

                json.dumps(
                    review_data,
                    ensure_ascii=False
                ),

                datetime.now().isoformat()
            ))

        except Exception as attempt_error:

            print(
                "AI ATTEMPT HISTORY SAVE ERROR:",
                attempt_error
            )

        # =================================================
        # UPDATE TOPIC PERFORMANCE
        # USING PRACTICE_ID
        # =================================================

        board = ai_session["board"]

        class_name = ai_session["class_name"]

        subject = ai_session["subject"]

        topic = ai_session["topic"]

        subtopic = ai_session["subtopic"]

        difficulty = ai_session["difficulty"]

        # -------------------------------------------------
        # CHECK EXISTING PERFORMANCE
        # -------------------------------------------------

        c.execute("""
        SELECT
            id,
            total_questions,
            correct_answers,
            incorrect_answers,
            score

        FROM ai_topic_performance

        WHERE practice_id=?
          AND board=?
          AND class_name=?
          AND subject=?
          AND topic=?
          AND subtopic=?
          AND difficulty=?

        LIMIT 1
        """, (

            practice_id,

            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty
        ))

        performance = c.fetchone()

        # -------------------------------------------------
        # UPDATE EXISTING PERFORMANCE
        # -------------------------------------------------

        if performance:

            performance_id = performance["id"]

            old_total = (
                performance["total_questions"] or 0
            )

            old_correct = (
                performance["correct_answers"] or 0
            )

            old_incorrect = (
                performance["incorrect_answers"] or 0
            )

            old_score = (
                performance["score"] or 0
            )

            new_total = (
                old_total + total_questions
            )

            new_correct = (
                old_correct + correct_count
            )

            new_incorrect = (
                old_incorrect + incorrect_count
            )

            new_score = (
                old_score + score
            )

            new_percentage = (

                (new_correct / new_total) * 100

                if new_total > 0

                else 0
            )

            c.execute("""
            UPDATE ai_topic_performance

            SET
                total_questions=?,
                correct_answers=?,
                incorrect_answers=?,
                score=?,
                percentage=?,
                last_attempt=datetime('now')

            WHERE id=?
            """, (

                new_total,

                new_correct,

                new_incorrect,

                new_score,

                round(
                    new_percentage,
                    2
                ),

                performance_id
            ))

        # -------------------------------------------------
        # CREATE FIRST PERFORMANCE RECORD
        # -------------------------------------------------

        else:

            c.execute("""
            INSERT INTO ai_topic_performance
            (
                practice_id,

                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,

                total_questions,

                correct_answers,
                incorrect_answers,

                score,
                percentage,

                last_attempt
            )

            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )

            """, (

                practice_id,

                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,

                total_questions,

                correct_count,
                incorrect_count,

                score,
                percentage
            ))

        # -------------------------------------------------
        # COMMIT EVERYTHING
        # -------------------------------------------------

        conn.commit()

        conn.close()

        # -------------------------------------------------
        # RETURN FINAL RESULT
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "session_id":
                session_id,

            "status":
                "completed",

            "total_questions":
                total_questions,

            "total_marks":
                total_marks,

            "correct":
                correct_count,

            "incorrect":
                incorrect_count,

            "unanswered":
                unanswered_count,

            "score":
                score,

            "percentage":
                percentage,

            "review":
                review_data
        })

    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as e:

        print("========================================")
        print("AI TOPICS ERROR")
        print("ERROR TYPE:", type(e).__name__)
        print("ERROR DETAILS:", str(e))
        print("========================================")

        return jsonify({

            "success": False,

            "error":
                str(e)
        }), 500
        
 # =====================================================
# AI LEARNING - STUDENT PERFORMANCE DASHBOARD
# =====================================================

@app.route("/api/ai-performance", methods=["GET"])
def ai_performance():

    try:

        # -------------------------------------------------
        # STUDENT LOGIN
        # -------------------------------------------------

        practice_id = get_practice_id()

        # -------------------------------------------------
        # OPTIONAL FILTERS
        # -------------------------------------------------

        board = request.args.get("board", "").strip()
        class_name = request.args.get("class_name", "").strip()
        subject = request.args.get("subject", "").strip()
        topic = request.args.get("topic", "").strip()
        subtopic = request.args.get("subtopic", "").strip()


        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect("students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()


        # =================================================
        # 1. ATTEMPT HISTORY
        # =================================================

        attempt_query = """
            SELECT
                id,
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                total_questions,
                total_marks,
                correct_answers,
                incorrect_answers,
                score,
                percentage,
                completed_at
            FROM ai_attempts
            WHERE practice_id=?
        """

        attempt_params = [practice_id]


        if board:
            attempt_query += " AND board=?"
            attempt_params.append(board)

        if class_name:
            attempt_query += " AND class_name=?"
            attempt_params.append(class_name)

        if subject:
            attempt_query += " AND subject=?"
            attempt_params.append(subject)

        if topic:
            attempt_query += " AND topic=?"
            attempt_params.append(topic)

        if subtopic:
            attempt_query += " AND subtopic=?"
            attempt_params.append(subtopic)


        attempt_query += """
            ORDER BY completed_at DESC
            LIMIT 50
        """


        c.execute(
            attempt_query,
            tuple(attempt_params)
        )

        attempt_rows = c.fetchall()


        attempts = []

        for row in attempt_rows:

            percentage = float(
                row["percentage"] or 0
            )

            if percentage >= 80:
                status = "Strong"

            elif percentage >= 50:
                status = "Average"

            else:
                status = "Weak"


            attempts.append({

                "id": row["id"],

                "board": row["board"],

                "class_name":
                    row["class_name"],

                "subject":
                    row["subject"],

                "topic":
                    row["topic"],

                "subtopic":
                    row["subtopic"],

                "difficulty":
                    row["difficulty"],

                "total_questions":
                    row["total_questions"],

                "total_marks":
                    row["total_marks"],

                "correct_answers":
                    row["correct_answers"],

                "incorrect_answers":
                    row["incorrect_answers"],

                "score":
                    row["score"],

                "percentage":
                    round(percentage, 2),

                "status":
                    status,

                "completed_at":
                    row["completed_at"]
            })


        # =================================================
        # 2. TOPIC / SUBTOPIC PERFORMANCE
        # =================================================

        performance_query = """
            SELECT
                topic,
                subtopic,
                difficulty,
                total_questions,
                correct_answers,
                incorrect_answers,
                score,
                percentage,
                last_attempt
            FROM ai_topic_performance
            WHERE practice_id=?
        """

        performance_params = [practice_id]


        if board:
            performance_query += " AND board=?"
            performance_params.append(board)

        if class_name:
            performance_query += " AND class_name=?"
            performance_params.append(class_name)

        if subject:
            performance_query += " AND subject=?"
            performance_params.append(subject)

        if topic:
            performance_query += " AND topic=?"
            performance_params.append(topic)

        if subtopic:
            performance_query += " AND subtopic=?"
            performance_params.append(subtopic)


        performance_query += """
            ORDER BY percentage ASC
        """


        c.execute(
            performance_query,
            tuple(performance_params)
        )

        performance_rows = c.fetchall()


        # =================================================
        # 3. AGGREGATE SUBTOPIC PERFORMANCE
        # =================================================

        subtopic_map = {}


        for row in performance_rows:

            key = (
                row["topic"],
                row["subtopic"]
            )

            if key not in subtopic_map:

                subtopic_map[key] = {

                    "topic":
                        row["topic"],

                    "subtopic":
                        row["subtopic"],

                    "total_questions":
                        0,

                    "correct_answers":
                        0,

                    "incorrect_answers":
                        0,

                    "score":
                        0
                }


            item = subtopic_map[key]


            item["total_questions"] += (
                row["total_questions"] or 0
            )

            item["correct_answers"] += (
                row["correct_answers"] or 0
            )

            item["incorrect_answers"] += (
                row["incorrect_answers"] or 0
            )

            item["score"] += (
                row["score"] or 0
            )


        subtopic_performance = []


        for item in subtopic_map.values():

            total = item["total_questions"]

            correct = item["correct_answers"]

            percentage = (
                (correct / total) * 100
                if total > 0
                else 0
            )

            percentage = round(
                percentage,
                2
            )


            if percentage >= 80:
                status = "Strong"

            elif percentage >= 50:
                status = "Average"

            else:
                status = "Weak"


            item["percentage"] = percentage

            item["status"] = status

            subtopic_performance.append(
                item
            )


        # Weakest first

        subtopic_performance.sort(
            key=lambda x: x["percentage"]
        )


        # =================================================
        # 4. EASY / MEDIUM / HARD PERFORMANCE
        # =================================================

        difficulty_map = {}


        for row in performance_rows:

            difficulty = (
                row["difficulty"] or ""
            ).lower()


            if difficulty not in difficulty_map:

                difficulty_map[difficulty] = {

                    "difficulty":
                        difficulty,

                    "total_questions":
                        0,

                    "correct_answers":
                        0,

                    "incorrect_answers":
                        0,

                    "score":
                        0
                }


            item = difficulty_map[
                difficulty
            ]


            item["total_questions"] += (
                row["total_questions"] or 0
            )

            item["correct_answers"] += (
                row["correct_answers"] or 0
            )

            item["incorrect_answers"] += (
                row["incorrect_answers"] or 0
            )

            item["score"] += (
                row["score"] or 0
            )


        difficulty_performance = []


        for level in [
            "easy",
            "medium",
            "hard"
        ]:

            item = difficulty_map.get(
                level
            )

            if not item:
                continue


            total = item[
                "total_questions"
            ]

            correct = item[
                "correct_answers"
            ]


            percentage = (
                (correct / total) * 100
                if total > 0
                else 0
            )

            percentage = round(
                percentage,
                2
            )


            if percentage >= 80:
                status = "Strong"

            elif percentage >= 50:
                status = "Average"

            else:
                status = "Weak"


            item["percentage"] = (
                percentage
            )

            item["status"] = status


            difficulty_performance.append(
                item
            )


        # =================================================
        # 5. OVERALL PERFORMANCE
        # =================================================

        overall_total = sum(
            item["total_questions"]
            for item in subtopic_performance
        )

        overall_correct = sum(
            item["correct_answers"]
            for item in subtopic_performance
        )

        overall_score = sum(
            item["score"]
            for item in subtopic_performance
        )


        overall_percentage = (

            (
                overall_correct /
                overall_total
            ) * 100

            if overall_total > 0

            else 0
        )


        overall_percentage = round(
            overall_percentage,
            2
        )


        if overall_percentage >= 80:
            overall_status = "Strong"

        elif overall_percentage >= 50:
            overall_status = "Average"

        else:
            overall_status = "Weak"


        # =================================================
        # 6. RECOMMENDED LEVEL
        # =================================================

        difficulty_percentages = {}

        for item in difficulty_performance:

            difficulty_percentages[
                item["difficulty"]
            ] = item["percentage"]


        easy_percentage = (
            difficulty_percentages
            .get("easy")
        )

        medium_percentage = (
            difficulty_percentages
            .get("medium")
        )

        hard_percentage = (
            difficulty_percentages
            .get("hard")
        )


        # Default

        recommended_level = "easy"


        if hard_percentage is not None:

            if hard_percentage < 80:

                recommended_level = "hard"

            else:

                recommended_level = "hard"


        elif medium_percentage is not None:

            if medium_percentage >= 80:

                recommended_level = "hard"

            else:

                recommended_level = "medium"


        elif easy_percentage is not None:

            if easy_percentage >= 80:

                recommended_level = "medium"

            else:

                recommended_level = "easy"


        # =================================================
        # 7. WHAT TO FOCUS ON
        # =================================================

        focus_items = []


        for item in subtopic_performance[:3]:

            if item["status"] == "Weak":

                focus_items.append({

                    "topic":
                        item["topic"],

                    "subtopic":
                        item["subtopic"],

                    "percentage":
                        item["percentage"],

                    "status":
                        "Weak",

                    "message":
                        "Strengthen this subtopic before moving to a higher difficulty level."
                })


            elif item["status"] == "Average":

                focus_items.append({

                    "topic":
                        item["topic"],

                    "subtopic":
                        item["subtopic"],

                    "percentage":
                        item["percentage"],

                    "status":
                        "Average",

                    "message":
                        "Continue practising this subtopic to improve accuracy."
                })


        if not focus_items:

            focus_items.append({

                "topic": "",

                "subtopic": "",

                "percentage":
                    overall_percentage,

                "status":
                    "Strong",

                "message":
                    "Excellent progress. Continue practising and challenge yourself with higher-level questions."
            })


        conn.close()


        # =================================================
        # FINAL RESPONSE
        # =================================================

        return jsonify({

            "success": True,

            "attempt_history":
                attempts,

            "subtopic_performance":
                subtopic_performance,

            "difficulty_performance":
                difficulty_performance,

            "overall": {

                "total_questions":
                    overall_total,

                "correct_answers":
                    overall_correct,

                "score":
                    overall_score,

                "percentage":
                    overall_percentage,

                "status":
                    overall_status
            },

            "recommended_level":
                recommended_level,

            "focus":
                focus_items

        })


    except Exception as e:

        print(
            "AI PERFORMANCE ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
        
# =====================================================
# AI DIAGNOSTIC QUESTION
# =====================================================

@app.route("/api/ai-diagnostic-question", methods=["POST"])
def ai_diagnostic_question():

    try:

        data = request.get_json() or {}

        board = data.get("board")
        class_name = data.get("class_name")
        subject = data.get("subject")
        topic = data.get("topic")
        subtopic = data.get("subtopic")

        question_number = int(
            data.get("question_number", 1)
        )


        # -----------------------------------------
        # VALIDATION
        # -----------------------------------------

        if not board or not class_name or not subject:
            return jsonify({
                "success": False,
                "error": "Board, Class and Subject are required."
            }), 400


        if not topic or not subtopic:
            return jsonify({
                "success": False,
                "error": "Chapter and Subtopic are required."
            }), 400


        # -----------------------------------------
        # GET SYLLABUS
        # -----------------------------------------

        conn = sqlite3.connect("students.db")
        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        c.execute("""
        SELECT syllabus_text
        FROM syllabi
        WHERE board=?
        AND class_name=?
        AND subject=?
        ORDER BY id DESC
        LIMIT 1
        """, (
            board,
            class_name,
            subject
        ))

        row = c.fetchone()

        conn.close()


        if not row:

            return jsonify({
                "success": False,
                "error":
                    "Syllabus not found for selected subject."
            }), 404


        syllabus_text = row["syllabus_text"] or ""


        if not syllabus_text.strip():

            return jsonify({
                "success": False,
                "error": "Uploaded syllabus is empty."
            }), 400


        syllabus_context = syllabus_text[:30000]


        # -----------------------------------------
        # DIAGNOSTIC PROMPT
        # -----------------------------------------

        prompt = f"""
        You are an expert educational assessment designer.
        
        Create ONE diagnostic multiple-choice question
        for a personalised learning system.
        
        STUDENT SELECTION
        
        Board:
        {board}
        
        Class:
        {class_name}
        
        Subject:
        {subject}
        
        Chapter / Topic:
        {topic}
        
        Subtopic:
        {subtopic}
        
        Diagnostic Question Number:
        {question_number}
        
        SUPPLIED SYLLABUS
        -------------------------
        {syllabus_context}
        -------------------------
        
        IMPORTANT RULES:
        
        1. Generate exactly ONE question.
        
        2. The question must be strictly related
           to the selected subject, topic and subtopic.
        
        3. The question must be based only on
           concepts available in the supplied syllabus.
        
        4. Do not introduce concepts outside
           the syllabus.
        
        5. Provide exactly FOUR options.
        
        6. Only ONE option must be correct.
        
        7. The diagnostic test should measure
           the student's understanding of the selected topic.
        
        8. Use a mixture of difficulty across the
           10-question diagnostic test.
        
        9. Questions should gradually cover:
           - basic understanding
           - concept application
           - moderate problem solving
        
        10. Do not make every question extremely difficult.
        
        11. The question must be academically correct.
        
        12. Do not copy textbook questions verbatim.
        
        13. Provide a short hint.
        
        14. Provide a clear explanation.
        
        15. Return ONLY valid JSON.
        
        JSON FORMAT:
        
        {{
            "question": "Question text",
        
            "options": [
                "Option 1",
                "Option 2",
                "Option 3",
                "Option 4"
            ],
        
            "correct_answer": 0,
        
            "hint": "Short helpful hint",
        
            "explanation": "Clear student-friendly explanation",
        
            "topic": "{topic}",
        
            "subtopic": "{subtopic}",
        
            "question_number": {question_number}
        }}
        """


        # -----------------------------------------
        # AI CALL
        # -----------------------------------------
        
        response = client.responses.create(
            model="gpt-5.6-luna",
            input=prompt
        )
        
        result = response.output_text.strip()
        
        # Remove markdown code block
        if result.startswith("```"):
            result = result.replace("```json", "")
            result = result.replace("```", "")
            result = result.strip()
        
        question_data = json.loads(result)


        # -----------------------------------------
        # VALIDATION
        # -----------------------------------------

        if not isinstance(
            question_data.get("options"),
            list
        ):

            raise ValueError(
                "AI returned invalid options."
            )


        if len(
            question_data["options"]
        ) != 4:

            raise ValueError(
                "AI must return exactly 4 options."
            )


        correct_answer = question_data.get("correct_answer")


        if correct_answer not in [
            0, 1, 2, 3
        ]:

            raise ValueError(
                "Invalid correct answer index."
            )


        return jsonify({

            "success": True,

            "question":
                question_data

        })


    except Exception as e:

        print(
            "AI DIAGNOSTIC ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500
        
if __name__ == "__main__":
    _load_feedback()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
