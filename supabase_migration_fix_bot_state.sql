-- ══════════════════════════════════════════════════════════════════
--  Fix: UNIQUE constraint untuk bot_sessions dan bot_linked
--  Jalankan SEKALI di Supabase SQL Editor (Supabase baru vercel)
-- ══════════════════════════════════════════════════════════════════

-- 1. Hapus baris duplikat di bot_sessions (pertahankan yang terbaru)
DELETE FROM bot_sessions
WHERE ctid NOT IN (
  SELECT DISTINCT ON (chat_id) ctid
  FROM bot_sessions
  ORDER BY chat_id, updated_at DESC
);

-- 2. Hapus baris duplikat di bot_linked (pertahankan yang terbaru)
DELETE FROM bot_linked
WHERE ctid NOT IN (
  SELECT DISTINCT ON (telegram_id) ctid
  FROM bot_linked
  ORDER BY telegram_id, updated_at DESC
);

-- 3. Pastikan chat_id sudah PRIMARY KEY (harusnya sudah, tapi tambahkan UNIQUE jika belum)
-- (bot_sessions sudah punya PRIMARY KEY chat_id dari setup awal — skip jika sudah ada)

-- 4. Tambahkan UNIQUE constraint di bot_linked jika belum ada
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'bot_linked_telegram_id_key'
  ) THEN
    ALTER TABLE bot_linked ADD CONSTRAINT bot_linked_telegram_id_key UNIQUE (telegram_id);
  END IF;
END$$;

-- ══════════════════════════════════════════════════════════════════
--  SELESAI
-- ══════════════════════════════════════════════════════════════════
