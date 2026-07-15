"""
Shared Supabase REST helper untuk semua API functions.
"""
import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

def _request(method, table, params=None, json_data=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    kwargs = {"headers": SB_HEADERS, "timeout": 10}
    if params:    kwargs["params"] = params
    if json_data: kwargs["json"]   = json_data
    try:
        r = method(url, **kwargs)
    except requests.exceptions.Timeout:
        r = method(url, **kwargs)
    if not r.ok:
        try:    detail = r.json().get("message", r.text[:200])
        except: detail = r.text[:200]
        raise Exception(f"Supabase {r.status_code}: {detail}")
    return r

def sb_get(table, params=None):
    return _request(requests.get, table, params=params).json()

def sb_post(table, data):
    return _request(requests.post, table, json_data=data).json()

def sb_patch(table, filters, data):
    return _request(requests.patch, table, params=filters, json_data=data).json()

def sb_delete(table, params):
    _request(requests.delete, table, params=params)
    return True

def sb_upsert(table, data):
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(url, headers=headers, json=data, timeout=10)
    if not r.ok:
        raise Exception(f"Supabase upsert {r.status_code}: {r.text[:200]}")
    return r.json()
