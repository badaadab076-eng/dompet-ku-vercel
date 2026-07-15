"""GET /api/private/summary"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import calendar
from datetime import date
from lib.supabase import sb_get
from lib.auth import get_session
from lib.response import json_response, error

def today():
    return date.today().isoformat()

def handler(request, response):
    if request.method != "GET":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return error("Tidak terautentikasi", 401)

    month    = request.args.get("month", today()[:7])
    owner_id = user["id"]

    try:
        y, m = month.split("-")
        last = calendar.monthrange(int(y), int(m))[1]
        rows = sb_get("private_notes", [
            ("select",    "type,amount"),
            ("owner_id",  f"eq.{owner_id}"),
            ("family_id", f"eq.{family_id}"),
            ("date",      f"gte.{month}-01"),
            ("date",      f"lte.{month}-{last:02d}"),
        ])
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)

    income  = sum(r["amount"] for r in rows if r["type"] == "inc")
    expense = sum(r["amount"] for r in rows if r["type"] == "exp")

    return json_response({
        "month":    month,
        "income":   income,
        "expense":  expense,
        "balance":  income - expense,
        "tx_count": len(rows),
    })
