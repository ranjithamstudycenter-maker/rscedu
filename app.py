from flask import Flask, render_template, request, redirect, session, send_from_directory, url_for
import os
import razorpay
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta

# -------------------- APP INIT --------------------
app = Flask(__name__)
app.secret_key = "supersecretkey123"

# -------------------- FOLDERS --------------------
PDF_FOLDER = "rsc-download"
os.makedirs(PDF_FOLDER, exist_ok=True)

# -------------------- PRODUCTS --------------------
PRODUCTS = {
    "math-basics-free": {
        "file": "math_basics.pdf",
        "title": "Math Basics (Free)",
        "price": 0,
        "course": "class5-7"
    },
    "class7-practice-free": {
        "file": "class7_practice.pdf",
        "title": "Class 7 Practice Worksheet (Free)",
        "price": 0,
        "course": "class5-7"
    },
    "class10-notes": {
        "file": "class10_notes.pdf",
        "title": "Class 10 Maths Notes",
        "price": 49,
        "course": "class8-10"
    },
    "class12-calculus": {
        "file": "class12_calculus.pdf",
        "title": "Class 12 Calculus Notes",
        "price": 99,
        "course": "class11-12"
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

razorpay_client = razorpay.Client(
    auth=(keys["razorpay_key"], keys["razorpay_secret"])
)

# -------------------- ROUTES --------------------

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/class")
@app.route("/courses")
def courses():
    return render_template("courses.html")

@app.route("/downloads")
def downloads():
    return render_template("downloads.html", products=PRODUCTS)

@app.route("/download/<product_id>")
def download(product_id):
    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product"

    if product["price"] == 0:
        return send_from_directory(PDF_FOLDER, product["file"], as_attachment=True)

    return redirect(url_for("pay", product=product_id))

# -------------------- PAYMENT --------------------

@app.route("/pay")
def pay():
    product_id = request.args.get("product")
    product = PRODUCTS.get(product_id)

    if not product:
        return "Invalid product"

    order = razorpay_client.order.create({
        "amount": product["price"] * 100,
        "currency": "INR",
        "payment_capture": 1
    })

    return render_template(
        "pay.html",
        product=product,
        order_id=order["id"],
        razorpay_key=keys["razorpay_key"]
    )

@app.route("/success", methods=["POST"])
def success():
    product_id = request.form.get("product")
    email = request.form.get("email")
    phone = request.form.get("phone")

    product = PRODUCTS.get(product_id)
    if not product:
        return "Invalid product"

    token = os.urandom(8).hex()
    expiry = datetime.now() + timedelta(hours=1)
    download_tokens[token] = {"file": product["file"], "expiry": expiry}

    secure_link = url_for("download_secure", token=token, _external=True)

    if email:
        send_email(email, secure_link)

    wa = whatsapp_link(phone, secure_link) if phone else None
    return render_template("success.html", whatsapp=wa)

@app.route("/download-secure/<token>")
def download_secure(token):
    data = download_tokens.get(token)
    if not data or datetime.now() > data["expiry"]:
        return "Link expired", 403

    return send_from_directory(PDF_FOLDER, data["file"], as_attachment=True)

# -------------------- ADMIN --------------------

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

# -------------------- CONTACT --------------------

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        print(request.form)
    return render_template("contact.html")

# -------------------- SITEMAP --------------------

@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(".", "sitemap.xml")

# -------------------- RUN --------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
