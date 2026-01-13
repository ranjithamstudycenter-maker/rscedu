from flask import Flask, render_template, request, redirect, send_from_directory
import razorpay
import os

app = Flask(__name__)

# Load Razorpay keys from Render Environment
keys = {
    "razorpay_key": os.environ.get("RAZORPAY_KEY"),
    "razorpay_secret": os.environ.get("RAZORPAY_SECRET")
}

client = razorpay.Client(auth=(keys["razorpay_key"], keys["razorpay_secret"]))

PDF_FOLDER = "static"  # folder where PDFs are stored

# ----- Homepage -----
@app.route("/")
def home():
    return "<h2>Welcome to Ranjitham Study Center</h2>Click /download/maths1 or /download/tnpsc1 to start."

# ----- Download link redirects to payment -----
@app.route("/download/<pdf_name>")
def download(pdf_name):
    return redirect(f"/pay/{pdf_name}")

# ----- Payment page -----
@app.route("/pay/<pdf_name>")
def pay(pdf_name):
    amount = 5000  # ₹50
    currency = "INR"

    payment = client.order.create({
        "amount": amount,
        "currency": currency,
        "payment_capture": 1
    })

    return render_template(
        "pay.html",
        key=keys["razorpay_key"],
        amount=amount,
        currency=currency,
        order_id=payment["id"],
        pdf=pdf_name
    )

# ----- Payment success & auto-download -----
@app.route("/success", methods=["POST"])
def success():
    pdf_name = request.form.get("pdf")
    return send_from_directory(PDF_FOLDER, f"{pdf_name}.pdf", as_attachment=True)

import os
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello World!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    print(f"Listening on port {port}")
    app.run(host="0.0.0.0", port=port)

