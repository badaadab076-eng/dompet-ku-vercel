"""GET /api/auth/me"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lib.auth import get_session, get_family_info
from lib.response import json_response, error

def handler(request, response):
    if request.method != "GET":
        return error("Method not allowed", 405)

    user, family_id = get_session(request)
    if not user:
        return json_response({"logged_in": False}, 401)

    family_name, family_code = get_family_info(family_id)

    return json_response({
        "logged_in":    True,
        "id":           user["id"],
        "username":     user["username"],
        "display_name": user["display_name"],
        "role":         user["role"],
        "family_id":    family_id,
        "family_name":  family_name,
        "family_code":  family_code,
    })
