"""POST /api/auth/login"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post
from lib.auth import (verify_password, create_session, get_family_info,
                      is_rate_limited, record_failed, clear_attempts, is_https)
from lib.response import json_response, error, set_cookie_header

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    try:
        body     = json.loads(request.body)
        username = str(body.get("username", "")).strip().lower()
        password = str(body.get("password", "")).strip()
    except Exception:
        return error("Invalid JSON", 400)

    if not username or not password:
        return error("Username dan password wajib diisi", 400)

    ip = request.headers.get("x-forwarded-for", "unknown").split(",")[0].strip()
    if is_rate_limited(ip):
        return error("Terlalu banyak percobaan. Coba lagi dalam 15 menit.", 429)

    try:
        users = sb_get("users", [
            ("select",   "id,family_id,username,password_hash,display_name,role"),
            ("username", f"eq.{username}"),
            ("limit",    "1"),
        ])
        if not users:
            record_failed(ip)
            return error("Username atau password salah", 401)
        user = users[0]
    except Exception as e:
        return error(f"Server error: {e}", 500)

    if not verify_password(password, user["password_hash"]):
        record_failed(ip)
        return error("Username atau password salah", 401)

    clear_attempts(ip)

    try:
        token = create_session(user["id"], user["family_id"])
        family_name, family_code = get_family_info(user["family_id"])
    except Exception as e:
        return error(f"Gagal buat session: {e}", 500)

    secure = is_https(request)
    return json_response(
        {
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
        },
        200,
        {"Set-Cookie": set_cookie_header(token, secure=secure)}
    )
