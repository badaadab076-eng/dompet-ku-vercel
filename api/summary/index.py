"""GET /api/summary"""
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

    month = request.args.get("month", today()[:7])

    try:
        y, m  = month.split("-")
        last  = calendar.monthrange(int(y), int(m))[1]
        params = [
            ("select",    "type,amount,category"),
            ("family_id", f"eq.{family_id}"),
            ("date",      f"gte.{month}-01"),
            ("date",      f"lte.{month}-{last:02d}"),
        ]
        txs = sb_get("transactions", params)
    except Exception as e:
        return error(f"Koneksi database bermasalah: {e}", 503)

    income  = sum(t["amount"] for t in txs if t["type"] == "inc")
    expense = sum(t["amount"] for t in txs if t["type"] == "exp")
    balance = income - expense

    # Top categories by expense
    by_cat = {}
    for t in txs:
        if t["type"] == "exp":
            by_cat[t["category"]] = by_cat.get(t["category"], 0) + t["amount"]
    top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)

    # Budget status
    try:
        cats = sb_get("categories", [
            ("select",    "name,budget"),
            ("family_id", f"eq.{family_id}"),
        ])
        cat_budgets = {c["name"]: c["budget"] for c in cats}
    except Exception:
        cat_budgets = {}

    budget_status = []
    for name, spent in top_cats:
        budget = cat_budgets.get(name, 0)
        pct    = round(spent / budget * 100) if budget > 0 else 0
        budget_status.append({
            "category": name,
            "spent":    spent,
            "budget":   budget,
            "pct":      pct,
            "over":     pct >= 100,
            "alert":    pct >= 80,
        })

    return json_response({
        "month":        month,
        "income":       income,
        "expense":      expense,
        "balance":      balance,
        "savings_rate": round(balance / income * 100, 1) if income > 0 else 0,
        "top_categories": top_cats[:7],
        "budget_status":  budget_status,
        "tx_count":       len(txs),
    })
