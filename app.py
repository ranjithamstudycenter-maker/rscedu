from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for,abort,jsonify,send_file
import os
import razorpay
import json
import smtplib
import time
import sqlite3
import csv
from datetime import datetime
from email.message import EmailMessage
from datetime import datetime, timedelta


# -------------------- APP INIT --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# TEMP USER STORAGE
users = {
    "test@gmail.com": {
        "name": "Student1",
        "hours_used": 0,
        "max_hours": 12,
        "demo_done": False,
        "demo_waiting": False
    }
}

teachers = {
    "Balakumar": {
        "password": "M10@2026",
        "course": "class10",
        "link": "https://meet.google.com/xxx-10",
        "active": True
    },
    "faculty2": {
        "password": "456",
        "course": "class12",
        "link": "https://meet.google.com/xxx-12",
        "active": True
    }
}
class_status = {
    "class10": False,
    "class12": False
}
@app.route("/reset-demo")
def reset_demo():

    if not session.get("admin"):
        return "Unauthorized ❌"

    email = request.args.get("email")

    if email in users:
        users[email]["demo_done"] = False
        users[email]["demo_waiting"] = False

    return "Demo reset done ✅"
# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        batch = request.form["batch"]

        users[email] = {
            "name": name,
            "password": password,
            "batch": batch,
            "demo_attended": False,
            "demo_waiting": False,
            "enrolled": False
        }

        session["user"] = email
        return redirect("/enroll")

    return """
    <html><head><title>Register</title>
    <style>
    body{font-family:Poppins;background:linear-gradient(135deg,#004aad,#0b5394);
    display:flex;justify-content:center;align-items:center;height:100vh;}
    .box{background:white;padding:40px;border-radius:15px;width:300px;text-align:center;}
    input,select{width:100%;padding:10px;margin:10px 0;border-radius:8px;border:1px solid #ccc;}
    button{width:100%;padding:10px;background:#28a745;color:white;border:none;border-radius:8px;}
    </style></head>
    <body>
    <div class="box">
    <h2>Register</h2>
    <form method="post">
    <input name="name" placeholder="Name" required>
    <input name="email" placeholder="Email" required>
    <input name="password" type="password" placeholder="Password" required>
    <select name="batch">
        <option value="indian">Indian</option>
        <option value="international">International</option>
    </select>
    <button>Register</button>
    </form>
    </div>
    </body></html>
    """


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = users.get(email)

        if user and user["password"] == password:
            session["user"] = email
            return redirect("/class")

        return "<h3 style='text-align:center;color:red;'>Invalid Login ❌</h3>"

    return """
    <html><head><title>Login</title>
    <style>
    body{font-family:Poppins;background:linear-gradient(135deg,#004aad,#0b5394);
    display:flex;justify-content:center;align-items:center;height:100vh;}
    .box{background:white;padding:40px;border-radius:15px;width:300px;text-align:center;}
    input{width:100%;padding:10px;margin:10px 0;border-radius:8px;border:1px solid #ccc;}
    button{width:100%;padding:10px;background:#0b5394;color:white;border:none;border-radius:8px;}
    a{color:#0b5394;}
    </style></head>
    <body>
    <div class="box">
    <h2>Login</h2>
    <form method="post">
    <input name="email" placeholder="Email" required>
    <input name="password" type="password" required>
    <button>Login</button>
    </form>
    <p><a href="/register">New user? Register</a></p>
    </div>
    </body></html>
    """


# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ================= DEMO CLASS =================
@app.route("/demo-class")
def demo_class():

    if not session.get("user"):
        return redirect("/login")

    email = session.get("user")
    user = users.get(email)

    if not user:
        return redirect("/login")

    # ✅ Already attended check
    if user.get("demo_done"):
        return "<h3 style='text-align:center;'>Demo already completed ✅<br>Enroll now</h3>"

    # ✅ Put user in waiting
    user["demo_waiting"] = True

    indian = []
    international = []

    for u in users.values():
        if u.get("demo_waiting"):
            if u.get("batch") == "indian":
                indian.append(u.get("name", "Student"))
            else:
                international.append(u.get("name", "Student"))

    return f"""
    <html><head><title>Demo Waiting</title>
    <style>
    body{{font-family:Poppins;background:#f5f7fa;text-align:center;padding:40px;}}
    .box{{background:white;padding:20px;margin:20px auto;width:300px;border-radius:12px;}}
    </style></head>

    <body>

    <h2>🔴 Demo Waiting Room</h2>

    <div class="box">
    <h3>🇮🇳 Indian ({len(indian)})</h3>
    {"<br>".join(indian) if indian else "No students yet"}
    </div>

    <div class="box">
    <h3>🌍 International ({len(international)})</h3>
    {"<br>".join(international) if international else "No students yet"}
    </div>

    <br><br>

    <a href="/live-room" style="padding:10px 20px;background:red;color:white;border-radius:8px;">
    Start Demo
    </a>

    </body></html>
    """

@app.route("/api/check-demo")
def check_demo():
    email = session.get("user")

    # முதலில் login check
    if not email or email not in users:
        return jsonify({"error": "Unauthorized"}), 401

    # பிறகு demo check
    user = users[email]  # ← இதுவும் missing ஆக இருந்தது!
    if not user.get("demo_done"):
        return "Please attend demo first ❌"

    return jsonify({
        "demo_done": users[email].get("demo_done", False)
    })

# ✅ MARK DEMO COMPLETE
@app.route("/api/demo-complete", methods=["POST"])
def demo_complete():

    email = session.get("user")

    if not email or email not in users:
        return jsonify({"error": "Unauthorized"}), 401

    users[email]["demo_done"] = True
    users[email]["demo_waiting"] = False

    return jsonify({"status": "saved"})


from datetime import datetime

last_reset_day = None

def reset_all_students():
    global last_reset_day
    
    today = datetime.now().day

    if last_reset_day == today:
        return   # avoid multiple runs

    print("Monthly reset done")

    # 👉 add your actual reset logic here
    # example:
    # students.clear()

    last_reset_day = today


# ================= ENROLL =================
from flask import request, jsonify, session, redirect

students = []

@app.route("/enroll", methods=["GET", "POST"])
def enroll():

    if not session.get("user"):
        return redirect("/login")

    user = users.get(session.get("user"))

    if not user:
        return redirect("/login")
    if request.method == "POST":

        student = {
            "name": request.form.get("name"),
            "class": request.form.get("class"),
            "country": request.form.get("country"),
            "timezone": request.form.get("timezone"),
            "time": request.form.get("time")
        }

        students.append(student)

        user["enrolled"] = True
        user["demo_attended"] = True
        user["demo_waiting"] = False

        return "<h3 style='text-align:center;'>🎉 Registered Successfully</h3>"

    return render_template("enroll.html")
    
# ================= LIVE ROOM (PAID STUDENTS) =================

@app.route("/live-room")
def live_room():

    if not session.get("user"):
        return redirect("/login")

    email = session.get("user")
    user = users.get(email)

    if not user:
        return redirect("/login")

    # ✅ ENROLL CHECK
    if not user.get("enrolled"):
        return "<h3 style='text-align:center;'>Please enroll first</h3>"

    # ✅ HOURS CHECK
    if user.get("hours_used", 0) >= user.get("max_hours", 12):
        return "<h3 style='text-align:center;'>Your class hours completed ❌</h3>"

    # ✅ INCREMENT HOURS (only once per session)
    if not session.get("joined"):
        user["hours_used"] = user.get("hours_used", 0) + 1
        session["joined"] = True

    course = request.args.get("course")

    print(course)  # test

    return render_template(
    "live_room.html",course=course,
    meet_link="https://meet.google.com/your-link",
    indian=indian,
    international=international
)

    

@app.route("/teacher-login", methods=["GET","POST"])
def teacher_login():

    error = ""
    selected_class = request.args.get("class")

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if username in teachers and teachers[username]["password"] == password:

            # ✅ CLASS CHECK
            if selected_class and teachers[username]["course"] != selected_class:
                return "Wrong class login ❌"

            if not teachers[username].get("active", True):
                error = "Your account is disabled ❌"
            else:
                session["teacher"] = username
                return redirect("/teacher-Dashboard")

        else:
            error = "Invalid Username or Password ❌"

    return render_template("teacher_login.html", error=error, class_name=selected_class)
    

@app.route("/teacher-Dashboard")
def teacher_dashboard():

    if "teacher" not in session:
        return redirect("/teacher-login")

    username = session["teacher"]
    teacher = teachers[username]

    feedbacks = feedback_db.get(username, [])

    if feedbacks:
        avg_rating = round(sum(f["rating"] for f in feedbacks)/len(feedbacks),2)
    else:
        avg_rating = 0

    # ⭐ ratings list for graph
    ratings = [f["rating"] for f in feedbacks]

    return render_template("teacher_Dashboard.html",
                           teacher_name=username,
                           course=teacher["course"],
                           meet_link=teacher["link"],
                           feedbacks=feedbacks,
                           avg_rating=avg_rating)


@app.route('/submit-teacher-feedback', methods=['POST'])
def submit_teacher_feedback():

    teacher = request.form["teacher"]
    rating = int(request.form["rating"])
    comment = request.form["comment"]

    if teacher not in feedback_db:
        feedback_db[teacher] = []

    feedback_db[teacher].append({
        "rating": rating,
        "comment": comment
    })

    return "Feedback submitted" 


# -------------------- FOLDERS --------------------
PDF_FOLDER = "rsc_download"
os.makedirs(PDF_FOLDER, exist_ok=True)

# -------------------- PRODUCTS --------------------
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


# -------------------- EMAIL CONFIG --------------------
EMAIL_ID = "ranjithamstudycenter@gmail.com"
EMAIL_PASS = "YOUR_APP_PASSWORD"

download_tokens = {}

def send_email(to_email, link):
    msg = EmailMessage()
    msg["Subject"] = "Your Maths PDF – Ranjitham Study Center"
    msg["From"] = EMAIL_ID
    msg["To"] = to_email

    msg.set_content(f"""
Hello,

Thank you for your payment.

Download your Maths PDF (valid for 1 hour):
{link}

Regards,
Ranjitham Study Center
""")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ID, EMAIL_PASS)
        server.send_message(msg)

def whatsapp_link(phone, link):
    msg = f"Payment successful! Download your Maths PDF (valid 1 hour): {link}"
    return f"https://wa.me/91{phone}?text={msg.replace(' ', '%20')}"

# -------------------- RAZORPAY --------------------

with open("admin.json") as f:
    keys = json.load(f)

razorpay_client = razorpay.Client(auth=(
    keys["razorpay_key"],
    keys["razorpay_secret"]
))
# -------------------- ROUTES --------------------

@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    response.cache_control.no_cache = True
    response.cache_control.must_revalidate = True
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/check_file')
def check_file():
    with open('feedback.json', 'r') as f:
        return f.read()


@app.route("/")
def home():
    return render_template("home.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/class")
def courses():

    email = session.get("user")

    if not email or email not in users:
        return redirect("/login")

    user = users[email]

    return render_template(
        "class.html",class_status=class_status,
        demo_completed=user.get("demo_completed", False),
        registered=user.get("enrolled", False),
        joined=session.get("joined", False)
    )
   
def is_valid(expiry): 
  if not expiry: 
      return False 
  return datetime.fromisoformat(expiry) > datetime.now()


@app.route("/materials")
def materials():
    
    board = request.args.get("board")
    cls = request.args.get("cls")
    open_id = request.args.get("open") or request.args.get("product_id")

    access = {}

    # 🔹 BUILD ACCESS + HANDLE EXPIRY
    for pid in PRODUCTS:

        view_key = "view_" + pid
        download_key = "download_" + pid

        view_data = session.get(view_key)
        download_data = session.get(download_key)

        def is_valid(data):
            if not data:
                return False
            expiry = data.get("expiry")
            if not expiry:
                return False
            return datetime.fromisoformat(expiry) > datetime.now()

        # ✅ valid check
        access[pid] = {
            "view": is_valid(view_data),
            "download": is_valid(download_data)
        }

        # ❌ remove expired
        if view_data and not is_valid(view_data):
            session.pop(view_key, None)

        if download_data and not is_valid(download_data):
            session.pop(download_key, None)

    # 🔥 EXPIRY TIME FOR FRONTEND
    expiry_time = None
    if open_id:
        data = session.get("view_" + open_id)
        if data:
            expiry_time = data.get("expiry")

    # 🔐 SECURITY CHECK
    if open_id:
        product = PRODUCTS.get(open_id)

        if not product:
            abort(403)

        if cls and str(product["class"]) != str(cls):
            abort(403)

        if not access.get(open_id, {}).get("view"):
            abort(403)

    # ✅ SAVE ACCESS
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
        return "Invalid"

    file_path = os.path.join(PDF_FOLDER, product["file"])

    return send_file(
        file_path,
        mimetype="application/pdf",
        as_attachment=False
    )

def check_access(key):

    data = session.get(key)

    # Nothing stored
    if not isinstance(data, dict):
        return False

    # Missing expiry
    if "expiry" not in data:
        return False

    try:
        expiry = datetime.fromisoformat(data["expiry"])
    except:
        return False

    # Expired
    if datetime.now() > expiry:
        session.pop(key, None)
        return False

    return True

@app.route("/download/<product_id>")
def download(product_id):

    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product"

    # Permission check
    if not check_access("download_" + product_id):
        return "⛔ Download access expired"

    return send_from_directory(
        PDF_FOLDER,
        product["file"],
        as_attachment=True
    )

@app.route("/pay")
def pay():

    product_id = request.args.get("product")
    mode = request.args.get("mode")
    board = request.args.get("board") or "cbse"
    cls = request.args.get("cls") or "12"

    session["board"] = board
    session["cls"]   = cls
   
  
    session["last_board"] = board
    session["last_cls"] = cls
    session["last_product"] = product_id
    session["last_mode"] = mode

    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product"

    order = razorpay_client.order.create({
        "amount": int(product["price"] * 100),
        "currency": "INR",
        "payment_capture": 1
    })

    return render_template(
        "pay.html",
        product=product,
        order_id=order["id"],
        razorpay_key=keys["razorpay_key"],
        board=board,
        cls=cls,
        product_id=product_id,
        mode=mode
        
    )

@app.route("/payment_success")
def payment_success():

    # ---------- GET DATA ----------
    product_id = request.args.get("product")
    mode = request.args.get("mode")
    board = request.args.get("board")
    cls = request.args.get("cls")

    phone = request.args.get("phone")
    email = request.args.get("email")
    state = request.args.get("state")

    board=session.get("board")
    cls=session.get("cls")

    if not product_id:
        return redirect(url_for("materials"))

    # ---------- ACCESS CONTROL ----------
    if mode == "view":
        session["view_" + product_id] = {
            "expiry": (datetime.now() + timedelta(minutes=1)).isoformat()
        }

    elif mode == "download":
        session["download_" + product_id] = {
            "expiry": (datetime.now() + timedelta(minutes=1)).isoformat()
        }

    session["access"] = session.get("access", {})
    session["access"][product_id] = {"view": True}

    # ---------- SAVE TO CSV ----------
    file = "payments.csv"

    with open(file, "a", newline="") as f:
        writer = csv.writer(f)

        if f.tell() == 0:
            writer.writerow(["Date", "Phone", "Email", "State", "Product"])

        writer.writerow([
            datetime.now().strftime("%d-%m-%Y %H:%M"),
            phone,
            email,
            state,
            product_id
        ])

    # ---------- REDIRECT ----------
    return redirect(url_for(
        "materials",
        board=board,
        cls=cls,
        paid=1,
        phone=phone   # 👉 for WhatsApp
    ))

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json()
    print("Received:", data)

    file_path = os.path.join(os.getcwd(), 'feedback.json')

    try:
        with open(file_path, 'r') as f:   # ✅ indent
            feedbacks = json.load(f)
    except:
        feedbacks = []

    feedbacks.append(data)

    with open(file_path, 'w') as f:
        json.dump(feedbacks, f, indent=4)

    return jsonify({"status": "success"})

# 🔹 Get feedback
@app.route('/get_feedback', methods=['GET'])
def get_feedback():
    with open('feedback.json', 'r') as f:
        feedbacks = json.load(f)

    # 🔥 only approved feedback
    approved_feedbacks = [f for f in feedbacks if f.get("approved") == True]
    
    return jsonify(feedbacks)


view_counts = {}

def increment_view_count(product_id):
    view_counts[product_id] = view_counts.get(product_id, 0) + 1

# ---------------- PERMISSION ----------------
@app.route("/check_permission/<product_id>")
def check_permission(product_id):

    allowed = check_access("download_" + product_id)
    return jsonify({"can_download": allowed})


# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    error = ""

    if request.method == "POST":
        if request.form.get("password") == "admin123":
            session["admin"] = True
            return redirect("/upload")
        else:
            error = "Wrong Password ❌"

    return f"""
<!DOCTYPE html>
<html>
<head>
<title>Admin Login</title>
<style>
body {{
    margin:0;
    height:100vh;
    display:flex;
    justify-content:center;
    align-items:center;
    background:#f4f6f9;
    font-family:Arial;
}}

.login-box {{
    background:white;
    padding:40px;
    border-radius:12px;
    box-shadow:0 8px 20px rgba(0,0,0,0.1);
    text-align:center;
    width:320px;
}}

.logo {{
    width:70px;
    margin-bottom:10px;
}}

h2 {{
    margin-bottom:15px;
    color:#0b5394;
}}

.error {{
    color:red;
    font-size:14px;
    margin-bottom:10px;
}}

.input-group {{
    text-align:left;
    margin-bottom:20px;
}}

.input-group input {{
    width:100%;
    padding:10px;
    border-radius:6px;
    border:1px solid #ccc;
}}

.password-box {{
    position:relative;
}}

.eye {{
    position:absolute;
    right:10px;
    top:10px;
    cursor:pointer;
}}

button {{
    width:100%;
    padding:10px;
    background:#0b5394;
    color:white;
    border:none;
    border-radius:6px;
    cursor:pointer;
}}

button:hover {{
    background:#083b73;
}}
</style>
</head>

<body>

<div class="login-box">

    <img src="/static/images/logo.jpg" class="logo">

    <h2>Admin Login</h2>

    <div class="error">{error}</div>

    <form method="post">
        <div class="input-group password-box">
            <input type="password" id="pwd" name="password" placeholder="Enter Password" required>
            <span class="eye" onclick="toggle()">👁️</span>
        </div>

        <button type="submit">Login</button>
    </form>
</div>

<script>
function toggle(){{
    const p = document.getElementById("pwd");
    p.type = p.type === "password" ? "text" : "password";
}}
</script>

</body>
</html>
"""

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return redirect("/admin")

    if request.method == "POST":
        file = request.files.get("pdf")
        if file:
            file.save(os.path.join(PDF_FOLDER, file.filename))

            # ✅ success response
            return """
            <h3>Uploaded Successfully ✅</h3>
            <a href='/upload'>⬅ Back</a>
            """

    return """
<h2>Admin Dashboard</h2>

<div style="max-width:400px; margin:auto; text-align:center;">

<h3>Upload Maths PDF</h3>

<form method="post" enctype="multipart/form-data">
    <input type="file" name="pdf" accept=".pdf" required><br><br>
    <button type="submit">Upload</button>
</form>

<br><br>

<a href="/manage-feedback">
    <button>Manage Feedback</button>
</a>

<br><br>

<a href="/logout">Logout</a>

</div>
"""
    
@app.route('/manage-feedback')
def manage_feedback():
    if not session.get("admin"):
        return redirect("/admin")

    return render_template("manage_feedback.html")

@app.route('/admin_feedback')
def admin_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403

    with open('feedback.json', 'r') as f:
        feedbacks = json.load(f)

    return jsonify(feedbacks)

@app.route('/approve_feedback', methods=['POST'])
def approve_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json()
    index = data.get("index")

    try:
        with open('feedback.json', 'r') as f:
            feedbacks = json.load(f)
    except:
        feedbacks = []

    # ✅ 👉 ADD HERE
    if index is None or index >= len(feedbacks):
        return jsonify({"error": "invalid index"}), 400

    feedbacks[index]["approved"] = True

    with open('feedback.json', 'w') as f:
        json.dump(feedbacks, f, indent=4)

    return jsonify({"status": "approved"})

@app.route('/delete_feedback', methods=['POST'])
def delete_feedback():
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 403

    data = request.get_json()
    index = data.get("index")

    try:
        with open('feedback.json', 'r') as f:
            feedbacks = json.load(f)
    except:
        feedbacks = []

    # ✅ 👉 ADD HERE
    if index is None or index >= len(feedbacks):
        return jsonify({"error": "invalid index"}), 400

    feedbacks.pop(index)

    with open('feedback.json', 'w') as f:
        json.dump(feedbacks, f, indent=4)

    return jsonify({"status": "deleted"})

# ---------------- CONTACT ----------------
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        print(request.form)
    return render_template("contact.html")
   


# ---------------- SITEMAP ----------------
@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(".", "sitemap.xml")


# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)

