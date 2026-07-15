"""GET + POST /api/categories"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    if request.method == "GET":
        return _get_categories(family_id)
    elif request.method == "POST":
        return _add_category(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _get_categories(family_id):
    try:
        cats = sb_get("categories", [
            ("select",    "*"),
            ("order",     "name"),
            ("family_id", f"eq.{family_id}"),
        ])
        return json_response(cats)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _add_category(request, user, family_id):
    if user.get("role") != "admin":
        return error("Hanya admin yang bisa menambah kategori", 403)

    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    if not data or not data.get("name"):
        return error("Nama kategori wajib diisi", 400)

    try:
        res = sb_post("categories", {
            "family_id": family_id,
            "name":      str(data["name"]).strip(),
            "color":     data.get("color", "#888780"),
            "budget":    int(data.get("budget", 0)),
            "icon":      data.get("icon", "dots"),
        })
        cat = res[0] if isinstance(res, list) else res
        return json_response(cat, 201)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
