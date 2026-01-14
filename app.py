from flask import Flask, render_template, request, redirect, send_from_directory
import razorpay
import os

app = Flask(__name__)
PDF_FOLDER = "rsc-download"
@app.route("/downloads")
def downloads():
    pdfs = os.listdir(PDF_FOLDER)
    return render_template("downloads.html", pdfs=pdfs)

# Razorpay keys from Render Environment Variables
RAZORPAY_KEY = os.environ.get("RAZORPAY_KEY")
RAZORPAY_SECRET = os.environ.get("RAZORPAY_SECRET")

print("Razorpay key loaded:", RAZORPAY_KEY is not None)

client = razorpay.Client(auth=(RAZORPAY_KEY, RAZORPAY_SECRET))



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
    return render_template("pay.html", file=file)


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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
