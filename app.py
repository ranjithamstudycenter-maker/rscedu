from flask import Flask, render_template, request, redirect, send_from_directory, jsonify
import razorpay
import json
import os

app = Flask(__name__)

# Load Razorpay keys
import os

keys = {
    "razorpay_key": os.environ.get("RAZORPAY_KEY"),
    "razorpay_secret": os.environ.get("RAZORPAY_SECRET")
}

client = razorpay.Client(auth=(keys["razorpay_key"], keys["razorpay_secret"]))

PDF_FOLDER = "static"  # PDFs location

# ----- Homepage -----
@app.route("/")
def home():
    return "<h2>Welcome to Ranjitham Study Center</h2>Click /download/maths1 or /download/tnpsc1 to start."

# ----- Payment page -----
@app.route("/pay/<pdf_name>")
def pay(pdf_name):
    # Payment amount in paise (₹50 = 5000 paise)
    amount = 5000
    currency = "INR"
    payment = client.order.create(dict(amount=amount, currency=currency, payment_capture=1))
    order_id = payment["id"]

    return render_template("pay.html", 
                           key=keys["razorpay_key"], 
                           amount=amount, 
                           currency=currency, 
                           order_id=order_id,
                           pdf=pdf_name)

# ----- Payment verification route -----
@app.route("/success", methods=["POST"])
def success():
    data = request.form
    pdf_name = data.get("pdf")
    
    # Here you can verify payment with Razorpay API if needed
    # For demo, we assume payment is successful

    # Send PDF for auto-download
    return send_from_directory(PDF_FOLDER, f"{pdf_name}.pdf", as_attachment=True)

# ----- Download link redirects to payment -----
@app.route("/download/<pdf_name>")
def download(pdf_name):
    return redirect(f"/pay/{pdf_name}")

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # use Render PORT env variable, default 5000
    app.run(host="0.0.0.0", port=port)
