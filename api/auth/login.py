"""POST /api/auth/login — Vercel Python (Flask WSGI)"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from lib.supabase import sb_get, sb_post
from lib.auth import (verify_password, create_session, get_family_info,
                      is_rate_limited, record_failed, clear_attempts, is_https,
                      SESSION_DAYS, MIN_PASS_LEN)
from lib.response import set_cookie_header

app = Flask(__name__)
CORS(app, supports_credentials=True)

@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data     = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({"error": "Username dan password wajib diisi"}), 400

    ip = request.headers.get("x-forwarded-for", "unknown").split(",")[0].strip()
    if is_rate_limited(ip):
        return jsonify({"error": "Terlalu banyak percobaan. Coba lagi dalam 15 menit."}), 429

    try:
        users = sb_get("users", [
            ("select",   "id,family_id,username,password_hash,display_name,role"),
            ("username", f"eq.{username}"),
            ("limit",    "1"),
        ])
        if not users:
            record_failed(ip)
            return jsonify({"error": "Username atau password salah"}), 401
        user = users[0]
    except Exception as e:
        return jsonify({"error": f"Server error: {e}"}), 500

    if not verify_password(password, user["password_hash"]):
        record_failed(ip)
        return jsonify({"error": "Username atau password salah"}), 401

    clear_attempts(ip)

    try:
        token = create_session(user["id"], user["family_id"])
        family_name, family_code = get_family_info(user["family_id"])
    except Exception as e:
        return jsonify({"error": f"Gagal buat session: {e}"}), 500

    resp = make_response(jsonify({
        "ok": True,
        "user": {
            "id":           user["id"],
            "username":     user["username"],
            "display_name": user["display_name"],
            "role":         user["role"],
            "family_id":    user["family_id"],
            "family_name":  family_name,
            "family_code":  family_code,
        }
    }))
    resp.set_cookie("dompetku_session", token,
                    max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="Lax",
                    secure=is_https(request))
    return resp
