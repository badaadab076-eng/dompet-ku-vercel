"""
Dompet-KU — Vercel Serverless (Single Flask App)
Semua API routes dalam satu file untuk kompatibilitas Vercel Python.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)

from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import datetime, re, json, calendar, requests as req_lib
from pathlib import Path

from lib.supabase import sb_get, sb_post, sb_patch, sb_delete, SUPABASE_URL, SB_HEADERS
import lib.auth as _auth

app = Flask(__name__)

_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://dompet-ku-vercel.vercel.app,http://localhost:3000"
).split(",") if o.strip()]

CORS(app, supports_credentials=True, origins=_ALLOWED_ORIGINS)

@app.after_request
def add_headers(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

def today():
    return datetime.date.today().isoformat()


# ══════ AUTH ══════════════════════════════════════════════════════════════════

@app.route("/api/auth/register", methods=["POST"])
def auth_register():    return _auth.register(sb_get, sb_post)

@app.route("/api/auth/login", methods=["POST"])
def auth_login():       return _auth.login(sb_get, sb_post)

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():      return _auth.logout(sb_get, sb_delete)

@app.route("/api/auth/me", methods=["GET"])
def auth_me():          return _auth.me(sb_get)

@app.route("/api/auth/members", methods=["GET"])
def auth_list_members():return _auth.list_members(sb_get)

@app.route("/api/auth/members", methods=["POST"])
def auth_add_member():  return _auth.add_member(sb_get, sb_post)

@app.route("/api/auth/change-password", methods=["POST"])
def auth_change_password(): return _auth.change_password(sb_get, sb_patch)

@app.route("/api/auth/request-reset", methods=["POST"])
def auth_request_reset():   return _auth.request_reset(sb_get, sb_post)

@app.route("/api/auth/reset-password", methods=["POST"])
def auth_reset_password():  return _auth.do_reset(sb_get, sb_post, sb_patch)

@app.route("/api/auth/link-telegram", methods=["POST"])
def auth_link_telegram():   return _auth.link_telegram(sb_get, sb_patch)

@app.route("/api/auth/invite", methods=["POST"])
def auth_generate_invite():  return _auth.generate_invite(sb_get, sb_post)

@app.route("/api/auth/join", methods=["POST"])
def auth_join_invite():  return _auth.join_via_invite(sb_get, sb_patch, sb_post)

@app.route("/join")
def join_page():
    return send_from_directory(os.path.join(_root, "public"), "index.html")


# ══════ TRANSACTIONS ══════════════════════════════════════════════════════════

@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error": "Tidak terautentikasi"}), 401
    month=request.args.get("month"); member=request.args.get("member"); ttype=request.args.get("type")
    try:
        params=[("select","*"),("order","date.desc"),("family_id",f"eq.{family_id}")]
        if month:
            y,m=month.split("-"); last=calendar.monthrange(int(y),int(m))[1]
            params.append(("date",f"gte.{month}-01")); params.append(("date",f"lte.{month}-{last:02d}"))
        if member and member!="Semua": params.append(("member",f"eq.{member}"))
        if ttype: params.append(("type",f"eq.{ttype}"))
        txs=sb_get("transactions",params)
        for t in txs:
            if "description" in t: t["desc"]=t.pop("description")
        return jsonify(txs)
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/transactions", methods=["POST"])
def add_transaction():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    data=request.json
    if not data: return jsonify({"error":"Tidak ada data"}), 400
    if not all(k in data for k in ["type","amount","desc","category","member"]): return jsonify({"error":"Data tidak lengkap"}), 400
    if data["type"] not in ("inc","exp"): return jsonify({"error":"type harus inc/exp"}), 400
    try:
        amount=int(data["amount"])
        if amount<=0: raise ValueError
    except: return jsonify({"error":"amount harus angka positif"}), 400
    try:
        res=sb_post("transactions",{"family_id":data.get("family_id",family_id),"type":data["type"],
            "amount":amount,"description":data["desc"].strip(),"category":data["category"],
            "member":data["member"],"date":data.get("date",today()),"source":data.get("source","web")})
        tx=res[0] if isinstance(res,list) else res
        if "description" in tx: tx["desc"]=tx.pop("description")
        return jsonify(tx), 201
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def delete_transaction(tx_id):
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try: sb_delete("transactions",{"id":f"eq.{tx_id}","family_id":f"eq.{family_id}"}); return jsonify({"deleted":tx_id})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/transactions/<int:tx_id>", methods=["PUT"])
def edit_transaction(tx_id):
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    data=request.json
    if not data: return jsonify({"error":"Tidak ada data"}), 400
    try:
        p={}
        if "type"     in data: p["type"]        =data["type"]
        if "amount"   in data: p["amount"]      =int(data["amount"])
        if "desc"     in data: p["description"] =data["desc"].strip()
        if "category" in data: p["category"]    =data["category"]
        if "member"   in data: p["member"]      =data["member"]
        if "date"     in data: p["date"]        =data["date"]
        res=sb_patch("transactions",{"id":f"eq.{tx_id}","family_id":f"eq.{family_id}"},p)
        tx=(res[0] if isinstance(res,list) else res) or {}
        if "description" in tx: tx["desc"]=tx.pop("description")
        return jsonify(tx)
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/reset", methods=["POST"])
def reset_transactions():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
    try:
        all_txs=sb_get("transactions",[("select","id"),("family_id",f"eq.{family_id}")])
        if all_txs: sb_delete("transactions",{"id":f"in.({','.join(str(t['id']) for t in all_txs)})"})
        return jsonify({"ok":True,"message":f"{len(all_txs)} transaksi dihapus"})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503


# ══════ CATEGORIES ════════════════════════════════════════════════════════════

@app.route("/api/categories", methods=["GET"])
def get_categories():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try: return jsonify(sb_get("categories",[("select","*"),("order","name"),("family_id",f"eq.{family_id}")]))
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/categories", methods=["POST"])
def add_category():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
    data=request.json
    if not data or not data.get("name"): return jsonify({"error":"Nama wajib"}), 400
    try:
        res=sb_post("categories",{"family_id":family_id,"name":data["name"].strip(),
            "color":data.get("color","#888780"),"budget":int(data.get("budget",0)),"icon":data.get("icon","dots")})
        return jsonify(res[0] if isinstance(res,list) else res), 201
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/categories/<path:cat_name>", methods=["PATCH"])
def update_category(cat_name):
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    data=request.json or {}
    try:
        p={"budget":int(data.get("budget",0))}
        if data.get("color"): p["color"]=data["color"]
        res=sb_patch("categories",{"name":f"eq.{cat_name}","family_id":f"eq.{family_id}"},p)
        return jsonify(res[0] if isinstance(res,list) and res else {"ok":True})
    except Exception as e: return jsonify({"error":str(e)}), 503

# ══════ SUMMARY ═══════════════════════════════════════════════════════════════

@app.route("/api/summary")
def summary():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    month=request.args.get("month",today()[:7])
    try:
        y,m=month.split("-"); last=calendar.monthrange(int(y),int(m))[1]
        txs=sb_get("transactions",[("select","type,amount,category"),("family_id",f"eq.{family_id}"),
            ("date",f"gte.{month}-01"),("date",f"lte.{month}-{last:02d}")])
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503
    income=sum(t["amount"] for t in txs if t["type"]=="inc")
    expense=sum(t["amount"] for t in txs if t["type"]=="exp")
    by_cat={}
    for t in txs:
        if t["type"]=="exp": by_cat[t["category"]]=by_cat.get(t["category"],0)+t["amount"]
    top_cats=sorted(by_cat.items(),key=lambda x:x[1],reverse=True)
    try:
        cats=sb_get("categories",[("select","name,budget"),("family_id",f"eq.{family_id}")])
        cat_budgets={c["name"]:c["budget"] for c in cats}
    except: cat_budgets={}
    budget_status=[]
    for name,spent in top_cats:
        budget=cat_budgets.get(name,0); pct=round(spent/budget*100) if budget>0 else 0
        budget_status.append({"category":name,"spent":spent,"budget":budget,"pct":pct,"over":pct>=100,"alert":pct>=80})
    return jsonify({"month":month,"income":income,"expense":expense,"balance":income-expense,
        "savings_rate":round((income-expense)/income*100,1) if income>0 else 0,
        "top_categories":top_cats[:7],"budget_status":budget_status,"tx_count":len(txs)})

@app.route("/api/summary/member")
def summary_per_member():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    month=request.args.get("month",today()[:7]); req_member=request.args.get("member")
    try:
        y,m=month.split("-"); last=calendar.monthrange(int(y),int(m))[1]
        params=[("select","type,amount,member"),("family_id",f"eq.{family_id}"),
                ("date",f"gte.{month}-01"),("date",f"lte.{month}-{last:02d}")]
        if user["role"]!="admin": params.append(("member",f"eq.{user['display_name']}"))
        elif req_member and req_member!="Semua": params.append(("member",f"eq.{req_member}"))
        txs=sb_get("transactions",params)
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503
    by_member={}
    for t in txs:
        n=t["member"]
        if n not in by_member: by_member[n]={"income":0,"expense":0}
        if t["type"]=="inc": by_member[n]["income"]+=t["amount"]
        else: by_member[n]["expense"]+=t["amount"]
    return jsonify({"month":month,"members":[{"member":n,"income":v["income"],"expense":v["expense"],
        "balance":v["income"]-v["expense"]} for n,v in by_member.items()]})

# ══════ SETTINGS & ADMINS ═════════════════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def get_settings():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try:
        sdata=sb_get("settings",[("select","key,value"),("family_id",f"eq.{family_id}")])
        mdata=sb_get("users",[("select","display_name,role"),("family_id",f"eq.{family_id}"),("order","created_at")])
        return jsonify({"settings":{r["key"]:r["value"] for r in sdata},"members":[r["display_name"] for r in mdata]})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/settings", methods=["PUT"])
def update_settings():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
    data=request.json
    try:
        if "settings" in data:
            upsert_headers={**SB_HEADERS,"Prefer":"resolution=merge-duplicates,return=representation"}
            payload=[{"family_id":family_id,"key":k,"value":str(v)} for k,v in data["settings"].items()]
            r=req_lib.post(f"{SUPABASE_URL}/rest/v1/settings",headers=upsert_headers,json=payload,timeout=10)
            if not r.ok:
                for key,value in data["settings"].items():
                    existing=sb_get("settings",[("key",f"eq.{key}"),("family_id",f"eq.{family_id}")])
                    if existing: sb_patch("settings",{"key":f"eq.{key}","family_id":f"eq.{family_id}"},{"value":str(value)})
                    else: sb_post("settings",{"family_id":family_id,"key":key,"value":str(value)})
        return jsonify({"ok":True})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/admins", methods=["GET"])
def get_admins():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try:
        rows=sb_get("users",[("select","display_name"),("family_id",f"eq.{family_id}"),("role","eq.admin")])
        return jsonify([r["display_name"] for r in rows])
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/admins", methods=["PUT"])
def set_admins():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
    admins=(request.json or {}).get("admins",[])
    try:
        all_users=sb_get("users",[("select","id,display_name"),("family_id",f"eq.{family_id}")])
        for u in all_users:
            sb_patch("users",{"id":f"eq.{u['id']}"},{"role":"admin" if u["display_name"] in admins else "member"})
        return jsonify({"ok":True})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503


# ══════ PRIVATE VAULT ═════════════════════════════════════════════════════════

@app.route("/api/private/transactions", methods=["GET"])
def priv_get():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    owner_id=user["id"]; month=request.args.get("month")
    try:
        params=[("select","*"),("owner_id",f"eq.{owner_id}"),("family_id",f"eq.{family_id}"),("order","date.desc")]
        if month:
            y,m=month.split("-"); last=calendar.monthrange(int(y),int(m))[1]
            params.append(("date",f"gte.{month}-01")); params.append(("date",f"lte.{month}-{last:02d}"))
        return jsonify(sb_get("private_notes",params))
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/private/transactions", methods=["POST"])
def priv_add():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    data=request.json or {}
    if not all(k in data for k in ["type","amount","desc","category"]): return jsonify({"error":"Data tidak lengkap"}), 400
    try:
        res=sb_post("private_notes",{"family_id":family_id,"owner_id":user["id"],"type":data["type"],
            "amount":int(data["amount"]),"note_desc":str(data["desc"]).strip(),"category":data["category"],
            "date":data.get("date",today()),"source":data.get("source","web")})
        return jsonify(res[0] if isinstance(res,list) else res), 201
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/private/transactions/<int:note_id>", methods=["DELETE"])
def priv_delete(note_id):
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try: sb_delete("private_notes",{"id":f"eq.{note_id}","owner_id":f"eq.{user['id']}"}); return jsonify({"deleted":note_id})
    except: return jsonify({"error":"Koneksi database bermasalah, coba lagi"}), 503

@app.route("/api/private/summary")
def priv_summary():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    month=request.args.get("month",today()[:7]); owner_id=user["id"]
    try:
        y,m=month.split("-"); last=calendar.monthrange(int(y),int(m))[1]
        rows=sb_get("private_notes",[("select","type,amount"),("owner_id",f"eq.{owner_id}"),
            ("family_id",f"eq.{family_id}"),("date",f"gte.{month}-01"),("date",f"lte.{month}-{last:02d}")])
    except: rows=[]
    income=sum(r["amount"] for r in rows if r["type"]=="inc")
    expense=sum(r["amount"] for r in rows if r["type"]=="exp")
    return jsonify({"month":month,"income":income,"expense":expense,"balance":income-expense,"tx_count":len(rows)})

@app.route("/api/private/admins")
def priv_admins():
    user, family_id = _auth.get_current_session(sb_get)
    if not user: return jsonify({"admin_ids":[],"is_admin":False})
    return jsonify({"admin_ids":[user["display_name"]],"is_admin":user["role"]=="admin","user_id":user["id"]})

# ══════ TELEGRAM WEBHOOK ══════════════════════════════════════════════════════

@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    WEBHOOK_SECRET=os.environ.get("TELEGRAM_WEBHOOK_SECRET","")
    if WEBHOOK_SECRET:
        got=request.headers.get("X-Telegram-Bot-Api-Secret-Token","")
        if got!=WEBHOOK_SECRET: return jsonify({"error":"forbidden"}), 403
    update=request.get_json(silent=True) or {}
    # ⚠️ DIPROSES SINKRON — bukan background thread.
    # Di Vercel serverless, execution dibekukan setelah response dikirim,
    # sehingga background thread tidak dijamin selesai. Sinkron lebih andal.
    # Telegram toleran menunggu response beberapa detik.
    try:
        bot_dir=os.path.join(_root,"bot"); sys.path.insert(0,bot_dir)
        import bot as tg_bot
        if "message" in update:        tg_bot.handle_message(update["message"])
        elif "callback_query" in update: tg_bot.handle_callback(update["callback_query"])
    except Exception as e:
        print(f"[Webhook] error: {e}")
    # Selalu return 200 — supaya Telegram tidak retry terus
    return jsonify({"ok":True})

# ── Setup webhook — MANUAL SEKALI, bukan otomatis tiap cold start ─────────────
# Memanggil setWebhook otomatis tiap cold start menambah latensi ~500ms.
# Panggil endpoint ini manual setelah deploy pertama atau ganti domain/token.

def _do_setup_webhook():
    token  =os.environ.get("TELEGRAM_TOKEN","")
    secret =os.environ.get("TELEGRAM_WEBHOOK_SECRET","")
    pub_url=os.environ.get("PUBLIC_URL","") or os.environ.get("VERCEL_URL","")
    if not token or not pub_url: return {"ok":False,"error":"TELEGRAM_TOKEN/PUBLIC_URL belum diset"}
    if not pub_url.startswith("http"): pub_url="https://"+pub_url
    try:
        sys.path.insert(0,os.path.join(_root,"bot"))
        import bot as tg_bot
        webhook_url=pub_url.rstrip("/")+"/api/telegram/webhook"
        payload={"url":webhook_url}
        if secret: payload["secret_token"]=secret
        result=tg_bot.tg("setWebhook",**payload)
        tg_bot.setup_commands()
        print(f"[Bot-Vercel] Webhook aktif: {webhook_url}")
        return {"ok":True,"webhook_url":webhook_url,"telegram_response":result}
    except Exception as e:
        return {"ok":False,"error":str(e)}

@app.route("/api/telegram/setup-webhook", methods=["POST"])
def setup_webhook_endpoint():
    """Panggil MANUAL (sekali saja) setelah deploy untuk daftarkan webhook."""
    setup_secret=os.environ.get("SETUP_WEBHOOK_SECRET","")
    if setup_secret and request.headers.get("X-Setup-Secret","")!=setup_secret:
        return jsonify({"error":"forbidden"}), 403
    return jsonify(_do_setup_webhook())

