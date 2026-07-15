"""POST /api/auth/logout"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lib.supabase import sb_delete
from lib.auth import SESSION_COOKIE, cache_invalidate
from lib.response import json_response, clear_cookie_header

def handler(request, response):
    if request.method != "POST":
        from lib.response import error
        return error("Method not allowed", 405)

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            sb_delete("sessions", {"token": f"eq.{token}"})
        except Exception:
            pass
        cache_invalidate(token)

    return json_response(
        {"ok": True},
        200,
        {"Set-Cookie": clear_cookie_header()}
    )
