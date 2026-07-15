"""
Helper untuk membuat response JSON standar di Vercel Python functions.
"""
import json
from http.server import BaseHTTPRequestHandler

def json_response(data, status=200, headers=None):
    """Buat response dict yang kompatibel dengan Vercel."""
    h = {"Content-Type": "application/json"}
    if headers: h.update(headers)
    return {
        "statusCode": status,
        "headers":    h,
        "body":       json.dumps(data, ensure_ascii=False),
    }

def error(message, status=400):
    return json_response({"error": message}, status)

def ok(data=None, status=200):
    if data is None: data = {"ok": True}
    return json_response(data, status)

def set_cookie_header(token, days=30, secure=True):
    """Buat Set-Cookie header string untuk session."""
    max_age = days * 86400
    flags   = f"Max-Age={max_age}; HttpOnly; SameSite=Lax; Path=/"
    if secure: flags += "; Secure"
    return f"dompetku_session={token}; {flags}"

def clear_cookie_header():
    return "dompetku_session=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/"
