"""DELETE + PUT /api/transactions/[id]"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_patch, sb_delete
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    # Ambil ID dari path parameter atau query string
    tx_id = (request.query.get("id")
             or request.args.get("id")
             or getattr(request, "path_params", {}).get("id"))
    if not tx_id:
        # Coba parse dari URL path: /api/transactions/123
        path = getattr(request, "path", "") or ""
        parts = [p for p in path.split("/") if p]
        if parts:
            tx_id = parts[-1]
    if not tx_id:
        return error("ID transaksi wajib", 400)

    if request.method == "DELETE":
        return _delete(tx_id, family_id)
    elif request.method == "PUT":
        return _update(request, tx_id, family_id)
    else:
        return error("Method not allowed", 405)


def _delete(tx_id, family_id):
    try:
        sb_delete("transactions", {
            "id":        f"eq.{tx_id}",
            "family_id": f"eq.{family_id}",
        })
        return json_response({"deleted": tx_id})
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _update(request, tx_id, family_id):
    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    if not data:
        return error("Tidak ada data", 400)

    try:
        patch_data = {}
        if "type"     in data: patch_data["type"]        = data["type"]
        if "amount"   in data: patch_data["amount"]      = int(data["amount"])
        if "desc"     in data: patch_data["description"] = str(data["desc"]).strip()
        if "category" in data: patch_data["category"]    = data["category"]
        if "member"   in data: patch_data["member"]      = data["member"]
        if "date"     in data: patch_data["date"]        = data["date"]

        res = sb_patch("transactions",
                       {"id": f"eq.{tx_id}", "family_id": f"eq.{family_id}"},
                       patch_data)
        tx = (res[0] if isinstance(res, list) else res) or {}
        if "description" in tx:
            tx["desc"] = tx.pop("description")
        return json_response(tx)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
