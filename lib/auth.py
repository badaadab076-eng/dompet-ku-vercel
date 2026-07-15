"""
Shared auth helper — dipakai oleh api/index.py (Vercel Flask app).
Menggunakan flask.request dari app context yang sudah aktif.
"""
import os, bcrypt, secrets, string, time
from datetime import datetime, timezone, timedelta
from flask import request, jsonify, make_response
from lib.supabase import sb_get, sb_post, sb_patch

SESSION_COOKIE = "dompetku_session"
SESSION_DAYS   = 30
MIN_PASS_LEN   = 6
INVITE_DAYS    = 7

# ── Rate limiter ──────────────────────────────────────────────────────────────
_login_attempts   = {}
RATE_LIMIT_MAX    = 5
RATE_LIMIT_WINDOW = 900

def _get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

def _is_rate_limited(ip):
    now = time.time(); window = now - RATE_LIMIT_WINDOW
    attempts = [t for t in _login_attempts.get(ip, []) if t > window]
    _login_attempts[ip] = attempts
    return len(attempts) >= RATE_LIMIT_MAX

def _record_failed_attempt(ip):
    if ip not in _login_attempts: _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())
    if len(_login_attempts) > 5000: _login_attempts.clear()

def _clear_attempts(ip):
    _login_attempts.pop(ip, None)

# ── Session cache ─────────────────────────────────────────────────────────────
_session_cache    = {}
SESSION_CACHE_TTL = 300

def _cache_get(token):
    entry = _session_cache.get(token)
    if not entry: return None, None
    user, fid, cached_at = entry
    if (datetime.now(timezone.utc) - cached_at).seconds > SESSION_CACHE_TTL:
        del _session_cache[token]; return None, None
    return user, fid

def _cache_set(token, user, fid):
    if len(_session_cache) > 1000:
        oldest = sorted(_session_cache.items(), key=lambda x: x[1][2])[:200]
        for k, _ in oldest: del _session_cache[k]
    _session_cache[token] = (user, fid, datetime.now(timezone.utc))

def _cache_invalidate(token):
    _session_cache.pop(token, None)

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc)

def expires_session():
    return (now_utc() + timedelta(days=SESSION_DAYS)).isoformat()

def expires_reset():
    return (now_utc() + timedelta(minutes=30)).isoformat()

def hash_password(plain):
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def verify_password(plain, hashed):
    try: return bcrypt.checkpw(plain.encode(), hashed.encode())
    except: return False

def gen_token(length=64):
    return secrets.token_urlsafe(length)

def gen_family_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))

def _is_https():
    if os.environ.get("VERCEL") or os.environ.get("RAILWAY_ENVIRONMENT"): return True
    proto = request.headers.get("X-Forwarded-Proto", "")
    if proto == "https": return True
    pub = os.environ.get("PUBLIC_URL", "")
    return pub.startswith("https://")

# ── Session ───────────────────────────────────────────────────────────────────

def get_current_session(sb_get_fn):
    token = request.cookies.get(SESSION_COOKIE)
    if not token: return None, None
    u, fid = _cache_get(token)
    if u: return u, fid
    try:
        rows = sb_get_fn("sessions",[("select","user_id,family_id,expires_at"),("token",f"eq.{token}"),("limit","1")])
        if not rows: return None, None
        sess = rows[0]
        exp  = datetime.fromisoformat(sess["expires_at"].replace("Z","+00:00"))
        if now_utc() > exp: return None, None
        users = sb_get_fn("users",[("select","id,family_id,username,display_name,role,telegram_id"),
                                   ("id",f"eq.{sess['user_id']}"),("limit","1")])
        if not users: return None, None
        user = users[0]; fid = sess["family_id"]
        _cache_set(token, user, fid)
        return user, fid
    except Exception as e:
        print(f"[auth] get_current_session: {e}")
        return None, None

def _set_session_cookie(resp, token):
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS*86400,
                    httponly=True, samesite="Lax", secure=_is_https())

def _get_family_info(family_id):
    try:
        fam = sb_get("families",[("select","name,code"),("id",f"eq.{family_id}"),("limit","1")])
        if fam: return fam[0]["name"], fam[0]["code"]
    except: pass
    return "Keluarga", ""


# ── Endpoints (dipanggil dari api/index.py) ───────────────────────────────────

def register(sb_get_fn, sb_post_fn):
    data = request.get_json(silent=True) or {}
    family_name  = str(data.get("family_name","")).strip()
    username     = str(data.get("username","")).strip().lower()
    display_name = str(data.get("display_name","")).strip()
    password     = str(data.get("password","")).strip()
    errs = []
    if not family_name:  errs.append("Nama keluarga wajib")
    if not username:     errs.append("Username wajib")
    if not display_name: errs.append("Nama tampil wajib")
    if len(password) < MIN_PASS_LEN: errs.append(f"Password min {MIN_PASS_LEN} karakter")
    if not username.replace("_","").replace("-","").isalnum(): errs.append("Username tidak valid")
    if errs: return jsonify({"error":"; ".join(errs)}), 400
    try:
        if sb_get_fn("users",[("select","id"),("username",f"eq.{username}"),("limit","1")]):
            return jsonify({"error":"Username sudah digunakan"}), 409
        for _ in range(10):
            code = gen_family_code()
            if not sb_get_fn("families",[("select","id"),("code",f"eq.{code}"),("limit","1")]): break
        fam = sb_get_fn.__self__ if hasattr(sb_get_fn,'__self__') else None
        family_res = sb_post_fn("families",{"name":family_name,"code":code})
        family     = family_res[0] if isinstance(family_res,list) else family_res
        family_id  = family["id"]
        user_res   = sb_post_fn("users",{"family_id":family_id,"username":username,
                     "password_hash":hash_password(password),"display_name":display_name,"role":"admin"})
        user = user_res[0] if isinstance(user_res,list) else user_res
        for cat in [
            {"name":"Makanan & Minuman","color":"#1D9E75","budget":2000000,"icon":"tools-kitchen-2"},
            {"name":"Transportasi","color":"#BA7517","budget":1600000,"icon":"car"},
            {"name":"Tagihan & Utilitas","color":"#378ADD","budget":2000000,"icon":"bolt"},
            {"name":"Belanja","color":"#D85A30","budget":1800000,"icon":"shopping-cart"},
            {"name":"Hiburan","color":"#7F77DD","budget":700000,"icon":"device-tv"},
            {"name":"Kesehatan","color":"#D4537E","budget":1000000,"icon":"heart"},
            {"name":"Pendidikan","color":"#639922","budget":600000,"icon":"school"},
            {"name":"Tabungan","color":"#0F6E56","budget":2000000,"icon":"piggy-bank"},
            {"name":"Gaji","color":"#0F6E56","budget":0,"icon":"cash"},
            {"name":"Freelance","color":"#3C3489","budget":0,"icon":"briefcase"},
            {"name":"Lainnya","color":"#888780","budget":500000,"icon":"dots"},
        ]:
            cat["family_id"] = family_id
            try: sb_post_fn("categories", cat)
            except: pass
        for s in [{"family_id":family_id,"key":"family_name","value":family_name},
                  {"family_id":family_id,"key":"currency","value":"Rp"},
                  {"family_id":family_id,"key":"budget_alert_pct","value":"80"}]:
            try: sb_post_fn("settings", s)
            except: pass
        token = gen_token()
        sb_post_fn("sessions",{"user_id":user["id"],"family_id":family_id,"token":token,"expires_at":expires_session()})
    except Exception as e:
        return jsonify({"error":str(e)}), 500
    resp = make_response(jsonify({"ok":True,"user":{"id":user["id"],"username":username,
        "display_name":display_name,"role":"admin","family_id":family_id,
        "family_name":family_name,"family_code":code}}), 201)
    _set_session_cookie(resp, token)
    return resp

def login(sb_get_fn, sb_post_fn):
    ip   = _get_client_ip()
    data = request.get_json(silent=True) or {}
    username = str(data.get("username","")).strip().lower()
    password = str(data.get("password","")).strip()
    if not username or not password: return jsonify({"error":"Username dan password wajib"}), 400
    if _is_rate_limited(ip): return jsonify({"error":"Terlalu banyak percobaan. Coba 15 menit lagi."}), 429
    try:
        users = sb_get_fn("users",[("select","id,family_id,username,password_hash,display_name,role"),
                                   ("username",f"eq.{username}"),("limit","1")])
        if not users: _record_failed_attempt(ip); return jsonify({"error":"Username atau password salah"}), 401
        user = users[0]
    except Exception as e: return jsonify({"error":str(e)}), 500
    if not verify_password(password, user["password_hash"]):
        _record_failed_attempt(ip); return jsonify({"error":"Username atau password salah"}), 401
    _clear_attempts(ip)
    try:
        fam = sb_get_fn("families",[("select","name,code"),("id",f"eq.{user['family_id']}"),("limit","1")])
        fname = fam[0]["name"] if fam else "Keluarga"
        fcode = fam[0]["code"] if fam else ""
        token = gen_token()
        sb_post_fn("sessions",{"user_id":user["id"],"family_id":user["family_id"],"token":token,"expires_at":expires_session()})
    except Exception as e: return jsonify({"error":str(e)}), 500
    resp = make_response(jsonify({"ok":True,"user":{"id":user["id"],"username":user["username"],
        "display_name":user["display_name"],"role":user["role"],"family_id":user["family_id"],
        "family_name":fname,"family_code":fcode}}))
    _set_session_cookie(resp, token)
    return resp

def logout(sb_get_fn, sb_delete_fn):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try: sb_delete_fn("sessions",{"token":f"eq.{token}"})
        except: pass
        _cache_invalidate(token)
    resp = make_response(jsonify({"ok":True}))
    resp.delete_cookie(SESSION_COOKIE)
    return resp

def me(sb_get_fn):
    user, fid = get_current_session(sb_get_fn)
    if not user: return jsonify({"logged_in":False}), 401
    try:
        fam = sb_get_fn("families",[("select","name,code"),("id",f"eq.{fid}"),("limit","1")])
        fname = fam[0]["name"] if fam else "Keluarga"
        fcode = fam[0]["code"] if fam else ""
    except: fname="Keluarga"; fcode=""
    return jsonify({"logged_in":True,"id":user["id"],"username":user["username"],
        "display_name":user["display_name"],"role":user["role"],"family_id":fid,
        "family_name":fname,"family_code":fcode})

def list_members(sb_get_fn):
    user, fid = get_current_session(sb_get_fn)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    try:
        members = sb_get_fn("users",[("select","id,username,display_name,role,telegram_id,created_at"),
                                     ("family_id",f"eq.{fid}"),("order","created_at")])
        return jsonify(members)
    except Exception as e: return jsonify({"error":str(e)}), 500

def add_member(sb_get_fn, sb_post_fn):
    user, fid = get_current_session(sb_get_fn)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role") != "admin": return jsonify({"error":"Hanya admin"}), 403
    data = request.get_json(silent=True) or {}
    username=str(data.get("username","")).strip().lower()
    display_name=str(data.get("display_name","")).strip()
    password=str(data.get("password","")).strip()
    role=data.get("role","member")
    if not username or not display_name or len(password)<MIN_PASS_LEN:
        return jsonify({"error":"Data tidak lengkap atau password terlalu pendek"}), 400
    try:
        if sb_get_fn("users",[("select","id"),("username",f"eq.{username}"),("limit","1")]):
            return jsonify({"error":"Username sudah digunakan"}), 409
        ur = sb_post_fn("users",{"family_id":fid,"username":username,
             "password_hash":hash_password(password),"display_name":display_name,"role":role})
        nu = ur[0] if isinstance(ur,list) else ur
        return jsonify({"ok":True,"user":{"id":nu["id"],"username":username,"display_name":display_name,"role":role}}), 201
    except Exception as e: return jsonify({"error":str(e)}), 500

def change_password(sb_get_fn, sb_patch_fn):
    user, fid = get_current_session(sb_get_fn)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    data=request.get_json(silent=True) or {}
    new_pw=str(data.get("new_password","")).strip()
    target_id=data.get("target_user_id")
    if len(new_pw)<MIN_PASS_LEN: return jsonify({"error":f"Password min {MIN_PASS_LEN} karakter"}), 400
    if not target_id or target_id==user["id"]:
        if not verify_password(str(data.get("old_password","")), user["password_hash"]):
            return jsonify({"error":"Password lama salah"}), 401
        uid=user["id"]
    else:
        if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
        uid=target_id
    try:
        sb_patch_fn("users",{"id":f"eq.{uid}"},{"password_hash":hash_password(new_pw)})
        return jsonify({"ok":True,"message":"Password berhasil diubah"})
    except Exception as e: return jsonify({"error":str(e)}), 500

def request_reset(sb_get_fn, sb_post_fn):
    data=request.get_json(silent=True) or {}
    tg_id=str(data.get("telegram_id","")).strip()
    if not tg_id: return jsonify({"error":"telegram_id wajib"}), 400
    try:
        users=sb_get_fn("users",[("select","id,username"),("telegram_id",f"eq.{tg_id}"),("limit","1")])
        if not users: return jsonify({"error":"Akun tidak ditemukan"}), 404
        u=users[0]; token=gen_token(32)
        sb_post_fn("reset_tokens",{"user_id":u["id"],"token":token,"expires_at":expires_reset()})
        return jsonify({"ok":True,"token":token,"username":u["username"]})
    except Exception as e: return jsonify({"error":str(e)}), 500

def do_reset(sb_get_fn, sb_post_fn, sb_patch_fn):
    data=request.get_json(silent=True) or {}
    token=str(data.get("token","")).strip()
    new_pw=str(data.get("new_password","")).strip()
    if not token or len(new_pw)<MIN_PASS_LEN: return jsonify({"error":"Token dan password baru wajib"}), 400
    try:
        rows=sb_get_fn("reset_tokens",[("select","user_id,expires_at,used"),("token",f"eq.{token}"),("used","eq.false"),("limit","1")])
        if not rows: return jsonify({"error":"Token tidak valid"}), 400
        row=rows[0]
        exp=datetime.fromisoformat(row["expires_at"].replace("Z","+00:00"))
        if now_utc()>exp: return jsonify({"error":"Token kadaluarsa"}), 400
        sb_patch_fn("users",{"id":f"eq.{row['user_id']}"},{"password_hash":hash_password(new_pw)})
        sb_patch_fn("reset_tokens",{"token":f"eq.{token}"},{"used":True})
        return jsonify({"ok":True})
    except Exception as e: return jsonify({"error":str(e)}), 500

def link_telegram(sb_get_fn, sb_patch_fn):
    data=request.get_json(silent=True) or {}
    username=str(data.get("username","")).strip().lower()
    password=str(data.get("password","")).strip()
    tg_id=str(data.get("telegram_id","")).strip()
    if not all([username,password,tg_id]): return jsonify({"error":"Semua field wajib"}), 400
    try:
        users=sb_get_fn("users",[("select","id,password_hash,display_name,role,family_id"),("username",f"eq.{username}"),("limit","1")])
        if not users: return jsonify({"error":"Username atau password salah"}), 401
        u=users[0]
        if not verify_password(password,u["password_hash"]): return jsonify({"error":"Username atau password salah"}), 401
        sb_patch_fn("users",{"id":f"eq.{u['id']}"},{"telegram_id":tg_id})
        return jsonify({"ok":True,"display_name":u["display_name"],"role":u["role"],"family_id":u["family_id"]})
    except Exception as e: return jsonify({"error":str(e)}), 500

def generate_invite(sb_get_fn, sb_post_fn):
    user, fid = get_current_session(sb_get_fn)
    if not user: return jsonify({"error":"Tidak terautentikasi"}), 401
    if user.get("role")!="admin": return jsonify({"error":"Hanya admin"}), 403
    data=request.get_json(silent=True) or {}
    target_id=data.get("target_user_id")
    if not target_id: return jsonify({"error":"target_user_id wajib"}), 400
    try:
        targets=sb_get_fn("users",[("select","id,username,display_name"),("id",f"eq.{target_id}"),("family_id",f"eq.{fid}"),("limit","1")])
        if not targets: return jsonify({"error":"User tidak ditemukan"}), 404
        t=targets[0]; token=gen_token(48)
        from datetime import timedelta
        sb_post_fn("invite_tokens",{"user_id":target_id,"token":token,"used":False,
            "expires_at":(now_utc()+timedelta(days=INVITE_DAYS)).isoformat()})
        pub=os.environ.get("PUBLIC_URL","").rstrip("/") or os.environ.get("VERCEL_URL","")
        if pub and not pub.startswith("http"): pub="https://"+pub
        invite_url=f"{pub}/join?token={token}" if pub else f"/join?token={token}"
        return jsonify({"ok":True,"token":token,"invite_url":invite_url,
            "display_name":t["display_name"],"username":t["username"],"expires_days":INVITE_DAYS})
    except Exception as e: return jsonify({"error":str(e)}), 500

def join_via_invite(sb_get_fn, sb_patch_fn, sb_post_fn):
    data=request.get_json(silent=True) or {}
    token=str(data.get("token","")).strip()
    if not token: return jsonify({"error":"Token wajib"}), 400
    try:
        rows=sb_get_fn("invite_tokens",[("select","user_id,used,expires_at"),("token",f"eq.{token}"),("limit","1")])
        if not rows: return jsonify({"error":"Link tidak valid"}), 400
        row=rows[0]
        if row["used"]: return jsonify({"error":"Link sudah digunakan"}), 400
        exp=datetime.fromisoformat(row["expires_at"].replace("Z","+00:00"))
        if now_utc()>exp: return jsonify({"error":"Link kadaluarsa"}), 400
        users=sb_get_fn("users",[("select","id,family_id,username,display_name,role"),("id",f"eq.{row['user_id']}"),("limit","1")])
        if not users: return jsonify({"error":"Akun tidak ditemukan"}), 404
        u=users[0]
        fam=sb_get_fn("families",[("select","name,code"),("id",f"eq.{u['family_id']}"),("limit","1")])
        fname=fam[0]["name"] if fam else "Keluarga"
        fcode=fam[0]["code"] if fam else ""
        sb_patch_fn("invite_tokens",{"token":f"eq.{token}"},{"used":True})
        sess_token=gen_token()
        sb_post_fn("sessions",{"user_id":u["id"],"family_id":u["family_id"],"token":sess_token,"expires_at":expires_session()})
    except Exception as e: return jsonify({"error":str(e)}), 500
    resp=make_response(jsonify({"ok":True,"first_time":True,"user":{"id":u["id"],"username":u["username"],
        "display_name":u["display_name"],"role":u["role"],"family_id":u["family_id"],
        "family_name":fname,"family_code":fcode}}))
    _set_session_cookie(resp, sess_token)
    return resp
