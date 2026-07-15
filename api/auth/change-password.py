"""POST /api/auth/change-password"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_patch
from lib.auth import get_session, hash_password, verify_password
from lib.response import json_response, error

MIN_PASS_LEN = 6

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    try:
        body = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    new_password = str(body.get("new_password", "")).strip()
    target_id    = body.get("target_user_id")

    if len(new_password) < MIN_PASS_LEN:
        return error(f"Password baru minimal {MIN_PASS_LEN} karakter", 400)

    # Ganti password sendiri — wajib verifikasi password lama
    if not target_id or target_id == user["id"]:
        old_password = str(body.get("old_password", "")).strip()
        # Ambil password_hash user dari DB (mungkin tidak ada di session cache)
        try:
            users = sb_get("users", [
                ("select", "id,password_hash"),
                ("id",     f"eq.{user['id']}"),
                ("limit",  "1"),
            ])
            if not users:
                return error("User tidak ditemukan", 404)
            pw_hash_current = users[0]["password_hash"]
        except Exception as e:
            return error(str(e), 500)

        if not verify_password(old_password, pw_hash_current):
            return error("Password lama salah", 401)
        uid = user["id"]
    else:
        # Admin reset password anggota lain
        if user.get("role") != "admin":
            return error("Hanya admin yang bisa reset password anggota", 403)
        try:
            targets = sb_get("users", [
                ("select",    "id,family_id"),
                ("id",        f"eq.{target_id}"),
                ("family_id", f"eq.{family_id}"),
                ("limit",     "1"),
            ])
            if not targets:
                return error("User tidak ditemukan", 404)
        except Exception as e:
            return error(str(e), 500)
        uid = target_id

    try:
        pw_hash = hash_password(new_password)
        sb_patch("users", {"id": f"eq.{uid}"}, {"password_hash": pw_hash})
        return json_response({"ok": True, "message": "Password berhasil diubah"})
    except Exception as e:
        return error(str(e), 500)
