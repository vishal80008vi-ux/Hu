"""
╔══════════════════════════════════════════════════════════════╗
║        BIGBASKET ₹100 OFF COUPON BOT  —  Full Rewrite        ║
║  Coupon: ₹100 OFF on Chocolates & Ice Cream on BigBasket     ║
║  • 1 coupon per referral (friend must join all channels)      ║
║  • Admin adds/removes force-join channels from Telegram       ║
║  • Full admin panel: users, coupons, broadcast, export        ║
║  python-telegram-bot == 20.7  |  SQLite                       ║
╚══════════════════════════════════════════════════════════════╝

INSTALL:   pip install python-telegram-bot==20.7
RUN:       python bot.py
"""

import sqlite3, logging, csv, asyncio, io
from datetime import datetime, date
from functools import wraps

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ══════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════
BOT_TOKEN    = "8767852570:AAFyDX9H_rIEksqeOH6LSeoPkcM7xWLceJw"   # from @BotFather
ADMIN_IDS    = [7550749598]             # your Telegram numeric user ID(s)
SUPPORT_LINK = "https://t.me/byteclaude"
DB_FILE      = "bot.db"
PAGE_SIZE    = 8

# Coupon details — shown everywhere to users
COUPON_OFFER      = "₹100 OFF"
COUPON_PRODUCT    = "Chocolates & Ice Cream"
COUPON_PLATFORM   = "BigBasket App / Website"
COUPON_MIN_ORDER  = "₹100"

# ══════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════
def get_db():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            username       TEXT    DEFAULT '',
            full_name      TEXT    DEFAULT '',
            referred_by    INTEGER DEFAULT NULL,
            invite_count   INTEGER DEFAULT 0,
            coupons_given  INTEGER DEFAULT 0,
            all_joined     INTEGER DEFAULT 0,
            is_banned      INTEGER DEFAULT 0,
            ban_reason     TEXT    DEFAULT '',
            joined_at      TEXT    DEFAULT '',
            last_active    TEXT    DEFAULT '',
            last_action    TEXT    DEFAULT 'Started bot'
        );

        CREATE TABLE IF NOT EXISTS channels (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   TEXT    UNIQUE NOT NULL,
            title     TEXT    DEFAULT '',
            link      TEXT    DEFAULT '',
            added_at  TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS coupon_pool (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            code  TEXT    UNIQUE NOT NULL,
            used  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS coupon_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            coupon_code TEXT    NOT NULL,
            issued_at   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS referral_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            full_name   TEXT    DEFAULT '',
            credited_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS bot_logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            level     TEXT,
            message   TEXT
        );

        INSERT OR IGNORE INTO settings VALUES ('bot_active',   '1');
        INSERT OR IGNORE INTO settings VALUES ('welcome_msg',  '');
        INSERT OR IGNORE INTO settings VALUES ('policy_text',  '');
    """)
    con.commit()
    con.close()
    log.info("Database ready.")

# ── Helpers ───────────────────────────────────────────────────
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def cfg(key, fallback=""):
    con = get_db()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else fallback

def set_cfg(key, val):
    con = get_db()
    con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, val))
    con.commit(); con.close()

def bot_log(level, msg):
    con = get_db()
    con.execute("INSERT INTO bot_logs (timestamp,level,message) VALUES (?,?,?)",
                (now(), level, msg))
    con.commit(); con.close()

# ── User helpers ──────────────────────────────────────────────
def get_user(uid):
    con = get_db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return dict(row) if row else None

def upsert_user(uid, username, full_name, referred_by=None):
    """Returns True if brand new user."""
    con = get_db()
    t   = now()
    ex  = con.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
    if not ex:
        con.execute(
            "INSERT INTO users "
            "(user_id,username,full_name,referred_by,joined_at,last_active) "
            "VALUES (?,?,?,?,?,?)",
            (uid, username, full_name, referred_by, t, t),
        )
        con.commit(); con.close()
        return True
    con.execute(
        "UPDATE users SET username=?,full_name=?,last_active=? WHERE user_id=?",
        (username, full_name, t, uid),
    )
    con.commit(); con.close()
    return False

def update_user(uid, **kw):
    con = get_db()
    sets = ", ".join(f"{k}=?" for k in kw)
    con.execute(f"UPDATE users SET {sets} WHERE user_id=?",
                list(kw.values()) + [uid])
    con.commit(); con.close()

def touch(uid, action):
    con = get_db()
    con.execute("UPDATE users SET last_active=?,last_action=? WHERE user_id=?",
                (now(), action, uid))
    con.commit(); con.close()

# ── Channel helpers ───────────────────────────────────────────
def get_channels():
    con  = get_db()
    rows = con.execute("SELECT * FROM channels ORDER BY id").fetchall()
    con.close()
    return [dict(r) for r in rows]

def add_channel(chat_id, title, link):
    con = get_db()
    try:
        con.execute(
            "INSERT INTO channels (chat_id,title,link,added_at) VALUES (?,?,?,?)",
            (str(chat_id), title, link, now()),
        )
        con.commit(); con.close()
        return True
    except sqlite3.IntegrityError:
        con.close()
        return False

def remove_channel(ch_id):
    con = get_db()
    con.execute("DELETE FROM channels WHERE id=?", (ch_id,))
    con.commit(); con.close()

# ── Coupon helpers ────────────────────────────────────────────
def pool_count():
    con = get_db()
    n   = con.execute("SELECT COUNT(*) FROM coupon_pool WHERE used=0").fetchone()[0]
    con.close()
    return n

def take_coupon():
    con = get_db()
    row = con.execute(
        "SELECT id,code FROM coupon_pool WHERE used=0 LIMIT 1").fetchone()
    if not row:
        con.close(); return None
    con.execute("UPDATE coupon_pool SET used=1 WHERE id=?", (row["id"],))
    con.commit(); con.close()
    return row["code"]

def save_coupon_history(uid, code):
    con = get_db()
    con.execute(
        "INSERT INTO coupon_history (user_id,coupon_code,issued_at) VALUES (?,?,?)",
        (uid, code, now()),
    )
    con.commit(); con.close()

def get_coupon_history(uid):
    con  = get_db()
    rows = con.execute(
        "SELECT coupon_code,issued_at FROM coupon_history "
        "WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

# ── Referral helpers ──────────────────────────────────────────
def save_ref_log(referrer_id, referred_id, full_name):
    con = get_db()
    ex  = con.execute(
        "SELECT id FROM referral_log WHERE referrer_id=? AND referred_id=?",
        (referrer_id, referred_id)).fetchone()
    if not ex:
        con.execute(
            "INSERT INTO referral_log "
            "(referrer_id,referred_id,full_name,credited_at) VALUES (?,?,?,?)",
            (referrer_id, referred_id, full_name, now()),
        )
        con.commit()
    con.close()

def get_ref_log(uid):
    con  = get_db()
    rows = con.execute(
        "SELECT full_name,credited_at FROM referral_log "
        "WHERE referrer_id=? ORDER BY id DESC", (uid,)).fetchall()
    con.close()
    return [dict(r) for r in rows]

# ── Stats ─────────────────────────────────────────────────────
def get_stats():
    con = get_db()
    td  = date.today().strftime("%Y-%m-%d")
    s   = {}
    s["total_users"]   = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s["today_joins"]   = con.execute(
        "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{td}%",)).fetchone()[0]
    s["total_refs"]    = con.execute("SELECT COUNT(*) FROM referral_log").fetchone()[0]
    s["total_coupons"] = con.execute("SELECT COUNT(*) FROM coupon_history").fetchone()[0]
    s["pool_left"]     = con.execute(
        "SELECT COUNT(*) FROM coupon_pool WHERE used=0").fetchone()[0]
    s["pool_total"]    = con.execute("SELECT COUNT(*) FROM coupon_pool").fetchone()[0]
    s["banned"]        = con.execute(
        "SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    top = con.execute(
        "SELECT username,full_name,invite_count FROM users "
        "ORDER BY invite_count DESC LIMIT 1").fetchone()
    s["top_referrer"] = (
        f"@{top['username']} ({top['invite_count']} refs)"
        if top and top["username"] else (top["full_name"] if top else "—")
    )
    con.close()
    return s

def get_users_page(page):
    con   = get_db()
    rows  = con.execute(
        "SELECT user_id,username,full_name,last_active,last_action,"
        "is_banned,invite_count,coupons_given "
        "FROM users ORDER BY last_active DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, page * PAGE_SIZE)).fetchall()
    total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return [dict(r) for r in rows], total

# ══════════════════════════════════════════════════════════════
#  GUARDS
# ══════════════════════════════════════════════════════════════
def admin_only(fn):
    @wraps(fn)
    async def wrap(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if update.effective_user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ Unauthorized.")
            return
        return await fn(update, ctx, *a, **kw)
    return wrap

async def check_channels(bot, uid):
    """
    Returns (all_joined: bool, missing: list[dict])
    Checks every channel in DB. If no channels added, returns (True, []).
    """
    channels = get_channels()
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch["chat_id"], uid)
            if m.status not in ("member", "administrator", "creator"):
                missing.append(ch)
        except TelegramError:
            missing.append(ch)
    return len(missing) == 0, missing

# ══════════════════════════════════════════════════════════════
#  TEXT & KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════════════
MAIN_KB = ReplyKeyboardMarkup([
    [KeyboardButton("🎁 GET COUPON"),    KeyboardButton("👥 REFER & EARN")],
    [KeyboardButton("📋 COUPON POLICY"), KeyboardButton("🛠️ SUPPORT")],
], resize_keyboard=True, is_persistent=True)

def welcome_text(first_name):
    custom = cfg("welcome_msg")
    if custom:
        return custom.replace("{name}", first_name)
    return (
        "╔════════════════════════════════╗\n"
        "║  🍫  𝗕𝗜𝗚𝗕𝗔𝗦𝗞𝗘𝗧 𝗖𝗢𝗨𝗣𝗢𝗡 𝗕𝗢𝗧  🍦  ║\n"
        "╚════════════════════════════════╝\n\n"
        f"𝗪𝗲𝗹𝗰𝗼𝗺𝗲, <b>{first_name}</b>! 👋🎉\n\n"
        f"🎁 <b>Get {COUPON_OFFER} FREE on {COUPON_PRODUCT}!</b>\n"
        f"🛒 Order on {COUPON_PLATFORM}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>How to get your coupon:</b>\n\n"
        "  1️⃣ Share your referral link\n"
        "  2️⃣ Friend joins our channel(s)\n"
        "  3️⃣ You instantly get <b>1 coupon code!</b> 🎟️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 Choose an option below:"
    )

def force_join_text(missing):
    ch_lines = "\n".join(
        f"  ➡️ <b>{ch['title'] or ch['chat_id']}</b>"
        for ch in missing
    )
    return (
        "⚠️ <b>Join Required!</b>\n\n"
        "Please join the channel(s) below\n"
        "to access this bot:\n\n"
        f"{ch_lines}\n\n"
        "✅ After joining, tap <b>I've Joined</b>."
    )

def force_join_kb(missing):
    rows = []
    for ch in missing:
        label = f"🔔 Join  {ch['title'] or ch['chat_id']}"
        url   = ch["link"] if ch["link"] else f"https://t.me/{ch['chat_id'].lstrip('@')}"
        rows.append([InlineKeyboardButton(label, url=url)])
    rows.append([InlineKeyboardButton(
        "✅ I've Joined — Check Again", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)

def policy_text():
    custom = cfg("policy_text")
    if custom:
        return custom
    return (
        "📋 <b>COUPON POLICY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎁 <b>Offer       :</b> {COUPON_OFFER} Discount\n"
        f"🍫 <b>Valid on    :</b> {COUPON_PRODUCT}\n"
        f"🛒 <b>Platform    :</b> {COUPON_PLATFORM}\n"
        f"💰 <b>Min. Order  :</b> {COUPON_MIN_ORDER}\n\n"
        "🔗 <b>How to earn coupons:</b>\n"
        "  • Share your unique referral link\n"
        "  • Each friend who joins = 1 coupon code\n"
        "  • Friend must join ALL channels first\n\n"
        "⚠️ <b>Rules:</b>\n"
        "  • New users only per referral\n"
        "  • No self-referral allowed\n"
        "  • Each coupon code is single-use\n"
        "  • Codes are non-transferable\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Misuse leads to a permanent ban.</i>"
    )

def coupon_display(codes):
    """Format list of coupon codes into a stylish box."""
    lines = "\n".join(
        f"┃  {i+1}. <code>{c}</code>"
        for i, c in enumerate(codes)
    )
    return (
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"{lines}\n"
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
    )

def activity_badge(last_str):
    if not last_str:
        return "⚫ Never"
    try:
        diff = datetime.now() - datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
        m    = diff.total_seconds() / 60
        if m < 5:    return "🟢 Online"
        if m < 60:   return f"🟡 {int(m)}m ago"
        if m < 1440: return f"🟠 {int(m//60)}h ago"
        return f"🔴 {diff.days}d ago"
    except Exception:
        return "⚫ Unknown"

# ══════════════════════════════════════════════════════════════
#  ATOMIC JOIN MARK  (prevents double credit on button spam)
# ══════════════════════════════════════════════════════════════
def atomic_mark_joined(uid):
    """
    Sets all_joined=1 only if it was 0.
    Returns referred_by on the very FIRST mark, else None.
    This is the single gate that prevents double credit.
    """
    con = get_db()
    cur = con.execute(
        "UPDATE users SET all_joined=1 WHERE user_id=? AND all_joined=0", (uid,))
    changed = cur.rowcount
    con.commit()
    if not changed:
        con.close(); return None
    row = con.execute("SELECT referred_by FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return row["referred_by"] if row else None

# ══════════════════════════════════════════════════════════════
#  CREDIT REFERRER + SEND NOTIFICATION
# ══════════════════════════════════════════════════════════════
async def credit_and_notify(bot, referrer_id, new_uid, new_fname):
    ref = get_user(referrer_id)
    if not ref or ref["is_banned"]:
        return

    new_count = ref["invite_count"] + 1
    given     = ref["coupons_given"]
    unclaimed = new_count - given

    update_user(referrer_id, invite_count=new_count)
    save_ref_log(referrer_id, new_uid, new_fname)
    bot_log("INFO", f"Credit: {referrer_id} ← {new_uid}. Invites={new_count}")

    if unclaimed > 0:
        action_line = (
            f"\n\n🎉 <b>You now have {unclaimed} unclaimed coupon(s)!</b>\n"
            "Tap 🎁 <b>GET COUPON</b> to claim now."
        )
    else:
        action_line = "\n\nTap 👥 <b>REFER &amp; EARN</b> to track progress."

    try:
        await bot.send_message(
            chat_id=referrer_id,
            parse_mode=ParseMode.HTML,
            text=(
                "🔔 <b>New Referral Joined!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 <b>{new_fname}</b> joined via your link\n"
                "and completed all channel joins! ✅\n\n"
                f"👥 Total referrals  : <b>{new_count}</b>\n"
                f"🎟️ Coupons earned  : <b>{new_count}</b>\n"
                f"✅ Coupons claimed : <b>{given}</b>"
                + action_line
            ),
        )
    except TelegramError as e:
        log.warning(f"Notify referrer {referrer_id}: {e}")

# ══════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id

    if cfg("bot_active") != "1" and uid not in ADMIN_IDS:
        await update.message.reply_text(
            "🔧 Bot is under maintenance. Please check back soon!")
        return

    # Parse referral payload: /start ref_12345
    ref_id = None
    if ctx.args and ctx.args[0].startswith("ref_"):
        try:
            ref_id = int(ctx.args[0][4:])
            if ref_id == uid:
                ref_id = None   # block self-referral
        except ValueError:
            pass

    is_new = upsert_user(uid, user.username or "", user.full_name, ref_id)

    # Force-join check
    all_in, missing = await check_channels(ctx.bot, uid)
    if not all_in:
        await update.message.reply_html(
            force_join_text(missing),
            reply_markup=force_join_kb(missing),
        )
        return

    # All channels joined — credit referrer once
    if is_new:
        referrer = atomic_mark_joined(uid)
        if referrer:
            await credit_and_notify(ctx.bot, referrer, uid, user.full_name)
    else:
        update_user(uid, all_joined=1)

    touch(uid, "Started bot")
    await update.message.reply_html(
        welcome_text(user.first_name), reply_markup=MAIN_KB)
    bot_log("INFO", f"Start: {uid} @{user.username}")

# ══════════════════════════════════════════════════════════════
#  check_join CALLBACK  (I've Joined button)
# ══════════════════════════════════════════════════════════════
async def cb_check_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    all_in, missing = await check_channels(ctx.bot, uid)

    if not all_in:
        await q.edit_message_text(
            force_join_text(missing)
            + "\n\n❌ <b>You haven't joined all channels yet!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=force_join_kb(missing),
        )
        return

    # Atomic mark — fires credit exactly once
    referrer = atomic_mark_joined(uid)
    if referrer:
        u = get_user(uid)
        await credit_and_notify(
            ctx.bot, referrer, uid,
            u["full_name"] if u else q.from_user.full_name,
        )

    try:
        await q.delete_message()
    except TelegramError:
        pass

    touch(uid, "Completed channel join")
    await ctx.bot.send_message(
        chat_id=uid,
        text=welcome_text(q.from_user.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KB,
    )

# ══════════════════════════════════════════════════════════════
#  MAIN MESSAGE ROUTER
# ══════════════════════════════════════════════════════════════
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id
    text = update.message.text or ""

    if cfg("bot_active") != "1" and uid not in ADMIN_IDS:
        await update.message.reply_text("🔧 Bot under maintenance.")
        return

    u = get_user(uid)
    if not u:
        await cmd_start(update, ctx)
        return

    if u["is_banned"]:
        await update.message.reply_text(
            f"🚫 You are banned.\n"
            f"Reason: {u['ban_reason'] or 'Policy violation'}\n"
            f"Contact: {SUPPORT_LINK}")
        return

    # Force-join guard on every message
    all_in, missing = await check_channels(ctx.bot, uid)
    if not all_in:
        await update.message.reply_html(
            force_join_text(missing),
            reply_markup=force_join_kb(missing))
        return

    if text == "🎁 GET COUPON":
        touch(uid, "Tapped GET COUPON")
        await handle_get_coupon(update, uid)

    elif text == "👥 REFER & EARN":
        touch(uid, "Tapped REFER & EARN")
        await handle_refer(update, ctx, uid)

    elif text == "📋 COUPON POLICY":
        touch(uid, "Read policy")
        await update.message.reply_html(policy_text())

    elif text == "🛠️ SUPPORT":
        touch(uid, "Contacted support")
        await update.message.reply_html(
            f"🛠️ <b>Support</b>\n\nContact us here:\n👉 {SUPPORT_LINK}")

    else:
        await update.message.reply_html(
            "👇 Please use the buttons below.", reply_markup=MAIN_KB)

# ══════════════════════════════════════════════════════════════
#  GET COUPON
# ══════════════════════════════════════════════════════════════
async def handle_get_coupon(update: Update, uid: int):
    u             = get_user(uid)
    invite_count  = u["invite_count"]
    coupons_given = u["coupons_given"]
    unclaimed     = invite_count - coupons_given
    history       = get_coupon_history(uid)

    # History block shown at the bottom always
    def history_block():
        if not history:
            return ""
        lines = "\n".join(
            f"  {i+1}. <code>{r['coupon_code']}</code>  "
            f"·  {r['issued_at'][5:16]}"
            for i, r in enumerate(history)
        )
        return (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗂️ <b>Your Coupon History ({len(history)}):</b>\n\n"
            + lines
        )

    # No referrals at all
    if invite_count == 0:
        await update.message.reply_html(
            "🔒 <b>No coupons yet!</b>\n\n"
            "You haven't referred anyone successfully yet.\n\n"
            "📌 <b>To earn coupons:</b>\n"
            "  • Tap 👥 REFER &amp; EARN\n"
            "  • Share your referral link\n"
            "  • Each friend who joins = <b>1 coupon 🎁</b>"
        )
        return

    # All earned coupons already claimed
    if unclaimed == 0:
        await update.message.reply_html(
            f"✅ <b>All {coupons_given} coupon(s) already claimed!</b>\n\n"
            "Refer more friends to earn more coupon codes.\n"
            "Tap 👥 <b>REFER &amp; EARN</b> for your link."
            + history_block()
        )
        return

    # Coupons waiting but pool is empty
    if pool_count() == 0:
        await update.message.reply_html(
            "😔 <b>Out of Stock!</b>\n\n"
            f"You have <b>{unclaimed}</b> coupon(s) waiting,\n"
            "but we've run out of codes right now.\n\n"
            "Please check back soon!\n"
            f"👉 {SUPPORT_LINK}"
            + history_block()
        )
        return

    # Issue all unclaimed coupons now
    given_codes = []
    for _ in range(unclaimed):
        code = take_coupon()
        if not code:
            break
        save_coupon_history(uid, code)
        given_codes.append(code)

    if not given_codes:
        await update.message.reply_text("⚠️ Something went wrong. Try again.")
        return

    update_user(uid, coupons_given=coupons_given + len(given_codes))
    bot_log("COUPON",
            f"User {uid} claimed {len(given_codes)} coupon(s): {given_codes}")

    still_pending = unclaimed - len(given_codes)
    pending_note  = (
        f"\n\n⚠️ <i>{still_pending} more code(s) pending — "
        "pool refill needed.</i>"
        if still_pending > 0 else ""
    )

    n = len(given_codes)
    await update.message.reply_html(
        f"🎉 <b>Here {'is' if n == 1 else 'are'} your "
        f"coupon {'code' if n == 1 else 'codes'}!</b>\n\n"
        + coupon_display(given_codes)
        + f"\n\n🍫 <b>{COUPON_OFFER} OFF on {COUPON_PRODUCT}</b>\n"
        f"🛒 Apply on {COUPON_PLATFORM}\n"
        f"💰 Min. order: {COUPON_MIN_ORDER}\n"
        "⚠️ <i>Single use · Non-transferable</i>"
        + pending_note
        + history_block()
    )

# ══════════════════════════════════════════════════════════════
#  REFER & EARN
# ══════════════════════════════════════════════════════════════
async def handle_refer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid: int):
    u             = get_user(uid)
    invite_count  = u["invite_count"] if u else 0
    coupons_given = u["coupons_given"] if u else 0
    unclaimed     = invite_count - coupons_given
    ref_link      = f"https://t.me/{ctx.bot.username}?start=ref_{uid}"
    ref_hist      = get_ref_log(uid)

    if unclaimed > 0:
        status = (
            f"🎁 <b>{unclaimed} coupon(s) ready!</b> "
            "Tap 🎁 GET COUPON to claim."
        )
    else:
        status = (
            f"<b>{invite_count}</b> referral(s) total  |  "
            f"<b>{coupons_given}</b> coupon(s) claimed"
        )

    # Referral history — names only, no usernames
    if ref_hist:
        hist_lines = "\n".join(
            f"  {i+1}. 👤 <b>{r['full_name']}</b>"
            f"  ·  {r['credited_at'][5:16]}"
            for i, r in enumerate(ref_hist[:20])
        )
    else:
        hist_lines = "  No referrals yet — share your link! 👆"

    await update.message.reply_html(
        "👥 <b>REFER &amp; EARN FREE COUPONS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 {status}\n\n"
        f"👥 Total Referrals  : <b>{invite_count}</b>\n"
        f"🎟️ Coupons Claimed  : <b>{coupons_given}</b>\n\n"
        "📌 <b>Rules:</b>\n"
        "  • Friend must be new to this bot\n"
        "  • Friend must join ALL channels ✅\n"
        "  • No self-referral 🚫\n"
        "  • 1 referral = 1 coupon code 🎁\n\n"
        "💡 <i>Share on WhatsApp, Instagram, groups!</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 <b>Your Referral History ({len(ref_hist)}):</b>\n\n"
        + hist_lines
    )

# ══════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════
ADMIN_HOME_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 Statistics",   callback_data="adm_stats"),
     InlineKeyboardButton("👥 Users",        callback_data="adm_users_0")],
    [InlineKeyboardButton("📢 Channels",     callback_data="adm_channels"),
     InlineKeyboardButton("🎟️ Coupon Pool",  callback_data="adm_coupon")],
    [InlineKeyboardButton("📣 Broadcast",    callback_data="adm_broadcast"),
     InlineKeyboardButton("🚫 Ban Manager",  callback_data="adm_ban_menu")],
    [InlineKeyboardButton("🔗 Referral Mgr", callback_data="adm_referral"),
     InlineKeyboardButton("📥 Export",       callback_data="adm_export")],
    [InlineKeyboardButton("⚙️ Settings",     callback_data="adm_settings"),
     InlineKeyboardButton("📋 Logs",         callback_data="adm_logs")],
])

def admin_home_text():
    s = get_stats()
    return (
        "╔══════════════════════════════╗\n"
        "║   ⚙️  𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗡𝗧𝗥𝗢𝗟 𝗣𝗔𝗡𝗘𝗟   ║\n"
        "╚══════════════════════════════╝\n\n"
        f"👥 Total Users    : <b>{s['total_users']}</b>"
        f"  (Today: +{s['today_joins']})\n"
        f"🔗 Total Referrals: <b>{s['total_refs']}</b>\n"
        f"🎟️ Coupons Issued : <b>{s['total_coupons']}</b>\n"
        f"📦 Pool Remaining : <b>{s['pool_left']}</b>"
        f" / {s['pool_total']}\n"
        f"🔗 Top Referrer   : <b>{s['top_referrer']}</b>\n\n"
        f"🕐 <i>{datetime.now().strftime('%d %b %Y, %I:%M %p')}</i>"
    )

# Channel panel helpers
def channels_text():
    chs = get_channels()
    if not chs:
        body = "  <i>No channels added yet.</i>\n\n" \
               "Add one so users must join before using the bot."
    else:
        body = "\n\n".join(
            f"  {i+1}. <b>{ch['title'] or ch['chat_id']}</b>\n"
            f"      ID: <code>{ch['chat_id']}</code>\n"
            f"      Link: {ch['link'] or 'N/A'}"
            for i, ch in enumerate(chs)
        )
    return (
        "📢 <b>FORCE-JOIN CHANNELS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + body
        + "\n\n<i>Users must join ALL channels above.</i>"
    )

def channels_kb():
    rows = []
    for ch in get_channels():
        rows.append([InlineKeyboardButton(
            f"🗑️ Remove: {ch['title'] or ch['chat_id']}",
            callback_data=f"adm_ch_del_{ch['id']}")])
    rows.append([InlineKeyboardButton(
        "➕ Add Channel / Group", callback_data="adm_ch_add")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="adm_home")])
    return InlineKeyboardMarkup(rows)

# Coupon panel helpers
def coupon_text_panel():
    con   = get_db()
    total = con.execute("SELECT COUNT(*) FROM coupon_pool").fetchone()[0]
    used  = con.execute("SELECT COUNT(*) FROM coupon_pool WHERE used=1").fetchone()[0]
    con.close()
    return (
        "🎟️ <b>COUPON POOL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Total Added : <b>{total}</b>\n"
        f"✅ Used        : <b>{used}</b>\n"
        f"📭 Remaining   : <b>{total - used}</b>\n"
    )

def coupon_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📤 Add Coupons (.txt or paste)", callback_data="adm_coupon_add")],
        [InlineKeyboardButton(
            "🗑️ Clear Unused Coupons", callback_data="adm_coupon_clear")],
        [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
    ])

# Settings panel helpers
def settings_text():
    ba = cfg("bot_active")
    return (
        "⚙️ <b>SETTINGS</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 Bot Status : "
        f"{'✅ LIVE' if ba == '1' else '🔧 MAINTENANCE'}\n"
    )

def settings_kb():
    ba = cfg("bot_active")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🤖 {'Turn OFF (go to maintenance)' if ba=='1' else 'Turn ON (go live)'}",
            callback_data="adm_toggle_bot")],
        [InlineKeyboardButton(
            "📝 Edit Welcome Message", callback_data="adm_edit_welcome")],
        [InlineKeyboardButton(
            "📋 Edit Policy Text", callback_data="adm_edit_policy")],
        [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
    ])

# Users page helper
def users_page(page):
    rows, total = get_users_page(page)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if not rows:
        return "👥 No users yet.", None

    lines = [
        f"👥 <b>USERS</b>  Page {page+1}/{pages}"
        f"  (Total: {total})\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for r in rows:
        badge  = activity_badge(r["last_active"])
        ban    = " 🚫" if r["is_banned"] else ""
        uname  = f"@{r['username']}" if r["username"] else "no username"
        try:
            la = datetime.strptime(
                r["last_active"], "%Y-%m-%d %H:%M:%S"
            ).strftime("%d %b, %I:%M %p")
        except Exception:
            la = r["last_active"] or "N/A"
        lines.append(
            f"<b>{r['full_name']}</b>{ban}\n"
            f"  🆔 <code>{r['user_id']}</code>  {uname}\n"
            f"  {badge}  |  🕐 {la}\n"
            f"  📌 <i>{r['last_action'] or 'N/A'}</i>\n"
            f"  👥 Refs: {r['invite_count']}"
            f"  🎟️ Given: {r['coupons_given']}\n"
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "◀️ Prev", callback_data=f"adm_users_{page-1}"))
    if (page + 1) < pages:
        nav.append(InlineKeyboardButton(
            "Next ▶️", callback_data=f"adm_users_{page+1}"))

    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([
        InlineKeyboardButton("🔍 Lookup", callback_data="adm_lookup"),
        InlineKeyboardButton("🔙 Back",   callback_data="adm_home"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        admin_home_text(), reply_markup=ADMIN_HOME_KB)

# ══════════════════════════════════════════════════════════════
#  ADMIN CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════
async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()

    if uid not in ADMIN_IDS:
        await q.edit_message_text("⛔ Unauthorized.")
        return

    # ── Home ──────────────────────────────────────────────
    if data == "adm_home":
        await q.edit_message_text(
            admin_home_text(), parse_mode=ParseMode.HTML,
            reply_markup=ADMIN_HOME_KB)

    # ── Statistics ────────────────────────────────────────
    elif data == "adm_stats":
        s = get_stats()
        await q.edit_message_text(
            "📊 <b>STATISTICS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Total Users     : <b>{s['total_users']}</b>\n"
            f"🆕 Today Joins     : <b>{s['today_joins']}</b>\n"
            f"🚫 Banned          : <b>{s['banned']}</b>\n\n"
            f"🔗 Total Referrals : <b>{s['total_refs']}</b>\n"
            f"🎟️ Coupons Issued  : <b>{s['total_coupons']}</b>\n"
            f"🔗 Top Referrer    : <b>{s['top_referrer']}</b>\n\n"
            f"📦 Pool Left       : <b>{s['pool_left']}"
            f"</b> / {s['pool_total']}\n\n"
            f"🕐 <i>{datetime.now().strftime('%d %b %Y, %I:%M %p')}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🏆 Top 10 Referrers", callback_data="adm_top10")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]),
        )

    elif data == "adm_top10":
        con  = get_db()
        rows = con.execute(
            "SELECT user_id,username,full_name,invite_count "
            "FROM users ORDER BY invite_count DESC LIMIT 10"
        ).fetchall()
        con.close()
        lines = "\n".join(
            f"  {i+1}. "
            f"{'@'+r['username'] if r['username'] else r['full_name']}"
            f" — <b>{r['invite_count']} refs</b>"
            for i, r in enumerate(rows)
        ) or "No data yet."
        await q.edit_message_text(
            f"🏆 <b>Top 10 Referrers</b>\n━━━━━━━━━━━━━━━━━\n\n{lines}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="adm_stats")]]),
        )

    # ── Users (paginated) ─────────────────────────────────
    elif data.startswith("adm_users_"):
        page = int(data.split("_")[-1])
        result = users_page(page)
        if result[1] is None:
            await q.edit_message_text(result[0]); return
        text, kb = result
        await q.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb)

    # ── Channels Manager ──────────────────────────────────
    elif data == "adm_channels":
        await q.edit_message_text(
            channels_text(), parse_mode=ParseMode.HTML,
            reply_markup=channels_kb())

    elif data == "adm_ch_add":
        ctx.user_data["adm_action"] = "add_channel"
        await q.edit_message_text(
            "➕ <b>Add Force-Join Channel / Group</b>\n\n"
            "Send the channel username, ID, or link:\n\n"
            "Format options:\n"
            "• <code>@channelname</code>\n"
            "• <code>-1001234567890</code> (private channel ID)\n"
            "• <code>https://t.me/channelname</code>\n"
            "• <code>@ch | Title | https://t.me/invite</code>\n\n"
            "⚠️ Make this bot an <b>admin</b> of the channel first!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_channels")]]),
        )

    elif data.startswith("adm_ch_del_"):
        ch_id = int(data.split("_")[-1])
        remove_channel(ch_id)
        bot_log("INFO", f"Admin removed channel id={ch_id}")
        await q.edit_message_text(
            "✅ Channel removed.\n\n" + channels_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=channels_kb(),
        )

    # ── Coupon Pool ───────────────────────────────────────
    elif data == "adm_coupon":
        await q.edit_message_text(
            coupon_text_panel(), parse_mode=ParseMode.HTML,
            reply_markup=coupon_kb())

    elif data == "adm_coupon_add":
        ctx.user_data["adm_action"] = "add_coupons"
        await q.edit_message_text(
            "📤 <b>Add Coupon Codes</b>\n\n"
            "Send a <b>.txt file</b> (one code per line)\n"
            "OR type/paste the codes directly (one per line).",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_coupon")]]),
        )

    elif data == "adm_coupon_clear":
        con = get_db()
        con.execute("DELETE FROM coupon_pool WHERE used=0")
        con.commit(); con.close()
        bot_log("INFO", "Admin cleared unused coupon pool.")
        await q.edit_message_text(
            "🗑️ Unused coupons cleared.\n\n" + coupon_text_panel(),
            parse_mode=ParseMode.HTML,
            reply_markup=coupon_kb())

    # ── Broadcast ─────────────────────────────────────────
    elif data == "adm_broadcast":
        await q.edit_message_text(
            "📣 <b>BROADCAST</b>\n\nWho to send to?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👥 All Users", callback_data="adm_bc_all")],
                [InlineKeyboardButton(
                    "🎟️ Got Coupons", callback_data="adm_bc_claimed")],
                [InlineKeyboardButton(
                    "🔗 Referrers", callback_data="adm_bc_referrers")],
                [InlineKeyboardButton(
                    "🆕 Today's Joins", callback_data="adm_bc_today")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]),
        )

    elif data.startswith("adm_bc_") and data != "adm_bc_confirm":
        tmap = {
            "adm_bc_all":       ("all",       "👥 All Users"),
            "adm_bc_claimed":   ("claimed",   "🎟️ Got Coupons"),
            "adm_bc_referrers": ("referrers", "🔗 Referrers"),
            "adm_bc_today":     ("today",     "🆕 Today's Joins"),
        }
        tkey, tname = tmap.get(data, ("all", "All"))
        ctx.user_data["adm_action"]     = "broadcast"
        ctx.user_data["bc_target"]      = tkey
        ctx.user_data["bc_target_name"] = tname
        await q.edit_message_text(
            f"📣 Broadcast to: <b>{tname}</b>\n\n"
            "Send your message now\n"
            "(text, photo, video, or document).",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ Cancel", callback_data="adm_broadcast")]]),
        )
        return

    # ── Ban Manager ───────────────────────────────────────
    elif data == "adm_ban_menu":
        await q.edit_message_text(
            "🚫 <b>BAN MANAGER</b>", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🚫 Ban User", callback_data="adm_ban_p")],
                [InlineKeyboardButton(
                    "✅ Unban User", callback_data="adm_unban_p")],
                [InlineKeyboardButton(
                    "📋 Ban List", callback_data="adm_ban_list")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]))

    elif data == "adm_ban_p":
        ctx.user_data["adm_action"] = "ban_user"
        await q.edit_message_text(
            "🚫 Send: <code>user_id reason</code>\n"
            "Example: <code>123456789 fake referrals</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_ban_menu")]]))

    elif data == "adm_unban_p":
        ctx.user_data["adm_action"] = "unban_user"
        await q.edit_message_text(
            "✅ Send the user ID to unban:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_ban_menu")]]))

    elif data == "adm_ban_list":
        con  = get_db()
        rows = con.execute(
            "SELECT user_id,username,full_name,ban_reason "
            "FROM users WHERE is_banned=1 LIMIT 20").fetchall()
        con.close()
        if not rows:
            body = "✅ No banned users."
        else:
            body = "\n".join(
                f"  🚫 "
                f"{'@'+r['username'] if r['username'] else r['full_name']}"
                f" (<code>{r['user_id']}</code>)"
                f" — {r['ban_reason'] or '—'}"
                for r in rows)
        await q.edit_message_text(
            f"📋 <b>Banned Users</b>\n━━━━━━━━━━━━━━━━━\n\n{body}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="adm_ban_menu")]]))

    # ── Referral Manager ──────────────────────────────────
    elif data == "adm_referral":
        await q.edit_message_text(
            "🔗 <b>REFERRAL MANAGER</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "🎁 Coupons per referral    : <b>1</b>\n"
            "✅ Channel join required   : <b>YES (all channels)</b>\n"
            "🚫 Self-referral blocked   : <b>YES</b>\n"
            "🔔 Referrer notified       : <b>YES (instant)</b>\n",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🏆 Top Referrers", callback_data="adm_top10")],
                [InlineKeyboardButton(
                    "🎁 Manual Credit", callback_data="adm_ref_credit")],
                [InlineKeyboardButton(
                    "🔍 Lookup User", callback_data="adm_lookup")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]))

    elif data == "adm_ref_credit":
        ctx.user_data["adm_action"] = "manual_credit"
        await q.edit_message_text(
            "🎁 Send: <code>user_id count</code>\n"
            "Example: <code>123456789 3</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_referral")]]))

    # ── Export ────────────────────────────────────────────
    elif data == "adm_export":
        await q.edit_message_text(
            "📥 <b>EXPORT</b>", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👥 All Users", callback_data="adm_exp_users")],
                [InlineKeyboardButton(
                    "🎟️ Coupon History", callback_data="adm_exp_coupons")],
                [InlineKeyboardButton(
                    "🔗 Referral Log", callback_data="adm_exp_refs")],
                [InlineKeyboardButton(
                    "🚫 Ban List", callback_data="adm_exp_bans")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]))

    elif data == "adm_exp_users":
        await do_export(q, ctx,
            "SELECT user_id,username,full_name,invite_count,coupons_given,"
            "all_joined,joined_at,last_active,last_action,is_banned FROM users",
            ["user_id","username","full_name","invite_count","coupons_given",
             "all_joined","joined_at","last_active","last_action","is_banned"],
            "users.csv")

    elif data == "adm_exp_coupons":
        await do_export(q, ctx,
            "SELECT ch.user_id,u.username,u.full_name,"
            "ch.coupon_code,ch.issued_at "
            "FROM coupon_history ch "
            "LEFT JOIN users u ON ch.user_id=u.user_id ORDER BY ch.id DESC",
            ["user_id","username","full_name","coupon_code","issued_at"],
            "coupon_history.csv")

    elif data == "adm_exp_refs":
        await do_export(q, ctx,
            "SELECT rl.referrer_id,u.username AS referrer_username,"
            "rl.referred_id,rl.full_name AS referred_name,rl.credited_at "
            "FROM referral_log rl "
            "LEFT JOIN users u ON rl.referrer_id=u.user_id ORDER BY rl.id DESC",
            ["referrer_id","referrer_username",
             "referred_id","referred_name","credited_at"],
            "referrals.csv")

    elif data == "adm_exp_bans":
        await do_export(q, ctx,
            "SELECT user_id,username,full_name,ban_reason "
            "FROM users WHERE is_banned=1",
            ["user_id","username","full_name","ban_reason"],
            "bans.csv")

    # ── Settings ──────────────────────────────────────────
    elif data == "adm_settings":
        await q.edit_message_text(
            settings_text(), parse_mode=ParseMode.HTML,
            reply_markup=settings_kb())

    elif data == "adm_toggle_bot":
        set_cfg("bot_active", "0" if cfg("bot_active") == "1" else "1")
        await q.edit_message_text(
            settings_text(), parse_mode=ParseMode.HTML,
            reply_markup=settings_kb())

    elif data == "adm_edit_welcome":
        ctx.user_data["adm_action"] = "edit_welcome"
        await q.edit_message_text(
            "📝 Send the new welcome message.\n"
            "Use <code>{name}</code> for the user's first name.\n"
            "HTML formatting supported.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_settings")]]))

    elif data == "adm_edit_policy":
        ctx.user_data["adm_action"] = "edit_policy"
        await q.edit_message_text(
            "📋 Send the new policy text (HTML supported):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_settings")]]))

    # ── Logs ──────────────────────────────────────────────
    elif data == "adm_logs":
        con  = get_db()
        rows = con.execute(
            "SELECT timestamp,level,message FROM bot_logs "
            "ORDER BY id DESC LIMIT 15").fetchall()
        con.close()
        icon  = {"INFO":"🟢","COUPON":"🎟️","ERROR":"🔴","WARN":"🟡","BAN":"🚫"}
        lines = "\n".join(
            f"{icon.get(r['level'],'⚪')} [{r['timestamp'][11:16]}] {r['message']}"
            for r in rows
        ) or "No logs yet."
        await q.edit_message_text(
            f"📋 <b>Recent Logs</b>\n━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{lines}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📥 Download bot.log", callback_data="adm_logs_dl")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_home")],
            ]))

    elif data == "adm_logs_dl":
        try:
            with open("bot.log", "rb") as f:
                await ctx.bot.send_document(
                    chat_id=uid, document=f,
                    filename="bot.log", caption="📋 Full bot log")
        except Exception:
            await q.answer("❌ bot.log not found.", show_alert=True)

    # ── Lookup user ───────────────────────────────────────
    elif data == "adm_lookup":
        ctx.user_data["adm_action"] = "lookup_user"
        await q.edit_message_text(
            "🔍 Send a user ID or @username:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_home")]]))

    # ── Give coupon directly ──────────────────────────────
    elif data.startswith("adm_give_"):
        tid  = int(data.split("_")[-1])
        code = take_coupon()
        if code:
            save_coupon_history(tid, code)
            u = get_user(tid)
            if u:
                update_user(tid, coupons_given=u["coupons_given"] + 1)
            try:
                await ctx.bot.send_message(
                    chat_id=tid,
                    parse_mode=ParseMode.HTML,
                    text=(
                        "🎁 <b>Admin sent you a coupon!</b>\n\n"
                        f"<code>{code}</code>\n\n"
                        f"🍫 <b>{COUPON_OFFER} on {COUPON_PRODUCT}</b>\n"
                        f"🛒 {COUPON_PLATFORM}\n"
                        "⚠️ <i>Single use · Non-transferable</i>"
                    ))
            except TelegramError:
                pass
            await q.answer(f"✅ Sent: {code}", show_alert=True)
            bot_log("COUPON", f"Admin gave {code} to {tid}")
        else:
            await q.answer("❌ Pool is empty!", show_alert=True)

    # ── Message a specific user ───────────────────────────
    elif data.startswith("adm_msg_"):
        tid = int(data.split("_")[-1])
        ctx.user_data["adm_action"]    = "msg_user"
        ctx.user_data["msg_target_id"] = tid
        await q.edit_message_text(
            f"📨 Type message for user <code>{tid}</code>:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="adm_home")]]))

# ══════════════════════════════════════════════════════════════
#  BROADCAST CONFIRM
# ══════════════════════════════════════════════════════════════
async def cb_bc_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.from_user.id not in ADMIN_IDS:
        return

    uid_list    = ctx.user_data.get("bc_user_ids", [])
    src_msg_id  = ctx.user_data.get("bc_message_id")
    src_chat_id = ctx.user_data.get("bc_msg_chat_id")

    if not uid_list or not src_msg_id:
        await q.edit_message_text("❌ Data lost — start again.")
        return

    await q.edit_message_text(f"📣 Sending to {len(uid_list)} users…")

    sent = failed = 0
    for uid in uid_list:
        try:
            # copy_message = no "Forwarded from" header
            await ctx.bot.copy_message(
                chat_id=uid,
                from_chat_id=src_chat_id,
                message_id=src_msg_id,
            )
            sent += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)   # stay under Telegram flood limit

    await ctx.bot.send_message(
        chat_id=q.from_user.id,
        parse_mode=ParseMode.HTML,
        text=(
            f"✅ <b>Broadcast Complete!</b>\n"
            f"📬 Sent   : {sent}\n"
            f"❌ Failed : {failed}"
        ))
    bot_log("INFO", f"Broadcast: {sent} sent, {failed} failed.")

# ══════════════════════════════════════════════════════════════
#  CSV EXPORT HELPER
# ══════════════════════════════════════════════════════════════
async def do_export(q, ctx, sql, headers, filename):
    con  = get_db()
    rows = con.execute(sql).fetchall()
    con.close()
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(headers)
    w.writerows([list(r) for r in rows])
    buf.seek(0)
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    data.name = filename
    await ctx.bot.send_document(
        chat_id=q.from_user.id,
        document=data,
        filename=filename,
        caption=f"📥 {filename}  ({len(rows)} rows)",
    )

# ══════════════════════════════════════════════════════════════
#  ADMIN TEXT / FILE INPUT HANDLER
# ══════════════════════════════════════════════════════════════
async def admin_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    action = ctx.user_data.get("adm_action")

    # No pending admin action → behave like regular user
    if not action:
        await handle_message(update, ctx)
        return

    msg  = update.message
    text = msg.text or ""

    # ── Add channel ───────────────────────────────────────
    if action == "add_channel":
        ctx.user_data["adm_action"] = None
        parts   = [p.strip() for p in text.strip().split("|")]
        raw     = parts[0]
        title   = parts[1] if len(parts) > 1 else ""
        link    = parts[2] if len(parts) > 2 else ""

        # Normalise chat_id
        if raw.startswith("https://t.me/"):
            handle  = raw.split("t.me/")[-1].split("/")[0]
            chat_id = f"@{handle}" if not handle.startswith("+") else raw
            if not link:
                link = raw
        elif raw.startswith("@"):
            chat_id = raw
            if not link:
                link = f"https://t.me/{raw[1:]}"
        else:
            chat_id = raw   # numeric ID

        # Auto-resolve title from Telegram
        if not title:
            try:
                chat  = await ctx.bot.get_chat(chat_id)
                title = chat.title or chat.username or str(chat_id)
                if not link and chat.username:
                    link = f"https://t.me/{chat.username}"
            except TelegramError as e:
                await msg.reply_html(
                    f"❌ <b>Cannot access channel:</b> <code>{e}</code>\n\n"
                    "Make sure:\n"
                    "• Bot is an <b>admin</b> of the channel\n"
                    "• Username / ID is correct\n\n"
                    "Try again → Admin → 📢 Channels → ➕ Add")
                return

        ok = add_channel(chat_id, title, link)
        bot_log("INFO", f"Channel {'added' if ok else 'already exists'}: {chat_id}")
        if ok:
            await msg.reply_html(
                f"✅ <b>Channel added!</b>\n\n"
                f"📢 <b>{title}</b>\n"
                f"ID: <code>{chat_id}</code>\n"
                f"Link: {link or 'N/A'}\n\n"
                "Users must now join this channel.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "📢 View Channels", callback_data="adm_channels")]]))
        else:
            await msg.reply_html(
                f"⚠️ <code>{chat_id}</code> is already in the list.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "📢 View Channels", callback_data="adm_channels")]]))

    # ── Add coupons ───────────────────────────────────────
    elif action == "add_coupons":
        ctx.user_data["adm_action"] = None
        doc = msg.document
        if doc:
            f     = await doc.get_file()
            raw   = await f.download_as_bytearray()
            lines = raw.decode("utf-8", errors="ignore").splitlines()
        else:
            lines = text.strip().splitlines()
        codes = [ln.strip() for ln in lines if ln.strip()]
        con   = get_db()
        added = 0
        for c in codes:
            try:
                con.execute(
                    "INSERT OR IGNORE INTO coupon_pool (code) VALUES (?)", (c,))
                added += 1
            except Exception:
                pass
        con.commit(); con.close()
        bot_log("INFO", f"Admin added {added} coupons. Pool={pool_count()}")
        await msg.reply_html(
            f"✅ <b>{added}</b> coupon(s) added.\n"
            f"📦 Pool now: <b>{pool_count()}</b> unused code(s).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🎟️ Coupon Pool", callback_data="adm_coupon")]]))

    # ── Lookup user ───────────────────────────────────────
    elif action == "lookup_user":
        ctx.user_data["adm_action"] = None
        val = text.strip().lstrip("@")
        con = get_db()
        row = (
            con.execute("SELECT * FROM users WHERE user_id=?",
                        (int(val),)).fetchone()
            if val.isdigit()
            else con.execute("SELECT * FROM users WHERE username=?",
                             (val,)).fetchone()
        )
        con.close()
        if not row:
            await msg.reply_text("❌ User not found.")
            return
        u       = dict(row)
        ref_h   = get_ref_log(u["user_id"])
        cpn_h   = get_coupon_history(u["user_id"])
        ref_lines = "\n".join(
            f"  {i+1}. {r['full_name']}  ·  {r['credited_at'][5:16]}"
            for i, r in enumerate(ref_h)) or "  None."
        cpn_lines = "\n".join(
            f"  🏷️ <code>{r['coupon_code']}</code>"
            f"  ·  {r['issued_at'][5:16]}"
            for r in cpn_h) or "  None."
        await msg.reply_html(
            "👤 <b>USER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 ID         : <code>{u['user_id']}</code>\n"
            f"👤 Name       : {u['full_name']}\n"
            f"🔖 Username   : {'@'+u['username'] if u['username'] else 'N/A'}\n"
            f"📅 Joined     : {u['joined_at']}\n"
            f"🔗 Referred by: {u['referred_by'] or 'Direct'}\n"
            f"👥 Invites    : {u['invite_count']}\n"
            f"🎟️ Given      : {u['coupons_given']}\n"
            f"📌 Last Action: {u['last_action']}\n"
            f"🕐 Last Active: {u['last_active']}\n"
            f"🚫 Banned     : "
            f"{'🔴 '+u['ban_reason'] if u['is_banned'] else '✅ No'}\n\n"
            f"👥 <b>Referral History:</b>\n{ref_lines}\n\n"
            f"🎟️ <b>Coupon History:</b>\n{cpn_lines}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🎁 Give Coupon",
                    callback_data=f"adm_give_{u['user_id']}"),
                 InlineKeyboardButton(
                    "📨 Message",
                    callback_data=f"adm_msg_{u['user_id']}")],
                [InlineKeyboardButton("🔙 Home", callback_data="adm_home")],
            ]))

    # ── Ban ───────────────────────────────────────────────
    elif action == "ban_user":
        ctx.user_data["adm_action"] = None
        parts   = text.strip().split(None, 1)
        uid_str = parts[0].lstrip("@")
        reason  = parts[1] if len(parts) > 1 else "Policy violation"
        con = get_db()
        row = (
            con.execute("SELECT user_id,username FROM users WHERE user_id=?",
                        (int(uid_str),)).fetchone()
            if uid_str.isdigit()
            else con.execute("SELECT user_id,username FROM users WHERE username=?",
                             (uid_str,)).fetchone()
        )
        con.close()
        if not row:
            await msg.reply_text("❌ User not found."); return
        update_user(row["user_id"], is_banned=1, ban_reason=reason)
        try:
            await ctx.bot.send_message(
                row["user_id"], f"🚫 You have been banned.\nReason: {reason}")
        except TelegramError:
            pass
        bot_log("BAN", f"Banned {row['user_id']}. Reason: {reason}")
        await msg.reply_text(f"✅ Banned user {row['user_id']}.")

    # ── Unban ─────────────────────────────────────────────
    elif action == "unban_user":
        ctx.user_data["adm_action"] = None
        if text.strip().isdigit():
            update_user(int(text.strip()), is_banned=0, ban_reason="")
            bot_log("INFO", f"Unbanned {text.strip()}")
            await msg.reply_text(f"✅ Unbanned user {text.strip()}.")
        else:
            await msg.reply_text("❌ Send a numeric user ID.")

    # ── Edit welcome ──────────────────────────────────────
    elif action == "edit_welcome":
        ctx.user_data["adm_action"] = None
        set_cfg("welcome_msg", text)
        await msg.reply_text("✅ Welcome message updated!")

    # ── Edit policy ───────────────────────────────────────
    elif action == "edit_policy":
        ctx.user_data["adm_action"] = None
        set_cfg("policy_text", text)
        await msg.reply_text("✅ Policy text updated!")

    # ── Manual credit ─────────────────────────────────────
    elif action == "manual_credit":
        ctx.user_data["adm_action"] = None
        parts = text.strip().split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            tid, cnt = int(parts[0]), int(parts[1])
            u = get_user(tid)
            if u:
                update_user(tid, invite_count=u["invite_count"] + cnt)
                bot_log("INFO", f"Manual credit {cnt} → {tid}")
                await msg.reply_text(
                    f"✅ Added {cnt} referral(s) to {tid}.\n"
                    f"New total: {u['invite_count'] + cnt}")
            else:
                await msg.reply_text("❌ User not found.")
        else:
            await msg.reply_text(
                "❌ Format: <user_id> <count>\nExample: 123456789 3")

    # ── Message user ──────────────────────────────────────
    elif action == "msg_user":
        ctx.user_data["adm_action"] = None
        tid = ctx.user_data.get("msg_target_id")
        if tid:
            try:
                await ctx.bot.send_message(
                    chat_id=tid,
                    parse_mode=ParseMode.HTML,
                    text=f"📨 <b>Message from Admin:</b>\n\n{text}")
                await msg.reply_text(f"✅ Sent to {tid}.")
            except TelegramError as e:
                await msg.reply_text(f"❌ Failed: {e}")

    # ── Broadcast collect ─────────────────────────────────
    elif action == "broadcast":
        ctx.user_data["adm_action"] = None
        target = ctx.user_data.get("bc_target", "all")
        tname  = ctx.user_data.get("bc_target_name", "All")
        today  = date.today().strftime("%Y-%m-%d")
        q_map  = {
            "all":       "SELECT DISTINCT user_id FROM users WHERE is_banned=0",
            "claimed":   "SELECT DISTINCT user_id FROM coupon_history",
            "referrers": "SELECT DISTINCT referrer_id FROM referral_log",
            "today":     (
                f"SELECT user_id FROM users "
                f"WHERE joined_at LIKE '{today}%' AND is_banned=0"
            ),
        }
        con      = get_db()
        rows     = con.execute(q_map.get(target, q_map["all"])).fetchall()
        con.close()
        uid_list = [r[0] for r in rows]
        ctx.user_data["bc_user_ids"]    = uid_list
        ctx.user_data["bc_message_id"]  = msg.message_id
        ctx.user_data["bc_msg_chat_id"] = msg.chat_id
        await msg.reply_html(
            f"📣 <b>Broadcast → {tname}</b>\n"
            f"👥 <b>{len(uid_list)}</b> users\n\nConfirm?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ Send Now", callback_data="adm_bc_confirm"),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data="adm_broadcast"),
            ]]))

# ══════════════════════════════════════════════════════════════
#  ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════
@admin_only
async def cmd_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /ban <user_id> [reason]"); return
    uid    = int(ctx.args[0])
    reason = " ".join(ctx.args[1:]) or "Policy violation"
    update_user(uid, is_banned=1, ban_reason=reason)
    try:
        await ctx.bot.send_message(uid, f"🚫 Banned. Reason: {reason}")
    except TelegramError:
        pass
    bot_log("BAN", f"/ban {uid}: {reason}")
    await update.message.reply_text(f"✅ Banned {uid}.")

@admin_only
async def cmd_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /unban <user_id>"); return
    update_user(int(ctx.args[0]), is_banned=0, ban_reason="")
    await update.message.reply_text(f"✅ Unbanned {ctx.args[0]}.")

@admin_only
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = get_stats()
    await update.message.reply_html(
        f"📊 Users: <b>{s['total_users']}</b>  Today: +<b>{s['today_joins']}</b>\n"
        f"🔗 Refs: <b>{s['total_refs']}</b>  "
        f"🎟️ Issued: <b>{s['total_coupons']}</b>\n"
        f"📦 Pool: <b>{s['pool_left']}</b> remaining")

@admin_only
async def cmd_pool(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📦 Pool: {pool_count()} unused coupon code(s).")

@admin_only
async def cmd_addch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quick: /addch @username  or  /addch -100xxxxxxx"""
    if not ctx.args:
        await update.message.reply_text(
            "Usage: /addch @username\n   or: /addch -100xxxxxxx"); return
    ctx.user_data["adm_action"] = "add_channel"
    update.message.text = ctx.args[0]
    await admin_input(update, ctx)

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
def main():
    init_db()
    log.info("Bot starting…")

    app = Application.builder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", cmd_start))

    # Admin commands
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CommandHandler("ban",    cmd_ban))
    app.add_handler(CommandHandler("unban",  cmd_unban))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("pool",   cmd_pool))
    app.add_handler(CommandHandler("addch",  cmd_addch))

    # Callbacks — specific patterns before general adm_ catch-all
    app.add_handler(CallbackQueryHandler(
        cb_check_join,  pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(
        cb_bc_confirm,  pattern="^adm_bc_confirm$"))
    app.add_handler(CallbackQueryHandler(
        admin_cb,       pattern="^adm_"))

    # Messages — admin handler first; falls through to user handler when idle
    app.add_handler(MessageHandler(
        filters.User(ADMIN_IDS) & ~filters.COMMAND
        & (filters.TEXT | filters.Document.ALL),
        admin_input,
    ))
    app.add_handler(MessageHandler(
        ~filters.COMMAND & filters.TEXT,
        handle_message,
    ))

    log.info("✅ Running. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
