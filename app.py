from flask import Flask, render_template, request, redirect, session, send_from_directory
import os
import razorpay
import json
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from flask import url_for


# -------------------- APP CONFIG --------------------
app = Flask(__name__)
app.secret_key = "supersecretkey123"

PDF_FOLDER = "rsc-download"
os.makedirs(PDF_FOLDER, exist_ok=True)
# ---------------- EMAIL CONFIG ----------------
EMAIL_ID = "ranjithamstudycenter@gmail.com"
EMAIL_PASS = "YOUR_APP_PASSWORD"

download_tokens = {}

def send_email(to_email, file, link):
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


# -------------------- LOAD RAZORPAY KEYS --------------------
with open("admin.json") as f:
    keys = json.load(f)

razorpay_client = razorpay.Client(
    auth=(keys["razorpay_key"], keys["razorpay_secret"])
)

# -------------------- HOME --------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------- LIST PDF DOWNLOADS --------------------
@app.route("/downloads")
def downloads():
    pdfs = os.listdir(PDF_FOLDER)
    return render_template("downloads.html", pdfs=pdfs)

# -------------------- REDIRECT TO PAYMENT --------------------
@app.route("/download/<pdf_name>")
def download(pdf_name):
    return redirect(f"/pay?file={pdf_name}")

# -------------------- PAYMENT PAGE --------------------
@app.route("/pay")
def pay():
    file = request.args.get("file")

    order = razorpay_client.order.create({
        "amount": 4900,  # ₹49
        "currency": "INR",
        "payment_capture": 1
    })

    return render_template(
        "pay.html",
        file=file,
        order_id=order["id"],
        razorpay_key=keys["razorpay_key"]
    )

# -------------------- PAYMENT SUCCESS --------------------
@app.route("/success", methods=["POST"])
def success():
    file = request.form.get("file")
    email = request.form.get("email")
    phone = request.form.get("phone")

    token = os.urandom(8).hex()
    expiry = datetime.now() + timedelta(hours=1)
    download_tokens[token] = {"file": file, "expiry": expiry}

    secure_link = url_for("download_secure", token=token, _external=True)

    if email:
        send_email(email, file, secure_link)

    wa_link = whatsapp_link(phone, secure_link) if phone else None

    return render_template("success.html", whatsapp=wa_link)
@app.route("/download-secure/<token>")
def download_secure(token):
    data = download_tokens.get(token)

    if not data or datetime.now() > data["expiry"]:
        return "Link expired or invalid", 403

    return send_from_directory(PDF_FOLDER, data["file"], as_attachment=True)


# -------------------- ADMIN LOGIN --------------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form["password"] == "admin123":
            session["admin"] = True
            return redirect("/upload")
    return '''
    <h2>Admin Login</h2>
    <form method="post">
        <input type="password" name="password" placeholder="Enter password" required>
        <button>Login</button>
    </form>
    '''

# -------------------- PDF UPLOAD --------------------
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return redirect("/admin")

    if request.method == "POST":
        file = request.files["pdf"]
        if file:
            file.save(os.path.join(PDF_FOLDER, file.filename))

    return '''
    <h2>Upload Maths PDF</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="pdf" accept=".pdf" required>
        <button>Upload</button>
    </form>
    '''
# ---------------- SITEMAP ----------------
@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(".", "sitemap.xml")

# -------------------- RUN APP --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
