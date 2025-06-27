from flask import Blueprint, request, jsonify
import qrcode
import io
import uuid
import time
from base64 import b64encode
from PIL import Image, ImageDraw, ImageFont
import psycopg2
from datetime import datetime, timedelta
from db_config import DB_HOST, DB_NAME, DB_USER, DB_PASS

token_bp = Blueprint('token_bp', __name__)

# ----------------- DB INSERT --------------------
def insert_token_to_db(token, patient_id, department_id, dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
    expires_at = dt + timedelta(days=1)
    today = dt.date()

    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()

    cur.execute("""
        SELECT COALESCE(MAX(id), 0) FROM patient_tokens
        WHERE DATE(datetime) = %s AND department_id = %s
    """, (today, department_id))
    max_id_today = cur.fetchone()[0]
    new_id = max_id_today + 1

    cur.execute("""
        INSERT INTO patient_tokens 
        (token, id, patient_id, department_id, datetime, expires_at, status, status_updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (token, new_id, patient_id, department_id, dt, expires_at, 'waiting', datetime.now()))

    conn.commit()
    cur.close()
    conn.close()
    return new_id, dt, expires_at

# ---------------- QR IMAGE GENERATOR ----------------
def generate_qr_card_image(patient_id, name, department_name, valid_till, id, qr_url):
    qr = qrcode.make(qr_url)
    qr = qr.resize((200, 200))

    card = Image.new("RGB", (400, 400), color="white")
    draw = ImageDraw.Draw(card)

    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except:
        font = ImageFont.load_default()

    qr_x = (card.width - qr.width) // 2
    card.paste(qr, (qr_x, 10))

    text_y_start = 230
    line_height = 20
    draw.text((20, text_y_start + 0 * line_height), f"Patient ID: {patient_id}", fill="black", font=font)
    draw.text((20, text_y_start + 1*line_height), f"Name: {name}", fill="black", font=font)
    draw.text((20, text_y_start + 2*line_height), f"Department: {department_name}", fill="black", font=font)
    draw.text((20, text_y_start + 3 * line_height), f"Valid till: {valid_till.strftime('%Y-%m-%d %H:%M')}", fill="black", font=font)
    draw.text((20, text_y_start + 4 * line_height), f"Token number: {id}", fill="black", font=font)

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return b64encode(buf.getvalue()).decode("utf-8")

# ---------------- REGISTER API ----------------
@token_bp.route("/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        patient_id = data["patient_id"]
        name = data["name"]
        department_id = data["department_id"]
        department_name = data["department_name"]
        datetime_str = data["date_time"]

        token = str(uuid.uuid4())
        daily_id, dt, expires_at = insert_token_to_db(token, patient_id, department_id, datetime_str)

        qr_url = f"{request.host_url}patient-info?upid={patient_id}"
        qr_card_b64 = generate_qr_card_image(patient_id, name, department_name, expires_at, daily_id, qr_url)

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

# ---------------- QUEUE API ----------------
@token_bp.route("/queue/<int:department_id>", methods=["GET"])
def get_department_queue(department_id):
    try:
        today = datetime.today().date()
        conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
        cur = conn.cursor()

        cur.execute("""
            SELECT id, token, patient_id, datetime, status, status_updated_at
            FROM patient_tokens
            WHERE department_id = %s AND DATE(datetime) = %s
            ORDER BY id ASC
        """, (department_id, today))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        queue = [
            {
                "id": row[0],
                "token": row[1],
                "patient_id": row[2],
                "datetime": row[3].strftime("%Y-%m-%d %H:%M"),
                "status": row[4],
                "status_updated_at": row[5].strftime("%Y-%m-%d %H:%M:%S")
            }
            for row in rows
        ]

        return jsonify({
            "department_id": department_id,
            "date": today.strftime("%Y-%m-%d"),
            "queue": queue
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
