"""GET + PUT /api/settings"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post, sb_patch, sb_upsert
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    if request.method == "GET":
        return _get_settings(family_id)
    elif request.method == "PUT":
        return _update_settings(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _get_settings(family_id):
    try:
        sdata = sb_get("settings", [
            ("select",    "key,value"),
            ("family_id", f"eq.{family_id}"),
        ])
        mdata = sb_get("users", [
            ("select",    "display_name,role"),
            ("family_id", f"eq.{family_id}"),
            ("order",     "created_at"),
        ])
        cfg  = {r["key"]: r["value"] for r in sdata}
        mems = [r["display_name"] for r in mdata]
        return json_response({"settings": cfg, "members": mems})
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _update_settings(request, user, family_id):
    if user.get("role") != "admin":
        return error("Hanya admin yang bisa ubah settings", 403)

    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    try:
        if "settings" in data:
            # Coba upsert dulu
            try:
                payload = [
                    {"family_id": family_id, "key": k, "value": str(v)}
                    for k, v in data["settings"].items()
                ]
                sb_upsert("settings", payload)
            except Exception:
                # Fallback: patch tiap key satu per satu
                for key, value in data["settings"].items():
                    existing = sb_get("settings", [
                        ("key",       f"eq.{key}"),
                        ("family_id", f"eq.{family_id}"),
                    ])
                    if existing:
                        sb_patch("settings",
                                 {"key": f"eq.{key}", "family_id": f"eq.{family_id}"},
                                 {"value": str(value)})
                    else:
                        sb_post("settings", {"family_id": family_id, "key": key, "value": str(value)})
        return json_response({"ok": True})
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
