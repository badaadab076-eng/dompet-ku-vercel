"""
Dompet-KU — Telegram Bot (Multi Keluarga + Tampilan Premium)
Webhook mode — dijalankan oleh app.py via /api/telegram/webhook
"""

import requests, logging, json, re, calendar, os, sys, base64
from datetime import datetime

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)

_bot_dir    = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_bot_dir)
sys.path.insert(0, _bot_dir)
sys.path.insert(0, _parent_dir)

try:
    from config import TELEGRAM_TOKEN as BOT_TOKEN, PORT, GEMINI_API_KEY
except ImportError:
    BOT_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
    PORT           = int(os.environ.get("PORT", 5000))
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

API_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/") + "/api"
BASE    = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ── State & linked users ──────────────────────────────────────────────────────
_state  = {}   # {chat_id: {...}}
_linked = {}   # {telegram_id_str: {user_id, display_name, role, family_id, family_name, session_token}}

def state_get(chat_id):    return _state.get(int(chat_id), {})
def state_set(chat_id, v): _state[int(chat_id)] = v
def state_pop(chat_id):    _state.pop(int(chat_id), None)
def _get_linked(tg_id):    return _linked.get(str(tg_id))
def _set_linked(tg_id, d): _linked[str(tg_id)] = d
def _unlink(tg_id):        _linked.pop(str(tg_id), None)

# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg(method, **kwargs):
    try:
        r = requests.post(f"{BASE}/{method}", json=kwargs, timeout=35)
        return r.json()
    except Exception as e:
        logging.error(f"TG [{method}]: {e}")
        return {}

def send(chat_id, text, keyboard=None, parse_mode="Markdown"):
    p = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if keyboard: p["reply_markup"] = keyboard
    return tg("sendMessage", **p)

def edit(chat_id, msg_id, text, keyboard=None, parse_mode="Markdown"):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": parse_mode}
    if keyboard: p["reply_markup"] = keyboard
    return tg("editMessageText", **p)

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
    try:
        if method == "GET":
            r = requests.get(f"{API_URL}{path}", params=params, cookies=cookies, timeout=10)
        elif method == "POST":
            r = requests.post(f"{API_URL}{path}", json=data, cookies=cookies, timeout=10)
        elif method == "DELETE":
            r = requests.delete(f"{API_URL}{path}", cookies=cookies, timeout=10)
        else:
            return None
        return r.json() if r.ok and r.content else ({"ok": True} if r.ok else None)
    except Exception as e:
        logging.error(f"API {method} {path}: {e}")
        return None


# ── Login & Link Akun ─────────────────────────────────────────────────────────

def do_link_account(chat_id, tg_id, username, password):
    try:
        r = requests.post(f"{API_URL}/auth/login",
                          json={"username": username, "password": password}, timeout=10)
        if not r.ok:
            err = r.json().get("error", "Login gagal")
            send(chat_id, f"❌ *Gagal login:* {err}\n\nKetik /login untuk coba lagi.")
            return False
        data   = r.json()
        user   = data.get("user", {})
        cookie = r.cookies.get("dompetku_session", "")
        if not cookie:
            send(chat_id, "❌ Gagal mendapatkan session. Coba lagi.")
            return False
        _set_linked(tg_id, {
            "user_id":      user.get("id"),
            "display_name": user.get("display_name", username),
            "role":         user.get("role", "member"),
            "family_id":    user.get("family_id"),
            "family_name":  user.get("family_name", "Keluarga"),
            "session_token": cookie,
        })
        # Simpan telegram_id ke database
        try:
            requests.post(f"{API_URL}/auth/link-telegram",
                          json={"username": username, "password": password,
                                "telegram_id": str(tg_id)}, timeout=10)
        except Exception:
            pass
        u = _get_linked(tg_id)
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
         "Ketik /login untuk masuk\n"
         "atau /daftar jika belum punya akun.",
         keyboard={"inline_keyboard": [[
             {"text": "🔑 Login",  "callback_data": "do_login"},
             {"text": "📝 Daftar", "callback_data": "do_daftar"},
         ]]})


# ── Menu Keyboards ────────────────────────────────────────────────────────────

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
        {"text": "✅ Simpan",  "callback_data": f"simpan_{tipe}"},
        {"text": "✏️ Ubah",   "callback_data": f"ubah_{tipe}"},
        {"text": "❌ Batal",  "callback_data": "batal"},
    ]]}

# ── Main Menu ─────────────────────────────────────────────────────────────────

def show_main_menu(chat_id, tg_id, text=None):
    u = _get_linked(tg_id)
    if not u:
        send_login_prompt(chat_id); return
    msg = text or (
        f"👋 Halo *{u['display_name']}*!\n\n"
        f"Pilih menu di bawah ini 👇"
    )
    send(chat_id, msg, keyboard=kb_main())


# ── Category Detection (Fuzzy) ────────────────────────────────────────────────

CAT_KEYWORDS = {
    "Makanan & Minuman": ["makan","minum","warung","resto","restoran","cafe","kafe","nasi",
                          "bakso","soto","mie","ayam","ikan","snack","jajan","kopi","teh",
                          "es","sarapan","camilan","gorengan","pizza","burger","minuman"],
    "Transportasi":      ["ojek","gojek","grab","bensin","bbm","solar","parkir","tol",
                          "bus","angkot","kereta","krl","mrt","lrt","taksi","motor","mobil",
                          "pertamina","shell","transport"],
    "Tagihan & Utilitas":["listrik","pln","air","pdam","internet","wifi","indihome",
                          "telkom","tagihan","pulsa","token","gas","elpiji","tv"],
    "Belanja":           ["belanja","shopee","tokopedia","lazada","indomaret","alfamart",
                          "minimarket","supermarket","hypermart","toko","pasar","mall","barang",
                          "aki","baut","sparepart","suku","onderdil"],
    "Hiburan":           ["bioskop","film","movie","netflix","spotify","youtube","game",
                          "gaming","musik","konser","wisata","liburan","nonton","rekreasi"],
    "Kesehatan":         ["obat","dokter","apotek","klinik","rumah sakit","vitamin",
                          "suplemen","dental","gigi","mata","bpjs","periksa"],
    "Pendidikan":        ["sekolah","kuliah","kursus","les","buku","spp","seminar",
                          "workshop","training","belajar","alat tulis"],
    "Tabungan":          ["tabungan","nabung","investasi","saham","reksadana","deposit"],
    "Gaji":              ["gaji","salary","upah","honor","thr","rapel"],
    "Freelance":         ["freelance","proyek","project","service","servis","jasa","fee",
                          "konsultan","desain","coding","order"],
}

def _levenshtein(a, b):
    if len(a) < len(b): a, b = b, a
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a):
        curr = [i+1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(0 if ca==cb else 1)))
        prev = curr
    return prev[-1]

def smart_category(text, tipe="exp"):
    text_low = text.lower().strip()
    words    = [w for w in re.split(r'\W+', text_low) if w]
    for cat, keys in CAT_KEYWORDS.items():
        for key in keys:
            if key in text_low:
                return cat
    best_cat, best_score = "Lainnya", 999
    for cat, keys in CAT_KEYWORDS.items():
        for word in words:
            if len(word) < 4: continue
            for key in keys:
                if len(key) < 4: continue
                ratio = min(len(word), len(key)) / max(len(word), len(key))
                if ratio < 0.6: continue
                dist = _levenshtein(word, key)
                tol  = 1 if max(len(word), len(key)) <= 7 else 2
                if dist <= tol and dist < best_score:
                    best_score = dist; best_cat = cat
    if tipe == "inc" and best_cat not in ("Gaji","Freelance","Tabungan","Lainnya"):
        return "Lainnya"
    return best_cat

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


# ── Multi-input parser (unified format) ──────────────────────────────────────

def parse_unified_tx(text, display_name, tg_id):
    """Parse multi-baris format: [nominal] [keterangan] [masuk|keluar] [vault?]"""
    results, errors = [], []
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    INC_WORDS = {"masuk","pemasukan","income","terima","dapat","diterima"}
    EXP_WORDS = {"keluar","pengeluaran","bayar","beli","habis","pakai"}

    for i, line in enumerate(lines, 1):
        raw = line.lower()
        is_vault   = "vault" in raw
        clean_raw  = re.sub(r'\bvault\b', '', raw).strip()
        tipe       = "exp"
        for w in INC_WORDS:
            if w in clean_raw:
                tipe = "inc"
                clean_raw = re.sub(r'\b'+w+r'\b', '', clean_raw).strip()
                break
        for w in EXP_WORDS:
            if w in clean_raw:
                tipe = "exp"
                clean_raw = re.sub(r'\b'+w+r'\b', '', clean_raw).strip()
                break
        amount = parse_amount(clean_raw)
        if not amount:
            errors.append(f"Baris {i}: `{line}` — nominal tidak terbaca")
            continue
        desc_raw = re.sub(r'^[\d.,\s]+(rb|ribu|jt|juta|k\b)?', '', clean_raw, flags=re.IGNORECASE).strip()
        desc = desc_raw.title() if desc_raw else ("Pemasukan" if tipe == "inc" else "Pengeluaran")
        cat  = smart_category(line, tipe)
        results.append({
            "tipe": tipe, "amount": amount, "desc": desc,
            "category": cat, "member": display_name,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "mode": "vault" if is_vault else "normal",
        })
    return results, errors

CAT_ICON = {
    "Makanan & Minuman":"🍽","Transportasi":"🚗","Tagihan & Utilitas":"⚡",
    "Belanja":"🛒","Hiburan":"🎬","Kesehatan":"💊","Pendidikan":"📚",
    "Tabungan":"🐷","Gaji":"💼","Freelance":"💻","Lainnya":"📦",
}

def show_unified_verify(chat_id, txs, errors):
    total_reg = sum(t["amount"] for t in txs if t["mode"] == "normal")
    total_vlt = sum(t["amount"] for t in txs if t["mode"] == "vault")
    lines = [f"📋 *{len(txs)} transaksi terdeteksi:*\n"]
    for i, t in enumerate(txs, 1):
        ic    = CAT_ICON.get(t["category"], "📦")
        arrow = "💚" if t["tipe"] == "inc" else "❤️"
        lock  = " 🔐" if t["mode"] == "vault" else ""
        lines.append(f"{i}. {arrow} *{fmt_rp(t['amount'])}*{lock}\n   {ic} {t['category']} — _{t['desc']}_")
    reg_n = sum(1 for t in txs if t["mode"]=="normal")
    vlt_n = sum(1 for t in txs if t["mode"]=="vault")
    if reg_n: lines.append(f"\n📂 Reguler: *{fmt_rp(total_reg)}* ({reg_n} tx)")
    if vlt_n: lines.append(f"🔐 Vault:   *{fmt_rp(total_vlt)}* ({vlt_n} tx)")
    if errors:
        lines.append(f"\n⚠️ {len(errors)} baris tidak terbaca:")
        for e in errors[:3]: lines.append(f"  • {e}")
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard": [[
        {"text": "✅ Simpan Semua", "callback_data": "unified_simpan"},
        {"text": "✏️ Ulang",        "callback_data": "unified_ulang"},
        {"text": "❌ Batal",        "callback_data": "batal"},
    ]]})

def do_unified_simpan(chat_id, tg_id, txs):
    ok_reg = ok_vlt = fail = 0
    total_reg = total_vlt = 0
    for t in txs:
        if t["mode"] == "vault":
            r = _api("POST", "/private/transactions", tg_id, {
                "type": t["tipe"], "amount": t["amount"], "desc": t["desc"],
                "category": t["category"], "date": t["date"], "source": "telegram",
            })
            if r and (r.get("id") or r.get("owner_id")): ok_vlt += 1; total_vlt += t["amount"]
            else: fail += 1
        else:
            r = _api("POST", "/transactions", tg_id, {
                "type": t["tipe"], "amount": t["amount"], "desc": t["desc"],
                "category": t["category"], "member": t["member"],
                "date": t["date"], "source": "telegram",
            })
            if r and r.get("id"): ok_reg += 1; total_reg += t["amount"]
            else: fail += 1
    state_pop(chat_id)
    parts = []
    if ok_reg: parts.append(f"📂 {ok_reg} reguler — {fmt_rp(total_reg)}")
    if ok_vlt: parts.append(f"🔐 {ok_vlt} vault — {fmt_rp(total_vlt)}")
    msg = "✅ *Tersimpan!*\n" + "\n".join(parts)
    if fail: msg += f"\n⚠️ {fail} gagal disimpan."
    send(chat_id, msg, keyboard=kb_main())


# ── Fitur: Saldo & Laporan ────────────────────────────────────────────────────

def show_saldo(chat_id, tg_id):
    month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/summary?month={month}", tg_id)
    if not r:
        send(chat_id, "❌ Gagal ambil data.", keyboard=kb_back_main()); return
    pct   = min(int(r.get("savings_rate", 0)), 100)
    bar   = "█" * (pct // 10) + "░" * (10 - pct // 10)
    emoji = "🌟" if pct >= 20 else ("⚠️" if pct < 10 else "👍")
    text  = (
        f"💰 *Ringkasan Keuangan*\n"
        f"📅 {datetime.now().strftime('%B %Y')}\n"
        f"{'─'*28}\n\n"
        f"📈 Pemasukan   : *{fmt_rp(r['income'])}*\n"
        f"📉 Pengeluaran : *{fmt_rp(r['expense'])}*\n"
        f"💵 Saldo Bersih: *{fmt_rp(r['balance'])}*\n\n"
        f"{emoji} Tabungan: *{r['savings_rate']}%*\n"
        f"`{bar}` {pct}%\n\n"
        f"📊 {r['tx_count']} transaksi bulan ini"
    )
    tops = r.get("top_categories", [])[:3]
    if tops:
        text += "\n\n*🔴 Top Pengeluaran:*\n"
        for i, (cat, amt) in enumerate(tops):
            text += f"{'1️⃣2️⃣3️⃣'[i*2:i*2+2]} {cat}: {fmt_rp(amt)}\n"
    send(chat_id, text, keyboard={"inline_keyboard": [[
        {"text": "📋 Laporan Detail", "callback_data": "menu_laporan"},
        {"text": "🏠 Menu Utama",     "callback_data": "menu_utama"},
    ]]})

def show_laporan(chat_id, tg_id, month=None):
    if not month: month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/summary?month={month}", tg_id)
    if not r:
        send(chat_id, "❌ Gagal ambil laporan.", keyboard=kb_back_main()); return
    bulan_id = ["","Januari","Februari","Maret","April","Mei","Juni",
                "Juli","Agustus","September","Oktober","November","Desember"]
    y, m_num = month.split("-")
    lines = [
        f"📊 *Laporan Detail*",
        f"📅 {bulan_id[int(m_num)]} {y}",
        f"{'─'*28}\n",
        f"💰 Pemasukan  : *{fmt_rp(r['income'])}*",
        f"💸 Pengeluaran: *{fmt_rp(r['expense'])}*",
        f"💵 Saldo      : *{fmt_rp(r['balance'])}*\n",
    ]
    tops = r.get("top_categories", [])
    if tops:
        lines.append("*📊 Pengeluaran per Kategori:*")
        emojis = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣"]
        for i, (cat, amt) in enumerate(tops[:6]):
            pct = round(amt/r["expense"]*100) if r["expense"] > 0 else 0
            bar = "█"*(pct//10) + "░"*(10-pct//10)
            lines.append(f"{emojis[i]} *{cat}*\n   `{bar}` {pct}% — {fmt_rp(amt)}")
    alerts = [b for b in r.get("budget_status", []) if b.get("alert")]
    if alerts:
        lines.append("\n*⚠️ Budget Alert:*")
        for b in alerts:
            icon = "🔴" if b["over"] else "🟡"
            lines.append(f"{icon} {b['category']}: {b['pct']}% dari budget")
    m_int = int(m_num)
    prev = f"{int(y)-1}-12" if m_int == 1 else f"{y}-{m_int-1:02d}"
    nxt  = f"{int(y)+1}-01" if m_int == 12 else f"{y}-{m_int+1:02d}"
    now_month = datetime.now().strftime("%Y-%m")
    nav = [{"text": f"⬅️ {bulan_id[int(prev.split('-')[1])]}", "callback_data": f"laporan_{prev}"}]
    if month < now_month:
        nav.append({"text": f"{bulan_id[int(nxt.split('-')[1])]} ➡️", "callback_data": f"laporan_{nxt}"})
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard": [nav,
        [{"text": "💸 Catat Pengeluaran", "callback_data": "menu_transaksi"},
         {"text": "🏠 Menu Utama",        "callback_data": "menu_utama"}]]})


# ── Fitur: Riwayat & Hapus ────────────────────────────────────────────────────

def show_riwayat(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    r = _api("GET", f"/transactions?member={u['display_name']}", tg_id)
    txs = r[:7] if isinstance(r, list) else []
    if not txs:
        send(chat_id, f"📭 Belum ada transaksi.", keyboard=kb_back_main()); return
    lines = [f"🕐 *Riwayat Transaksi*\n👤 {u['display_name']}\n{'─'*24}\n"]
    for t in txs:
        icon = "💚" if t["type"] == "inc" else "❤️"
        sign = "+" if t["type"] == "inc" else "-"
        src  = "📱" if t.get("source") == "telegram" else "🖥"
        lines.append(
            f"{icon} *{t.get('desc','?')}* {src}\n"
            f"   🏷 {t['category']} • {sign}{fmt_rp(t['amount'])}\n"
            f"   📅 {t['date']}"
        )
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard": [[
        {"text": "➕ Tambahkan Transaksi", "callback_data": "menu_tambah_multi"},
        {"text": "🏠 Menu Utama",          "callback_data": "menu_utama"},
    ]]})

def show_hapus(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    endpoint = "/transactions" if u["role"] == "admin" else f"/transactions?member={u['display_name']}"
    r = _api("GET", endpoint, tg_id)
    txs = sorted(r, key=lambda t: t.get("date",""), reverse=True)[:10] if isinstance(r, list) else []
    if not txs:
        send(chat_id, "📭 Tidak ada transaksi untuk dihapus.", keyboard=kb_back_main()); return
    send(chat_id, f"🗑 *Hapus Transaksi*\nPilih transaksi yang ingin dihapus:\n_(10 transaksi terakhir)_")
    for t in txs:
        icon = "💚" if t["type"] == "inc" else "❤️"
        sign = "+" if t["type"] == "inc" else "-"
        send(chat_id,
             f"{icon} *{t.get('desc','?')}* — {sign}{fmt_rp(t['amount'])}\n"
             f"📅 {t['date']} • 🏷 {t['category']} • 👤 {t.get('member','')}",
             keyboard={"inline_keyboard": [[
                 {"text": f"🗑 Hapus", "callback_data": f"hapus_{t['id']}"},
             ]]})

# ── Fitur: Vault Pribadi ──────────────────────────────────────────────────────

def show_vault_menu(chat_id, tg_id):
    u = _get_linked(tg_id)
    if not u: return
    send(chat_id,
         f"🔐 *Private Vault*\n"
         f"━━━━━━━━━━━━━━━━━━━━\n"
         f"👤 {u['display_name']}\n\n"
         f"Catatan keuangan pribadi yang hanya\n"
         f"bisa dilihat oleh kamu sendiri 🔒\n\n"
         f"Pilih menu:",
         keyboard={"inline_keyboard": [
             [{"text": "💸 Catat Keluar", "callback_data": "vault_keluar"},
              {"text": "💰 Catat Masuk",  "callback_data": "vault_masuk"}],
             [{"text": "📊 Ringkasan",    "callback_data": "vault_ringkasan"},
              {"text": "🕐 Riwayat",      "callback_data": "vault_riwayat"}],
             [{"text": "🔙 Menu Utama",   "callback_data": "menu_utama"}],
         ]})

def show_vault_ringkasan(chat_id, tg_id):
    month = datetime.now().strftime("%Y-%m")
    r = _api("GET", f"/private/summary?month={month}", tg_id)
    if not r:
        send(chat_id, "❌ Gagal ambil data vault.", keyboard=kb_back_main()); return
    bulan_id = ["","Januari","Februari","Maret","April","Mei","Juni",
                "Juli","Agustus","September","Oktober","November","Desember"]
    m_num = int(month.split("-")[1]); y = month.split("-")[0]
    send(chat_id,
         f"🔐 *Vault — Ringkasan*\n"
         f"📅 {bulan_id[m_num]} {y}\n"
         f"{'─'*24}\n\n"
         f"💰 Pemasukan   : *{fmt_rp(r['income'])}*\n"
         f"💸 Pengeluaran : *{fmt_rp(r['expense'])}*\n"
         f"💵 Saldo       : *{fmt_rp(r['balance'])}*\n"
         f"📊 {r['tx_count']} catatan",
         keyboard={"inline_keyboard": [[
             {"text": "🕐 Riwayat Vault", "callback_data": "vault_riwayat"},
             {"text": "🔙 Vault",         "callback_data": "menu_vault"},
         ]]})

def show_vault_riwayat(chat_id, tg_id):
    r = _api("GET", "/private/transactions", tg_id)
    txs = r[:7] if isinstance(r, list) else []
    if not txs:
        send(chat_id, "📭 Vault masih kosong.", keyboard={"inline_keyboard": [[
            {"text": "➕ Catat", "callback_data": "vault_keluar"},
            {"text": "🔙 Vault", "callback_data": "menu_vault"},
        ]]}); return
    lines = [f"🔐 *Vault — Riwayat Terakhir*\n{'─'*24}\n"]
    for t in txs:
        icon = "💚" if t.get("type") == "inc" else "❤️"
        sign = "+" if t.get("type") == "inc" else "-"
        lines.append(
            f"{icon} *{t.get('note_desc','?')}*\n"
            f"   🏷 {t.get('category','?')} • {sign}{fmt_rp(t['amount'])}\n"
            f"   📅 {t.get('date','')}"
        )
    send(chat_id, "\n".join(lines), keyboard={"inline_keyboard": [[
        {"text": "➕ Catat Baru", "callback_data": "vault_keluar"},
        {"text": "🔙 Vault",      "callback_data": "menu_vault"},
    ]]})


# ── Scan Struk (Groq Vision) ──────────────────────────────────────────────────

def start_scan(chat_id, tg_id):
    """Langkah 1: tanya jenis transaksi dulu."""
    state_set(chat_id, {"step": "scan_tipe", "telegram_id": str(tg_id)})
    send(chat_id,
         "📷 *Scan Struk / Nota / Slip Gaji*\n\n"
         "Ini transaksi pengeluaran atau pemasukan?",
         keyboard={"inline_keyboard": [[
             {"text": "✅ Jenis: Pengeluaran 💸", "callback_data": "scan_tipe_exp"},
             {"text": "✅ Jenis: Pemasukan 💰",  "callback_data": "scan_tipe_inc"},
         ],[
             {"text": "❌ Batal", "callback_data": "batal"},
         ]]})

def ask_scan_photo(chat_id, tipe):
    """Langkah 2: minta kirim foto."""
    label = "Pengeluaran 💸" if tipe == "exp" else "Pemasukan 💰"
    send(chat_id,
         f"✅ Jenis: *{label}*\n\n"
         f"Sekarang kirim foto struk/nota/slip gaji.\n\n"
         f"💡 *Tips foto yang baik:*\n"
         f"• Cahaya cukup, tidak gelap\n"
         f"• Teks angka terlihat jelas\n"
         f"• Tidak blur / goyang\n"
         f"• Foto lurus, tidak miring\n\n"
         f"📲 Pilih dari galeri atau ambil foto sekarang 👇",
         keyboard={"inline_keyboard": [[
             {"text": "❌ Batal", "callback_data": "batal"},
         ]]})

def handle_photo(msg):
    """Langkah 3: proses foto dengan Groq Vision."""
    chat_id = msg["chat"]["id"]
    tg_id   = str(msg.get("from", {}).get("id", chat_id))
    u = _get_linked(tg_id)
    if not u:
        send(chat_id, "🔐 Login dulu dengan /login"); return

    s = state_get(chat_id)
    tipe = s.get("tipe", "exp")
    label = "Pengeluaran 💸" if tipe == "exp" else "Pemasukan 💰"

    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("ISI_"):
        send(chat_id, "⚠️ Groq API Key belum diset di server."); return

    send(chat_id,
         f"📷 *Foto diterima! ({label})*\n"
         f"⏳ Sedang membaca struk/nota dengan AI...\n"
         f"Mohon tunggu sebentar")

    try:
        photos   = msg.get("photo", [])
        if not photos:
            send(chat_id, "❌ Tidak ada foto terdeteksi."); return
        file_id  = photos[-1]["file_id"]
        fi       = tg("getFile", file_id=file_id)
        fp       = fi.get("result", {}).get("file_path")
        if not fp:
            send(chat_id, "❌ Gagal ambil foto dari Telegram."); return

        img_resp = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=30)
        if not img_resp.ok:
            send(chat_id, "❌ Gagal download foto."); return
        b64 = base64.b64encode(img_resp.content).decode()

        groq_resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": (
                        "Kamu adalah asisten pencatat keuangan.\n"
                        "Baca gambar struk/nota/slip gaji ini dan ekstrak:\n"
                        "- Deskripsi transaksi utama (singkat, bahasa Indonesia)\n"
                        "- Total nominal (angka saja)\n"
                        "- Tanggal (format YYYY-MM-DD, kosong jika tidak ada)\n"
                        "- Nama toko/sumber (jika ada)\n\n"
                        "Jawab HANYA dengan JSON:\n"
                        '{"desc":"deskripsi","amount":12000,"date":"2024-01-15","source_name":"nama toko"}\n'
                        "Jika bukan struk/nota: {\"error\":\"bukan struk\"}"
                    )},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}]
            },
            headers={"Authorization": f"Bearer {GEMINI_API_KEY}",
                     "Content-Type": "application/json"},
            timeout=40
        )

        if groq_resp.status_code == 429:
            send(chat_id, "⏳ *Groq sedang sibuk (rate limit).*\n\nTunggu 1 menit lalu kirim foto lagi.", keyboard=kb_back_main()); return
        if not groq_resp.ok:
            send(chat_id, f"❌ Groq error {groq_resp.status_code}. Coba lagi.", keyboard=kb_back_main()); return

        content = groq_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            send(chat_id, "⚠️ AI tidak bisa membaca struk. Coba foto lebih terang.", keyboard=kb_back_main()); return

        data = json.loads(json_match.group())
        if "error" in data:
            send(chat_id, f"⚠️ {data['error']}. Pastikan foto adalah struk/nota.", keyboard=kb_back_main()); return

        desc        = str(data.get("desc", "Transaksi")).strip().title()
        amount      = int(data.get("amount", 0))
        date_str    = data.get("date", "") or datetime.now().strftime("%Y-%m-%d")
        source_name = data.get("source_name", "")
        cat         = smart_category(desc, tipe)

        if amount <= 0:
            send(chat_id, "⚠️ Nominal tidak terdeteksi. Coba foto lebih dekat.", keyboard=kb_back_main()); return

        # Simpan state untuk konfirmasi
        state_set(chat_id, {
            "step":     "scan_konfirmasi",
            "tipe":     tipe,
            "desc":     desc,
            "amount":   amount,
            "date":     date_str,
            "category": cat,
            "source_name": source_name,
        })

        icon  = "💸" if tipe == "exp" else "💰"
        label = "Pengeluaran" if tipe == "exp" else "Pemasukan"
        note  = f"\n_{source_name}_" if source_name else ""
        send(chat_id,
             f"✅ *Berhasil membaca struk!*\n\n"
             f"{icon} {label}\n"
             f"{'━'*20}\n"
             f"📝 Keterangan : *{desc}*\n"
             f"🏷️ Kategori   : *{cat}*\n"
             f"💵 Nominal    : *{fmt_rp(amount)}*\n"
             f"📅 Tanggal    : *{date_str}*\n"
             f"{'━'*20}{note}\n\n"
             f"Simpan transaksi ini?",
             keyboard=kb_konfirmasi(tipe))

    except json.JSONDecodeError:
        send(chat_id, "⚠️ Format respons AI tidak valid. Coba lagi.", keyboard=kb_back_main())
    except Exception as e:
        logging.error(f"handle_photo error: {e}")
        send(chat_id, "❌ Terjadi kesalahan saat scan. Coba lagi.", keyboard=kb_back_main())


# ── Konfirmasi simpan (dari scan atau input manual) ───────────────────────────

def do_simpan_tx(chat_id, tg_id, s):
    """Simpan transaksi dari state s — bisa dari input manual maupun scan struk."""
    u = _get_linked(tg_id)
    if not u:
        send(chat_id, "❌ Sesi kamu sudah habis. Ketik /login untuk masuk kembali.")
        return
    tipe   = s.get("tipe", "exp")
    amount = s.get("amount")
    desc   = s.get("desc")
    cat    = s.get("category", "Lainnya")
    date   = s.get("date", datetime.now().strftime("%Y-%m-%d"))

    if not amount or not desc:
        logging.error(f"do_simpan_tx: data tidak lengkap — amount={amount} desc={desc} state={s}")
        send(chat_id, "❌ Data transaksi tidak lengkap. Coba lagi.", keyboard=kb_back_main())
        return

    logging.info(f"[Bot] Simpan TX: {tipe} {amount} {desc} {cat} → {u['display_name']}")
    r = _api("POST", "/transactions", tg_id, {
        "type":     tipe,
        "amount":   amount,
        "desc":     desc,
        "category": cat,
        "member":   u["display_name"],
        "date":     date,
        "source":   "telegram",
    })
    state_pop(chat_id)
    if r and r.get("id"):
        send(chat_id,
             f"✅ *Tersimpan!*\n\n"
             f"{'❤️' if tipe=='exp' else '💚'} *{fmt_rp(amount)}*\n"
             f"📝 {desc}\n"
             f"🏷 {cat}",
             keyboard={"inline_keyboard": [[
                 {"text": "➕ Catat Lagi",  "callback_data": "menu_transaksi"},
                 {"text": "🏠 Menu Utama", "callback_data": "menu_utama"},
             ]]})
    else:
        logging.error(f"do_simpan_tx: API response = {r}")
        send(chat_id,
             "❌ *Gagal menyimpan transaksi.*\n\n"
             "Kemungkinan penyebab:\n"
             "• Sesi login habis — coba /logout lalu /login\n"
             "• Server sedang bermasalah — coba lagi",
             keyboard=kb_back_main())

def do_simpan_vault(chat_id, tg_id, s):
    """Simpan ke vault dari state s."""
    tipe = s.get("tipe", "exp")
    r = _api("POST", "/private/transactions", tg_id, {
        "type":     tipe,
        "amount":   s["amount"],
        "desc":     s["desc"],
        "category": s["category"],
        "date":     s.get("date", datetime.now().strftime("%Y-%m-%d")),
        "source":   "telegram",
    })
    state_pop(chat_id)
    if r and (r.get("id") or r.get("owner_id")):
        send(chat_id,
             f"✅ *Tersimpan di Vault!*\n\n"
             f"{'❤️' if tipe=='exp' else '💚'} *{fmt_rp(s['amount'])}*\n"
             f"📝 {s['desc']}\n🏷 {s['category']}",
             keyboard={"inline_keyboard": [[
                 {"text": "🔐 Menu Vault", "callback_data": "menu_vault"},
                 {"text": "🏠 Menu",       "callback_data": "menu_utama"},
             ]]})
    else:
        send(chat_id, "❌ Gagal simpan vault.", keyboard=kb_back_main())


# ── Handler: pesan teks ───────────────────────────────────────────────────────

def handle_message(msg):
    if not msg: return
    chat_id = msg.get("chat", {}).get("id")
    tg_id   = str(msg.get("from", {}).get("id", ""))
    text    = msg.get("text", "").strip()

    # Foto
    if msg.get("photo"):
        handle_photo(msg); return

    if not chat_id or not text: return

    s   = state_get(chat_id)
    u   = _get_linked(tg_id)
    cmd = text.split()[0].lower().split("@")[0]

    # ── Flow login ────────────────────────────────────────────────────────────
    if s.get("step") == "login_username":
        state_set(chat_id, {"step": "login_password", "username": text})
        send(chat_id, "🔑 Masukkan *password* kamu:"); return

    if s.get("step") == "login_password":
        username = s.get("username", "")
        state_pop(chat_id)
        send(chat_id, "⏳ Memverifikasi...")
        do_link_account(chat_id, tg_id, username, text); return

    # ── Flow input transaksi manual (single) ──────────────────────────────────
    if s.get("step") == "input_tx":
        amount = parse_amount(text)
        if not amount:
            send(chat_id, "⚠️ Nominal tidak terbaca.\nContoh: `makan siang 25000` atau `gaji 5jt`"); return
        desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?', '', text, flags=re.IGNORECASE).strip()
        desc = desc_raw.title() if desc_raw else ("Pemasukan" if s["tipe"] == "inc" else "Pengeluaran")
        cat  = smart_category(desc, s["tipe"])
        state_set(chat_id, {**s, "step": "konfirmasi_tx", "amount": amount, "desc": desc, "category": cat})
        icon  = "💸" if s["tipe"] == "exp" else "💰"
        label = "Pengeluaran" if s["tipe"] == "exp" else "Pemasukan"
        send(chat_id,
             f"{icon} *Konfirmasi {label}*\n\n"
             f"📝 Keterangan : *{desc}*\n"
             f"🏷 Kategori   : *{cat}*\n"
             f"💵 Nominal    : *{fmt_rp(amount)}*\n"
             f"📅 Tanggal    : *{datetime.now().strftime('%d %b %Y')}*\n\n"
             f"Simpan transaksi ini?",
             keyboard=kb_konfirmasi(s["tipe"])); return

    # ── Flow input vault manual ───────────────────────────────────────────────
    if s.get("step") == "vault_input":
        amount = parse_amount(text)
        if not amount:
            send(chat_id, "⚠️ Nominal tidak terbaca."); return
        desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?', '', text, flags=re.IGNORECASE).strip()
        desc = desc_raw.title() if desc_raw else ("Pemasukan" if s["tipe"] == "inc" else "Pengeluaran")
        cat  = smart_category(desc, s["tipe"])
        state_set(chat_id, {**s, "step": "vault_konfirmasi", "amount": amount, "desc": desc, "category": cat})
        send(chat_id,
             f"🔐 *Konfirmasi Vault*\n\n"
             f"📝 {desc}\n🏷 {cat}\n💵 {fmt_rp(amount)}\n\n"
             f"Simpan ke vault pribadi?",
             keyboard={"inline_keyboard": [[
                 {"text": "✅ Simpan",  "callback_data": "vault_simpan_ok"},
                 {"text": "❌ Batal",   "callback_data": "batal"},
             ]]}); return

    # ── Flow multi-input unified ──────────────────────────────────────────────
    if s.get("step") == "multi_input":
        if not u: return
        txs, errors = parse_unified_tx(text, u["display_name"], tg_id)
        if not txs and errors:
            send(chat_id, f"⚠️ Tidak ada transaksi yang terbaca.\n\n" + "\n".join(errors[:3]))
            return
        state_set(chat_id, {**s, "step": "multi_konfirmasi", "txs": txs})
        show_unified_verify(chat_id, txs, errors); return

    # ── Perintah ──────────────────────────────────────────────────────────────
    if cmd in ("/start", "/menu"):
        if u: show_main_menu(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/login":
        state_set(chat_id, {"step": "login_username"})
        send(chat_id, "👤 Masukkan *username* akun Dompet-KU kamu:")

    elif cmd == "/logout":
        _unlink(tg_id); state_pop(chat_id)
        send(chat_id, "✅ Berhasil logout.\n\nKetik /login untuk masuk kembali.")

    elif cmd == "/saldo":
        if u: show_saldo(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/laporan":
        if u: show_laporan(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/riwayat":
        if u: show_riwayat(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/hapus":
        if u: show_hapus(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/vault":
        if u: show_vault_menu(chat_id, tg_id)
        else: send_login_prompt(chat_id)

    elif cmd == "/id":
        send(chat_id, f"🆔 *Telegram ID kamu:*\n`{tg_id}`")

    elif cmd == "/cek":
        if not u: send_login_prompt(chat_id); return
        month = datetime.now().strftime("%Y-%m")
        r = _api("GET", f"/summary?month={month}", tg_id)
        if not r: send(chat_id, "❌ Gagal ambil data."); return
        alerts = [b for b in r.get("budget_status", []) if b.get("alert")]
        if not alerts:
            send(chat_id, "✅ Semua budget masih aman bulan ini!", keyboard=kb_back_main()); return
        lines = ["⚠️ *Budget Alert Bulan Ini:*\n"]
        for b in alerts:
            icon = "🔴" if b["over"] else "🟡"
            lines.append(f"{icon} *{b['category']}*: {b['pct']}% dari budget\n   Terpakai: {fmt_rp(b['spent'])} / {fmt_rp(b['budget'])}")
        send(chat_id, "\n".join(lines), keyboard=kb_back_main())

    elif cmd == "/bantuan":
        send(chat_id,
             "❓ *Panduan Dompet-KU Bot*\n\n"
             "*Perintah:*\n"
             "• /start atau /menu — menu utama\n"
             "• /login — hubungkan akun\n"
             "• /logout — keluar akun\n"
             "• /saldo — saldo bulan ini\n"
             "• /laporan — laporan keuangan\n"
             "• /riwayat — transaksi terakhir\n"
             "• /hapus — hapus transaksi\n"
             "• /vault — catatan pribadi\n"
             "• /cek — cek status budget\n"
             "• /id — lihat Telegram ID kamu\n\n"
             "*Input cepat:*\n"
             "`makan siang 25000`\n"
             "`bensin 80rb`\n"
             "`gaji 5juta masuk`\n\n"
             "📷 Kirim *foto struk* untuk scan otomatis!",
             keyboard=kb_back_main())

    else:
        # Input bebas — coba parse sebagai transaksi atau multi-baris
        if not u: send_login_prompt(chat_id); return
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) > 1:
            # Multi-baris → unified parser
            txs, errors = parse_unified_tx(text, u["display_name"], tg_id)
            if txs:
                state_set(chat_id, {"step": "multi_konfirmasi", "txs": txs})
                show_unified_verify(chat_id, txs, errors)
            elif errors:
                show_main_menu(chat_id, tg_id)
        else:
            # Satu baris → coba parse sebagai pengeluaran cepat
            amount = parse_amount(text)
            if amount:
                desc_raw = re.sub(r'[\d.,]+(rb|ribu|jt|juta|k\b)?', '', text, flags=re.IGNORECASE).strip()
                desc = desc_raw.title() if desc_raw else "Pengeluaran"
                cat  = smart_category(desc, "exp")
                state_set(chat_id, {"step":"konfirmasi_tx","tipe":"exp",
                                    "amount":amount,"desc":desc,"category":cat})
                send(chat_id,
                     f"💸 *Pengeluaran terdeteksi*\n\n"
                     f"📝 {desc}\n🏷 {cat}\n💵 {fmt_rp(amount)}\n\n"
                     f"Simpan transaksi ini?",
                     keyboard=kb_konfirmasi("exp"))
            else:
                show_main_menu(chat_id, tg_id)


# ── Handler: callback query ───────────────────────────────────────────────────

def handle_callback(cb):
    if not cb: return
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    data    = cb.get("data", "")
    tg_id   = str(cb.get("from", {}).get("id", ""))
    answer_cb(cb["id"])

    u = _get_linked(tg_id)
    s = state_get(chat_id)

    # ── Navigasi dasar ────────────────────────────────────────────────────────
    if data == "menu_utama":
        state_pop(chat_id)
        show_main_menu(chat_id, tg_id); return

    if data == "batal":
        state_pop(chat_id)
        show_main_menu(chat_id, tg_id, "❌ Dibatalkan."); return

    # ── Login/daftar via tombol ───────────────────────────────────────────────
    if data == "do_login":
        state_set(chat_id, {"step": "login_username"})
        send(chat_id, "👤 Masukkan *username* akun Dompet-KU kamu:"); return

    if data == "do_daftar":
        send(chat_id,
             "📝 *Daftar Keluarga Baru*\n\n"
             "Buka link berikut di browser untuk mendaftar:\n"
             f"🌐 {os.environ.get('PUBLIC_URL', 'https://web-production-a4f09.up.railway.app')}\n\n"
             "Setelah terdaftar, kembali ke sini dan ketik /login"); return

    if not u:
        send(chat_id, "🔐 Ketik /login untuk masuk."); return

    # ── Menu utama ────────────────────────────────────────────────────────────
    if data == "menu_transaksi":
        send(chat_id,
             "📝 *Catat Transaksi*\n\n"
             "Pilih jenis transaksi:",
             keyboard={"inline_keyboard": [[
                 {"text": "💸 Pengeluaran", "callback_data": "tx_tipe_exp"},
                 {"text": "💰 Pemasukan",   "callback_data": "tx_tipe_inc"},
             ],[
                 {"text": "📋 Multi-baris (banyak sekaligus)", "callback_data": "menu_tambah_multi"},
             ],[
                 {"text": "❌ Batal", "callback_data": "batal"},
             ]]}); return

    if data == "tx_tipe_exp":
        state_set(chat_id, {"step": "input_tx", "tipe": "exp"})
        send(chat_id,
             "💸 *Catat Pengeluaran*\n\n"
             "Ketik nominal dan keterangan:\n\n"
             "*Contoh:*\n`makan siang 25000`\n`bensin 80rb`\n`belanja 250ribu`",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return

    if data == "tx_tipe_inc":
        state_set(chat_id, {"step": "input_tx", "tipe": "inc"})
        send(chat_id,
             "💰 *Catat Pemasukan*\n\n"
             "Ketik nominal dan keterangan:\n\n"
             "*Contoh:*\n`gaji 5juta`\n`freelance 500rb`",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return

    if data == "menu_tambah_multi":
        state_set(chat_id, {"step": "multi_input", "tipe": "exp"})
        send(chat_id,
             "➕ *Tambahkan Transaksi*\n"
             "─────────────────────────\n"
             "1 baris = 1 transaksi\n\n"
             "*Format:*\n"
             "`[nominal] [keterangan] [jenis] [mode]`\n\n"
             "*Jenis* — wajib salah satu:\n"
             "`masuk` → pemasukan\n"
             "`keluar` → pengeluaran _(default jika tidak ditulis)_\n\n"
             "*Mode* — opsional:\n"
             "`vault` → simpan ke catatan pribadi 🔐\n\n"
             "*Contoh:*\n"
             "`37000 beli air mineral keluar`\n"
             "`150000 gaji freelance masuk`\n"
             "`50000 makan padang keluar vault`\n"
             "`500000 bonus proyek masuk vault`\n\n"
             "💡 Kategori otomatis terdeteksi. Boleh typo 😊\n\n"
             "Kirim semua sekaligus 👆",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return

    if data == "menu_scan":
        start_scan(chat_id, tg_id); return

    if data == "scan_tipe_exp":
        state_set(chat_id, {"step": "scan_tunggu_foto", "tipe": "exp"})
        ask_scan_photo(chat_id, "exp"); return

    if data == "scan_tipe_inc":
        state_set(chat_id, {"step": "scan_tunggu_foto", "tipe": "inc"})
        ask_scan_photo(chat_id, "inc"); return

    if data == "menu_saldo":
        show_saldo(chat_id, tg_id); return

    if data == "menu_laporan":
        show_laporan(chat_id, tg_id); return

    if data.startswith("laporan_"):
        show_laporan(chat_id, tg_id, data[8:]); return

    if data == "menu_riwayat":
        show_riwayat(chat_id, tg_id); return

    if data == "menu_hapus":
        show_hapus(chat_id, tg_id); return

    if data == "menu_vault":
        show_vault_menu(chat_id, tg_id); return

    if data == "vault_keluar":
        state_set(chat_id, {"step": "vault_input", "tipe": "exp"})
        send(chat_id, "🔐 💸 *Vault — Catat Keluar*\n\nKetik nominal dan keterangan:",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return

    if data == "vault_masuk":
        state_set(chat_id, {"step": "vault_input", "tipe": "inc"})
        send(chat_id, "🔐 💰 *Vault — Catat Masuk*\n\nKetik nominal dan keterangan:",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return

    if data == "vault_ringkasan":
        show_vault_ringkasan(chat_id, tg_id); return

    if data == "vault_riwayat":
        show_vault_riwayat(chat_id, tg_id); return

    if data == "vault_simpan_ok":
        if s.get("step") == "vault_konfirmasi":
            do_simpan_vault(chat_id, tg_id, s)
        return

    if data == "menu_bantuan":
        send(chat_id,
             "❓ *Panduan Dompet-KU Bot*\n\n"
             "• /menu — menu utama\n"
             "• /saldo — saldo bulan ini\n"
             "• /laporan — laporan keuangan\n"
             "• /riwayat — transaksi terakhir\n"
             "• /hapus — hapus transaksi\n"
             "• /vault — catatan pribadi\n"
             "• /cek — cek budget alert\n"
             "• /id — lihat Telegram ID\n"
             "• /logout — keluar akun\n\n"
             "📷 Kirim *foto struk* untuk scan otomatis!",
             keyboard=kb_back_main()); return

    # ── Simpan transaksi ──────────────────────────────────────────────────────
    if data in ("simpan_exp", "simpan_inc"):
        # Terima dari input manual (konfirmasi_tx) MAUPUN dari scan (scan_konfirmasi)
        if s.get("step") in ("konfirmasi_tx", "scan_konfirmasi"):
            do_simpan_tx(chat_id, tg_id, s)
        return

    if data in ("ubah_exp", "ubah_inc"):
        tipe = data.split("_")[1]
        # Pertahankan semua data state, hanya ubah step agar bisa input ulang
        state_set(chat_id, {**s, "step": "input_tx", "tipe": tipe})
        send(chat_id, "✏️ Ketik ulang nominal dan keterangan:"); return

    # ── Hapus transaksi ───────────────────────────────────────────────────────
    if data.startswith("hapus_"):
        tx_id = data.split("_")[1]
        r = None
        try:
            sess = u["session_token"]
            resp = requests.delete(f"{API_URL}/transactions/{tx_id}",
                                   cookies={"dompetku_session": sess}, timeout=10)
            r = resp.ok
        except Exception as e:
            logging.error(f"hapus TX: {e}")
        if r:
            send(chat_id, "✅ Transaksi berhasil dihapus.", keyboard=kb_back_main())
        else:
            send(chat_id, "❌ Gagal menghapus transaksi.", keyboard=kb_back_main())
        return

    # ── Multi-input ───────────────────────────────────────────────────────────
    if data == "unified_simpan":
        if s.get("step") == "multi_konfirmasi":
            do_unified_simpan(chat_id, tg_id, s.get("txs", []))
        return

    if data == "unified_ulang":
        state_set(chat_id, {"step": "multi_input"})
        send(chat_id,
             "✏️ Ketik ulang transaksi kamu.\n\n"
             "Format: `[nominal] [keterangan] [masuk/keluar] [vault?]`",
             keyboard={"inline_keyboard": [[{"text": "❌ Batal", "callback_data": "batal"}]]}); return


# ── Setup webhook & commands ──────────────────────────────────────────────────

def setup_commands():
    tg("setMyCommands", commands=[
        {"command": "start",   "description": "🏠 Menu Utama"},
        {"command": "menu",    "description": "🏠 Buka Menu"},
        {"command": "login",   "description": "🔑 Hubungkan Akun"},
        {"command": "logout",  "description": "🚪 Keluar Akun"},
        {"command": "saldo",   "description": "💰 Cek Saldo Bulan Ini"},
        {"command": "laporan", "description": "📋 Laporan Pengeluaran"},
        {"command": "riwayat", "description": "🕐 Riwayat Transaksi"},
        {"command": "hapus",   "description": "🗑 Hapus Transaksi"},
        {"command": "vault",   "description": "🔐 Private Vault"},
        {"command": "cek",     "description": "⚠️ Cek Budget Sekarang"},
        {"command": "id",      "description": "🆔 Lihat Telegram ID"},
        {"command": "bantuan", "description": "❓ Panduan Penggunaan"},
    ])
    logging.info("[Bot] Commands registered.")

def start_scheduler():
    """Placeholder — tidak dipakai di webhook mode."""
    pass

