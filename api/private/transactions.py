"""GET + POST /api/private/transactions"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json, calendar
from datetime import date
from lib.supabase import sb_get, sb_post
from lib.auth import get_session
from lib.response import json_response, error

def today():
    return date.today().isoformat()

def handler(request, response):
    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    if request.method == "GET":
        return _get_private(request, user, family_id)
    elif request.method == "POST":
        return _add_private(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _get_private(request, user, family_id):
    owner_id = user["id"]
    month    = request.args.get("month")

    try:
        params = [
            ("select",    "*"),
            ("owner_id",  f"eq.{owner_id}"),
            ("family_id", f"eq.{family_id}"),
            ("order",     "date.desc"),
        ]
        if month:
            y, m = month.split("-")
            last = calendar.monthrange(int(y), int(m))[1]
            params.append(("date", f"gte.{month}-01"))
            params.append(("date", f"lte.{month}-{last:02d}"))

        rows = sb_get("private_notes", params)
        return json_response(rows)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _add_private(request, user, family_id):
    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    if not data:
        return error("Tidak ada data", 400)
    if not all(k in data for k in ["type", "amount", "desc", "category"]):
        return error("Data tidak lengkap: type, amount, desc, category wajib ada", 400)

    try:
        row = {
            "family_id": family_id,
            "owner_id":  user["id"],
            "type":      data["type"],
            "amount":    int(data["amount"]),
            "note_desc": str(data["desc"]).strip(),
            "category":  data["category"],
            "date":      data.get("date", today()),
            "source":    data.get("source", "web"),
        }
        res = sb_post("private_notes", row)
        return json_response(res[0] if isinstance(res, list) else res, 201)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
