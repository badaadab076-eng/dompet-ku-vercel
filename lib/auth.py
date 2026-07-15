"""
Shared auth helper untuk semua API functions Vercel.
"""
import os, bcrypt, secrets, string, time
from datetime import datetime, timezone, timedelta
from lib.supabase import sb_get, sb_post, sb_patch

SESSION_COOKIE = "dompetku_session"
SESSION_DAYS   = 30
MIN_PASS_LEN   = 6
INVITE_DAYS    = 7

# ── Rate limiter ──────────────────────────────────────────────────────────────
_login_attempts = {}
RATE_LIMIT_MAX    = 5
RATE_LIMIT_WINDOW = 900  # 15 menit

def _get_ip(request):
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "unknown"

def is_rate_limited(ip):
    now     = time.time()
    window  = now - RATE_LIMIT_WINDOW
    attempts = [t for t in _login_attempts.get(ip, []) if t > window]
    _login_attempts[ip] = attempts
    return len(attempts) >= RATE_LIMIT_MAX

def record_failed(ip):
    if ip not in _login_attempts: _login_attempts[ip] = []
    _login_attempts[ip].append(time.time())

def clear_attempts(ip):
    _login_attempts.pop(ip, None)

# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(plain):
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def verify_password(plain, hashed):
    try:    return bcrypt.checkpw(plain.encode(), hashed.encode())
    except: return False

# ── Token helpers ─────────────────────────────────────────────────────────────

def gen_token(length=64):
    return secrets.token_urlsafe(length)

def gen_family_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))

def now_utc():
    return datetime.now(timezone.utc)

def expires_session():
    return (now_utc() + timedelta(days=SESSION_DAYS)).isoformat()

def expires_invite():
    return (now_utc() + timedelta(days=INVITE_DAYS)).isoformat()

# ── HTTPS detection ───────────────────────────────────────────────────────────

def is_https(request):
    # Di Vercel selalu HTTPS
    if os.environ.get("VERCEL"): return True
    proto = request.headers.get("x-forwarded-proto", "")
    return proto == "https"

# ── Session cache ─────────────────────────────────────────────────────────────
# Vercel functions bisa reuse instance, cache membantu kurangi query
_session_cache = {}
SESSION_CACHE_TTL = 300  # 5 menit

def cache_get(token):
    entry = _session_cache.get(token)
    if not entry: return None, None
    user, fid, cached_at = entry
    if (now_utc() - cached_at).seconds > SESSION_CACHE_TTL:
        del _session_cache[token]; return None, None
    return user, fid

def cache_set(token, user, family_id):
    if len(_session_cache) > 500:
        oldest = sorted(_session_cache.items(), key=lambda x: x[1][2])[:100]
        for k, _ in oldest: del _session_cache[k]
    _session_cache[token] = (user, family_id, now_utc())

def cache_invalidate(token):
    _session_cache.pop(token, None)

# ── Get session dari cookie ───────────────────────────────────────────────────

def get_session(request):
    """Ambil (user, family_id) dari cookie session. Return (None, None) jika invalid."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token: return None, None

    # Cek cache dulu
    u, fid = cache_get(token)
    if u: return u, fid

    try:
        rows = sb_get("sessions", [
            ("select",  "user_id,family_id,expires_at"),
            ("token",   f"eq.{token}"),
            ("limit",   "1"),
        ])
        if not rows: return None, None
        sess = rows[0]
        exp  = datetime.fromisoformat(sess["expires_at"].replace("Z", "+00:00"))
        if now_utc() > exp: return None, None

        users = sb_get("users", [
            ("select", "id,family_id,username,display_name,role,telegram_id"),
            ("id",     f"eq.{sess['user_id']}"),
            ("limit",  "1"),
        ])
        if not users: return None, None
        user = users[0]
        cache_set(token, user, sess["family_id"])
        return user, sess["family_id"]
    except Exception as e:
        print(f"[auth] get_session error: {e}")
        return None, None

# ── Helper: buat session cookie ───────────────────────────────────────────────

def create_session(user_id, family_id):
    """Buat session baru di DB, return token."""
    token = gen_token()
    sb_post("sessions", {
        "user_id":    user_id,
        "family_id":  family_id,
        "token":      token,
        "expires_at": expires_session(),
    })
    return token

# ── Helper: ambil info keluarga ───────────────────────────────────────────────

def get_family_info(family_id):
    try:
        rows = sb_get("families", [
            ("select", "name,code"),
            ("id",     f"eq.{family_id}"),
            ("limit",  "1"),
        ])
        if rows: return rows[0]["name"], rows[0]["code"]
    except: pass
    return "Keluarga", ""
