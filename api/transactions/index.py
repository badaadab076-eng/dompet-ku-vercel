"""GET + POST /api/transactions"""
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
        return _get_transactions(request, family_id)
    elif request.method == "POST":
        return _add_transaction(request, user, family_id)
    else:
        return error("Method not allowed", 405)


def _get_transactions(request, family_id):
    month  = request.args.get("month")
    member = request.args.get("member")
    ttype  = request.args.get("type")

    try:
        params = [
            ("select",    "*"),
            ("order",     "date.desc"),
            ("family_id", f"eq.{family_id}"),
        ]
        if month:
            y, m = month.split("-")
            last = calendar.monthrange(int(y), int(m))[1]
            params.append(("date", f"gte.{month}-01"))
            params.append(("date", f"lte.{month}-{last:02d}"))
        if member and member != "Semua":
            params.append(("member", f"eq.{member}"))
        if ttype:
            params.append(("type", f"eq.{ttype}"))

        txs = sb_get("transactions", params)
        for t in txs:
            if "description" in t:
                t["desc"] = t.pop("description")
        return json_response(txs)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)


def _add_transaction(request, user, family_id):
    try:
        data = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    if not data:
        return error("Tidak ada data", 400)
    if not all(k in data for k in ["type", "amount", "desc", "category", "member"]):
        return error("Data tidak lengkap: type, amount, desc, category, member wajib ada", 400)
    if data["type"] not in ("inc", "exp"):
        return error("type harus 'inc' atau 'exp'", 400)
    try:
        amount = int(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return error("amount harus angka positif", 400)
    if not str(data["desc"]).strip():
        return error("desc tidak boleh kosong", 400)

    try:
        res = sb_post("transactions", {
            "family_id":   family_id,
            "type":        data["type"],
            "amount":      amount,
            "description": str(data["desc"]).strip(),
            "category":    data["category"],
            "member":      data["member"],
            "date":        data.get("date", today()),
            "source":      data.get("source", "web"),
        })
        tx = res[0] if isinstance(res, list) else res
        if "description" in tx:
            tx["desc"] = tx.pop("description")
        return json_response(tx, 201)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)
