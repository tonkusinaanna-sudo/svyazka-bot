# Svyazka Bot 🤖

Telegram-бот для процессинг-агента. Умеет:
- Автопостинг в группы каждые 3 часа (AI перефразирует текст)
- Автоответ на входящие личные сообщения
- Готовит черновики ответов через Groq AI
- Сохраняет важное в Базу знаний приложения (Supabase)

---

## Шаг 1 — Авторизация (делается ОДИН РАЗ локально)

Нужен Python 3.11+ и pip.

```bash
pip install telethon
python auth.py
```

Введи api_id, api_hash и номер телефона купленного аккаунта.
Введи код из Telegram. Появится файл `svyazka_session.session`.

Теперь конвертируй сессию в строку для Render:
```python
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

API_ID   = 12345678      # твой api_id
API_HASH = "abc..."      # твой api_hash

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print(client.session.save())
```

Скопируй строку — она понадобится как TG_SESSION на Render.

---

## Шаг 2 — Деплой на Render

1. Залей эту папку на GitHub (новый репозиторий `svyazka-bot`)
2. В Render: **New → Web Service** → подключи репозиторий
3. Настройки:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Starter ($7/мес) — НЕ Free (засыпает)

4. Добавь переменные окружения (**Environment → Add variable**):

| Key | Value |
|-----|-------|
| TG_API_ID | твой api_id (число) |
| TG_API_HASH | твой api_hash |
| TG_SESSION | строка сессии из Шага 1 |
| BOT_TOKEN | токен от @BotFather |
| GROQ_API_KEY | ключ от Groq |
| SUPABASE_URL | https://uqnvxyasloxdkoopcpcf.supabase.co |
| SUPABASE_KEY | твой anon key от Supabase |

5. Нажми **Deploy**

---

## Команды бота (пишешь себе в Telegram)

| Команда | Что делает |
|---------|-----------|
| `/help` | Список всех команд |
| `/post` | Немедленно сделать пост в группу |
| `/save Заголовок \| Текст` | Сохранить в Базу знаний |
| `/edit_123456 Текст` | Отправить свой текст пользователю с id 123456 |

---

## Как добавить новую группу для постинга

В файле `bot.py` найди:
```python
POST_CHAT = "processing_russia"
```
Измени на нужный @username группы. Или скажи разработчику — добавим список групп.
