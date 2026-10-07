import asyncio
import os
import re
import shutil
import json
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

MY_PROC = psutil.Process() if psutil else None
if MY_PROC:
    MY_PROC.cpu_percent(interval=None)
    
from telethon import TelegramClient, events, Button, types, utils
from telethon.errors import UserNotParticipantError, PhoneNumberInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError, SessionPasswordNeededError

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "acbot.py"
SESSIONS = ROOT / "sessions"
DATA = ROOT / "user_data"
SESSIONS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

bot = TelegramClient(str(ROOT / "control_bot"), API_ID, API_HASH)

# ---------- BLOCKQUOTE: bot ke saare messages/captions quote box mein jayenge ----------
# (Telethon purana ho aur blockquote support na ho to: pip install -U telethon)
try:
    from telethon.tl.types import MessageEntityBlockquote, MessageEntityCustomEmoji
    from telethon.extensions import markdown as _tl_md
except Exception:
    MessageEntityBlockquote = None
    MessageEntityCustomEmoji = None

def _u16(text):
    return len(text.encode("utf-16-le")) // 2

# ---------- PREMIUM (CUSTOM) EMOJI ----------
# Format:  "normal emoji": premium_emoji_id,
# Bot ke saare messages/captions/alerts mein wo normal emoji automatically premium ban jayega.
# ID kaise nikale: kisi bhi message mein premium emoji bhejo (ya reply karo) aur bot ko /emojiid bhejo.
# NOTE: premium emoji sirf tab dikhte hain jab bot ka owner Telegram Premium ho; warna normal emoji dikhega.
PREMIUM_EMOJI = {
     "🎩": 5409376095151615368,
     "💎": 5408854995359524419,
     "👤": 5249053508681883137,
     "🔤": 5841276284155467413,
     "🟢": 4958920483492857102,
     "⚡️": 6339079456371511141,
     "🎯": 6172468191671883349,
     "📣": 6206080502651164081,
     "✅": 6206185428702206246,
     "🚨": 6098257904190624738,
     "🌐": 6206293004748068499,
     "🎁": 5411311841206890566,
     "❤️‍🔥": 5278602067634565580,
     "🔓": 5291873529464122510,
     "❌": 5370713555467247906,
     "✍️": 5258500400918587241,
     "📊": 6206343625232619150,
     "🧬": 5316592213008854304,
     "🙂": 6195124844237954893,
     "📡": 6048749957903555159,
     "📄": 5956561916573782596,
     "➡️": 6127514998072680291,
     "💭": 6206503415195899956,
     "💀": 5370598007962083530,
     "🚗": 5233638613358486264,
     "😘": 6307698282118256447,
     "🦚": 6053079272053018699,
     "💋": 5386629424365979714,
     "🍄": 5411513635950325417,
     "🔍": 6206446249181189526,
     "✍️": 5458382591121964689,
     "🔥": 5303489036587933548,
     "🧮": 5046394669366249699,
     "🚫": 6206396878532121864,
     "🛡": 5042328396193864923,
     "👁": 5303259870017932992,
     "📹": 5337301488748211009,
     "🔗": 6206497372176913599,
     "📌": 6206190608432764318,
     "👻": 5818704139365914137,
     "🔓": 5291873529464122510,
     "🔍": 5303398614641453311,
     "➕": 6206375377925839184,
     "🧹": 6271644466914790278,
     "🏷": 5987802868734760945,
     "🌕": 6195126497800365212,
     "👑": 6206096153511990389,
     "👨‍👩‍👧": 6082576398772345226,
     "🗑": 4958534924278694938,
     "💬": 6206495649895028694,
     "👀": 6206366384264320881,
     "⭕️": 5949775417274536507,
     "🎅": 5303355737982942267,
}

_FE0F = "\ufe0f"
_PREM_MAP = {}
_PREM_RE = None

def _rebuild_premium():
    global _PREM_MAP, _PREM_RE
    _PREM_MAP = {k.replace(_FE0F, ""): int(v) for k, v in PREMIUM_EMOJI.items() if v}
    if not _PREM_MAP:
        _PREM_RE = None
        return
    keys = sorted(_PREM_MAP, key=len, reverse=True)
    _PREM_RE = re.compile("(?:" + "|".join(re.escape(k) for k in keys) + ")" + _FE0F + "?")

_rebuild_premium()

def _premium_entities(text):
    """text ke andar mapped emojis ke liye MessageEntityCustomEmoji list banata hai."""
    if not _PREM_RE or not text or MessageEntityCustomEmoji is None:
        return []
    out = []
    for m in _PREM_RE.finditer(text):
        eid = _PREM_MAP.get(m.group(0).replace(_FE0F, ""))
        if eid:
            out.append(MessageEntityCustomEmoji(_u16(text[:m.start()]), _u16(m.group(0)), eid))
    return out

def _premium_html(text):
    """HTML text mein mapped emojis ko <tg-emoji> premium se replace karta hai (acbot userbot ke liye).
    Pehle se <tg-emoji> mein wrapped emoji ko dobara wrap nahi karta."""
    if not _PREM_RE or not isinstance(text, str):
        return text
    rx = re.compile(r"(<tg-emoji\b.*?</tg-emoji>)|(" + _PREM_RE.pattern + ")", re.S)
    def _sub(m):
        if m.group(1):
            return m.group(1)
        ch = m.group(2)
        eid = _PREM_MAP.get(ch.replace(_FE0F, ""))
        return f'<tg-emoji emoji-id="{eid}">{ch}</tg-emoji>' if eid else ch
    return rx.sub(_sub, text)

_PREM_WARNED = False

def _check_premium(sent, entities):
    """Agar humne custom emoji bheje lekin Telegram ne wapas nahi diye -> console mein warning."""
    global _PREM_WARNED
    if _PREM_WARNED or not entities or MessageEntityCustomEmoji is None:
        return
    if not any(isinstance(e, MessageEntityCustomEmoji) for e in entities):
        return
    got = getattr(sent, "entities", None)
    if got is None:
        return
    if not any(isinstance(e, MessageEntityCustomEmoji) for e in got):
        _PREM_WARNED = True
        print("[PREMIUM] Telegram ne custom emoji hata diye. Check: (1) BotFather se bot banane wala "
              "account Telegram Premium ho, (2) emoji ID sahi ho (/emojiid se nikalo).")

# ---------- BUTTON PREMIUM EMOJI (Bot API 9.4: icon_custom_emoji_id + style) ----------
# Button ke text (small-caps wala, emoji/space ke bina) ke hisaab se ID daalo:
#   BUTTON_EMOJI = {"ᴏᴡɴᴇʀ": 5368324170671202286, "ʜᴇʟᴩ": 5368324170671202287}
# Ya button text ke shuru mein koi emoji ho jo PREMIUM_EMOJI dict mein hai (jaise "⬅ ʙᴀᴄᴋ"),
# to wo automatically button ka premium icon ban jayega.
BUTTON_EMOJI = {
    # "ᴏᴡɴᴇʀ": 5368324170671202286,
    # "ꜱᴜᴩᴩᴏʀᴛ": 5368324170671202287,
    # "ꜱᴛᴀᴛᴜꜱ": 5368324170671202288,
    # "ʜᴇʟᴩ": 5368324170671202289,
    # "ᴠᴇʀɪꜰʏ": 5368324170671202290,
}
# Button ka color: "primary" (blue), "success" (green), "danger" (red)
BUTTON_STYLE = {
    # "ᴏᴡɴᴇʀ": "primary",
    # "ᴠᴇʀɪꜰʏ": "success",
}

def _btn_key(text):
    return re.sub(r"^[^\w]+", "", (text or "").strip()).lower()

def _api_markup(buttons):
    """Telethon buttons -> Bot API reply_markup (icon/style ke saath). None = kuch lagana nahi/unsupported."""
    if not buttons or (not BUTTON_EMOJI and not BUTTON_STYLE and not _PREM_RE):
        return None
    if not isinstance(buttons, (list, tuple)):
        buttons = [[buttons]]
    elif not buttons or not isinstance(buttons[0], (list, tuple)):
        buttons = [buttons]
    keys_emoji = {_btn_key(k): int(v) for k, v in BUTTON_EMOJI.items() if v}
    keys_style = {_btn_key(k): v for k, v in BUTTON_STYLE.items() if v}
    rows, changed = [], False
    for row in buttons:
        out = []
        for b in row:
            b = getattr(b, "button", b)
            text = getattr(b, "text", None)
            if text is None:
                return None
            if hasattr(b, "url") and getattr(b, "url", None):
                item = {"text": text, "url": b.url}
            elif hasattr(b, "data") and isinstance(getattr(b, "data", None), (bytes, bytearray)):
                item = {"text": text, "callback_data": bytes(b.data).decode("utf-8", "ignore")}
            else:
                return None   # unsupported button type -> Telethon wala hi rehne do
            key = _btn_key(text)
            eid = keys_emoji.get(key)
            if not eid and _PREM_RE:
                m = _PREM_RE.match(text.strip())
                if m:
                    eid = _PREM_MAP.get(m.group(0).replace(_FE0F, ""))
                    if eid:
                        item["text"] = text.strip()[m.end():].strip() or text
            if eid:
                item["icon_custom_emoji_id"] = str(eid)
                changed = True
            if keys_style.get(key) in ("primary", "success", "danger"):
                item["style"] = keys_style[key]
                changed = True
            out.append(item)
        rows.append(out)
    return {"inline_keyboard": rows} if changed else None

_BTN_WARNED = False

def _bot_api_call(method, payload):
    import urllib.request
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "ignore")
        except Exception:
            pass
        return {"ok": False, "description": f"{type(exc).__name__}: {exc} {body}"}

async def _apply_button_icons(chat_id, sent, buttons):
    """Message Telethon se bhejne ke baad Bot API se buttons pe premium icon/style laga do."""
    global _BTN_WARNED
    try:
        markup = _api_markup(buttons)
        msg_id = getattr(sent, "id", None)
        if not markup or not msg_id or not chat_id:
            return
        res = await asyncio.to_thread(_bot_api_call, "editMessageReplyMarkup",
                                      {"chat_id": chat_id, "message_id": msg_id, "reply_markup": markup})
        if not res.get("ok") and "not modified" not in str(res.get("description", "")).lower() and not _BTN_WARNED:
            _BTN_WARNED = True
            print(f"[BUTTON PREMIUM] Telegram ne icon/style accept nahi kiya: {res.get('description')} "
                  "(owner Premium ho, ID sahi ho, ya Telegram ne naya field abhi enable na kiya ho)")
    except Exception as exc:
        print(f"[BUTTON PREMIUM] {type(exc).__name__}: {exc}")

def _install_premium_html(client):
    """acbot userbot client ke send/edit mein HTML messages ko premium emoji mein badal do."""
    if getattr(client, "_prem_patched", False):
        return
    client._prem_patched = True
    orig_send, orig_edit = client.send_message, client.edit_message

    def _is_html(kw):
        return str(kw.get("parse_mode") or "").lower() == "html"

    async def send_message(entity, message="", *a, **kw):
        if isinstance(message, str) and _is_html(kw):
            message = _premium_html(message)
        return await orig_send(entity, message, *a, **kw)

    async def edit_message(entity, message=None, text=None, *a, **kw):
        if _is_html(kw):
            if isinstance(text, str):
                text = _premium_html(text)
            elif isinstance(message, str):
                message = _premium_html(message)
        return await orig_edit(entity, message, text, *a, **kw)

    client.send_message = send_message
    client.edit_message = edit_message

def _quote(text):
    parsed, entities = _tl_md.parse(text)
    parsed = parsed.rstrip()
    entities = [e for e in entities if e.offset + e.length <= _u16(parsed)]
    entities.insert(0, MessageEntityBlockquote(0, _u16(parsed)))
    entities += _premium_entities(parsed)
    entities.sort(key=lambda e: (e.offset, -e.length))
    return parsed, entities

if MessageEntityBlockquote is not None:
    _orig_send_message = bot.send_message
    _orig_send_file = bot.send_file
    _orig_edit_message = bot.edit_message

    async def _send_message(entity, message="", *args, **kwargs):
        if isinstance(message, str) and message and "formatting_entities" not in kwargs and "parse_mode" not in kwargs:
            try:
                message, kwargs["formatting_entities"] = _quote(message)
            except Exception as exc:
                print(f"[BLOCKQUOTE] {type(exc).__name__}: {exc}")
        sent = await _orig_send_message(entity, message, *args, **kwargs)
        _check_premium(sent, kwargs.get("formatting_entities"))
        if kwargs.get("buttons"):
            await _apply_button_icons(getattr(sent, "chat_id", None) or utils.get_peer_id(await bot.get_input_entity(entity)), sent, kwargs["buttons"])
        return sent

    async def _send_file(entity, file, *args, **kwargs):
        caption = kwargs.get("caption")
        if isinstance(caption, str) and caption and "formatting_entities" not in kwargs and "parse_mode" not in kwargs:
            try:
                kwargs["caption"], kwargs["formatting_entities"] = _quote(caption)
            except Exception as exc:
                print(f"[BLOCKQUOTE] {type(exc).__name__}: {exc}")
        sent = await _orig_send_file(entity, file, *args, **kwargs)
        _check_premium(sent, kwargs.get("formatting_entities"))
        if kwargs.get("buttons"):
            await _apply_button_icons(getattr(sent, "chat_id", None) or utils.get_peer_id(await bot.get_input_entity(entity)), sent, kwargs["buttons"])
        return sent

    async def _edit_message(entity, message=None, text=None, *args, **kwargs):
        if isinstance(text, str) and text and "formatting_entities" not in kwargs and "parse_mode" not in kwargs:
            try:
                text, kwargs["formatting_entities"] = _quote(text)
            except Exception as exc:
                print(f"[BLOCKQUOTE] {type(exc).__name__}: {exc}")
        res = await _orig_edit_message(entity, message, text, *args, **kwargs)
        if kwargs.get("buttons"):
            chat_id = getattr(res, "chat_id", None)
            if not chat_id:
                try:
                    chat_id = utils.get_peer_id(await bot.get_input_entity(entity))
                except Exception:
                    chat_id = None
            await _apply_button_icons(chat_id, res, kwargs["buttons"])
        return res

    bot.send_message = _send_message
    bot.send_file = _send_file
    bot.edit_message = _edit_message
USERBOTS = {}
BOOT_TIME = time.time()

# Bot ke users (jinhone /start ya /login kiya) -> "Total friends"
USERS_FILE = ROOT / "bot_users.json"

def _load_bot_users():
    try:
        return set(json.loads(USERS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()

BOT_USERS = _load_bot_users()

def add_bot_user(user_id):
    if user_id not in BOT_USERS:
        BOT_USERS.add(user_id)
        try:
            USERS_FILE.write_text(json.dumps(sorted(BOT_USERS)), encoding="utf-8")
        except Exception as exc:
            print(f"[USERS] {type(exc).__name__}: {exc}")
    return len(BOT_USERS)
PENDING = {}

def session_name(owner_id):
    return str(SESSIONS / str(owner_id))

def data_dir(owner_id):
    path = DATA / str(owner_id)
    path.mkdir(parents=True, exist_ok=True)
    return path

def load_source(owner_id):
    if not TEMPLATE.exists():
        raise FileNotFoundError("acbot.py ko multi_acbot.py ke same folder mein rakho.")
    source = TEMPLATE.read_text(encoding="utf-8")
    session = repr(session_name(owner_id))
    folder = repr(str(data_dir(owner_id)))
    source, count = re.subn(
        r"SESSION_NAME\s*=.*?\nclient\s*=\s*TelegramClient\(SESSION_NAME, API_ID, API_HASH\)",
        f"SESSION_NAME = {session}\nclient = TelegramClient(SESSION_NAME, API_ID, API_HASH)",
        source, count=1, flags=re.S,
    )
    if count != 1:
        raise RuntimeError("acbot.py ka session block nahi mila.")
    source = source.replace("os.path.dirname(os.path.abspath(__file__))", folder)
    for name, filename in {
        "ECHO_TARGETS_FILE": "echo_targets.json",
        "CLONE_BACKUP_FILE": "clone_backup.json",
        "CLONE_BACKUP_PHOTO": "clone_backup_photo.jpg",
        "OFF_BACKUP_FILE": "off_backup.json",
        "OFF_BACKUP_PHOTO": "off_backup_photo.jpg",
        "AUTO_DELETE_FILE": "auto_delete.json",
    }.items():
        source = re.sub(
            rf"^{name}\s*=\s*['\"][^'\"]+['\"]",
            f"{name} = os.path.join({folder}, {filename!r})",
            source, flags=re.M,
        )
    return source

async def start_userbot(owner_id):
    if owner_id in USERBOTS:
        return USERBOTS[owner_id]
    namespace = {"__name__": "loaded_userbot", "__file__": str(TEMPLATE)}
    exec(compile(load_source(owner_id), str(TEMPLATE), "exec"), namespace)
    # Premium emoji: upar wala PREMIUM_EMOJI dict acbot.py (userbot) mein bhi load hoga
    if PREMIUM_EMOJI and isinstance(namespace.get("PREMIUM_EMOJI"), dict):
        namespace["PREMIUM_EMOJI"].update(PREMIUM_EMOJI)
        rebuild = namespace.get("_rebuild_premium_index")
        if rebuild:
            rebuild()
    client = namespace["client"]
    _install_premium_html(client)   # acbot ke saare HTML messages mein premium emoji
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Session authorized nahi hai.")
    if namespace.get("PYTGCALLS_AVAILABLE") and namespace.get("call_py"):
        try:
            await namespace["call_py"].start()
        except Exception as error:
            print(f"[VOICE {owner_id}] {error}")
    USERBOTS[owner_id] = {"client": client, "namespace": namespace}
    return USERBOTS[owner_id]

async def stop_userbot(owner_id):
    item = USERBOTS.pop(owner_id, None)
    if not item:
        return
    call_py = item["namespace"].get("call_py")
    if call_py:
        try:
            await call_py.stop()
        except Exception:
            pass
    if item["client"].is_connected():
        await item["client"].disconnect()

async def finish_login(event, owner_id, client):
    PENDING.pop(owner_id, None)
    if client.is_connected():
        await client.disconnect()
    item = await start_userbot(owner_id)
    me = await item["client"].get_me()
    await event.reply(
        "╭── [ ɴᴏᴅᴇ ᴄᴏɴɴᴇᴄᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ]\n"
        "│\n"
        f"├── 👤 ⇛ ɴᴀᴍᴇ: {me.first_name or 'ᴜꜱᴇʀ'}\n"
        f"├── 🆔 ⇛ ɪᴅ: `{me.id}`\n"
        "├── 🟢 ⇛ ꜱᴛᴀᴛᴜꜱ: ᴏɴʟɪɴᴇ\n"
        "├── ⚡ ⇛ ᴜꜱᴇʀʙᴏᴛ: ᴀᴄᴛɪᴠᴇ\n"
        "│\n├── 💎 ⇛ ᴛʀʏ: `.ping`\n"
        "╰──  ➡️⇛ ʟᴏɢᴏᴜᴛ: /logout"
    )
    try:
        await alert_new_id(me)
    except Exception as exc:
        print(f"[ALERT] new id alert failed: {type(exc).__name__}: {exc}")

# ---------- FORCE JOIN ----------
# Yahan apna channel aur group daalo (bot dono mein ADMIN hona chahiye).
# Public ho to username, private ho to numeric id (-100...) likho.
# Link hamesha likho (private ke liye invite link zaroori hai).
FORCE_CHANNEL = "-1003305941533"                      # @ ke bina username, ya -1001234567890
FORCE_CHANNEL_LINK = "https://t.me/alexaxfamily"    # private: https://t.me/+AbCdEfGh

FORCE_GROUP = "-1003747191357"                                   # khali chhodo to group verify nahi hoga, sirf join button dikhega
FORCE_GROUP_LINK = "https://t.me/+n3Eh1RN4wnZkODZl"        # yahan group ka link daalo

FORCE_JOIN = [
    ("ᴄʜᴀɴɴᴇʟ", FORCE_CHANNEL, FORCE_CHANNEL_LINK),
    ("ɢʀᴏᴜᴩ", FORCE_GROUP, FORCE_GROUP_LINK),
]

# Home card ke buttons
OWNER_USERNAME = "ll_LORD_EROX_ll"          # owner ka username (@ ke bina)
SUPPORT_LINK = "https://t.me/+n3Eh1RN4wnZkODZl"         # support group ka link (alag chahiye to yahan likho)

# Alerts (New Friend / New ID) is chat mein jayenge. Alag group chahiye to id/username yahan likho.
ALERT_CHAT = FORCE_GROUP

def _chat_ref(ref):
    r = str(ref).strip()
    return int(r) if r.lstrip("-").isdigit() else r.lstrip("@")

async def send_alert(text):
    if not ALERT_CHAT:
        return
    try:
        if MessageEntityBlockquote is not None:
            await bot.send_message(_chat_ref(ALERT_CHAT), text,
                                   formatting_entities=[MessageEntityBlockquote(0, _u16(text))] + _premium_entities(text))
        else:
            await bot.send_message(_chat_ref(ALERT_CHAT), text, parse_mode=None)
    except Exception as exc:
        print(f"[ALERT] {type(exc).__name__}: {exc} (bot ko alert group mein add/admin karo)")

async def alert_new_id(me):
    text = (
        "╭── [ ɴᴇᴡ ɪᴅ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ]\n"
        "│\n"
        f"├── 🎩 ⇛ ɴᴀᴍᴇ: {me.first_name or 'ᴜꜱᴇʀ'}\n"
        f"├── 📎 ⇛ ɪᴅ: {me.id}\n"
        f"├── 💎 ⇛ ᴜꜱᴇʀɴᴀᴍᴇ: {('@' + me.username) if getattr(me, 'username', None) else 'ɴᴏɴᴇ'}\n"
        f"╰── 🍄 ⇛ ᴛᴏᴛᴀʟ ᴀᴄᴛɪᴠᴇ ɪᴅ: {len(USERBOTS)}"
    )
    await send_alert(text)

# ---------- JOIN REQUEST (private group) ----------
# Private group ka link "request to join" wala ho to user member nahi banta, bas request jaati hai.
# Bot ko wo request update ke through dikhti hai (bot us group mein ADMIN + "Invite Users" permission
# ke saath hona chahiye). Hum wo request yaad rakhte hain, aur verify ke time request ko bhi "joined" maante hain.
# Bot request ko accept NAHI karta, accept group ka admin apne time par karega.

_REQ_UPDATE = getattr(types, "UpdateBotChatInviteRequester", None)
REQ_FILE = ROOT / "join_requests.json"

def _load_requests():
    try:
        raw = json.loads(REQ_FILE.read_text(encoding="utf-8"))
        return {str(k): set(int(x) for x in v) for k, v in raw.items()}
    except Exception:
        return {}

JOIN_REQUESTS = _load_requests()   # {chat_peer_id(str): {user_id, ...}}

# /logout ke baad user ko dobara NAYI join request bhejni padegi (purani pending/verified request nahi chalegi).
REJOIN_FILE = ROOT / "rejoin_required.json"

def _load_rejoin():
    try:
        raw = json.loads(REJOIN_FILE.read_text(encoding="utf-8"))
        return {str(k): set(int(x) for x in v) for k, v in raw.items()}
    except Exception:
        return {}

REJOIN = _load_rejoin()   # {chat_peer_id(str): {user_id, ...}}

def _save_rejoin():
    try:
        REJOIN_FILE.write_text(json.dumps({k: sorted(v) for k, v in REJOIN.items()}), encoding="utf-8")
    except Exception as exc:
        print(f"[REJOIN] save error: {exc}")

def _save_requests():
    try:
        REQ_FILE.write_text(json.dumps({k: sorted(v) for k, v in JOIN_REQUESTS.items()}), encoding="utf-8")
    except Exception as exc:
        print(f"[JOIN REQ] save error: {exc}")

def all_friend_ids():
    """Bot start karne wale + join request bhejne wale (duplicate ek hi count hota hai)."""
    ids = set(BOT_USERS)
    for users in JOIN_REQUESTS.values():
        ids |= users
    return ids

def total_friends():
    return len(all_friend_ids())

async def send_friend_alert(user_id):
    name, username = "ᴜꜱᴇʀ", "ɴᴏɴᴇ"
    try:
        user = await bot.get_entity(user_id)
        name = " ".join(x for x in (user.first_name, user.last_name) if x) or "ᴜꜱᴇʀ"
        if getattr(user, "username", None):
            username = "@" + user.username
    except Exception:
        pass
    text = (
        "ɴᴇᴡ ꜰʀɪᴇɴᴅ ᴀʟᴇʀᴛ!\n"
        f"├── 😽 ɴᴀᴍᴇ: {name}\n"
        f"├── 💎 ɪᴅ: {user_id}\n"
        f"├── ⭐ ᴜꜱᴇʀɴᴀᴍᴇ: {username}\n"
        f"╰── 💐 ᴛᴏᴛᴀʟ ꜰʀɪᴇɴᴅꜱ: {total_friends()}"
    )
    await send_alert(text)

async def _peer_id_of(ref):
    try:
        return utils.get_peer_id(await bot.get_input_entity(_chat_ref(ref)))
    except Exception:
        return None

# Optional: kisi USER account (group/channel mein ADMIN) ka session. Bot ye call nahi kar sakta,
# isliye pending request cancel hui ya nahi, ye sirf ye account dekh sakta hai.
CHECKER = TelegramClient(str(ROOT / "checker"), API_ID, API_HASH)

async def _live_pending(ref, user_id):
    """Telegram se seedha poochho: kya user ki join request abhi pending hai?
    True/False = pakka jawab, None = check nahi ho paya (CHECKER login nahi / error)."""
    if not CHECKER.is_connected():
        return None
    try:
        from telethon.tl.functions.messages import GetChatInviteImportersRequest
        peer = await CHECKER.get_input_entity(_chat_ref(ref))
        offset_date, offset_user = None, types.InputUserEmpty()
        for _ in range(30):   # max ~3000 pending requests tak dekho
            res = await CHECKER(GetChatInviteImportersRequest(
                peer=peer, limit=100, offset_date=offset_date,
                offset_user=offset_user, requested=True))
            if not res.importers:
                return False
            if any(i.user_id == user_id for i in res.importers):
                return True
            last = res.importers[-1]
            offset_date = last.date
            offset_user = await CHECKER.get_input_entity(last.user_id)
            if len(res.importers) < 100:
                return False
        return False
    except Exception as exc:
        print(f"[JOIN REQ] live check failed for {ref}: {type(exc).__name__}: {exc}")
        return None

async def has_pending_request(ref, user_id, left=False):
    # /logout ke baad: sirf logout ke BAAD aayi fresh request maani jayegi
    pid0 = await _peer_id_of(ref)
    if pid0 is not None and user_id in REJOIN.get(str(pid0), set()):
        return user_id in JOIN_REQUESTS.get(str(pid0), set())
    # Pehle Telegram se live check: purani/stale saved request pe bharosa nahi karna.
    live = await _live_pending(ref, user_id)
    if live is not None:
        if not live:
            await forget_request(ref, user_id)
        return live
    # Live check na ho paya:
    if left:
        # User group/channel chhod chuka hai -> purani saved request pe bharosa nahi, join maango.
        print(f"[FORCE JOIN] {ref}: user {user_id} left, live check unavailable -> join required "
              f"(bot ko admin + Invite Users permission do)")
        return False
    pid = await _peer_id_of(ref)
    return pid is not None and user_id in JOIN_REQUESTS.get(str(pid), set())

async def forget_request(ref, user_id):
    """User ab member ban chuka hai (ya request khatam) -> purani join request yaad mat rakho."""
    pid = await _peer_id_of(ref)
    users = JOIN_REQUESTS.get(str(pid)) if pid is not None else None
    if users and user_id in users:
        users.discard(user_id)
        _save_requests()

def forget_all_requests(user_id):
    """/logout par: is user ki saari purani join requests hata do."""
    changed = False
    for users in JOIN_REQUESTS.values():
        if user_id in users:
            users.discard(user_id)
            changed = True
    if changed:
        _save_requests()

async def require_rejoin(user_id):
    """/logout par: is user ko har force-join chat mein dobara naya join karna/request bhejna padega."""
    for label, ref, link in FORCE_JOIN:
        if not ref:
            continue
        pid = await _peer_id_of(ref)
        if pid is None:
            continue
        REJOIN.setdefault(str(pid), set()).add(user_id)
        JOIN_REQUESTS.get(str(pid), set()).discard(user_id)
    _save_rejoin()
    _save_requests()

async def _watched_chat_ids():
    ids = set()
    for label, ref, link in FORCE_JOIN:
        if not ref:
            continue
        pid = await _peer_id_of(ref)
        if pid is not None:
            ids.add(pid)
    return ids

if _REQ_UPDATE is not None:
    @bot.on(events.Raw(_REQ_UPDATE))
    async def join_request_alert(update):
        try:
            chat_pid = utils.get_peer_id(update.peer)
            if chat_pid not in await _watched_chat_ids():
                return
        except Exception:
            return
        user_id = update.user_id
        JOIN_REQUESTS.setdefault(str(chat_pid), set()).add(user_id)
        _save_requests()
        if user_id in REJOIN.get(str(chat_pid), set()):
            REJOIN[str(chat_pid)].discard(user_id)   # logout ke baad fresh request aa gayi
            _save_rejoin()

        await send_friend_alert(user_id)

# User join/approve/leave ho to purani request hata do (pending request jab tak rahe verified rahegi).
_PART_UPDATE = getattr(types, "UpdateChannelParticipant", None)
if _PART_UPDATE is not None:
    @bot.on(events.Raw(_PART_UPDATE))
    async def participant_changed(update):
        try:
            pid = utils.get_peer_id(types.PeerChannel(update.channel_id))
            if pid not in await _watched_chat_ids():
                return
        except Exception:
            return
        users = JOIN_REQUESTS.get(str(pid))
        if users and update.user_id in users:
            users.discard(update.user_id)
            _save_requests()
        # User ne group/channel chhod diya (ya kick/ban hua) -> userbot band + alert
        new = getattr(update, "new_participant", None)
        if new is None or isinstance(new, (_PartLeft, _PartBanned)):
            await terminate_for_leave(update.user_id)


# Start image: local file (bot ke folder mein, jaise "start.jpg") ya direct image URL. Khali = bina image.
START_IMAGE = "https://files.catbox.moe/5fxx81.jpg"

def _start_image():
    if not START_IMAGE:
        return None
    if START_IMAGE.startswith("http"):
        return START_IMAGE
    path = ROOT / START_IMAGE
    return str(path) if path.exists() else None

async def send_card(chat_id, text, buttons=None, with_image=True):
    image = _start_image() if with_image else None
    if image:
        try:
            return await bot.send_file(chat_id, image, caption=text, buttons=buttons)
        except Exception as exc:
            print(f"[START IMAGE] {type(exc).__name__}: {exc}")
    return await bot.send_message(chat_id, text, buttons=buttons)

HELP_TEXT = (
    "╭── [ ʜᴇʟᴩ ᴍᴇɴᴜ : ʟᴏɢɪɴ ɢᴜɪᴅᴇ ]\n"
    "│\n"
    "🎁 ⇛ ꜱᴛᴇᴩ 1: ꜱᴇɴᴅ /login ᴄᴏᴍᴍᴀɴᴅ.\n"
    "📎 ⇛ ꜱᴛᴇᴩ 2: ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴩʜᴏɴᴇ ɴᴜᴍʙᴇʀ.\n"
    "❤️ ⇛ ꜱᴛᴇᴩ 3: ᴇɴᴛᴇʀ ᴏᴛᴩ ᴡɪᴛʜ ꜱᴩᴀᴄᴇꜱ (ᴇx: 6 3 2 1 4).\n"
    "❤️ ⇛ ꜱᴛᴇᴩ 4: ᴇɴᴛᴇʀ 2ꜰᴀ ᴩᴀꜱꜱᴡᴏʀᴅ (ɪꜰ ᴀꜱᴋᴇᴅ).\n"
    "💎 ⇛ ꜱᴛᴇᴩ 5: ᴇɴᴊᴏʏ ʏᴏᴜʀ ꜱᴇᴄᴜʀᴇ ᴜꜱᴇʀʙᴏᴛ!"
)

def _bar(percent):
    filled = max(0, min(10, round(percent / 10)))
    return "▰" * filled + "▱" * (10 - filled)

async def build_home(user_id, name):
    started = time.perf_counter()
    try:
        await bot.get_me()
    except Exception:
        pass
    latency = (time.perf_counter() - started) * 1000
    up = int(time.time() - BOOT_TIME)
    days, rem = divmod(up, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    uptime = (f"{days}ᴅ " if days else "") + f"{hours}ʜ {minutes}ᴍ"
    cpu = ram = 0.0
    if psutil:
        try:
            cpu = psutil.cpu_percent(interval=None)
        except Exception:
            try:
                cpu = min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100)
            except Exception:
                try:
                    cpu = MY_PROC.cpu_percent(interval=None) / (os.cpu_count() or 1)
                except Exception:
                    cpu = 0.0
        try:
            ram = psutil.virtual_memory().percent
        except Exception:
            ram = 0.0
    node = "ᴀᴄᴛɪᴠᴇ ɴᴏᴅᴇ" if user_id in USERBOTS else "ɴᴏᴛ ᴄᴏɴɴᴇᴄᴛᴇᴅ"
    text = (
        "**  💎 ᴀʟᴇxᴀ : ᴏᴍɴɪ ᴄᴏʀᴇ**\n"
        "**━━━━━━━━━━━━━━━━━━━━**\n"
        "**╭── 🎩 ᴜꜱᴇʀ ɪɴꜰᴏ**\n"
        f"**│   ├── ɴᴀᴍᴇ :** {name}\n"
        f"**│   ├── ɪᴅ :** {user_id}\n"
        f"**│   ╰── ꜱᴛᴀᴛᴜꜱ :** {node}\n"
        "**│**\n"
        "**╰── 🙂 ꜱʏꜱᴛᴇᴍ ꜱᴛᴀᴛꜱ**\n"
        f"**    ├── ʟᴀᴛᴇɴᴄʏ :** {latency:.2f} ᴍꜱ\n"
        f"**    ├── ᴜᴩᴛɪᴍᴇ :** {uptime}\n"
        f"**    ├── ᴄᴩᴜ :** [{_bar(cpu)}] {cpu:.1f}%\n"
        f"**    ╰── ʀᴀᴍ :** [{_bar(ram)}] {ram:.1f}%\n\n"
        "**💎 ᴛʜᴇ ᴍᴏꜱᴛ ᴀᴅᴠᴀɴᴄᴇᴅ ᴜꜱᴇʀʙᴏᴛ .**\n"
        "**ᴄʟɪᴄᴋ ᴏɴ 'ʜᴇʟᴩ' ᴛᴏ ʙᴇɢɪɴ ʏᴏᴜʀ ꜱᴇꜱꜱɪᴏɴ**"
    )
    rows = [
        [Button.url(" 🎁ᴏᴡɴᴇʀ", f"https://t.me/{OWNER_USERNAME.lstrip('@')}"),
         Button.url(" 🎁ꜱᴜᴩᴩᴏʀᴛ", SUPPORT_LINK)],
        [Button.inline(" 🎁ꜱᴛᴀᴛᴜꜱ", b"status_info"),
         Button.inline(" 🎁ʜᴇʟᴩ", b"help_open")],
    ]
    return text, rows

async def send_gate(chat_id, user_id, name="ᴜꜱᴇʀ"):
    missing = await missing_joins(user_id)
    # Agar user pehle se sab join kar chuka hai to seedha home card dikhao
    if not missing and any(ref for _, ref, _ in FORCE_JOIN):
        text, rows = await build_home(user_id, name)
        await send_card(chat_id, text, rows)
        return
    text, rows = join_gate_message(missing or FORCE_JOIN_ALL())
    await send_card(chat_id, text, rows, with_image=False)

def FORCE_JOIN_ALL():
    return [(label, link) for label, ref, link in FORCE_JOIN]

from telethon.tl.functions.channels import GetParticipantRequest as _GetParticipantRequest
from telethon.tl.types import ChannelParticipantLeft as _PartLeft, ChannelParticipantBanned as _PartBanned

async def missing_joins(user_id):
    missing = []
    for label, ref, link in FORCE_JOIN:
        if not ref:
            continue
        try:
            chat_ref = int(str(ref).strip()) if str(ref).strip().lstrip("-").isdigit() else str(ref).strip().lstrip("@")
            # Seedha participant type dekho: Telegram left/banned user ke liye error nahi,
            # "ChannelParticipantLeft/Banned" wapas deta hai -> use member NAHI maanna hai.
            res = await bot(_GetParticipantRequest(await bot.get_input_entity(chat_ref),
                                                   await bot.get_input_entity(user_id)))
            if isinstance(res.participant, (_PartLeft, _PartBanned)):
                # Leave kar chuka hai: sirf tab verified jab abhi koi NAYI request pending ho
                if not await has_pending_request(ref, user_id, left=True):
                    print(f"[FORCE JOIN] {ref}: user {user_id} left -> join required")
                    missing.append((label, link))
                continue
            await forget_request(ref, user_id)   # member hai, purani request ka koi kaam nahi
        except UserNotParticipantError:
            # Private group: request bhej di hai to verified maano
            if not await has_pending_request(ref, user_id):
                missing.append((label, link))
        except Exception as exc:
            print(f"[FORCE JOIN] {ref}: {type(exc).__name__}: {exc} (bot ko admin banao)")
            if not await has_pending_request(ref, user_id):
                missing.append((label, link))
    return missing

LEAVE_TEXT = (
    "╭── [ ɢʀᴏᴜᴩ ʟᴇꜰᴛ ]\n│\n"
    "├── 🚫 ⇛ TUNE GROUP LEAVE KAR DIYA HAI, TERA SESSION TERMINATE HO GAYA HAI\n"
    "├── ⛔ ⇛ AB USERBOT KAAM NAHI KAREGA\n"
    "╰── 🌕⇛ WAPAS JOIN KAR KE /login KAR 💀"
)

_TERMINATING = set()
_STRIKES = {}

async def terminate_for_leave(user_id):
    """Userbot band, Telegram se session terminate, local data delete, aur DM alert."""
    if user_id not in USERBOTS or user_id in _TERMINATING:
        return
    _TERMINATING.add(user_id)
    try:
        item = USERBOTS.get(user_id)
        try:
            await item["client"].log_out()      # Telegram side se bhi session terminate
        except Exception as exc:
            print(f"[LEAVE {user_id}] log_out: {type(exc).__name__}: {exc}")
        await stop_userbot(user_id)
        PENDING.pop(user_id, None)
        await require_rejoin(user_id)           # dobara NAYI join request zaroori
        for suffix in (".session", ".session-journal"):
            Path(session_name(user_id) + suffix).unlink(missing_ok=True)
        shutil.rmtree(data_dir(user_id), ignore_errors=True)
        print(f"[LEAVE {user_id}] left force-join chat -> userbot terminated")
        try:
            await bot.send_message(user_id, LEAVE_TEXT)
        except Exception as exc:
            print(f"[LEAVE {user_id}] alert failed: {type(exc).__name__}: {exc}")
    finally:
        _TERMINATING.discard(user_id)

async def has_left(user_id):
    """True sirf tab jab PAKKA ho ki user chhod chuka hai aur koi pending request bhi nahi.
    Error/unknown ho to False (galti se kisi ko terminate na karein)."""
    for label, ref, link in FORCE_JOIN:
        if not ref:
            continue
        try:
            chat_ref = int(str(ref).strip()) if str(ref).strip().lstrip("-").isdigit() else str(ref).strip().lstrip("@")
            res = await bot(_GetParticipantRequest(await bot.get_input_entity(chat_ref),
                                                   await bot.get_input_entity(user_id)))
            gone = isinstance(res.participant, (_PartLeft, _PartBanned))
        except UserNotParticipantError:
            gone = True
        except Exception as exc:
            print(f"[LEAVE CHECK] {ref}: {type(exc).__name__}: {exc}")
            continue
        if not gone:
            continue
        live = await _live_pending(ref, user_id)
        if live is True:
            continue                     # request abhi pending hai -> theek
        if live is None:
            # CHECKER nahi: sirf saved request dekh sakte hain (cancel pakad nahi sakte)
            pid = await _peer_id_of(ref)
            if pid is not None and user_id in JOIN_REQUESTS.get(str(pid), set()):
                continue
        return True
    return False

async def leave_watcher(interval=120):
    """Har logged-in user ko check karta hai. 2 baar lagataar 'left' aaye tabhi terminate."""
    while True:
        for uid in list(USERBOTS):
            try:
                if await has_left(uid):
                    _STRIKES[uid] = _STRIKES.get(uid, 0) + 1
                    if _STRIKES[uid] >= 2:
                        _STRIKES.pop(uid, None)
                        await terminate_for_leave(uid)
                else:
                    _STRIKES.pop(uid, None)
            except Exception as exc:
                print(f"[LEAVE WATCH {uid}] {type(exc).__name__}: {exc}")
            await asyncio.sleep(1)
        await asyncio.sleep(interval)

def join_gate_message(missing):
    text = (
        "╭── [ ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ ]\n│\n"
        "├── 👁 ⇛ ʟᴏɢɪɴ ᴋᴇ ʟɪʏᴇ ᴩᴀʜʟᴇ ᴊᴏɪɴ ᴋᴀʀᴏ\n"
        "╰── ✅ ⇛ ᴊᴏɪɴ ᴋᴀʀɴᴇ ᴋᴇ ʙᴀᴀᴅ ᴠᴇʀɪꜰʏ ᴅᴀʙᴀᴏ"
    )
    rows = [[Button.url(f" ᴊᴏɪɴ {label}", link)] for label, ref, link in FORCE_JOIN if link]
    rows.append([Button.inline(" ᴠᴇʀɪꜰʏ", b"fj_check")])
    return text, rows

async def begin_login(send, owner_id):
    if owner_id in USERBOTS:
        await send(
            "╭── [ ɴᴏᴅᴇ ᴀʟʀᴇᴀᴅʏ ᴄᴏɴɴᴇᴄᴛᴇᴅ ]\n│\n"
            "├── ✅ ⇛ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ɪꜱ ᴀʟʀᴇᴀᴅʏ ᴏɴʟɪɴᴇ\n"
            "├── 📊 ⇛ ᴄʜᴇᴄᴋ: /status\n"
            "╰── 🌕 ⇛ ʟᴏɢᴏᴜᴛ: /logout"
        )
        return
    old = PENDING.pop(owner_id, None)
    if old and old["client"].is_connected():
        await old["client"].disconnect()
    client = TelegramClient(session_name(owner_id), API_ID, API_HASH)
    await client.connect()
    PENDING[owner_id] = {"step": "phone", "client": client}
    await send(
        "╭── [ ꜱᴇᴄᴜʀᴇ ʟᴏɢɪɴ ᴩᴀɴᴇʟ ]\n│\n"
        "├── 💎 ⇛ ꜱᴇɴᴅ ʏᴏᴜʀ ᴩʜᴏɴᴇ ɴᴜᴍʙᴇʀ\n"
        "╰── 👁 ⇛ ᴡɪᴛʜ ᴏʀ ᴡɪᴛʜᴏᴜᴛ ᴄᴏᴜɴᴛʀʏ ᴄᴏᴅᴇ\n\n"
        "❖ ᴇxᴀᴍᴩʟᴇ: `+919876543210`\n❖ ᴄᴀɴᴄᴇʟ: /cancel"
    )

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_command(event):
    if event.is_private:
        is_new = event.sender_id not in all_friend_ids()
        add_bot_user(event.sender_id)
        if is_new:
            await send_friend_alert(event.sender_id)
        sender = await event.get_sender()
        await send_gate(event.chat_id, event.sender_id, getattr(sender, "first_name", None) or "ᴜꜱᴇʀ")

def _emoji_lines(msgs):
    from telethon.helpers import add_surrogate, del_surrogate
    lines, seen = [], set()
    for msg in msgs:
        text = add_surrogate(msg.raw_text or "")
        for ent in (msg.entities or []):
            if isinstance(ent, MessageEntityCustomEmoji) and ent.document_id not in seen:
                seen.add(ent.document_id)
                ch = del_surrogate(text[ent.offset:ent.offset + ent.length])
                lines.append(f'"{ch}": {ent.document_id},')
    return lines

@bot.on(events.NewMessage(pattern=r"^/emojiid"))
async def emojiid_command(event):
    """Premium emoji wale message pe reply karo (ya /emojiid ke saath emoji bhejo) -> IDs milenge."""
    if not event.is_private:
        return
    msgs = [event.message]
    reply = await event.get_reply_message()
    if reply:
        msgs.insert(0, reply)
    lines = _emoji_lines(msgs)
    if not lines:
        await event.reply("Premium emoji bhejo (ya premium emoji wale message pe reply karke /emojiid likho).", parse_mode=None)
        return
    await event.reply("\n".join(lines), parse_mode=None)

@bot.on(events.NewMessage(incoming=True))
async def auto_emojiid(event):
    """Bot ke DM mein koi bhi premium emoji bhejo -> bina command ke ID mil jayegi."""
    if not event.is_private or event.sender_id in PENDING:
        return
    if (event.raw_text or "").startswith("/"):
        return
    lines = _emoji_lines([event.message])
    if lines:
        await event.reply("\n".join(lines), parse_mode=None)

@bot.on(events.NewMessage(pattern=r"^/login$"))
async def login_command(event):
    if not event.is_private:
        return
    add_bot_user(event.sender_id)
    missing = await missing_joins(event.sender_id)
    if missing:
        text, rows = join_gate_message(missing)
        await send_card(event.chat_id, text, rows, with_image=False)
        return
    await begin_login(event.reply, event.sender_id)

@bot.on(events.CallbackQuery(data=b"fj_check"))
async def verify_join(event):
    missing = await missing_joins(event.sender_id)
    if missing:
        await event.answer("❌ ᴊᴏɪɴ ᴀʟʟ ꜰɪʀꜱᴛ, ᴛʜᴇɴ ᴩʀᴇꜱꜱ ᴠᴇʀɪꜰʏ.", alert=True)
        return
    await event.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ!")
    await event.delete()
    sender = await event.get_sender()
    text, rows = await build_home(event.sender_id, getattr(sender, "first_name", None) or "ᴜꜱᴇʀ")
    await send_card(event.sender_id, text, rows)

@bot.on(events.CallbackQuery(data=b"status_info"))
async def status_info(event):
    db = "ᴄᴏɴɴᴇᴄᴛᴇᴅ" if DATA.exists() and SESSIONS.exists() else "ᴅɪꜱᴄᴏɴɴᴇᴄᴛᴇᴅ"
    await event.answer(f"🟢 ꜱᴛᴀᴛᴜꜱ ɪꜱ ᴀʟɪᴠᴇ\n🗄 ᴅᴀᴛᴀʙᴀꜱᴇ: {db}", alert=True)

@bot.on(events.CallbackQuery(data=b"help_open"))
async def help_open(event):
    await event.answer()
    await event.edit(HELP_TEXT, buttons=[[Button.inline("⬅ ʙᴀᴄᴋ", b"help_back")]])

@bot.on(events.CallbackQuery(data=b"help_back"))
async def help_back(event):
    await event.answer()
    sender = await event.get_sender()
    text, rows = await build_home(event.sender_id, getattr(sender, "first_name", None) or "ᴜꜱᴇʀ")
    await event.edit(text, buttons=rows)

@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_command(event):
    state = PENDING.pop(event.sender_id, None)
    if state and state["client"].is_connected():
        await state["client"].disconnect()
    await event.reply("╭── [ ʟᴏɢɪɴ ᴄᴀɴᴄᴇʟʟᴇᴅ ]\n│\n├── ✅ ⇛ ʟᴏɢɪɴ ᴩʀᴏᴄᴇꜱꜱ ꜱᴛᴏᴩᴩᴇᴅ\n╰── 🔐 ⇛ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ: /login")

@bot.on(events.NewMessage(pattern=r"^/status$"))
async def status_command(event):
    item = USERBOTS.get(event.sender_id)
    if not item:
        await event.reply("╭── [ ɴᴏ ᴀᴄᴛɪᴠᴇ ɴᴏᴅᴇ ꜰᴏᴜɴᴅ ]\n│\n├── ❌ ⇛ ɴᴏ ᴜꜱᴇʀʙᴏᴛ ɪꜱ ᴄᴏɴɴᴇᴄᴛᴇᴅ\n╰── 🔐 ⇛ ᴄᴏɴɴᴇᴄᴛ: /login")
        return
    me = await item["client"].get_me()
    await event.reply(f"╭── [ ɴᴏᴅᴇ ꜱᴛᴀᴛᴜꜱ ]\n│\n├── 👤 ⇛ {me.first_name or 'ᴜꜱᴇʀ'}\n├── 🆔 ⇛ `{me.id}`\n╰── 🟢 ⇛ ᴏɴʟɪɴᴇ")

@bot.on(events.NewMessage(pattern=r"^/logout$"))
async def logout_command(event):
    owner_id = event.sender_id
    await stop_userbot(owner_id)
    PENDING.pop(owner_id, None)
    await require_rejoin(owner_id)   # dobara login se pehle join/request zaroori
    for suffix in (".session", ".session-journal"):
        Path(session_name(owner_id) + suffix).unlink(missing_ok=True)
    shutil.rmtree(data_dir(owner_id), ignore_errors=True)
    await event.reply("╭── [ ɴᴏᴅᴇ ᴅɪꜱᴄᴏɴɴᴇᴄᴛᴇᴅ ]\n│\n├── ✅ ⇛ ʟᴏɢᴏᴜᴛ ᴄᴏᴍᴩʟᴇᴛᴇᴅ ꜱᴜᴄᴄᴇꜱꜰᴜʟʟʏ\n├── 🗑 ⇛ ꜱᴇꜱꜱɪᴏɴ ᴅᴇʟᴇᴛᴇᴅ\n╰── 🔐 ⇛ ᴄᴏɴɴᴇᴄᴛ ᴀɢᴀɪɴ: /login")

@bot.on(events.NewMessage(incoming=True))
async def login_steps(event):
    if not event.is_private or event.raw_text.startswith("/"):
        return
    owner_id = event.sender_id
    state = PENDING.get(owner_id)
    if not state:
        return
    client = state["client"]
    text = event.raw_text.strip()
    try:
        if state["step"] == "phone":
            await client.send_code_request(text)
            state.update(step="code", phone=text)
            await event.reply("╭── [ ᴏᴛᴩ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ]\n│\n├── 🔐 ⇛ ꜱᴇɴᴅ ᴛʜᴇ ʟᴏɢɪɴ ᴄᴏᴅᴇ (ᴇx: 6 3 2 1 4)\n╰── 📩 ⇛ ᴄʜᴇᴄᴋ ᴛᴇʟᴇɢʀᴀᴍ ꜰᴏʀ ᴛʜᴇ ᴏᴛᴩ")
        elif state["step"] == "code":
            try:
                await client.sign_in(phone=state["phone"], code=text.replace(" ", ""))
                await finish_login(event, owner_id, client)
            except SessionPasswordNeededError:
                state["step"] = "password"
                await event.reply("╭── [ 2ꜰᴀ ꜱᴇᴄᴜʀɪᴛʏ ᴄʜᴇᴄᴋ ]\n│\n├── 🔒 ⇛ 2ꜰᴀ ᴩᴀꜱꜱᴡᴏʀᴅ ʀᴇǫᴜɪʀᴇᴅ\n╰── 🗝 ⇛ ꜱᴇɴᴅ ʏᴏᴜʀ ᴩᴀꜱꜱᴡᴏʀᴅ")
        elif state["step"] == "password":
            await client.sign_in(password=text)
            await finish_login(event, owner_id, client)
    except PhoneNumberInvalidError:
        await event.reply("╭── [ ɪɴᴠᴀʟɪᴅ ᴩʜᴏɴᴇ ɴᴜᴍʙᴇʀ ]\n│\n├── ❌ ⇛ ᴩʜᴏɴᴇ ɴᴜᴍʙᴇʀ ɪꜱ ɴᴏᴛ ᴠᴀʟɪᴅ\n╰── 💎 ⇛ ꜱᴇɴᴅ ɴᴜᴍʙᴇʀ ᴀɢᴀɪɴ")
    except PhoneCodeInvalidError:
        await event.reply("╭── [ ɪɴᴠᴀʟɪᴅ ᴏᴛᴩ ᴄᴏᴅᴇ ]\n│\n├── ❌ ⇛ ᴛʜᴇ ᴏᴛᴩ ɪꜱ ɪɴᴄᴏʀʀᴇᴄᴛ\n╰── 📩 ⇛ ꜱᴇɴᴅ ᴄᴏʀʀᴇᴄᴛ ᴏᴛᴩ")
    except PhoneCodeExpiredError:
        await event.reply("╭── [ ᴏᴛᴩ ᴇxᴩɪʀᴇᴅ ]\n│\n├── ⏳ ⇛ ᴛʜɪꜱ ᴏᴛᴩ ɪꜱ ɴᴏ ʟᴏɴɢᴇʀ ᴠᴀʟɪᴅ\n╰── 🔄 ⇛ /cancel, ᴛʜᴇɴ /login")
    except Exception as exc:
        print(f"[LOGIN {owner_id}] {type(exc).__name__}: {exc}")
        await event.reply("╭── [ ʟᴏɢɪɴ ꜰᴀɪʟᴇᴅ ]\n│\n├── ❌ ⇛ ᴜɴᴀʙʟᴇ ᴛᴏ ᴄᴏɴɴᴇᴄᴛ\n╰── 🔄 ⇛ /cancel, ᴛʜᴇɴ /login")

async def load_saved_sessions():
    for path in SESSIONS.glob("*.session"):
        try:
            await start_userbot(int(path.stem))
        except Exception as exc:
            print(f"[LOAD {path.name}] {exc}")

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    try:
        await CHECKER.connect()
        if await CHECKER.is_user_authorized():
            await CHECKER.get_dialogs()      # chats cache mein aa jayein
            print("[CHECKER] ready (pending request cancel bhi pakdega)")
        else:
            print("[CHECKER] login nahi hai -> sirf real leave pakdega, request cancel nahi")
    except Exception as exc:
        print(f"[CHECKER] off: {type(exc).__name__}: {exc}")
    await load_saved_sessions()
    global WATCHER
    WATCHER = asyncio.create_task(leave_watcher())
    print("Control bot started.")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Multi-user bot stopped.")
