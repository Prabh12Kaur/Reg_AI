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

def fetch_department_name(department_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM specializations WHERE specialization_id = %s", (department_id,))
            result = cur.fetchone()
            return result[0] if result else "Unknown"

def fetch_current_token(department_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ct.token_number, pt.status
                FROM current_token ct
                JOIN patient_tokens pt ON pt.id = ct.token_number
                WHERE ct.department_id = %s
                ORDER BY ct.updated_at DESC
                LIMIT 1
            """, (department_id,))
            return cur.fetchone()

def fetch_next_token(department_id, skip_token_id=None):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for status in ('recall', 'waiting', 'hold'):
                query = """
                    SELECT pt.id, pt.token, pt.patient_id, p.first_name, p.last_name
                    FROM patient_tokens pt
                    JOIN patients p ON pt.patient_id = p.patient_id
                    WHERE pt.datetime::date = CURRENT_DATE
                      AND pt.status = %s
                      AND pt.department_id = %s
                """
                params = [status, department_id]

                if skip_token_id:
                    query += " AND pt.id != %s"
                    params.append(skip_token_id)

                query += " ORDER BY pt.status_updated_at ASC LIMIT 1"

                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    return {
                        "uuid": row["token"],
                        "token": row["id"],
                        "name": f"{row['first_name']} {row['last_name']}",
                        "patient_id": row["patient_id"],
                        "department_id": department_id
                    }
    return None

def safe_emit(event, data):
    try:
        socketio.emit(event, data)
    except Exception as e:
        print(f"⚠ SocketIO emit failed: {e}")

@announcement_bp.route('/')
def health_check():
    return jsonify({"status": "API running"}), 200

@announcement_bp.route('/api/call-next', methods=['POST'])
def call_next():
    data = request.get_json()
    department_id = data.get("department_id")
    if not department_id:
        return jsonify({"error": "Missing department_id"}), 400

    # Step 1: Mark current consulting token as completed
    # Step 1: Mark current token as completed (regardless of its current status)
    current = fetch_current_token(department_id)
    token_id = current["token_number"] if current else None

    if token_id:
        print(f"✅ Marking token {token_id} as completed (forced)")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE patient_tokens
                    SET status = 'completed', status_updated_at = NOW()
                    WHERE id = %s
                """, (token_id,))
                conn.commit()
    else:
        print("⚠️ No token to complete.")

    # Step 2: Fetch next eligible token
    next_token = fetch_next_token(department_id)

    # Step 3: If found, conditionally update to consulting
    if next_token:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Check the status of the selected token
                cur.execute("SELECT status FROM patient_tokens WHERE id = %s", (next_token["token"],))
                status_row = cur.fetchone()
                token_status = status_row[0] if status_row else None

                # Only promote to consulting if token is in 'waiting'
                if token_status == "waiting":
                    cur.execute("""
                        UPDATE patient_tokens
                        SET status = 'consulting', status_updated_at = NOW()
                        WHERE id = %s
                    """, (next_token["token"],))

                # Always update current_token table
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

        # Step 4: Emit update
        safe_emit('update-token', {
            "token": next_token["token"],
            "name": next_token["name"],
            "department_id": department_id,
            "status": token_status or "consulting"
        })

        return jsonify({
            "token": next_token["token"],
            "name": next_token["name"],
            "department": fetch_department_name(department_id)
        }), 200

    else:
        # No eligible token found
        safe_emit('update-token', {
            "token": "--",
            "name": "No more tokens",
            "department_id": department_id,
            "force": True
        })
        return jsonify({"message": "No more tokens"}), 200


@announcement_bp.route('/api/move-next', methods=['POST'])
def move_next():
    data = request.get_json()
    department_id = data.get("department_id")
    if not department_id:
        return jsonify({"error": "Missing department_id"}), 400

    current_token_id = None
    current_status = None
    new_status = None
    patient_name = "Unknown"

    # Step 1: Identify current token
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ct.token_number, p.first_name, p.last_name
                FROM current_token ct
                JOIN patient_tokens pt ON pt.id = ct.token_number
                JOIN patients p ON pt.patient_id = p.patient_id
                WHERE ct.department_id = %s
                ORDER BY ct.updated_at DESC
                LIMIT 1
            """, (department_id,))
            row = cur.fetchone()
            if row:
                current_token_id = row["token_number"]
                patient_name = f"{row['first_name']} {row['last_name']}"

    # Step 2: If current token found, update its status
    if current_token_id:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM patient_tokens WHERE id = %s", (current_token_id,))
                row = cur.fetchone()
                if row:
                    current_status = row[0]
                    # Determine next status based on lifecycle
                    if current_status == "consulting":
                        new_status = "recall"
                    elif current_status == "recall":
                        new_status = "hold"
                    elif current_status == "hold":
                        new_status = "no_show"
                    else:
                        new_status = "recall"  # fallback for unexpected state

                    # Update the status
                    cur.execute("""
                        UPDATE patient_tokens
                        SET status = %s, status_updated_at = NOW()
                        WHERE id = %s
                    """, (new_status, current_token_id))
                    conn.commit()

                    print(f"✅ Token {current_token_id} marked as {new_status}")

                    # Emit token status update
                    safe_emit('update-token', {
                        "token": current_token_id,
                        "name": patient_name,
                        "department_id": department_id,
                        "status": new_status
                    })

    # Step 3: Fetch the next eligible token, skipping the current one
    next_token = fetch_next_token(department_id, skip_token_id=current_token_id)

    # Step 4: Assign next token (if found)
    if next_token:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Check the token's current status
                cur.execute("SELECT status FROM patient_tokens WHERE id = %s", (next_token["token"],))
                status_row = cur.fetchone()
                if status_row and status_row[0] == "waiting":
                    # Only promote to consulting if it's in waiting
                    cur.execute("""
                        UPDATE patient_tokens
                        SET status = 'consulting', status_updated_at = NOW()
                        WHERE id = %s
                    """, (next_token["token"],))

                # Always update current_token table
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

        print(f"✅ Now showing token {next_token['token']}")

        safe_emit('update-token', {
            "token": next_token["token"],
            "name": next_token["name"],
            "department_id": department_id,
            "status": status_row[0] if status_row else "consulting"
        })

        return jsonify({
            "token": next_token["token"],
            "name": next_token["name"],
            "department": fetch_department_name(department_id)
        }), 200

    else:
        print("ℹ️ No eligible tokens to call next.")

        safe_emit('update-token', {
            "token": "--",
            "name": "No more tokens",
            "department_id": department_id,
            "force": True
        })
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
                    "name": f"{row['first_name']} {row['last_name']}",
                    "department": fetch_department_name(department_id)
                }), 200
            else:
                return jsonify({"message": "No current token"}), 200

@announcement_bp.route('/doctor-display')
def doctor_display():
    return render_template("doctor_display.html")

@announcement_bp.route('/waiting-display')
def waiting_display():
    return render_template("waiting_display.html")

@announcement_bp.route('/multi-waiting-display')
def multi_waiting_display():
    return render_template("multi_waiting_display.html")

@announcement_bp.route('/api/departments', methods=['GET'])
def get_departments():
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT specialization_id AS id, name FROM specializations")
            departments = cur.fetchall()
            return jsonify({"departments": departments}), 200

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
                safe_emit('update-token', {
                    "token": row["token_number"],
                    "name": f"{row['first_name']} {row['last_name']}",
                    "department_id": department_id,
                    "force": True
                })
                return jsonify({"success": True, "message": "Announcement repeated"}), 200
            else:
                return jsonify({"success": False, "message": "No current token"}), 200
