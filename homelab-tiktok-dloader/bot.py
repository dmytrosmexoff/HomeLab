import asyncio, os, logging, yt_dlp, re, json, time, uuid
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# ======================== ПУТИ UMBREL OS ========================
SAVE_PATH = '/umbrel/umbrel/home/TikTok/'
SETTINGS_FILE = '/data/config/settings.json'
STATS_FILE = '/data/config/stats.json'
MESSAGES_FILE = '/data/config/user_messages.json'
POLLS_FILE = '/data/config/polls.json'
LANG_FILE = '/app/languages.json'
MEDIA_TEMP = '/data/media_temp/'
URL_REGEX = r'https?://[^\s]+'
START_TIME = time.time()

for p in [SAVE_PATH, MEDIA_TEMP, '/data/config/']:
    os.makedirs(p, exist_ok=True)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
pending = {}
progress_data = {}

# ======================== ПЛАТФОРМЫ ========================
PLATFORM_EXTRACTORS = {
    "youtube": {"patterns": [r'(?:youtube\.com|youtu\.be)']},
    "twitter": {"patterns": [r'(?:twitter\.com|x\.com)']},
    "instagram": {"patterns": [r'(?:instagram\.com|instagr\.am)']},
    "facebook": {"patterns": [r'(?:facebook\.com|fb\.watch)']},
    "tiktok": {"patterns": [r'(?:tiktok\.com|vm\.tiktok)']},
    "reddit": {"patterns": [r'(?:reddit\.com|v\.redd\.it)']},
    "vimeo": {"patterns": [r'vimeo\.com']},
    "twitch": {"patterns": [r'(?:twitch\.tv|clips\.twitch\.tv)']},
    "soundcloud": {"patterns": [r'soundcloud\.com']},
    "rutube": {"patterns": [r'rutube\.ru']},
    "dailymotion": {"patterns": [r'dailymotion\.com']}
}

QUALITY_FORMATS = {
    "best": {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4", "ext": "mp4"},
    "medium": {"format": "bestvideo[height<=480]+bestaudio/best[height<=480]/best", "merge_output_format": "mp4", "ext": "mp4"},
    "low": {"format": "bestvideo[height<=240]+bestaudio/best[height<=240]/best", "merge_output_format": "mp4", "ext": "mp4"},
    "audio": {"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], "ext": "mp3"},
}

def detect_platform(url: str) -> str:
    for platform, config in PLATFORM_EXTRACTORS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, url.lower()):
                return platform
    return "unknown"

# ======================== ЯЗЫКИ ========================
def load_languages():
    try:
        with open(LANG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"en": {"start": "Hi! Send me a link to download video", "done": "✅ Done!", "error": "❌ Error", "choose_quality": "Choose quality:", "btn_best": "🎬 Best", "btn_medium": "📱 Medium", "btn_audio": "🔊 Audio", "detected_platform": "🔍 Platform: {platform}"}}

LANGUAGES = load_languages()

def get_text(lang_code, key, **kwargs):
    lang = lang_code if lang_code in LANGUAGES else 'en'
    text = LANGUAGES[lang].get(key) or LANGUAGES.get('en', {}).get(key, key)
    return text.format(**kwargs) if kwargs else text

# ======================== НАСТРОЙКИ ========================
def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)

def get_config():
    s = load_settings()
    token = s.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_raw = s.get("admin_id") or os.environ.get("ADMIN_ID", "")
    try:
        admin_id = int(admin_raw)
    except:
        admin_id = 0
    return token.strip(), admin_id

TOKEN, ADMIN_ID = get_config()
TOKEN_VALID = False
try:
    if TOKEN:
        from aiogram.utils.token import validate_token
        validate_token(TOKEN)
        TOKEN_VALID = True
except:
    pass

bot = Bot(token=TOKEN) if TOKEN_VALID else None
dp = Dispatcher()

# ======================== СТАТИСТИКА ========================
def load_stats():
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"users": {}, "recent": []}

def save_stats(stats):
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Stats error: {e}")

def record_download(user_id: int, user_name: str, url: str, platform: str = "unknown"):
    stats = load_stats()
    uid = str(user_id)
    today = date.today().isoformat()
    
    stats.setdefault("users", {})
    if uid not in stats["users"]:
        stats["users"][uid] = {
            "name": user_name,
            "downloads": 0,
            "errors": 0,
            "last_active": today,
            "urls": []
        }
    
    stats["users"][uid]["downloads"] = stats["users"][uid].get("downloads", 0) + 1
    stats["users"][uid]["last_active"] = today
    stats["users"][uid]["name"] = user_name
    stats["users"][uid].setdefault("urls", [])
    stats["users"][uid]["urls"].insert(0, url)
    stats["users"][uid]["urls"] = stats["users"][uid]["urls"][:50]
    
    save_stats(stats)

def record_error(user_id: int, user_name: str):
    stats = load_stats()
    uid = str(user_id)
    today = date.today().isoformat()
    
    stats.setdefault("users", {})
    if uid not in stats["users"]:
        stats["users"][uid] = {
            "name": user_name,
            "downloads": 0,
            "errors": 0,
            "last_active": today,
            "urls": []
        }
    
    stats["users"][uid]["errors"] = stats["users"][uid].get("errors", 0) + 1
    stats["users"][uid]["last_active"] = today
    
    save_stats(stats)

# ======================== СООБЩЕНИЯ ОТ ЮЗЕРОВ ========================
def load_user_messages():
    try:
        with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_user_messages(messages):
    os.makedirs(os.path.dirname(MESSAGES_FILE), exist_ok=True)
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

def add_user_message(user_id: int, user_name: str, text: str):
    messages = load_user_messages()
    messages.insert(0, {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "user_name": user_name,
        "text": text,
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "read": False
    })
    messages = messages[:100]
    save_user_messages(messages)

# ======================== ГОЛОСОВАНИЯ ========================
def load_polls():
    try:
        with open(POLLS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_polls(polls):
    os.makedirs(os.path.dirname(POLLS_FILE), exist_ok=True)
    with open(POLLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(polls, f, ensure_ascii=False, indent=2)

def create_poll(question: str, options: list, show_days: int):
    polls = load_polls()
    poll = {
        "id": uuid.uuid4().hex,
        "question": question,
        "options": {opt: [] for opt in options},
        "user_votes": {},
        "created": datetime.now().isoformat(),
        "show_until": (datetime.now() + timedelta(days=show_days)).isoformat(),
        "active": True
    }
    polls.append(poll)
    save_polls(polls)
    return poll

def vote_in_poll(poll_id: str, user_id: int, option: str):
    polls = load_polls()
    for poll in polls:
        if poll["id"] == poll_id:
            user_votes = poll.get("user_votes", {})
            uid = str(user_id)
            
            # Удалить старый голос если есть
            old_option = user_votes.get(uid)
            if old_option and old_option in poll["options"]:
                if user_id in poll["options"][old_option]:
                    poll["options"][old_option].remove(user_id)
            
            # Добавить новый голос
            if option in poll["options"]:
                if user_id not in poll["options"][option]:
                    poll["options"][option].append(user_id)
                user_votes[uid] = option
            
            poll["user_votes"] = user_votes
            save_polls(polls)
            return True
    return False

# ======================== СКАЧИВАНИЕ ========================
async def do_download(msg, url, user_name, user_id, lang, quality, platform):
    user_folder = os.path.join(SAVE_PATH, f"{user_name}_{user_id}")
    os.makedirs(user_folder, exist_ok=True)
    
    async with DOWNLOAD_SEMAPHORE:
        try:
            ts = int(time.time())
            opts = {
                "format": QUALITY_FORMATS[quality]["format"],
                "outtmpl": os.path.join(user_folder, f"%(title).30s_{ts}.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
            }
            if quality != "audio":
                opts["merge_output_format"] = "mp4"
            if "postprocessors" in QUALITY_FORMATS[quality]:
                opts["postprocessors"] = QUALITY_FORMATS[quality]["postprocessors"]
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                await asyncio.to_thread(ydl.extract_info, url, download=True)
                record_download(user_id, user_name, url, platform)
                await msg.answer(get_text(lang, "done"))
        except Exception as e:
            record_error(user_id, user_name)
            await msg.answer(get_text(lang, "error"))
            logging.error(f"Download error: {e}")

# ======================== TELEGRAM HANDLERS ========================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    lang = message.from_user.language_code or "en"
    await message.answer(get_text(lang, "start"))

@dp.message(Command("message"))
async def message_handler(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Unknown"
    text = message.text.replace("/message", "").strip()
    
    if not text:
        await message.answer("📝 Напиши сообщение после команды /message текст_сообщения")
        return
    
    add_user_message(user_id, user_name, text)
    await message.answer("✅ Сообщение отправлено админу!")

@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Unknown"
    lang = message.from_user.language_code or "en"
    
    urls = re.findall(URL_REGEX, message.text)
    if not urls:
        return
    
    url = urls[0]
    platform = detect_platform(url)
    await message.answer(get_text(lang, "detected_platform", platform=platform))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Best", callback_data=f"dl_best_{user_id}"),
         InlineKeyboardButton(text="📱 Medium", callback_data=f"dl_medium_{user_id}")],
        [InlineKeyboardButton(text="🐢 Low", callback_data=f"dl_low_{user_id}"),
         InlineKeyboardButton(text="🔊 Audio", callback_data=f"dl_audio_{user_id}")]
    ])
    
    await message.answer(get_text(lang, "choose_quality"), reply_markup=kb)
    pending[str(user_id)] = {"url": url, "platform": platform, "user_name": user_name, "lang": lang}

@dp.callback_query()
async def handle_callback(query: CallbackQuery):
    if query.data.startswith("dl_"):
        parts = query.data.split("_")
        quality = parts[1]
        user_id = int(parts[2])
        
        if str(user_id) not in pending:
            return
        
        data = pending[str(user_id)]
        await query.answer()
        await do_download(query.message, data["url"], data["user_name"], user_id, data["lang"], quality, data["platform"])
        del pending[str(user_id)]

# ======================== ВЕБ-СЕРВЕР ========================
STYLE = """<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0f1115; color:#ccc; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { display:flex; min-height:100vh; }
.nav { background:#1a1d24; width:200px; padding:24px 0; position:fixed; height:100vh; overflow-y:auto; border-right:1px solid #2a2d36; }
.nav a { display:block; padding:12px 16px; color:#aaa; text-decoration:none; transition:all 0.2s; border-left:3px solid transparent; }
.nav a:hover { background:#2a2d36; color:#fff; }
.nav a.active { background:#2a2d36; color:#3D6BFF; border-left-color:#3D6BFF; }
.main { margin-left:200px; padding:32px; flex:1; }
.header { display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #2a2d36; padding-bottom:16px; margin-bottom:24px; }
.logo { font-size:20px; font-weight:700; background:linear-gradient(90deg,#FF3D77,#B43DFF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.cards { display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }
.kpi { background:#1a1d24; border-radius:12px; padding:20px; flex:1; min-width:180px; }
.kpi .val { font-size:28px; font-weight:700; color:#fff; line-height:1.2; }
.kpi .lbl { font-size:12px; color:#6c727f; margin-top:4px; }
.panel { background:#1a1d24; border-radius:16px; padding:24px; margin-bottom:24px; }
.panel h2 { font-size:16px; color:#fff; margin-bottom:20px; font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { color:#6c727f; font-weight:600; padding:12px 16px; border-bottom:1px solid #2a2d36; text-transform:uppercase; font-size:11px; cursor:pointer; user-select:none; }
th:hover { color:#fff; }
td { padding:14px 16px; border-bottom:1px solid #1e2128; color:#ccc; }
tr:hover { background:#252a33; }
.badge { display:inline-block; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600; }
.badge-error { background:rgba(255,61,119,0.1); color:#ff3d77; }
.expand-btn { background:none; border:none; color:#3D6BFF; cursor:pointer; font-size:16px; padding:0; }
.sub-row { display:none; background:#0f1115; }
.sub-row.show { display:table-row; }
.sub-row td { padding:16px; font-size:12px; }
.video-item { padding:8px 0; border-bottom:1px solid #2a2d36; }
.video-item a { color:#3D6BFF; text-decoration:none; font-size:12px; word-break:break-all; }
.video-item a:hover { text-decoration:underline; }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:13px; color:#aaa; margin-bottom:6px; }
input, textarea, select { width:100%; padding:10px 14px; border-radius:8px; border:1px solid #2a2d36; background:#0f1115; color:#fff; font-size:14px; }
input:focus, textarea:focus, select:focus { border-color:#3D6BFF; outline:none; }
textarea { min-height:120px; resize:vertical; }
.btn { display:inline-flex; padding:10px 20px; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; text-decoration:none; }
.btn-primary { background:linear-gradient(90deg,#3D6BFF,#B43DFF); color:#fff; }
.btn-primary:hover { opacity:0.8; }
.search-box { margin-bottom:16px; display:flex; gap:12px; }
.search-box input { flex:1; max-width:400px; }
.expandable-row { cursor:pointer; }
.expandable-row:hover { background:#252a33; }
.poll-result { margin:12px 0; padding:12px; background:#0f1115; border-radius:8px; }
.poll-option { font-size:12px; color:#aaa; margin-bottom:4px; display:flex; justify-content:space-between; }
.poll-bar { width:100%; height:6px; background:#2a2d36; border-radius:3px; overflow:hidden; }
.poll-fill { height:100%; background:linear-gradient(90deg,#3D6BFF,#B43DFF); }
</style>"""

def layout(content, active_tab):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Dashboard</title>{STYLE}</head><body><div class="wrap"><div class="nav"><div class="logo" style="margin-bottom:24px; padding-left:16px;">📥 TT Dloader</div><a href="/" class="{"active" if active_tab=="index" else ""}">📊 Stats</a><a href="/media" class="{"active" if active_tab=="media" else ""}">🎬 Media</a><a href="/broadcast" class="{"active" if active_tab=="broadcast" else ""}">📢 Broadcast</a><a href="/users" class="{"active" if active_tab=="users" else ""}">👥 Users</a><a href="/settings" class="{"active" if active_tab=="settings" else ""}">⚙️ Settings</a></div><div class="main">{content}</div></div></body></html>"""

async def index(request):
    stats = load_stats()
    users = stats.get("users", {})
    search_q = request.rel_url.query.get("q", "").lower()
    
    user_list = []
    for uid, info in users.items():
        if search_q and search_q not in info.get("name", "").lower():
            continue
        user_list.append({
            "uid": uid,
            "name": info.get("name", "Unknown"),
            "downloads": info.get("downloads", 0),
            "errors": info.get("errors", 0),
            "last_active": info.get("last_active", ""),
            "urls": info.get("urls", [])
        })
    
    user_list.sort(key=lambda x: x["downloads"], reverse=True)
    
    rows = ""
    for u in user_list:
        url_html = "".join([f'<div class="video-item"><a href="{url}" target="_blank">{url[:70]}...</a></div>' for url in u["urls"]])
        rows += f"""<tr class="expandable-row" onclick="document.getElementById('sub-{u['uid']}').classList.toggle('show')">
            <td><button class="expand-btn">▼</button> {u['name']}</td>
            <td>{u['downloads']}</td>
            <td>{u['last_active']}</td>
            <td><span class="badge badge-error">{u['errors']}</span></td>
        </tr>
        <tr class="sub-row" id="sub-{u['uid']}">
            <td colspan="4" style="padding:16px;"><div style="font-size:12px;color:#aaa;">Загруженные ссылки:</div>{url_html if url_html else '<div style="color:#666; margin-top:8px;">Нет ссылок</div>'}</td>
        </tr>"""
    
    uptime = str(timedelta(seconds=int(time.time()-START_TIME)))
    total_dl = sum(u["downloads"] for u in user_list)
    total_err = sum(u["errors"] for u in user_list)
    
    c = f"""<div class="header"><div class="logo">📊 Статистика</div><div style="color:#6c727f; font-size:14px;">Аптайм: {uptime}</div></div>
    <div class="cards">
        <div class="kpi"><div class="val">{len(user_list)}</div><div class="lbl">Пользователей</div></div>
        <div class="kpi"><div class="val">{total_dl}</div><div class="lbl">Загрузок</div></div>
        <div class="kpi"><div class="val">{total_err}</div><div class="lbl">Ошибок</div></div>
    </div>
    <div class="panel">
        <h2>🔍 Поиск пользователя</h2>
        <form method="get" class="search-box">
            <input type="text" name="q" placeholder="Введите имя..." value="{search_q}">
            <button type="submit" class="btn btn-primary">Поиск</button>
        </form>
    </div>
    <div class="panel">
        <h2>👥 Пользователи</h2>
        <table>
            <thead><tr><th>👤 Имя</th><th onclick="sortCol(this, 1)">📥 Видео</th><th onclick="sortCol(this, 2)">🕐 Последнее</th><th onclick="sortCol(this, 3)">❌ Ошибок</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет данных</td></tr>'}</tbody>
        </table>
    </div>
    <script>
    function sortCol(el, col) {{
        const tbody = el.closest('table').querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => !r.classList.contains('sub-row'));
        rows.sort((a, b) => {{
            const aVal = a.cells[col]?.textContent || '';
            const bVal = b.cells[col]?.textContent || '';
            return isNaN(aVal) ? aVal.localeCompare(bVal) : parseInt(aVal) - parseInt(bVal);
        }});
        rows.forEach(r => tbody.appendChild(r));
    }}
    </script>"""
    
    return web.Response(text=layout(c, "index"), content_type='text/html')

async def media_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    search_q = request.rel_url.query.get("q", "").lower()
    
    media_data = []
    for uid, info in users.items():
        if search_q and search_q not in info.get("name", "").lower():
            continue
        user_folder = os.path.join(SAVE_PATH, f"{info['name']}_{uid}")
        try:
            files = sorted([f for f in os.listdir(user_folder) if f.endswith(('.mp4', '.mp3'))], reverse=True)
        except:
            files = []
        
        media_data.append({
            "uid": uid,
            "name": info.get("name", "Unknown"),
            "videos": len(files),
            "errors": info.get("errors", 0),
            "last_active": info.get("last_active", ""),
            "files": files
        })
    
    media_data.sort(key=lambda x: x["videos"], reverse=True)
    
    rows = ""
    for m in media_data:
        file_html = "".join([f'<div class="video-item"><a href="/media/file?f={f}&uid={m["uid"]}" target="_blank">🎬 {f}</a></div>' for f in m["files"]])
        rows += f"""<tr class="expandable-row" onclick="document.getElementById('med-{m['uid']}').classList.toggle('show')">
            <td><button class="expand-btn">▼</button> {m['name']}</td>
            <td>{m['videos']}</td>
            <td>{m['last_active']}</td>
            <td><span class="badge badge-error">{m['errors']}</span></td>
        </tr>
        <tr class="sub-row" id="med-{m['uid']}">
            <td colspan="4">{file_html if file_html else '<div style="color:#666; padding:12px;">Нет файлов</div>'}</td>
        </tr>"""
    
    c = f"""<div class="header"><div class="logo">🎬 Медиатека</div></div>
    <div class="panel">
        <h2>🔍 Поиск пользователя</h2>
        <form method="get" class="search-box">
            <input type="text" name="q" placeholder="Введите имя..." value="{search_q}">
            <button type="submit" class="btn btn-primary">Поиск</button>
        </form>
    </div>
    <div class="panel">
        <h2>👥 Пользователи</h2>
        <table>
            <thead><tr><th>👤 Имя</th><th>📹 Видео</th><th>🕐 Последнее</th><th>❌ Ошибок</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет данных</td></tr>'}</tbody>
        </table>
    </div>"""
    
    return web.Response(text=layout(c, "media"), content_type='text/html')

async def media_file(request):
    file = request.rel_url.query.get("f", "")
    uid = request.rel_url.query.get("uid", "")
    stats = load_stats()
    users = stats.get("users", {})
    if uid not in users or ".." in file:
        return web.Response(status=400)
    filepath = os.path.join(SAVE_PATH, f"{users[uid]['name']}_{uid}", file)
    if not os.path.exists(filepath):
        return web.Response(status=404)
    ctype = "video/mp4" if file.endswith(".mp4") else "audio/mpeg"
    return web.FileResponse(filepath, headers={"Content-Type": ctype})

async def broadcast_page(request):
    messages = load_user_messages()
    polls = load_polls()
    
    msg_rows = ""
    for m in messages[:20]:
        msg_rows += f"<tr><td>{m['timestamp']}</td><td>{m['user_name']}</td><td>{m['text'][:60]}</td></tr>"
    
    poll_rows = ""
    for p in polls:
        total = sum(len(v) for v in p["options"].values())
        opts_html = ""
        for opt, voters in p["options"].items():
            pct = int(len(voters) / total * 100) if total > 0 else 0
            opts_html += f'<div class="poll-result"><div class="poll-option"><span>{opt}</span><span>{len(voters)} голосов</span></div><div class="poll-bar"><div class="poll-fill" style="width:{pct}%"></div></div></div>'
        poll_rows += f'<tr><td>{p["question"]}</td><td>{total}</td><td>{opts_html}</td></tr>'
    
    c = f"""<div class="header"><div class="logo">📢 Рассылка</div></div>
    <div class="panel"><h2>📩 Отправить сообщение</h2>
    <form action="/api/broadcast" method="post">
        <div class="form-group"><label>Текст</label><textarea name="text" required></textarea></div>
        <button type="submit" class="btn btn-primary">Отправить всем</button>
    </form></div>
    <div class="panel"><h2>💬 Сообщения от пользователей</h2>
    <table><thead><tr><th>Дата</th><th>Пользователь</th><th>Сообщение</th></tr></thead><tbody>{msg_rows if msg_rows else '<tr><td colspan="3" style="text-align:center;color:#666;">Нет сообщений</td></tr>'}</tbody></table></div>
    <div class="panel"><h2>📊 Создать голосование</h2>
    <form action="/api/poll-create" method="post">
        <div class="form-group"><label>Вопрос</label><input type="text" name="question" required></div>
        <div class="form-group"><label>Варианты (по одному в строке)</label><textarea name="options" rows="4" required></textarea></div>
        <div class="form-group"><label>Показывать результаты</label><select name="days"><option value="1">1 день</option><option value="7">7 дней</option><option value="14">14 дней</option><option value="30">30 дней</option></select></div>
        <button type="submit" class="btn btn-primary">Создать голосование</button>
    </form></div>
    <div class="panel"><h2>📈 Текущие голосования</h2>
    <table><thead><tr><th>Вопрос</th><th>Голосов</th><th>Результаты</th></tr></thead><tbody>{poll_rows if poll_rows else '<tr><td colspan="3" style="text-align:center;color:#666;">Нет голосований</td></tr>'}</tbody></table></div>"""
    
    return web.Response(text=layout(c, "broadcast"), content_type='text/html')

async def api_broadcast(request):
    data = await request.post()
    text = data.get("text", "").strip()
    if text and bot:
        stats = load_stats()
        uids = list(stats.get("users", {}).keys())
        async def send_all():
            for uid in uids:
                try:
                    await bot.send_message(int(uid), text)
                    await asyncio.sleep(0.05)
                except:
                    pass
        asyncio.create_task(send_all())
    return web.HTTPFound('/broadcast')

async def api_poll_create(request):
    data = await request.post()
    question = data.get("question", "").strip()
    options_text = data.get("options", "").strip()
    if question and options_text:
        options = [o.strip() for o in options_text.split('\n') if o.strip()]
        if len(options) >= 2:
            days = int(data.get("days", 1))
            poll = create_poll(question, options, days)
            if bot:
                stats = load_stats()
                uids = list(stats.get("users", {}).keys())
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=opt, callback_data=f"vote_{poll['id']}_{opt}") for opt in options]])
                async def send_poll():
                    for uid in uids:
                        try:
                            await bot.send_message(int(uid), f"📊 {question}", reply_markup=kb)
                            await asyncio.sleep(0.05)
                        except:
                            pass
                asyncio.create_task(send_poll())
    return web.HTTPFound('/broadcast')

@dp.callback_query(lambda c: c.data.startswith("vote_"))
async def vote_handler(query: CallbackQuery):
    parts = query.data.split("_", 2)
    poll_id = parts[1]
    option = parts[2]
    user_id = query.from_user.id
    if vote_in_poll(poll_id, user_id, option):
        await query.answer("✅ Голос учтён!")
    else:
        await query.answer("❌ Ошибка")

async def users_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    rows = ""
    for uid, info in users.items():
        rows += f"<tr><td>{info.get('name')}</td><td>{uid}</td><td>{info.get('downloads', 0)}</td><td><span class='badge badge-error'>{info.get('errors', 0)}</span></td></tr>"
    
    c = f"""<div class="header"><div class="logo">👥 Пользователи</div></div>
    <div class="panel"><h2>Список</h2>
    <table><thead><tr><th>Имя</th><th>ID</th><th>Видео</th><th>Ошибок</th></tr></thead><tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет пользователей</td></tr>'}</tbody></table></div>"""
    return web.Response(text=layout(c, "users"), content_type='text/html')

async def settings_get(request):
    s = load_settings()
    c = f"""<div class="header"><div class="logo">⚙️ Настройки</div></div>
    <div class="panel"><h2>Конфигурация</h2>
    <form action="/api/settings" method="post">
        <div class="form-group"><label>Bot Token</label><input type="text" name="token" value="{s.get('token', '')}" required></div>
        <div class="form-group"><label>Admin ID</label><input type="text" name="admin_id" value="{s.get('admin_id', '')}" required></div>
        <button type="submit" class="btn btn-primary">Сохранить</button>
    </form></div>"""
    return web.Response(text=layout(c, "settings"), content_type='text/html')

async def api_settings(request):
    data = await request.post()
    s = load_settings()
    s['token'] = data.get('token', '').strip()
    s['admin_id'] = data.get('admin_id', '').strip()
    save_settings(s)
    return web.HTTPFound('/settings')

async def start_web():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/media', media_page)
    app.router.add_get('/media/file', media_file)
    app.router.add_get('/broadcast', broadcast_page)
    app.router.add_post('/api/broadcast', api_broadcast)
    app.router.add_post('/api/poll-create', api_poll_create)
    app.router.add_get('/users', users_page)
    app.router.add_get('/settings', settings_get)
    app.router.add_post('/api/settings', api_settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8090)
    await site.start()
    logging.info("Web server started on 0.0.0.0:8090")

async def bot_task():
    if not (bot and ADMIN_ID):
        logging.warning("Bot not configured!")
        await asyncio.Event().wait()
        return
    try:
        await bot.send_message(ADMIN_ID, "🚀 Bot started!")
    except:
        pass
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Polling error: {e}")

async def main():
    await asyncio.gather(bot_task(), start_web())

if __name__ == '__main__':
    asyncio.run(main())
