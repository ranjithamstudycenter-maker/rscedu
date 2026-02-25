from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for,abort,jsonify,send_file
import os
import razorpay
import json
import smtplib
import time

from email.message import EmailMessage
from datetime import datetime, timedelta


# -------------------- APP INIT --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

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

@app.route("/reset")
def reset():
    session.clear()
    return "Session Cleared"


@app.route("/")
def home():
    return render_template("home.html")

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/class")
def courses():  
    return render_template("class.html")

@app.route("/materials")
def materials():

    board = request.args.get("board")
    cls = request.args.get("cls")
    open_id = request.args.get("open")

    if not board or not cls:
        return render_template(
            "materials.html",
            products={},
            access={},
            active_board=None,
            active_class=None,
            open=None
        )

    filtered_products = {
        pid: p for pid, p in PRODUCTS.items()
        if str(p["class"]) == str(cls)
        and str(p["board"]).lower() == str(board).lower()
    }

    access = {}
    for pid in filtered_products:
        access[pid] = {
            "view": session.get(f"view_{pid}", False),
            "download": session.get(f"download_{pid}", False)
        }

    if open_id not in filtered_products:
        open_id = None

    return render_template(
        "materials.html",
        products=filtered_products,
        access=access,
        active_board=board,
        active_class=cls,
        open=open_id
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

    # ⭐ Get directly from URL (not session)
    product_id = request.args.get("product")
    mode = request.args.get("mode")
    board = request.args.get("board")
    cls = request.args.get("cls")

    board=session.get("board")
    cls=session.get("cls")


    if not product_id:
        return redirect(url_for("materials"))

    # Grant access
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
    session[f"view_{product_id}"] = True
    
    # ✅ unlock only after success
    session[f"view_{product_id}"] = True
    
   # ⭐ FINAL redirect
    return redirect(url_for(
        "materials",
        board=board,
        cls=cls,
        paid=1
       
    ))




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
    if request.method == "POST" and request.form.get("password") == "admin123":
        session["admin"] = True
        return redirect("/upload")

    return """
    <h2>Admin Login</h2>
    <form method="post">
        <input type="password" name="password" required>
        <button>Login</button>
    </form>
    """


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return redirect("/admin")

    if request.method == "POST":
        file = request.files.get("pdf")
        if file:
            file.save(os.path.join(PDF_FOLDER, file.filename))

    return """
    <h2>Upload Maths PDF</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="pdf" accept=".pdf" required>
        <button>Upload</button>
    </form>
    """


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

