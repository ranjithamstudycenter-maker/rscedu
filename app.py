from flask import Flask, render_template, request, redirect, send_from_directory
import razorpay
import os

app = Flask(__name__)

# Razorpay keys from Render Environment Variables
RAZORPAY_KEY = os.environ.get("RAZORPAY_KEY")
RAZORPAY_SECRET = os.environ.get("RAZORPAY_SECRET")

client = razorpay.Client(auth=(RAZORPAY_KEY, RAZORPAY_SECRET))

PDF_FOLDER = "static"

@app.route("/")
def home():
    return "Ranjitham Study Center Backend Running"

@app.route("/download/<pdf_name>")
def download(pdf_name):
    return redirect(f"/pay/{pdf_name}")

@app.route("/pay/<pdf_name>")
def pay(pdf_name):
    amount = 5000  # ₹50
    currency = "INR"
    order = client.order.create({
        "amount": amount,
        "currency": currency,
        "payment_capture": 1
    })

    return render_template(
        "pay.html",
        key=RAZORPAY_KEY,
        amount=amount,
        order_id=order["id"],
        pdf=pdf_name
    )

@app.route("/success", methods=["POST"])
def success():
    pdf = request.form.get("pdf")
    return send_from_directory(PDF_FOLDER, f"{pdf}.pdf", as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
