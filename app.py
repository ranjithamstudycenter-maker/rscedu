from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for, abort, jsonify, send_file
import uuid
import os
import razorpay
import zipfile
import hmac
import hashlib
import json
import smtplib
import time
import sqlite3
import csv
import random
import requests
import pandas as pd
import smtplib
from openai import OpenAI
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from openpyxl import load_workbook

from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)
from email.message import EmailMessage
from PyPDF2 import PdfReader


# =====================================================
# RSC PERSISTENT STORAGE
# =====================================================

DATA_DIR = "/var/data"
DB_PATH = os.path.join(DATA_DIR, "students.db")

# =====================================================
# CLASS SCHEDULE AND DEMO REGISTRATION CUTOFF
# =====================================================

CLASS_SCHEDULE = {
    "cbse9": "09:00",
    "cbse10": "19:00",
    "cbse11": "20:00",
    "cbse12": "21:00",

    "engg1": "17:00",
    "engg2": "18:30",
    "engg3": "20:30",

    "control": "10:00",
    "AGS": "11:00",
    "maths": "19:30"
}


CLASS_DURATION_MINUTES = 75


def get_class_schedule_status(course):

    # Current Indian time
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)

    scheduled_time = CLASS_SCHEDULE.get(course)

    if not scheduled_time:
        return {
            "schedule_available": False,
            "waiting_for_teacher": False,
            "registration_closed": False,
            "teacher_not_started": False
        }

    hour, minute = map(int, scheduled_time.split(":"))

    scheduled_start = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0
    )

    registration_cutoff = (
        scheduled_start +
        timedelta(minutes=CLASS_DURATION_MINUTES)
    )

    return {
        "schedule_available": True,
        "scheduled_start": scheduled_start,
        "registration_cutoff": registration_cutoff,
        "waiting_for_teacher": now >= scheduled_start,
        "registration_closed": now >= registration_cutoff,
        "teacher_not_started": now >= registration_cutoff,
        "remaining_seconds": max(
            0,
            int((scheduled_start - now).total_seconds())
        )
    }

def init_db():
    conn = sqlite3.connect(DB_PATH)
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

    # =====================================================
    # STUDENT STATE - FOR MOCK LEADERBOARD
    # =====================================================
    
    try:
        c.execute("""
        ALTER TABLE students
        ADD COLUMN state TEXT DEFAULT ''
        """)
    except:
        pass

    try:
        c.execute("""
            ALTER TABLE students
            ADD COLUMN redemo_paid INTEGER DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    # ==========================================
    # MONTHLY FEEDBACK - PLAN CYCLE
    # ==========================================

    try:
        c.execute("""
            ALTER TABLE students
            ADD COLUMN plan_cycle INTEGER DEFAULT 1
        """)
    except sqlite3.OperationalError:
        pass

    # Store one feedback per student per monthly plan
    c.execute("""
        CREATE TABLE IF NOT EXISTS monthly_teacher_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            course TEXT NOT NULL,
            plan_cycle INTEGER NOT NULL,
            teacher TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            UNIQUE(phone, course, plan_cycle)
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
    
        total_questions INTEGER DEFAULT 50,
        total_marks INTEGER DEFAULT 100,
    
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
    
        total_questions INTEGER DEFAULT 50,
        total_marks INTEGER DEFAULT 100,
    
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
        # =====================================================
        # RSC PRACTICE + MOCK TEST DATABASE
        # =====================================================
        # -----------------------------------------------------
        # PRACTICE MASTER SYLLABUS
        # -----------------------------------------------------
        
        c.execute("""
        CREATE TABLE IF NOT EXISTS practice_syllabus (
        
            id INTEGER PRIMARY KEY AUTOINCREMENT,
        
            board TEXT NOT NULL,
        
            class_name TEXT NOT NULL,
        
            subject TEXT NOT NULL,
        
            topic TEXT NOT NULL,
        
            subtopic TEXT NOT NULL,
        
            display_order INTEGER DEFAULT 0,
        
            active INTEGER DEFAULT 1,
        
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        
            UNIQUE(
                board,
                class_name,
                subject,
                topic,
                subtopic
            )
        
        )
        """)
    # -----------------------------------------------------
    # 1. PRACTICE QUESTION BANK
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_questions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,

        difficulty TEXT NOT NULL,

        question TEXT NOT NULL,

        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,

        correct_answer TEXT NOT NULL,

        explanation TEXT DEFAULT '',
        hint TEXT DEFAULT '',

        marks INTEGER DEFAULT 2,

        active INTEGER DEFAULT 1,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP

    )
    """)
    
    # =====================================================
    # PRACTICE QUESTION DIAGRAM SUPPORT
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE practice_questions
            ADD COLUMN diagram_path TEXT DEFAULT NULL
        """)
    except sqlite3.OperationalError:
        # Column already exists; continue normally.
        pass

    # -----------------------------------------------------
    # PRACTICE EXCEL UPLOAD HISTORY
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_question_uploads (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        filename TEXT NOT NULL,

        board TEXT DEFAULT '',
        class_name TEXT DEFAULT '',
        subject TEXT DEFAULT '',

        total_rows INTEGER DEFAULT 0,
        imported INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,

        easy_count INTEGER DEFAULT 0,
        medium_count INTEGER DEFAULT 0,
        hard_count INTEGER DEFAULT 0,

        uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP

    )
    """)

    # =====================================================
    # PRACTICE QUESTION BANK PERFORMANCE INDEXES
    # =====================================================
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_pq_board
        ON practice_questions(board)
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_pq_class
        ON practice_questions(class_name)
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_pq_subject
        ON practice_questions(subject)
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_pq_difficulty
        ON practice_questions(difficulty)
    """)
    
    c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_pq_filter
        ON practice_questions(
            board,
            class_name,
            subject,
            difficulty
        )
    """)
    # -----------------------------------------------------
    # 2. MOCK TEST CONFIGURATION
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS mock_tests (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        mock_test_no INTEGER NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        test_name TEXT NOT NULL,

        syllabus_scope TEXT DEFAULT '',

        total_questions INTEGER DEFAULT 50,

        total_marks INTEGER DEFAULT 100,

        duration_minutes INTEGER DEFAULT 60,

        price_inr REAL DEFAULT 0,

        attempt_limit INTEGER DEFAULT 1,

        active INTEGER DEFAULT 0,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(
            mock_test_no,
            board,
            class_name,
            subject
        )

    )
    """)

    # =====================================================
    # MOCK TEST CATEGORY COLUMNS - DATABASE SAFETY MIGRATION
    # =====================================================
    
    try:
    
        c.execute("""
            ALTER TABLE mock_tests
            ADD COLUMN mock_type TEXT DEFAULT 'chapter'
        """)
    
    except sqlite3.OperationalError:
    
        # Column already exists
        pass
    
    
    try:
    
        c.execute("""
            ALTER TABLE mock_tests
            ADD COLUMN chapter_scope TEXT DEFAULT ''
        """)
    
    except sqlite3.OperationalError:
    
        # Column already exists
        pass
    
    
    conn.commit()
    # -----------------------------------------------------
    # 3. MOCK QUESTION BANK
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS mock_questions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        mock_test_id INTEGER NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,

        difficulty TEXT NOT NULL,

        question TEXT NOT NULL,

        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,

        correct_answer TEXT NOT NULL,

        explanation TEXT DEFAULT '',
        hint TEXT DEFAULT '',

        marks INTEGER DEFAULT 2,

        active INTEGER DEFAULT 1,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(mock_test_id)
            REFERENCES mock_tests(id)

    )
    """)


    # -----------------------------------------------------
    # 4. PRACTICE EXAM SESSIONS
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_sessions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,

        difficulty TEXT NOT NULL,

        total_questions INTEGER DEFAULT 50,
        total_marks INTEGER DEFAULT 100,

        question_ids TEXT NOT NULL,

        answers TEXT DEFAULT '{}',

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
    # PRACTICE RESULT REVIEW DATA
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE practice_sessions
            ADD COLUMN review_data TEXT DEFAULT '[]'
        """)
    except sqlite3.OperationalError:
        pass

    # -----------------------------------------------------
    # 5. PRACTICE ATTEMPT HISTORY
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_attempts (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,

        difficulty TEXT NOT NULL,

        total_questions INTEGER DEFAULT 50,
        total_marks INTEGER DEFAULT 100,

        correct_answers INTEGER DEFAULT 0,
        incorrect_answers INTEGER DEFAULT 0,
        unanswered INTEGER DEFAULT 0,

        score INTEGER DEFAULT 0,

        percentage REAL DEFAULT 0,

        question_data TEXT,

        completed_at TEXT

    )
    """)


    # -----------------------------------------------------
    # 6. PRACTICE PERFORMANCE
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_performance (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,

        difficulty TEXT NOT NULL,

        total_questions INTEGER DEFAULT 0,

        correct_answers INTEGER DEFAULT 0,

        incorrect_answers INTEGER DEFAULT 0,

        score INTEGER DEFAULT 0,

        percentage REAL DEFAULT 0,

        status TEXT DEFAULT 'New',

        last_attempt TEXT

    )
    """)


    # -----------------------------------------------------
    # 7. MOCK TEST ATTEMPTS
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS mock_attempts (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT NOT NULL,

        mock_test_id INTEGER NOT NULL,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        question_ids TEXT,

        answers TEXT DEFAULT '{}',

        status TEXT DEFAULT 'payment_pending',

        payment_status TEXT DEFAULT 'pending',

        payment_id TEXT,

        total_questions INTEGER DEFAULT 50,

        total_marks INTEGER DEFAULT 100,

        correct_answers INTEGER DEFAULT 0,

        incorrect_answers INTEGER DEFAULT 0,

        unanswered INTEGER DEFAULT 0,

        score INTEGER DEFAULT 0,

        percentage REAL DEFAULT 0,

        rank INTEGER,

        started_at TEXT,

        submitted_at TEXT,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(
            practice_id,
            mock_test_id
        )

    )
    """)


    # -----------------------------------------------------
    # 8. MOCK TEST PERFORMANCE / LEADERBOARD
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS mock_results (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        mock_test_id INTEGER NOT NULL,

        practice_id TEXT NOT NULL,

        score INTEGER DEFAULT 0,

        percentage REAL DEFAULT 0,

        correct_answers INTEGER DEFAULT 0,

        incorrect_answers INTEGER DEFAULT 0,

        unanswered INTEGER DEFAULT 0,

        rank INTEGER,

        submitted_at TEXT,

        UNIQUE(
            mock_test_id,
            practice_id
        )

    )
    """)
    # =====================================================
    # MOCK RESULTS - STUDENT DETAILS FOR LEADERBOARD
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE mock_results
            ADD COLUMN student_phone TEXT DEFAULT ''
        """)
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("""
            ALTER TABLE mock_results
            ADD COLUMN student_name TEXT DEFAULT ''
        """)
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("""
            ALTER TABLE mock_results
            ADD COLUMN student_state TEXT DEFAULT ''
        """)
    except sqlite3.OperationalError:
        pass
        
    # =====================================================
    # MOCK ATTEMPT RESUME STATE
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE mock_attempts
            ADD COLUMN current_question INTEGER DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass   

    # =====================================================
    # MOCK RESULT ANALYSIS DATA
    # =====================================================
    
    try:
        c.execute("""
            ALTER TABLE mock_attempts
            ADD COLUMN review_data TEXT DEFAULT '[]'
        """)
    except sqlite3.OperationalError:
        pass
    # -----------------------------------------------------
    # 9. MOCK TEST PACKAGE PURCHASES
    # -----------------------------------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS mock_purchases (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        practice_id TEXT NOT NULL,

        phone TEXT,

        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,

        amount REAL DEFAULT 1,

        razorpay_order_id TEXT UNIQUE,
        razorpay_payment_id TEXT,

        payment_status TEXT DEFAULT 'pending',

        purchased_at TEXT,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(
            practice_id,
            board,
            class_name,
            subject
        )
    )
    """)
    
    # Save name/state collected before package payment
    for column_name, column_type in [
        ("student_name", "TEXT DEFAULT ''"),
        ("student_state", "TEXT DEFAULT ''")
    ]:
        try:
            c.execute(
                f"ALTER TABLE mock_purchases ADD COLUMN {column_name} {column_type}"
            )
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()
    
       
    # =====================================================
    # RSC PRACTICE SESSION TABLE SAFETY MIGRATION
    # =====================================================
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS practice_sessions (
    
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    
        practice_id TEXT NOT NULL,
    
        board TEXT NOT NULL,
        class_name TEXT NOT NULL,
        subject TEXT NOT NULL,
    
        topic TEXT NOT NULL,
        subtopic TEXT NOT NULL,
    
        difficulty TEXT NOT NULL,
    
        total_questions INTEGER DEFAULT 50,
        total_marks INTEGER DEFAULT 100,
    
        question_ids TEXT NOT NULL,
    
        answers TEXT DEFAULT '{}',
    
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
    conn.close()
# =====================================================
# MOCK TEST DATABASE SCHEMA SAFETY
# =====================================================

def ensure_mock_test_columns():

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check existing columns
    c.execute("PRAGMA table_info(mock_tests)")

    columns = [
        row[1]
        for row in c.fetchall()
    ]

    print("MOCK_TEST COLUMNS:", columns)

    # -------------------------------------------------
    # ADD mock_type IF MISSING
    # -------------------------------------------------

    if "mock_type" not in columns:

        print("ADDING COLUMN: mock_type")

        c.execute("""
            ALTER TABLE mock_tests
            ADD COLUMN mock_type TEXT DEFAULT 'chapter'
        """)

    # -------------------------------------------------
    # ADD chapter_scope IF MISSING
    # -------------------------------------------------

    if "chapter_scope" not in columns:

        print("ADDING COLUMN: chapter_scope")

        c.execute("""
            ALTER TABLE mock_tests
            ADD COLUMN chapter_scope TEXT DEFAULT ''
        """)

    conn.commit()

    # Verify again
    c.execute("PRAGMA table_info(mock_tests)")

    final_columns = [
        row[1]
        for row in c.fetchall()
    ]

    print(
        "MOCK_TEST FINAL COLUMNS:",
        final_columns
    )

    conn.close()
    
# =====================================================
# INITIALIZE DATABASE
# =====================================================

init_db()
ensure_mock_test_columns()

# =====================================================
# RSC FACULTY SALARY DATABASE
# NEW MODULE - DOES NOT MODIFY EXISTING RAZORPAY TABLES
# =====================================================

def init_faculty_salary_db():

    os.makedirs(DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        # -------------------------------------------------
        # 1. CLASS / BATCH MASTER
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS class_batches (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            class_name TEXT NOT NULL,

            course TEXT NOT NULL,

            subject TEXT DEFAULT '',

            faculty_username TEXT NOT NULL,

            schedule TEXT DEFAULT '',

            active_status INTEGER DEFAULT 1,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP

        )
        """)

        # -------------------------------------------------
        # 2. CLASS-WISE TUITION PAYMENT RECORDS
        # Only tuition payments will be stored here.
        # Notes / PDF / Mock Test payments are excluded.
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS class_fee_payments (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            class_id INTEGER NOT NULL,

            student_phone TEXT NOT NULL,

            student_name TEXT DEFAULT '',

            razorpay_order_id TEXT,

            razorpay_payment_id TEXT NOT NULL UNIQUE,

            amount_paise INTEGER NOT NULL,

            refund_amount_paise INTEGER DEFAULT 0,

            payment_status TEXT DEFAULT 'captured',

            payment_date TEXT,

            month_key TEXT NOT NULL,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP

        )
        """)

        # -------------------------------------------------
        # 3. MONTHLY CLASS COLLECTION
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS class_monthly_collection (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            class_id INTEGER NOT NULL,

            month_key TEXT NOT NULL,

            gross_collection_paise INTEGER DEFAULT 0,

            refund_amount_paise INTEGER DEFAULT 0,

            net_collection_paise INTEGER DEFAULT 0,

            rsc_share_paise INTEGER DEFAULT 0,

            faculty_share_paise INTEGER DEFAULT 0,

            generated_at TEXT,

            UNIQUE(class_id, month_key)

        )
        """)

        # -------------------------------------------------
        # 4. CLASS-WISE FACULTY SALARY
        # One faculty can have multiple class salary records.
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS class_salary (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            class_id INTEGER NOT NULL,

            faculty_username TEXT NOT NULL,

            month_key TEXT NOT NULL,

            total_collection_paise INTEGER DEFAULT 0,

            rsc_percentage REAL DEFAULT 40,

            faculty_percentage REAL DEFAULT 60,

            salary_amount_paise INTEGER DEFAULT 0,

            paid_amount_paise INTEGER DEFAULT 0,

            pending_amount_paise INTEGER DEFAULT 0,

            salary_status TEXT DEFAULT 'pending',

            approved_by TEXT DEFAULT '',

            approved_at TEXT,

            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(class_id, month_key)

        )
        """)

        # -------------------------------------------------
        # 5. FACULTY BANK / RAZORPAYX BENEFICIARY MAPPING
        # Do not store raw bank account numbers here.
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS faculty_bank_accounts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            faculty_username TEXT NOT NULL UNIQUE,

            razorpay_contact_id TEXT DEFAULT '',

            razorpay_fund_account_id TEXT DEFAULT '',

            account_last4 TEXT DEFAULT '',

            ifsc_code TEXT DEFAULT '',

            beneficiary_name TEXT DEFAULT '',

            verification_status TEXT DEFAULT 'pending',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT

        )
        """)

        # -------------------------------------------------
        # 6. FACULTY SALARY PAYOUT HISTORY
        # -------------------------------------------------

        c.execute("""
        CREATE TABLE IF NOT EXISTS salary_payouts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            salary_id INTEGER NOT NULL,

            faculty_username TEXT NOT NULL,

            amount_paise INTEGER NOT NULL,

            razorpayx_payout_id TEXT DEFAULT '',

            idempotency_key TEXT NOT NULL UNIQUE,

            payout_status TEXT DEFAULT 'pending',

            initiated_at TEXT,

            completed_at TEXT,

            failure_reason TEXT DEFAULT ''

        )
        """)

        # -------------------------------------------------
        # 6A. MANUAL BANK PAYMENT DETAILS
        # -------------------------------------------------

        payout_columns = [
            ("payment_method", "TEXT DEFAULT 'Bank Transfer'"),
            ("payment_date", "TEXT"),
            ("payment_reference", "TEXT DEFAULT ''"),
            ("payment_notes", "TEXT DEFAULT ''"),
            ("recorded_by", "TEXT DEFAULT 'Admin'")
        ]

        for column_name, column_type in payout_columns:
            try:
                c.execute(
                    f"""
                    ALTER TABLE salary_payouts
                    ADD COLUMN {column_name} {column_type}
                    """
                )
            except sqlite3.OperationalError:
                pass

        # -------------------------------------------------
        # 6B. SALARY APPROVAL STATUS MIGRATION
        # -------------------------------------------------

        c.execute("PRAGMA table_info(class_salary)")

        salary_columns = [
            row[1] for row in c.fetchall()
        ]

        if "approval_status" not in salary_columns:
            c.execute("""
                ALTER TABLE class_salary
                ADD COLUMN approval_status
                TEXT DEFAULT 'pending_review'
            """)
        # -------------------------------------------------
        # 7. INDEXES FOR FASTER SEARCH
        # -------------------------------------------------

        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_class_fee_month
        ON class_fee_payments(class_id, month_key)
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_month
        ON class_salary(month_key)
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_payout_salary
        ON salary_payouts(salary_id)
        """)

        conn.commit()

        print("RSC FACULTY SALARY DATABASE INITIALIZED")

    except Exception as e:

        conn.rollback()

        print("FACULTY SALARY DATABASE ERROR:", str(e))

        raise

    finally:

        conn.close()


# Initialize the new salary database tables
init_faculty_salary_db()


# -------------------- APP INIT --------------------
app = Flask(__name__)

# =====================================================
# PRACTICE QUESTION DIAGRAM STORAGE
# =====================================================

PRACTICE_DIAGRAM_FOLDER = "/var/data/practice_diagrams"

os.makedirs(
    PRACTICE_DIAGRAM_FOLDER,
    exist_ok=True
)

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
        "class_live": False
        
    },
    "Balakumar10": {
        "password": "M10@2026",
        "course": "cbse10",
        "meet_link": "",
        "active": True,
        "class_live": False
       
    },
    "Balakumar12": {
        "password": "M12@2026",
        "course": "cbse12",
        "meet_link": "",
        "active": True,
        "class_live": False
        
    },
    "faculty1": {
        "password": "",
        "course": "cbse12",
        "meet_link": "",
        "active": False,
        "class_live": False
        
    },
    "faculty2": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False
            
    },
    "faculty3": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False
            
    },
    "faculty4": {
            "password": "",
            "course": "cbse12",
            "meet_link": "",
            "active": False
            
    }
}

def get_faculty_feedback_list(username):
    if isinstance(feedback_db, list):
        return [
            f for f in feedback_db
            if f.get("teacher") == username
        ]

    return feedback_db.get(username, [])
    
def get_faculty_feedback_summary(username):

    feedbacks = get_faculty_feedback_list(username)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT feedback_review_after
        FROM faculty_status
        WHERE username=?
    """, (username,))

    row = c.fetchone()
    conn.close()

    review_after = row[0] if row and row[0] is not None else 0

    feedbacks = feedbacks[review_after:]

    ratings = []

    for f in feedbacks:
        try:
            rating = int(f.get("rating", 0))
            if 1 <= rating <= 5:
                ratings.append(rating)
        except (TypeError, ValueError):
            continue

    total_feedbacks = len(ratings)

    low_count = sum(1 for r in ratings if r < 3)

    avg_rating = (
        round(sum(ratings) / total_feedbacks, 2)
        if total_feedbacks else 0
    )

    warning_msg = ""

    if low_count >= 6 and total_feedbacks < 10:
        warning_msg = (
            "Warning: Multiple low ratings detected. "
            "Improve teaching quality immediately."
        )

    deactivate = (
        total_feedbacks >= 10
        and avg_rating < 3
    )

    return {
        "total_feedbacks": total_feedbacks,
        "low_count": low_count,
        "average_rating": avg_rating,
        "warning_msg": warning_msg,
        "deactivate": deactivate
    }

def init_faculty_status_table():

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS faculty_status (
            username TEXT PRIMARY KEY,
            active_status INTEGER DEFAULT 1,
            status_reason TEXT DEFAULT '',
            updated_at TEXT,
            feedback_review_after INTEGER DEFAULT 0
        )
    """)
        # Existing database upgrade
    c.execute("PRAGMA table_info(faculty_status)")
    columns = [row[1] for row in c.fetchall()]

    if "feedback_review_after" not in columns:
        c.execute("""
            ALTER TABLE faculty_status
            ADD COLUMN feedback_review_after INTEGER DEFAULT 0
        """)
        
    for username, details in teachers.items():

        active = 1 if details.get("active", True) else 0

        c.execute("""
            INSERT OR IGNORE INTO faculty_status
            (username, active_status, status_reason, updated_at)
            VALUES (?, ?, '', ?)
        """, (
            username,
            active,
            datetime.now().isoformat()
        ))

    conn.commit()

    c.execute("""
        SELECT username, active_status
        FROM faculty_status
    """)

    for username, active in c.fetchall():
        if username in teachers:
            teachers[username]["active"] = bool(active)

    conn.close()


def set_faculty_status(username, active, reason=""):

    if username not in teachers:
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    feedback_count = len(get_faculty_feedback_list(username))

    c.execute("""
        INSERT INTO faculty_status
        (username, active_status, status_reason, updated_at,
         feedback_review_after)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username)
        DO UPDATE SET
            active_status = excluded.active_status,
            status_reason = excluded.status_reason,
            updated_at = excluded.updated_at,
            feedback_review_after =
                CASE
                    WHEN excluded.active_status = 1
                    THEN excluded.feedback_review_after
                    ELSE faculty_status.feedback_review_after
                END
    """, (
        username,
        1 if active else 0,
        reason,
        datetime.now().isoformat(),
        feedback_count
    ))

    conn.commit()
    conn.close()

    teachers[username]["active"] = bool(active)
        # Stop the course live class only when no other
    # active faculty is assigned to the same course.
    if not active:

        course = teachers[username].get("course")

        other_active = any(
            name != username
            and details.get("course") == course
            and details.get("active", True)
            for name, details in teachers.items()
        )

        if not other_active and course:

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            c.execute("""
                UPDATE live_classes
                SET live=0,
                    meet_link=''
                WHERE course=?
            """, (course,))

            conn.commit()
            conn.close()

            teachers[username]["class_live"] = False
            teachers[username]["meet_link"] = ""

init_faculty_status_table()

COURSE_TEACHERS = {

    "cbse9": "Balakumar9",
    "cbse10": "Balakumar10",
    "cbse11": "Balakumar",
    "cbse12": "Balakumar12",

    "engg1": "Balakumar",
    "engg2": "Balakumar",
    "engg3": "Balakumar",

    "control": "Balakumar",
    "AGS": "Balakumar",
    "Maths": "Balakumar"

}

# ==========================================
# GET OR CREATE CLASS BATCH FOR SALARY
# ==========================================

def get_or_create_salary_class(course):

    faculty_username = COURSE_TEACHERS.get(course)

    if not faculty_username:
        raise ValueError(
            f"No faculty assigned for course: {course}"
        )

    if faculty_username not in teachers:
        raise ValueError(
            f"Faculty account not found: {faculty_username}"
        )

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:

        c.execute("""
            SELECT id
            FROM class_batches
            WHERE course=?
            ORDER BY id
            LIMIT 1
        """, (course,))

        row = c.fetchone()

        if row:

            class_id = row[0]

            c.execute("""
                UPDATE class_batches
                SET faculty_username=?
                WHERE id=?
            """, (faculty_username, class_id))

        else:

            class_name = {
                "cbse9": "CBSE Class 9",
                "cbse10": "CBSE Class 10",
                "cbse12": "CBSE Class 12"
            }.get(course, course)

            c.execute("""
                INSERT INTO class_batches
                (
                    class_name,
                    course,
                    subject,
                    faculty_username,
                    schedule,
                    active_status
                )
                VALUES (?, ?, '', ?, '', 1)
            """, (
                class_name,
                course,
                faculty_username
            ))

            class_id = c.lastrowid

        conn.commit()

        return class_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

def generate_monthly_class_salary(month_key=None):

    if not month_key:
        month_key = datetime.now().strftime("%Y-%m")

    # Validate month format
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        raise ValueError("Invalid month format. Use YYYY-MM")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    generated_count = 0

    try:
        # Get classes having captured payments in selected month
        c.execute("""
            SELECT
                p.class_id,
                SUM(p.amount_paise),
                SUM(p.refund_amount_paise)
            FROM class_fee_payments p
            WHERE p.month_key = ?
              AND p.payment_status = 'captured'
            GROUP BY p.class_id
        """, (month_key,))

        collection_rows = c.fetchall()

        for class_id, gross_amount, refund_amount in collection_rows:

            gross_amount = int(gross_amount or 0)
            refund_amount = int(refund_amount or 0)

            net_collection = max(
                gross_amount - refund_amount, 0
            )

            # 60% Faculty share; remaining 40% goes to RSC
            faculty_share = round(net_collection * 0.60)
            rsc_share = net_collection - faculty_share

            # Get assigned faculty
            c.execute("""
                SELECT faculty_username
                FROM class_batches
                WHERE id = ?
            """, (class_id,))

            faculty_row = c.fetchone()

            if not faculty_row:
                print("SALARY SKIPPED: Class not found", class_id)
                continue

            faculty_username = faculty_row[0]

            if not faculty_username:
                print("SALARY SKIPPED: Faculty not assigned", class_id)
                continue

            # Update monthly collection
            c.execute("""
                INSERT INTO class_monthly_collection (
                    class_id,
                    month_key,
                    gross_collection_paise,
                    refund_amount_paise,
                    net_collection_paise,
                    rsc_share_paise,
                    faculty_share_paise,
                    generated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)

                ON CONFLICT(class_id, month_key)
                DO UPDATE SET
                    gross_collection_paise = excluded.gross_collection_paise,
                    refund_amount_paise = excluded.refund_amount_paise,
                    net_collection_paise = excluded.net_collection_paise,
                    rsc_share_paise = excluded.rsc_share_paise,
                    faculty_share_paise = excluded.faculty_share_paise,
                    generated_at = CURRENT_TIMESTAMP
            """, (
                class_id,
                month_key,
                gross_amount,
                refund_amount,
                net_collection,
                rsc_share,
                faculty_share
            ))

            # Create or update faculty salary.
            # IMPORTANT: Existing paid amount is preserved.
            c.execute("""
                INSERT INTO class_salary (
                    class_id,
                    faculty_username,
                    month_key,
                    total_collection_paise,
                    rsc_percentage,
                    faculty_percentage,
                    salary_amount_paise,
                    paid_amount_paise,
                    pending_amount_paise,
                    salary_status,
                    generated_at
                )
                VALUES (?, ?, ?, ?, 40, 60, ?, 0, ?, 'pending',
                        CURRENT_TIMESTAMP)

                ON CONFLICT(class_id, month_key)
                DO UPDATE SET
                    faculty_username = excluded.faculty_username,
                    total_collection_paise = excluded.total_collection_paise,
                    rsc_percentage = 40,
                    faculty_percentage = 60,
                    salary_amount_paise = excluded.salary_amount_paise,
                    approval_status = 'pending_review',
                    approved_by = '',
                    approved_at = NULL,
                    pending_amount_paise = MAX(
                        0,
                        excluded.salary_amount_paise
                        - class_salary.paid_amount_paise
                    ),

                    salary_status = CASE
                        WHEN class_salary.paid_amount_paise
                             >= excluded.salary_amount_paise
                            THEN 'paid'
                        WHEN class_salary.paid_amount_paise > 0
                            THEN 'partial'
                        ELSE 'pending'
                    END,

                    generated_at = CURRENT_TIMESTAMP
            """, (
                class_id,
                faculty_username,
                month_key,
                net_collection,
                faculty_share,
                faculty_share
            ))

            generated_count += 1

        conn.commit()

        print(
            "MONTHLY SALARY GENERATED:",
            month_key,
            "Classes:",
            generated_count
        )

        return generated_count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


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

# =====================================================
# ANONYMOUS PRACTICE ID
# =====================================================

def get_practice_id():

    # First use the long-lived browser cookie
    practice_id = request.cookies.get(
        "rsc_practice_id"
    )

    # Backward compatibility:
    # use old Flask session ID if cookie is not available
    if not practice_id:
        practice_id = session.get(
            "practice_id"
        )

    # Create a new ID only if neither exists
    if not practice_id:
        practice_id = str(uuid.uuid4())

    # Keep the same ID in Flask session too
    session["practice_id"] = practice_id

    return practice_id


@app.after_request
def persist_practice_id(response):

    practice_id = session.get(
        "practice_id"
    )

    if practice_id:

        response.set_cookie(
            "rsc_practice_id",
            practice_id,

            # 10 years
            max_age=10 * 365 * 24 * 60 * 60,

            httponly=True,
            secure=True,
            samesite="Lax"
        )

    return response
    
def get_user(phone):

    user = {
        "name": "",
        "phone": phone,
        "demo_done": {},
        "enrolled": {},
        "hours_used": {},
        "max_hours": {},
        "redemo_paid": {},
        "plan_cycle": {},
        "monthly_feedback_submitted": {},
    }

    # 🔥 ALWAYS LOAD FROM DB
    conn = sqlite3.connect("/var/data/students.db")
    c = conn.cursor()

    c.execute("""
        SELECT course, demo_done, enrolled,
               hours_used, max_hours, redemo_paid,
               plan_cycle, name
        FROM students
        WHERE phone=?
    """, (phone,))

    rows = c.fetchall()

    for r in rows:
        course = r[0]
    
        user["demo_done"][course] = bool(r[1])
        user["enrolled"][course] = bool(r[2])
        user["hours_used"][course] = r[3]
        user["max_hours"][course] = r[4]
        user["redemo_paid"][course] = bool(r[5])
        user["plan_cycle"][course] = int(r[6] or 1)
        user["name"] = r[7] or user["name"]

    # Check whether feedback is submitted for current plan cycle
    for course, cycle in user["plan_cycle"].items():

        c.execute("""
            SELECT 1
            FROM monthly_teacher_feedback
            WHERE phone = ?
              AND course = ?
              AND plan_cycle = ?
            LIMIT 1
        """, (phone, course, cycle))

        user["monthly_feedback_submitted"][course] = (
            c.fetchone() is not None
        )

    conn.close()

    return user


def available_seats(course):
    d = seat_data.get(course, {"total": 30, "booked": 0})
    return d["total"] - d["booked"]

# -------------------- AUTH: OTP --------------------

@app.route("/save-user", methods=["POST"])
def save_user():

    data = request.get_json(silent=True) or {}

    phone = (data.get("phone") or "").strip()
    name = (data.get("name") or "").strip()
    course = (data.get("course") or "").strip()

    if not phone or not name or not course:
        return jsonify({
            "error": "Name, phone and course are required."
        }), 400

    session["phone"] = phone

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        # New student: create initial record.
        # Existing student: update only verified details.
        # Preserve demo_done, enrolled, hours_used,
        # max_hours, payment_amount and join_time.

        c.execute("""
            INSERT INTO students (
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
            VALUES (?, ?, ?, 1, 1, 0, 0, 0, 0, 0, ?)

            ON CONFLICT(phone, course)
            DO UPDATE SET
                name = excluded.name,
                otp_verified = 1,
                demo_allowed = 1,
                last_updated = excluded.last_updated
        """, (
            name,
            phone,
            course,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))

        conn.commit()

        return jsonify({
            "status": "ok",
            "otp_verified": True,
            "demo_allowed": True
        })

    except Exception as e:

        conn.rollback()
        print("SAVE USER ERROR:", str(e))

        return jsonify({
            "error": "Unable to save student details."
        }), 500

    finally:
        conn.close()

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
        # CHECK EXISTING OTP VERIFICATION
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT otp_verified
        FROM students
        WHERE phone = ? AND course = ?
    """, (phone, course))

    otp_row = c.fetchone()
    otp_verified = bool(otp_row and otp_row[0] == 1)

    conn.close()

    # ✅ GET LIVE MEET LINK
    meet_link = get_active_meet_link(course)

    # ✅ IF DEMO ALREADY COMPLETED
    # still allow reopening link
    if user["demo_done"].get(course):

        return jsonify({
            "demo_done": True,
            "otp_verified": otp_verified,
            "meet_link": meet_link
        })

    
    # Check whether new demo registration is closed
    schedule = get_class_schedule_status(course)

    if schedule.get("registration_closed", False) and not meet_link:

        return jsonify({
            "error": "Today's demo class is closed.",
            "demo_done": False,
            "otp_verified": otp_verified,
            "meet_link": "",
            "registration_closed": True,
            "message": "Teacher Not Started the Class Today"
                if schedule.get("teacher_not_started", False)
                else "Today's demo class is closed."
        }), 403

    # Normal response
    return jsonify({
        "demo_done": False,
        "otp_verified": otp_verified,
        "meet_link": "",
        "registration_closed": False
       
   
    })

@app.route("/api/demo-complete", methods=["POST"])
def demo_complete():

    data = request.get_json(silent=True) or {}

    phone = data.get("phone") or session.get("phone")
    course = data.get("course")
    demo_stage = data.get("demo")

    if not phone:
        return jsonify({"error": "Unauthorized"}), 401

    if not course:
        return jsonify({"error": "Course missing"}), 400

    # This API is only for starting/registering a demo.
    # Demo completion is controlled by verified attendance.

    if demo_stage != "start":
        return jsonify({
            "error": "Demo completion is controlled by attendance."
        }), 403

    conn = sqlite3.connect("/var/data/students.db", timeout=30)
    c = conn.cursor()

    try:

        # ==========================================
        # 1. CHECK EXISTING STUDENT RECORD
        # ==========================================

        c.execute("""
            SELECT
                demo_done,
                otp_verified,
                demo_allowed,
                redemo_paid
            FROM students
            WHERE phone=? AND course=?
        """, (phone, course))

        row = c.fetchone()

        # ==========================================
        # 2. STUDENT RECORD NOT FOUND
        # ==========================================

        if not row:

            return jsonify({
                "error": "Student record not found. Please verify OTP first."
            }), 404

        demo_done, otp_verified, demo_allowed, redemo_paid = row

        # ==========================================
        # 3. OTP AND DEMO ACCESS VALIDATION
        # ==========================================

        # First free demo: OTP required.
        # Paid Re-Demo: previous payment authorizes access.
        
        if not redemo_paid and (
            not otp_verified or not demo_allowed
        ):
            return jsonify({
                "error": "Demo access not authorized."
            }), 403

            return jsonify({
                "error": "Demo access not authorized."
            }), 403

        # ==========================================
        # 4. CHECK ALREADY COMPLETED DEMO
        # ==========================================

        if demo_done:

            return jsonify({
                "error": "Demo already completed.",
                "demo_done": True
            }), 400

        # ==========================================
        # 5. DEMO START ACCEPTED
        # ==========================================

        # Do not mark demo_done = 1 here.
        # Attendance logic will complete the demo.

        return jsonify({
            "status": "ready",
            "demo_done": False,
            "message": "Demo start request accepted."
        }), 200

    except Exception as e:

        print("DEMO START ERROR:", e)

        return jsonify({
            "error": "Unable to start demo."
        }), 500

    finally:
        conn.close()
        
@app.route("/api/redemo/create-order", methods=["POST"])
def create_redemo_order():

    phone = session.get("phone")

    if not phone:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json() or {}
    course = data.get("course")

    if course not in price_per_hour:
        return jsonify({"error": "Invalid course"}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT name, demo_done, redemo_paid
        FROM students
        WHERE phone=? AND course=?
    """, (phone, course))

    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Student not found"}), 404

    name, demo_done, redemo_paid = row

    if not demo_done:
        return jsonify({"error": "Demo is not completed"}), 403

    if redemo_paid:
        return jsonify({"error": "Re-Demo already paid"}), 400

    try:
        with open("admin.json") as f:
            keys = json.load(f)

        client = razorpay.Client(
            auth=(
                keys["razorpay_key"],
                keys["razorpay_secret"]
            )
        )

        order = client.order.create({
            "amount": 100,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "purpose": "RE_DEMO",
                "course": course,
                "phone": phone
            }
        })

        session["pending_redemo_course"] = course
        session["pending_redemo_order"] = order["id"]

        return jsonify({
            "order_id": order["id"],
            "amount": 10000,
            "razorpay_key": keys["razorpay_key"],
            "name": name
        })

    except Exception as e:

        print("RE-DEMO ORDER ERROR:", str(e))

        return jsonify({
            "error": "Unable to start payment"
        }), 500

@app.route(
    "/api/redemo/payment-success",
    methods=["POST"]
)
def redemo_payment_success():

    phone = session.get("phone")

    if not phone:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}

    course = session.get("pending_redemo_course")
    order_id = data.get("order_id")
    payment_id = data.get("payment_id")
    signature = data.get("signature")

    if not course or course not in price_per_hour:
        return jsonify({"error": "Invalid course"}), 400

    if order_id != session.get("pending_redemo_order"):
        return jsonify({"error": "Invalid order"}), 400

    if not payment_id or not signature:
        return jsonify({"error": "Invalid payment details"}), 400

    try:

        with open("admin.json") as f:
            keys = json.load(f)

        client = razorpay.Client(
            auth=(
                keys["razorpay_key"],
                keys["razorpay_secret"]
            )
        )

        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })

        payment = client.payment.fetch(payment_id)

        if (
            payment.get("order_id") != order_id
            or int(payment.get("amount", 0)) != 100
            or payment.get("status") != "captured"
        ):
            return jsonify({
                "error": "Payment not captured"
            }), 400

    except Exception as e:

        print("RE-DEMO PAYMENT VERIFICATION ERROR:", str(e))

        return jsonify({
            "error": "Payment verification failed"
        }), 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        c.execute("""
            UPDATE students
            SET demo_done=0,
                redemo_paid=1,
                last_updated=?
            WHERE phone=?
              AND course=?
              AND demo_done=1
              AND redemo_paid=0
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            phone,
            course
        ))

        if c.rowcount != 1:
            conn.rollback()
            return jsonify({
                "error": "Student demo status changed. Contact support."
            }), 409

        conn.commit()

    except Exception as e:

        conn.rollback()
        print("RE-DEMO DATABASE ERROR:", str(e))

        return jsonify({"error": "Unable to update demo"}), 500

    finally:
        conn.close()

    session.pop("pending_redemo_course", None)
    session.pop("pending_redemo_order", None)

    return jsonify({
        "status": "success",
        "payment_status": "Paid",
        "demo_done": False,
        "redemo_paid": True
    })

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

    # ==========================================
    # MONTHLY RENEWAL VALIDATION
    # ==========================================

    is_renewal = False
    current_plan_cycle = 1

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:
        c.execute("""
            SELECT enrolled, hours_used, max_hours, plan_cycle
            FROM students
            WHERE phone=? AND course=?
        """, (phone, course))

        student = c.fetchone()

        if student:
            enrolled, hours_used, max_hours, plan_cycle = student

            current_plan_cycle = int(plan_cycle or 1)

            if enrolled:
                if hours_used < max_hours:
                    conn.close()
                    return jsonify({
                        "error": "Your current monthly plan is still active."
                    }), 403

                is_renewal = True

                # Verify feedback for the current plan cycle
                c.execute("""
                    SELECT 1
                    FROM monthly_teacher_feedback
                    WHERE phone=?
                      AND course=?
                      AND plan_cycle=?
                    LIMIT 1
                """, (
                    phone,
                    course,
                    current_plan_cycle
                ))

                if not c.fetchone():
                    conn.close()
                    return jsonify({
                        "error": "Please submit teacher feedback before renewing."
                    }), 403

        # Seat check only for new enrolments
        if not is_renewal and available_seats(course) <= 0:
            conn.close()
            return jsonify({"error": "Seats full"}), 403

    except Exception as e:
        conn.close()
        print("MONTHLY RENEWAL VALIDATION ERROR:", e)

        return jsonify({
            "error": "Unable to validate monthly plan."
        }), 500

    conn.close()

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

    # Save pending enrollment details
    user["name"] = name
    
    session["pending_course"] = course
    session["pending_order_id"] = order["id"]
    session["pending_amount"] = amount
    session["pending_plan_cycle"] = current_plan_cycle
    session["pending_is_renewal"] = is_renewal

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

    data = request.get_json() or {}

    course = session.get("pending_course")
    order_id = data.get("order_id")
    payment_id = data.get("payment_id")
    signature = data.get("signature")
    
    # Validate pending order
    if not course or course not in price_per_hour:
        return jsonify({"error": "Invalid pending course"}), 400
    
    if (
        not order_id
        or not payment_id
        or not signature
        or order_id != session.get("pending_order_id")
    ):
        return jsonify({"error": "Invalid payment details"}), 400
    
    amount = session.get("pending_amount")
    
    if amount is None:
        return jsonify({"error": "Payment amount not found"}), 400
    
    # Verify Razorpay payment signature
    try:
        with open("admin.json") as f:
            keys = json.load(f)
    
        client = razorpay.Client(
            auth=(keys["razorpay_key"], keys["razorpay_secret"])
        )
    
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
    
    except Exception as e:
        print("RAZORPAY SIGNATURE VERIFICATION ERROR:", str(e))
        return jsonify({"error": "Payment verification failed"}), 400

        # ==========================================
    # VERIFY MONTHLY PLAN CYCLE
    # ==========================================

    pending_cycle = session.get("pending_plan_cycle")
    is_renewal = session.get("pending_is_renewal", False)

    if pending_cycle is None:
        return jsonify({
            "error": "Payment plan information missing."
        }), 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:
        c.execute("""
            SELECT enrolled, hours_used, max_hours, plan_cycle
            FROM students
            WHERE phone=? AND course=?
        """, (phone, course))

        student = c.fetchone()

        if is_renewal:

            if not student:
                return jsonify({
                    "error": "Student record not found."
                }), 404

            enrolled, hours_used, max_hours, current_cycle = student
            current_cycle = int(current_cycle or 1)

            if current_cycle != int(pending_cycle):
                return jsonify({
                    "error": "This payment order belongs to an old plan cycle."
                }), 409

            if not enrolled or hours_used < max_hours:
                return jsonify({
                    "error": "Current monthly plan is not completed."
                }), 403

            c.execute("""
                SELECT 1
                FROM monthly_teacher_feedback
                WHERE phone=?
                  AND course=?
                  AND plan_cycle=?
                LIMIT 1
            """, (phone, course, current_cycle))

            if not c.fetchone():
                return jsonify({
                    "error": "Teacher feedback is required before renewal."
                }), 403

        elif student and student[0]:
            return jsonify({
                "error": "An active enrolment already exists."
            }), 409

    except Exception as e:
        print("PAYMENT CYCLE VALIDATION ERROR:", e)

        return jsonify({
            "error": "Unable to verify monthly plan."
        }), 500

    finally:
        conn.close()
    user = get_user(phone)
  
       # ==========================================
    # ACTIVATE NEXT MONTHLY PLAN
    # ==========================================

    new_plan_cycle = (
        int(pending_cycle) + 1
        if is_renewal
        else int(pending_cycle)
    )

    user["enrolled"][course] = True
    user["hours_used"][course] = 0
    user["max_hours"][course] = classes_per_month

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        c.execute("""
            UPDATE students
            SET name=?,
                demo_done=1,
                enrolled=1,
                hours_used=0,
                max_hours=?,
                payment_amount=?,
                plan_cycle=?,
                last_updated=?
            WHERE phone=? AND course=?
        """, (
            user.get("name", ""),
            classes_per_month,
            amount,
            new_plan_cycle,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            phone,
            course
        ))

        # Insert only if student record does not exist
        if c.rowcount == 0:

            c.execute("""
                INSERT INTO students (
                    phone, course, name,
                    demo_done, enrolled,
                    hours_used, max_hours,
                    payment_amount, plan_cycle,
                    last_updated
                )
                VALUES (?, ?, ?, 1, 1, 0, ?, ?, ?, ?)
            """, (
                phone,
                course,
                user.get("name", ""),
                classes_per_month,
                amount,
                new_plan_cycle,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ))

        conn.commit()

        user["plan_cycle"][course] = new_plan_cycle

    except Exception as e:

        conn.rollback()
        print("MONTHLY PLAN UPDATE ERROR:", e)

        return jsonify({
            "error": "Unable to activate monthly plan."
        }), 500

    finally:
        conn.close()

    
    # ==========================================
    # CLASS-WISE TUITION PAYMENT RECORD
    # Only confirmed CBSE tuition courses
    # ==========================================

    salary_tracked_courses = (
        "cbse9",
        "cbse10",
        "cbse12"
    )

    if course in salary_tracked_courses:

        try:

            # Get the assigned faculty class ID
            class_id = get_or_create_salary_class(course)

            amount_paise = int(round(float(amount) * 100))

            payment_date = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            month_key = datetime.now().strftime("%Y-%m")

            salary_conn = sqlite3.connect(
                DB_PATH,
                timeout=30
            )

            salary_c = salary_conn.cursor()

            # INSERT OR IGNORE prevents duplicate payment IDs
            salary_c.execute("""
                INSERT OR IGNORE INTO class_fee_payments
                (
                    class_id,
                    student_phone,
                    student_name,
                    razorpay_order_id,
                    razorpay_payment_id,
                    amount_paise,
                    refund_amount_paise,
                    payment_status,
                    payment_date,
                    month_key
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 'captured', ?, ?)
            """, (
                class_id,
                phone,
                user.get("name", ""),
                order_id,
                payment_id,
                amount_paise,
                payment_date,
                month_key
            ))

            salary_conn.commit()

            if salary_c.rowcount == 1:
                print(
                    "CLASS-WISE PAYMENT RECORDED:",
                    course,
                    payment_id,
                    amount_paise
                )
            else:
                print(
                    "PAYMENT ALREADY RECORDED:",
                    payment_id
                )

            salary_conn.close()

        except Exception as e:

            print(
                "CLASS-WISE SALARY PAYMENT RECORD ERROR:",
                str(e)
            )

    # Increment seat count only for new enrolments
    if not is_renewal and course in seat_data:
        seat_data[course]["booked"] = min(
            seat_data[course]["booked"] + 1,
            seat_data[course]["total"]
        )

    # Save to CSV
    try:
        file = os.path.join("/var/data", "payments.csv")
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
                amount
            ])
    except Exception as e:
        print("CSV error:", e)

        # =========================================
    # 🔥 FACULTY PAYMENT SPLIT
    # =========================================

    teacher = COURSE_TEACHERS.get(course, "Unknown")
    # Calculate salary split using actual amount paid
    faculty_share = round(amount * 0.60, 2)
    admin_share = round(amount * 0.40, 2)

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
    # ==========================================
    # CLEAR COMPLETED PAYMENT SESSION
    # ==========================================

    session.pop("pending_course", None)
    session.pop("pending_order_id", None)
    session.pop("pending_amount", None)
    session.pop("pending_plan_cycle", None)
    session.pop("pending_is_renewal", None)
    
    return jsonify({
        "status": "success",
        "enrolled": True,
        "hours_remaining": user["max_hours"][course],
        "plan_cycle": new_plan_cycle,
        "is_renewal": is_renewal
    })

# =====================================================
# RSC SUBJECT PACKAGE - PRACTICE + MOCK
# =====================================================

# =====================================================
# RSC SUBJECT PACKAGE - PRACTICE + MOCK
# =====================================================

# Temporary package price
# Final pricing can be made class + subject wise later
# =====================================================
# RSC SUBJECT PACKAGE PRICES
# CLASS + SUBJECT WISE
# =====================================================

PACKAGE_PRICES = {

    "9": {
        "math": 299,
        "science": 299,
        "social_science": 299,
        "english": 299
    },

    "10": {
        "math": 1,
        "science": 1,
        "social_science": 299,
        "english": 299
    },

    "11": {
        "math": 299,
        "physics": 299,
        "chemistry": 299,
        "biology": 299
    },

    "12": {
        "math": 299,
        "physics": 299,
        "chemistry": 299,
        "biology": 299
    }

}

PACKAGE_SUBJECTS = {

    "math": "Mathematics",

    "science": "Science",

    "social_science": "Social Science",

    "english": "English",

    "physics": "Physics",

    "chemistry": "Chemistry",

    "biology": "Biology"

}
# =====================================================
# CLASS-WISE SUBJECT VALIDATION
# =====================================================

PACKAGE_CLASS_SUBJECTS = {

    "9": [
        "math",
        "science",
        "social_science",
        "english"
    ],

    "10": [
        "math",
        "science",
        "social_science",
        "english"
    ],

    "11": [
        "math",
        "physics",
        "chemistry",
        "biology"
    ],

    "12": [
        "math",
        "physics",
        "chemistry",
        "biology"
    ]

}


# =====================================================
# RSC SUBJECT PACKAGE - CREATE ORDER
# PRACTICE + MOCK TEST
# =====================================================

@app.route("/api/mock/create-order", methods=["POST"])
def mock_create_order():

    practice_id = get_practice_id()

    data = request.get_json() or {}

    subject = str(
        data.get("subject", "")
    ).strip()

    board = str(
        data.get("board", "")
    ).strip()

    class_name = str(
        data.get("class_name", "")
    ).strip()

    student_name = str(
        data.get("name", "")
    ).strip()[:80]

    student_state = str(
        data.get("state", "")
    ).strip()[:80]

    if not student_name or not student_state:
        return jsonify({
            "success": False,
            "error": "Student name and state are required."
        }), 400

    # -------------------------------------------------
    # VALIDATION
    # -------------------------------------------------

    if subject not in PACKAGE_SUBJECTS:

        return jsonify({
            "success": False,
            "error": "Invalid subject package."
        }), 400
    # -------------------------------------------------
    # CLASS-WISE SUBJECT VALIDATION
    # -------------------------------------------------
    
    normalized_class = (
        class_name
        .strip()
        .lower()
        .replace("class", "")
        .strip()
    )
    
    allowed_subjects = PACKAGE_CLASS_SUBJECTS.get(
        normalized_class,
        []
    )
    
    if subject not in allowed_subjects:
    
        return jsonify({
            "success": False,
            "error":
                "This subject is not available for the selected class."
        }), 400
    if not board or not class_name:

        return jsonify({
            "success": False,
            "error": "Board and Class are required."
        }), 400

    subject_name = PACKAGE_SUBJECTS[subject]
    package_price = PACKAGE_PRICES.get(
        normalized_class,
        {}
    ).get(
        subject
    )
    
    if package_price is None:

        
        return jsonify({
            "success": False,
            "error":
                "Package price is not configured for this class and subject."
        }), 400
    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------

    conn = sqlite3.connect(
        "/var/data/students.db"
    )

    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # -------------------------------------------------
    # CHECK EXISTING PURCHASE
    # -------------------------------------------------

    c.execute("""
        SELECT
            id,
            payment_status,
            razorpay_payment_id
        FROM mock_purchases
        WHERE practice_id=?
          AND board=?
          AND class_name=?
          AND subject=?
        LIMIT 1
    """, (
        practice_id,
        board,
        class_name,
        subject_name
    ))

    existing = c.fetchone()

    if existing and existing["payment_status"] == "paid":

        conn.close()

        return jsonify({
            "success": True,
            "already_paid": True,
            "unlocked": True,
            "package_type": "practice_mock",
            "message":
                "Practice + Mock Test package is already unlocked."
        })
      
               
    
    # -------------------------------------------------
    # LOAD RAZORPAY
    # -------------------------------------------------

    try:

        with open("admin.json") as f:
            keys = json.load(f)

        client = razorpay.Client(
            auth=(
                keys["razorpay_key"],
                keys["razorpay_secret"]
            )
        )

        # -------------------------------------------------
        # CREATE ₹299 ORDER
        # -------------------------------------------------

        order = client.order.create({

            "amount": package_price * 100,

            "currency": "INR",

            "payment_capture": 1,

            "notes": {

                "type": "practice_mock_package",

                "practice_id": practice_id,

                "subject": subject_name,

                "board": board,

                "class_name": class_name

            }

        })

    except Exception as e:

        conn.close()

        print(
            "PACKAGE RAZORPAY CREATE ORDER ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error":
                "Unable to start payment."
        }), 500

    # -------------------------------------------------
    # SAVE PENDING PAYMENT
    # -------------------------------------------------

    try:

        
        c.execute("""
            INSERT OR REPLACE INTO mock_purchases
            (
                practice_id,
                phone,
                subject,
                board,
                class_name,
                student_name,
                student_state,
                amount,
                razorpay_order_id,
                razorpay_payment_id,
                payment_status,
                purchased_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            practice_id,
            None,
            subject_name,
            board,
            class_name,
            student_name,
            student_state,
            package_price,
            order["id"],
            None,
            "pending",
            None
        ))

        conn.commit()

    except Exception as e:

        print(
            "PACKAGE PURCHASE SAVE ERROR:",
            e
        )

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Unable to save payment order."
        }), 500

    conn.close()

    response = jsonify({

        "success": True,
    
        "already_paid": False,
    
        "unlocked": False,
    
        "package_type":
            "practice_mock",
    
        "order_id":
            order["id"],
    
        "amount":
             package_price * 100,
    
        "currency":
            "INR",
    
        "razorpay_key":
            keys["razorpay_key"],
    
        "subject":
            subject_name,
    
        "subject_key":
            subject,
    
        "board":
            board,
    
        "class_name":
            class_name
    
    })

    response.set_cookie(
        "rsc_practice_id",
        practice_id,
        max_age=60 * 60 * 24 * 365 * 10,
        httponly=True,
        secure=True,
        samesite="Lax"
    )
    
    return response

# =====================================================
# RSC MOCK TEST - VERIFY PAYMENT
# =====================================================

@app.route(
    "/api/mock/payment-success",
    methods=["POST"]
)
def mock_payment_success():

    # -------------------------------------------------
    # ANONYMOUS BROWSER ID
    # -------------------------------------------------
    practice_id = get_practice_id()

    data = request.get_json() or {}

    order_id = str(
        data.get(
            "razorpay_order_id",
            ""
        )
    ).strip()

    payment_id = str(
        data.get(
            "razorpay_payment_id",
            ""
        )
    ).strip()

    signature = str(
        data.get(
            "razorpay_signature",
            ""
        )
    ).strip()

    if not order_id or not payment_id or not signature:

        return jsonify({
            "success": False,
            "error":
                "Incomplete payment response."
        }), 400

    # -------------------------------------------------
    # LOAD RAZORPAY KEYS
    # -------------------------------------------------
    try:

        with open("admin.json") as f:
            keys = json.load(f)

        client = razorpay.Client(
            auth=(
                keys["razorpay_key"],
                keys["razorpay_secret"]
            )
        )

    except Exception as e:

        print(
            "MOCK RAZORPAY KEY ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error":
                "Payment verification unavailable."
        }), 500

    # -------------------------------------------------
    # FIND OUR PENDING PURCHASE
    # -------------------------------------------------
    conn = sqlite3.connect("/var/data/students.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            id,
            practice_id,
            phone,
            subject,
            board,
            class_name,
            amount,
            razorpay_order_id,
            payment_status
        FROM mock_purchases
        WHERE razorpay_order_id=?
          AND practice_id=?
        LIMIT 1
    """, (
        order_id,
        practice_id
    ))

    purchase = c.fetchone()

    if not purchase:

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Payment order not found."
        }), 404

    # -------------------------------------------------
    # ALREADY PAID
    # -------------------------------------------------
    if purchase["payment_status"] == "paid":

        conn.close()

        return jsonify({
            "success": True,
            "unlocked": True,
            "message":
                "Mock Test package already unlocked."
        })

    # -------------------------------------------------
    # VERIFY RAZORPAY SIGNATURE
    # -------------------------------------------------
    try:

        client.utility.verify_payment_signature({
            "razorpay_order_id":
                order_id,

            "razorpay_payment_id":
                payment_id,

            "razorpay_signature":
                signature
        })

    except Exception as e:

        print(
            "MOCK PAYMENT SIGNATURE ERROR:",
            e
        )

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Payment verification failed."
        }), 400

    # -------------------------------------------------
    # VERIFY PAYMENT DETAILS
    # -------------------------------------------------
    try:
        print("===== PACKAGE PAYMENT DEBUG =====")
        print("ORDER ID:", order_id)
        print("PAYMENT ID:", payment_id)
        print("PRACTICE ID:", practice_id)
        print("PURCHASE ID:", purchase["id"])
        print("PURCHASE AMOUNT:", purchase["amount"])
        print("FETCHING RAZORPAY PAYMENT...")
        payment = client.payment.fetch(
            payment_id
        )
        print("RAZORPAY PAYMENT FETCHED:", payment)
        payment_order_id = payment.get(
            "order_id"
        )

        payment_amount = int(
            payment.get(
                "amount",
                0
            )
        )

        payment_status = payment.get(
            "status",
            ""
        )

        expected_amount = int(
            purchase["amount"] * 100
        )

        if payment_order_id != order_id:

            raise ValueError(
                "Order ID mismatch."
            )

        if payment_amount != expected_amount:

            raise ValueError(
                "Payment amount mismatch."
            )

        if payment_status != "captured":

            raise ValueError(
                "Payment is not captured."
            )

    except Exception as e:

        print(
            "MOCK PAYMENT FETCH ERROR:",
            e
        )

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Payment could not be confirmed."
        }), 400

    # -------------------------------------------------
    # MARK PACKAGE AS PAID
    # -------------------------------------------------
    try:

        c.execute("""
            UPDATE mock_purchases
            SET
                razorpay_payment_id=?,
                payment_status='paid',
                purchased_at=?
            WHERE id=?
        """, (
            payment_id,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            purchase["id"]
        ))

        conn.commit()

    except Exception as e:

        print(
            "MOCK PURCHASE UPDATE ERROR:",
            e
        )

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Payment received but package update failed."
        }), 500

    conn.close()

    return jsonify({
        "success": True,
        "unlocked": True,
        "subject":
            purchase["subject"],
        "board":
            purchase["board"],
        "class_name":
            purchase["class_name"],
        "message":
            "Payment successful. Mock Test package unlocked."
    })


# =====================================================
# SERVE PRACTICE QUESTION DIAGRAMS
# =====================================================

@app.route("/practice-diagrams/<filename>")
def serve_practice_diagram(filename):

    filename = secure_filename(filename)

    if not filename:
        return "Invalid image filename", 400

    return send_from_directory(
        PRACTICE_DIAGRAM_FOLDER,
        filename
    )

# =====================================================
# RSC MOCK TEST - CHECK PURCHASE
# =====================================================

@app.route("/api/mock/check-access")
def mock_check_access():

    # -------------------------------------------------
    # ANONYMOUS BROWSER ID
    # -------------------------------------------------
    practice_id = get_practice_id()

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    board = request.args.get(
        "board",
        ""
    ).strip()

    class_name = request.args.get(
        "class_name",
        ""
    ).strip()

    if not subject or not board or not class_name:

        return jsonify({
            "success": False,
            "error":
                "Subject, Board and Class are required."
        }), 400

    conn = sqlite3.connect("/var/data/students.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            payment_status
        FROM mock_purchases
        WHERE practice_id=?
          AND subject=?
          AND board=?
          AND class_name=?
        LIMIT 1
    """, (
        practice_id,
        subject,
        board,
        class_name
    ))

    row = c.fetchone()

    conn.close()

    unlocked = bool(
        row and
        row["payment_status"] == "paid"
    )

    return jsonify({
        "success": True,
        "logged_in": False,
        "unlocked": unlocked
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

    # Check whether this course has an active faculty
    active_faculty = any(
        details.get("course") == course
        and details.get("active", True)
        for details in teachers.values()
    )

    if not active_faculty:
        return jsonify({
            "error": "Class is unavailable. Faculty is inactive."
        }), 403

    user = get_user(phone)

     
    # =================================
    # STUDENT ACCESS VALIDATION
    # =================================
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT
            otp_verified,
            demo_allowed,
            demo_done,
            enrolled,
            redemo_paid
        FROM students
        WHERE phone=? AND course=?
    """, (phone, course))
    
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({
            "error": "Register first"
        }), 403
    
    otp_verified, demo_allowed, demo_done_db, enrolled_db, redemo_paid = row
    
    # Demo / Re-Demo eligibility
    demo_access = (
        otp_verified == 1
        and demo_done_db == 0
        and (
            demo_allowed == 1
            or redemo_paid == 1
        )
    )
    
    # Regular paid class eligibility
    enrolled = bool(enrolled_db)
    
    # Either valid demo access OR paid enrollment
    allow_join = demo_access or enrolled
    
    if not allow_join:
        conn.close()
        return jsonify({
            "error": "Join not allowed"
        }), 403
    
    # =================================
    # USER STATUS
    # =================================
    
    demo_done = bool(demo_done_db)


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
    # CHECK LIVE CLASS FIRST
    # =================================

    meet_link = get_active_meet_link(course)

    if not meet_link:
        conn.close()
        return jsonify({
            "error": "Class not started yet"
        }), 404

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
        SET join_time = COALESCE(join_time, ?),
            last_updated = ?
        WHERE phone = ? AND course = ?
    """, (
        join_time,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        phone,
        course
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "meet_link": meet_link
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
        
            "demo_done": user.get("demo_done", {}),
            "is_demo_user": user.get("demo_done", {}),
            "redemo_paid": user.get("redemo_paid", {}),
        
            "enrolled": user.get("enrolled", {}),
            "is_enrolled_user": user.get("enrolled", {}),
        
            "hours_used": user.get("hours_used", {}),
            "max_hours": user.get("max_hours", {}),

            "plan_cycle": user.get("plan_cycle", {}),
            "monthly_feedback_submitted": user.get(
                "monthly_feedback_submitted", {}
            ),

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

    if not teachers[username].get("active", True):
        session.pop("teacher", None)
        session.pop("course", None)

        return jsonify({
            "error": "Your account is inactive. Contact Admin."
        }), 403

    meet_link = request.json.get("meetLink")

    if not meet_link:
        return jsonify({"error": "Meet link missing"}), 400

    course = teachers[username]["course"]

    try:

        # =====================================
        # 🔥 SAVE LIVE CLASS TO DB
        # =====================================

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        # 🔥 create table if not exists
        c.execute("""
        CREATE TABLE IF NOT EXISTS live_classes (
            course TEXT PRIMARY KEY,
            meet_link TEXT,
            live INTEGER DEFAULT 0
        )
        """)
        # Add class timing columns
        existing_columns = [
            row[1] for row in c.execute(
                "PRAGMA table_info(live_classes)"
            ).fetchall()
        ]
        
        for column, definition in [
            ("started_at", "REAL"),
            ("warning_sent", "INTEGER DEFAULT 0"),
            ("ended_reason", "TEXT DEFAULT ''"),
            ("class_date", "TEXT DEFAULT ''")
        ]:
            if column not in existing_columns:
                c.execute(
                    f"ALTER TABLE live_classes ADD COLUMN {column} {definition}"
                )
        class_start_timestamp = time.time()

       
        class_start_date = (
            datetime.utcnow() + timedelta(hours=5, minutes=30)
        ).strftime("%Y-%m-%d")
        
        c.execute("""
            INSERT OR REPLACE INTO live_classes
            (
                course,
                meet_link,
                live,
                started_at,
                warning_sent,
                ended_reason,
                class_date
            )
            VALUES (?, ?, 1, ?, 0, '', ?)
        """, (
            course,
            meet_link,
            class_start_timestamp,
            class_start_date
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


def finish_class_for_course(course, reason="automatic"):

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:
        # Check whether the class is currently live
        c.execute("""
            SELECT live
            FROM live_classes
            WHERE course=?
        """, (course,))

        live_row = c.fetchone()

        if not live_row or not live_row[0]:
            return False

        # Get students who joined this course
        c.execute("""
            SELECT
                phone,
                join_time,
                enrolled,
                demo_done,
                otp_verified,
                demo_allowed,
                redemo_paid,
                hours_used
            FROM students
            WHERE course=?
              AND join_time IS NOT NULL
        """, (course,))

        students = c.fetchall()

        current_time = time.time()
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        for student in students:

            (
                phone,
                join_time,
                enrolled,
                demo_done,
                otp_verified,
                demo_allowed,
                redemo_paid,
                hours_used
            ) = student

            attended_minutes = (
                current_time - join_time
            ) / 60

            # Minimum attendance: 50 minutes
            if attended_minutes >= 50:
            # ==========================================
            # PAID RE-DEMO STUDENT
            # ==========================================
            
                if redemo_paid and not demo_done:
                
                    c.execute("""
                        UPDATE students
                        SET demo_done=1,
                            redemo_paid=0,
                            last_updated=?
                        WHERE phone=?
                          AND course=?
                          AND demo_done=0
                          AND redemo_paid=1
                    """, (
                        updated_at,
                        phone,
                        course
                    ))
            
            # ==========================================
            # PAID / ENROLLED STUDENT
            # ==========================================
            
            elif enrolled:
            
                c.execute("""
                    UPDATE students
                    SET hours_used = COALESCE(hours_used, 0) + 1,
                        last_updated = ?
                    WHERE phone=? AND course=? AND enrolled=1
                """, (
                    updated_at,
                    phone,
                    course
                ))
            
            # ==========================================
            # ORIGINAL FREE DEMO STUDENT
            # ==========================================
            
            elif (
                not demo_done
                and otp_verified
                and demo_allowed
            ):
            
                c.execute("""
                    UPDATE students
                    SET demo_done=1,
                        last_updated=?
                    WHERE phone=?
                      AND course=?
                      AND enrolled=0
                      AND demo_done=0
                """, (
                    updated_at,
                    phone,
                    course
                ))
                # PAID / ENROLLED STUDENT
                if enrolled:

                    c.execute("""
                        UPDATE students
                        SET hours_used = COALESCE(hours_used, 0) + 1,
                            last_updated = ?
                        WHERE phone=? AND course=? AND enrolled=1
                    """, (
                        updated_at,
                        phone,
                        course
                    ))

                # FREE DEMO STUDENT
                elif (
                    not demo_done
                    and otp_verified
                    and demo_allowed
                ):

                    c.execute("""
                        UPDATE students
                        SET demo_done=1,
                            last_updated=?
                        WHERE phone=?
                          AND course=?
                          AND enrolled=0
                          AND demo_done=0
                    """, (
                        updated_at,
                        phone,
                        course
                    ))

            # Clear attendance timestamp after processing
            c.execute("""
                UPDATE students
                SET join_time=NULL
                WHERE phone=? AND course=?
            """, (phone, course))

        # Mark class as ended
        c.execute("""
            UPDATE live_classes
            SET live=0,
                meet_link='',
                warning_sent=0,
                ended_reason=?,
                class_date=?
            WHERE course=?
        """, (
            reason,
            (
                datetime.utcnow() + timedelta(hours=5, minutes=30)
            ).strftime("%Y-%m-%d"),
            course
        ))

        conn.commit()

        # Update faculty memory state
        for username, teacher in teachers.items():

            if teacher.get("course") == course:
                teacher["class_live"] = False
                teacher["meet_link"] = ""

        print(
            f"CLASS ENDED: {course} | Reason: {reason}"
        )

        return True

    except Exception as e:

        conn.rollback()
        print("FINISH CLASS ERROR:", str(e))
        raise

    finally:
        conn.close()

def get_active_meet_link(course):

    conn = sqlite3.connect("/var/data/students.db")
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
            "meet_link": "",
            "class_over": False
        })

    # Get today's schedule and registration cutoff
    schedule = get_class_schedule_status(course)

    if not schedule["schedule_available"]:
        return jsonify({
            "live": False,
            "meet_link": "",
            "class_over": False
        })

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        # Ensure live_classes table exists
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_classes (
                course TEXT PRIMARY KEY,
                meet_link TEXT,
                live INTEGER DEFAULT 0
            )
        """)

        # Check existing database columns
        existing_columns = [
            row[1] for row in c.execute(
                "PRAGMA table_info(live_classes)"
            ).fetchall()
        ]

        # Preserve all required columns
        for column, definition in [
            ("started_at", "REAL"),
            ("warning_sent", "INTEGER DEFAULT 0"),
            ("ended_reason", "TEXT DEFAULT ''"),
            ("class_date", "TEXT DEFAULT ''")
        ]:

            if column not in existing_columns:
                c.execute(
                    f"ALTER TABLE live_classes ADD COLUMN {column} {definition}"
                )

        conn.commit()

        # Fetch today's class information
        c.execute("""
            SELECT
                meet_link,
                live,
                started_at,
                ended_reason,
                class_date
            FROM live_classes
            WHERE course=?
        """, (course,))

        row = c.fetchone()

        today = (
            datetime.utcnow() + timedelta(hours=5, minutes=30)
        ).strftime("%Y-%m-%d")

        # -----------------------------------------
        # RESET PREVIOUS-DAY OR LEGACY RECORDS
        # -----------------------------------------

        if row and row[4] != today:

            c.execute("""
                UPDATE live_classes
                SET live=0,
                    meet_link='',
                    started_at=NULL,
                    warning_sent=0,
                    ended_reason='',
                    class_date=?
                WHERE course=?
            """, (today, course))

            conn.commit()
            row = None

        # -----------------------------------------
        # RESET OLD SAME-DAY RECORD IF SCHEDULE CHANGED
        # -----------------------------------------

        if (
            row
            and not row[1]
            and row[3] in ("automatic", "manual")
            and row[2]
            and row[2] < schedule["scheduled_start"].timestamp()
        ):

            c.execute("""
                UPDATE live_classes
                SET live=0,
                    meet_link='',
                    started_at=NULL,
                    warning_sent=0,
                    ended_reason='',
                    class_date=?
                WHERE course=?
            """, (today, course))

            conn.commit()
            row = None

    finally:
        conn.close()

    # -----------------------------------------
    # NO CLASS RECORD / TEACHER NOT STARTED
    # -----------------------------------------

    if not row:

        # Scheduled start + 75 minutes passed
        if schedule["registration_closed"]:

            return jsonify({
                "live": False,
                "meet_link": "",
                "class_over": False,
                "waiting_for_teacher": False,
                "teacher_not_started": True,
                "registration_closed": True,
                "message": "Class Not Started for Today"
            })

        # Scheduled time reached; waiting for faculty
        if schedule["waiting_for_teacher"]:

            return jsonify({
                "live": False,
                "meet_link": "",
                "class_over": False,
                "waiting_for_teacher": True,
                "teacher_not_started": False,
                "registration_closed": False,
                "message": "Waiting for teacher to start class"
            })

        # Before scheduled time
        return jsonify({
            "live": False,
            "meet_link": "",
            "class_over": False,
            "waiting_for_teacher": False,
            "teacher_not_started": False,
            "registration_closed": False,
            "remaining_seconds": schedule["remaining_seconds"]
        })

    meet_link, live, started_at, ended_reason, class_date = row

    # -----------------------------------------
    # CLASS ALREADY ENDED BY FACULTY OR AUTOMATICALLY
    # -----------------------------------------

    if not live:

        if ended_reason in ("automatic", "manual"):

            return jsonify({
                "live": False,
                "meet_link": "",
                "class_over": True,
                "waiting_for_teacher": False,
                "teacher_not_started": False,
                "registration_closed": schedule["registration_closed"],
                "message": "Class Over for Today"
            })

        # No valid start record and registration cutoff passed
        if schedule["registration_closed"]:

            return jsonify({
                "live": False,
                "meet_link": "",
                "class_over": False,
                "waiting_for_teacher": False,
                "teacher_not_started": True,
                "registration_closed": True,
                "message": "Class Not Started for Today"
            })

        return jsonify({
            "live": False,
            "meet_link": "",
            "class_over": False,
            "waiting_for_teacher": schedule["waiting_for_teacher"],
            "teacher_not_started": False,
            "registration_closed": False,
            "remaining_seconds": schedule["remaining_seconds"]
        })

    # -----------------------------------------
    # AUTOMATIC END: 75 MINUTES FROM ACTUAL START
    # -----------------------------------------

    elapsed = time.time() - started_at if started_at else 0

    if started_at and elapsed >= CLASS_DURATION_MINUTES * 60:

        finish_class_for_course(
            course,
            "automatic"
        )

        return jsonify({
            "live": False,
            "meet_link": "",
            "class_over": True,
            "waiting_for_teacher": False,
            "teacher_not_started": False,
            "registration_closed": True,
            "message": "Class Over for Today"
        })

    # -----------------------------------------
    # CLASS IS STILL LIVE
    # Scheduled registration cutoff must not stop
    # an already-started class.
    # -----------------------------------------

    return jsonify({
        "live": True,
        "meet_link": meet_link or "",
        "class_over": False,
        "waiting_for_teacher": False,
        "teacher_not_started": False,
        "registration_closed": schedule["registration_closed"],
        "elapsed_seconds": int(elapsed),
        "remaining_seconds": max(
            0,
            int(CLASS_DURATION_MINUTES * 60 - elapsed)
        )
    })




@app.route("/end-class", methods=["POST"])
def end_class():

    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    try:

        course = teachers[username]["course"]

        ended = finish_class_for_course(
            course,
            "manual"
        )

        if not ended:
            return jsonify({
                "success": True,
                "live": False,
                "ended": True,
                "message": "Today Class over."
            }), 200

        return jsonify({
            "success": True,
            "live": False,
            "message": "Class ended successfully."
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

        if (
            t.get("course") == course
            and t.get("active", True)
        ):
            return jsonify({"teacher": name})

    return jsonify({"teacher": None})



@app.route("/api/faculty/class-timer")
def faculty_class_timer():

    username = session.get("teacher")

    if not username or username not in teachers:
        return jsonify({"error": "Unauthorized"}), 403

    course = teachers[username]["course"]

    # Get scheduled class timing
    schedule = get_class_schedule_status(course)

    if not schedule["schedule_available"]:
        return jsonify({
            "live": False,
            "warning": False,
            "ended": False
        })

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        # Ensure live_classes table exists
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_classes (
                course TEXT PRIMARY KEY,
                meet_link TEXT,
                live INTEGER DEFAULT 0
            )
        """)

        # Check existing database columns
        existing_columns = [
            row[1] for row in c.execute(
                "PRAGMA table_info(live_classes)"
            ).fetchall()
        ]

        # Preserve required database columns
        required_columns = [
            ("started_at", "REAL"),
            ("warning_sent", "INTEGER DEFAULT 0"),
            ("ended_reason", "TEXT DEFAULT ''"),
            ("class_date", "TEXT DEFAULT ''")
        ]

        for column, definition in required_columns:

            if column not in existing_columns:

                c.execute(
                    f"ALTER TABLE live_classes ADD COLUMN {column} {definition}"
                )

        conn.commit()

        # Read class information
        c.execute("""
            SELECT
                live,
                started_at,
                warning_sent,
                class_date,
                ended_reason
            FROM live_classes
            WHERE course=?
        """, (course,))

        row = c.fetchone()

        today = (
            datetime.utcnow() + timedelta(hours=5, minutes=30)
        ).strftime("%Y-%m-%d")

        # Reset previous-day records
        if row and row[3] != today:

            c.execute("""
                UPDATE live_classes
                SET live=0,
                    meet_link='',
                    started_at=NULL,
                    warning_sent=0,
                    ended_reason='',
                    class_date=?
                WHERE course=?
            """, (today, course))

            conn.commit()
            row = None

    finally:
        conn.close()

    # -----------------------------------------
    # FACULTY HAS NOT STARTED CLASS
    # -----------------------------------------

    if not row or not row[0] or not row[1]:

        # Scheduled start + 75 minutes passed
        # but faculty never started the class
        if schedule["registration_closed"]:

            return jsonify({
                "live": False,
                "warning": False,
                "ended": False,
                "not_started": True,
                "registration_closed": True,
                "message": "Class Not Started for Today"
            })

        return jsonify({
            "live": False,
            "warning": False,
            "ended": False,
            "not_started": False,
            "registration_closed": False
        })

    # -----------------------------------------
    # FACULTY HAS STARTED CLASS
    # -----------------------------------------

    live, started_at, warning_sent, class_date, ended_reason = row

    # Actual faculty start time
    elapsed = time.time() - started_at

    # -----------------------------------------
    # 75 MINUTES: AUTOMATIC CLASS END
    # -----------------------------------------

    if elapsed >= CLASS_DURATION_MINUTES * 60:

        finish_class_for_course(
            course,
            "automatic"
        )

        return jsonify({
            "live": False,
            "warning": False,
            "ended": True,
            "remaining_seconds": 0,
            "message": "Today's class completed."
        })

    # -----------------------------------------
    # 70 MINUTES: FACULTY WARNING
    # -----------------------------------------

    warning = elapsed >= 70 * 60

    if warning and not warning_sent:

        conn = sqlite3.connect(DB_PATH, timeout=30)
        c = conn.cursor()

        try:

            c.execute("""
                UPDATE live_classes
                SET warning_sent=1
                WHERE course=? AND live=1
            """, (course,))

            conn.commit()

        finally:
            conn.close()

    # -----------------------------------------
    # REMAINING CLASS TIME
    # -----------------------------------------

    remaining = max(
        0,
        int(CLASS_DURATION_MINUTES * 60 - elapsed)
    )

    return jsonify({
        "live": True,
        "warning": warning,
        "ended": False,
        "not_started": False,
        "remaining_seconds": remaining
    })

# =====================================================
# FACULTY - DOWNLOAD MONTHLY SALARY STATEMENT PDF
# =====================================================

@app.route("/faculty/salary-statement/<int:salary_id>")
def faculty_salary_statement(salary_id):

    # Faculty authentication
    username = session.get("teacher")

    if not username:
        return redirect("/teacher-login")

    teacher = teachers.get(username)

    if not teacher or not teacher.get("active", True):
        session.pop("teacher", None)
        return redirect("/teacher-login")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:

        # Fetch only the logged-in faculty's salary
        c.execute("""
            SELECT
                cs.id,
                cs.faculty_username,
                cs.month_key,
                cs.total_collection_paise,
                cs.rsc_percentage,
                cs.faculty_percentage,
                cs.salary_amount_paise,
                cs.paid_amount_paise,
                cs.pending_amount_paise,
                cs.salary_status,
                COALESCE(
                    cs.approval_status,
                    'pending_review'
                ) AS approval_status,
                cs.approved_by,
                cs.approved_at,
                cb.class_name,
                cb.course

            FROM class_salary cs

            INNER JOIN class_batches cb
                ON cb.id = cs.class_id

            WHERE cs.id=?
              AND cs.faculty_username=?

        """, (salary_id, username))

        salary = c.fetchone()

        if not salary:
            return "Salary statement not found.", 404

        # Fetch completed payout history
        c.execute("""
            SELECT
                amount_paise,
                payment_method,
                payment_date,
                payment_reference,
                payment_notes

            FROM salary_payouts

            WHERE salary_id=?
              AND faculty_username=?
              AND payout_status='completed'

            ORDER BY payment_date ASC, id ASC

        """, (salary_id, username))

        payments = c.fetchall()

        # Prepare PDF in memory
        buffer = BytesIO()

        pdf = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()
        story = []

        story.append(
            Paragraph(
                "<b>RANJITHAM STUDY CENTER</b>",
                styles["Title"]
            )
        )

        story.append(
            Paragraph(
                "Faculty Monthly Salary Statement",
                styles["Heading2"]
            )
        )

        story.append(Spacer(1, 18))

        def rupees(value):
            return "Rs. {:,.2f}".format(
                int(value or 0) / 100
            )

        # Faculty and class details
        details = [
            ["Faculty Name", salary["faculty_username"]],
            ["Class / Batch", salary["class_name"]],
            ["Course", salary["course"]],
            ["Salary Month", salary["month_key"]],
            ["Statement ID", str(salary["id"])]
        ]

        details_table = Table(
            details,
            colWidths=[150, 320]
        )

        details_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
        ]))

        story.append(details_table)
        story.append(Spacer(1, 20))

        # Salary calculation
        salary_details = [
            ["Description", "Amount"],

            [
                "Total Net Collection",
                rupees(salary["total_collection_paise"])
            ],

            [
                "RSC Share ({:.0f}%)".format(
                    salary["rsc_percentage"]
                ),
                rupees(
                    int(salary["total_collection_paise"] or 0)
                    * float(salary["rsc_percentage"] or 0) / 100
                )
            ],

            [
                "Faculty Share ({:.0f}%)".format(
                    salary["faculty_percentage"]
                ),
                rupees(salary["salary_amount_paise"])
            ],

            [
                "Amount Paid",
                rupees(salary["paid_amount_paise"])
            ],

            [
                "Pending Amount",
                rupees(salary["pending_amount_paise"])
            ]
        ]

        salary_table = Table(
            salary_details,
            colWidths=[300, 170]
        )

        salary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")
        ]))

        story.append(salary_table)
        story.append(Spacer(1, 20))

        # Approval information
        story.append(
            Paragraph(
                "<b>Approval Information</b>",
                styles["Heading3"]
            )
        )

        approval_details = [
            ["Approval Status", salary["approval_status"]],
            ["Approved By", salary["approved_by"] or "-"],
            ["Approved Date", salary["approved_at"] or "-"]
        ]

        approval_table = Table(
            approval_details,
            colWidths=[150, 320]
        )

        approval_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 8)
        ]))

        story.append(approval_table)
        story.append(Spacer(1, 20))

        # Payment history
        story.append(
            Paragraph(
                "<b>Payment History</b>",
                styles["Heading3"]
            )
        )

        payment_data = [[
            "Date",
            "Method",
            "Amount",
            "Reference"
        ]]

        for payment in payments:

            payment_data.append([
                payment["payment_date"] or "-",
                payment["payment_method"] or "-",
                rupees(payment["amount_paise"]),
                payment["payment_reference"] or "-"
            ])

        if not payments:
            payment_data.append([
                "-",
                "No payment recorded",
                "Rs. 0.00",
                "-"
            ])

        payment_table = Table(
            payment_data,
            colWidths=[90, 110, 100, 170]
        )

        payment_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 7),
            ("FONTSIZE", (0, 0), (-1, -1), 8)
        ]))

        story.append(payment_table)
        story.append(Spacer(1, 25))

        story.append(
            Paragraph(
                "This is a computer-generated salary statement.",
                styles["Italic"]
            )
        )

        pdf.build(story)

        buffer.seek(0)

        filename = (
            f"Salary_Statement_{username}_"
            f"{salary['month_key']}.pdf"
        )

        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf"
        )

    except Exception as e:

        print("FACULTY SALARY PDF ERROR:", str(e))

        return "Unable to generate salary statement.", 500

    finally:
        conn.close()
    
@app.route("/teacher-dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect("/teacher-login")

    username = session["teacher"]
    teacher = teachers.get(username)

    if not teacher or not teacher.get("active", True):

        session.pop("teacher", None)
        session.pop("course", None)

        return redirect("/teacher-login")

    course = teacher.get("course", "")
    feedbacks = get_faculty_feedback_list(username)
    summary = get_faculty_feedback_summary(username)

    avg_rating = summary["average_rating"]
    total_feedbacks = summary["total_feedbacks"]
    low_count = summary["low_count"]
    warning_msg = summary["warning_msg"]

    if summary["deactivate"]:

        set_faculty_status(
            username,
            False,
            "Automatic deactivation due to low feedback rating"
        )

        session.pop("teacher", None)
        session.pop("course", None)

        return redirect("/teacher-login")
        

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

    conn = sqlite3.connect("/var/data/students.db")
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
    # STUDENTS WAITING FOR FACULTY ADMISSION
    # =========================================
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT
            name,
            phone,
            course,
            otp_verified,
            enrolled
        FROM students
        WHERE course=?
          AND (
                (
                    otp_verified=1
                    AND demo_done=0
                    AND (
                        demo_allowed=1
                        OR redemo_paid=1
                    )
                )
                OR enrolled=1
          )
        ORDER BY name
    """, (course,))
    
    rows = c.fetchall()
    
    waiting_students = []
    
    for r in rows:
        waiting_students.append({
            "name": r[0],
            "phone": r[1],
            "course": r[2],
            "otp_verified": bool(r[3]),
            "enrolled": bool(r[4])
        })
    
    conn.close()

    
    conn = sqlite3.connect("/var/data/students.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
    SELECT *
    FROM students
    WHERE course=?
    """, (teacher.get("course"),))
    
    students = c.fetchall()
    
    conn.close()
        # ==========================================
    # NEW CLASS-WISE FACULTY SALARY DATA
    # ==========================================

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    class_salary_records = []

    c.execute("""
        SELECT
            cs.id,
            cb.class_name,
            cb.course,
            cs.month_key,
            cs.total_collection_paise,
            cs.salary_amount_paise,
            cs.paid_amount_paise,
            cs.pending_amount_paise,
            cs.salary_status,
            COALESCE(cs.approval_status, 'pending_review')
                AS approval_status

        FROM class_salary cs

        INNER JOIN class_batches cb
            ON cb.id = cs.class_id

        WHERE cs.faculty_username = ?

        ORDER BY cs.month_key DESC, cb.class_name
    """, (username,))

    salary_rows = c.fetchall()

    class_salary_total = 0
    class_salary_paid = 0
    class_salary_pending = 0
    class_salary_approved = 0

    for row in salary_rows:

        salary_id = row["id"]

        collection = int(
            row["total_collection_paise"] or 0
        )

        salary_amount = int(
            row["salary_amount_paise"] or 0
        )

        paid_amount = int(
            row["paid_amount_paise"] or 0
        )

        pending_amount = int(
            row["pending_amount_paise"] or 0
        )

        approval_status = row["approval_status"]

        if approval_status == "approved":
            class_salary_approved += salary_amount

        class_salary_total += salary_amount
        class_salary_paid += paid_amount
        class_salary_pending += pending_amount

        # Individual payout history
        c.execute("""
            SELECT
                amount_paise,
                payment_method,
                payment_date,
                payment_reference,
                payment_notes

            FROM salary_payouts

            WHERE salary_id=?
              AND payout_status='completed'

            ORDER BY payment_date DESC, id DESC
        """, (salary_id,))

        payout_rows = c.fetchall()

        payout_history = []

        for payment in payout_rows:

            payout_history.append({
                "amount": int(
                    payment["amount_paise"] or 0
                ) / 100,

                "method": payment["payment_method"] or "",

                "date": payment["payment_date"] or "",

                "reference": payment["payment_reference"] or "",

                "notes": payment["payment_notes"] or ""
            })

        class_salary_records.append({

            "salary_id": salary_id,

            "class_name": row["class_name"],

            "course": row["course"],

            "month": row["month_key"],

            "collection": collection / 100,

            "salary": salary_amount / 100,

            "paid": paid_amount / 100,

            "pending": pending_amount / 100,

            "status": row["salary_status"],

            "approval_status": approval_status,

            "payments": payout_history
        })

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
        avg_rating=avg_rating,
        class_salary_records=class_salary_records,
        class_salary_total=class_salary_total / 100,
        class_salary_paid=class_salary_paid / 100,
        class_salary_pending=class_salary_pending / 100,
        class_salary_approved=class_salary_approved / 100
       
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

    _save_feedback()

    summary = get_faculty_feedback_summary(teacher_name)

    if summary["deactivate"]:

        set_faculty_status(
            teacher_name,
            False,
            "Automatic deactivation due to low feedback rating"
        )

    return jsonify({
        "status": "success",
        "average_rating": summary["average_rating"],
        "total_feedbacks": summary["total_feedbacks"],
        "warning": summary["warning_msg"],
        "deactivated": summary["deactivate"]
    })


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

    phone = session.get("phone")
    teacher = request.form.get("teacher", "").strip()
    course = request.form.get("course", "").strip()
    comment = request.form.get("comment", "").strip()

    try:
        rating = int(request.form.get("rating", 0))
    except (ValueError, TypeError):
        rating = 0

    if not phone:
        return jsonify({"error": "Please login first"}), 401

    if not teacher or not course or rating not in range(1, 6) or not comment:
        return jsonify({"error": "Please provide rating and feedback"}), 400

    # Verify assigned active teacher
    assigned_teacher = next(
        (
            name for name, data in teachers.items()
            if data.get("course") == course
            and data.get("active", True)
        ),
        None
    )

    if teacher != assigned_teacher:
        return jsonify({"error": "Invalid teacher for this course"}), 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:
        c.execute("""
            SELECT enrolled, hours_used, max_hours, plan_cycle
            FROM students
            WHERE phone=? AND course=?
        """, (phone, course))

        student = c.fetchone()

        if not student:
            return jsonify({"error": "Student record not found"}), 404

        enrolled, hours_used, max_hours, plan_cycle = student
        plan_cycle = int(plan_cycle or 1)

        if not enrolled or hours_used < max_hours:
            return jsonify({
                "error": "Feedback is available after monthly classes are completed."
            }), 403

        submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c.execute("""
            INSERT INTO monthly_teacher_feedback
            (phone, course, plan_cycle, teacher, rating, comment, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            phone, course, plan_cycle,
            teacher, rating, comment, submitted_at
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        return jsonify({
            "error": "Feedback already submitted for this monthly plan."
        }), 409

    except Exception as e:
        conn.rollback()
        print("MONTHLY FEEDBACK ERROR:", e)
        return jsonify({"error": "Unable to save feedback"}), 500

    finally:
        conn.close()

    # Keep existing admin/faculty feedback display
    if teacher not in feedback_db:
        feedback_db[teacher] = []

    feedback_db[teacher].append({
        "phone": phone,
        "rating": rating,
        "comment": comment,
        "course": course,
        "time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "approved": False
    })

    _save_feedback()

    # Check faculty performance using existing feedback rules
    summary = get_faculty_feedback_summary(teacher)

    if summary["deactivate"]:
        set_faculty_status(
            teacher,
            False,
            "Automatic deactivation due to low feedback rating"
        )

    return jsonify({
        "status": "submitted",
        "plan_cycle": plan_cycle,
        "next_month_payment_enabled": True,
        "average_rating": summary["average_rating"],
        "total_feedbacks": summary["total_feedbacks"],
        "warning": summary["warning_msg"],
        "deactivated": summary["deactivate"]
    })
    


def _save_feedback():
    try:
        with open("/var/data/feedback.json", "w") as f:
            json.dump(feedback_db, f, indent=4)
    except Exception as e:
        print("Feedback save error:", e)


def _load_feedback():
    global feedback_db
    try:
        with open("/var/data/feedback.json", "r") as f:
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


@app.route("/admin/generate-class-salary", methods=["POST"])
def admin_generate_class_salary():

    if not session.get("admin"):
        return redirect("/admin")

    month_key = (
        request.form.get("month_key")
        or datetime.now().strftime("%Y-%m")
    )

    try:
        count = generate_monthly_class_salary(month_key)

        print(
            "ADMIN GENERATED CLASS SALARY:",
            month_key,
            "Classes:",
            count
        )

        return redirect(
            "/admin-dashboard?salary_month=" + month_key
        )

    except Exception as e:
        print("MONTHLY SALARY GENERATION ERROR:", str(e))
        return "Salary generation failed. Check server logs.", 500

# ==========================================
# ADMIN - APPROVE / REJECT FACULTY SALARY
# ==========================================

@app.route("/admin/review-class-salary", methods=["POST"])
def admin_review_class_salary():

    if not session.get("admin"):
        return redirect("/admin")

    salary_id = request.form.get("salary_id", type=int)
    decision = request.form.get("decision", "").strip()
    month_key = request.form.get("month_key", "")

    if not salary_id or decision not in ("approved", "rejected"):
        return "Invalid salary approval request.", 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:
        c.execute("BEGIN IMMEDIATE")

        c.execute("""
            SELECT id
            FROM class_salary
            WHERE id=?
        """, (salary_id,))

        if not c.fetchone():
            conn.rollback()
            return "Salary record not found.", 404

        if decision == "approved":
            c.execute("""
                UPDATE class_salary
                SET approval_status=?,
                    approved_by=?,
                    approved_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, ("approved", "Admin", salary_id))

        else:
            c.execute("""
                UPDATE class_salary
                SET approval_status=?,
                    approved_by='',
                    approved_at=NULL
                WHERE id=?
            """, ("rejected", salary_id))

        conn.commit()

        return redirect(url_for(
            "admin_dashboard",
            tab="salary",
            salary_month=month_key
        ))

    except Exception as e:
        conn.rollback()
        print("SALARY APPROVAL ERROR:", str(e))
        return "Salary approval failed. Check server logs.", 500

    finally:
        conn.close()

# =====================================================
# ADMIN - RECORD MANUAL FACULTY SALARY PAYMENT
# =====================================================

@app.route("/admin/record-salary-payment", methods=["POST"])
def admin_record_salary_payment():

    if not session.get("admin"):
        return redirect("/admin")

    salary_id = request.form.get("salary_id", type=int)
    amount_input = request.form.get("amount", "").strip()
    payment_date = request.form.get("payment_date", "").strip()
    payment_reference = request.form.get(
        "payment_reference", ""
    ).strip()
    payment_notes = request.form.get(
        "payment_notes", ""
    ).strip()

    month_key = request.form.get(
        "month_key",
        datetime.now().strftime("%Y-%m")
    )

    # Validate required fields
    if not salary_id or not amount_input or not payment_date:
        return "Salary ID, amount and payment date are required.", 400
    
    if not payment_reference:
        return "Bank UTR / Transaction Reference is required.", 400
    
    if len(payment_reference) > 100:
        return "Transaction reference is too long.", 400

    try:
        amount_paise = round(float(amount_input) * 100)

        if amount_paise <= 0:
            return "Payment amount must be greater than zero.", 400

        datetime.strptime(payment_date, "%Y-%m-%d")
        datetime.strptime(month_key, "%Y-%m")

    except ValueError:
        return "Invalid amount or date format.", 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    try:

        # Lock transaction to prevent concurrent overpayment
        c.execute("BEGIN IMMEDIATE")

        c.execute("""
            SELECT
                id,
                faculty_username,
                month_key,
                salary_amount_paise,
                paid_amount_paise,
                approval_status
            FROM class_salary
            WHERE id=?
        """, (salary_id,))

        salary = c.fetchone()

        if not salary:
            conn.rollback()
            return "Salary record not found.", 404

        (
            salary_id,
            faculty_username,
            salary_month,
            salary_amount,
            paid_amount,
            approval_status
        ) = salary

        # Salary payment is allowed only after admin approval
        if approval_status != "approved":
            conn.rollback()
            return (
                "Salary payment is blocked. "
                "Admin approval is required first.",
                403
            )

        salary_amount = int(salary_amount or 0)
        paid_amount = int(paid_amount or 0)

        pending_amount = max(
            salary_amount - paid_amount, 0
        )

        # Prevent overpayment
        if amount_paise > pending_amount:
            conn.rollback()
            return (
                f"Payment exceeds pending salary. "
                f"Pending amount: ₹{pending_amount / 100:.2f}",
                400
            )

        new_paid_amount = paid_amount + amount_paise

        new_pending_amount = max(
            salary_amount - new_paid_amount, 0
        )

        if new_pending_amount == 0:
            salary_status = "paid"
        elif new_paid_amount > 0:
            salary_status = "partial"
        else:
            salary_status = "pending"

        # Save individual payment history
        c.execute("""
            INSERT INTO salary_payouts
            (
                salary_id,
                faculty_username,
                amount_paise,
                razorpayx_payout_id,
                idempotency_key,
                payout_status,
                initiated_at,
                completed_at,
                failure_reason,
                payment_method,
                payment_date,
                payment_reference,
                payment_notes,
                recorded_by
            )
            VALUES (?, ?, ?, '', ?, 'completed',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '',
                    'Bank Transfer', ?, ?, ?, 'Admin')
        """, (
            salary_id,
            faculty_username,
            amount_paise,
            uuid.uuid4().hex,
            payment_date,
            payment_reference,
            payment_notes
        ))

        # Update salary totals
        c.execute("""
            UPDATE class_salary
            SET
                paid_amount_paise=?,
                pending_amount_paise=?,
                salary_status=?
            WHERE id=?
        """, (
            new_paid_amount,
            new_pending_amount,
            salary_status,
            salary_id
        ))

        conn.commit()

        print(
            "MANUAL SALARY PAYMENT RECORDED:",
            faculty_username,
            salary_month,
            amount_paise / 100
        )

        return redirect(url_for(
            "admin_dashboard",
            tab="salary",
            salary_month=salary_month
        ))

    except Exception as e:

        conn.rollback()

        print("MANUAL SALARY PAYMENT ERROR:", str(e))

        return "Salary payment recording failed. Check server logs.", 500

    finally:
        conn.close()
# =====================================================
# ADMIN - REACTIVATE FACULTY
# =====================================================


# =====================================================
# ADMIN - REACTIVATE FACULTY
# =====================================================

@app.route("/admin/faculty/<username>/reactivate", methods=["POST"])
def reactivate_faculty(username):

    # Admin authentication
    if not session.get("admin"):
        return redirect("/admin")

    if username not in teachers:
        return "Faculty not found", 404

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT active_status, status_reason
        FROM faculty_status
        WHERE username=?
    """, (username,))

    status_row = c.fetchone()
    conn.close()

    # Allow reactivation only for feedback-based deactivation
    if not status_row:
        return "Faculty status record not found.", 404

    active_status, status_reason = status_row

    if active_status:
        return "Faculty is already active.", 400

    if status_reason != "Automatic deactivation due to low feedback rating":
        return "Reactivation is not permitted for this status.", 403

    # Restore the same faculty account.
    # Existing class assignment records remain unchanged.
    set_faculty_status(
        username,
        True,
        "Reactivated by Admin"
    )

    print("FACULTY REACTIVATED:", username)

    return redirect("/admin-dashboard")



@app.route("/admin-dashboard")
def admin_dashboard():

    if not session.get("admin"):
        return redirect("/admin")

    selected_month = request.args.get("month", "")

    summary = {}
    months = []

    # ==========================================
    # OLD SALARY SUMMARY
    # ==========================================

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
                "month": datetime.now().strftime("%B"),
                "year": datetime.now().strftime("%Y")
            }

        summary[teacher]["students"] += 1

        if s["paid_to_faculty"]:
            summary[teacher]["paid"] += s["faculty_share"]
        else:
            summary[teacher]["pending"] += s["faculty_share"]

    # If no old salary data, show all faculties
    if not summary:

        for teacher, t in teachers.items():

            summary[teacher] = {
                "pending": 0,
                "paid": 0,
                "students": 0,
                "course": t.get("course", "Not Assigned"),
                "class_count": 0,
                "strength": seat_data.get(
                    t.get("course", ""), {}
                ).get("total", 30),
                "month": datetime.now().strftime("%B"),
                "year": datetime.now().strftime("%Y")
            }

    active_classes = sum(
        1 for t in teachers.values()
        if t.get("active", False)
    )

    # ==========================================
    # DASHBOARD KPI DATA
    # ==========================================

    dashboard_month = datetime.now().strftime("%B %Y")
    month_key = datetime.now().strftime("%Y-%m")

    total_students = 0
    active_class_count = 0
    total_faculties = sum(
        1 for t in teachers.values()
        if t.get("active", False)
    )

    monthly_collection_paise = 0
    faculty_salary_total_paise = 0
    paid_salary_total_paise = 0
    pending_salary_total_paise = 0

    # Salary tab default values
    salary_month_key = datetime.now().strftime("%Y-%m")
    salary_month_options = [salary_month_key]
    salary_month_options_display = [{
        "value": salary_month_key,
        "label": datetime.now().strftime("%B %Y")
    }]
    salary_month_label = datetime.now().strftime("%B %Y")
    class_salary_rows = []

    # HR default values
    hr_faculty = []
    class_monitoring = []

    # ==========================================
    # DATABASE CONNECTION
    # ==========================================

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:

        # Ensure live_classes table exists BEFORE querying it
        c.execute("""
            CREATE TABLE IF NOT EXISTS live_classes (
                course TEXT PRIMARY KEY,
                meet_link TEXT,
                live INTEGER DEFAULT 0
            )
        """)

        # Total enrolled students
        c.execute("""
            SELECT COUNT(*)
            FROM students
            WHERE enrolled = 1
        """)

        total_students = c.fetchone()[0] or 0

        # Active class batches
        c.execute("""
            SELECT COUNT(*)
            FROM class_batches
            WHERE active_status = 1
        """)

        active_class_count = c.fetchone()[0] or 0

        # Monthly net tuition collection
        c.execute("""
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN amount_paise > COALESCE(refund_amount_paise, 0)
                        THEN amount_paise - COALESCE(refund_amount_paise, 0)
                        ELSE 0
                    END
                ), 0
            )
            FROM class_fee_payments
            WHERE month_key = ?
            AND payment_status = 'captured'
        """, (month_key,))

        monthly_collection_paise = c.fetchone()[0] or 0

        # Faculty 60% share (KPI estimate)
        faculty_salary_total_paise = round(
            monthly_collection_paise * 0.60
        )

        # Actual salary already paid
        c.execute("""
            SELECT COALESCE(SUM(paid_amount_paise), 0)
            FROM class_salary
            WHERE month_key = ?
        """, (month_key,))

        paid_salary_total_paise = c.fetchone()[0] or 0

        # Actual pending salary
        c.execute("""
            SELECT COALESCE(SUM(pending_amount_paise), 0)
            FROM class_salary
            WHERE month_key = ?
        """, (month_key,))

        pending_salary_total_paise = c.fetchone()[0] or 0

        # ==========================================
        # CLASS-WISE SALARY TAB DATA
        # ==========================================

        salary_month_key = (
            request.args.get("salary_month")
            or datetime.now().strftime("%Y-%m")
        )

        class_salary_rows = []

        # Available payment / salary months
        c.execute("""
            SELECT month_key FROM class_fee_payments
            UNION
            SELECT month_key FROM class_salary
            ORDER BY month_key DESC
        """)

        salary_month_options = [
            row[0] for row in c.fetchall()
            if row[0]
        ]

        if salary_month_key not in salary_month_options:
            salary_month_options.insert(0, salary_month_key)
        salary_month_options_display = [
        {
            "value": m,
            "label": datetime.strptime(
                m, "%Y-%m"
            ).strftime("%B %Y")
        }
        for m in salary_month_options
        ]

        salary_month_label = datetime.strptime(
            salary_month_key, "%Y-%m"
        ).strftime("%B %Y")

        # One row per salary class
        c.execute("""
            SELECT
                cb.id,
                cb.class_name,
                cb.course,
                cb.faculty_username,

                (
                    SELECT COUNT(*)
                    FROM students s
                    WHERE s.course = cb.course
                      AND s.enrolled = 1
                ) AS enrolled_students,

                COALESCE((
                    SELECT SUM(
                        CASE
                            WHEN p.amount_paise >
                                 COALESCE(p.refund_amount_paise, 0)
                            THEN p.amount_paise -
                                 COALESCE(p.refund_amount_paise, 0)
                            ELSE 0
                        END
                    )
                    FROM class_fee_payments p
                    WHERE p.class_id = cb.id
                      AND p.month_key = ?
                      AND p.payment_status = 'captured'
                ), 0) AS net_collection,

                cs.id,
                COALESCE(cs.salary_amount_paise, 0),
                COALESCE(cs.paid_amount_paise, 0),
                COALESCE(cs.pending_amount_paise, 0),
                COALESCE(cs.salary_status, 'not_generated'),
                COALESCE(cs.approval_status, 'pending_review')

            FROM class_batches cb

            LEFT JOIN class_salary cs
                ON cs.class_id = cb.id
               AND cs.month_key = ?

            WHERE cb.course IN ('cbse9', 'cbse10', 'cbse12')

            ORDER BY cb.course
        """, (salary_month_key, salary_month_key))

        for row in c.fetchall():

            (
                class_id,
                class_name,
                course,
                faculty_username,
                enrolled_students,
                net_collection_paise,
                salary_id,
                salary_amount_paise,
                paid_amount_paise,
                pending_amount_paise,
                salary_status,
                approval_status
            ) = row

            net_collection_paise = int(net_collection_paise or 0)

            # Use generated salary record when available.
            # Otherwise show the estimated 60% share until generated.
            if salary_id:
                faculty_share_paise = int(salary_amount_paise or 0)
                paid_paise = int(paid_amount_paise or 0)
                pending_paise = int(pending_amount_paise or 0)
            else:
                faculty_share_paise = round(
                    net_collection_paise * 0.60
                )
                paid_paise = 0
                pending_paise = 0

            rsc_share_paise = (
                net_collection_paise - faculty_share_paise
            )
            # Fetch completed manual salary payment history
            salary_payments = []

            if salary_id:
                c.execute("""
                    SELECT
                        amount_paise,
                        payment_date,
                        payment_reference,
                        payment_notes,
                        recorded_by
                    FROM salary_payouts
                    WHERE salary_id=?
                      AND payout_status='completed'
                    ORDER BY payment_date DESC, id DESC
                """, (salary_id,))

                for payment in c.fetchall():
                    salary_payments.append({
                        "amount": int(payment[0] or 0) / 100,
                        "date": payment[1] or "",
                        "reference": payment[2] or "",
                        "notes": payment[3] or "",
                        "recorded_by": payment[4] or "Admin"
                    })
                    

            class_salary_rows.append({
                "class_id": class_id,
                "class_name": class_name,
                "course": course,
                "faculty": faculty_username,
                "enrolled": enrolled_students or 0,
                "collection": net_collection_paise / 100,
                "rsc_share": rsc_share_paise / 100,
                "faculty_share": faculty_share_paise / 100,
                "paid": paid_paise / 100,
                "pending": pending_paise / 100,
                "status": salary_status,
                "approval_status": approval_status,
                "generated": bool(salary_id),
                "salary_id": salary_id,
                "payments": salary_payments
            })

        # ==========================================
        # HR MANAGEMENT DATA
        # ==========================================

        hr_faculty = []

        for username, details in teachers.items():

            course = details.get("course", "Not Assigned")

            # Faculty class assignment summary
            c.execute("""
                SELECT
                    COUNT(*) AS assigned_count,
                    SUM(
                        CASE WHEN active_status = 1
                        THEN 1 ELSE 0 END
                    ) AS active_class_count,
                    GROUP_CONCAT(class_name, ', ')
                        AS assigned_class_names
                FROM class_batches
                WHERE faculty_username = ?
                  AND TRIM(faculty_username) != ''
            """, (username,))

            assignment_row = c.fetchone()

            assigned_class_count = (
                assignment_row["assigned_count"] or 0
            )

            active_assigned_class_count = (
                assignment_row["active_class_count"] or 0
            )

            assigned_class_names = (
                assignment_row["assigned_class_names"] or ""
            )

            feedback = get_faculty_feedback_summary(username)

            c.execute("""
                SELECT live
                FROM live_classes
                WHERE course=?
            """, (course,))
            
            live_row = c.fetchone()
            faculty_is_live = bool(
                live_row and live_row["live"]
            )
            c.execute("""
                SELECT status_reason
                FROM faculty_status
                WHERE username=?
            """, (username,))

            status_row = c.fetchone()

            c.execute("""
                SELECT COUNT(DISTINCT phone)
                FROM students
                WHERE course=? AND enrolled=1
            """, (course,))

            student_row = c.fetchone()

            
            # ==========================================
            # FACULTY-WISE MONTHLY SALARY SUMMARY
            # ==========================================
            
            faculty_salary_classes = [
                row for row in class_salary_rows
                if row["faculty"] == username
            ]
            
            total_faculty_collection = sum(
                row["collection"]
                for row in faculty_salary_classes
            )
            
            total_faculty_share = sum(
                row["faculty_share"]
                for row in faculty_salary_classes
            )
            
            total_faculty_paid = sum(
                row["paid"]
                for row in faculty_salary_classes
            )
            
            total_faculty_pending = sum(
                row["pending"]
                for row in faculty_salary_classes
            )
            
            generated_salary = sum(
                row["faculty_share"]
                for row in faculty_salary_classes
                if row["generated"]
            )
            
            not_generated_salary = sum(
                row["faculty_share"]
                for row in faculty_salary_classes
                if not row["generated"]
            )
            
            hr_faculty.append({
                "username": username,
                "course": course,
                "active": details.get("active", False),
                "assigned": assigned_class_count > 0,
                "assigned_class_count": assigned_class_count,
                "active_assigned_class_count": active_assigned_class_count,
                "assigned_class_names": assigned_class_names,

                "live": (
                    faculty_is_live
                    and details.get("active", False)
                    and assigned_class_count > 0
                ),

                "students": student_row[0] if student_row else 0,
            
                "feedback_count": feedback["total_feedbacks"],
                "average_rating": feedback["average_rating"],
                "low_count": feedback["low_count"],
                "warning_msg": feedback["warning_msg"],
            
                "status_reason": (
                    status_row["status_reason"]
                    if status_row else ""
                ),
            
                # Monthly salary summary
                "salary_month": salary_month_label,
                "salary_classes": faculty_salary_classes,
                "salary_collection": total_faculty_collection,
                "salary_share": total_faculty_share,
                "salary_generated": generated_salary,
                "salary_not_generated": not_generated_salary,
                "salary_paid": total_faculty_paid,
                "salary_pending": total_faculty_pending
            })


        # ==========================================
        # CLASS-WISE MONITORING
        # ==========================================

        class_monitoring = []

        courses = sorted(set(
            t.get("course", "Not Assigned")
            for t in teachers.values()
        ))

        for course in courses:

            assigned = [
                name for name, details in teachers.items()
                if details.get("course") == course
            ]

            active_assigned = [
                name for name in assigned
                if teachers[name].get("active", False)
            ]

            c.execute("""
                SELECT live
                FROM live_classes
                WHERE course=?
            """, (course,))

            live_row = c.fetchone()
            is_live = bool(live_row and live_row["live"])

            class_monitoring.append({
                "course": course,
                "faculty": ", ".join(assigned),
                "faculty_status": (
                    "Active" if active_assigned else "Inactive"
                ),
                "class_status": (
                    "Live" if is_live else "Not Live"
                )
            })

        conn.commit()

    except Exception as e:

        print("ADMIN DASHBOARD ERROR:", str(e))

        hr_faculty = []
        class_monitoring = []

    finally:
        conn.close()

    # ==========================================
    # CONVERT AMOUNTS TO RUPEES
    # ==========================================

    monthly_collection = monthly_collection_paise / 100

    faculty_salary_total = (
        faculty_salary_total_paise / 100
    )

    pending_salary_total = (
        pending_salary_total_paise / 100
    )

    # ==========================================
    # RENDER ADMIN DASHBOARD
    # ==========================================

    return render_template(
        "admin_dashboard.html",
        summary=summary,
        teachers=teachers,
        active_classes=active_classes,
        salary_db=salary_db,
        months=months,
        selected_month=selected_month,
        dashboard_month=dashboard_month,
        total_students=total_students,
        active_class_count=active_class_count,
        total_faculties=total_faculties,
        monthly_collection=monthly_collection,
        faculty_salary_total=faculty_salary_total,
        pending_salary_total=pending_salary_total,
        hr_faculty=hr_faculty,
        class_monitoring=class_monitoring,
        salary_month_key=salary_month_key,
        salary_month_options=salary_month_options,
        class_salary_rows=class_salary_rows,
        salary_month_options_display=salary_month_options_display,
        salary_month_label=salary_month_label
    )

@app.route("/admin/practice")
def admin_practice():

    if not session.get("admin"):
        return redirect("/admin")

    return render_template("admin_practice.html")

@app.route("/admin/mock-tests")
def admin_mock_tests():

    if not session.get("admin"):
        return redirect("/admin")

    return render_template("admin_mock_tests.html")

# =====================================================
# ADMIN - MOCK TEST LIST
# =====================================================

# =====================================================
# ADMIN - MOCK TEST LIST
# =====================================================

@app.route("/admin/mock-test-list")
def admin_mock_test_list():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                mt.id,
                mt.mock_test_no,
                mt.mock_type,
                mt.chapter_scope,
                mt.board,
                mt.class_name,
                mt.subject,
                mt.test_name,
                mt.syllabus_scope,
                mt.total_questions,
                mt.total_marks,
                mt.duration_minutes,
                mt.price_inr,
                mt.attempt_limit,
                mt.active,
                mt.created_at,

                COUNT(mq.id) AS question_count

            FROM mock_tests mt

            LEFT JOIN mock_questions mq
                ON mq.mock_test_id = mt.id

            GROUP BY mt.id

            ORDER BY
                mt.board,
                mt.class_name,
                mt.subject,
                CASE
                    WHEN mt.mock_type = 'chapter'
                        THEN 1
                    WHEN mt.mock_type = 'four_chapter'
                        THEN 2
                    WHEN mt.mock_type = 'full_syllabus'
                        THEN 3
                    ELSE 4
                END,
                mt.id
        """)

        tests = []

        for row in c.fetchall():

            tests.append({

                "id":
                    row["id"],

                # Internal compatibility only.
                # Not displayed in frontend.
                "mock_test_no":
                    row["mock_test_no"],

                "mock_type":
                    row["mock_type"]
                    or "chapter",

                "chapter_scope":
                    row["chapter_scope"]
                    or "",

                "board":
                    row["board"],

                "class_name":
                    row["class_name"],

                "subject":
                    row["subject"],

                "test_name":
                    row["test_name"],

                "syllabus_scope":
                    row["syllabus_scope"]
                    or "",

                "total_questions":
                    row["total_questions"],

                "total_marks":
                    row["total_marks"],

                "duration_minutes":
                    row["duration_minutes"],

                "price_inr":
                    row["price_inr"],

                "attempt_limit":
                    row["attempt_limit"],

                "active":
                    bool(row["active"]),

                "created_at":
                    row["created_at"],

                "question_count":
                    row["question_count"]
            })

        conn.close()

        return jsonify({
            "success": True,
            "tests": tests
        })

    except Exception as e:

        print(
            "ADMIN MOCK TEST LIST ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
# =====================================================
# ADMIN - MOCK QUESTIONS LIST
# =====================================================

@app.route("/admin/mock-questions")
def admin_mock_questions():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:
        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                mq.id,
                mq.mock_test_id,
                mt.mock_test_no,
                mq.board,
                mq.class_name,
                mq.subject,
                mq.topic,
                mq.subtopic,
                mq.difficulty,
                mq.question,
                mq.option_a,
                mq.option_b,
                mq.option_c,
                mq.option_d,
                mq.correct_answer,
                mq.explanation,
                mq.hint,
                mq.marks,
                mq.active,
                mq.created_at
            FROM mock_questions mq
            INNER JOIN mock_tests mt
                ON mt.id = mq.mock_test_id
            ORDER BY
                mt.mock_test_no,
                mq.id DESC
        """)

        questions = []

        for row in c.fetchall():
            questions.append({
                "id": row["id"],
                "mock_test_id": row["mock_test_id"],
                "mock_test_no": row["mock_test_no"],
                "board": row["board"],
                "class_name": row["class_name"],
                "subject": row["subject"],
                "topic": row["topic"],
                "subtopic": row["subtopic"],
                "difficulty": row["difficulty"],
                "question": row["question"],
                "option_a": row["option_a"],
                "option_b": row["option_b"],
                "option_c": row["option_c"],
                "option_d": row["option_d"],
                "correct_answer": row["correct_answer"],
                "explanation": row["explanation"],
                "hint": row["hint"],
                "marks": row["marks"],
                "active": bool(row["active"]),
                "created_at": row["created_at"]
            })

        conn.close()

        return jsonify({
            "success": True,
            "questions": questions
        })

    except Exception as e:

        print("ADMIN MOCK QUESTIONS ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =====================================================
# ADMIN - ADD MOCK QUESTION
# =====================================================

@app.route("/admin/mock-questions/add", methods=["POST"])
def admin_add_mock_question():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        data = request.get_json() or {}

        mock_test_no = int(data.get("mock_test_no", 0))

        board = str(data.get("board", "")).strip()
        class_name = str(data.get("class_name", "")).strip()
        subject = str(data.get("subject", "")).strip()

        topic = str(data.get("topic", "")).strip()
        subtopic = str(data.get("subtopic", "")).strip()
        difficulty = str(data.get("difficulty", "")).strip().lower()

        question = str(data.get("question", "")).strip()

        option_a = str(data.get("option_a", "")).strip()
        option_b = str(data.get("option_b", "")).strip()
        option_c = str(data.get("option_c", "")).strip()
        option_d = str(data.get("option_d", "")).strip()

        correct_answer = str(
            data.get("correct_answer", "")
        ).strip().upper()

        explanation = str(
            data.get("explanation", "")
        ).strip()

        hint = str(
            data.get("hint", "")
        ).strip()

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if mock_test_no <= 0:
            return jsonify({
                "success": False,
                "error": "Invalid Mock Test No."
            }), 400

        required = {
            "Board": board,
            "Class": class_name,
            "Subject": subject,
            "Topic": topic,
            "Subtopic": subtopic,
            "Difficulty": difficulty,
            "Question": question,
            "Option A": option_a,
            "Option B": option_b,
            "Option C": option_c,
            "Option D": option_d,
            "Correct Answer": correct_answer
        }

        missing = [
            name
            for name, value in required.items()
            if not value
        ]

        if missing:
            return jsonify({
                "success": False,
                "error": "Missing: " + ", ".join(missing)
            }), 400

        if correct_answer not in ["A", "B", "C", "D"]:
            return jsonify({
                "success": False,
                "error": "Correct Answer must be A, B, C or D."
            }), 400

        if difficulty not in ["easy", "medium", "hard"]:
            return jsonify({
                "success": False,
                "error": "Difficulty must be Easy, Medium or Hard."
            }), 400

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        # -------------------------------------------------
        # FIND EXISTING MOCK TEST
        # -------------------------------------------------

        c.execute("""
            SELECT id
            FROM mock_tests
            WHERE mock_test_no=?
              AND board=?
              AND class_name=?
              AND subject=?
            LIMIT 1
        """, (
            mock_test_no,
            board,
            class_name,
            subject
        ))

        test_row = c.fetchone()

        # -------------------------------------------------
        # CREATE MOCK TEST IF NOT EXISTS
        # -------------------------------------------------

        if test_row:

            mock_test_id = test_row[0]

        else:

            test_name = f"Mock Test {mock_test_no}"

            c.execute("""
                INSERT INTO mock_tests (
                    mock_test_no,
                    board,
                    class_name,
                    subject,
                    test_name,
                    syllabus_scope,
                    total_questions,
                    total_marks,
                    duration_minutes,
                    price_inr,
                    attempt_limit,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mock_test_no,
                board,
                class_name,
                subject,
                test_name,
                "",
                50,
                100,
                60,
                1,
                1,
                1
            ))

            mock_test_id = c.lastrowid

        # -------------------------------------------------
        # ADD QUESTION
        # -------------------------------------------------

        c.execute("""
            INSERT INTO mock_questions (
                mock_test_id,
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer,
                explanation,
                hint,
                marks,
                active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mock_test_id,
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty,
            question,
            option_a,
            option_b,
            option_c,
            option_d,
            correct_answer,
            explanation,
            hint,
            2,
            1
        ))

        question_id = c.lastrowid

        # -------------------------------------------------
        # UPDATE QUESTION COUNT
        # -------------------------------------------------

        c.execute("""
            SELECT COUNT(*)
            FROM mock_questions
            WHERE mock_test_id=?
              AND active=1
        """, (mock_test_id,))

        question_count = c.fetchone()[0]

        c.execute("""
            UPDATE mock_tests
            SET total_questions=?,
                total_marks=?
            WHERE id=?
        """, (
            question_count,
            question_count * 2,
            mock_test_id
        ))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Mock question added successfully.",
            "question_id": question_id,
            "mock_test_id": mock_test_id,
            "question_count": question_count
        })

    except Exception as e:

        print("ADD MOCK QUESTION ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =====================================================
# ADMIN - DELETE MOCK QUESTION
# =====================================================

@app.route("/admin/mock-questions/delete/<int:question_id>", methods=["POST"])
def admin_delete_mock_question(question_id):

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        c.execute("""
            SELECT mock_test_id
            FROM mock_questions
            WHERE id=?
        """, (question_id,))

        row = c.fetchone()

        if not row:
            conn.close()

            return jsonify({
                "success": False,
                "error": "Question not found."
            }), 404

        mock_test_id = row[0]

        c.execute("""
            DELETE FROM mock_questions
            WHERE id=?
        """, (question_id,))

        # Update test count
        c.execute("""
            SELECT COUNT(*)
            FROM mock_questions
            WHERE mock_test_id=?
              AND active=1
        """, (mock_test_id,))

        question_count = c.fetchone()[0]

        c.execute("""
            UPDATE mock_tests
            SET total_questions=?,
                total_marks=?
            WHERE id=?
        """, (
            question_count,
            question_count * 2,
            mock_test_id
        ))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Mock question deleted successfully."
        })

    except Exception as e:

        print("DELETE MOCK QUESTION ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =====================================================
# ADMIN - DELETE MOCK TEST
# =====================================================

@app.route("/admin/mock-tests/delete/<int:test_id>", methods=["POST"])
def admin_delete_mock_test(test_id):

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        c.execute("""
            SELECT id
            FROM mock_tests
            WHERE id=?
        """, (test_id,))

        row = c.fetchone()

        if not row:
            conn.close()

            return jsonify({
                "success": False,
                "error": "Mock Test not found."
            }), 404

        # Delete all questions first
        c.execute("""
            DELETE FROM mock_questions
            WHERE mock_test_id=?
        """, (test_id,))

        # Delete mock test
        c.execute("""
            DELETE FROM mock_tests
            WHERE id=?
        """, (test_id,))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Mock Test and all its questions deleted."
        })

    except Exception as e:

        print("DELETE MOCK TEST ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# ADMIN - RESET MOCK TEST
# =====================================================

@app.route(
    "/admin/mock-tests/reset/<int:test_id>",
    methods=["POST"]
)
def admin_reset_mock_test(test_id):

    if not session.get("admin"):

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403


    conn = None

    try:

        conn = sqlite3.connect(DB_PATH)

        c = conn.cursor()


        # ---------------------------------------------
        # CHECK MOCK TEST
        # ---------------------------------------------

        c.execute("""
            SELECT id
            FROM mock_tests
            WHERE id=?
        """, (
            test_id,
        ))


        test = c.fetchone()


        if not test:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Mock Test not found."
            }), 404


        # ---------------------------------------------
        # RESET ACTIVE / EXISTING ATTEMPTS
        # ---------------------------------------------

        c.execute("""
            UPDATE mock_attempts
            SET
                status='expired',
                submitted_at=NULL,
                answers='{}',
                correct_answers=0,
                incorrect_answers=0,
                unanswered=0,
                score=0,
                percentage=0,
                rank=NULL
            WHERE mock_test_id=?
        """, (
            test_id,
        ))


        reset_attempts = c.rowcount


        # ---------------------------------------------
        # CLEAR OLD LEADERBOARD RESULTS
        # ---------------------------------------------

        c.execute("""
            DELETE FROM mock_results
            WHERE mock_test_id=?
        """, (
            test_id,
        ))


        cleared_results = c.rowcount


        conn.commit()

        conn.close()


        return jsonify({

            "success": True,

            "reset_attempts":
                reset_attempts,

            "cleared_results":
                cleared_results

        })


    except Exception as e:

        if conn:

            conn.close()


        print(
            "RESET MOCK TEST ERROR:",
            e
        )


        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
        

# =====================================================
# ADMIN - IMPORT MOCK QUESTIONS FROM EXCEL
# NEW 3-CATEGORY SYSTEM
# =====================================================

@app.route(
    "/admin/mock-questions/import-excel",
    methods=["POST"]
)
def admin_import_mock_questions_excel():

    if not session.get("admin"):

        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    conn = None

    try:

        # =================================================
        # 1. GET FORM DATA
        # =================================================

        mock_type = str(
            request.form.get("mock_type", "")
        ).strip()

        board = str(
            request.form.get("board", "")
        ).strip()

        class_name = str(
            request.form.get("class_name", "")
        ).strip()

        subject = str(
            request.form.get("subject", "")
        ).strip()

        chapter_scope = str(
            request.form.get("chapter_scope", "")
        ).strip()


        # =================================================
        # 2. VALIDATE MOCK TYPE
        # =================================================

        allowed_types = [
            "chapter",
            "four_chapter",
            "full_syllabus"
        ]

        if mock_type not in allowed_types:

            return jsonify({
                "success": False,
                "error": "Invalid Mock Test Type."
            }), 400


        # =================================================
        # 3. VALIDATE BASIC DETAILS
        # =================================================

        if not board:

            return jsonify({
                "success": False,
                "error": "Board is required."
            }), 400


        if not class_name:

            return jsonify({
                "success": False,
                "error": "Class is required."
            }), 400


        if not subject:

            return jsonify({
                "success": False,
                "error": "Subject is required."
            }), 400


        # =================================================
        # 4. VALIDATE CHAPTER SCOPE
        # =================================================

        if mock_type == "chapter":

            if not chapter_scope:

                return jsonify({
                    "success": False,
                    "error":
                        "Please select a chapter."
                }), 400


        elif mock_type == "four_chapter":

            if not chapter_scope:

                return jsonify({
                    "success": False,
                    "error":
                        "Please select four chapters."
                }), 400


            chapters = [
                x.strip()
                for x in chapter_scope.split("|")
                if x.strip()
            ]

            if len(chapters) != 4:

                return jsonify({
                    "success": False,
                    "error":
                        "Exactly four chapters are required."
                }), 400


            if len(set(chapters)) != 4:

                return jsonify({
                    "success": False,
                    "error":
                        "Four different chapters are required."
                }), 400


        elif mock_type == "full_syllabus":

            chapter_scope = "FULL_SYLLABUS"


        # =================================================
        # 5. GET EXCEL FILE
        # =================================================

        if "excel_file" not in request.files:

            return jsonify({
                "success": False,
                "error": "Excel file is required."
            }), 400


        file = request.files["excel_file"]


        if not file or not file.filename:

            return jsonify({
                "success": False,
                "error":
                    "Please select an Excel file."
            }), 400


        if not file.filename.lower().endswith(
            (".xlsx", ".xls")
        ):

            return jsonify({
                "success": False,
                "error":
                    "Only .xlsx or .xls files are supported."
            }), 400


        # =================================================
        # 6. READ EXCEL
        # =================================================

        df = pd.read_excel(file)

        df = df.dropna(how="all")


        if df.empty:

            return jsonify({
                "success": False,
                "error":
                    "The Excel file contains no questions."
            }), 400


        # =================================================
        # 7. NORMALIZE COLUMN NAMES
        # =================================================

        df.columns = [

            str(col)
            .strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")

            for col in df.columns

        ]


        rename_map = {

            "a":
                "option_a",

            "b":
                "option_b",

            "c":
                "option_c",

            "d":
                "option_d",

            "answer":
                "correct_answer",

            "correct":
                "correct_answer",

            "correct_option":
                "correct_answer",

            "explanation_text":
                "explanation",

            "hint_text":
                "hint"

        }


        df.rename(
            columns={
                old: new
                for old, new in rename_map.items()
                if old in df.columns
            },
            inplace=True
        )


        # =================================================
        # 8. REQUIRED EXCEL COLUMNS
        # =================================================

        required_columns = [

            "question",

            "option_a",

            "option_b",

            "option_c",

            "option_d",

            "correct_answer"

        ]


        missing_columns = [

            col
            for col in required_columns
            if col not in df.columns

        ]


        if missing_columns:

            return jsonify({

                "success": False,

                "error":
                    "Missing Excel columns: "
                    +
                    ", ".join(
                        missing_columns
                    )

            }), 400


        # =================================================
        # 9. DATABASE
        # =================================================

        conn = sqlite3.connect(
            DB_PATH
        )

        c = conn.cursor()


        # =================================================
        # 10. INTERNAL LEGACY TEST NUMBER
        # =================================================
        #
        # IMPORTANT:
        # User does NOT select Mock Test No.
        #
        # This value is only kept internally because
        # the existing database still has mock_test_no
        # as a NOT NULL field.
        #
        # It is NOT shown in the Admin UI.
        # =================================================

        type_code = {

            "chapter": 1,

            "four_chapter": 2,

            "full_syllabus": 3

        }[mock_type]


        # Find existing tests for same configuration.

        c.execute("""
            SELECT id
            FROM mock_tests
            WHERE board=?
              AND class_name=?
              AND subject=?
              AND mock_type=?
              AND chapter_scope=?
            LIMIT 1
        """, (

            board,
            class_name,
            subject,
            mock_type,
            chapter_scope

        ))


        existing_test = c.fetchone()


        # =================================================
        # 11. CREATE / REUSE MOCK TEST
        # =================================================

        if existing_test:

            mock_test_id = existing_test[0]

            # Clear previous questions when the
            # same configuration is re-uploaded.

            c.execute("""
                DELETE FROM mock_questions
                WHERE mock_test_id=?
            """, (
                mock_test_id,
            ))


        else:

            # Generate internal number.
            #
            # Example:
            # chapter       -> 100001+
            # four_chapter  -> 200001+
            # full_syllabus -> 300001+

            c.execute("""
                SELECT
                    COALESCE(
                        MAX(mock_test_no),
                        0
                    )
                FROM mock_tests
                WHERE board=?
                  AND class_name=?
                  AND subject=?
            """, (

                board,
                class_name,
                subject

            ))


            max_no = c.fetchone()[0] or 0


            mock_test_no = max(
                max_no + 1,
                type_code * 100000 + 1
            )


            if mock_type == "chapter":

                test_name = (
                    f"{chapter_scope} - Chapter Mock"
                )

            elif mock_type == "four_chapter":

                test_name = (
                    "4-Chapter Mock"
                )

            else:

                test_name = (
                    "Final Test - Full Syllabus"
                )


            c.execute("""
                INSERT INTO mock_tests
                (
                    mock_test_no,
                    board,
                    class_name,
                    subject,
                    test_name,
                    syllabus_scope,
                    total_questions,
                    total_marks,
                    duration_minutes,
                    price_inr,
                    attempt_limit,
                    active,
                    mock_type,
                    chapter_scope
                )
                VALUES
                (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
            """, (

                mock_test_no,

                board,

                class_name,

                subject,

                test_name,

                chapter_scope,

                0,

                0,

                60,

                0,

                1,

                1,

                mock_type,

                chapter_scope

            ))


            mock_test_id = c.lastrowid


        # =================================================
        # 12. IMPORT QUESTIONS
        # =================================================

        imported = 0

        skipped = 0

        errors = []


        for index, row in df.iterrows():

            excel_row = index + 2

            try:

                # -----------------------------------------
                # QUESTION
                # -----------------------------------------

                question = str(
                    row["question"]
                ).strip()


                option_a = str(
                    row["option_a"]
                ).strip()


                option_b = str(
                    row["option_b"]
                ).strip()


                option_c = str(
                    row["option_c"]
                ).strip()


                option_d = str(
                    row["option_d"]
                ).strip()


                correct_answer = str(
                    row["correct_answer"]
                ).strip().upper()


                explanation = ""

                if "explanation" in df.columns:

                    value = row["explanation"]

                    if pd.notna(value):

                        explanation = str(
                            value
                        ).strip()


                hint = ""

                if "hint" in df.columns:

                    value = row["hint"]

                    if pd.notna(value):

                        hint = str(
                            value
                        ).strip()


                # -----------------------------------------
                # VALIDATION
                # -----------------------------------------

                if not all([

                    question,

                    option_a,

                    option_b,

                    option_c,

                    option_d,

                    correct_answer

                ]):

                    skipped += 1

                    errors.append(
                        f"Row {excel_row}: "
                        "Required value missing."
                    )

                    continue


                if correct_answer not in [
                    "A",
                    "B",
                    "C",
                    "D"
                ]:

                    skipped += 1

                    errors.append(
                        f"Row {excel_row}: "
                        "Answer must be A, B, C or D."
                    )

                    continue


                # -----------------------------------------
                # DUPLICATE CHECK
                # -----------------------------------------

                c.execute("""
                    SELECT id
                    FROM mock_questions
                    WHERE mock_test_id=?
                      AND question=?
                    LIMIT 1
                """, (

                    mock_test_id,

                    question

                ))


                if c.fetchone():

                    skipped += 1

                    continue


                # -----------------------------------------
                # INSERT
                # -----------------------------------------
                #
                # topic/subtopic/difficulty are retained
                # temporarily only because the current
                # database schema requires them.
                #
                # They are NOT part of the new Excel format.
                # -----------------------------------------

                c.execute("""
                    INSERT INTO mock_questions
                    (
                        mock_test_id,
                        board,
                        class_name,
                        subject,
                        topic,
                        subtopic,
                        difficulty,
                        question,
                        option_a,
                        option_b,
                        option_c,
                        option_d,
                        correct_answer,
                        explanation,
                        hint,
                        marks,
                        active
                    )
                    VALUES
                    (
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                """, (

                    mock_test_id,

                    board,

                    class_name,

                    subject,

                    "",

                    "",

                    "mixed",

                    question,

                    option_a,

                    option_b,

                    option_c,

                    option_d,

                    correct_answer,

                    explanation,

                    hint,

                    2,

                    1

                ))


                imported += 1


            except Exception as row_error:

                skipped += 1

                errors.append(
                    f"Row {excel_row}: "
                    f"{str(row_error)}"
                )


        # =================================================
        # 13. UPDATE QUESTION COUNT
        # =================================================

        c.execute("""
            SELECT COUNT(*)
            FROM mock_questions
            WHERE mock_test_id=?
              AND active=1
        """, (
            mock_test_id,
        ))


        question_count = c.fetchone()[0]


        c.execute("""
            UPDATE mock_tests
            SET
                total_questions=?,
                total_marks=?,
                active=1
            WHERE id=?
        """, (

            question_count,

            question_count * 2,

            mock_test_id

        ))


        # =================================================
        # 14. COMMIT
        # =================================================

        conn.commit()

        conn.close()

        conn = None


        # =================================================
        # 15. RESPONSE
        # =================================================

        return jsonify({

            "success": True,

            "message":
                "Mock Test Excel imported successfully.",

            "mock_test_id":
                mock_test_id,

            "mock_type":
                mock_type,

            "board":
                board,

            "class_name":
                class_name,

            "subject":
                subject,

            "chapter_scope":
                chapter_scope,

            "imported":
                imported,

            "skipped":
                skipped,

            "question_count":
                question_count,

            "errors":
                errors[:50]

        })


    except Exception as e:

        if conn:

            try:
                conn.rollback()
                conn.close()
            except:
                pass


        print(
            "IMPORT MOCK EXCEL ERROR:",
            str(e)
        )


        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500



@app.route("/download-salary-pdf")
def download_salary_pdf():

    if not session.get("admin"):
        return redirect("/admin")

    month = request.args.get("month", "All Months")

    return f"""

    <h1>Salary PDF Download</h1>

    <p>Month: {month}</p>

    <p>PDF generation next step la add pannalam </p>

    """

from werkzeug.utils import secure_filename

SYLLABUS_FOLDER = os.path.join("/var/data", "syllabus_files")
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
                    conn = sqlite3.connect("/var/data/students.db")

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
    conn = sqlite3.connect("/var/data/students.db")

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

        conn = sqlite3.connect("/var/data/students.db")
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
# =====================================================
# ADMIN - PRACTICE QUESTION BANK
# =====================================================

@app.route("/admin/practice-questions", methods=["GET"])
def admin_practice_questions():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        # =================================================
        # FILTERS
        # =================================================

        board = request.args.get(
            "board", ""
        ).strip()

        class_name = request.args.get(
            "class_name", ""
        ).strip()

        subject = request.args.get(
            "subject", ""
        ).strip()

        topic = request.args.get(
            "topic", ""
        ).strip()

        subtopic = request.args.get(
            "subtopic", ""
        ).strip()

        difficulty = request.args.get(
            "difficulty", ""
        ).strip().lower()


        # =================================================
        # PAGINATION
        # =================================================

        try:
            page = int(
                request.args.get(
                    "page",
                    1
                )
            )
        except:
            page = 1

        try:
            limit = int(
                request.args.get(
                    "limit",
                    50
                )
            )
        except:
            limit = 50


        # Safety limits
        if page < 1:
            page = 1

        if limit < 1:
            limit = 50

        if limit > 100:
            limit = 100


        offset = (
            page - 1
        ) * limit


        # =================================================
        # DATABASE
        # =================================================

        conn = sqlite3.connect(
            "/var/data/students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()


        # =================================================
        # BUILD WHERE CONDITION
        # =================================================

        where_conditions = []
        params = []

        # BOARD FILTER
        if board:
            where_conditions.append(
                "LOWER(TRIM(board)) = ?"
            )
            params.append(board.strip().lower())

        # CLASS FILTER
        if class_name:
            where_conditions.append("""
                TRIM(
                    REPLACE(
                        LOWER(TRIM(class_name)),
                        'class',
                        ''
                    )
                ) = ?
            """)

            normalized_class = (
                class_name.lower()
                .replace("class", "")
                .strip()
            )

            params.append(normalized_class)

        # SUBJECT FILTER
        if subject:
            where_conditions.append(
                "LOWER(TRIM(subject)) = ?"
            )
            params.append(subject.strip().lower())

        # TOPIC FILTER
        if topic:
            where_conditions.append(
                "LOWER(TRIM(topic)) = ?"
            )
            params.append(topic.strip().lower())

        # SUBTOPIC FILTER
        if subtopic:
            where_conditions.append(
                "LOWER(TRIM(subtopic)) = ?"
            )
            params.append(subtopic.strip().lower())

        # DIFFICULTY FILTER
        if difficulty:
            where_conditions.append(
                "LOWER(TRIM(difficulty)) = ?"
            )
            params.append(difficulty.strip().lower())

        # =================================================
        # WHERE SQL
        # =================================================

        where_sql = ""

        if where_conditions:

            where_sql = (
                " WHERE "
                +
                " AND ".join(
                    where_conditions
                )
            )


        # =================================================
        # TOTAL COUNT
        # =================================================

        count_query = f"""
            SELECT COUNT(*)
            FROM practice_questions
            {where_sql}
        """

        c.execute(
            count_query,
            params
        )

        total_count = c.fetchone()[0]


        # =================================================
        # TOTAL PAGES
        # =================================================

        total_pages = (
            (total_count + limit - 1)
            // limit
        )


        # =================================================
        # GET ONLY CURRENT PAGE
        # =================================================

        question_query = f"""
            SELECT

                id,
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer,
                explanation,
                hint,
                marks,
                active,
                created_at

            FROM practice_questions

            {where_sql}

            ORDER BY id DESC

            LIMIT ?
            OFFSET ?
        """


        question_params = (
            params
            + [
                limit,
                offset
            ]
        )


        c.execute(
            question_query,
            question_params
        )


        rows = c.fetchall()


        # =================================================
        # FORMAT QUESTIONS
        # =================================================

        questions = []


        for row in rows:

            questions.append({

                "id":
                    row["id"],

                "board":
                    row["board"],

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

                "question":
                    row["question"],

                "option_a":
                    row["option_a"],

                "option_b":
                    row["option_b"],

                "option_c":
                    row["option_c"],

                "option_d":
                    row["option_d"],

                "correct_answer":
                    row["correct_answer"],

                "explanation":
                    row["explanation"] or "",

                "hint":
                    row["hint"] or "",

                "marks":
                    row["marks"],

                "active":
                    bool(
                        row["active"]
                    ),

                "created_at":
                    row["created_at"]

            })


        conn.close()


        # =================================================
        # RESPONSE
        # =================================================

        return jsonify({

            "success":
                True,

            "questions":
                questions,

            "count":
                len(questions),

            "total":
                total_count,

            "page":
                page,

            "limit":
                limit,

            "total_pages":
                total_pages

        })


    except Exception as e:

        print(
            "ADMIN PRACTICE QUESTIONS ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500

# =====================================================
# ADMIN - IMPORT PRACTICE QUESTIONS FROM EXCEL
# =====================================================

@app.route("/admin/practice-questions/import-excel", methods=["POST"])
def import_practice_questions_excel():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        # -------------------------------------------------
        # 1. CHECK FILE
        # -------------------------------------------------

        if "excel_file" not in request.files:
            return jsonify({
                "success": False,
                "error": "Excel file not selected."
            }), 400

        file = request.files["excel_file"]

        if not file or not file.filename:
            return jsonify({
                "success": False,
                "error": "Excel file not selected."
            }), 400

        if not file.filename.lower().endswith((".xlsx", ".xls")):
            return jsonify({
                "success": False,
                "error": "Please upload an Excel file (.xlsx or .xls)."
            }), 400


        # -------------------------------------------------
        # 2. READ EXCEL
        # -------------------------------------------------

        df = pd.read_excel(file)
        # Optional diagram ID column
        if "Diagram_ID" not in df.columns:
            df["Diagram_ID"] = ""
        
        df["Diagram_ID"] = (
            df["Diagram_ID"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        # Remove completely empty rows
        df = df.dropna(how="all")


        # -------------------------------------------------
        # 3. REQUIRED COLUMNS
        # -------------------------------------------------

        required_columns = [
            "Board",
            "Class",
            "Subject",
            "Topic",
            "Subtopic",
            "Difficulty",
            "Question",
            "A",
            "B",
            "C",
            "D",
            "Answer"
        ]

        missing_columns = [
            col for col in required_columns
            if col not in df.columns
        ]

        if missing_columns:

            return jsonify({
                "success": False,
                "error":
                    "Missing Excel columns: "
                    + ", ".join(missing_columns)
            }), 400

         # -------------------------------------------------
        # OPTIONAL DIAGRAM ZIP UPLOAD
        # -------------------------------------------------
        
        diagram_map = {}
        
        diagram_zip = request.files.get("diagram_zip")
        
        if diagram_zip and diagram_zip.filename:
            if not diagram_zip.filename.lower().endswith(".zip"):
                return jsonify({
                    "success": False,
                    "error": "Diagram images must be uploaded as a ZIP file."
                }), 400
        
            try:
                with zipfile.ZipFile(diagram_zip) as archive:
                    for member in archive.infolist():
        
                        if member.is_dir():
                            continue
        
                        # Ignore files inside subfolders
                        original_name = os.path.basename(member.filename)
                        diagram_id = os.path.splitext(original_name)[0]
        
                        if not diagram_id:
                            continue
        
                        safe_id = secure_filename(diagram_id)
                        extension = os.path.splitext(original_name)[1].lower()
        
                        if extension not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                            continue
        
                        if not safe_id:
                            continue
        
                        # Unique filename avoids accidental overwrites
                        saved_name = f"{safe_id}_{uuid.uuid4().hex[:8]}{extension}"
                        save_path = os.path.join(
                            PRACTICE_DIAGRAM_FOLDER,
                            saved_name
                        )
        
                        with archive.open(member) as source:
                            with open(save_path, "wb") as destination:
                                destination.write(source.read())
        
                        diagram_map[diagram_id] = saved_name
        
            except zipfile.BadZipFile:
                return jsonify({
                    "success": False,
                    "error": "The diagram ZIP file is invalid."
                }), 400
        # -------------------------------------------------
        # 4. DATABASE
        # -------------------------------------------------

        
        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        # -------------------------------------------------
        # CHECK: ONE BOARD + CLASS + SUBJECT PER FILE
        # -------------------------------------------------

        def get_single_value(column):
            values = (
                df[column]
                .dropna()
                .astype(str)
                .str.strip()
            )
            values = values[values != ""].unique().tolist()

            return values[0] if len(values) == 1 else None

        upload_board = get_single_value("Board")
        upload_class = get_single_value("Class")
        upload_subject = get_single_value("Subject")

        if not all([upload_board, upload_class, upload_subject]):
            conn.close()
            return jsonify({
                "success": False,
                "error": "Excel must contain one Board, one Class and one Subject."
            }), 400

        # -------------------------------------------------
        # PRE-VALIDATE ALL ROWS BEFORE REPLACING OLD BANK
        # -------------------------------------------------

        validation_errors = []

        for excel_row, row in df.iterrows():
            row_number = excel_row + 2

            difficulty = str(row["Difficulty"]).strip().lower()
            answer = str(row["Answer"]).strip().upper()

            required_values = [
                row["Board"], row["Class"], row["Subject"],
                row["Topic"], row["Subtopic"], row["Question"],
                row["A"], row["B"], row["C"], row["D"]
            ]

            if difficulty not in ["easy", "medium", "hard"]:
                validation_errors.append(
                    f"Row {row_number}: Invalid difficulty."
                )
            elif answer not in ["A", "B", "C", "D"]:
                validation_errors.append(
                    f"Row {row_number}: Invalid answer."
                )
            elif any(pd.isna(v) or not str(v).strip()
                     for v in required_values):
                validation_errors.append(
                    f"Row {row_number}: Required field is empty."
                )

        if validation_errors:
            conn.close()
            return jsonify({
                "success": False,
                "error": "Excel validation failed. Existing questions were not deleted.",
                "error_count": len(validation_errors),
                "errors": validation_errors[:50]
            }), 400

        # -------------------------------------------------
        # REPLACE OLD QUESTIONS FOR THIS CLASS/SUBJECT
        # -------------------------------------------------

        c.execute("""
            DELETE FROM practice_questions
            WHERE board = ?
              AND class_name = ?
              AND subject = ?
        """, (upload_board, upload_class, upload_subject))

        # Remove previous upload summaries for this same bank
        c.execute("""
            DELETE FROM practice_question_uploads
            WHERE board = ?
              AND class_name = ?
              AND subject = ?
        """, (upload_board, upload_class, upload_subject))

        imported = 0
        skipped = 0
        errors = []



        # -------------------------------------------------
        # 5. PROCESS EACH ROW
        # -------------------------------------------------

        for excel_row, row in df.iterrows():

            row_number = excel_row + 2

            try:

                board = str(row["Board"]).strip()
                class_name = str(row["Class"]).strip()
                subject = str(row["Subject"]).strip()
                topic = str(row["Topic"]).strip()
                subtopic = str(row["Subtopic"]).strip()
                difficulty = str(row["Difficulty"]).strip().lower()

                question = str(row["Question"]).strip()

                option_a = str(row["A"]).strip()
                option_b = str(row["B"]).strip()
                option_c = str(row["C"]).strip()
                option_d = str(row["D"]).strip()

                correct_answer = str(row["Answer"]).strip().upper()

                explanation = ""

                if "Explanation" in df.columns:
                    value = row["Explanation"]

                    if pd.notna(value):
                        explanation = str(value).strip()

                hint = ""

                if "Hint" in df.columns:
                    value = row["Hint"]

                    if pd.notna(value):
                        hint = str(value).strip()


                # -------------------------------------------------
                # 6. VALIDATION
                # -------------------------------------------------

                if difficulty not in ["easy", "medium", "hard"]:
                    errors.append(
                        f"Row {row_number}: Invalid difficulty."
                    )
                    skipped += 1
                    continue


                if correct_answer not in ["A", "B", "C", "D"]:
                    errors.append(
                        f"Row {row_number}: Invalid answer."
                    )
                    skipped += 1
                    continue


                required_values = [
                    board,
                    class_name,
                    subject,
                    topic,
                    subtopic,
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d
                ]

                if not all(required_values):
                    errors.append(
                        f"Row {row_number}: Required field is empty."
                    )
                    skipped += 1
                    continue


                


                # -------------------------------------------------
                # 8. INSERT
                # -------------------------------------------------

                c.execute("""
                    INSERT INTO practice_questions
                    (
                        board,
                        class_name,
                        subject,
                        topic,
                        subtopic,
                        difficulty,
                        question,
                        option_a,
                        option_b,
                        option_c,
                        option_d,
                        correct_answer,
                        explanation,
                        hint,
                        marks,
                        active,
                        diagram_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    board,
                    class_name,
                    subject,
                    topic,
                    subtopic,
                    difficulty,
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_answer,
                    explanation,
                    hint,
                    2,
                    1,
                    diagram_map.get(
                        str(row.get("Diagram_ID", "")).strip()
                    )
                ))

                imported += 1


            except Exception as row_error:

                errors.append(
                    f"Row {row_number}: {str(row_error)}"
                )

                skipped += 1

        
        # -------------------------------------------------
        # SAVE PRACTICE EXCEL UPLOAD HISTORY
        # -------------------------------------------------

        def single_value(column):
            values = (
                df[column]
                .dropna()
                .astype(str)
                .str.strip()
                .unique()
                .tolist()
            )
            return values[0] if len(values) == 1 else (
                "Multiple" if values else ""
            )

        difficulty_values = (
            df["Difficulty"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        easy_count = int((difficulty_values == "easy").sum())
        medium_count = int((difficulty_values == "medium").sum())
        hard_count = int((difficulty_values == "hard").sum())

        c.execute("""
            INSERT INTO practice_question_uploads
            (
                filename,
                board,
                class_name,
                subject,
                total_rows,
                imported,
                skipped,
                easy_count,
                medium_count,
                hard_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file.filename,
            single_value("Board"),
            single_value("Class"),
            single_value("Subject"),
            len(df),
            imported,
            skipped,
            easy_count,
            medium_count,
            hard_count
        ))

       
        # -------------------------------------------------
        # 9. SAVE + SAFE ERROR HANDLING
        # -------------------------------------------------

        conn.commit()
        conn.close()

        # -------------------------------------------------
        # 10. RESPONSE
        # -------------------------------------------------

        return jsonify({
            "success": True,
            "message": "Excel import completed.",
            "board": upload_board,
            "class_name": upload_class,
            "subject": upload_subject,
            "total_rows": len(df),
            "imported": imported,
            "skipped": skipped,
            "errors": errors
        })

    except Exception as e:

        # Roll back uncommitted database changes when possible
        try:
            conn.rollback()
            conn.close()
        except Exception:
            pass

        print("IMPORT PRACTICE EXCEL ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# ADMIN - PRACTICE TEST LIBRARY
# =====================================================

@app.route("/admin/practice-questions/library", methods=["GET"])
def admin_practice_question_library():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:
        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                id,
                filename,
                board,
                class_name,
                subject,
                total_rows,
                imported,
                skipped,
                easy_count,
                medium_count,
                hard_count,
                uploaded_at
            FROM practice_question_uploads
            ORDER BY id DESC
        """)

        uploads = [dict(row) for row in c.fetchall()]

        # Current question totals for each Board/Class/Subject
        c.execute("""
            SELECT
                board,
                class_name,
                subject,
                COUNT(*) AS total_questions,
                SUM(CASE WHEN LOWER(difficulty) = 'easy'
                    THEN 1 ELSE 0 END) AS easy_count,
                SUM(CASE WHEN LOWER(difficulty) = 'medium'
                    THEN 1 ELSE 0 END) AS medium_count,
                SUM(CASE WHEN LOWER(difficulty) = 'hard'
                    THEN 1 ELSE 0 END) AS hard_count,
                SUM(CASE WHEN active = 1
                    THEN 1 ELSE 0 END) AS active_questions
            FROM practice_questions
            GROUP BY board, class_name, subject
            ORDER BY board, class_name, subject
        """)

        question_banks = [
            dict(row) for row in c.fetchall()
        ]

        conn.close()

        return jsonify({
            "success": True,
            "uploads": uploads,
            "question_banks": question_banks
        })

    except Exception as e:
        print("PRACTICE LIBRARY ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# ADMIN - DELETE ONE PRACTICE QUESTION BANK
# =====================================================

@app.route("/admin/practice-questions/delete-bank", methods=["POST"])
def delete_practice_question_bank():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    conn = None

    try:
        data = request.get_json() or {}

        board = str(data.get("board", "")).strip()
        class_name = str(data.get("class_name", "")).strip()
        subject = str(data.get("subject", "")).strip()

        if not board or not class_name or not subject:
            return jsonify({
                "success": False,
                "error": "Board, class and subject are required."
            }), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Begin one transaction for both deletions
        c.execute("BEGIN")

        # 1. Delete questions only for the selected bank
        c.execute("""
            DELETE FROM practice_questions
            WHERE LOWER(TRIM(board)) = LOWER(TRIM(?))
              AND LOWER(TRIM(class_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(subject)) = LOWER(TRIM(?))
        """, (board, class_name, subject))

        deleted_questions = c.rowcount

        # 2. Delete matching Excel upload history
        c.execute("""
            DELETE FROM practice_question_uploads
            WHERE LOWER(TRIM(board)) = LOWER(TRIM(?))
              AND LOWER(TRIM(class_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(subject)) = LOWER(TRIM(?))
        """, (board, class_name, subject))

        deleted_uploads = c.rowcount

        # Commit only after both operations succeed
        conn.commit()

        return jsonify({
            "success": True,
            "deleted": deleted_questions,
            "deleted_questions": deleted_questions,
            "deleted_uploads": deleted_uploads,
            "board": board,
            "class_name": class_name,
            "subject": subject,
            "message": "Practice question bank and matching upload history deleted successfully."
        })

    except Exception as e:
        if conn:
            conn.rollback()

        print("DELETE PRACTICE QUESTION BANK ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:
        if conn:
            conn.close()

# =====================================================
# ADMIN - ADD PRACTICE QUESTION
# =====================================================

@app.route("/admin/practice-questions/add", methods=["POST"])
def add_practice_question():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        data = request.get_json() or {}

        board = data.get("board", "").strip()
        class_name = data.get("class_name", "").strip()
        subject = data.get("subject", "").strip()
        topic = data.get("topic", "").strip()
        subtopic = data.get("subtopic", "").strip()
        difficulty = data.get("difficulty", "").strip().lower()

        question = data.get("question", "").strip()

        option_a = data.get("option_a", "").strip()
        option_b = data.get("option_b", "").strip()
        option_c = data.get("option_c", "").strip()
        option_d = data.get("option_d", "").strip()

        correct_answer = data.get(
            "correct_answer",
            ""
        ).strip().upper()

        explanation = data.get(
            "explanation",
            ""
        ).strip()

        hint = data.get(
            "hint",
            ""
        ).strip()

        # =================================================
        # VALIDATION
        # =================================================

        if not board:
            return jsonify({
                "success": False,
                "error": "Board is required."
            }), 400

        if not class_name:
            return jsonify({
                "success": False,
                "error": "Class is required."
            }), 400

        if not subject:
            return jsonify({
                "success": False,
                "error": "Subject is required."
            }), 400

        if not topic:
            return jsonify({
                "success": False,
                "error": "Chapter / Topic is required."
            }), 400

        if not subtopic:
            return jsonify({
                "success": False,
                "error": "Subtopic is required."
            }), 400

        if difficulty not in [
            "easy",
            "medium",
            "hard"
        ]:
            return jsonify({
                "success": False,
                "error": "Difficulty must be Easy, Medium or Hard."
            }), 400

        if not question:
            return jsonify({
                "success": False,
                "error": "Question is required."
            }), 400

        if not option_a or not option_b or not option_c or not option_d:
            return jsonify({
                "success": False,
                "error": "All four options are required."
            }), 400

        if correct_answer not in [
            "A",
            "B",
            "C",
            "D"
        ]:
            return jsonify({
                "success": False,
                "error": "Correct answer must be A, B, C or D."
            }), 400

        # =================================================
        # SAVE QUESTION
        # =================================================

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        c.execute("""
            INSERT INTO practice_questions
            (
                board,
                class_name,
                subject,
                topic,
                subtopic,
                difficulty,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer,
                explanation,
                hint,
                marks,
                active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty,
            question,
            option_a,
            option_b,
            option_c,
            option_d,
            correct_answer,
            explanation,
            hint,
            2,
            1
        ))

        question_id = c.lastrowid

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Practice question added successfully.",
            "question_id": question_id
        })

    except Exception as e:

        print("ADD PRACTICE QUESTION ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =====================================================
# ADMIN - DELETE PRACTICE QUESTION
# =====================================================

@app.route(
    "/admin/practice-questions/delete/<int:question_id>",
    methods=["POST"]
)
def delete_practice_question(question_id):

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        c.execute("""
            SELECT id
            FROM practice_questions
            WHERE id=?
        """, (question_id,))

        row = c.fetchone()

        if not row:
            conn.close()

            return jsonify({
                "success": False,
                "error": "Question not found."
            }), 404

        c.execute("""
            DELETE FROM practice_questions
            WHERE id=?
        """, (question_id,))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Practice question deleted successfully."
        })

    except Exception as e:

        print("DELETE PRACTICE QUESTION ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# ADMIN - DELETE ALL PRACTICE QUESTIONS
# =====================================================

@app.route(
    "/admin/practice-questions/delete-all",
    methods=["POST"]
)
def delete_all_practice_questions():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            DELETE FROM practice_questions
        """)

        deleted_count = c.rowcount

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "All practice questions deleted successfully.",
            "deleted": deleted_count
        })

    except Exception as e:

        print(
            "DELETE ALL PRACTICE QUESTIONS ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
 # =====================================================
# ADMIN - RESET ACTIVE PRACTICE SESSIONS
# =====================================================

@app.route(
    "/admin/practice-sessions/reset-active",
    methods=["POST"]
)
def reset_active_practice_sessions():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    conn = None

    try:

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            UPDATE practice_sessions
            SET status='expired'
            WHERE status='in_progress'
        """)

        reset_count = c.rowcount

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "reset": reset_count
        })

    except Exception as e:

        if conn:
            conn.close()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
# =====================================================
# ADMIN - PRACTICE QUESTION BANK COUNTS
# =====================================================

@app.route("/admin/practice-question-count")
def practice_question_count():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        board = request.args.get("board", "").strip()
        class_name = request.args.get("class_name", "").strip()
        subject = request.args.get("subject", "").strip()
        topic = request.args.get("topic", "").strip()
        subtopic = request.args.get("subtopic", "").strip()

        conn = sqlite3.connect("/var/data/students.db")
        c = conn.cursor()

        query = """
            SELECT difficulty, COUNT(*)
            FROM practice_questions
            WHERE active=1
        """

        params = []

        if board:
            query += " AND board=?"
            params.append(board)

        if class_name:
            query += " AND class_name=?"
            params.append(class_name)

        if subject:
            query += " AND subject=?"
            params.append(subject)

        if topic:
            query += " AND topic=?"
            params.append(topic)

        if subtopic:
            query += " AND subtopic=?"
            params.append(subtopic)

        query += """
            GROUP BY difficulty
        """

        c.execute(query, params)

        rows = c.fetchall()

        result = {
            "easy": 0,
            "medium": 0,
            "hard": 0,
            "total": 0
        }

        for difficulty, count in rows:

            difficulty = (
                difficulty or ""
            ).lower()

            if difficulty in result:
                result[difficulty] = count

            result["total"] += count

        conn.close()

        return jsonify({
            "success": True,
            "counts": result
        })

    except Exception as e:

        print(
            "PRACTICE QUESTION COUNT ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# RSC PRACTICE - CREATE / RESUME SESSION
# =====================================================
      
@app.route("/api/practice/session", methods=["POST"])
def practice_create_session():

    conn = None

    try:

        data = request.get_json() or {}

        # -------------------------------------------------
        # 1. GET PRACTICE ID
        # -------------------------------------------------

        practice_id = get_practice_id()

        # -------------------------------------------------
        # 2. GET REQUEST DATA
        # -------------------------------------------------

        board = str(
            data.get("board", "")
        ).strip()

        class_name = str(
            data.get("class_name", "")
        ).strip()

        subject = str(
            data.get("subject", "")
        ).strip()

        topic = str(
            data.get("topic", "")
        ).strip()

        subtopic = str(
            data.get("subtopic", "")
        ).strip()

        difficulty = str(
            data.get("difficulty", "")
        ).strip().lower()

        # -------------------------------------------------
        # 3. VALIDATION
        # -------------------------------------------------

        if not board:
            return jsonify({
                "success": False,
                "error": "Board is required."
            }), 400

        if not class_name:
            return jsonify({
                "success": False,
                "error": "Class is required."
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

        if difficulty not in [
            "easy",
            "medium",
            "hard"
        ]:
            return jsonify({
                "success": False,
                "error":
                    "Difficulty must be Easy, Medium or Hard."
            }), 400

        # -------------------------------------------------
        # 4. DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect("/var/data/students.db")
        conn.execute("PRAGMA foreign_keys = ON")

        conn.row_factory = sqlite3.Row
        
        c = conn.cursor()

        # -------------------------------------------------
        # 5. CHECK EXISTING IN-PROGRESS SESSION
        # -------------------------------------------------

        c.execute("""
            SELECT *
            FROM practice_sessions
            WHERE practice_id=?
            AND board=?
            AND class_name=?
            AND subject=?
            AND topic=?
            AND subtopic=?
            AND difficulty=?
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
            difficulty
        ))
        
        existing = c.fetchone()
        # Fresh Practice start: expire only the matching old session
        if data.get("new_attempt") and existing:
            c.execute("""
                UPDATE practice_sessions
                SET status='expired'
                WHERE id=?
                AND status='in_progress'
            """, (existing["id"],))

            conn.commit()
            existing = None
        
        # -------------------------------------------------
        # 6. CHECK SESSION TIME AND RESUME / EXPIRE
        # -------------------------------------------------

        if existing:

            session_is_active = False

            # ---------------------------------------------
            # CHECK ORIGINAL SESSION START TIME
            # ---------------------------------------------

            try:
                started_at = existing["started_at"]

                if started_at:
                    started_dt = datetime.strptime(
                        started_at,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    elapsed_seconds = (
                        datetime.now() - started_dt
                    ).total_seconds()

                    # Session is active only for 60 minutes
                    session_is_active = (
                        0 <= elapsed_seconds < (60 * 60)
                    )

            except Exception as session_time_error:
                print(
                    "PRACTICE SESSION TIME CHECK ERROR:",
                    session_time_error
                )
                session_is_active = False

            # ---------------------------------------------
            # ACTIVE SESSION → RESUME
            # ---------------------------------------------

            if session_is_active:

                try:
                    question_ids = json.loads(
                        existing["question_ids"] or "[]"
                    )
                except Exception:
                    question_ids = []

                try:
                    answers = json.loads(
                        existing["answers"] or "{}"
                    )
                except Exception:
                    answers = {}

                conn.close()

                return jsonify({
                    "success": True,
                    "resumed": True,
                    "session_id": existing["id"],
                    "practice_id": practice_id,
                    "board": existing["board"],
                    "class_name": existing["class_name"],
                    "subject": existing["subject"],
                    "topic": existing["topic"],
                    "subtopic": existing["subtopic"],
                    "difficulty": existing["difficulty"],
                    "total_questions": existing["total_questions"],
                    "total_marks": existing["total_marks"],
                    "question_ids": question_ids,
                    "answers": answers,
                    "current_question":
                        existing["current_question"] or 0,
                    "status": existing["status"],
                    "started_at": existing["started_at"]
                })

            # ---------------------------------------------
            # OLD / EXPIRED SESSION → MARK AS EXPIRED
            # ---------------------------------------------

            c.execute("""
                UPDATE practice_sessions
                SET status='expired'
                WHERE id=?
                AND status='in_progress'
            """, (
                existing["id"],
            ))

            conn.commit()

            print(
                "OLD PRACTICE SESSION EXPIRED:",
                existing["id"]
            )

        
        # -------------------------------------------------
        # 7. CHECK QUESTION BANK
        # -------------------------------------------------

        c.execute("""
            SELECT COUNT(*)
            FROM practice_questions
            WHERE board=?
            AND class_name=?
            AND subject=?
            AND topic=?
            AND subtopic=?
            AND difficulty=?
            AND active=1
        """, (
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty
        ))

        question_count = c.fetchone()[0]

        # -------------------------------------------------
        # 8. MINIMUM 50 QUESTIONS REQUIRED
        # -------------------------------------------------

        if question_count < 50:

            conn.close()

            return jsonify({

                "success": False,

                "error":
                    f"Only {question_count} active questions "
                    f"are available. Minimum 25 questions "
                    f"are required for this Practice test.",

                "available":
                    question_count,

                "required":
                    25

            }), 400

        # -------------------------------------------------
        # 9. RANDOMLY SELECT EXACTLY 25 QUESTIONS
        # -------------------------------------------------

        c.execute("""
            SELECT id
            FROM practice_questions
            WHERE board=?
            AND class_name=?
            AND subject=?
            AND topic=?
            AND subtopic=?
            AND difficulty=?
            AND active=1
            ORDER BY RANDOM()
            LIMIT 50
        """, (
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty
        ))

        rows = c.fetchall()

        question_ids = [
            row["id"]
            for row in rows
        ]

        # Safety check
        if len(question_ids) != 50:

            conn.close()

            return jsonify({

                "success": False,

                "error":
                    "Unable to create 25-question Practice session."

            }), 500

        # -------------------------------------------------
        # 10. INITIAL ANSWERS
        # -------------------------------------------------

        answers = {}

        # -------------------------------------------------
        # 11. START TIME
        # -------------------------------------------------

        started_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # -------------------------------------------------
        # 12. CREATE NEW SESSION
        # -------------------------------------------------

        c.execute("""
            INSERT INTO practice_sessions
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
                question_ids,
                answers,
                current_question,
                status,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            practice_id,
            board,
            class_name,
            subject,
            topic,
            subtopic,
            difficulty,
            50,
            100,
            json.dumps(question_ids),
            json.dumps(answers),
            0,
            "in_progress",
            started_at
        ))

        session_id = c.lastrowid

        conn.commit()

        conn.close()

        # -------------------------------------------------
        # 13. RETURN NEW SESSION
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

            "total_questions":
                50,

            "total_marks":
                100,

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

        if conn:
            try:
                conn.close()
            except:
                pass

        print(
            "PRACTICE CREATE SESSION ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
# =====================================================
# RSC PRACTICE - GET SESSION QUESTIONS
# =====================================================

@app.route("/api/practice/session/questions", methods=["GET"])
def practice_session_questions():

    conn = None

    try:

        # -------------------------------------------------
        # 1. PRACTICE ID
        # -------------------------------------------------

        practice_id = get_practice_id()

        # -------------------------------------------------
        # 2. SESSION ID
        # -------------------------------------------------

        session_id = request.args.get(
            "session_id"
        )

        if not session_id:

            return jsonify({
                "success": False,
                "error": "Session ID is required."
            }), 400

        try:

            session_id = int(
                session_id
            )

        except:

            return jsonify({
                "success": False,
                "error": "Invalid session ID."
            }), 400

        # -------------------------------------------------
        # 3. DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            DB_PATH
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # 4. GET SESSION
        # -------------------------------------------------

        c.execute("""
            SELECT *
            FROM practice_sessions
            WHERE id=?
            AND practice_id=?
            LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        practice_session = c.fetchone()

        if not practice_session:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Practice session not found."
            }), 404

        # -------------------------------------------------
        # 5. QUESTION IDS
        # -------------------------------------------------

        try:

            question_ids = json.loads(
                practice_session["question_ids"]
                or "[]"
            )

        except:

            question_ids = []

        if not isinstance(
            question_ids,
            list
        ) or len(question_ids) != 50:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Invalid question list in Practice session."
            }), 500

        # -------------------------------------------------
        # 6. SAVED ANSWERS
        # -------------------------------------------------

        try:

            saved_answers = json.loads(
                practice_session["answers"]
                or "{}"
            )

        except:

            saved_answers = {}

        # -------------------------------------------------
        # 7. LOAD QUESTIONS
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
                    board,
                    class_name,
                    subject,
                    topic,
                    subtopic,
                    difficulty,
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    marks,
                    diagram_path
                FROM practice_questions
                WHERE id=?
                AND active=1
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

            # -------------------------------------------------
            # IMPORTANT
            # -------------------------------------------------
            # DO NOT SEND correct_answer
            # during exam.
            # -------------------------------------------------

            questions.append({

                "id":
                    row["id"],

                "question":
                    row["question"],

                "options": [

                    row["option_a"],

                    row["option_b"],

                    row["option_c"],

                    row["option_d"]

                ],

                "topic":
                    row["topic"],

                "subtopic":
                    row["subtopic"],

                "difficulty":
                    row["difficulty"],

                "marks":
                    row["marks"] or 2,

                "saved_answer":
                    saved_answers.get(
                        str(row["id"])
                    ),
                "diagram_path": row["diagram_path"],

            })

        conn.close()

        # -------------------------------------------------
        # 8. RETURN
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
                practice_session[
                    "current_question"
                ] or 0,

            "status":
                practice_session[
                    "status"
                ],

            "started_at":
                practice_session[
                    "started_at"
                ],

            "total_questions":
                50,

            "total_marks":
                100

        })

    except Exception as e:

        if conn:
            try:
                conn.close()
            except:
                pass

        print(
            "PRACTICE GET QUESTIONS ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
# =====================================================
# RSC PRACTICE - SAVE ANSWER
# =====================================================

@app.route("/api/practice/session/save-answer", methods=["POST"])
def practice_session_save_answer():

    conn = None

    try:

        data = request.get_json() or {}

        practice_id = get_practice_id()

        session_id = data.get(
            "session_id"
        )

        question_id = data.get(
            "question_id"
        )

        answer = data.get(
            "answer"
        )

        current_question = data.get(
            "current_question"
        )

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

            session_id = int(
                session_id
            )

            question_id = int(
                question_id
            )

            answer = int(
                answer
            )

        except:

            return jsonify({
                "success": False,
                "error":
                    "Invalid session, question or answer."
            }), 400

        # Answer index:
        # 0 = A
        # 1 = B
        # 2 = C
        # 3 = D

        if answer not in [
            0,
            1,
            2,
            3
        ]:

            return jsonify({
                "success": False,
                "error":
                    "Invalid answer option."
            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            DB_PATH
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # GET SESSION
        # -------------------------------------------------

        c.execute("""
            SELECT *
            FROM practice_sessions
            WHERE id=?
            AND practice_id=?
            LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        practice_session = c.fetchone()

        if not practice_session:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Practice session not found."
            }), 404

        # -------------------------------------------------
        # SESSION STATUS
        # -------------------------------------------------

        if practice_session["status"] != "in_progress":

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "This Practice session is already completed."
            }), 400

        # -------------------------------------------------
        # QUESTION IDS
        # -------------------------------------------------

        try:

            question_ids = json.loads(
                practice_session["question_ids"]
                or "[]"
            )

        except:

            question_ids = []

        if question_id not in [
            int(x)
            for x in question_ids
        ]:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "This question does not belong "
                    "to this Practice session."
            }), 400

        # -------------------------------------------------
        # LOAD EXISTING ANSWERS
        # -------------------------------------------------

        try:

            answers = json.loads(
                practice_session["answers"]
                or "{}"
            )

        except:

            answers = {}

        # -------------------------------------------------
        # SAVE / UPDATE ANSWER
        # -------------------------------------------------

        answers[
            str(question_id)
        ] = answer

        # -------------------------------------------------
        # CURRENT QUESTION
        # -------------------------------------------------

        if current_question is not None:

            try:

                current_question = int(
                    current_question
                )

            except:

                current_question = (
                    practice_session[
                        "current_question"
                    ] or 0
                )

        else:

            current_question = (
                practice_session[
                    "current_question"
                ] or 0
            )

        # Safety limit

        if current_question < 0:
            current_question = 0

        if current_question > 49:
            current_question = 49

        # -------------------------------------------------
        # UPDATE SESSION
        # -------------------------------------------------

        c.execute("""
            UPDATE practice_sessions

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

        # -------------------------------------------------
        # RETURN
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "session_id":
                session_id,

            "question_id":
                question_id,

            "answer":
                answer,

            "current_question":
                current_question

            

        })

    except Exception as e:

        if conn:
            try:
                conn.close()
            except:
                pass

        print(
            "PRACTICE SAVE ANSWER ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
# =====================================================
# RSC PRACTICE - SUBMIT SESSION
# =====================================================

@app.route("/api/practice/session/submit", methods=["POST"])
def practice_session_submit():

    conn = None

    try:

        data = request.get_json() or {}

        practice_id = get_practice_id()

        session_id = data.get(
            "session_id"
        )

        submitted_answers = data.get(
            "answers",
            {}
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not session_id:

            return jsonify({
                "success": False,
                "error":
                    "Session ID is required."
            }), 400

        try:

            session_id = int(
                session_id
            )

        except:

            return jsonify({
                "success": False,
                "error":
                    "Invalid session ID."
            }), 400

        if not isinstance(
            submitted_answers,
            dict
        ):

            return jsonify({
                "success": False,
                "error":
                    "Invalid answer data."
            }), 400

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        conn = sqlite3.connect(
            DB_PATH
        )
        conn.row_factory = sqlite3.Row

        c = conn.cursor()

        # -------------------------------------------------
        # GET SESSION
        # -------------------------------------------------

        c.execute("""
            SELECT *
            FROM practice_sessions
            WHERE id=?
            AND practice_id=?
            LIMIT 1
        """, (
            session_id,
            practice_id
        ))

        practice_session = c.fetchone()

        if not practice_session:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Practice session not found."
            }), 404

        # -------------------------------------------------
        # ALREADY COMPLETED
        # -------------------------------------------------

        if practice_session["status"] == "completed":

            conn.close()

            return jsonify({

                "success": True,

                "already_completed": True,

                "session_id":
                    session_id,

                "score":
                    practice_session["score"],

                "correct_answers":
                    practice_session[
                        "correct_answers"
                    ],

                "incorrect_answers":
                    practice_session[
                        "incorrect_answers"
                    ],

                "unanswered":
                    practice_session[
                        "unanswered"
                    ],

                "percentage":
                    practice_session[
                        "percentage"
                    ]

            })

        # -------------------------------------------------
        # GET QUESTION IDS
        # -------------------------------------------------

        try:

            question_ids = json.loads(
                practice_session[
                    "question_ids"
                ] or "[]"
            )

        except:

            question_ids = []

        if len(question_ids) != 50:

            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Invalid question list."
            }), 500

        # -------------------------------------------------
        # COMBINE SERVER SAVED ANSWERS
        # WITH SUBMITTED ANSWERS
        # -------------------------------------------------

        try:

            saved_answers = json.loads(
                practice_session[
                    "answers"
                ] or "{}"
            )

        except:

            saved_answers = {}

        final_answers = dict(
            saved_answers
        )

        for key, value in submitted_answers.items():

            try:

                answer_value = int(
                    value
                )

            except:

                continue

            if answer_value in [
                0,
                1,
                2,
                3
            ]:

                final_answers[
                    str(key)
                ] = answer_value

        # -------------------------------------------------
        # SCORE VARIABLES
        # -------------------------------------------------

        correct_answers = 0

        incorrect_answers = 0

        unanswered = 0

        score = 0

        review = []

        # -------------------------------------------------
        # EVALUATE 25 QUESTIONS
        # -------------------------------------------------

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
                    board,
                    class_name,
                    subject,
                    topic,
                    subtopic,
                    difficulty,
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_answer,
                    explanation,
                    hint,
                    marks
                FROM practice_questions
                WHERE id=?
                LIMIT 1
            """, (
                question_id,
            ))

            row = c.fetchone()

            if not row:

                continue

            # -------------------------------------------------
            # DATABASE CORRECT ANSWER
            # A/B/C/D
            # -------------------------------------------------

            correct_letter = (
                row["correct_answer"]
                or ""
            ).strip().upper()

            letter_to_index = {
                "A": 0,
                "B": 1,
                "C": 2,
                "D": 3
            }

            correct_index = (
                letter_to_index.get(
                    correct_letter
                )
            )

            # -------------------------------------------------
            # STUDENT ANSWER
            # -------------------------------------------------

            student_answer = final_answers.get(
                str(question_id)
            )

            # -------------------------------------------------
            # UNANSWERED
            # -------------------------------------------------

            if student_answer is None:

                unanswered += 1

                result_status = "unanswered"

            # -------------------------------------------------
            # CORRECT
            # -------------------------------------------------

            elif student_answer == correct_index:

                correct_answers += 1

                marks = row["marks"] or 2

                score += int(
                    marks
                )

                result_status = "correct"

            # -------------------------------------------------
            # INCORRECT
            # -------------------------------------------------

            else:

                incorrect_answers += 1

                result_status = "incorrect"

            # -------------------------------------------------
            # REVIEW DATA
            # -------------------------------------------------

            options = [

                row["option_a"],

                row["option_b"],

                row["option_c"],

                row["option_d"]

            ]

            review.append({

                "id":
                    row["id"],

                "question":
                    row["question"],

                "options":
                    options,

                "student_answer":
                    student_answer,

                "correct_answer":
                    correct_index,

                "correct_letter":
                    correct_letter,

                "result":
                    result_status,

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

                "marks":
                    row["marks"] or 2

            })

        # -------------------------------------------------
        # PERCENTAGE
        # -------------------------------------------------

        percentage = round(
            (score / 100) * 100,
            2
        )

        submitted_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # -------------------------------------------------
        # UPDATE SESSION
        # -------------------------------------------------

        c.execute("""
            UPDATE practice_sessions

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
            AND practice_id=?
        """, (

            json.dumps(
                final_answers
            ),

            submitted_at,

            score,

            correct_answers,

            incorrect_answers,

            unanswered,

            percentage,

            session_id,

            practice_id

        ))

        # -------------------------------------------------
        # SAVE ATTEMPT HISTORY
        # -------------------------------------------------

        question_data = json.dumps(
            review,
            ensure_ascii=False
        )

        c.execute("""
            INSERT INTO practice_attempts
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
                unanswered,
                score,
                percentage,
                question_data,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            practice_id,

            practice_session["board"],

            practice_session["class_name"],

            practice_session["subject"],

            practice_session["topic"],

            practice_session["subtopic"],

            practice_session["difficulty"],

            50,

            100,

            correct_answers,

            incorrect_answers,

            unanswered,

            score,

            percentage,

            question_data,

            submitted_at

        ))

        attempt_id = c.lastrowid

        # -------------------------------------------------
        # PERFORMANCE STATUS
        # -------------------------------------------------

        if percentage >= 80:

            performance_status = "Strong"

        elif percentage >= 50:

            performance_status = "Average"

        else:

            performance_status = "Weak"

        # -------------------------------------------------
        # CHECK PERFORMANCE ROW
        # -------------------------------------------------

        c.execute("""
            SELECT id
            FROM practice_performance
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

            practice_session["board"],

            practice_session["class_name"],

            practice_session["subject"],

            practice_session["topic"],

            practice_session["subtopic"],

            practice_session["difficulty"]

        ))

        performance_row = c.fetchone()

        # -------------------------------------------------
        # CREATE PERFORMANCE
        # -------------------------------------------------

        if not performance_row:

            c.execute("""
                INSERT INTO practice_performance
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
                    status,
                    last_attempt
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (

                practice_id,

                practice_session["board"],

                practice_session["class_name"],

                practice_session["subject"],

                practice_session["topic"],

                practice_session["subtopic"],

                practice_session["difficulty"],

                50,

                correct_answers,

                incorrect_answers,

                score,

                percentage,

                performance_status,

                submitted_at

            ))

        # -------------------------------------------------
        # UPDATE PERFORMANCE
        # -------------------------------------------------

        else:

            c.execute("""
                UPDATE practice_performance

                SET
                    total_questions =
                        total_questions + ?,

                    correct_answers =
                        correct_answers + ?,

                    incorrect_answers =
                        incorrect_answers + ?,

                    score =
                        score + ?,

                    percentage=?,

                    status=?,

                    last_attempt=?

                WHERE id=?
            """, (

                50,

                correct_answers,

                incorrect_answers,

                score,

                percentage,

                performance_status,

                submitted_at,

                performance_row["id"]

            ))

        # -------------------------------------------------
        # COMMIT
        # -------------------------------------------------

        conn.commit()

        conn.close()

        # -------------------------------------------------
        # RETURN RESULT + REVIEW
        # -------------------------------------------------

        return jsonify({

            "success": True,

            "already_completed":
                False,

            "attempt_id":
                attempt_id,

            "session_id":
                session_id,

            "total_questions":
                50,

            "total_marks":
                100,

            "correct_answers":
                correct_answers,

            "incorrect_answers":
                incorrect_answers,

            "unanswered":
                unanswered,

            "score":
                score,

            "percentage":
                percentage,

            "status":
                performance_status,

            "review":
                review

        })

    except Exception as e:

        if conn:
            try:
                conn.close()
            except:
                pass

        print(
            "PRACTICE SUBMIT ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
      
@app.route("/admin/students")
def admin_students():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    # ✅ FETCH FROM DB
    conn = sqlite3.connect("/var/data/students.db")
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

    
    # Count only successfully enrolled students
    c.execute("""
        SELECT course, COUNT(*)
        FROM students
        WHERE enrolled = 1
        GROUP BY course
    """)

    enrolled_counts = dict(c.fetchall())

    conn.close()

    # Return database-based seat information
    return jsonify({
        "students": students_list,
        "seats": {
            course: {
                "total": d["total"],
                "booked": enrolled_counts.get(course, 0),
                "available": max(
                    d["total"] - enrolled_counts.get(course, 0), 0
                )
            }
            for course, d in seat_data.items()
        }
    })



@app.route("/admin/classes", methods=["GET", "POST"])
def admin_classes():

    if not session.get("admin"):
        return redirect("/admin")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == "POST":

        class_name = request.form.get("class_name", "").strip()
        course = request.form.get("course", "").strip()
        subject = request.form.get("subject", "").strip()
        faculty_username = request.form.get("faculty_username", "").strip()
        schedule = request.form.get("schedule", "").strip()

        # Validate required fields
        if not all([class_name, course, subject, faculty_username]):
            conn.close()
            return "Please fill all required fields", 400

        # Faculty must exist and be active
        faculty = teachers.get(faculty_username)

        if not faculty or not faculty.get("active", False):
            conn.close()
            return "Selected faculty is not active", 400

        c.execute("""
            INSERT INTO class_batches
            (class_name, course, subject, faculty_username,
             schedule, active_status)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (
            class_name,
            course,
            subject,
            faculty_username,
            schedule
        ))

        conn.commit()
        conn.close()

        return redirect("/admin/classes")

    # Get all batches
    c.execute("""
        SELECT *
        FROM class_batches
        ORDER BY id DESC
    """)
    batches = c.fetchall()

    conn.close()

    # Only active faculty can be assigned to new batches
    active_faculty = {
        username: data
        for username, data in teachers.items()
        if data.get("active", False)
    }

    return render_template(
        "classes.html",
        batches=batches,
        active_faculty=active_faculty
    )


@app.route("/admin/classes/toggle/<int:class_id>", methods=["POST"])
def toggle_class_status(class_id):

    if not session.get("admin"):
        return redirect("/admin")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    c.execute("""
        UPDATE class_batches
        SET active_status =
            CASE
                WHEN active_status = 1 THEN 0
                ELSE 1
            END
        WHERE id = ?
    """, (class_id,))

    conn.commit()
    conn.close()

    return redirect("/admin/classes")

@app.route("/admin/students-view")
def students_view():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template("students.html")
    
@app.route("/admin/reset-demo", methods=["POST"])
def admin_reset_demo():
    phone = request.json.get("phone")
    course = request.json.get("course")
    
    conn = sqlite3.connect("/var/data/students.db")
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

    conn = sqlite3.connect("/var/data/students.db")
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

PDF_FOLDER = os.path.join("/var/data", "rsc_download")
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
        file = os.path.join("/var/data", "payments.csv")
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

@app.route("/practice")
def practice():
    return render_template("practice.html")

# =====================================================
# RSC MOCK TEST - AVAILABLE OPTIONS
# =====================================================
# =====================================================
# RSC MOCK TEST - FINAL FULL SYLLABUS TEST
# =====================================================

# =====================================================
# MOCK TEST - START
# =====================================================

@app.route("/api/mock/start", methods=["POST"])
def mock_start():

    data = request.get_json(silent=True) or {}

    practice_id = get_practice_id()

    # -------------------------------------------------
    # GET MOCK TEST DETAILS FROM FRONTEND
    # -------------------------------------------------
    
    mock_test_id = data.get("mock_test_id")
    
    board = str(
        data.get("board", "")
    ).strip()
    
    class_name = str(
        data.get("class_name", "")
    ).strip()
    
    subject = str(
        data.get("subject", "")
    ).strip()
    
    mock_type = str(
        data.get("mock_type", "chapter")
    ).strip()
    
    chapter_scope = str(
        data.get("chapter_scope", "")
    ).strip()
    
    
    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    
    # -------------------------------------------------
    # IF MOCK TEST ID IS NOT GIVEN,
    # FIND IT USING BOARD + CLASS + SUBJECT +
    # MOCK TYPE + CHAPTER SCOPE
    # -------------------------------------------------
    
    if not mock_test_id:
    
        if not board or not class_name or not subject:
    
            conn.close()
    
            return jsonify({
                "success": False,
                "error": "Board, Class and Subject are required."
            }), 400
    
    
        c.execute("""
            SELECT *
            FROM mock_tests
            WHERE board=?
              AND class_name=?
              AND subject=?
              AND mock_type=?
              AND chapter_scope=?
              AND active=1
            LIMIT 1
        """, (
            board,
            class_name,
            subject,
            mock_type,
            chapter_scope
        ))
    
        test = c.fetchone()
    
    
    else:
    
        # -------------------------------------------------
        # MOCK TEST ID WAS DIRECTLY PROVIDED
        # -------------------------------------------------
    
        c.execute("""
            SELECT *
            FROM mock_tests
            WHERE id=?
              AND active=1
            LIMIT 1
        """, (
            mock_test_id,
        ))
    
        test = c.fetchone()
    
    
    # -------------------------------------------------
    # TEST NOT FOUND
    # -------------------------------------------------
    
    if not test:
    
        conn.close()
    
        return jsonify({
            "success": False,
            "error": (
                "Mock test is not configured yet for "
                "this chapter."
            )
        }), 404
    
    
    # -------------------------------------------------
    # NOW USE THE REAL DATABASE TEST ID
    # -------------------------------------------------
    
    mock_test_id = test["id"]

    # -------------------------------------------------
    # CHECK PREVIOUS ATTEMPT
    # -------------------------------------------------

    c.execute("""
        SELECT *
        FROM mock_attempts
        WHERE practice_id=?
          AND mock_test_id=?
        LIMIT 1
    """, (
        practice_id,
        mock_test_id
    ))

    existing = c.fetchone()

    # -------------------------------------------------
    # IF ALREADY SUBMITTED
    # -------------------------------------------------
    
    if existing and existing["status"] == "submitted":
    
        conn.close()
    
        return jsonify({

            "success": False,
    
            "already_submitted": True,
    
            "attempt_id":
                existing["id"],
    
            "mock_test_id":
                existing["mock_test_id"],
    
            "error":
                "You have already completed this mock test."
    
        }), 400


    # -------------------------------------------------
    # IF ACTIVE ATTEMPT EXISTS
    # DO NOT RESTART THE TIMER
    # -------------------------------------------------
    
    if existing and existing["status"] == "started":

        try:

            started_dt = datetime.fromisoformat(
                existing["started_at"]
            )

            elapsed_seconds = (
                datetime.utcnow() - started_dt
            ).total_seconds()

            duration_seconds = (
                int(test["duration_minutes"] or 60)
                * 60
            )

            # -----------------------------------------
            # STILL ACTIVE
            # -----------------------------------------

            if elapsed_seconds < duration_seconds:

                conn.close()

                return jsonify({

                    "success": True,

                    "resumed": True,

                    "attempt_id":
                        existing["id"],

                    "mock_test_id":
                        existing["mock_test_id"],

                    "board":
                        existing["board"],

                    "class_name":
                        existing["class_name"],

                    "subject":
                        existing["subject"],

                    "test_name":
                        test["test_name"],

                    "mock_type":
                        test["mock_type"],

                    "chapter_scope":
                        test["chapter_scope"],

                    "total_questions":
                        existing["total_questions"],

                    "total_marks":
                        existing["total_marks"],

                    "duration_minutes":
                        test["duration_minutes"],

                    "started_at":
                        existing["started_at"],

                    "status":
                        "started"

                })

            # -----------------------------------------
            # TIME EXPIRED
            # -----------------------------------------

            else:

                c.execute("""
                    UPDATE mock_attempts
                    SET
                        status='expired'
                    WHERE id=?
                """, (
                    existing["id"],
                ))

                conn.commit()

                print(
                    "MOCK ATTEMPT EXPIRED:",
                    existing["id"]
                )

        except Exception as e:

            print(
                "MOCK ATTEMPT TIME CHECK ERROR:",
                e
            )

    # -------------------------------------------------
    # GET QUESTIONS
    # -------------------------------------------------

    c.execute("""
        SELECT id
        FROM mock_questions
        WHERE mock_test_id=?
          AND active=1
        ORDER BY RANDOM()
        LIMIT ?
    """, (
        mock_test_id,
        test["total_questions"]
    ))

    questions = c.fetchall()

    if len(questions) < int(test["total_questions"]):

        conn.close()

        return jsonify({
            "success": False,
            "error": (
                f"Only {len(questions)} active questions "
                f"are available. "
                f"{test['total_questions']} are required."
            )
        }), 400

    question_ids = [
        row["id"]
        for row in questions
    ]

    question_ids_json = json.dumps(question_ids)

    started_at = datetime.utcnow().isoformat()

    # -------------------------------------------------
    # CREATE / RESET ATTEMPT
    # -------------------------------------------------

    if existing:

        c.execute("""
            UPDATE mock_attempts
            SET
                question_ids=?,
                answers='{}',
                status='started',
                payment_status='paid',
                total_questions=?,
                total_marks=?,
                correct_answers=0,
                incorrect_answers=0,
                unanswered=0,
                score=0,
                percentage=0,
                rank=NULL,
                started_at=?,
                submitted_at=NULL
            WHERE id=?
        """, (
            question_ids_json,
            test["total_questions"],
            test["total_marks"],
            started_at,
            existing["id"]
        ))

        attempt_id = existing["id"]

    else:

        c.execute("""
            INSERT INTO mock_attempts (
                practice_id,
                mock_test_id,
                board,
                class_name,
                subject,
                question_ids,
                answers,
                status,
                payment_status,
                total_questions,
                total_marks,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '{}',
                    'started', 'paid', ?, ?, ?)
        """, (
            practice_id,
            mock_test_id,
            test["board"],
            test["class_name"],
            test["subject"],
            question_ids_json,
            test["total_questions"],
            test["total_marks"],
            started_at
        ))

        attempt_id = c.lastrowid

    conn.commit()
    conn.close()

    return jsonify({

        "success": True,

        "attempt_id": attempt_id,

        "mock_test_id": mock_test_id,

        "board": test["board"],

        "class_name": test["class_name"],

        "subject": test["subject"],

        "test_name": test["test_name"],

        "mock_type": test["mock_type"],

        "chapter_scope": test["chapter_scope"],

        "total_questions": test["total_questions"],

        "total_marks": test["total_marks"],

        "duration_minutes": test["duration_minutes"],

        "question_ids": question_ids

    })
# =====================================================
# MOCK TEST - GET QUESTIONS
# =====================================================

@app.route("/api/mock/questions")
def mock_get_questions():

    practice_id = get_practice_id()
    attempt_id = request.args.get("attempt_id", type=int)

    if not attempt_id:
        return jsonify({
            "success": False,
            "error": "Attempt ID is required."
        }), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT
        mock_attempts.*,
        mock_tests.duration_minutes
    FROM mock_attempts
    LEFT JOIN mock_tests
        ON mock_tests.id = mock_attempts.mock_test_id
    WHERE mock_attempts.id=?
      AND mock_attempts.practice_id=?
    LIMIT 1
""", (
    attempt_id,
    practice_id
))

    attempt = c.fetchone()

    if not attempt:
        conn.close()
        return jsonify({
            "success": False,
            "error": "Mock attempt not found."
        }), 404

    try:
        question_ids = json.loads(
            attempt["question_ids"] or "[]"
        )
    except Exception:
        conn.close()
        return jsonify({
            "success": False,
            "error": "Invalid question data."
        }), 500

    if not question_ids:
        conn.close()
        return jsonify({
            "success": False,
            "error": "No questions found."
        }), 400

    placeholders = ",".join(["?"] * len(question_ids))

    c.execute(
        f"""
        SELECT
            id,
            question,
            option_a,
            option_b,
            option_c,
            option_d,
            marks
        FROM mock_questions
        WHERE id IN ({placeholders})
          AND active=1
        """,
        question_ids
    )

    rows = c.fetchall()

    question_map = {}

    for row in rows:

        question_map[str(row["id"])] = {
            "id": row["id"],
            "question": row["question"],
            "option_a": row["option_a"],
            "option_b": row["option_b"],
            "option_c": row["option_c"],
            "option_d": row["option_d"],
            "marks": row["marks"] or 1
        }

    # Preserve the randomized order stored in the attempt
    questions = []

    for question_id in question_ids:

        question = question_map.get(str(question_id))

        if question:
            questions.append(question)

    conn.close()

    try:
        saved_answers = json.loads(
            attempt["answers"] or "{}"
        )
    except:
        saved_answers = {}

    return jsonify({
        "success": True,
    
        "attempt_id":
            attempt_id,
    
        "mock_test_id":
            attempt["mock_test_id"],
    
        "status":
            attempt["status"],
    
        "total_questions":
            attempt["total_questions"],
    
        "total_marks":
            attempt["total_marks"],
    
        "duration_minutes":
            attempt["duration_minutes"] or 60,

        "started_at":
            attempt["started_at"],

        "current_question":
            attempt["current_question"] or 0,
    
        "answers":
            saved_answers,
    
        "questions":
            questions
    })

@app.route("/api/mock/save-answer", methods=["POST"])
def mock_save_answer():

    data = request.get_json(silent=True) or {}

    practice_id = get_practice_id()

    attempt_id = data.get("attempt_id")
    question_id = data.get("question_id")
    answer = data.get("answer")
    current_question = data.get("current_question")

    if not attempt_id:
        return jsonify({
            "success": False,
            "error": "Attempt ID is required."
        }), 400

    if question_id is None:
        return jsonify({
            "success": False,
            "error": "Question ID is required."
        }), 400

    if answer is None:
        return jsonify({
            "success": False,
            "error": "Answer is required."
        }), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT id, answers, status
        FROM mock_attempts
        WHERE id=?
          AND practice_id=?
        LIMIT 1
    """, (
        attempt_id,
        practice_id
    ))

    attempt = c.fetchone()

    if not attempt:
        conn.close()

        return jsonify({
            "success": False,
            "error": "Mock attempt not found."
        }), 404

    if attempt["status"] != "started":
        conn.close()

        return jsonify({
            "success": False,
            "error": "This mock test is no longer active."
        }), 400

    try:

        answers = json.loads(
            attempt["answers"] or "{}"
        )

    except Exception:

        answers = {}

    answers[str(question_id)] = int(answer)

    # -------------------------------------------------
    # CURRENT QUESTION
    # -------------------------------------------------
    
    if current_question is None:
        current_question = 0
    
    try:
        current_question = int(current_question)
    except:
        current_question = 0
    
    if current_question < 0:
        current_question = 0
    
    
    # -------------------------------------------------
    # SAVE ANSWER + CURRENT QUESTION
    # -------------------------------------------------
    
    c.execute("""
        UPDATE mock_attempts
        SET
            answers=?,
            current_question=?
        WHERE id=?
    """, (
        json.dumps(answers),
        current_question,
        attempt_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "attempt_id": attempt_id,
        "answers": answers,
        "current_question": current_question
    })    
# =====================================================
# MOCK TEST - SAVE CURRENT QUESTION
# =====================================================

@app.route("/api/mock/save-progress", methods=["POST"])
def mock_save_progress():

    data = request.get_json(silent=True) or {}

    practice_id = get_practice_id()

    attempt_id = data.get("attempt_id")
    current_question = data.get("current_question")

    if not attempt_id:
        return jsonify({
            "success": False,
            "error": "Attempt ID is required."
        }), 400

    try:
        current_question = int(current_question)
    except:
        current_question = 0

    if current_question < 0:
        current_question = 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT id, status
        FROM mock_attempts
        WHERE id=?
          AND practice_id=?
        LIMIT 1
    """, (
        attempt_id,
        practice_id
    ))

    attempt = c.fetchone()

    if not attempt:
        conn.close()

        return jsonify({
            "success": False,
            "error": "Mock attempt not found."
        }), 404

    if attempt["status"] != "started":
        conn.close()

        return jsonify({
            "success": False,
            "error": "Mock test is no longer active."
        }), 400

    c.execute("""
        UPDATE mock_attempts
        SET current_question=?
        WHERE id=?
    """, (
        current_question,
        attempt_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "current_question": current_question
    })
    
# =====================================================
# MOCK TEST - SUBMIT
# =====================================================

@app.route("/api/mock/submit", methods=["POST"])
def mock_submit():

    data = request.get_json(silent=True) or {}

    practice_id = get_practice_id()
    attempt_id = data.get("attempt_id")

    # -------------------------------------------------
    # GET STUDENT DETAILS
    # -------------------------------------------------
    
    student_phone = session.get("phone", "")
    
    student_name = ""
    student_state = ""
    
    if student_phone:
    
        student_conn = sqlite3.connect(DB_PATH)
        student_conn.row_factory = sqlite3.Row
        student_cursor = student_conn.cursor()
    
        student_cursor.execute("""
            SELECT name, state
            FROM students
            WHERE phone=?
            ORDER BY rowid DESC
            LIMIT 1
        """, (
            student_phone,
        ))
    
        student = student_cursor.fetchone()
    
        if student:
    
            student_name = (
                student["name"] or ""
            )
    
            student_state = (
                student["state"] or ""
            )
    
        student_conn.close()
        

    answers = data.get("answers", {})

    if not attempt_id:
        return jsonify({
            "success": False,
            "error": "Attempt ID is required."
        }), 400

    if not isinstance(answers, dict):
        return jsonify({
            "success": False,
            "error": "Invalid answers format."
        }), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # -------------------------------------------------
    # GET ATTEMPT
    # -------------------------------------------------

    c.execute("""
        SELECT *
        FROM mock_attempts
        WHERE id=?
          AND practice_id=?
        LIMIT 1
    """, (
        attempt_id,
        practice_id
    ))

    attempt = c.fetchone()

    if not attempt:
        
            # Prefer the name/state entered before package payment.
            c.execute("""
                SELECT student_name, student_state
                FROM mock_purchases
                WHERE practice_id=?
                  AND board=?
                  AND class_name=?
                  AND payment_status='paid'
                ORDER BY purchased_at DESC, id DESC
                LIMIT 1
            """, (
                practice_id,
                attempt["board"],
                attempt["class_name"]
            ))
        
            package_student = c.fetchone()
        
            if package_student:
                if package_student["student_name"]:
                    student_name = package_student["student_name"]
        
                if package_student["student_state"]:
                    student_state = package_student["student_state"]
        
                conn.close()
        
                return jsonify({
                    "success": False,
                    "error": "Mock attempt not found."
                }), 404

    # -------------------------------------------------
    # PREVENT DOUBLE SUBMISSION
    # -------------------------------------------------

    if attempt["status"] == "submitted":

        conn.close()

        return jsonify({
            "success": False,
            "error": "This mock test has already been submitted."
        }), 400

    # -------------------------------------------------
    # GET QUESTION IDS
    # -------------------------------------------------

    try:
        question_ids = json.loads(
            attempt["question_ids"] or "[]"
        )
    except Exception:

        conn.close()

        return jsonify({
            "success": False,
            "error": "Invalid question data."
        }), 500

    if not question_ids:

        conn.close()

        return jsonify({
            "success": False,
            "error": "No questions found for this attempt."
        }), 400

    # -------------------------------------------------
    # LOAD CORRECT ANSWERS
    # -------------------------------------------------

    placeholders = ",".join(
        ["?"] * len(question_ids)
    )

    c.execute(
        f"""
        SELECT
            id,
            question,
            option_a,
            option_b,
            option_c,
            option_d,
            topic,
            subtopic,
            difficulty,
            correct_answer,
            explanation,
            hint,
            marks
        FROM mock_questions
        WHERE id IN ({placeholders})
        """,
        question_ids
    )

    question_rows = c.fetchall()

    correct_map = {}

    marks_map = {}

    for row in question_rows:

        correct_map[str(row["id"])] = (
            str(row["correct_answer"])
            .strip()
            .upper()
        )

        marks_map[str(row["id"])] = (
            int(row["marks"] or 1)
        )

    # -------------------------------------------------
    # CALCULATE RESULT
    # -------------------------------------------------

    correct_answers = 0
    incorrect_answers = 0
    unanswered = 0
    score = 0
    review = []

    # Create quick lookup by question ID
    row_map = {
        str(row["id"]): row
        for row in question_rows
    }

    for question_id in question_ids:

        qid = str(question_id)

        row = row_map.get(qid)

        user_answer = answers.get(qid, "")

        # -------------------------------------------------
        # NORMALIZE STUDENT ANSWER
        # -------------------------------------------------

        if user_answer is None or user_answer == "":
            user_answer = ""

        else:

            try:

                answer_index = int(user_answer)

                if 0 <= answer_index <= 3:
                    user_answer = "ABCD"[answer_index]
                else:
                    user_answer = ""

            except (ValueError, TypeError):

                user_answer = str(
                    user_answer
                ).strip().upper()

        # -------------------------------------------------
        # CORRECT ANSWER
        # -------------------------------------------------

        correct_answer = correct_map.get(
            qid,
            ""
        )

        marks = marks_map.get(
            qid,
            1
        )

        # -------------------------------------------------
        # SCORE
        # -------------------------------------------------

        if not user_answer:

            unanswered += 1
            result_status = "unanswered"

        elif user_answer == correct_answer:

            correct_answers += 1
            score += marks
            result_status = "correct"

        else:

            incorrect_answers += 1
            result_status = "incorrect"

        # -------------------------------------------------
        # REVIEW DATA
        # -------------------------------------------------

        correct_letter = (
            correct_answer
            .strip()
            .upper()
        )

        letter_to_index = {
            "A": 0,
            "B": 1,
            "C": 2,
            "D": 3
        }

        correct_index = letter_to_index.get(
            correct_letter
        )

        student_answer = None

        if user_answer:

            student_answer = letter_to_index.get(
                user_answer
            )

        if row:

            review.append({

                "id":
                    row["id"],

                "question":
                    row["question"],

                "options": [
                    row["option_a"],
                    row["option_b"],
                    row["option_c"],
                    row["option_d"]
                ],

                "student_answer":
                    student_answer,

                "correct_answer":
                    correct_index,

                "correct_letter":
                    correct_letter,

                "result":
                    result_status,

                "explanation":
                    row["explanation"] or "",

                "hint":
                    row["hint"] or "",

                "topic":
                    row["topic"] or "",

                "subtopic":
                    row["subtopic"] or "",

                "difficulty":
                    row["difficulty"] or "",

                "marks":
                    row["marks"] or 2

            })
    # -------------------------------------------------
    # PERCENTAGE
    # -------------------------------------------------

    total_marks = int(
        attempt["total_marks"] or 100
    )

    if total_marks > 0:

        percentage = round(
            (score / total_marks) * 100,
            2
        )

    else:

        percentage = 0

    submitted_at = datetime.utcnow().isoformat()

    answers_json = json.dumps(
        answers
    )

    # -------------------------------------------------
    # UPDATE ATTEMPT
    # -------------------------------------------------

    c.execute("""
        UPDATE mock_attempts
        SET
            answers=?,
            status='submitted',
            correct_answers=?,
            incorrect_answers=?,
            unanswered=?,
            score=?,
            percentage=?,
            submitted_at=?,
            review_data=?
        WHERE id=?
          AND practice_id=?
    """, (
        answers_json,
        correct_answers,
        incorrect_answers,
        unanswered,
        score,
        percentage,
        submitted_at,
        json.dumps(
            review,
            ensure_ascii=False
        ),
        attempt_id,
        practice_id
    ))

    # -------------------------------------------------
    # SAVE RESULT
    # -------------------------------------------------

    c.execute("""
        INSERT INTO mock_results (
            mock_test_id,
            practice_id,
            student_phone,
            student_name,
            student_state,
            score,
            percentage,
            correct_answers,
            incorrect_answers,
            unanswered,
            submitted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mock_test_id, practice_id)
        DO UPDATE SET
            student_phone=excluded.student_phone,
            student_name=excluded.student_name,
            student_state=excluded.student_state,
            score=excluded.score,
            percentage=excluded.percentage,
            correct_answers=excluded.correct_answers,
            incorrect_answers=excluded.incorrect_answers,
            unanswered=excluded.unanswered,
            submitted_at=excluded.submitted_at
    """, (
            attempt["mock_test_id"],
            practice_id,
            student_phone,
            student_name,
            student_state,
            score,
            percentage,
            correct_answers,
            incorrect_answers,
            unanswered,
            submitted_at
    )   )

    conn.commit()
    conn.close()

    # -------------------------------------------------
    # RESPONSE
    # -------------------------------------------------

    return jsonify({

        "success": True,

        "attempt_id": attempt_id,

        "mock_test_id": attempt["mock_test_id"],

        "total_questions": attempt["total_questions"],

        "total_marks": total_marks,

        "correct_answers": correct_answers,

        "incorrect_answers": incorrect_answers,

        "unanswered": unanswered,

        "score": score,

        "percentage": percentage,

        "submitted_at": submitted_at,
        "review": review

    })
# =====================================================
# MOCK TEST - RESULT ANALYSIS
# =====================================================

@app.route("/api/mock/result-analysis")
def mock_result_analysis():

    practice_id = get_practice_id()

    attempt_id = request.args.get(
        "attempt_id",
        type=int
    )

    if not attempt_id:

        return jsonify({
            "success": False,
            "error": "Attempt ID is required."
        }), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT *
        FROM mock_attempts
        WHERE id=?
          AND practice_id=?
        LIMIT 1
    """, (
        attempt_id,
        practice_id
    ))

    attempt = c.fetchone()

    if not attempt:

        conn.close()

        return jsonify({
            "success": False,
            "error": "Mock attempt not found."
        }), 404

    if attempt["status"] != "submitted":

        conn.close()

        return jsonify({
            "success": False,
            "error":
                "Mock test has not been submitted yet."
        }), 400

    try:

        review = json.loads(
            attempt["review_data"] or "[]"
        )

    except:

        review = []

    c.execute("""
        SELECT
            test_name,
            mock_type,
            chapter_scope
        FROM mock_tests
        WHERE id=?
        LIMIT 1
    """, (
        attempt["mock_test_id"],
    ))

    test = c.fetchone()

    conn.close()

    return jsonify({

        "success": True,

        "attempt_id":
            attempt["id"],

        "mock_test_id":
            attempt["mock_test_id"],

        "test_name":
            test["test_name"]
            if test else "Mock Test",

        "total_questions":
            attempt["total_questions"],

        "total_marks":
            attempt["total_marks"],

        "correct_answers":
            attempt["correct_answers"],

        "incorrect_answers":
            attempt["incorrect_answers"],

        "unanswered":
            attempt["unanswered"],

        "score":
            attempt["score"],

        "percentage":
            attempt["percentage"],

        "submitted_at":
            attempt["submitted_at"],

        "review":
            review

    })
# =====================================================
# MOCK TEST - TOP 10 LEADERBOARD
# =====================================================

@app.route("/api/mock/final-test")
def mock_final_test():

    board = request.args.get("board", "").strip()
    class_name = request.args.get("class_name", "").strip()
    subject = request.args.get(
        "subject",
        MOCK_TEST_SUBJECT
    ).strip()

    if not board or not class_name or not subject:
        return jsonify({
            "success": False,
            "error": "Board, Class and Subject are required."
        }), 400

    try:

        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                id,
                mock_test_no,
                board,
                class_name,
                subject,
                test_name,
                syllabus_scope,
                total_questions,
                total_marks,
                duration_minutes,
                attempt_limit,
                active
            FROM mock_tests
            WHERE board=?
              AND class_name=?
              AND subject=?
              AND active=1
              AND (
                    LOWER(test_name) LIKE '%final%'
                    OR LOWER(test_name) LIKE '%full%'
                    OR LOWER(syllabus_scope) LIKE '%full%'
                    OR LOWER(syllabus_scope) LIKE '%syllabus%'
                  )
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
                "found": False,
                "error": "Final Full-Syllabus Mock Test not configured yet."
            }), 404

        return jsonify({
            "success": True,
            "found": True,
            "test": {
                "id": row["id"],
                "mock_test_no": row["mock_test_no"],
                "board": row["board"],
                "class_name": row["class_name"],
                "subject": row["subject"],
                "test_name": row["test_name"],
                "syllabus_scope": row["syllabus_scope"],
                "total_questions": row["total_questions"],
                "total_marks": row["total_marks"],
                "duration_minutes": row["duration_minutes"],
                "attempt_limit": row["attempt_limit"]
            }
        })

    except Exception as e:

        print("FINAL MOCK TEST ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/mock/options")
def mock_options():

    try:

        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT DISTINCT
                board,
                class_name,
                subject
            FROM mock_tests
            WHERE active=1
            ORDER BY board, class_name, subject
        """)

        options = [
            {
                "board": row["board"],
                "class_name": row["class_name"],
                "subject": row["subject"]
            }
            for row in c.fetchall()
        ]

        conn.close()

        return jsonify({
            "success": True,
            "options": options
        })

    except Exception as e:

        print(
            "MOCK OPTIONS ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# MOCK TEST - STUDENT ATTEMPT STATUS
# =====================================================

@app.route("/api/mock/status")
def mock_status():

    practice_id = get_practice_id()

    board = request.args.get(
        "board",
        ""
    ).strip()

    class_name = request.args.get(
        "class_name",
        ""
    ).strip()

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    if not board or not class_name or not subject:

        return jsonify({
            "success": False,
            "error":
                "Board, Class and Subject are required."
        }), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            mt.id,
            mt.mock_type,
            mt.chapter_scope,
            mt.test_name,
            mt.duration_minutes,

            ma.id AS attempt_id,
            ma.status AS attempt_status

        FROM mock_tests mt

        LEFT JOIN mock_attempts ma
            ON ma.mock_test_id = mt.id
           AND ma.practice_id = ?

        WHERE mt.board=?
          AND mt.class_name=?
          AND mt.subject=?
          AND mt.active=1

        ORDER BY mt.id
    """, (
        practice_id,
        board,
        class_name,
        subject
    ))

    rows = c.fetchall()

    conn.close()

    tests = []

    for row in rows:

        tests.append({

            "mock_test_id":
                row["id"],

            "mock_type":
                row["mock_type"],

            "chapter_scope":
                row["chapter_scope"],

            "test_name":
                row["test_name"],

            "duration_minutes":
                row["duration_minutes"],

            "attempt_id":
                row["attempt_id"],

            "status":
                row["attempt_status"]
                or "not_started"

        })

    return jsonify({

        "success": True,

        "tests":
            tests

    })
# =====================================================
# RSC MOCK TEST - TOP 10 LEADERBOARD
# =====================================================

@app.route("/api/mock/leaderboard")
def mock_leaderboard():

    mock_test_id = request.args.get(
        "mock_test_id",
        ""
    ).strip()

    if not mock_test_id:

        return jsonify({
            "success": False,
            "error": "Mock Test ID is required."
        }), 400

    try:

        mock_test_id = int(mock_test_id)

    except ValueError:

        return jsonify({
            "success": False,
            "error": "Invalid Mock Test ID."
        }), 400


    conn = None

    try:

        conn = sqlite3.connect(
            "/var/data/students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()


        # =================================================
        # GET MOCK TEST INFORMATION
        # =================================================

        c.execute("""
            SELECT
                id,
                mock_type,
                chapter_scope,
                test_name,
                board,
                class_name,
                subject
            FROM mock_tests
            WHERE id=?
            LIMIT 1
        """, (
            mock_test_id,
        ))

        test_row = c.fetchone()


        if not test_row:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Mock Test not found."
            }), 404


        # =================================================
        # GET TOP 10 RESULTS
        #
        # Higher score = higher rank
        #
        # Same score:
        # Less time taken = higher rank
        # =================================================

        c.execute("""
            SELECT

                mr.id,

                mr.mock_test_id,

                mr.practice_id,

                mr.score,

                mr.percentage,

                mr.correct_answers,

                mr.incorrect_answers,

                mr.unanswered,

                mr.submitted_at,

                ma.started_at,

                ma.submitted_at AS attempt_submitted_at,

                mr.student_name,

                mr.student_state

            FROM mock_results mr

            LEFT JOIN mock_attempts ma
                ON ma.practice_id = mr.practice_id
               AND ma.mock_test_id = mr.mock_test_id

            LEFT JOIN students s
                ON s.phone = ma.practice_id

            WHERE mr.mock_test_id=?

            ORDER BY

                mr.score DESC,

                CASE

                    WHEN ma.started_at IS NOT NULL
                     AND ma.submitted_at IS NOT NULL

                    THEN (
                        strftime(
                            '%s',
                            ma.submitted_at
                        )
                        -
                        strftime(
                            '%s',
                            ma.started_at
                        )
                    )

                    ELSE 999999999

                END ASC,

                mr.submitted_at ASC

            LIMIT 10

        """, (
            mock_test_id,
        ))


        rows = c.fetchall()


        leaderboard = []


        for index, row in enumerate(
            rows,
            start=1
        ):

            leaderboard.append({

                "rank":
                    index,

                "name":
                    row["student_name"]
                    or "Student",

                "state":
                    row["student_state"]
                    or "",

                "score":
                    row["score"] or 0,

                "percentage":
                    row["percentage"] or 0,

                "correct_answers":
                    row["correct_answers"] or 0,

                "incorrect_answers":
                    row["incorrect_answers"] or 0,

                "unanswered":
                    row["unanswered"] or 0,

                "submitted_at":
                    row["submitted_at"],

                "started_at":
                    row["started_at"]

            })


        conn.close()


        # =================================================
        # RESPONSE
        # =================================================

        return jsonify({

            "success": True,

            "mock_test": {

                "id":
                    test_row["id"],

                "mock_type":
                    test_row["mock_type"]
                    or "chapter",

                "chapter_scope":
                    test_row["chapter_scope"]
                    or "",

                "test_name":
                    test_row["test_name"],

                "board":
                    test_row["board"],

                "class_name":
                    test_row["class_name"],

                "subject":
                    test_row["subject"]

            },

            "leaderboard":
                leaderboard

        })


    except Exception as e:

        if conn:

            try:
                conn.close()
            except:
                pass


        print(
            "MOCK LEADERBOARD ERROR:",
            e
        )


        return jsonify({

            "success": False,

            "error":
                str(e)

        }), 500
        
@app.route("/api/practice/options")
def practice_options():
    try:
        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT DISTINCT board, class_name, subject
            FROM practice_questions
            WHERE active=1
            ORDER BY board, class_name, subject
        """)

        options = [
            {
                "board": row["board"],
                "class_name": row["class_name"],
                "subject": row["subject"]
            }
            for row in c.fetchall()
        ]

        conn.close()

        return jsonify({
            "success": True,
            "options": options
        })

    except Exception as e:
        print("PRACTICE OPTIONS ERROR:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/practice/topics", methods=["POST"])
def practice_topics():

    try:

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


        if not board or not class_name or not subject:

            return jsonify({
                "success": False,
                "error":
                    "Board, Class and Subject are required."
            }), 400


        conn = sqlite3.connect(
            "/var/data/students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()


        # =================================================
        # FIRST SOURCE:
        # OFFICIAL / ADMIN SYLLABUS TOPIC CACHE
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

        row = c.fetchone()


        if row:

            try:

                topic_data = json.loads(
                    row["topics_json"]
                )

                raw_topics = topic_data.get(
                    "topics",
                    []
                )

                topics = []


                for item in raw_topics:

                    if not isinstance(item, dict):
                        continue


                    topic = str(
                        item.get(
                            "topic",
                            ""
                        )
                    ).strip()


                    if not topic:
                        continue


                    raw_subtopics = item.get(
                        "subtopics",
                        []
                    )


                    if not isinstance(
                        raw_subtopics,
                        list
                    ):
                        raw_subtopics = []


                    subtopics = []


                    for subtopic in raw_subtopics:

                        subtopic = str(
                            subtopic
                        ).strip()


                        if (
                            subtopic
                            and subtopic
                            not in subtopics
                        ):

                            subtopics.append(
                                subtopic
                            )


                    topics.append({

                        "topic":
                            topic,

                        "subtopics":
                            subtopics

                    })


                if topics:

                    conn.close()

                    return jsonify({

                        "success":
                            True,

                        "source":
                            "syllabus",

                        "board":
                            board,

                        "class_name":
                            class_name,

                        "subject":
                            subject,

                        "topics":
                            topics

                    })


            except Exception as e:

                print(
                    "SYLLABUS TOPIC CACHE ERROR:",
                    e
                )


        # =================================================
        # FALLBACK:
        # EXISTING PRACTICE QUESTIONS
        # =================================================

        c.execute("""
            SELECT DISTINCT
                topic,
                subtopic

            FROM practice_questions

            WHERE board=?
              AND class_name=?
              AND subject=?
              AND active=1

            ORDER BY
                topic,
                subtopic

        """, (
            board,
            class_name,
            subject
        ))


        grouped = {}


        for row in c.fetchall():

            topic = str(
                row["topic"] or ""
            ).strip()

            subtopic = str(
                row["subtopic"] or ""
            ).strip()


            if not topic:
                continue


            if topic not in grouped:

                grouped[topic] = []


            if (
                subtopic
                and subtopic
                not in grouped[topic]
            ):

                grouped[topic].append(
                    subtopic
                )


        conn.close()


        topics = [

            {
                "topic": topic,
                "subtopics": subtopics
            }

            for topic, subtopics
            in grouped.items()

        ]


        return jsonify({

            "success":
                True,

            "source":
                "practice_questions",

            "board":
                board,

            "class_name":
                class_name,

            "subject":
                subject,

            "topics":
                topics

        })


    except Exception as e:

        print(
            "PRACTICE TOPICS ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 5000



@app.route("/admin/practice-syllabus", methods=["GET"])
def admin_practice_syllabus():

    if not session.get("admin"):
        return jsonify({
            "success": False,
            "error": "Unauthorized"
        }), 403

    try:

        board = request.args.get("board", "").strip()
        class_name = request.args.get("class_name", "").strip()
        subject = request.args.get("subject", "").strip()

        if not board or not class_name or not subject:
            return jsonify({
                "success": False,
                "error": "Board, Class and Subject are required."
            }), 400

        conn = sqlite3.connect("/var/data/students.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                id,
                topic,
                subtopic,
                display_order,
                active
            FROM practice_syllabus
            WHERE board=?
              AND class_name=?
              AND subject=?
            ORDER BY display_order, id
        """, (
            board,
            class_name,
            subject
        ))

        rows = c.fetchall()

        topics = {}

        for row in rows:

            topic = row["topic"]

            if topic not in topics:
                topics[topic] = []

            topics[topic].append({
                "id": row["id"],
                "subtopic": row["subtopic"],
                "display_order": row["display_order"],
                "active": bool(row["active"])
            })

        conn.close()

        result = []

        for topic, subtopics in topics.items():

            result.append({
                "topic": topic,
                "subtopics": subtopics
            })

        return jsonify({
            "success": True,
            "topics": result
        })

    except Exception as e:

        print(
            "ADMIN PRACTICE SYLLABUS ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
# =====================================================
# RSC MOCK TEST - LOAD COMPLETE SYLLABUS CHAPTERS
# =====================================================

@app.route("/api/mock/topics", methods=["POST"])
def mock_topics():

    try:

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


        if not board or not class_name or not subject:

            return jsonify({
                "success": False,
                "error":
                    "Board, Class and Subject are required."
            }), 400


        conn = sqlite3.connect(
            "/var/data/students.db"
        )

        conn.row_factory = sqlite3.Row

        c = conn.cursor()


        # =================================================
        # SAME SYLLABUS USED BY PRACTICE
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


        row = c.fetchone()


        if not row:

            # Fallback to Practice topics
            c.execute("""
                SELECT DISTINCT
                    topic,
                    subtopic

                FROM practice_questions

                WHERE board=?
                  AND class_name=?
                  AND subject=?
                  AND active=1

                ORDER BY
                    topic,
                    subtopic

            """, (
                board,
                class_name,
                subject
            ))


            grouped = {}


            for item in c.fetchall():

                topic = str(
                    item["topic"] or ""
                ).strip()


                if not topic:
                    continue


                if topic not in grouped:

                    grouped[topic] = []


            conn.close()


            return jsonify({

                "success": True,

                "source":
                    "practice_questions",

                "topics": [
                    {
                        "topic": topic
                    }

                    for topic
                    in grouped.keys()
                ]

            })


        try:

            topic_data = json.loads(
                row["topics_json"]
            )

            raw_topics = topic_data.get(
                "topics",
                []
            )


            topics = []


            for item in raw_topics:

                if isinstance(item, dict):

                    topic = str(
                        item.get(
                            "topic",
                            ""
                        )
                    ).strip()

                elif isinstance(item, str):

                    topic = item.strip()

                else:

                    continue


                if not topic:
                    continue


                # Avoid duplicate chapters

                exists = any(
                    str(x["topic"]).lower()
                    == topic.lower()
                    for x in topics
                )


                if exists:
                    continue


                topics.append({

                    "topic":
                        topic

                })


            conn.close()


            return jsonify({

                "success":
                    True,

                "source":
                    "syllabus",

                "board":
                    board,

                "class_name":
                    class_name,

                "subject":
                    subject,

                "topics":
                    topics

            })


        except Exception as e:

            conn.close()

            print(
                "MOCK SYLLABUS JSON ERROR:",
                e
            )

            return jsonify({

                "success":
                    False,

                "error":
                    "Unable to read syllabus topics."

            }), 500


    except Exception as e:

        print(
            "MOCK TOPICS ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "error":
                str(e)

        }), 500
        
        
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

     
     
if __name__ == "__main__":
    _load_feedback()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
