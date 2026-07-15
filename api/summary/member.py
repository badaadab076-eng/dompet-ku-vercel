"""GET /api/summary/member"""
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

    month      = request.args.get("month", today()[:7])
    req_member = request.args.get("member")

    try:
        y, m = month.split("-")
        last = calendar.monthrange(int(y), int(m))[1]
        params = [
            ("select",    "type,amount,member"),
            ("family_id", f"eq.{family_id}"),
            ("date",      f"gte.{month}-01"),
            ("date",      f"lte.{month}-{last:02d}"),
        ]
        # Anggota biasa hanya lihat diri sendiri
        if user["role"] != "admin":
            params.append(("member", f"eq.{user['display_name']}"))
        elif req_member and req_member != "Semua":
            params.append(("member", f"eq.{req_member}"))

        txs = sb_get("transactions", params)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)

    by_member = {}
    for t in txs:
        mem = t["member"]
        if mem not in by_member:
            by_member[mem] = {"income": 0, "expense": 0}
        if t["type"] == "inc":
            by_member[mem]["income"] += t["amount"]
        else:
            by_member[mem]["expense"] += t["amount"]

    result = [
        {
            "member":  name,
            "income":  v["income"],
            "expense": v["expense"],
            "balance": v["income"] - v["expense"],
        }
        for name, v in by_member.items()
    ]

    return json_response({"month": month, "members": result})
