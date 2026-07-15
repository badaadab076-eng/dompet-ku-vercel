"""POST /api/auth/register"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.supabase import sb_get, sb_post
from lib.auth import (hash_password, gen_token, gen_family_code,
                      expires_session, create_session, get_family_info, is_https)
from lib.response import json_response, error, set_cookie_header

MIN_PASS_LEN = 6
SESSION_DAYS = 30

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    try:
        body = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    family_name  = str(body.get("family_name",  "")).strip()
    username     = str(body.get("username",     "")).strip().lower()
    display_name = str(body.get("display_name", "")).strip()
    password     = str(body.get("password",     "")).strip()

    # Validasi input
    errors = []
    if not family_name:  errors.append("Nama keluarga wajib diisi")
    if not username:     errors.append("Username wajib diisi")
    if not display_name: errors.append("Nama tampil wajib diisi")
    if len(password) < MIN_PASS_LEN:
        errors.append(f"Password minimal {MIN_PASS_LEN} karakter")
    if not username.replace("_", "").replace("-", "").isalnum():
        errors.append("Username hanya boleh huruf, angka, - dan _")
    if errors:
        return error("; ".join(errors), 400)

    # Cek username sudah ada
    try:
        existing = sb_get("users", [("select", "id"), ("username", f"eq.{username}"), ("limit", "1")])
        if existing:
            return error("Username sudah digunakan, pilih yang lain", 409)
    except Exception as e:
        return error(f"Gagal cek username: {e}", 500)

    # Buat keluarga baru
    try:
        for _ in range(10):
            code = gen_family_code()
            exist_code = sb_get("families", [("select", "id"), ("code", f"eq.{code}"), ("limit", "1")])
            if not exist_code:
                break
        family_res = sb_post("families", {"name": family_name, "code": code})
        family     = family_res[0] if isinstance(family_res, list) else family_res
        family_id  = family["id"]
    except Exception as e:
        return error(f"Gagal buat keluarga: {e}", 500)

    # Buat user admin
    try:
        pw_hash  = hash_password(password)
        user_res = sb_post("users", {
            "family_id":     family_id,
            "username":      username,
            "password_hash": pw_hash,
            "display_name":  display_name,
            "role":          "admin",
        })
        user = user_res[0] if isinstance(user_res, list) else user_res
    except Exception as e:
        return error(f"Gagal buat akun: {e}", 500)

    # Buat kategori default
    try:
        default_cats = [
            {"name": "Makanan & Minuman", "color": "#1D9E75", "budget": 2000000, "icon": "tools-kitchen-2"},
            {"name": "Transportasi",      "color": "#BA7517", "budget": 1600000, "icon": "car"},
            {"name": "Tagihan & Utilitas","color": "#378ADD", "budget": 2000000, "icon": "bolt"},
            {"name": "Belanja",           "color": "#D85A30", "budget": 1800000, "icon": "shopping-cart"},
            {"name": "Hiburan",           "color": "#7F77DD", "budget":  700000, "icon": "device-tv"},
            {"name": "Kesehatan",         "color": "#D4537E", "budget": 1000000, "icon": "heart"},
            {"name": "Pendidikan",        "color": "#639922", "budget":  600000, "icon": "school"},
            {"name": "Tabungan",          "color": "#0F6E56", "budget": 2000000, "icon": "piggy-bank"},
            {"name": "Gaji",              "color": "#0F6E56", "budget":       0, "icon": "cash"},
            {"name": "Freelance",         "color": "#3C3489", "budget":       0, "icon": "briefcase"},
            {"name": "Lainnya",           "color": "#888780", "budget":  500000, "icon": "dots"},
        ]
        for cat in default_cats:
            cat["family_id"] = family_id
            sb_post("categories", cat)
    except Exception as e:
        print(f"[register] Warning: gagal buat kategori default: {e}")

    # Buat settings default
    try:
        for s in [
            {"family_id": family_id, "key": "family_name",      "value": family_name},
            {"family_id": family_id, "key": "currency",         "value": "Rp"},
            {"family_id": family_id, "key": "budget_alert_pct", "value": "80"},
        ]:
            sb_post("settings", s)
    except Exception as e:
        print(f"[register] Warning: gagal buat settings default: {e}")

    # Buat session
    try:
        token = create_session(user["id"], family_id)
    except Exception as e:
        return error(f"Gagal buat session: {e}", 500)

    secure = is_https(request)
    return json_response(
        {
            "ok": True,
            "user": {
                "id":           user["id"],
                "username":     username,
                "display_name": display_name,
                "role":         "admin",
                "family_id":    family_id,
                "family_name":  family_name,
                "family_code":  code,
            }
        },
        201,
        {"Set-Cookie": set_cookie_header(token, days=SESSION_DAYS, secure=secure)}
    )
