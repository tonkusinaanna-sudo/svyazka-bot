"""
Svyazka Bot — Telegram userbot for processing agent.
Команды работают через Избранное (Saved Messages).
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
POST_INTERVAL = 60 * 60  # каждый час

# ─── Текст поста ─────────────────────────────────────────────────────────────
POST_TEXT = (
    "🔗 ПОДКЛЮЧЕНИЕ К ПЛОЩАДКАМ\n"
    "МНОГО ТРАФИКА, ЛЮБОЕ ГЕО\n"
    "ЕСТЬ ТРАНСГРАН, БТ, ЛОУ ЧЕКИ\n"
    "МАНУАЛЫ ДЛЯ СВОИХ 🔗"
)

# ─── Чаты для постинга ───────────────────────────────────────────────────────
POST_TARGETS = [
    ("processing_russia",  92814),
    ("blackprocforum",     3324),
    ("EsotericHighRisk",   4),
    ("processing_m",       8),
]

# ─── file_id видео (добавь на Render после получения) ────────────────────────
VIDEO_FILE_ID = os.environ.get("VIDEO_FILE_ID", "")

# ─── Автоответ ────────────────────────────────────────────────────────────────
AUTO_REPLY = (
    "Добрый день, присылайте свой запрос!\n"
    "Как только буду на связи — дам ответ."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
drafts = {}

async def draft_reply(text):
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "Ты ассистент переговорщика в сфере процессинга платёжей. Пишешь кратко, деловито, по-русски. Только текст ответа."},
                        {"role": "user", "content": f"Сообщение партнёра:\n{text}"},
                    ],
                    "max_tokens": 300, "temperature": 0.7,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"⚠️ Groq error: {e}"

async def save_to_kb(title, body, tag="Входящие"):
    try:
        res = sb.table("app_state").select("value").eq("key", "kb:data").execute()
        notes = res.data[0]["value"] if res.data and res.data[0]["value"] else []
        notes.insert(0, {"id": int(datetime.now().timestamp()*1000), "title": title[:80], "tag": tag, "body": body, "updated": int(datetime.now().timestamp()*1000)})
        sb.table("app_state").upsert({"key": "kb:data", "value": notes, "updated_at": datetime.utcnow().isoformat()}).execute()
        return True
    except Exception as e:
        log.error(f"save_to_kb: {e}")
        return False

async def do_post(client):
    for chat, topic_id in POST_TARGETS:
        try:
            kwargs = {"reply_to": topic_id} if topic_id else {}
            if VIDEO_FILE_ID:
                await client.send_file(chat, file=VIDEO_FILE_ID, caption=POST_TEXT, **kwargs)
            else:
                await client.send_message(chat, POST_TEXT, **kwargs)
            log.info(f"Posted to {chat} topic={topic_id}")
            await asyncio.sleep(5)
        except Exception as e:
            log.error(f"Post to {chat} failed: {e}")

async def main():
    session = StringSession(TG_SESSION) if TG_SESSION else StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    my_id = me.id
    log.info(f"Userbot started. Logged in as: {me.username or me.id}")

    auto_replied = set()

    # ─── Автоответ на входящие личные сообщения ───────────────────────────
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_private(event):
        sender_id = event.sender_id
        if sender_id == my_id:
            return
        sender = await event.get_sender()
        sender_name = getattr(sender, "username", None) or str(sender_id)
        msg_text = event.raw_text or ""

        # Автоответ один раз
        if sender_id not in auto_replied:
            await event.reply(AUTO_REPLY)
            auto_replied.add(sender_id)

        # Черновик ответа → в Избранное
        draft = await draft_reply(msg_text)
        drafts[sender_id] = draft
        notify = (
            f"📨 **От @{sender_name}** (`{sender_id}`):\n"
            f"```\n{msg_text[:300]}\n```\n\n"
            f"💡 **Черновик:**\n{draft}\n\n"
            f"➡️ `/send {sender_id}` — отправить черновик\n"
            f"➡️ `/reply {sender_id} ТЕКСТ` — свой текст"
        )
        await client.send_message("me", notify, parse_mode="md")
        log.info(f"Draft sent to Saved Messages for @{sender_name}")

    # ─── Команды через Избранное (пишешь себе) ────────────────────────────
    @client.on(events.NewMessage(outgoing=True, chats="me"))
    async def handle_saved(event):
        text = event.raw_text.strip()

        if text == "/help":
            await client.send_message("me",
                "🤖 **Svyazka Bot — команды** (пиши себе в Избранное):\n\n"
                "`/post` — немедленно постить во все чаты\n"
                "`/send ID` — отправить черновик\n"
                "`/reply ID ТЕКСТ` — отправить свой текст\n"
                "`/save Заголовок | Текст` — в Базу знаний\n"
                "`/videoid` — получить id видео (перешли видео следующим)\n"
                "`/help` — эта справка\n\n"
                f"📹 VIDEO_FILE_ID: `{VIDEO_FILE_ID or 'не задан'}`\n"
                f"⏱ Интервал постинга: каждый час\n"
                f"📢 Чатов: {len(POST_TARGETS)}"
            )

        elif text == "/post":
            await client.send_message("me", "📤 Делаю пост во все чаты...")
            await do_post(client)
            await client.send_message("me", "✅ Готово!")

        elif text == "/videoid":
            await client.send_message("me", "📹 Перешли следующим сообщением видео для постинга — я скажу его file_id.")

        elif text.startswith("/send "):
            parts = text.split(" ", 1)
            if len(parts) == 2:
                target_id = int(parts[1].strip())
                draft = drafts.get(target_id)
                if draft:
                    await client.send_message(target_id, draft)
                    await client.send_message("me", f"✅ Черновик отправлен пользователю {target_id}")
                else:
                    await client.send_message("me", f"❌ Черновик не найден для {target_id}")

        elif text.startswith("/reply "):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                target_id = int(parts[1])
                msg = parts[2]
                await client.send_message(target_id, msg)
                await client.send_message("me", f"✅ Отправлено пользователю {target_id}")

        elif text.startswith("/save "):
            content = text[6:]
            if "|" in content:
                t, b = content.split("|", 1)
            else:
                t, b = content[:50], content
            ok = await save_to_kb(t.strip(), b.strip())
            await client.send_message("me", f"{'✅ Сохранено: ' + t.strip() if ok else '❌ Ошибка'}")

    # ─── Получить file_id видео ───────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, chats="me", func=lambda e: e.video or e.gif))
    async def handle_video(event):
        media = event.video or event.gif
        if media:
            fid = str(media.id)
            await client.send_message("me",
                f"📹 **file_id видео:**\n`{fid}`\n\n"
                f"Добавь на Render → Environment → `VIDEO_FILE_ID` = это значение → Save, rebuild, and deploy"
            )

    # ─── Автопостинг ──────────────────────────────────────────────────────
    async def auto_post_loop():
        log.info("Auto-post loop started")
        await asyncio.sleep(60)
        while True:
            await do_post(client)
            await asyncio.sleep(POST_INTERVAL)

    asyncio.create_task(auto_post_loop())
    log.info("Bot is running! Write commands to Saved Messages (Избранное)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
