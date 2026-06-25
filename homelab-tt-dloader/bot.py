import asyncio, os, logging, yt_dlp, re, json, time, uuid
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.utils.token import validate_token, TokenValidationError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# --- ПУТИ ---
SAVE_PATH    = '/data/downloads/'
LANG_FILE    = '/app/languages.json'
SETTINGS_FILE = '/data/config/settings.json'
STATS_FILE   = '/data/config/stats.json'
PENDING_FILE = '/data/config/pending_messages.json'
FAVORITES_FILE = '/data/config/favorites.json'
MEDIA_BASE = '/data/downloads/TikTok'
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
    translator_key = s.get("translator_api_key", "")
    return token.strip(), admin_id, translator_key

TOKEN, ADMIN_ID, TRANSLATOR_KEY = current_config()
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
        return {"downloads": {}, "users": {}, "recent": [], "errors": {}, "quality_stats": {}, "platform_stats": {}, "lang_stats": {}}

def save_stats(stats):
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Stats save error: {e}")

def record_user_language(user_id, lang_code):
    stats = load_stats()
    stats.setdefault("lang_stats", {})
    lang = lang_code or "unknown"
    stats["lang_stats"][lang] = stats["lang_stats"].get(lang, 0) + 1
    
    # Обновляем язык в профиле пользователя
    stats.setdefault("users", {})
    uid = str(user_id)
    if uid in stats["users"]:
        stats["users"][uid]["lang"] = lang
    else:
        # Если пользователь ещё не создан, создаём с языком
        stats["users"][uid] = {
            "name": "Unknown",
            "first_seen": date.today().isoformat(),
            "last_active": date.today().isoformat(),
            "lang": lang
        }
    save_stats(stats)

def get_top_languages(limit=10):
    stats = load_stats()
    lang_stats = stats.get("lang_stats", {})
    return sorted(lang_stats.items(), key=lambda x: x[1], reverse=True)[:limit]

def record_error(day: str):
    stats = load_stats()
    stats.setdefault("quality_stats", {})
    stats["quality_stats"].setdefault(day, {"success": 0, "downgraded": 0, "error": 0})
    stats["quality_stats"][day]["error"] += 1
    save_stats(stats)

def record_download(user_id: int, user_name: str, url: str, requested_quality: str, achieved_quality: str, platform: str = "unknown", lang_code: str = None):
    today = date.today().isoformat()
    stats = load_stats()
    stats.setdefault("downloads", {})
    stats["downloads"][today] = stats["downloads"].get(today, 0) + 1
    stats.setdefault("users", {})
    uid = str(user_id)
    if uid not in stats["users"]:
        stats["users"][uid] = {
            "name": user_name,
            "first_seen": today,
            "last_active": today,
            "lang": lang_code or "unknown"
        }
    else:
        stats["users"][uid]["last_active"] = today
        stats["users"][uid]["name"] = user_name
        if lang_code:
            stats["users"][uid]["lang"] = lang_code
    stats.setdefault("platform_stats", {})
    stats["platform_stats"][platform] = stats["platform_stats"].get(platform, 0) + 1
    stats.setdefault("recent", [])
    stats["recent"].insert(0, {"ts": datetime.now().strftime("%d.%m %H:%M"), "user": user_name, "user_id": user_id, "url": url, "quality": achieved_quality, "requested": requested_quality, "downgraded": achieved_quality != requested_quality, "platform": platform})
    stats["recent"] = stats["recent"][:20]
    stats.setdefault("quality_stats", {})
    stats["quality_stats"].setdefault(today, {"success": 0, "downgraded": 0, "error": 0})
    if achieved_quality != requested_quality:
        stats["quality_stats"][today]["downgraded"] += 1
    else:
        stats["quality_stats"][today]["success"] += 1
    save_stats(stats)

def get_chart_data(days=14):
    stats = load_stats()
    today = date.today()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days-1, -1, -1)]
    downloads_by_day = stats.get("downloads", {})
    users = stats.get("users", {})
    quality_stats = stats.get("quality_stats", {})
    platform_stats = stats.get("platform_stats", {})
    downloads_data = [downloads_by_day.get(d, 0) for d in labels]
    new_users_data = [sum(1 for u in users.values() if u.get("first_seen") == d) for d in labels]
    active_returning = []
    today_str = today.isoformat()
    for d in labels:
        if d == today_str:
            active_returning.append(sum(1 for u in users.values() if u.get("last_active") == today_str and u.get("first_seen") != today_str))
        else:
            active_returning.append(0)
    success_data = [quality_stats.get(d, {}).get("success", 0) for d in labels]
    downgraded_data = [quality_stats.get(d, {}).get("downgraded", 0) for d in labels]
    error_data = [quality_stats.get(d, {}).get("error", 0) for d in labels]
    short_labels = [d[5:].replace("-", ".") for d in labels]
    top_platforms = sorted(platform_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "labels": short_labels,
        "downloads": downloads_data,
        "new_users": new_users_data,
        "active_returning": active_returning,
        "success": success_data,
        "downgraded": downgraded_data,
        "errors": error_data,
        "total_users": len(users),
        "total_downloads": sum(downloads_by_day.values()),
        "total_errors": sum(error_data),
        "active_today": active_returning[-1] if active_returning else 0,
        "recent": stats.get("recent", []),
        "top_platforms": top_platforms,
        "top_languages": get_top_languages(10)
    }

def mask_token(token):
    if not token or len(token) < 10:
        return "не задан"
    return f"{token[:6]}…{token[-4:]}"

# ============================== ПРОГРЕСС И СКАЧИВАНИЕ ==============================
def format_speed(speed_bytes: float) -> str:
    if speed_bytes is None:
        return "N/A"
    units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
    for unit in units:
        if speed_bytes < 1024:
            return f"{speed_bytes:.1f} {unit}"
        speed_bytes /= 1024
    return f"{speed_bytes:.1f} TB/s"

def format_eta(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "N/A"
    if seconds < 60:
        return f"{int(seconds)} сек"
    elif seconds < 3600:
        return f"{int(seconds // 60)} мин {int(seconds % 60)} сек"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}ч {minutes}м"

def make_progress_hook(uid):
    """Возвращает хук прогресса, привязанный к конкретному user_id через замыкание"""
    def hook(d):
        try:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                downloaded = d.get('downloaded_bytes', 0)
                percent = int((downloaded / total) * 100) if total > 0 else 0
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                if uid in progress_data:
                    progress_data[uid]["percent"] = percent
                    progress_data[uid]["speed"] = format_speed(speed)
                    progress_data[uid]["eta"] = format_eta(eta)
                    progress_data[uid]["status"] = "downloading"
            elif d['status'] == 'finished':
                if uid in progress_data:
                    progress_data[uid]["percent"] = 100
                    progress_data[uid]["speed"] = "0 B/s"
                    progress_data[uid]["eta"] = "0 сек"
                    progress_data[uid]["status"] = "completed"
        except Exception as e:
            logging.error(f"Progress hook error: {e}")
    return hook

async def update_progress_deluxe(status_msg, user_id, lang_code, queue_msg=None):
    """Анимированный прогресс с часами и спиннером"""
    clock_frames = ["🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚","🕛"]
    spinner_frames = ["⣾","⣽","⣻","⢿","⡿","⣟","⣯","⣷"]
    clock_idx = 0
    spinner_idx = 0
    progress_msg = None
    while True:
        try:
            if user_id not in progress_data:
                await asyncio.sleep(0.3)
                continue
            
            data = progress_data[user_id]
            percent = data.get('percent', 0)
            speed = data.get('speed', 'N/A')
            eta = data.get('eta', 'N/A')
            status = data.get('status', 'downloading')
            
            # Если загрузка завершена (100%)
            if percent >= 100 or status == 'completed':
                # Удаляем сообщение "В очереди"
                if queue_msg:
                    try:
                        await queue_msg.delete()
                    except:
                        pass
                
                # Удаляем сообщение с прогрессом
                if progress_msg:
                    try:
                        await progress_msg.delete()
                    except:
                        pass
                
                # Удаляем из progress_data
                if user_id in progress_data:
                    del progress_data[user_id]
                
                break
            
            # Анимируем часы и спиннер
            clock = clock_frames[clock_idx % len(clock_frames)]
            clock_idx += 1
            spinner = spinner_frames[spinner_idx % len(spinner_frames)]
            spinner_idx += 1
            
            # Прогресс-бар
            bar_length = 20
            filled = int(bar_length * percent / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            text = f"{clock} **{percent}%** {spinner}\n\n`{bar}`\n⚡ {speed}\n⏱️ {eta}"
            
            # Отправляем или обновляем сообщение с прогрессом
            if progress_msg is None:
                progress_msg = await status_msg.answer(text, parse_mode="Markdown")
            else:
                try:
                    await progress_msg.edit_text(text, parse_mode="Markdown")
                except:
                    progress_msg = await status_msg.answer(text, parse_mode="Markdown")
            
            await asyncio.sleep(0.4)

        except asyncio.CancelledError:
            if progress_msg:
                try:
                    await progress_msg.delete()
                except:
                    pass
            raise
        except Exception as e:
            logging.error(f"Progress update error: {e}")
            await asyncio.sleep(0.4)

async def do_download(status_msg, url, user_name, user_id, lang_code, requested_quality, platform="unknown"):
    user_folder = os.path.join(SAVE_PATH, f"{user_name}_{user_id}")
    os.makedirs(user_folder, exist_ok=True)
    log_file = os.path.join(user_folder, "history.txt")
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{now_str}] [запрос: {requested_quality}] [платформа: {platform}] {url}\n")
    
    chain = FALLBACK_CHAIN.get(requested_quality, [requested_quality])
    async with DOWNLOAD_SEMAPHORE:
        achieved_quality = None
        result_media = None
        
        for attempt_quality in chain:
            q_cfg = QUALITY_FORMATS[attempt_quality]
            format_str = q_cfg["format"]
            if platform in ["twitter", "facebook"]:
                format_str = "best[ext=mp4]/best"
            try:
                ts = int(time.time())
                opts = {
                    "format": format_str,
                    "outtmpl": os.path.join(user_folder, f"%(title).30s_{ts}.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "progress_hooks": [make_progress_hook(user_id)],
                    "compat_opts": {"filename-sanitization": "windows"},
                }
                if attempt_quality != "audio":
                    opts["merge_output_format"] = "mp4"
                if "postprocessors" in q_cfg:
                    opts["postprocessors"] = q_cfg["postprocessors"]
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    
                    paths = []
                    if "requested_downloads" in info:
                        for d in info["requested_downloads"]:
                            paths.append(d["filepath"])
                    else:
                        paths.append(ydl.prepare_filename(info))
                    
                    img_ext = ('.jpg','.jpeg','.png','.webp')
                    images = [p for p in paths if p.lower().endswith(img_ext)]
                    videos = [p for p in paths if p.lower().endswith(('.mp4','.mkv','.webm'))]
                    audios = [p for p in paths if p.lower().endswith(('.mp3','.m4a','.ogg'))]
                
                achieved_quality = attempt_quality
                result_media = (images, videos, audios)
                break
            except Exception as e:
                logging.warning(f"Quality '{attempt_quality}' failed: {e}")
                continue
        
        if achieved_quality is None:
            record_error(date.today().isoformat())
            try:
                await status_msg.edit_text(get_text(lang_code, 'error'))
            except:
                pass
            return
        
        images, videos, audios = result_media
        caption = get_text(lang_code, 'done', name=user_name)
        
        try:
            if len(images) > 1:
                mg = MediaGroupBuilder(caption=caption)
                for p in sorted(images)[:10]:
                    mg.add_photo(media=types.FSInputFile(p))
                await status_msg.answer_media_group(media=mg.build())
            elif audios:
                await status_msg.answer_audio(types.FSInputFile(audios[0]), caption=caption)
            elif videos:
                await status_msg.answer_video(types.FSInputFile(videos[0]), caption=caption)
            elif images:
                await status_msg.answer_photo(types.FSInputFile(images[0]), caption=caption)
        except Exception as e:
            logging.error(f"Send error: {e}")
            record_error(date.today().isoformat())
            try:
                await status_msg.edit_text(get_text(lang_code, 'error'))
            except:
                pass
            return
        
        # Записываем скачивание с языком
        lang = lang_code or "unknown"
        record_download(user_id, user_name, url, requested_quality, achieved_quality, platform, lang)
        
        quality_labels = {
            "best": get_text(lang_code, 'btn_best'),
            "medium": get_text(lang_code, 'btn_medium'),
            "low": get_text(lang_code, 'quality_low'),
            "audio": get_text(lang_code, 'btn_audio')
        }
        
        if achieved_quality != requested_quality:
            try:
                await status_msg.edit_text(
                    get_text(lang_code, 'downgraded', quality=quality_labels.get(achieved_quality, achieved_quality))
                )
            except:
                pass
        
        if bot and ADMIN_ID:
            platform_label = get_text(lang_code, f"platform_{platform}") or platform
            admin_msg = (
                f"📥 **Скачано медиа:**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"👤 **Имя:** {user_name}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"🌐 **Платформа:** {platform_label}\n"
                f"🎚 **Качество:** {quality_labels.get(achieved_quality, achieved_quality)}"
                f"{' (запрошено: ' + quality_labels.get(requested_quality, requested_quality) + ')' if achieved_quality != requested_quality else ''}\n"
                f"🌍 **Язык:** {lang_code}\n"
                f"🔗 **Ссылка:** {url}"
            )
            await bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")

# ============================== ХЕНДЛЕРЫ БОТА ==============================
@dp.message(Command("start"))
async def start(message: types.Message):
    record_user_language(message.from_user.id, message.from_user.language_code)
    await message.answer(get_text(message.from_user.language_code, 'start'))

@dp.message(Command("stats"))
async def get_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        data = get_chart_data(7)
        platform_text = "\n".join([f"  • {p}: {c}" for p,c in data['top_platforms']]) if data['top_platforms'] else "Нет данных"
        lang_text = "\n".join([f"  • {l}: {c}" for l,c in data['top_languages']]) if data['top_languages'] else "Нет данных"
        stats_msg = (
            f"📊 **Статистика бота:**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👥 **Всего пользователей:** {data['total_users']}\n"
            f"📥 **Всего скачиваний:** {data['total_downloads']}\n"
            f"🟢 **Активны сегодня:** {data['active_today']}\n"
            f"📁 **Путь хранения:** `{SAVE_PATH}`\n\n"
            f"🌐 **Популярные платформы:**\n{platform_text}\n\n"
            f"🗣️ **Топ языков:**\n{lang_text}"
        )
        await message.answer(stats_msg, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(lambda msg: (msg.text and "http" in msg.text) or (msg.caption and "http" in msg.caption))
async def ask_quality(message: types.Message):
    lang_code = message.from_user.language_code or "en"
    full_text = message.text or message.caption or ""
    match = re.search(URL_REGEX, full_text)
    if not match:
        return
    
    url = match.group(0).strip()
    key = uuid.uuid4().hex[:12]
    platform = detect_platform(url)
    platform_label = get_text(lang_code, f"platform_{platform}") or platform
    
    # Чистим старые записи
    now = time.time()
    for k in list(pending.keys()):
        if now - pending[k]["ts"] > 600:
            del pending[k]
    
    # Сохраняем в pending с ID сообщений
    pending[key] = {
        "url": url,
        "user_id": message.from_user.id,
        "user_name": message.from_user.first_name or "User",
        "lang_code": lang_code,
        "ts": now,
        "platform": platform
    }
    
    # Отправляем сообщение о платформе
    platform_msg = await message.answer(
        get_text(lang_code, 'detected_platform', platform=platform_label)
    )
    pending[key]["platform_msg_id"] = platform_msg.message_id
    
    # Отправляем сообщение с выбором качества
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text(lang_code, 'btn_best'), callback_data=f"q:best:{key}"),
            InlineKeyboardButton(text=get_text(lang_code, 'btn_medium'), callback_data=f"q:medium:{key}")
        ],
        [
            InlineKeyboardButton(text=get_text(lang_code, 'btn_audio'), callback_data=f"q:audio:{key}")
        ]
    ])
    quality_msg = await message.answer(
        get_text(lang_code, 'choose_quality'),
        reply_markup=keyboard
    )
    pending[key]["quality_msg_id"] = quality_msg.message_id

@dp.callback_query(F.data.startswith("q:"))
async def handle_quality_choice(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    
    _, requested_quality, key = parts
    info = pending.pop(key, None)
    if not info:
        await callback.message.edit_text("❌ Ссылка устарела. Отправь её снова.")
        await callback.answer()
        return
    
    # Удаляем сообщение о платформе
    try:
        await callback.bot.delete_message(
            callback.message.chat.id,
            info["platform_msg_id"]
        )
    except:
        pass
    
    # Удаляем сообщение с выбором качества
    try:
        await callback.bot.delete_message(
            callback.message.chat.id,
            info["quality_msg_id"]
        )
    except:
        pass
    
    url = info["url"]
    user_name = info["user_name"]
    user_id = info["user_id"]
    lang_code = info["lang_code"]
    platform = info.get("platform", "unknown")
    
    # Отправляем сообщение "В очереди"
    queue_msg = await callback.message.answer(
        get_text(lang_code, 'queued')
    )
    await callback.answer()
    
    # Инициализируем прогресс
    progress_data[user_id] = {
        "percent": 0,
        "speed": "0 B/s",
        "eta": "N/A",
        "status": "starting",
        "msg_id": queue_msg.message_id
    }
    
    # Запускаем задачу обновления прогресса
    progress_task = asyncio.create_task(
        update_progress_deluxe(callback.message, user_id, lang_code, queue_msg)
    )
    
    # Запускаем скачивание
    try:
        await do_download(
            callback.message,
            url,
            user_name,
            user_id,
            lang_code,
            requested_quality,
            platform
        )
    finally:
        await asyncio.sleep(0.2)
        progress_task.cancel()
        
        # Удаляем сообщение "В очереди" если оно ещё есть
        if user_id in progress_data:
            try:
                await callback.bot.delete_message(
                    callback.message.chat.id,
                    progress_data[user_id].get("msg_id")
                )
            except:
                pass
            del progress_data[user_id]

# ============================== ВЕБ-ПАНЕЛЬ ==============================
STYLE = """
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { background:#0f1115; color:#eee; font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif; padding:24px; min-height:100vh; }
.wrap { max-width:1200px; margin:0 auto; display:flex; gap:24px; }
.nav { width:240px; background:#1a1d24; border-radius:16px; padding:20px; height:fit-content; }
.nav a { display:flex; align-items:center; gap:10px; color:#aaa; text-decoration:none; padding:12px 16px; border-radius:8px; margin-bottom:4px; font-size:14px; transition:all 0.2s; }
.nav a:hover, .nav a.active { color:#fff; background:#2a2d36; }
.nav a.active { background:linear-gradient(90deg,#3D6BFF,#B43DFF); color:#fff; }
.main { flex:1; min-width:0; }
.header { display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #2a2d36; padding-bottom:16px; margin-bottom:24px; }
.logo { font-size:20px; font-weight:700; background:linear-gradient(90deg,#FF3D77,#B43DFF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.cards { display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }
.kpi { background:#1a1d24; border-radius:12px; padding:20px; flex:1; min-width:180px; box-shadow:0 4px 12px rgba(0,0,0,0.1); }
.kpi .val { font-size:28px; font-weight:700; color:#fff; line-height:1.2; }
.kpi .lbl { font-size:12px; color:#6c727f; margin-top:4px; font-weight:500; text-transform:uppercase; letter-spacing:0.5px; }
.panel { background:#1a1d24; border-radius:16px; padding:24px; margin-bottom:24px; box-shadow:0 4px 12px rgba(0,0,0,0.1); }
.panel h2 { font-size:16px; color:#fff; margin-bottom:20px; font-weight:600; }
canvas { width:100% !important; max-height:280px; }
table { width:100%; border-collapse:collapse; font-size:13px; text-align:left; }
th { color:#6c727f; font-weight:600; padding:12px 16px; border-bottom:1px solid #2a2d36; text-transform:uppercase; font-size:11px; letter-spacing:0.5px; }
td { padding:14px 16px; border-bottom:1px solid #1e2128; color:#ccc; max-width:200px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
tr:last-child td { border-bottom:none; }
.badge { display:inline-block; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600; }
.badge-success { background:rgba(61,220,132,0.1); color:#3ddc84; }
.badge-downgraded { background:rgba(255,184,77,0.1); color:#ffb84d; }
.badge-error { background:rgba(255,61,119,0.1); color:#ff3d77; }
.form-group { margin-bottom:16px; }
.form-group label { display:block; font-size:13px; color:#aaa; margin-bottom:6px; font-weight:500; }
input[type="text"], textarea, select { width:100%; padding:10px 14px; border-radius:8px; border:1px solid #2a2d36; background:#0f1115; color:#fff; font-size:14px; outline:none; transition:border 0.2s; }
input[type="text"]:focus, textarea:focus, select:focus { border-color:#3D6BFF; }
textarea { min-height:120px; resize:vertical; }
.btn { display:inline-flex; align-items:center; justify-content:center; padding:10px 20px; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; transition:opacity 0.2s; text-decoration:none; }
.btn-primary { background:linear-gradient(90deg,#3D6BFF,#B43DFF); color:#fff; }
.btn-secondary { background:#2a2d36; color:#fff; }
.btn-primary:hover { opacity:0.8; }
.btn-secondary:hover { background:#3a3d46; }
.panel .checkbox { display:flex; align-items:center; gap:8px; margin:12px 0; color:#aaa; font-size:13px; }
.modal { display:none; position:fixed; z-index:1000; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.7); justify-content:center; align-items:center; }
.modal-content { background:#1a1d24; border-radius:16px; max-width:500px; width:90%; padding:24px; position:relative; }
.modal-close { position:absolute; top:12px; right:16px; font-size:24px; cursor:pointer; color:#888; }
.modal-close:hover { color:#fff; }
.telegram-message { background:#0f1115; border-radius:12px; padding:16px; margin-top:12px; }
.telegram-message .sender { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.telegram-message .avatar { width:36px; height:36px; border-radius:50%; background:linear-gradient(90deg,#FF3D77,#B43DFF); display:flex; align-items:center; justify-content:center; color:#fff; font-weight:700; font-size:14px; }
.telegram-message .meta { font-size:13px; }
.telegram-message .meta .name { color:#fff; font-weight:600; }
.telegram-message .meta .status { color:#5288c1; font-size:11px; }
.telegram-message .msg-body { color:#f5f5f5; font-size:14px; line-height:1.4; word-break:break-word; white-space:pre-wrap; margin-top:6px; }
</style>
"""

def layout(content, active_tab):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Dashboard</title>{STYLE}<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head><body><div class="wrap"><div class="nav"><div class="logo" style="margin-bottom:24px; padding-left:16px;">📥 Media Downloader</div><a href="/" class="{"active" if active_tab=="index" else ""}">📈 Статистика</a><a href="/broadcast" class="{"active" if active_tab=="broadcast" else ""}">📢 Рассылка</a><a href="/users" class="{"active" if active_tab=="users" else ""}">👥 Пользователи</a><a href="/media" class="{"active" if active_tab=="media" else ""}">🎬 Медиатека</a><a href="/settings" class="{"active" if active_tab=="settings" else ""}">⚙️ Настройки</a></div><div class="main">{content}</div></div></body></html>"""

async def index(request):
    data = get_chart_data(14)
    rows = ""
    for r in data["recent"]:
        b = "badge-downgraded" if r["downgraded"] else "badge-success"
        lbl = "Снижено" if r["downgraded"] else "Успешно"
        rows += f"""<tr><td>{r['ts']}</td><td>{r['user']} (`{r['user_id']}`)</td><td><span class="badge {b}">{lbl} ({r['quality']})</span></td><td>{r['platform']}</td><td title="{r['url']}" style="max-width:150px;">{r['url'][:40]}…</td></tr>"""
    uptime = str(timedelta(seconds=int(time.time()-START_TIME)))
    c = f"""<div class="header"><div class="logo">📊 Статистика системы</div><div style="color:#6c727f; font-size:14px;">Аптайм: {uptime}</div></div><div class="cards"><div class="kpi"><div class="val">{data['total_users']}</div><div class="lbl">Всего пользователей</div></div><div class="kpi"><div class="val">{data['total_downloads']}</div><div class="lbl">Скачиваний</div></div><div class="kpi"><div class="val">{data['total_errors']}</div><div class="lbl">Ошибок</div></div><div class="kpi"><div class="val">{data['active_today']}</div><div class="lbl">Активны сегодня</div></div></div><div class="panel"><h2>📈 График загрузок (14 дней)</h2><canvas id="ch"></canvas></div><div class="panel"><h2>🕐 Последние загрузки</h2><table><thead><tr><th>Время</th><th>Пользователь</th><th>Качество</th><th>Платформа</th><th>Ссылка</th></tr></thead><tbody>{rows}</tbody></table></div><script>new Chart(document.getElementById('ch'),{{type:'line',data:{{labels:{json.dumps(data['labels'])},datasets:[{{label:'Загрузки',data:{json.dumps(data['downloads'])},borderColor:'#3D6BFF',tension:0.2,fill:true,backgroundColor:'rgba(61,107,255,0.05)'}},{{label:'Новые пользователи',data:{json.dumps(data['new_users'])},borderColor:'#B43DFF',tension:0.2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{labels:{{color:'#eee'}}}}}},scales:{{x:{{grid:{{color:'#2a2d36'}},ticks:{{color:'#aaa'}}}},y:{{grid:{{color:'#2a2d36'}},ticks:{{color:'#aaa'}}}}}}}}}});</script>"""
    return web.Response(text=layout(c, "index"), content_type='text/html')

async def broadcast_page(request):
    tasks = load_pending_tasks()
    t_rows = ""
    for t in tasks:
        t_rows += f"<tr><td>{t['id'][:6]}</td><td>{t.get('date','')} {t.get('time','')}</td><td title='{t['text']}'>{t['text'][:50]}…</td><td>{len(t.get('targets',[]))}</td><td><span class='badge badge-downgraded'>В очереди</span></td></tr>"
    c = f"""<div class="header"><div class="logo">📢 Глобальная рассылка</div></div><div class="panel"><h2>Новое уведомление</h2><form action="/broadcast/send" method="post"><div class="form-group"><label>Текст сообщения</label><textarea name="text" id="tx" placeholder="Введите текст рассылки..." required></textarea></div><div class="checkbox"><input type="checkbox" name="sched" id="sc" onchange="document.getElementById('sp').style.display=this.checked?'block':'none'"> <label for="sc">📅 Запланировать отправку</label></div><div id="sp" style="display:none; margin-bottom:16px;"><div style="display:flex; gap:16px;"><div class="form-group" style="flex:1;"><label>Дата</label><input type="date" name="date"></div><div class="form-group" style="flex:1;"><label>Время</label><input type="time" name="time"></div></div></div><button type="submit" class="btn btn-primary">🚀 Запустить рассылку</button></form></div><div class="panel"><h2>⏳ Отложенные рассылки</h2><table><thead><tr><th>ID</th><th>Время отправки</th><th>Текст</th><th>Получателей</th><th>Статус</th></tr></thead><tbody>{t_rows}</tbody></table></div>"""
    return web.Response(text=layout(c, "broadcast"), content_type='text/html')

async def send_broadcast(request):
    if not bot:
        return web.HTTPFound('/settings')
    data = await request.post()
    text = data.get("text", "").strip()
    sched = data.get("sched") == "on"
    if not text:
        return web.HTTPFound('/broadcast')
    stats = load_stats()
    uids = list(stats.get("users", {}).keys())
    if sched:
        tasks = load_pending_tasks()
        tasks.append({
            "id": uuid.uuid4().hex,
            "date": data.get("date", ""),
            "time": data.get("time", ""),
            "text": text,
            "targets": uids
        })
        save_pending_tasks(tasks)
    else:
        async def run():
            for uid in uids:
                try:
                    await bot.send_message(int(uid), text)
                    await asyncio.sleep(0.05)
                except:
                    pass
        asyncio.create_task(run())
    return web.HTTPFound('/broadcast')

async def users_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    rows = ""
    for uid, info in users.items():
        lang = info.get('lang', 'unknown')
        rows += f"<tr><td>`{uid}`</td><td>{info.get('name','User')}</td><td>{info.get('first_seen','-')}</td><td>{info.get('last_active','-')}</td><td>{lang}</td></tr>"
    c = f"""<div class="header"><div class="logo">👥 Управление аудиторией</div><a href="/users/export" class="btn btn-secondary">📥 Экспорт JSON</a></div><div class="panel"><h2>Зарегистрированные пользователи ({len(users)})</h2><table><thead><tr><th>Telegram ID</th><th>Имя</th><th>Первая активность</th><th>Последняя активность</th><th>Язык</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return web.Response(text=layout(c, "users"), content_type='text/html')

async def export_users(request):
    stats = load_stats()
    return web.Response(
        text=json.dumps(stats.get("users", {}), indent=2),
        content_type='application/json',
        headers={'Content-Disposition': 'attachment; filename="users.json"'}
    )

async def settings_get(request):
    s = load_settings()
    c = f"""<div class="header"><div class="logo">⚙️ Настройки системы</div></div><div class="panel"><h2>Конфигурация API и Администратора</h2><form method="post"><div class="form-group"><label>Telegram Bot Token</label><input type="text" name="token" value="{s.get('token','')}" placeholder="123456789:ABC..."></div><div class="form-group"><label>Admin Telegram ID</label><input type="text" name="admin_id" value="{s.get('admin_id','')}" placeholder="987654321"></div><div class="form-group"><label>API Ключ переводчика</label><input type="text" name="translator_api_key" value="{s.get('translator_api_key','')}" placeholder="Ключ для автоперевода"></div><button type="submit" class="btn btn-primary">💾 Сохранить</button></form></div>"""
    return web.Response(text=layout(c, "settings"), content_type='text/html')

async def settings_post(request):
    data = await request.post()
    settings = {
        "token": data.get("token", "").strip(),
        "admin_id": data.get("admin_id", "").strip(),
        "translator_api_key": data.get("translator_api_key", "").strip()
    }
    save_settings(settings)
    return web.Response(text="⚡ Конфигурация сохранена! Перезапустите приложение в Umbrel для применения.", content_type='text/plain')

# ============================== ФОНОВЫЕ ЗАДАЧИ ==============================
def load_pending_tasks():
    try:
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_pending_tasks(tasks):
    try:
        os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
        with open(PENDING_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Save pending tasks error: {e}")

async def scheduled_sender():
    """Фоновая задача для отложенных рассылок"""
    while True:
        try:
            tasks = load_pending_tasks()
            now = datetime.now()
            now_str = now.strftime("%Y-%m-%d %H:%M")
            changed = False
            for task in list(tasks):
                if task.get("date") and task.get("time"):
                    scheduled = f"{task['date']} {task['time']}"
                    if scheduled <= now_str:
                        if bot:
                            for uid in task.get("targets", []):
                                try:
                                    await bot.send_message(int(uid), task["text"])
                                    await asyncio.sleep(0.05)
                                except:
                                    pass
                        tasks.remove(task)
                        changed = True
            if changed:
                save_pending_tasks(tasks)
        except Exception as e:
            logging.error(f"Scheduled sender error: {e}")
        await asyncio.sleep(60)

# ============================== ЗАПУСК ==============================

# ============================== МЕДИАТЕКА ==============================
def load_favorites():
    try:
        with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"fav_users": [], "fav_files": {}}

def save_favorites(favs):
    os.makedirs(os.path.dirname(FAVORITES_FILE), exist_ok=True)
    with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
        json.dump(favs, f, ensure_ascii=False, indent=2)

async def media_page(request):
    favs = load_favorites()
    fav_users = favs.get("fav_users", [])
    fav_files = favs.get("fav_files", {})

    try:
        all_users = [d for d in os.listdir(MEDIA_BASE) if os.path.isdir(os.path.join(MEDIA_BASE, d))]
    except:
        all_users = []

    # Sort: favourites first (in order), then rest alphabetically
    rest = sorted([u for u in all_users if u not in fav_users])
    ordered_users = fav_users + rest

    cards = ""
    for username in ordered_users:
        user_dir = os.path.join(MEDIA_BASE, username)
        try:
            all_files = sorted([f for f in os.listdir(user_dir) if f.endswith(('.mp4', '.mp3'))])
        except:
            all_files = []

        user_fav = fav_users.count(username) > 0
        star_user = "⭐" if user_fav else "☆"
        star_user_cls = "btn-star active" if user_fav else "btn-star"

        user_fav_files = fav_files.get(username, [])
        ordered_files = user_fav_files + [f for f in all_files if f not in user_fav_files]

        files_html = ""
        for fname in ordered_files:
            is_fav = fname in user_fav_files
            star = "⭐" if is_fav else "☆"
            star_cls = "btn-star active" if is_fav else "btn-star"
            fpath = f"/media/file?user={username}&file={fname}"
            if fname.endswith('.mp4'):
                player = f'''<video controls style="width:100%;border-radius:8px;margin-top:8px;background:#000;">
                    <source src="{fpath}" type="video/mp4">
                </video>'''
            else:
                player = f'''<audio controls style="width:100%;margin-top:8px;">
                    <source src="{fpath}" type="audio/mpeg">
                </audio>'''
            files_html += f'''<div class="media-item">
                <div class="media-header">
                    <span class="media-name" title="{fname}">{fname}</span>
                    <button class="{star_cls}" onclick="toggleFileFav('{username}','{fname}',this)">{star}</button>
                </div>
                {player}
            </div>'''

        if not files_html:
            files_html = '<div style="color:#6c727f;font-size:13px;padding:8px 0;">Нет файлов</div>'

        cards += f'''<div class="panel">
            <div class="media-user-header">
                <div class="logo" style="font-size:16px;">👤 {username}</div>
                <button class="{star_user_cls}" onclick="toggleUserFav('{username}',this)">{star_user} В избранное</button>
            </div>
            <div class="media-files">{files_html}</div>
        </div>'''

    if not cards:
        cards = '<div class="panel"><div style="color:#6c727f;text-align:center;padding:32px;">Папка пуста или не найдена</div></div>'

    extra_style = """<style>
    .media-user-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}
    .media-item{border-bottom:1px solid #2a2d36;padding:12px 0;}
    .media-item:last-child{border-bottom:none;}
    .media-header{display:flex;align-items:center;justify-content:space-between;gap:8px;}
    .media-name{color:#ccc;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%;}
    .btn-star{background:#2a2d36;border:none;border-radius:8px;color:#aaa;cursor:pointer;padding:6px 14px;font-size:13px;font-weight:600;transition:all 0.2s;}
    .btn-star.active{background:rgba(255,184,77,0.15);color:#ffb84d;}
    .btn-star:hover{opacity:0.8;}
    </style>"""

    c = f'''<div class="header"><div class="logo">🎬 Медиатека</div></div>
    {extra_style}
    {cards}
    <script>
    async function toggleUserFav(username, btn) {{
        const r = await fetch('/media/favorite', {{method:'POST', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{type:\'user\',username}}) }});
        const d = await r.json();
        btn.className = d.active ? \'btn-star active\' : \'btn-star\';
        btn.textContent = (d.active ? \'⭐\' : \'☆\') + \' В избранное\';
        setTimeout(()=>location.reload(), 300);
    }}
    async function toggleFileFav(username, filename, btn) {{
        const r = await fetch('/media/favorite\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{type:\'file\',username,filename}}) }});
        const d = await r.json();
        btn.className = d.active ? \'btn-star active\' : \'btn-star\';
        btn.textContent = d.active ? \'⭐\' : \'☆\';
        setTimeout(()=>location.reload(), 300);
    }}
    </script>'''
    return web.Response(text=layout(c, "media"), content_type='text/html')

async def media_file(request):
    username = request.rel_url.query.get("user", "")
    filename = request.rel_url.query.get("file", "")
    if not username or not filename or ".." in username or ".." in filename:
        return web.Response(status=400)
    filepath = os.path.join(MEDIA_BASE, username, filename)
    if not os.path.exists(filepath):
        return web.Response(status=404)
    ctype = "video/mp4" if filename.endswith(".mp4") else "audio/mpeg"
    return web.FileResponse(filepath, headers={"Content-Type": ctype})

async def media_favorite(request):
    data = await request.json()
    favs = load_favorites()
    ftype = data.get("type")
    if ftype == "user":
        username = data.get("username", "")
        if username in favs["fav_users"]:
            favs["fav_users"].remove(username)
            active = False
        else:
            favs["fav_users"].insert(0, username)
            active = True
    elif ftype == "file":
        username = data.get("username", "")
        filename = data.get("filename", "")
        favs.setdefault("fav_files", {})
        favs["fav_files"].setdefault(username, [])
        if filename in favs["fav_files"][username]:
            favs["fav_files"][username].remove(filename)
            active = False
        else:
            favs["fav_files"][username].insert(0, filename)
            active = True
    else:
        return web.Response(status=400)
    save_favorites(favs)
    return web.Response(text=json.dumps({"active": active}), content_type="application/json")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/broadcast', broadcast_page)
    app.router.add_post('/broadcast/send', send_broadcast)
    app.router.add_get('/users', users_page)
    app.router.add_get('/users/export', export_users)
    app.router.add_get('/media', media_page)
    app.router.add_get('/media/file', media_file)
    app.router.add_post('/media/favorite', media_favorite)
    app.router.add_get('/settings', settings_get)
    app.router.add_post('/settings', settings_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8090)
    await site.start()

async def bot_task():
    if not (bot and ADMIN_ID):
        logging.warning("Бот не настроен. Откройте веб-страницу → Настройки.")
        await asyncio.Event().wait()
        return
    try:
        await bot.send_message(ADMIN_ID, "🚀 Бот запущен!")
    except Exception as e:
        logging.error(f"Startup message error: {e}")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Polling error: {e}")

async def main():
    asyncio.create_task(scheduled_sender())
    await asyncio.gather(bot_task(), start_web_server())

if __name__ == '__main__':
    asyncio.run(main())
