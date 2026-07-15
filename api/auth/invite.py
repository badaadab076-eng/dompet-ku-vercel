"""POST /api/auth/invite"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post
from lib.auth import get_session, gen_token, expires_invite
from lib.response import json_response, error

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)
    if user.get("role") != "admin":
        return error("Hanya admin yang bisa membuat undangan", 403)

    try:
        body = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    target_user_id = body.get("target_user_id")
    if not target_user_id:
        return error("target_user_id wajib diisi", 400)

    # Pastikan target ada di family yang sama
    try:
        targets = sb_get("users", [
            ("select",    "id,username,display_name,role"),
            ("id",        f"eq.{target_user_id}"),
            ("family_id", f"eq.{family_id}"),
            ("limit",     "1"),
        ])
        if not targets:
            return error("User tidak ditemukan di keluarga ini", 404)
        target = targets[0]
    except Exception as e:
        return error(str(e), 500)

    # Buat token undangan
    token = gen_token(48)
    try:
        sb_post("invite_tokens", {
            "user_id":    target_user_id,
            "token":      token,
            "used":       False,
            "expires_at": expires_invite(),
        })
    except Exception as e:
        return error(f"Gagal buat token: {e}", 500)

    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    invite_url = f"{public_url}/join?token={token}" if public_url else f"/join?token={token}"

    return json_response({
        "ok":           True,
        "token":        token,
        "invite_url":   invite_url,
        "display_name": target["display_name"],
        "username":     target["username"],
        "expires_days": 7,
    })
