"""
Svyazka Bot — Telegram userbot for processing agent.
- Posts to multiple forum chats every hour with video
- Auto-reply to incoming private messages
- Drafts replies via Groq AI
- Saves to Knowledge Base (Supabase)
"""

import asyncio
import logging
import os
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
import httpx
from supabase import create_client

# ─── Config ───────────────────────────────────────────────────────────────────
API_ID       = int(os.environ.get("TG_API_ID", "2040"))
API_HASH     = os.environ.get("TG_API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN    = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TG_SESSION   = os.environ.get("TG_SESSION", "")
OWNER        = "Cardsmg_assistant"
POST_INTERVAL = 60 * 60  # каждый час

# ─── Текст поста (фиксированный, без перефразирования) ───────────────────────
POST_TEXT = (
    "🔗 ПОДКЛЮЧЕНИЕ К ПЛОЩАДКАМ\n"
    "МНОГО ТРАФИКА, ЛЮБОЕ ГЕО\n"
    "ЕСТЬ ТРАНСГРАН, БТ, ЛОУ ЧЕКИ\n"
    "МАНУАЛЫ ДЛЯ СВОИХ 🔗"
)

# ─── Чаты для постинга: (username, reply_to_topic_id) ────────────────────────
# reply_to_topic_id = ID топика внутри форума (None = обычный чат)
POST_TARGETS = [
    ("processing_russia",  92814),
    ("blackprocforum",     3324),
    ("EsotericHighRisk",   4),
    ("processing_m",       8),
]

# ─── file_id видео (заполняется после первого запуска через /getvideoid) ──────
# Оставь пустым — бот сам попросит загрузить видео
VIDEO_FILE_ID = os.environ.get("VIDEO_FILE_ID", "")

# ─── Автоответ ────────────────────────────────────────────────────────────────
AUTO_REPLY = (
    "Добрый день, присылайте свой запрос!\n"
    "Как только буду на связи — дам ответ."
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Supabase ─────────────────────────────────────────────────────────────────
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Groq AI ──────────────────────────────────────────────────────────────────
async def draft_reply(message_text: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": (
                            "Ты ассистент переговорщика в сфере процессинга платёжей. "
                            "Пишешь кратко, деловито, по-русски. "
                            "Составь ответ на сообщение партнёра. "
                            "Только текст ответа, без пояснений."
                        )},
                        {"role": "user", "content": f"Сообщение от партнёра:\n{message_text}"},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.7,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"Groq draft failed: {e}")
        return "⚠️ Не удалось сгенерировать черновик."

# ─── Supabase: сохранить в Базу знаний ───────────────────────────────────────
async def save_to_kb(title: str, body: str, tag: str = "Входящие") -> bool:
    try:
        res = sb.table("app_state").select("value").eq("key", "kb:data").execute()
        notes = []
        if res.data and res.data[0]["value"]:
            notes = res.data[0]["value"]
        new_note = {
            "id": int(datetime.now().timestamp() * 1000),
            "title": title[:80],
            "tag": tag,
            "body": body,
            "updated": int(datetime.now().timestamp() * 1000),
        }
        notes.insert(0, new_note)
        sb.table("app_state").upsert({
            "key": "kb:data",
            "value": notes,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
        return True
    except Exception as e:
        log.error(f"save_to_kb error: {e}")
        return False

# ─── Хранилище черновиков ─────────────────────────────────────────────────────
drafts = {}  # sender_id -> draft_text

# ─── Основной клиент ──────────────────────────────────────────────────────────
async def main():
    session = StringSession(TG_SESSION) if TG_SESSION else StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    my_id = me.id
    log.info(f"Userbot started. Logged in as: {me.username or me.id}")

    auto_replied = set()

    # ─── Автоответ на входящие ────────────────────────────────────────────
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_private(event):
        sender_id = event.sender_id
        if sender_id == my_id:
            return
        sender = await event.get_sender()
        sender_name = getattr(sender, "username", None) or str(sender_id)
        msg_text = event.raw_text or ""
        log.info(f"Private from @{sender_name}: {msg_text[:80]}")

        if sender_id not in auto_replied:
            await event.reply(AUTO_REPLY)
            auto_replied.add(sender_id)

        draft = await draft_reply(msg_text)
        drafts[sender_id] = draft

        notify = (
            f"📨 **Новое сообщение** от @{sender_name} (`{sender_id}`):\n"
            f"```\n{msg_text[:300]}\n```\n\n"
            f"💡 **Черновик:**\n{draft}\n\n"
            f"Отправить черновик: `/send_{sender_id}`\n"
            f"Свой текст: `/edit_{sender_id} ТЕКСТ`"
        )
        try:
            await client.send_message(OWNER, notify, parse_mode="md")
        except Exception as e:
            log.warning(f"Notify owner failed: {e}")

    # ─── Команды ──────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=r"^/send_(\d+)$"))
    async def cmd_send(event):
        target_id = int(event.pattern_match.group(1))
        draft = drafts.get(target_id)
        if not draft:
            await event.reply("❌ Черновик не найден. Используй /edit_{id} ТЕКСТ")
            return
        await client.send_message(target_id, draft)
        await event.reply(f"✅ Черновик отправлен пользователю {target_id}")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/edit_(\d+) (.+)$"))
    async def cmd_edit(event):
        target_id = int(event.pattern_match.group(1))
        text = event.pattern_match.group(2)
        try:
            await client.send_message(target_id, text)
            await event.reply(f"✅ Отправлено пользователю {target_id}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/save (.+)$"))
    async def cmd_save(event):
        content = event.pattern_match.group(1)
        if "|" in content:
            parts = content.split("|", 1)
            title, body = parts[0].strip(), parts[1].strip()
        else:
            title, body = content[:50], content
        ok = await save_to_kb(title, body)
        await event.reply(f"{'✅ Сохранено: ' + title if ok else '❌ Ошибка сохранения'}")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/post$"))
    async def cmd_post(event):
        await event.reply("📤 Делаю пост во все чаты...")
        await do_post(client)
        await event.reply("✅ Готово!")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/getvideoid$"))
    async def cmd_getvideoid(event):
        await event.reply(
            "Перешли мне любое видео которое хочешь использовать для постинга.\n"
            "Я отвечу его file_id который нужно добавить в переменную VIDEO_FILE_ID на Render."
        )

    @client.on(events.NewMessage(outgoing=True, func=lambda e: e.video))
    async def handle_video(event):
        fid = event.video.id
        await event.reply(f"file_id этого видео:\n`{fid}`\n\nДобавь это значение как VIDEO_FILE_ID на Render.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/help$"))
    async def cmd_help(event):
        await event.reply(
            "🤖 **Svyazka Bot:**\n\n"
            "/post — немедленно постить во все чаты\n"
            "/send_{id} — отправить черновик\n"
            "/edit_{id} ТЕКСТ — отправить свой текст\n"
            "/save Заголовок | Текст — в Базу знаний\n"
            "/getvideoid — получить id видео\n"
            "/help — эта справка"
        )

    # ─── Автопостинг ──────────────────────────────────────────────────────
    async def do_post(client):
        for chat, topic_id in POST_TARGETS:
            try:
                kwargs = {"reply_to": topic_id} if topic_id else {}
                if VIDEO_FILE_ID:
                    await client.send_file(
                        chat,
                        file=VIDEO_FILE_ID,
                        caption=POST_TEXT,
                        **kwargs
                    )
                else:
                    await client.send_message(chat, POST_TEXT, **kwargs)
                log.info(f"Posted to {chat} topic={topic_id}")
                await asyncio.sleep(5)  # пауза между чатами
            except Exception as e:
                log.error(f"Post to {chat} failed: {e}")

    async def auto_post_loop():
        log.info("Auto-post loop started")
        await asyncio.sleep(60)  # первый пост через минуту
        while True:
            await do_post(client)
            await asyncio.sleep(POST_INTERVAL)

    asyncio.create_task(auto_post_loop())
    log.info("Bot is running. Commands: /help /post /save /send_ID /edit_ID /getvideoid")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
