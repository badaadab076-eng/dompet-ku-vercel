"""DELETE /api/private/transactions/[id]"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from lib.supabase import sb_delete
from lib.auth import get_session
from lib.response import json_response, error

def handler(request, response):
    if request.method != "DELETE":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    # Ambil ID dari path parameter atau query string
    note_id = (request.query.get("id")
               or request.args.get("id")
               or getattr(request, "path_params", {}).get("id"))
    if not note_id:
        path = getattr(request, "path", "") or ""
        parts = [p for p in path.split("/") if p]
        if parts:
            note_id = parts[-1]
    if not note_id:
        return error("ID catatan wajib", 400)

    try:
        sb_delete("private_notes", {
            "id":       f"eq.{note_id}",
            "owner_id": f"eq.{user['id']}",
        })
        return json_response({"deleted": note_id})
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
