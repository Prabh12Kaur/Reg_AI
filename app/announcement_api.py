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

def fetch_next_token(department_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COALESCE(MAX(token_number), 0) FROM current_token
                WHERE department_id = %s
            """, (department_id,))
            last_served_id = cur.fetchone()["coalesce"]

            cur.execute("""
                SELECT pt.token, pt.id, pt.patient_id, pt.department_id, p.first_name, p.last_name
                FROM patient_tokens pt
                JOIN patients p ON pt.patient_id = p.patient_id
                WHERE pt.datetime::date = CURRENT_DATE
                  AND pt.expires_at > NOW()
                  AND pt.id > %s
                  AND pt.department_id = %s
                ORDER BY pt.id ASC
                LIMIT 1
            """, (last_served_id, department_id))
            row = cur.fetchone()
            if row:
                return {
                    "uuid": row["token"],
                    "token": row["id"],
                    "name": f"{row['first_name']} {row['last_name']}",
                    "patient_id": row["patient_id"],
                    "department_id": row["department_id"]
                }
    return None

@announcement_bp.route('/')
def health_check():
    return jsonify({"status": "API running"}), 200

@announcement_bp.route('/api/call-next', methods=['POST'])
def call_next():
    data = request.get_json()
    department_id = data.get("department_id")
    if not department_id:
        return jsonify({"error": "Missing department_id"}), 400

    next_token = fetch_next_token(department_id)
    if next_token:
        socketio.emit('update-token', {
            "token": next_token["token"],
            "name": next_token["name"]
        })

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO current_token (token_uuid, token_number, patient_id, department_id, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (department_id) DO UPDATE SET
                        token_uuid = EXCLUDED.token_uuid,
                        token_number = EXCLUDED.token_number,
                        patient_id = EXCLUDED.patient_id,
                        updated_at = NOW()
                """, (
                    next_token["uuid"],
                    next_token["token"],
                    next_token["patient_id"],
                    next_token["department_id"]
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
    department_id = request.args.get("department_id")
    if not department_id:
        return jsonify({"error": "Missing department_id"}), 400

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ct.token_number, p.first_name, p.last_name
                FROM current_token ct
                JOIN patients p ON ct.patient_id = p.patient_id
                WHERE ct.department_id = %s
                ORDER BY ct.updated_at DESC
                LIMIT 1
            """, (department_id,))
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
    data = request.get_json()
    department_id = data.get("department_id")
    if not department_id:
        return jsonify({"error": "Missing department_id"}), 400

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ct.token_number, p.first_name, p.last_name
                FROM current_token ct
                JOIN patients p ON ct.patient_id = p.patient_id
                WHERE ct.department_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
            """, (department_id,))
            row = cur.fetchone()
            if row:
                socketio.emit('update-token', {
                    "token": row["token_number"],
                    "name": f"{row['first_name']} {row['last_name']}"
                })
                return jsonify({"success": True, "message": "Announcement repeated"}), 200
            else:
                return jsonify({"success": False, "message": "No current token"}), 200
