"""GET + POST /api/auth/members"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post
from lib.auth import get_session, hash_password
from lib.response import json_response, error

MIN_PASS_LEN = 6

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    if request.method == "GET":
        return _list_members(family_id)
    elif request.method == "POST":
        return _add_member(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _list_members(family_id):
    try:
        members = sb_get("users", [
            ("select",    "id,username,display_name,role,telegram_id,created_at"),
            ("family_id", f"eq.{family_id}"),
            ("order",     "created_at"),
        ])
        return json_response(members)
    except Exception as e:
        return error(str(e), 500)


def _add_member(request, user, family_id):
    if user.get("role") != "admin":
        return error("Hanya admin yang bisa menambah anggota", 403)

    try:
        body = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    username     = str(body.get("username",     "")).strip().lower()
    display_name = str(body.get("display_name", "")).strip()
    password     = str(body.get("password",     "")).strip()
    role         = body.get("role", "member")

    errors = []
    if not username:     errors.append("Username wajib diisi")
    if not display_name: errors.append("Nama tampil wajib diisi")
    if len(password) < MIN_PASS_LEN:
        errors.append(f"Password minimal {MIN_PASS_LEN} karakter")
    if role not in ("admin", "member"):
        errors.append("Role harus 'admin' atau 'member'")
    if errors:
        return error("; ".join(errors), 400)

    # Cek username unik global
    try:
        existing = sb_get("users", [("select", "id"), ("username", f"eq.{username}"), ("limit", "1")])
        if existing:
            return error("Username sudah digunakan", 409)
    except Exception as e:
        return error(str(e), 500)

    try:
        pw_hash  = hash_password(password)
        user_res = sb_post("users", {
            "family_id":     family_id,
            "username":      username,
            "password_hash": pw_hash,
            "display_name":  display_name,
            "role":          role,
        })
        new_user = user_res[0] if isinstance(user_res, list) else user_res
        return json_response({
            "ok": True,
            "user": {
                "id":           new_user["id"],
                "username":     username,
                "display_name": display_name,
                "role":         role,
            }
        }, 201)
    except Exception as e:
        return error(str(e), 500)
