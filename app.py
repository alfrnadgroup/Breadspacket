from flask import Flask, request, jsonify, send_file
import sqlite3
import os
import requests
from datetime import datetime

app = Flask(__name__)

DB_NAME = "bread_orders.db"

# ======================
# PAYPAL CONFIG
# ======================
PAYPAL_CLIENT = os.environ.get(
    "PAYPAL_CLIENT",
    "AdAZZJ6hx9Dp_cz_e506XL770LMrBhzaepLYQhloCBMxn8JAN85AYlpBVLS-PwLnMcG5sFm2uCRgZrYH"
)

PAYPAL_SECRET = os.environ.get(
    "PAYPAL_SECRET",
    "EDa0pdNGmpAQcu8ETAZsTp4awM15QbmtzwIyiREd2LyVVNvWRvL663QI-ewys-0llVK5eZLmXyMrH_x3"
)

PAYPAL_API = "https://api-m.paypal.com"

# ======================
# WHATSAPP CONFIG
# ======================
WHATSAPP_ACCESS_TOKEN = os.environ.get(
    "WHATSAPP_ACCESS_TOKEN",
    "EAATDkqdl5CQBRo22tAhuZCwbaCn76H7AfTZBQ2GH7tlo5fDRFQjcbyjHC3TpQnK2sUJBWw0qNi4jG6YSnSc6z76JbIC6s09H0DwlJ8LndRq8kfJJkfg6ZB3k4gZCvOrtZBrr1MiNrM2ZAgNLKSYqGKsYIUJkLJUKex933y3A9saZBXQoCZAo7G6KVImPh77z5LXc5yguAaqwVMRFvhhHwHnouYmPzcngME3IZAZAnh5W8G1QHji3ZAtZAwrJpQZDZD"
)

WHATSAPP_PHONE_NUMBER_ID = os.environ.get(
    "WHATSAPP_PHONE_NUMBER_ID",
    "1159465090580320"
)

ADMIN_WHATSAPP = os.environ.get("ADMIN_WHATSAPP", "96876976795")

# حفظ الطلبات المؤقتة للدفع الإلكتروني
PENDING_ORDERS = {}


# ======================
# INIT DATABASE
# ======================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            address TEXT,
            items TEXT,
            total REAL,
            status TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


# ======================
# WHATSAPP NOTIFICATION
# ======================
def send_whatsapp_admin(order):
    if not WHATSAPP_ACCESS_TOKEN:
        print("WhatsApp not configured")
        return

    message = f"""
🥖 طلب جديد - Bread Packet

👤 الاسم: {order.get('name','')}
📞 الهاتف: {order.get('phone','')}
📍 العنوان: {order.get('address','')}

🧺 المنتجات:
{order.get('items','')}

💰 الإجمالي:
{order.get('total','')}

📦 الحالة:
{order.get('status','Pending')}
"""

    try:
        requests.post(
            f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "to": ADMIN_WHATSAPP,
                "type": "text",
                "text": {"body": message}
            },
            timeout=20
        )
    except Exception as e:
        print("WhatsApp error:", e)


# ======================
# PAYPAL TOKEN
# ======================
def get_paypal_token():
    res = requests.post(
        PAYPAL_API + "/v1/oauth2/token",
        auth=(PAYPAL_CLIENT, PAYPAL_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials"
    )
    res.raise_for_status()
    return res.json()["access_token"]


# ======================
# ROUTES
# ======================

@app.route("/")
def home():
    return send_file("index.html")


@app.route("/admin")
def admin():
    return send_file("admin.html")


# ======================
# CREATE PAYPAL ORDER
# ======================
@app.route("/create-payment", methods=["POST"])
def create_payment():
    try:
        data = request.get_json()
        token = get_paypal_token()

        res = requests.post(
            PAYPAL_API + "/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": str(data["total"])
                    }
                }]
            }
        )

        res.raise_for_status()
        order = res.json()

        PENDING_ORDERS[order["id"]] = data

        return jsonify({"id": order["id"]})

    except Exception as e:
        print("CREATE PAYMENT ERROR:", e)
        return jsonify({"error": str(e)}), 500


# ======================
# CAPTURE PAYMENT
# ======================
@app.route("/capture-payment", methods=["POST"])
def capture_payment():
    try:
        body = request.get_json()
        order_id = body["orderID"]

        token = get_paypal_token()

        res = requests.post(
            f"{PAYPAL_API}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )

        res.raise_for_status()
        result = res.json()

        status = result["purchase_units"][0]["payments"]["captures"][0]["status"]

        if status == "COMPLETED":

            order = PENDING_ORDERS.get(order_id)

            if order:
                conn = sqlite3.connect(DB_NAME)

                conn.execute("""
                    INSERT INTO orders (
                        name, phone, address,
                        items, total, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.get("name"),
                    order.get("phone"),
                    order.get("address"),
                    order.get("items"),
                    float(order.get("total", 0)),
                    "Paid",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

                conn.commit()
                conn.close()

                order["status"] = "Paid"
                send_whatsapp_admin(order)

                del PENDING_ORDERS[order_id]

            return jsonify({"paid": True})

        return jsonify({"paid": False})

    except Exception as e:
        print("CAPTURE ERROR:", e)
        return jsonify({"paid": False, "error": str(e)}), 500


# ======================
# SAVE CASH / PHONE ORDER
# ======================
@app.route("/save-order", methods=["POST"])
def save_order():
    try:
        data = request.get_json()

        conn = sqlite3.connect(DB_NAME)

        conn.execute("""
            INSERT INTO orders (
                name, phone, address,
                items, total, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("name"),
            data.get("phone"),
            data.get("address"),
            data.get("items"),
            float(data.get("total", 0)),
            data.get("status", "Phone Payment"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        conn.close()

        send_whatsapp_admin(data)

        return jsonify({"success": True})

    except Exception as e:
        print("SAVE ORDER ERROR:", e)
        return jsonify({"success": False}), 500


# ======================
# GET ORDERS (ADMIN)
# ======================
@app.route("/orders")
def orders():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()

    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "phone": r["phone"],
            "address": r["address"],
            "items": r["items"],
            "total": r["total"],
            "status": r["status"],
            "created_at": r["created_at"]
        }
        for r in rows
    ])


# ======================
# RUN SERVER
# ======================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
  )
