"""
Dompet-KU — Telegram Bot (Vercel Edition)
State disimpan di Supabase agar bisa jalan di serverless (stateless).
Optimasi: lazy import, minimal top-level code.
"""
# Import minimal di top-level untuk percepat cold start
import os, sys, re, json, logging, base64
from datetime import datetime

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)

# Lazy import — hanya load saat pertama dipakai
_requests = None
_sb_get   = None
_sb_post  = None
_sb_patch = None
_sb_delete= None
_SB_URL   = None
_SB_HDR   = None

def _get_requests():
    global _requests
    if _requests is None:
        import requests as _r; _requests = _r
    return _requests

def _init_supabase():
    global _sb_get, _sb_post, _sb_patch, _sb_delete, _SB_URL, _SB_HDR
    if _sb_get is None:
        from lib.supabase import sb_get, sb_post, sb_patch, sb_delete, SUPABASE_URL, SB_HEADERS
        _sb_get=sb_get; _sb_post=sb_post; _sb_patch=sb_patch; _sb_delete=sb_delete
        _SB_URL=SUPABASE_URL; _SB_HDR=SB_HEADERS

BOT_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_KEY   = os.environ.get("GEMINI_API_KEY", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://dompet-ku-vercel.vercel.app")
API_URL    = PUBLIC_URL.rstrip("/") + "/api"
BASE       = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ── State di Supabase (bukan memory) ─────────────────────────────────────────

def state_get(chat_id):
    _init_supabase()
    try:
        # Order by updated_at desc agar selalu ambil state terbaru
        rows = _sb_get("bot_sessions", [
            ("select","state"),
            ("chat_id",f"eq.{chat_id}"),
            ("order","updated_at.desc"),
            ("limit","1")
        ])
        return rows[0]["state"] if rows else {}
    except: return {}

def state_set(chat_id, value):
    _init_supabase()
    try:
        req = _get_requests()
        # Tambahkan ?on_conflict=chat_id agar PostgREST tahu kolom untuk upsert
        url = f"{_SB_URL}/rest/v1/bot_sessions?on_conflict=chat_id"
        headers = {**_SB_HDR, "Prefer": "resolution=merge-duplicates,return=representation"}
        r = req.post(url, headers=headers, json={"chat_id": int(chat_id), "state": value,
                 "updated_at": datetime.utcnow().isoformat()}, timeout=5)
        if not r.ok:
            logging.error(f"state_set FAILED: {r.status_code} {r.text[:100]}")
    except Exception as e:
        logging.error(f"state_set error (state mungkin hilang): {e}")

def state_pop(chat_id):
    _init_supabase()
    try: _sb_delete("bot_sessions", {"chat_id": f"eq.{chat_id}"})
    except: pass

# ── Linked users di Supabase ──────────────────────────────────────────────────

def _get_linked(tg_id):
    _init_supabase()
    try:
        # Order by updated_at desc agar selalu ambil data login terbaru
        rows = _sb_get("bot_linked", [
            ("select","*"),
            ("telegram_id",f"eq.{str(tg_id)}"),
            ("order","updated_at.desc"),
            ("limit","1")
        ])
        return rows[0] if rows else None
    except: return None

def _set_linked(tg_id, data):
    _init_supabase()
    try:
        req = _get_requests()
        # on_conflict=telegram_id agar tidak duplikat
        url = f"{_SB_URL}/rest/v1/bot_linked?on_conflict=telegram_id"
        headers = {**_SB_HDR, "Prefer": "resolution=merge-duplicates,return=representation"}
        payload = {"telegram_id": str(tg_id), "updated_at": datetime.utcnow().isoformat()}
        payload.update(data)
        r = req.post(url, headers=headers, json=payload, timeout=5)
        if not r.ok:
            logging.error(f"_set_linked FAILED: {r.status_code} {r.text[:100]}")
    except Exception as e:
        logging.warning(f"_set_linked error: {e}")

def _unlink(tg_id):
    _init_supabase()
    try: _sb_delete("bot_linked", {"telegram_id": f"eq.{str(tg_id)}"})
    except: pass


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg(method, **kwargs):
    try:
        r = _get_requests().post(f"{BASE}/{method}", json=kwargs, timeout=35)
        return r.json()
    except Exception as e:
        logging.error(f"TG [{method}]: {e}")
        return {}

def send(chat_id, text, keyboard=None, parse_mode="Markdown"):
    p = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if keyboard: p["reply_markup"] = keyboard
    return tg("sendMessage", **p)

def answer_cb(cb_id, text=""):
    tg("answerCallbackQuery", callback_query_id=cb_id, text=text)

def fmt_rp(n):
    return "Rp " + f"{int(n):,}".replace(",", ".")

def kb_back_main():
    return {"inline_keyboard": [[{"text": "🏠 Menu Utama", "callback_data": "menu_utama"}]]}

# ── API helpers ───────────────────────────────────────────────────────────────

def _api(method, path, tg_id, data=None, params=None):
    u = _get_linked(tg_id)
    if not u: return None
    cookies = {"dompetku_session": u["session_token"]}
    req = _get_requests()
    try:
        if method == "GET":
            r = req.get(f"{API_URL}{path}", params=params, cookies=cookies, timeout=10)
        elif method == "POST":
            r = req.post(f"{API_URL}{path}", json=data, cookies=cookies, timeout=10)
        elif method == "DELETE":
            r = req.delete(f"{API_URL}{path}", cookies=cookies, timeout=10)
        else:
            return None
        return r.json() if r.ok and r.content else ({"ok": True} if r.ok else None)
    except Exception as e:
        logging.error(f"API {method} {path}: {e}")
        return None


# ── Login ─────────────────────────────────────────────────────────────────────

def do_link_account(chat_id, tg_id, username, password):
    req = _get_requests()
    try:
        r = req.post(f"{API_URL}/auth/login",
                     json={"username": username, "password": password}, timeout=10)
        if not r.ok:
            err = r.json().get("error", "Login gagal")
            send(chat_id, f"❌ *Gagal:* {err}\n\nKetik /login untuk coba lagi.")
            return False
        data   = r.json()
        user   = data.get("user", {})
        cookie = r.cookies.get("dompetku_session", "")
        if not cookie:
            send(chat_id, "❌ Gagal session. Coba lagi."); return False
        _set_linked(tg_id, {
            "user_id":      user.get("id",""),
            "display_name": user.get("display_name", username),
            "role":         user.get("role", "member"),
            "family_id":    user.get("family_id",""),
            "family_name":  user.get("family_name","Keluarga"),
            "session_token": cookie,
        })
        try:
            _get_requests().post(f"{API_URL}/auth/link-telegram",
                          json={"username": username, "password": password,
                                "telegram_id": str(tg_id)}, timeout=10)
        except: pass
        show_main_menu(chat_id, tg_id)
        return True
    except Exception as e:
        logging.error(f"do_link_account: {e}")
        send(chat_id, "❌ Gagal koneksi ke server. Coba lagi nanti.")
        return False

def send_login_prompt(chat_id):
    send(chat_id,
         "🔐 *Dompet-KU*\n\n"
         "Akun Telegram kamu belum terhubung.\n\n"
         "Ketik /login untuk masuk.",
         keyboard={"inline_keyboard": [[{"text": "🔑 Login", "callback_data": "do_login"}]]})

# ── Menu ──────────────────────────────────────────────────────────────────────

def kb_main():
    return {"inline_keyboard": [
        [{"text": "➕ Transaksi",       "callback_data": "menu_transaksi"},
         {"text": "📷 Scan Struk",      "callback_data": "menu_scan"}],
        [{"text": "📊 Saldo Bulan Ini", "callback_data": "menu_saldo"},
         {"text": "📋 Laporan",         "callback_data": "menu_laporan"}],
        [{"text": "🕐 Riwayat Saya",    "callback_data": "menu_riwayat"},
         {"text": "🗑 Hapus Transaksi", "callback_data": "menu_hapus"}],
        [{"text": "🔐 Vault Pribadi",   "callback_data": "menu_vault"},
         {"text": "❓ Bantuan",         "callback_data": "menu_bantuan"}],
    ]}

def kb_konfirmasi(tipe):
    return {"inline_keyboard": [[
        {"text": "✅ Simpan", "callback_data": f"simpan_{tipe}"},
        {"text": "✏️ Ubah",  "callback_data": f"ubah_{tipe}"},
        {"text": "❌ Batal", "callback_data": "batal"},
    ]]}

def show_main_menu(chat_id, tg_id, text=None):
    u = _get_linked(tg_id)
    if not u: send_login_prompt(chat_id); return
    msg = text or f"👋 Halo *{u['display_name']}*!\n\nPilih menu di bawah ini 👇"
    send(chat_id, msg, keyboard=kb_main())


# ── Category & Amount Parser ──────────────────────────────────────────────────

CAT_KEYWORDS = {
    "Makanan & Minuman": ["makan","minum","warung","resto","cafe","nasi","bakso","kopi","snack","jajan"],
    "Transportasi":      ["ojek","gojek","grab","bensin","parkir","tol","bus","kereta","motor","mobil"],
    "Tagihan & Utilitas":["listrik","pln","air","internet","wifi","tagihan","pulsa","token","gas"],
    "Belanja":           ["belanja","shopee","tokopedia","indomaret","alfamart","supermarket","toko","pasar"],
    "Hiburan":           ["bioskop","netflix","spotify","game","wisata","nonton","liburan"],
    "Kesehatan":         ["obat","dokter","apotek","klinik","vitamin","bpjs"],
    "Pendidikan":        ["sekolah","kuliah","kursus","les","buku","spp"],
    "Tabungan":          ["tabungan","nabung","investasi","saham","deposit"],
    "Gaji":              ["gaji","salary","upah","thr","rapel"],
    "Freelance":         ["freelance","proyek","service","servis","jasa","fee","konsultan"],
}

def smart_category(text, tipe="exp"):
    text_low = text.lower().strip()
    for cat, keys in CAT_KEYWORDS.items():
        for key in keys:
            if key in text_low: return cat
    if tipe == "inc": return "Lainnya"
    return "Lainnya"

def parse_amount(text):
    text = text.lower().strip().replace(",", ".")
    patterns = [
        (r"([\d.]+)\s*juta?", 1_000_000),
        (r"([\d.]+)\s*jt",    1_000_000),
        (r"([\d.]+)\s*ribu?", 1_000),
        (r"([\d.]+)\s*rb",    1_000),
        (r"([\d.]+)\s*k\b",   1_000),
        (r"([\d.]+)",         1),
    ]
    for pat, mult in patterns:
        m = re.search(pat, text)
        if m:
            try:
                n = float(m.group(1).replace(".", "")) if mult == 1 else float(m.group(1))
                result = int(n * mult)
                if result > 0: return result
            except: continue
    return None

# ── Fitur Utama ───────────────────────────────────────────────────────────────

def show_saldo(chat_id, tg_id):
    month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/summary?month={month}", tg_id)
    if not r: send(chat_id, "❌ Gagal ambil data.", keyboard=kb_back_main()); return
    pct   = min(int(r.get("savings_rate", 0)), 100)
    bar   = "█"*(pct//10) + "░"*(10-pct//10)
    emoji = "🌟" if pct >= 20 else ("⚠️" if pct < 10 else "👍")
    text  = (f"💰 *Ringkasan Keuangan*\n📅 {datetime.now().strftime('%B %Y')}\n{'─'*28}\n\n"
             f"📈 Pemasukan   : *{fmt_rp(r['income'])}*\n"
             f"📉 Pengeluaran : *{fmt_rp(r['expense'])}*\n"
             f"💵 Saldo Bersih: *{fmt_rp(r['balance'])}*\n\n"
             f"{emoji} Tabungan: *{r['savings_rate']}%*\n`{bar}` {pct}%\n\n"
             f"📊 {r['tx_count']} transaksi bulan ini")
    tops = r.get("top_categories", [])[:3]
    if tops:
        text += "\n\n*🔴 Top Pengeluaran:*\n"
        for i, (cat, amt) in enumerate(tops):
            text += f"{'1️⃣2️⃣3️⃣'[i*2:i*2+2]} {cat}: {fmt_rp(amt)}\n"
    send(chat_id, text, keyboard={"inline_keyboard": [[
        {"text":"📋 Laporan","callback_data":"menu_laporan"},
        {"text":"🏠 Menu","callback_data":"menu_utama"}]]})

def show_laporan(chat_id, tg_id, month=None):
    if not month: month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/summary?month={month}", tg_id)
    if not r: send(chat_id, "❌ Gagal ambil laporan.", keyboard=kb_back_main()); return
    bulan = ["","Januari","Februari","Maret","April","Mei","Juni",
             "Juli","Agustus","September","Oktober","November","Desember"]
    y, mn = month.split("-")
    lines = [f"📊 *Laporan Detail*\n📅 {bulan[int(mn)]} {y}\n{'─'*28}\n",
             f"💰 Pemasukan  : *{fmt_rp(r['income'])}*",
             f"💸 Pengeluaran: *{fmt_rp(r['expense'])}*",
             f"💵 Saldo      : *{fmt_rp(r['balance'])}*\n"]
    tops = r.get("top_categories",[])
    if tops:
        lines.append("*📊 Pengeluaran per Kategori:*")
        for i, (cat, amt) in enumerate(tops[:6]):
            pct = round(amt/r["expense"]*100) if r["expense"]>0 else 0
            bar = "█"*(pct//10)+"░"*(10-pct//10)
            lines.append(f"{'🥇🥈🥉4️⃣5️⃣6️⃣'[i*2:i*2+2]} *{cat}*\n   `{bar}` {pct}% — {fmt_rp(amt)}")
    m_int = int(mn)
    prev  = f"{int(y)-1}-12" if m_int==1 else f"{y}-{m_int-1:02d}"
    nxt   = f"{int(y)+1}-01" if m_int==12 else f"{y}-{m_int+1:02d}"
    now_m = datetime.now().strftime("%Y-%m")
    nav   = [{"text":f"⬅️ {bulan[int(prev.split('-')[1])]}","callback_data":f"laporan_{prev}"}]
    if month < now_m:
        nav.append({"text":f"{bulan[int(nxt.split('-')[1])]} ➡️","callback_data":f"laporan_{nxt}"})
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard":[nav,
        [{"text":"🏠 Menu","callback_data":"menu_utama"}]]})

def show_riwayat(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    r = _api("GET", f"/transactions?member={u['display_name']}", tg_id)
    txs = r[:7] if isinstance(r, list) else []
    if not txs: send(chat_id, "📭 Belum ada transaksi.", keyboard=kb_back_main()); return
    lines = [f"🕐 *Riwayat Transaksi*\n👤 {u['display_name']}\n{'─'*24}\n"]
    for t in txs:
        icon = "💚" if t["type"]=="inc" else "❤️"
        sign = "+" if t["type"]=="inc" else "-"
        src  = "📱" if t.get("source")=="telegram" else "🖥"
        lines.append(f"{icon} *{t.get('desc','?')}* {src}\n"
                     f"   🏷 {t['category']} • {sign}{fmt_rp(t['amount'])}\n"
                     f"   📅 {t['date']}")
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard":[[
        {"text":"➕ Tambahkan","callback_data":"menu_transaksi"},
        {"text":"🏠 Menu","callback_data":"menu_utama"}]]})

def show_hapus(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    endpoint = "/transactions" if u["role"]=="admin" else f"/transactions?member={u['display_name']}"
    r = _api("GET", endpoint, tg_id)
    txs = sorted(r, key=lambda t: t.get("date",""), reverse=True)[:10] if isinstance(r,list) else []
    if not txs: send(chat_id, "📭 Tidak ada transaksi.", keyboard=kb_back_main()); return
    send(chat_id, "🗑 *Hapus Transaksi*\nPilih yang ingin dihapus _(10 terakhir)_:")
    for t in txs:
        icon = "💚" if t["type"]=="inc" else "❤️"
        send(chat_id,
             f"{icon} *{t.get('desc','?')}* — {fmt_rp(t['amount'])}\n"
             f"📅 {t['date']} • 🏷 {t['category']}",
             keyboard={"inline_keyboard":[[{"text":"🗑 Hapus","callback_data":f"hapus_{t['id']}"}]]})

def show_vault_menu(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    send(chat_id,
         f"🔐 *Private Vault*\n━━━━━━━━━━━━━━━━━━━━\n"
         f"👤 {u['display_name']}\n\nCatatan keuangan pribadi 🔒\n\nPilih menu:",
         keyboard={"inline_keyboard":[
             [{"text":"💸 Catat Keluar","callback_data":"vault_keluar"},
              {"text":"💰 Catat Masuk","callback_data":"vault_masuk"}],
             [{"text":"📊 Ringkasan","callback_data":"vault_ringkasan"},
              {"text":"🕐 Riwayat","callback_data":"vault_riwayat"}],
             [{"text":"🔙 Menu Utama","callback_data":"menu_utama"}]]})


def show_vault_ringkasan(chat_id, tg_id):
    month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/private/summary?month={month}", tg_id)
    if not r: send(chat_id, "❌ Gagal ambil data vault.", keyboard=kb_back_main()); return
    bulan = ["","Januari","Februari","Maret","April","Mei","Juni",
             "Juli","Agustus","September","Oktober","November","Desember"]
    mn = int(month.split("-")[1]); y = month.split("-")[0]
    send(chat_id, f"🔐 *Vault — Ringkasan*\n📅 {bulan[mn]} {y}\n{'─'*24}\n\n"
         f"💰 Pemasukan   : *{fmt_rp(r['income'])}*\n"
         f"💸 Pengeluaran : *{fmt_rp(r['expense'])}*\n"
         f"💵 Saldo       : *{fmt_rp(r['balance'])}*\n📊 {r['tx_count']} catatan",
         keyboard={"inline_keyboard":[[{"text":"🕐 Riwayat","callback_data":"vault_riwayat"},
                                        {"text":"🔙 Vault","callback_data":"menu_vault"}]]})

def show_vault_riwayat(chat_id, tg_id):
    r = _api("GET", "/private/transactions", tg_id)
    txs = r[:7] if isinstance(r,list) else []
    if not txs:
        send(chat_id, "📭 Vault masih kosong.", keyboard={"inline_keyboard":[[
            {"text":"➕ Catat","callback_data":"vault_keluar"},
            {"text":"🔙 Vault","callback_data":"menu_vault"}]]}); return
    lines = [f"🔐 *Vault — Riwayat Terakhir*\n{'─'*24}\n"]
    for t in txs:
        icon = "💚" if t.get("type")=="inc" else "❤️"
        sign = "+" if t.get("type")=="inc" else "-"
        lines.append(f"{icon} *{t.get('note_desc','?')}*\n"
                     f"   🏷 {t.get('category','?')} • {sign}{fmt_rp(t['amount'])}\n"
                     f"   📅 {t.get('date','')}")
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard":[[
        {"text":"➕ Catat Baru","callback_data":"vault_keluar"},
        {"text":"🔙 Vault","callback_data":"menu_vault"}]]})

def do_simpan_tx(chat_id, tg_id, s):
    u = _get_linked(tg_id)
    if not u:
        send(chat_id, "❌ Sesi habis. Ketik /login."); return
    tipe=s.get("tipe","exp"); amount=s.get("amount"); desc=s.get("desc")
    cat=s.get("category","Lainnya"); ikey=s.get("idempotency_key")
    logging.info(f"[do_simpan_tx] step={s.get('step')} tipe={tipe} amount={amount} ikey={ikey}")
    if not amount or not desc:
        send(chat_id, f"❌ Data tidak lengkap. Coba scan ulang.", keyboard=kb_back_main()); return
    payload = {
        "type":tipe,"amount":amount,"desc":desc,"category":cat,
        "member":u["display_name"],"date":s.get("date",datetime.now().strftime("%Y-%m-%d")),
        "source":"telegram"
    }
    if ikey:
        payload["idempotency_key"] = ikey
    r = _api("POST", "/transactions", tg_id, payload)
    state_pop(chat_id)
    if r and r.get("id"):
        send(chat_id, f"✅ *Tersimpan!*\n\n{'❤️' if tipe=='exp' else '💚'} *{fmt_rp(amount)}*\n📝 {desc}\n🏷 {cat}",
             keyboard={"inline_keyboard":[[{"text":"➕ Catat Lagi","callback_data":"menu_transaksi"},
                                           {"text":"🏠 Menu","callback_data":"menu_utama"}]]})
    elif r and ("duplicate" in str(r).lower() or "unique" in str(r).lower()):
        # Transaksi sudah tersimpan sebelumnya (double-click atau retry)
        send(chat_id, "✅ *Transaksi sudah tersimpan sebelumnya.*\n_(duplikat diabaikan)_",
             keyboard={"inline_keyboard":[[{"text":"🏠 Menu","callback_data":"menu_utama"}]]})
    else:
        logging.error(f"[do_simpan_tx] API response gagal: {r}")
        send(chat_id, "❌ Gagal menyimpan. Coba lagi.", keyboard=kb_back_main())

def do_simpan_vault(chat_id, tg_id, s):
    tipe=s.get("tipe","exp"); amount=s.get("amount"); desc=s.get("desc"); cat=s.get("category","Lainnya")
    if not amount or not desc:
        send(chat_id, "❌ Data tidak lengkap.", keyboard=kb_back_main()); return
    r = _api("POST", "/private/transactions", tg_id, {
        "type":tipe,"amount":amount,"desc":desc,"category":cat,
        "date":s.get("date",datetime.now().strftime("%Y-%m-%d")),"source":"telegram"})
    state_pop(chat_id)
    if r and (r.get("id") or r.get("owner_id")):
        send(chat_id, f"✅ *Tersimpan di Vault!*\n\n{'❤️' if tipe=='exp' else '💚'} *{fmt_rp(amount)}*\n📝 {desc}\n🏷 {cat}",
             keyboard={"inline_keyboard":[[{"text":"🔐 Menu Vault","callback_data":"menu_vault"},
                                           {"text":"🏠 Menu","callback_data":"menu_utama"}]]})
    else:
        send(chat_id, "❌ Gagal simpan vault.", keyboard=kb_back_main())


# ── Scan Struk ────────────────────────────────────────────────────────────────

def start_scan(chat_id, tg_id):
    state_set(chat_id, {"step":"scan_tipe","telegram_id":str(tg_id)})
    send(chat_id, "📷 *Scan Struk / Nota / Slip Gaji*\n\nIni transaksi pengeluaran atau pemasukan?",
         keyboard={"inline_keyboard":[[{"text":"✅ Jenis: Pengeluaran 💸","callback_data":"scan_tipe_exp"},
                                        {"text":"✅ Jenis: Pemasukan 💰","callback_data":"scan_tipe_inc"}],
                                       [{"text":"❌ Batal","callback_data":"batal"}]]})

def ask_scan_photo(chat_id, tipe):
    label = "Pengeluaran 💸" if tipe=="exp" else "Pemasukan 💰"
    send(chat_id, f"✅ Jenis: *{label}*\n\nSekarang kirim foto struk/nota/slip gaji.\n\n"
         f"💡 *Tips foto yang baik:*\n• Cahaya cukup\n• Teks angka jelas\n• Tidak blur\n• Foto lurus\n\n"
         f"📲 Pilih dari galeri atau ambil foto sekarang 👇",
         keyboard={"inline_keyboard":[[{"text":"❌ Batal","callback_data":"batal"}]]})

def handle_photo(msg):
    chat_id = msg["chat"]["id"]
    tg_id   = str(msg.get("from",{}).get("id", chat_id))
    u = _get_linked(tg_id)
    if not u: send(chat_id, "🔐 Login dulu dengan /login"); return
    s    = state_get(chat_id)
    tipe = s.get("tipe","exp")
    label= "Pengeluaran 💸" if tipe=="exp" else "Pemasukan 💰"
    if not GROQ_KEY: send(chat_id, "⚠️ Groq API Key belum diset."); return
    send(chat_id, f"📷 *Foto diterima! ({label})*\n⏳ Sedang membaca dengan AI...\nMohon tunggu sebentar")
    req = _get_requests()
    try:
        photos  = msg.get("photo",[])
        if not photos: send(chat_id, "❌ Tidak ada foto."); return
        fi = tg("getFile", file_id=photos[-1]["file_id"])
        fp = fi.get("result",{}).get("file_path")
        if not fp: send(chat_id, "❌ Gagal ambil foto."); return
        img  = req.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=30)
        if not img.ok: send(chat_id, "❌ Gagal download foto."); return
        b64  = base64.b64encode(img.content).decode()
        resp = req.post("https://api.groq.com/openai/v1/chat/completions",
            json={"model":"meta-llama/llama-4-scout-17b-16e-instruct","max_tokens":600,
                  "messages":[{"role":"user","content":[
                      {"type":"text","text":'Baca struk/nota ini. Jawab HANYA JSON:\n{"desc":"deskripsi","amount":12000,"date":"2024-01-15","source_name":"nama toko"}\nJika bukan struk: {"error":"bukan struk"}'},
                      {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}]},
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"}, timeout=40)
        if resp.status_code==429:
            send(chat_id, "⏳ Groq rate limit. Tunggu 1 menit.", keyboard=kb_back_main()); return
        if not resp.ok:
            send(chat_id, f"❌ Groq error {resp.status_code}.", keyboard=kb_back_main()); return
        content = resp.json().get("choices",[{}])[0].get("message",{}).get("content","{}")
        jm = re.search(r'\{.*\}', content, re.DOTALL)
        if not jm: send(chat_id, "⚠️ AI tidak bisa baca struk.", keyboard=kb_back_main()); return
        data = json.loads(jm.group())
        if "error" in data: send(chat_id, f"⚠️ {data['error']}", keyboard=kb_back_main()); return
        desc   = str(data.get("desc","Transaksi")).strip().title()
        amount = int(data.get("amount",0))
        date_s = data.get("date","") or datetime.now().strftime("%Y-%m-%d")
        src_n  = data.get("source_name","")
        cat    = smart_category(desc, tipe)
        if amount<=0: send(chat_id, "⚠️ Nominal tidak terdeteksi.", keyboard=kb_back_main()); return
        state_set(chat_id, {**s, "step":"scan_konfirmasi","tipe":tipe,"desc":desc,"amount":amount,"date":date_s,"category":cat,
                            "idempotency_key": f"scan_{chat_id}_{int(datetime.now().timestamp())}"})
        icon  = "💸" if tipe=="exp" else "💰"
        label = "Pengeluaran" if tipe=="exp" else "Pemasukan"
        note  = f"\n_{src_n}_" if src_n else ""
        send(chat_id, f"✅ *Berhasil membaca struk!*\n\n{icon} {label}\n{'━'*20}\n"
             f"📝 Keterangan : *{desc}*\n🏷️ Kategori   : *{cat}*\n💵 Nominal    : *{fmt_rp(amount)}*\n"
             f"📅 Tanggal    : *{date_s}*\n{'━'*20}{note}\n\nSimpan transaksi ini?",
             keyboard=kb_konfirmasi(tipe))
    except json.JSONDecodeError:
        send(chat_id, "⚠️ Format respons AI tidak valid.", keyboard=kb_back_main())
    except Exception as e:
        logging.error(f"handle_photo: {e}")
        send(chat_id, "❌ Terjadi kesalahan saat scan.", keyboard=kb_back_main())


# ── Handle Message ────────────────────────────────────────────────────────────

def handle_message(msg):
    if not msg: return
    chat_id = msg.get("chat",{}).get("id")
    tg_id   = str(msg.get("from",{}).get("id",""))
    text    = msg.get("text","").strip()
    if msg.get("photo"): handle_photo(msg); return
    if not chat_id or not text: return
    s   = state_get(chat_id)
    u   = _get_linked(tg_id)
    cmd = text.split()[0].lower().split("@")[0]

    # Flow login
    if s.get("step") == "login_username":
        state_set(chat_id, {"step":"login_password","username":text})
        send(chat_id, "🔑 Masukkan *password* kamu:"); return
    if s.get("step") == "login_password":
        username = s.get("username",""); state_pop(chat_id)
        send(chat_id, "⏳ Memverifikasi...")
        do_link_account(chat_id, tg_id, username, text); return

    # Flow input transaksi
    if s.get("step") == "input_tx":
        amount = parse_amount(text)
        if not amount: send(chat_id, "⚠️ Nominal tidak terbaca.\nContoh: `makan siang 25000`"); return
        desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?','',text,flags=re.IGNORECASE).strip()
        desc = desc_raw.title() if desc_raw else ("Pemasukan" if s["tipe"]=="inc" else "Pengeluaran")
        cat  = smart_category(desc, s["tipe"])
        state_set(chat_id, {**s,"step":"konfirmasi_tx","amount":amount,"desc":desc,"category":cat})
        icon  = "💸" if s["tipe"]=="exp" else "💰"
        label = "Pengeluaran" if s["tipe"]=="exp" else "Pemasukan"
        send(chat_id, f"{icon} *Konfirmasi {label}*\n\n📝 Keterangan : *{desc}*\n🏷 Kategori   : *{cat}*\n"
             f"💵 Nominal    : *{fmt_rp(amount)}*\n📅 Tanggal    : *{datetime.now().strftime('%d %b %Y')}*\n\nSimpan?",
             keyboard=kb_konfirmasi(s["tipe"])); return

    # Flow input vault
    if s.get("step") == "vault_input":
        amount = parse_amount(text)
        if not amount: send(chat_id, "⚠️ Nominal tidak terbaca."); return
        desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?','',text,flags=re.IGNORECASE).strip()
        desc = desc_raw.title() if desc_raw else ("Pemasukan" if s["tipe"]=="inc" else "Pengeluaran")
        cat  = smart_category(desc, s["tipe"])
        state_set(chat_id, {**s,"step":"vault_konfirmasi","amount":amount,"desc":desc,"category":cat})
        send(chat_id, f"🔐 *Konfirmasi Vault*\n\n📝 {desc}\n🏷 {cat}\n💵 {fmt_rp(amount)}\n\nSimpan ke vault?",
             keyboard={"inline_keyboard":[[{"text":"✅ Simpan","callback_data":"vault_simpan_ok"},
                                           {"text":"❌ Batal","callback_data":"batal"}]]}); return

    # Perintah
    if cmd in ("/start","/menu"):
        if u: show_main_menu(chat_id, tg_id)
        else: send_login_prompt(chat_id)
    elif cmd == "/login":
        state_set(chat_id, {"step":"login_username"})
        send(chat_id, "👤 Masukkan *username* akun Dompet-KU kamu:")
    elif cmd == "/logout":
        _unlink(tg_id); state_pop(chat_id)
        send(chat_id, "✅ Berhasil logout. Ketik /login untuk masuk kembali.")
    elif cmd == "/saldo":
        if u: show_saldo(chat_id, tg_id)
        else: send_login_prompt(chat_id)
    elif cmd == "/laporan":
        if u: show_laporan(chat_id, tg_id)
        else: send_login_prompt(chat_id)
    elif cmd == "/riwayat":
        if u: show_riwayat(chat_id, tg_id)
        else: send_login_prompt(chat_id)
    elif cmd == "/vault":
        if u: show_vault_menu(chat_id, tg_id)
        else: send_login_prompt(chat_id)
    elif cmd == "/id":
        send(chat_id, f"🆔 *Telegram ID kamu:*\n`{tg_id}`")
    elif cmd == "/bantuan":
        send(chat_id, "❓ *Panduan Dompet-KU Bot*\n\n• /login — hubungkan akun\n• /menu — menu utama\n"
             "• /saldo — saldo bulan ini\n• /laporan — laporan\n• /riwayat — transaksi terakhir\n"
             "• /vault — catatan pribadi\n• /logout — keluar\n• /id — lihat Telegram ID\n\n"
             "📷 Kirim foto struk untuk scan otomatis!", keyboard=kb_back_main())
    else:
        if not u: send_login_prompt(chat_id); return
        amount = parse_amount(text)
        if amount:
            desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?','',text,flags=re.IGNORECASE).strip()
            desc = desc_raw.title() if desc_raw else "Pengeluaran"
            cat  = smart_category(desc, "exp")
            state_set(chat_id, {"step":"konfirmasi_tx","tipe":"exp","amount":amount,"desc":desc,"category":cat})
            send(chat_id, f"💸 *Pengeluaran terdeteksi*\n\n📝 {desc}\n🏷 {cat}\n💵 {fmt_rp(amount)}\n\nSimpan?",
                 keyboard=kb_konfirmasi("exp"))
        else:
            show_main_menu(chat_id, tg_id)


# ── Handle Callback ───────────────────────────────────────────────────────────

def handle_callback(cb):
    if not cb: return
    chat_id = cb["message"]["chat"]["id"]
    data    = cb.get("data","")
    tg_id   = str(cb.get("from",{}).get("id",""))
    answer_cb(cb["id"])
    u = _get_linked(tg_id)
    s = state_get(chat_id)

    if data == "menu_utama":    state_pop(chat_id); show_main_menu(chat_id, tg_id); return
    if data == "batal":         state_pop(chat_id); show_main_menu(chat_id, tg_id, "❌ Dibatalkan."); return
    if data == "do_login":
        state_set(chat_id, {"step":"login_username"})
        send(chat_id, "👤 Masukkan *username* akun Dompet-KU kamu:"); return

    if not u: send(chat_id, "🔐 Ketik /login untuk masuk."); return

    if data == "menu_transaksi":
        send(chat_id, "📝 Pilih jenis transaksi:", keyboard={"inline_keyboard":[
            [{"text":"💸 Pengeluaran","callback_data":"tx_tipe_exp"},
             {"text":"💰 Pemasukan","callback_data":"tx_tipe_inc"}],
            [{"text":"❌ Batal","callback_data":"batal"}]]}); return
    if data == "tx_tipe_exp":
        state_set(chat_id,{"step":"input_tx","tipe":"exp"})
        send(chat_id,"💸 Ketik nominal dan keterangan:\n\n`makan siang 25000`",
             keyboard={"inline_keyboard":[[{"text":"❌ Batal","callback_data":"batal"}]]}); return
    if data == "tx_tipe_inc":
        state_set(chat_id,{"step":"input_tx","tipe":"inc"})
        send(chat_id,"💰 Ketik nominal dan keterangan:\n\n`gaji 5juta`",
             keyboard={"inline_keyboard":[[{"text":"❌ Batal","callback_data":"batal"}]]}); return
    if data == "menu_scan":    start_scan(chat_id, tg_id); return
    if data == "scan_tipe_exp": state_set(chat_id,{**s,"step":"scan_tunggu_foto","tipe":"exp"}); ask_scan_photo(chat_id,"exp"); return
    if data == "scan_tipe_inc": state_set(chat_id,{**s,"step":"scan_tunggu_foto","tipe":"inc"}); ask_scan_photo(chat_id,"inc"); return
    if data == "menu_saldo":   show_saldo(chat_id, tg_id); return
    if data == "menu_laporan": show_laporan(chat_id, tg_id); return
    if data.startswith("laporan_"): show_laporan(chat_id, tg_id, data[8:]); return
    if data == "menu_riwayat": show_riwayat(chat_id, tg_id); return
    if data == "menu_hapus":   show_hapus(chat_id, tg_id); return
    if data == "menu_vault":   show_vault_menu(chat_id, tg_id); return
    if data == "vault_keluar":
        state_set(chat_id,{"step":"vault_input","tipe":"exp"})
        send(chat_id,"🔐 💸 Ketik nominal dan keterangan:",
             keyboard={"inline_keyboard":[[{"text":"❌ Batal","callback_data":"batal"}]]}); return
    if data == "vault_masuk":
        state_set(chat_id,{"step":"vault_input","tipe":"inc"})
        send(chat_id,"🔐 💰 Ketik nominal dan keterangan:",
             keyboard={"inline_keyboard":[[{"text":"❌ Batal","callback_data":"batal"}]]}); return
    if data == "vault_ringkasan": show_vault_ringkasan(chat_id, tg_id); return
    if data == "vault_riwayat":   show_vault_riwayat(chat_id, tg_id); return
    if data == "vault_simpan_ok":
        if s.get("step") == "vault_konfirmasi": do_simpan_vault(chat_id, tg_id, s)
        return
    if data == "menu_bantuan":
        send(chat_id,"❓ *Panduan*\n• /menu /saldo /laporan /riwayat\n• /vault /logout /id\n📷 Kirim foto struk!",
             keyboard=kb_back_main()); return
    if data in ("simpan_exp","simpan_inc"):
        # Debug log untuk diagnosa scan tidak tersimpan
        logging.info(f"[simpan] data={data} step={s.get('step')} amount={s.get('amount')} desc={s.get('desc')} tipe={s.get('tipe')}")
        if s.get("step") in ("konfirmasi_tx","scan_konfirmasi"):
            do_simpan_tx(chat_id, tg_id, s)
        else:
            logging.error(f"[simpan] Step tidak cocok: {s.get('step')} — state penuh: {s}")
            send(chat_id, f"❌ State tidak valid (step={s.get('step')}). Coba scan ulang.", keyboard=kb_back_main())
        return
    if data in ("ubah_exp","ubah_inc"):
        tipe = data.split("_")[1]
        state_set(chat_id,{**s,"step":"input_tx","tipe":tipe})
        send(chat_id,"✏️ Ketik ulang nominal dan keterangan:"); return
    if data.startswith("hapus_"):
        tx_id = data.split("_")[1]
        try:
            r = _get_requests().delete(f"{API_URL}/transactions/{tx_id}",
                cookies={"dompetku_session":u["session_token"]}, timeout=10)
            if r.ok: send(chat_id,"✅ Transaksi berhasil dihapus.", keyboard=kb_back_main())
            else: send(chat_id,"❌ Gagal menghapus.", keyboard=kb_back_main())
        except Exception as e:
            logging.error(f"hapus TX: {e}"); send(chat_id,"❌ Gagal.", keyboard=kb_back_main())
        return

# ── Setup commands ────────────────────────────────────────────────────────────

def setup_commands():
    tg("setMyCommands", commands=[
        {"command":"start",   "description":"🏠 Menu Utama"},
        {"command":"menu",    "description":"🏠 Buka Menu"},
        {"command":"login",   "description":"🔑 Hubungkan Akun"},
        {"command":"logout",  "description":"🚪 Keluar Akun"},
        {"command":"saldo",   "description":"💰 Cek Saldo"},
        {"command":"laporan", "description":"📋 Laporan"},
        {"command":"riwayat", "description":"🕐 Riwayat Transaksi"},
        {"command":"vault",   "description":"🔐 Private Vault"},
        {"command":"id",      "description":"🆔 Lihat Telegram ID"},
        {"command":"bantuan", "description":"❓ Panduan"},
    ])
    logging.info("[Bot] Commands registered.")

def start_scheduler():
    pass  # Tidak dipakai di serverless
