"""POST /api/auth/join"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_patch, sb_post
from lib.auth import get_family_info, create_session, is_https, now_utc
from lib.response import json_response, error, set_cookie_header

SESSION_DAYS = 30

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    try:
        body = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    token = str(body.get("token", "")).strip()
    if not token:
        return error("Token wajib diisi", 400)

    # Verifikasi token
    try:
        rows = sb_get("invite_tokens", [
            ("select", "id,user_id,used,expires_at"),
            ("token",  f"eq.{token}"),
            ("limit",  "1"),
        ])
        if not rows:
            return error("Link undangan tidak valid atau sudah kadaluarsa", 400)
        row = rows[0]
        if row["used"]:
            return error("Link undangan sudah pernah digunakan. Minta admin kirim ulang.", 400)
        exp = None
        try:
            exp = __import__("datetime").datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        except Exception:
            pass
        if exp and now_utc() > exp:
            return error("Link undangan sudah kadaluarsa. Minta admin kirim ulang.", 400)
    except Exception as e:
        return error(str(e), 500)

    # Ambil data user
    try:
        users = sb_get("users", [
            ("select", "id,family_id,username,display_name,role"),
            ("id",     f"eq.{row['user_id']}"),
            ("limit",  "1"),
        ])
        if not users:
            return error("Akun tidak ditemukan", 404)
        u = users[0]
    except Exception as e:
        return error(str(e), 500)

    family_name, family_code = get_family_info(u["family_id"])

    # Tandai token sudah dipakai
    try:
        sb_patch("invite_tokens", {"token": f"eq.{token}"}, {"used": True})
    except Exception:
        pass

    # Buat session baru
    try:
        session_token = create_session(u["id"], u["family_id"])
    except Exception as e:
        return error(f"Gagal buat session: {e}", 500)

    secure = is_https(request)
    return json_response(
        {
            "ok":           True,
            "first_login":  True,
            "user": {
                "id":           u["id"],
                "username":     u["username"],
                "display_name": u["display_name"],
                "role":         u["role"],
                "family_id":    u["family_id"],
                "family_name":  family_name,
                "family_code":  family_code,
            }
        },
        200,
        {"Set-Cookie": set_cookie_header(session_token, days=SESSION_DAYS, secure=secure)}
    )
