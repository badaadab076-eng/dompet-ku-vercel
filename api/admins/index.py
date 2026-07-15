"""GET + PUT /api/admins"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_patch
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    if request.method == "GET":
        return _get_admins(family_id)
    elif request.method == "PUT":
        return _set_admins(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _get_admins(family_id):
    try:
        rows = sb_get("users", [
            ("select",    "display_name"),
            ("family_id", f"eq.{family_id}"),
            ("role",      "eq.admin"),
        ])
        return json_response([r["display_name"] for r in rows])
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _set_admins(request, user, family_id):
    if user.get("role") != "admin":
        return error("Hanya admin yang bisa ubah role", 403)

    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    admins = data.get("admins", [])

    try:
        all_users = sb_get("users", [
            ("select",    "id,display_name"),
            ("family_id", f"eq.{family_id}"),
        ])
        for u in all_users:
            new_role = "admin" if u["display_name"] in admins else "member"
            sb_patch("users", {"id": f"eq.{u['id']}"}, {"role": new_role})
        return json_response({"ok": True})
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
