import asyncio, os, logging, yt_dlp, re, json, time, uuid
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# ======================== ПУТИ UMBREL OS ========================
SAVE_PATH = '/umbrel/umbrel/home/TikTok/'
SETTINGS_FILE = '/data/config/settings.json'
STATS_FILE = '/data/config/stats.json'
MESSAGES_FILE = '/data/config/user_messages.json'
POLLS_FILE = '/data/config/polls.json'
FAVORITES_FILE = '/data/config/favorites.json'
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
FALLBACK_CHAIN = {"best": ["best", "medium", "low"], "medium": ["medium", "low"], "low": ["low"], "audio": ["audio"]}

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
        return {"users": {}, "recent": [], "downloads_by_day": {}, "errors_by_day": {}, "platform_stats": {}, "lang_stats": {}}

def save_stats(stats):
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Stats error: {e}")

def ensure_user(stats: dict, uid: str, user_name: str, lang_code: str = None):
    today = date.today().isoformat()
    stats.setdefault("users", {})
    if uid not in stats["users"]:
        stats["users"][uid] = {
            "name": user_name,
            "downloads": 0,
            "errors": 0,
            "first_seen": today,
            "last_active": today,
            "lang": lang_code or "unknown",
            "urls": []
        }
    else:
        stats["users"][uid]["name"] = user_name
        stats["users"][uid]["last_active"] = today
        stats["users"][uid].setdefault("first_seen", today)
        stats["users"][uid].setdefault("urls", [])
        if lang_code:
            stats["users"][uid]["lang"] = lang_code
    return stats["users"][uid]

def record_user_seen(user_id: int, user_name: str, lang_code: str = None):
    """Регистрирует пользователя и его язык (напр. при /start), не увеличивая счётчик загрузок."""
    stats = load_stats()
    uid = str(user_id)
    ensure_user(stats, uid, user_name, lang_code)
    if lang_code:
        stats.setdefault("lang_stats", {})
        stats["lang_stats"][lang_code] = stats["lang_stats"].get(lang_code, 0) + 1
    save_stats(stats)

def record_download(user_id: int, user_name: str, url: str, platform: str = "unknown", lang_code: str = None):
    stats = load_stats()
    uid = str(user_id)
    today = date.today().isoformat()

    u = ensure_user(stats, uid, user_name, lang_code)
    u["downloads"] = u.get("downloads", 0) + 1
    u["urls"].insert(0, url)
    u["urls"] = u["urls"][:50]

    stats.setdefault("downloads_by_day", {})
    stats["downloads_by_day"][today] = stats["downloads_by_day"].get(today, 0) + 1

    stats.setdefault("platform_stats", {})
    stats["platform_stats"][platform] = stats["platform_stats"].get(platform, 0) + 1

    stats.setdefault("recent", [])
    stats["recent"].insert(0, {"ts": datetime.now().strftime("%d.%m %H:%M"), "user": user_name, "user_id": user_id, "url": url, "platform": platform})
    stats["recent"] = stats["recent"][:20]

    save_stats(stats)

def record_error(user_id: int, user_name: str, lang_code: str = None):
    stats = load_stats()
    uid = str(user_id)
    today = date.today().isoformat()

    u = ensure_user(stats, uid, user_name, lang_code)
    u["errors"] = u.get("errors", 0) + 1

    stats.setdefault("errors_by_day", {})
    stats["errors_by_day"][today] = stats["errors_by_day"].get(today, 0) + 1

    save_stats(stats)

def get_top_languages(limit=10):
    stats = load_stats()
    return sorted(stats.get("lang_stats", {}).items(), key=lambda x: x[1], reverse=True)[:limit]

def get_chart_data(days=14):
    stats = load_stats()
    today = date.today()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    dl_by_day = stats.get("downloads_by_day", {})
    err_by_day = stats.get("errors_by_day", {})
    users = stats.get("users", {})

    downloads_data = [dl_by_day.get(d, 0) for d in labels]
    errors_data = [err_by_day.get(d, 0) for d in labels]
    new_users_data = [sum(1 for u in users.values() if u.get("first_seen") == d) for d in labels]
    short_labels = [d[5:].replace("-", ".") for d in labels]

    platform_stats = stats.get("platform_stats", {})
    top_platforms = sorted(platform_stats.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "labels": short_labels,
        "downloads": downloads_data,
        "errors": errors_data,
        "new_users": new_users_data,
        "top_platforms": top_platforms,
        "top_languages": get_top_languages(10),
    }

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

def mark_message_read(msg_id: str):
    messages = load_user_messages()
    for m in messages:
        if m["id"] == msg_id:
            m["read"] = True
    save_user_messages(messages)

def set_message_reply(msg_id: str, reply_text: str):
    messages = load_user_messages()
    for m in messages:
        if m["id"] == msg_id:
            m["read"] = True
            m["reply"] = reply_text
            m["replied_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
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
    """Юзер может проголосовать, и один раз поменять свой ответ. Возвращает (успех, сообщение)."""
    polls = load_polls()
    for poll in polls:
        if poll["id"] == poll_id:
            if option not in poll["options"]:
                return False, "❌ Такого варианта нет"

            show_until = poll.get("show_until")
            if show_until and datetime.now().isoformat() > show_until:
                return False, "⏳ Голосование уже завершено"

            user_votes = poll.setdefault("user_votes", {})
            changed_users = poll.setdefault("changed_users", [])
            uid = str(user_id)

            old_option = user_votes.get(uid)

            if old_option == option:
                return False, "ℹ️ Ты уже выбрал этот вариант"

            if old_option is not None:
                # Юзер уже голосовал — это попытка сменить голос
                if uid in changed_users:
                    return False, "🚫 Ты уже менял свой голос один раз, повторная смена недоступна"
                if old_option in poll["options"] and user_id in poll["options"][old_option]:
                    poll["options"][old_option].remove(user_id)
                changed_users.append(uid)

            if user_id not in poll["options"][option]:
                poll["options"][option].append(user_id)
            user_votes[uid] = option

            poll["user_votes"] = user_votes
            poll["changed_users"] = changed_users
            save_polls(polls)
            return True, "✅ Голос учтён!"
    return False, "❌ Голосование не найдено"

# ======================== ИЗБРАННОЕ ========================
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

# ======================== ПРОГРЕСС ========================
def format_speed(speed_bytes):
    if speed_bytes is None:
        return "N/A"
    units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
    for unit in units:
        if speed_bytes < 1024:
            return f"{speed_bytes:.1f} {unit}"
        speed_bytes /= 1024
    return f"{speed_bytes:.1f} TB/s"

def format_eta(seconds):
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
    """Хук прогресса, привязанный к user_id через замыкание"""
    def hook(d):
        try:
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                downloaded = d.get('downloaded_bytes', 0)
                percent = int((downloaded / total) * 100) if total else 0
                if uid in progress_data:
                    progress_data[uid]["percent"] = percent
                    progress_data[uid]["speed"] = format_speed(d.get('speed', 0))
                    progress_data[uid]["eta"] = format_eta(d.get('eta', 0))
                    progress_data[uid]["status"] = "downloading"
            elif d['status'] == 'finished':
                if uid in progress_data:
                    progress_data[uid]["percent"] = 100
                    progress_data[uid]["status"] = "completed"
        except Exception as e:
            logging.error(f"Progress hook error: {e}")
    return hook

async def update_progress_deluxe(status_msg, user_id, queue_msg=None):
    """Анимированный прогресс с часами и спиннером"""
    clock_frames = ["🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚","🕛"]
    spinner_frames = ["⣾","⣽","⣻","⢿","⡿","⣟","⣯","⣷"]
    idx = 0
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

            if percent >= 100 or status == 'completed':
                if queue_msg:
                    try:
                        await queue_msg.delete()
                    except:
                        pass
                if progress_msg:
                    try:
                        await progress_msg.delete()
                    except:
                        pass
                progress_data.pop(user_id, None)
                break

            clock = clock_frames[idx % len(clock_frames)]
            spinner = spinner_frames[idx % len(spinner_frames)]
            idx += 1
            bar_len = 20
            filled = int(bar_len * percent / 100)
            bar = '█' * filled + '░' * (bar_len - filled)
            text = f"{clock} {percent}% {spinner}\n\n`{bar}`\n⚡ {speed}\n⏱️ {eta}"

            if progress_msg is None:
                progress_msg = await status_msg.answer(text, parse_mode="Markdown")
            else:
                try:
                    await progress_msg.edit_text(text, parse_mode="Markdown")
                except:
                    pass
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

# ======================== СКАЧИВАНИЕ ========================
async def do_download(status_msg, url, user_name, user_id, lang, requested_quality, platform="unknown"):
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
            if platform in ("twitter", "facebook"):
                format_str = "best[ext=mp4]/best"
            try:
                ts = int(time.time())
                opts = {
                    "format": format_str,
                    "outtmpl": os.path.join(user_folder, f"%(title).30s_{ts}.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "progress_hooks": [make_progress_hook(user_id)],
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

                    img_ext = ('.jpg', '.jpeg', '.png', '.webp')
                    images = [p for p in paths if p.lower().endswith(img_ext)]
                    videos = [p for p in paths if p.lower().endswith(('.mp4', '.mkv', '.webm'))]
                    audios = [p for p in paths if p.lower().endswith(('.mp3', '.m4a', '.ogg'))]

                achieved_quality = attempt_quality
                result_media = (images, videos, audios)
                break
            except Exception as e:
                logging.warning(f"Quality '{attempt_quality}' failed: {e}")
                continue

        if achieved_quality is None:
            record_error(user_id, user_name, lang)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] [ОШИБКА] [качество: {requested_quality}] [платформа: {platform}] {url}\n")
            try:
                await status_msg.answer(get_text(lang, "error"))
            except:
                pass
            return

        images, videos, audios = result_media
        caption = get_text(lang, "done", name=user_name)

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
            else:
                await status_msg.answer(caption)
        except Exception as e:
            logging.error(f"Send error: {e}")
            record_error(user_id, user_name, lang)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] [ОШИБКА ОТПРАВКИ] [качество: {achieved_quality}] [платформа: {platform}] {url}\n")
            try:
                await status_msg.answer(get_text(lang, "error"))
            except:
                pass
            return

        record_download(user_id, user_name, url, platform, lang)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] [качество: {achieved_quality}] [платформа: {platform}] {url}\n")

        if achieved_quality != requested_quality:
            quality_labels = {
                "best": get_text(lang, 'btn_best'),
                "medium": get_text(lang, 'btn_medium'),
                "low": get_text(lang, 'quality_low'),
                "audio": get_text(lang, 'btn_audio'),
            }
            try:
                await status_msg.answer(get_text(lang, "downgraded", quality=quality_labels.get(achieved_quality, achieved_quality)))
            except:
                pass

        if bot and ADMIN_ID:
            try:
                platform_label = get_text(lang, f"platform_{platform}") or platform
                await bot.send_message(
                    ADMIN_ID,
                    f"📥 Скачано медиа:\n👤 {user_name} (`{user_id}`)\n🌐 {platform_label}\n🎚 {achieved_quality}\n🌍 {lang}\n🔗 {url}",
                    parse_mode="Markdown"
                )
            except:
                pass

# ======================== TELEGRAM HANDLERS ========================
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    lang = message.from_user.language_code or "en"
    record_user_seen(message.from_user.id, message.from_user.first_name or "Unknown", lang)
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

@dp.message(lambda msg: (msg.text and "http" in msg.text) or (msg.caption and "http" in msg.caption))
async def ask_quality(message: types.Message):
    lang = message.from_user.language_code or "en"
    full_text = message.text or message.caption or ""
    match = re.search(URL_REGEX, full_text)
    if not match:
        return

    url = match.group(0).strip()
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Unknown"
    platform = detect_platform(url)
    platform_label = get_text(lang, f"platform_{platform}") or platform
    key = uuid.uuid4().hex[:12]

    now = time.time()
    for k in list(pending.keys()):
        if now - pending[k]["ts"] > 600:
            del pending[k]

    pending[key] = {"url": url, "platform": platform, "user_name": user_name, "user_id": user_id, "lang": lang, "ts": now}

    platform_msg = await message.answer(get_text(lang, "detected_platform", platform=platform_label))
    pending[key]["platform_msg_id"] = platform_msg.message_id

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text(lang, "btn_best"), callback_data=f"q:best:{key}"),
         InlineKeyboardButton(text=get_text(lang, "btn_medium"), callback_data=f"q:medium:{key}")],
        [InlineKeyboardButton(text=get_text(lang, "btn_audio"), callback_data=f"q:audio:{key}")]
    ])
    quality_msg = await message.answer(get_text(lang, "choose_quality"), reply_markup=kb)
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
        await callback.answer("❌ Ссылка устарела, отправь снова", show_alert=True)
        return

    for msg_id_key in ("platform_msg_id", "quality_msg_id"):
        try:
            await callback.bot.delete_message(callback.message.chat.id, info[msg_id_key])
        except:
            pass

    await callback.answer()
    queue_msg = await callback.message.answer(get_text(info["lang"], "queued"))

    user_id = info["user_id"]
    progress_data[user_id] = {"percent": 0, "speed": "0 B/s", "eta": "N/A", "status": "starting"}
    progress_task = asyncio.create_task(update_progress_deluxe(callback.message, user_id, queue_msg))

    try:
        await do_download(callback.message, info["url"], info["user_name"], user_id, info["lang"], requested_quality, info["platform"])
    finally:
        await asyncio.sleep(0.2)
        progress_task.cancel()
        progress_data.pop(user_id, None)

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
canvas { width:100% !important; max-height:280px; }
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
.btn-star { background:#2a2d36; border:none; border-radius:8px; color:#aaa; cursor:pointer; padding:4px 10px; font-size:13px; font-weight:600; transition:all 0.2s; }
.btn-star.active { background:rgba(255,184,77,0.15); color:#ffb84d; }
.btn-star:hover { opacity:0.8; }
.name-cell { display:flex; align-items:center; gap:8px; }
.media-item { border-bottom:1px solid #2a2d36; padding:10px 0; }
.media-item:last-child { border-bottom:none; }
.media-item-header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.media-item-header .fname { color:#ccc; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%; }
.media-item video, .media-item audio { width:100%; margin-top:6px; border-radius:8px; background:#000; }
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:100; align-items:center; justify-content:center; }
.modal-overlay.show { display:flex; }
.modal-box { background:#1a1d24; border-radius:16px; padding:24px; max-width:600px; width:90%; max-height:80vh; overflow-y:auto; }
.modal-box h3 { color:#fff; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; }
.modal-close { background:none; border:none; color:#aaa; font-size:20px; cursor:pointer; }
.modal-close:hover { color:#fff; }
.status-badge { display:inline-block; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600; }
.status-unread { background:rgba(255,61,119,0.15); color:#ff3d77; }
.status-read { background:rgba(80,200,120,0.12); color:#4caf50; }
.reply-box { display:flex; gap:8px; margin-top:8px; }
.reply-box input { flex:1; }
.reply-box button { white-space:nowrap; }
.reply-shown { font-size:12px; color:#6c727f; margin-top:6px; padding-top:6px; border-top:1px dashed #2a2d36; }
</style>"""

def layout(content, active_tab):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Dashboard</title>{STYLE}<script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head><body><div class="wrap"><div class="nav"><div class="logo" style="margin-bottom:24px; padding-left:16px;">📥 TT Dloader</div><a href="/" class="{"active" if active_tab=="index" else ""}">📊 Stats</a><a href="/media" class="{"active" if active_tab=="media" else ""}">🎬 Media</a><a href="/broadcast" class="{"active" if active_tab=="broadcast" else ""}">📢 Broadcast</a><a href="/users" class="{"active" if active_tab=="users" else ""}">👥 Users</a><a href="/settings" class="{"active" if active_tab=="settings" else ""}">⚙️ Settings</a></div><div class="main">{content}</div></div></body></html>"""

async def index(request):
    stats = load_stats()
    users = stats.get("users", {})

    user_list = []
    for uid, info in users.items():
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
    urls_by_uid = {}
    for u in user_list:
        urls_by_uid[u["uid"]] = u["urls"]
        name_esc = u['name'].replace("'", "\\'")
        rows += f"""<tr data-name="{u['name'].lower()}">
            <td><div class="name-cell"><button class="expand-btn" onclick="openModal('{u['uid']}','{name_esc}')">▼</button> {u['name']}</div></td>
            <td>{u['downloads']}</td>
            <td>{u['last_active']}</td>
            <td><span class="badge badge-error">{u['errors']}</span></td>
        </tr>"""

    uptime = str(timedelta(seconds=int(time.time()-START_TIME)))
    total_dl = sum(u["downloads"] for u in user_list)
    total_err = sum(u["errors"] for u in user_list)

    chart_data = get_chart_data(14)

    c = f"""<div class="header"><div class="logo">📊 Статистика</div><div style="color:#6c727f; font-size:14px;">Аптайм: {uptime}</div></div>
    <div class="cards">
        <div class="kpi"><div class="val">{len(user_list)}</div><div class="lbl">Пользователей</div></div>
        <div class="kpi"><div class="val">{total_dl}</div><div class="lbl">Загрузок</div></div>
        <div class="kpi"><div class="val">{total_err}</div><div class="lbl">Ошибок</div></div>
    </div>
    <div class="panel">
        <h2>📈 График за 14 дней</h2>
        <canvas id="statsChart"></canvas>
    </div>
    <div class="panel">
        <h2>🔍 Поиск пользователя</h2>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Введите имя..." oninput="filterRows()">
        </div>
    </div>
    <div class="panel">
        <h2>👥 Пользователи</h2>
        <table id="usersTable">
            <thead><tr><th onclick="sortCol(this, 0)">👤 Имя</th><th onclick="sortCol(this, 1)">📥 Видео</th><th onclick="sortCol(this, 2)">🕐 Последнее</th><th onclick="sortCol(this, 3)">❌ Ошибок</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет данных</td></tr>'}</tbody>
        </table>
    </div>

    <div class="modal-overlay" id="linksModal">
        <div class="modal-box">
            <h3><span id="modalTitle">Ссылки</span><button class="modal-close" onclick="closeModal()">✕</button></h3>
            <div id="modalBody"></div>
        </div>
    </div>

    <script>
    const urlsByUid = {json.dumps(urls_by_uid, ensure_ascii=False)};

    new Chart(document.getElementById('statsChart'), {{
        type: 'line',
        data: {{
            labels: {json.dumps(chart_data['labels'])},
            datasets: [
                {{ label: 'Загрузки', data: {json.dumps(chart_data['downloads'])}, borderColor: '#3D6BFF', backgroundColor: 'rgba(61,107,255,0.08)', tension: 0.25, fill: true }},
                {{ label: 'Новые пользователи', data: {json.dumps(chart_data['new_users'])}, borderColor: '#B43DFF', tension: 0.25 }},
                {{ label: 'Ошибки', data: {json.dumps(chart_data['errors'])}, borderColor: '#ff3d77', tension: 0.25 }}
            ]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }},
            scales: {{
                x: {{ grid: {{ color: '#2a2d36' }}, ticks: {{ color: '#aaa' }} }},
                y: {{ grid: {{ color: '#2a2d36' }}, ticks: {{ color: '#aaa' }}, beginAtZero: true }}
            }}
        }}
    }});

    function openModal(uid, name) {{
        document.getElementById('modalTitle').textContent = 'Ссылки: ' + name;
        const urls = urlsByUid[uid] || [];
        const body = document.getElementById('modalBody');
        if (urls.length === 0) {{
            body.innerHTML = '<div style="color:#666;">Нет ссылок</div>';
        }} else {{
            body.innerHTML = urls.map(u => `<div class="video-item"><a href="${{u}}" target="_blank">${{u}}</a></div>`).join('');
        }}
        document.getElementById('linksModal').classList.add('show');
    }}
    function closeModal() {{
        document.getElementById('linksModal').classList.remove('show');
    }}
    document.getElementById('linksModal').addEventListener('click', (e) => {{
        if (e.target.id === 'linksModal') closeModal();
    }});

    function filterRows() {{
        const q = document.getElementById('searchInput').value.toLowerCase();
        document.querySelectorAll('#usersTable tbody tr').forEach(r => {{
            const name = r.dataset.name || '';
            r.style.display = name.includes(q) ? '' : 'none';
        }});
    }}

    function sortCol(el, col) {{
        const tbody = el.closest('table').querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const asc = el.dataset.asc !== 'true';
        el.dataset.asc = asc;
        rows.sort((a, b) => {{
            const aVal = a.cells[col]?.textContent.trim() || '';
            const bVal = b.cells[col]?.textContent.trim() || '';
            const aNum = parseFloat(aVal), bNum = parseFloat(bVal);
            let cmp = (!isNaN(aNum) && !isNaN(bNum)) ? aNum - bNum : aVal.localeCompare(bVal);
            return asc ? cmp : -cmp;
        }});
        rows.forEach(r => tbody.appendChild(r));
    }}
    </script>"""

    return web.Response(text=layout(c, "index"), content_type='text/html')

async def media_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    favs = load_favorites()
    fav_users = favs.get("fav_users", [])
    fav_files = favs.get("fav_files", {})

    media_data = []
    for uid, info in users.items():
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

    # Избранные пользователи — наверх, остальные по числу видео
    media_data.sort(key=lambda m: (m["uid"] not in fav_users, -m["videos"]))

    rows = ""
    for m in media_data:
        user_fav = m["uid"] in fav_users
        star_cls = "btn-star active" if user_fav else "btn-star"
        star_char = "⭐" if user_fav else "☆"

        user_fav_files = fav_files.get(m["uid"], [])
        ordered_files = [f for f in user_fav_files if f in m["files"]] + [f for f in m["files"] if f not in user_fav_files]

        files_html = ""
        for fname in ordered_files:
            is_fav = fname in user_fav_files
            f_star_cls = "btn-star active" if is_fav else "btn-star"
            f_star_char = "⭐" if is_fav else "☆"
            fpath = f"/media/file?f={fname}&uid={m['uid']}"
            if fname.endswith('.mp4'):
                player = f'<video controls preload="none"><source src="{fpath}" type="video/mp4"></video>'
            else:
                player = f'<audio controls preload="none"><source src="{fpath}" type="audio/mpeg"></audio>'
            files_html += f"""<div class="media-item">
                <div class="media-item-header">
                    <span class="fname" title="{fname}">🎬 {fname}</span>
                    <button class="{f_star_cls}" onclick="toggleFav(event,'file','{m['uid']}','{fname}')">{f_star_char}</button>
                </div>
                {player}
            </div>"""
        if not files_html:
            files_html = '<div style="color:#666; padding:12px;">Нет файлов</div>'

        rows += f"""<tr class="expandable-row" data-name="{m['name'].lower()}" data-uid="{m['uid']}" onclick="toggleRow(event,'med-{m['uid']}')">
            <td><div class="name-cell"><button class="expand-btn">▼</button> {m['name']} <button class="{star_cls}" onclick="toggleFav(event,'user','{m['uid']}','')">{star_char}</button></div></td>
            <td>{m['videos']}</td>
            <td>{m['last_active']}</td>
            <td><span class="badge badge-error">{m['errors']}</span></td>
        </tr>
        <tr class="sub-row" id="med-{m['uid']}">
            <td colspan="4">{files_html}</td>
        </tr>"""

    c = f"""<div class="header"><div class="logo">🎬 Медиатека</div></div>
    <div class="panel">
        <h2>🔍 Поиск пользователя</h2>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Введите имя..." oninput="filterRows()">
        </div>
    </div>
    <div class="panel">
        <h2>👥 Пользователи</h2>
        <table id="mediaTable">
            <thead><tr><th onclick="sortCol(this, 0)">👤 Имя</th><th onclick="sortCol(this, 1)">📹 Видео</th><th onclick="sortCol(this, 2)">🕐 Последнее</th><th onclick="sortCol(this, 3)">❌ Ошибок</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет данных</td></tr>'}</tbody>
        </table>
    </div>
    <script>
    function toggleRow(e, id) {{
        if (e.target.closest('.btn-star')) return;
        document.getElementById(id).classList.toggle('show');
    }}
    async function toggleFav(e, type, uid, filename) {{
        e.stopPropagation();
        const r = await fetch('/media/favorite', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{type, uid, filename}}) }});
        const d = await r.json();
        const btn = e.target;
        btn.className = d.active ? 'btn-star active' : 'btn-star';
        btn.textContent = d.active ? '⭐' : '☆';
        setTimeout(() => location.reload(), 250);
    }}
    function filterRows() {{
        const q = document.getElementById('searchInput').value.toLowerCase();
        document.querySelectorAll('#mediaTable tbody tr').forEach(r => {{
            if (r.classList.contains('sub-row')) return;
            const name = r.dataset.name || '';
            const show = name.includes(q);
            r.style.display = show ? '' : 'none';
        }});
    }}
    function sortCol(el, col) {{
        const tbody = el.closest('table').querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => !r.classList.contains('sub-row'));
        const asc = el.dataset.asc !== 'true';
        el.dataset.asc = asc;
        rows.sort((a, b) => {{
            const aVal = a.cells[col]?.textContent.trim() || '';
            const bVal = b.cells[col]?.textContent.trim() || '';
            const aNum = parseFloat(aVal), bNum = parseFloat(bVal);
            let cmp = (!isNaN(aNum) && !isNaN(bNum)) ? aNum - bNum : aVal.localeCompare(bVal);
            return asc ? cmp : -cmp;
        }});
        rows.forEach(r => {{
            tbody.appendChild(r);
            const sub = document.getElementById('med-' + r.dataset.uid);
            if (sub) tbody.appendChild(sub);
        }});
    }}
    </script>"""

    return web.Response(text=layout(c, "media"), content_type='text/html')

async def media_favorite(request):
    data = await request.json()
    favs = load_favorites()
    favs.setdefault("fav_users", [])
    favs.setdefault("fav_files", {})
    ftype = data.get("type")
    uid = data.get("uid", "")

    if ftype == "user":
        if uid in favs["fav_users"]:
            favs["fav_users"].remove(uid)
            active = False
        else:
            favs["fav_users"].insert(0, uid)
            active = True
    elif ftype == "file":
        filename = data.get("filename", "")
        favs["fav_files"].setdefault(uid, [])
        if filename in favs["fav_files"][uid]:
            favs["fav_files"][uid].remove(filename)
            active = False
        else:
            favs["fav_files"][uid].insert(0, filename)
            active = True
    else:
        return web.Response(status=400)

    save_favorites(favs)
    return web.Response(text=json.dumps({"active": active}), content_type="application/json")

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
    for m in messages[:50]:
        status_cls = "status-read" if m.get("read") else "status-unread"
        status_txt = "✅ Прочитано" if m.get("read") else "🔴 Новое"
        reply_html = ""
        if m.get("reply"):
            reply_html = f'<div class="reply-shown">↩️ Ответ ({m.get("replied_at","")}): {m["reply"]}</div>'
        msg_rows += f"""<tr>
            <td style="white-space:nowrap;">{m['timestamp']}</td>
            <td>{m['user_name']}</td>
            <td>{m['text'][:200]}{reply_html}</td>
            <td><span class="status-badge {status_cls}">{status_txt}</span></td>
            <td>
                <div class="reply-box">
                    <input type="text" id="reply-{m['id']}" placeholder="Написать ответ...">
                    <button class="btn btn-primary" onclick="sendReply('{m['id']}')">Ответить</button>
                </div>
            </td>
        </tr>"""

    poll_rows = ""
    for p in polls:
        total = sum(len(v) for v in p["options"].values())
        active = p.get("active", True) and (not p.get("show_until") or datetime.now().isoformat() <= p["show_until"])
        status_txt = "🟢 Активно" if active else "⚪ Завершено"
        opts_html = ""
        for opt, voters in p["options"].items():
            pct = int(len(voters) / total * 100) if total > 0 else 0
            opts_html += f'<div class="poll-result"><div class="poll-option"><span>{opt}</span><span>{len(voters)} голосов ({pct}%)</span></div><div class="poll-bar"><div class="poll-fill" style="width:{pct}%"></div></div></div>'
        poll_rows += f'<tr><td>{p["question"]}</td><td>{total}</td><td>{status_txt}</td><td>{opts_html}</td></tr>'

    c = f"""<div class="header"><div class="logo">📢 Рассылка</div></div>
    <div class="panel"><h2>📩 Новое уведомление</h2>
    <form action="/api/broadcast" method="post">
        <div class="form-group"><label>Текст</label><textarea name="text" required></textarea></div>
        <button type="submit" class="btn btn-primary">Отправить всем</button>
    </form></div>
    <div class="panel"><h2>💬 Сообщения от пользователей</h2>
    <table><thead><tr><th>Дата</th><th>Пользователь</th><th>Сообщение</th><th>Статус</th><th>Ответ</th></tr></thead><tbody>{msg_rows if msg_rows else '<tr><td colspan="5" style="text-align:center;color:#666;">Нет сообщений</td></tr>'}</tbody></table></div>
    <div class="panel"><h2>📊 Создать голосование</h2>
    <form action="/api/poll-create" method="post">
        <div class="form-group"><label>Вопрос</label><input type="text" name="question" required></div>
        <div class="form-group"><label>Варианты (по одному в строке)</label><textarea name="options" rows="4" required></textarea></div>
        <div class="form-group"><label>Показывать результаты</label><select name="days"><option value="1">1 день</option><option value="7">7 дней</option><option value="14">14 дней</option><option value="30">30 дней</option></select></div>
        <button type="submit" class="btn btn-primary">Создать голосование</button>
    </form></div>
    <div class="panel"><h2>📈 Голосования</h2>
    <table><thead><tr><th>Вопрос</th><th>Всего голосов</th><th>Статус</th><th>Результаты</th></tr></thead><tbody>{poll_rows if poll_rows else '<tr><td colspan="4" style="text-align:center;color:#666;">Нет голосований</td></tr>'}</tbody></table></div>
    <script>
    async function sendReply(msgId) {{
        const input = document.getElementById('reply-' + msgId);
        const text = input.value.trim();
        if (!text) return;
        input.disabled = true;
        await fetch('/api/message-reply', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{id: msgId, text: text}})
        }});
        location.reload();
    }}
    </script>"""

    return web.Response(text=layout(c, "broadcast"), content_type='text/html')

async def api_message_reply(request):
    data = await request.json()
    msg_id = data.get("id", "")
    text = data.get("text", "").strip()
    if not msg_id or not text:
        return web.Response(status=400)

    messages = load_user_messages()
    target = next((m for m in messages if m["id"] == msg_id), None)
    if not target:
        return web.Response(status=404)

    if bot:
        try:
            await bot.send_message(int(target["user_id"]), f"💬 Ответ от администратора:\n{text}")
        except Exception as e:
            logging.error(f"Reply send error: {e}")

    set_message_reply(msg_id, text)
    return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

async def api_message_read(request):
    data = await request.json()
    msg_id = data.get("id", "")
    if msg_id:
        mark_message_read(msg_id)
    return web.Response(text=json.dumps({"ok": True}), content_type="application/json")

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
    ok, msg_text = vote_in_poll(poll_id, user_id, option)
    await query.answer(msg_text, show_alert=not ok)

async def users_page(request):
    stats = load_stats()
    users = stats.get("users", {})
    rows = ""
    for uid, info in users.items():
        rows += f"<tr><td>{info.get('name')}</td><td>{uid}</td><td>{info.get('downloads', 0)}</td><td><span class='badge badge-error'>{info.get('errors', 0)}</span></td><td>{info.get('lang', 'unknown')}</td><td>{info.get('first_seen', '-')}</td></tr>"
    
    c = f"""<div class="header"><div class="logo">👥 Пользователи</div></div>
    <div class="panel"><h2>Список</h2>
    <table><thead><tr><th>Имя</th><th>ID</th><th>Видео</th><th>Ошибок</th><th>Язык</th><th>Первая активность</th></tr></thead><tbody>{rows if rows else '<tr><td colspan="6" style="text-align:center;color:#666;">Нет пользователей</td></tr>'}</tbody></table></div>"""
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
    app.router.add_post('/media/favorite', media_favorite)
    app.router.add_get('/broadcast', broadcast_page)
    app.router.add_post('/api/broadcast', api_broadcast)
    app.router.add_post('/api/poll-create', api_poll_create)
    app.router.add_post('/api/message-reply', api_message_reply)
    app.router.add_post('/api/message-read', api_message_read)
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
