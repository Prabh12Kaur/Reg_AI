from flask import Blueprint, request, jsonify
import qrcode
import io
import uuid
import time
from base64 import b64encode
from PIL import Image, ImageDraw, ImageFont
import psycopg2
from datetime import datetime, timedelta

token_bp = Blueprint('token_bp', __name__)

# PostgreSQL connection config
DB_HOST = 'localhost'
DB_NAME = 'MeghalayaDev'
DB_USER = 'postgres'
DB_PASS = 'Harsha@123'

def insert_token_to_db(token, patient_id, department_id, dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
    expires_at = dt + timedelta(days=1)
    today = dt.date()

    conn = psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(MAX(id), 0) FROM patient_tokens
        WHERE DATE(datetime) = %s
    """, (today,))
    max_id_today = cur.fetchone()[0]
    new_id = max_id_today + 1

    cur.execute("""
        INSERT INTO patient_tokens (token, id, patient_id, department_id, datetime, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (token, new_id, patient_id, department_id, dt, expires_at))

    conn.commit()
    cur.close()
    conn.close()
    return new_id, dt, expires_at

def generate_qr_card_image(patient_id, name, department_id, valid_till, id, qr_url):
    # Generate QR code image
    qr = qrcode.make(qr_url)
    qr = qr.resize((200, 200))

    # Create a blank image
    card = Image.new("RGB", (400, 300), color="white")
    draw = ImageDraw.Draw(card)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()

    # Draw text fields
    draw.text((220, 50), f"Name: {name}", fill="black", font=font)
    draw.text((220, 80), f"Dept: {department_id}", fill="black", font=font)
    draw.text((220, 100), f"Valid till:", fill="black", font=font)
    draw.text((220, 140), valid_till.strftime("%Y-%m-%d %H:%M"), fill="black", font=font)
    draw.text((220, 180), f"Token No.:{id}", fill="black", font=font)

    # Paste QR code
    card.paste(qr, (10, 50))

    # Convert to base64
    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return b64encode(buf.getvalue()).decode("utf-8")

@token_bp.route("/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        patient_id = data["patient_id"]
        name = data["name"]
        department_id = data["department_id"]
        datetime_str = data["date_time"]

        token = str(uuid.uuid4())
        timestamp = int(time.time())

        daily_id, dt, expires_at = insert_token_to_db(token, patient_id, department_id, datetime_str)
        qr_url = f"{request.host_url}patient-info?upid={patient_id}"
        print(qr_url)
        qr_card_b64 = generate_qr_card_image(patient_id, name, department_id, expires_at, daily_id, qr_url)

        return jsonify({
            "message": "Patient registered successfully",
            "token": token,
            "verify_url": qr_url,
            "qr_card_base64": qr_card_b64,
            "daily_id": daily_id,
            "patient": {
                "patient_id": patient_id,
                "department_id": department_id,
                "datetime": datetime_str
            }
        }), 201

    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
