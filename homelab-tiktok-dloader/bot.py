import asyncio, os, logging, yt_dlp, re, json, time, uuid
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.utils.token import validate_token, TokenValidationError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# --- ПУТИ ДЛЯ UMBREL OS ---
SAVE_PATH    = '/umbrel/umbrel/home/TikTok/'
LANG_FILE    = '/app/languages.json'
SETTINGS_FILE = '/data/config/settings.json'
STATS_FILE   = '/data/config/stats.json'
PENDING_FILE = '/data/config/pending_messages.json'
FAVORITES_FILE = '/data/config/favorites.json'
MESSAGES_FILE = '/data/config/user_messages.json'
POLLS_FILE   = '/data/config/polls.json'
MEDIA_BASE = '/umbrel/umbrel/home/TikTok'
MEDIA_TEMP   = '/data/media_temp/'
URL_REGEX    = r'https?://[^\s]+'
START_TIME   = time.time()

for p in [SAVE_PATH, MEDIA_TEMP, '/data/config/']:
    os.makedirs(p, exist_ok=True)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
pending: dict = {}
progress_data: dict = {}

# ============================== ПЛАТФОРМЫ ==============================
PLATFORM_EXTRACTORS = {
    "youtube": {"patterns": [r'(?:youtube\.com|youtu\.be)'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "twitter": {"patterns": [r'(?:twitter\.com|x\.com)'], "format": "best[ext=mp4]/best", "merge_output_format": "mp4"},
    "instagram": {"patterns": [r'(?:instagram\.com|instagr\.am)'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "facebook": {"patterns": [r'(?:facebook\.com|fb\.watch)'], "format": "best[ext=mp4]/best", "merge_output_format": "mp4"},
    "tiktok": {"patterns": [r'(?:tiktok\.com|vm\.tiktok)'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "reddit": {"patterns": [r'(?:reddit\.com|v\.redd\.it)'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "vimeo": {"patterns": [r'vimeo\.com'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "twitch": {"patterns": [r'(?:twitch\.tv|clips\.twitch\.tv)'], "format": "best[ext=mp4]/best", "merge_output_format": "mp4"},
    "soundcloud": {"patterns": [r'soundcloud\.com'], "format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], "ext": "mp3"},
    "rutube": {"patterns": [r'rutube\.ru'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
    "dailymotion": {"patterns": [r'dailymotion\.com'], "format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"}
}

QUALITY_FORMATS = {
    "best": {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4", "ext": "mp4"},
    "medium": {"format": "bestvideo[height<=480]+bestaudio/best[height<=480]/best", "merge_output_format": "mp4", "ext": "mp4"},
    "low": {"format": "bestvideo[height<=240]+bestaudio/best[height<=240]/best", "merge_output_format": "mp4", "ext": "mp4"},
    "audio": {"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], "ext": "mp3"},
}
FALLBACK_CHAIN = {"best": ["best", "medium", "low"], "medium": ["medium", "low"], "low": ["low"], "audio": ["audio"]}

def detect_platform(url: str) -> str:
    for platform, config in PLATFORM_EXTRACTORS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, url.lower()):
                return platform
    return "unknown"

# ============================== ЯЗЫКИ ==============================
def load_languages():
    try:
        with open(LANG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"en": {"start": "Hi! Send me a link to a video and I'll download it.", "done": "✅ Done, {name}!", "error": "❌ Error while downloading.", "choose_quality": "🎬 Choose quality:", "btn_best": "🎬 Best", "btn_medium": "📱 Medium (480p)", "btn_audio": "🔊 Audio (mp3)", "queued": "⏳ Added to queue...", "quality_low": "🐢 Low (240p)", "downgraded": "⚠️ Downloaded as {quality}", "detected_platform": "🔍 Detected: {platform}"}}
LANGUAGES = load_languages()

def get_text(lang_code, key, **kwargs):
    lang = lang_code if lang_code in LANGUAGES else 'en'
    text = LANGUAGES[lang].get(key) or LANGUAGES.get('en', {}).get(key, key)
    return text.format(**kwargs) if kwargs else text

# ============================== НАСТРОЙКИ ==============================
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

def current_config():
    s = load_settings()
    token = s.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_raw = s.get("admin_id") or os.environ.get("ADMIN_ID", "")
    try: admin_id = int(admin_raw)
    except: admin_id = 0
    return token.strip(), admin_id

TOKEN, ADMIN_ID = current_config()
TOKEN_VALID = False
if TOKEN:
    try:
        validate_token(TOKEN)
        TOKEN_VALID = True
    except: pass
bot = Bot(token=TOKEN) if TOKEN_VALID else None
dp = Dispatcher()

# ============================== СТАТИСТИКА ==============================
def load_stats():
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"downloads": {}, "users": {}, "recent": [], "errors": {}}

def save_stats(stats):
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Stats save error: {e}")

def record_error(user_id: int, user_name: str):
    stats = load_stats()
    uid = str(user_id)
    stats.setdefault("users", {})
    if uid not in stats["users"]:
        stats["users"][uid] = {"name": user_name, "downloads": 0, "errors": 0, "last_active": date.today().isoformat()}
    stats["users"][uid]["errors"] = stats["users"][uid].get("errors", 0) + 1
    stats["users"][uid]["last_active"] = date.today().isoformat()
    save_stats(stats)

def record_download(user_id: int, user_name: str, url: str, platform: str = "unknown"):
    today = date.today().isoformat()
    stats = load_stats()
    uid = str(user_id)
    stats.setdefault("users", {})
    if uid not in stats["users"]:
        stats["users"][uid] = {"name": user_name, "downloads": 0, "errors": 0, "last_active": today}
    stats["users"][uid]["downloads"] = stats["users"][uid].get("downloads", 0) + 1
    stats["users"][uid]["last_active"] = today
    save_stats(stats)

# ============================== СООБЩЕНИЯ ОТ ЮЗЕРОВ ==============================
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
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    })
    messages = messages[:100]
    save_user_messages(messages)

# ============================== ГОЛОСОВАНИЯ ==============================
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

# ============================== СКАЧИВАНИЕ ==============================
def make_progress_hook(uid):
    def hook(d):
        try:
            if d['status'] == 'finished':
                if uid in progress_data:
                    progress_data[uid]["status"] = "completed"
        except:
            pass
    return hook

async def do_download(status_msg, url, user_name, user_id, lang_code, requested_quality, platform="unknown"):
    user_folder = os.path.join(SAVE_PATH, f"{user_name}_{user_id}")
    os.makedirs(user_folder, exist_ok=True)
    
    chain = FALLBACK_CHAIN.get(requested_quality, [requested_quality])
    async with DOWNLOAD_SEMAPHORE:
        result = False
        for attempt_quality in chain:
            q_cfg = QUALITY_FORMATS[attempt_quality]
            try:
                ts = int(time.time())
                opts = {
                    "format": q_cfg["format"],
                    "outtmpl": os.path.join(user_folder, f"%(title).30s_{ts}.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                }
                if attempt_quality != "audio":
                    opts["merge_output_format"] = "mp4"
                if "postprocessors" in q_cfg:
                    opts["postprocessors"] = q_cfg["postprocessors"]
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    record_download(user_id, user_name, url, platform)
                    result = True
                    break
            except:
                continue
        
        if result:
            try:
                await status_msg.answer(get_text(lang_code, "done", name=user_name))
            except:
                pass
        else:
            record_error(user_id, user_name)
            try:
                await status_msg.answer(get_text(lang_code, "error"))
            except:
                pass

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    lang = message.from_user.language_code or "en"
    await message.answer(get_text(lang, "start"))

@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Unknown"
    lang = message.from_user.language_code or "en"
    
    urls = re.findall(URL_REGEX, message.text)
    if not urls:
        await message.answer("❌ Link not found")
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
    msg = await message.answer(get_text(lang, "choose_quality"), reply_markup=kb)
    pending[f"{user_id}"] = {"url": url, "platform": platform, "user_name": user_name, "lang": lang}

@dp.callback_query()
async def handle_callback(query: CallbackQuery):
    if query.data.startswith("dl_"):
        parts = query.data.split("_")
        quality = parts[1]
        user_id = int(parts[2])
        
        if str(user_id) not in pending:
            await query.answer("❌ Data expired")
            return
        
        data = pending[str(user_id)]
        url = data["url"]
        user_name = data["user_name"]
        lang = data["lang"]
        platform = data["platform"]
        
        await query.answer()
        await do_download(query.message, url, user_name, user_id, lang, quality, platform)
        del pending[str(user_id)]

# ============================== ВЕБ-СЕРВЕР ==============================

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
.kpi .val { font-size:28px; font-weight:700; color:#fff; }
.kpi .lbl { font-size:12px; color:#6c727f; margin-top:4px; }
.panel { background:#1a1d24; border-radius:16px; padding:24px; margin-bottom:24px; }
.panel h2 { font-size:16px; color:#fff; margin-bottom:20px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { color:#6c727f; font-weight:600; padding:12px 16px; border-bottom:1px solid #2a2d36; text-transform:uppercase; font-size:11px; cursor:pointer; }
th:hover { color:#fff; }
td { padding:14px 16px; border-bottom:1px solid #1e2128; color:#ccc; }
tr:hover { background:#252a33; }
.badge { display:inline-block; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600; }
.badge-error { background:rgba(255,61,119,0.1); color:#ff3d77; }
.btn { display:inline-flex; padding:10px 20px; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; text-decoration:none; }
.btn-primary { background:linear-gradient(90deg,#3D6BFF,#B43DFF); color:#fff; }
.btn-primary:hover { opacity:0.8; }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:13px; color:#aaa; margin-bottom:6px; }
input, textarea, select { width:100%; padding:10px 14px; border-radius:8px; border:1px solid #2a2d36; background:#0f1115; color:#fff; font-size:14px; }
input:focus, textarea:focus, select:focus { border-color:#3D6BFF; }
textarea { min-height:120px; resize:vertical; }
.expand-btn { background:none; border:none; color:#3D6BFF; cursor:pointer; font-size:16px; padding:0; }
.sub-row { display:none; background:#0f1115; }
.sub-row.show { display:table-row; }
.sub-row td { padding:16px; font-size:12px; }
.video-item { padding:8px 0; border-bottom:1px solid #2a2d36; }
.video-item a { color:#3D6BFF; text-decoration:none; }
.video-item a:hover { text-decoration:underline; }
</style>"""

def layout(content, active_tab):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Dashboard</title>{STYLE}</head><body><div class="wrap"><div class="nav"><div class="logo" style="margin-bottom:24px; padding-left:16px;">📥 Downloader</div><a href="/" class="{"active" if active_tab=="index" else ""}">📊 Stats</a><a href="/media" class="{"active" if active_tab=="media" else ""}">🎬 Media</a><a href="/broadcast" class="{"active" if active_tab=="broadcast" else ""}">📢 Broadcast</a><a href="/users" class="{"active" if active_tab=="users" else ""}">👥 Users</a><a href="/settings" class="{"active" if active_tab=="settings" else ""}">⚙️ Settings</a></div><div class="main">{content}</div></div></body></html>"""

async def index(request):
    stats = load_stats()
    users = stats.get("users", {})
    search_q = request.rel_url.query.get("q", "").lower()
    
    user_list = []
    for uid, info in users.items():
        if search_q and search_q not in info.get("name", "").lower():
            continue
        user_list.append({"uid": uid, "name": info.get("name"), "downloads": info.get("downloads", 0), "errors": info.get("errors", 0), "last_active": info.get("last_active", "")})
    
    user_list.sort(key=lambda x: x["downloads"], reverse=True)
    
    rows = ""
    for u in user_list:
        rows += f"""<tr onclick="fetch('/api/user-urls?uid={u['uid']}').then(r=>r.json()).then(d=>document.getElementById('urls-{u['uid']}').innerHTML=d.urls.map(x=>'<div class=video-item><a href=#>'+x.substring(0,50)+'...</a></div>').join(''))" style="cursor:pointer;">
            <td><button class="expand-btn">▼</button> {u['name']}</td><td>{u['downloads']}</td><td>{u['last_active']}</td><td><span class="badge badge-error">{u['errors']}</span></td>
        </tr>
        <tr class="sub-row" id="sub-{u['uid']}"><td colspan="4" style="padding:16px;"><div id="urls-{u['uid']}"></div></td></tr>"""
    
    uptime = str(timedelta(seconds=int(time.time()-START_TIME)))
    total_dl = sum(u["downloads"] for u in user_list)
    total_err = sum(u["errors"] for u in user_list)
    
    c = f"""<div class="header"><div class="logo">📊 Statistics</div><div style="color:#6c727f; font-size:14px;">Uptime: {uptime}</div></div>
    <div class="cards">
        <div class="kpi"><div class="val">{len(user_list)}</div><div class="lbl">Users</div></div>
        <div class="kpi"><div class="val">{total_dl}</div><div class="lbl">Downloads</div></div>
        <div class="kpi"><div class="val">{total_err}</div><div class="lbl">Errors</div></div>
    </div>
    <div class="panel">
        <h2>🔍 Search</h2>
        <form method="get" style="display:flex; gap:12px;">
            <input type="text" name="q" placeholder="User name..." value="{search_q}" style="flex:1;">
            <button type="submit" class="btn btn-primary">Search</button>
        </form>
    </div>
    <div class="panel">
        <h2>👥 Users</h2>
        <table><thead><tr><th>Name</th><th>Videos</th><th>Last</th><th>Errors</th></tr></thead><tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">No data</td></tr>'}</tbody></table>
    </div>
    <script>
    document.querySelectorAll('tbody tr[onclick]').forEach(tr => {{
        tr.addEventListener('click', e => {{
            const subRow = tr.nextElementSibling;
            if (subRow && subRow.classList.contains('sub-row')) subRow.classList.toggle('show');
        }});
    }});
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
            files = sorted([f for f in os.listdir(user_folder) if f.endswith(('.mp4', '.mp3'))])
        except:
            files = []
        
        media_data.append({"uid": uid, "name": info.get("name"), "downloads": len(files), "errors": info.get("errors", 0), "last_active": info.get("last_active", ""), "files": files})
    
    media_data.sort(key=lambda x: x["downloads"], reverse=True)
    
    rows = ""
    for m in media_data:
        file_html = "".join([f'<div class="video-item"><a href="/media/file?file={f}&uid={m["uid"]}" target="_blank">{f}</a></div>' for f in m["files"]])
        rows += f"""<tr onclick="document.getElementById('media-{m['uid']}').classList.toggle('show')" style="cursor:pointer;">
            <td><button class="expand-btn">▼</button> {m['name']}</td><td>{m['downloads']}</td><td>{m['last_active']}</td><td><span class="badge badge-error">{m['errors']}</span></td>
        </tr>
        <tr class="sub-row" id="media-{m['uid']}"><td colspan="4">{file_html or '<div style="color:#666;">No files</div>'}</td></tr>"""
    
    c = f"""<div class="header"><div class="logo">🎬 Media</div></div>
    <div class="panel">
        <h2>🔍 Search</h2>
        <form method="get" style="display:flex; gap:12px;">
            <input type="text" name="q" placeholder="User name..." value="{search_q}" style="flex:1;">
            <button type="submit" class="btn btn-primary">Search</button>
        </form>
    </div>
    <div class="panel">
        <h2>👥 Users</h2>
        <table><thead><tr><th>Name</th><th>Videos</th><th>Last</th><th>Errors</th></tr></thead><tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">No data</td></tr>'}</tbody></table>
    </div>"""
    return web.Response(text=layout(c, "media"), content_type='text/html')

async def media_file(request):
    file = request.rel_url.query.get("file", "")
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

async def api_user_urls(request):
    uid = request.rel_url.query.get("uid", "")
    stats = load_stats()
    users = stats.get("users", {})
    if uid not in users:
        return web.Response(text=json.dumps({"urls": []}), content_type='application/json')
    user_folder = os.path.join(SAVE_PATH, f"{users[uid]['name']}_{uid}")
    try:
        with open(os.path.join(user_folder, "history.txt"), "r", encoding="utf-8") as f:
            lines = f.readlines()
            urls = [line.split()[-1] for line in lines if line.strip()]
            return web.Response(text=json.dumps({"urls": urls[-20:]}), content_type='application/json')
    except:
        return web.Response(text=json.dumps({"urls": []}), content_type='application/json')

async def broadcast_page(request):
    messages = load_user_messages()
    msg_rows = ""
    for m in messages:
        msg_rows += f"<tr><td>{m['timestamp']}</td><td>{m['user_name']}</td><td>{m['text'][:60]}</td></tr>"
    
    c = f"""<div class="header"><div class="logo">📢 Broadcast</div></div>
    <div class="panel"><h2>📩 Send Message</h2>
    <form action="/broadcast/send" method="post">
        <div class="form-group"><label>Text</label><textarea name="text" required></textarea></div>
        <button type="submit" class="btn btn-primary">Send</button>
    </form></div>
    <div class="panel"><h2>💬 User Messages</h2>
    <table><thead><tr><th>Date</th><th>User</th><th>Message</th></tr></thead><tbody>{msg_rows if msg_rows else '<tr><td colspan="3" style="text-align:center;color:#666;">No messages</td></tr>'}</tbody></table></div>
    <div class="panel"><h2>📊 Create Poll</h2>
    <form action="/polls/create" method="post">
        <div class="form-group"><label>Question</label><input type="text" name="question" required></div>
        <div class="form-group"><label>Options (one per line)</label><textarea name="options" rows="4" required></textarea></div>
        <div class="form-group"><label>Show results</label><select name="days"><option value="1">1 day</option><option value="7">7 days</option><option value="14">14 days</option><option value="30">30 days</option></select></div>
        <button type="submit" class="btn btn-primary">Create</button>
    </form></div>"""
    return web.Response(text=layout(c, "broadcast"), content_type='text/html')

async def send_broadcast(request):
    data = await request.post()
    text = data.get("text", "").strip()
    if text and bot:
        stats = load_stats()
        uids = list(stats.get("users", {}).keys())
        async def run():
            for uid in uids:
                try:
                    await bot.send_message(int(uid), text)
                    await asyncio.sleep(0.05)
                except:
                    pass
        asyncio.create_task(run())
    return web.HTTPFound('/broadcast')

async def polls_create(request):
    data = await request.post()
    question = data.get("question", "").strip()
    options_text = data.get("options", "").strip()
    if question and options_text:
        options = [o.strip() for o in options_text.split('\n') if o.strip()]
        if len(options) >= 2:
            days = int(data.get("days", 1))
            polls = load_polls()
            polls.append({
                "id": uuid.uuid4().hex,
                "question": question,
                "options": {opt: [] for opt in options},
                "days": days
            })
            save_polls(polls)
    return web.HTTPFound('/broadcast')

async def users_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    rows = ""
    for uid, info in users.items():
        rows += f"<tr><td>{info.get('name')}</td><td>{uid}</td><td>{info.get('downloads', 0)}</td><td><span class='badge badge-error'>{info.get('errors', 0)}</span></td></tr>"
    c = f"""<div class="header"><div class="logo">👥 Users</div></div>
    <div class="panel"><h2>List</h2>
    <table><thead><tr><th>Name</th><th>ID</th><th>Videos</th><th>Errors</th></tr></thead><tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">No users</td></tr>'}</tbody></table></div>"""
    return web.Response(text=layout(c, "users"), content_type='text/html')

async def settings_get(request):
    s = load_settings()
    c = f"""<div class="header"><div class="logo">⚙️ Settings</div></div>
    <div class="panel"><h2>Config</h2>
    <form action="/settings" method="post">
        <div class="form-group"><label>Bot Token</label><input type="text" name="token" value="{s.get('token', '')}" required></div>
        <div class="form-group"><label>Admin ID</label><input type="text" name="admin_id" value="{s.get('admin_id', '')}" required></div>
        <button type="submit" class="btn btn-primary">Save</button>
    </form></div>"""
    return web.Response(text=layout(c, "settings"), content_type='text/html')

async def settings_post(request):
    data = await request.post()
    s = load_settings()
    s['token'] = data.get('token', '').strip()
    s['admin_id'] = data.get('admin_id', '').strip()
    save_settings(s)
    return web.HTTPFound('/settings')

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/media', media_page)
    app.router.add_get('/media/file', media_file)
    app.router.add_get('/api/user-urls', api_user_urls)
    app.router.add_get('/broadcast', broadcast_page)
    app.router.add_post('/broadcast/send', send_broadcast)
    app.router.add_post('/polls/create', polls_create)
    app.router.add_get('/users', users_page)
    app.router.add_get('/settings', settings_get)
    app.router.add_post('/settings', settings_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 4545)
    await site.start()
    logging.info("Web server started on 0.0.0.0:4545")

async def bot_task():
    if not (bot and ADMIN_ID):
        logging.warning("Bot not configured. Open web interface → Settings.")
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
    await asyncio.gather(bot_task(), start_web_server())

if __name__ == '__main__':
    asyncio.run(main())
