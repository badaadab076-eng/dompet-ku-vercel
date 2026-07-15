"""PATCH /api/categories/[name]"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_patch
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    if request.method != "PATCH":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    # Ambil name dari path parameter
    cat_name = (request.query.get("name")
                or request.args.get("name")
                or getattr(request, "path_params", {}).get("name"))
    if not cat_name:
        path = getattr(request, "path", "") or ""
        parts = [p for p in path.split("/") if p]
        if parts:
            cat_name = parts[-1]
    if not cat_name:
        return error("Nama kategori wajib", 400)

    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    if data is None:
        return error("Tidak ada data", 400)

    try:
        patch_data = {"budget": int(data.get("budget", 0))}
        if "color" in data:
            patch_data["color"] = data["color"]

        res = sb_patch("categories",
                       {"name": f"eq.{cat_name}", "family_id": f"eq.{family_id}"},
                       patch_data)
        result = (res[0] if isinstance(res, list) and res else {"ok": True})
        return json_response(result)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
