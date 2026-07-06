"""
Svyazka Bot — Telegram assistant for processing agent.
Works via Telethon (userbot) + aiogram (command bot).
"""

import asyncio
import logging
import os
import random
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerChannel
import httpx
from supabase import create_client

# ─── Config ───────────────────────────────────────────────────────────────────
API_ID   = int(os.environ.get("TG_API_ID", "2040"))
API_HASH = os.environ.get("TG_API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN        = os.environ["BOT_TOKEN"]
GROQ_API_KEY     = os.environ["GROQ_API_KEY"]
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
OWNER_USERNAME   = "Cardsmg_assistant"          # твой @username без @
POST_CHAT        = "processing_russia"           # куда постить (без @)
POST_INTERVAL    = 3 * 60 * 60                   # каждые 3 часа в секундах
TG_SESSION       = os.environ.get("TG_SESSION", "")  # строка сессии

# ─── Auto-reply text ──────────────────────────────────────────────────────────
AUTO_REPLY = (
    "Добрый день, присылайте свой запрос!\n"
    "Как только буду на связи — дам ответ."
)

# ─── Post templates (AI будет перефразировать каждый раз) ────────────────────
POST_BASE = (
    "🔗 ПОДКЛЮЧЕНИЕ К ПЛОЩАДКАМ\n"
    "МНОГО ТРАФИКА, ЛЮБОЕ ГЕО\n"
    "ЕСТЬ ТРАНСГРАН, БТ, ЛОУ ЧЕКИ\n"
    "МАНУАЛЫ ДЛЯ СВОИХ 🔗"
)

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── Supabase ─────────────────────────────────────────────────────────────────
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Groq AI ──────────────────────────────────────────────────────────────────
async def ask_groq(system: str, user: str) -> str:
    """Запрос к Groq API."""
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "max_tokens": 500,
                "temperature": 0.8,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def rephrase_post(base: str) -> str:
    """Перефразирует рекламный пост чтобы избежать бана."""
    try:
        return await ask_groq(
            system=(
                "Ты помощник по рерайтингу рекламных текстов в Telegram. "
                "Перефразируй текст сохраняя смысл и эмодзи, "
                "меняй порядок слов и синонимы. "
                "Отвечай только текстом поста, без пояснений."
            ),
            user=f"Перефразируй этот пост:\n{base}",
        )
    except Exception as e:
        log.warning(f"Groq rephrase failed: {e}, using original")
        return base


async def draft_reply(message_text: str) -> str:
    """Готовит черновик ответа на входящее сообщение."""
    try:
        return await ask_groq(
            system=(
                "Ты ассистент переговорщика в сфере процессинга платёжей. "
                "Пишешь кратко, деловито, по-русски. "
                "Составь ответ на сообщение партнёра. "
                "Не используй лишних слов. "
                "Ответ — только текст сообщения, без пояснений."
            ),
            user=f"Сообщение от партнёра:\n{message_text}",
        )
    except Exception as e:
        log.warning(f"Groq draft failed: {e}")
        return "⚠️ Не удалось сгенерировать черновик. Ответь вручную."


# ─── Supabase: сохранить в Базу знаний ───────────────────────────────────────
async def save_to_kb(title: str, body: str, tag: str = "Входящие") -> bool:
    """Сохраняет текст в раздел «База знаний» приложения."""
    try:
        # Читаем текущие заметки
        res = sb.table("app_state").select("value").eq("key", "kb:data").execute()
        notes = []
        if res.data and res.data[0]["value"]:
            notes = res.data[0]["value"]

        # Добавляем новую заметку
        new_note = {
            "id": int(datetime.now().timestamp() * 1000),
            "title": title[:80],
            "tag": tag,
            "body": body,
            "updated": int(datetime.now().timestamp() * 1000),
        }
        notes.insert(0, new_note)

        # Сохраняем обратно
        sb.table("app_state").upsert({
            "key": "kb:data",
            "value": notes,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
        return True
    except Exception as e:
        log.error(f"save_to_kb error: {e}")
        return False


# ─── Основной клиент (userbot) ────────────────────────────────────────────────
async def main():
    # Userbot — работает от имени купленного аккаунта
    session = StringSession(TG_SESSION) if TG_SESSION else StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start(bot_token=None)  # авторизация через сессию
    log.info("Userbot started")

    me = await client.get_me()
    log.info(f"Logged in as: {me.username or me.id}")

    # Кешируем своё id чтобы не отвечать самому себе
    my_id = me.id

    # Флаги — кому уже ответили авто-ответом (чтобы не спамить)
    auto_replied: set[int] = set()

    # ─── Автоответ на входящие личные сообщения ───────────────────────────
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_private(event):
        sender_id = event.sender_id
        if sender_id == my_id:
            return

        sender = await event.get_sender()
        sender_name = getattr(sender, "username", None) or str(sender_id)
        msg_text = event.raw_text or ""

        log.info(f"Private message from @{sender_name}: {msg_text[:80]}")

        # Автоответ (один раз на диалог)
        if sender_id not in auto_replied:
            await event.reply(AUTO_REPLY)
            auto_replied.add(sender_id)
            log.info(f"Auto-replied to @{sender_name}")

        # Готовим черновик и отправляем тебе
        draft = await draft_reply(msg_text)
        notify = (
            f"📨 **Новое сообщение** от @{sender_name}:\n"
            f"```\n{msg_text[:300]}\n```\n\n"
            f"💡 **Черновик ответа:**\n{draft}\n\n"
            f"Отправь /send_{sender_id} чтобы отправить этот черновик\n"
            f"Или /edit_{sender_id} ТЕКСТ чтобы отправить свой текст"
        )
        try:
            await client.send_message(OWNER_USERNAME, notify, parse_mode="md")
        except Exception as e:
            log.warning(f"Could not notify owner: {e}")

    # ─── Команды от тебя (owner) ──────────────────────────────────────────
    @client.on(events.NewMessage(
        outgoing=False,
        from_users=[OWNER_USERNAME],
        pattern=r"^/send_(\d+)$"
    ))
    async def cmd_send(event):
        """Отправить последний черновик указанному пользователю."""
        target_id = int(event.pattern_match.group(1))
        # Берём черновик из истории (последнее сообщение боту с этим id)
        await event.reply(f"✅ Пытаюсь отправить черновик пользователю {target_id}...")
        # TODO: хранить черновики в памяти по sender_id
        await event.reply("⚠️ Используй /edit_{id} ТЕКСТ для отправки своего текста")

    @client.on(events.NewMessage(
        outgoing=False,
        from_users=[OWNER_USERNAME],
        pattern=r"^/edit_(\d+) (.+)$"
    ))
    async def cmd_edit(event):
        """Отправить свой текст указанному пользователю."""
        target_id = int(event.pattern_match.group(1))
        text = event.pattern_match.group(2)
        try:
            await client.send_message(target_id, text)
            await event.reply(f"✅ Отправлено пользователю {target_id}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

    @client.on(events.NewMessage(
        outgoing=False,
        from_users=[OWNER_USERNAME],
        pattern=r"^/save (.+)$"
    ))
    async def cmd_save(event):
        """Сохранить текст в Базу знаний. Формат: /save Заголовок | Текст"""
        content = event.pattern_match.group(1)
        if "|" in content:
            parts = content.split("|", 1)
            title, body = parts[0].strip(), parts[1].strip()
        else:
            title = content[:50]
            body = content
        ok = await save_to_kb(title, body)
        if ok:
            await event.reply(f"✅ Сохранено в Базу знаний: **{title}**")
        else:
            await event.reply("❌ Ошибка сохранения. Проверь Supabase.")

    @client.on(events.NewMessage(
        outgoing=False,
        from_users=[OWNER_USERNAME],
        pattern=r"^/post$"
    ))
    async def cmd_post(event):
        """Немедленно сделать пост в группу."""
        text = await rephrase_post(POST_BASE)
        try:
            await client.send_message(POST_CHAT, text)
            await event.reply(f"✅ Пост отправлен в @{POST_CHAT}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

    @client.on(events.NewMessage(
        outgoing=False,
        from_users=[OWNER_USERNAME],
        pattern=r"^/help$"
    ))
    async def cmd_help(event):
        """Список команд."""
        await event.reply(
            "🤖 **Svyazka Bot — команды:**\n\n"
            "/post — немедленно опубликовать пост\n"
            "/send_{id} — отправить черновик пользователю\n"
            "/edit_{id} ТЕКСТ — отправить свой текст пользователю\n"
            "/save Заголовок | Текст — сохранить в Базу знаний\n"
            "/help — эта справка\n\n"
            "📬 На каждое входящее личное сообщение:\n"
            "— автоответ отправляется сразу\n"
            "— черновик ответа приходит тебе"
        )

    # ─── Автопостинг каждые 3 часа ────────────────────────────────────────
    async def auto_post_loop():
        log.info("Auto-post loop started")
        # Ждём немного перед первым постом чтобы клиент успел подключиться
        await asyncio.sleep(60)
        while True:
            try:
                text = await rephrase_post(POST_BASE)
                await client.send_message(POST_CHAT, text)
                log.info(f"Auto-post sent to {POST_CHAT}")
            except Exception as e:
                log.error(f"Auto-post error: {e}")
            await asyncio.sleep(POST_INTERVAL)

    # Запускаем автопостинг параллельно
    asyncio.create_task(auto_post_loop())

    log.info("Bot is running. Commands: /help /post /save /send_ID /edit_ID")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
