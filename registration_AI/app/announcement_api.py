import eventlet
eventlet.monkey_patch()

from flask import Blueprint, jsonify, request, render_template
from app import socketio
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

announcement_bp = Blueprint('announcement', __name__)

DB_CONFIG = {
    'dbname': 'your_db',
    'user': 'your_user',
    'password': 'your_password',
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def fetch_next_token():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(token_number), 0) FROM current_token")
            last_served_id = cur.fetchone()["coalesce"]

            cur.execute("""
                SELECT token, id, patient_id
                FROM patient_tokens
                WHERE datetime::date = CURRENT_DATE
                  AND expires_at > NOW()
                  AND id > %s
                ORDER BY id ASC
                LIMIT 1
            """, (last_served_id,))
            row = cur.fetchone()
            if row:
                return {
                    "uuid": row["token"],
                    "token": row["id"],
                    "name": row["patient_id"]
                }
    return None

@announcement_bp.route('/')
def health_check():
    return jsonify({"status": "API running"}), 200

@announcement_bp.route('/api/call-next', methods=['POST'])
def call_next():
    next_token = fetch_next_token()
    if next_token:
        socketio.emit('update-token', {
            "token": next_token["token"],
            "name": next_token["name"]
        })

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO current_token (token_uuid, token_number, patient_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                """, (
                    next_token["uuid"],
                    next_token["token"],
                    next_token["name"]
                ))
                conn.commit()

        return jsonify({
            "token": next_token["token"],
            "name": next_token["name"]
        }), 200
    else:
        return jsonify({"message": "No more tokens"}), 200

@announcement_bp.route('/api/current-token', methods=['GET'])
def get_current_token():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT token_number, patient_id
                FROM current_token
                ORDER BY updated_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                return jsonify({
                    "token": row[0],
                    "name": row[1]
                }), 200
            else:
                return jsonify({"message": "No current token"}), 200

@announcement_bp.route('/doctor-display')
def doctor_display():
    return render_template("templates/doctor_display.html")

@announcement_bp.route('/waiting-display')
def waiting_display():
    return render_template("templates/waiting_display.html")