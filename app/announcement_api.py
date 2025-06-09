import eventlet
eventlet.monkey_patch()

from flask import Blueprint, jsonify, request, render_template
from app import socketio
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from db_config import DB_HOST, DB_NAME, DB_USER, DB_PASS

announcement_bp = Blueprint('announcement', __name__)

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)

def fetch_next_token():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(token_number), 0) FROM current_token")
            last_served_id = cur.fetchone()["coalesce"]

            cur.execute("""
                SELECT pt.token, pt.id, p.first_name, p.last_name
                FROM patient_tokens pt
                JOIN patients p ON pt.patient_id = p.patient_id
                WHERE pt.datetime::date = CURRENT_DATE
                  AND pt.expires_at > NOW()
                  AND pt.id > %s
                ORDER BY pt.id ASC
                LIMIT 1
            """, (last_served_id,))
            row = cur.fetchone()
            if row:
                return {
                    "uuid": row["token"],
                    "token": row["id"],
                    "name": f"{row['first_name']} {row['last_name']}",
                    "patient_id": row["patient_id"]
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
                    next_token["patient_id"]
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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ct.token_number, p.first_name, p.last_name
                FROM current_token ct
                JOIN patients p ON ct.patient_id = p.patient_id
                ORDER BY ct.updated_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                return jsonify({
                    "token": row["token_number"],
                    "name": f"{row['first_name']} {row['last_name']}"
                }), 200
            else:
                return jsonify({"message": "No current token"}), 200

@announcement_bp.route('/doctor-display')
def doctor_display():
    return render_template("doctor_display.html")

@announcement_bp.route('/waiting-display')
def waiting_display():
    return render_template("waiting_display.html")

@announcement_bp.route('/api/announce-current', methods=['POST'])
def announce_current():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT token_number, patient_id
                FROM current_token
                ORDER BY updated_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            
            if row:
                # Re-emit the current token to trigger announcement
                socketio.emit('update-token', {
                    "token": row["token_number"],
                    "name": row["patient_id"]  # This contains the patient name in your current implementation
                })
                return jsonify({"success": True, "message": "Announcement repeated"}), 200
            else:
                return jsonify({"success": False, "message": "No current token"}), 200
