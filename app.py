from flask import session

app.secret_key = "super-secret-key"
from flask import Flask, render_template, request, redirect, send_from_directory
from flask import Flask, request, redirect, session
import os
import razorpay
import json
import os

app = Flask(__name__)
PDF_FOLDER = "rsc-download"
@app.route("/downloads")
def downloads():
    pdfs = os.listdir(PDF_FOLDER)
    return render_template("downloads.html", pdfs=pdfs)
app = Flask(__name__)
app.secret_key = "supersecretkey123"
# Razorpay keys from Render Environment Variables
RAZORPAY_KEY = os.environ.get("RAZORPAY_KEY")
RAZORPAY_SECRET = os.environ.get("RAZORPAY_SECRET")

print("Razorpay key loaded:", RAZORPAY_KEY is not None)

client = razorpay.Client(auth=(RAZORPAY_KEY, RAZORPAY_SECRET))
with open("admin.json") as f:
    keys = json.load(f)

razorpay_client = razorpay.Client(
    auth=(keys["razorpay_key"], keys["razorpay_secret"])
)



# ✅ HOME PAGE
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/download/<pdf_name>")
def download(pdf_name):
    return redirect(f"/pay/{pdf_name}")

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

    })

    return render_template(
        "pay.html",
        key=RAZORPAY_KEY,
        amount=amount,
        order_id=order["id"],
        pdf=pdf_name
    )
@app.route("/success")
def success():
    file = request.args.get("file")
    return render_template("success.html", file=file)

@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(PDF_FOLDER, filename, as_attachment=True)

@app.route("/success", methods=["POST"])
def success():
    pdf = request.form.get("pdf")
    return send_from_directory(PDF_FOLDER, f"{pdf}.pdf", as_attachment=True)
    @app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if request.form["password"] == "admin123":
            session["admin"] = True
            return redirect("/upload")
    return '''
    <form method="post">
        <h2>Admin Login</h2>
        <input type="password" name="password" placeholder="Enter password" required>
        <button>Login</button>
    </form>
    '''


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return redirect("/admin")

    if request.method == "POST":
        file = request.files["pdf"]
        if file:
            os.makedirs("rsc-download", exist_ok=True)
            file.save(os.path.join("rsc-download", file.filename))

    return '''
    <h2>Upload Maths PDF</h2>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="pdf" accept=".pdf" required>
        <button>Upload</button>
    </form>
    '''


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
