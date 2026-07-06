"""
Авторизация через QR-код — не нужен api_id с my.telegram.org.
Использует встроенные данные от официального Telegram Desktop.

Запуск:
  pip install telethon qrcode pillow
  python auth.py
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# Официальный Telegram Desktop api_id (публичный, всегда работает)
API_ID   = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

async def main():
    print("=" * 50)
    print("Авторизация Svyazka Bot")
    print("=" * 50)
    print()
    
    session = StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    
    await client.connect()
    
    print("Выбери способ входа:")
    print("1 — По номеру телефона")
    print("2 — По QR-коду (отсканируй в Telegram)")
    print()
    choice = input("Твой выбор (1 или 2): ").strip()
    
    if choice == "2":
        print()
        print("Открой Telegram на телефоне:")
        print("Настройки → Устройства → Подключить устройство → Сканировать QR")
        print()
        
        async def qr_callback(token):
            import qrcode
            qr = qrcode.QRCode()
            qr.add_data(token.url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
            print(f"\nQR-код выше. Отсканируй его в Telegram.")
            print(f"Или перейди по ссылке: {token.url}")
            print()
        
        try:
            await client.qr_login(qr_callback)
        except Exception as e:
            print(f"QR не сработал: {e}")
            print("Пробуем через номер телефона...")
            choice = "1"
    
    if choice == "1":
        phone = input("Номер телефона (например +79001234567): ").strip()
        await client.send_code_request(phone)
        code = input("Код из Telegram: ").strip()
        try:
            await client.sign_in(phone, code)
        except Exception as e:
            if "two-steps" in str(e).lower() or "password" in str(e).lower():
                pwd = input("Введи пароль двухфакторной аутентификации: ").strip()
                await client.sign_in(password=pwd)
            else:
                raise
    
    me = await client.get_me()
    print(f"\n✅ Успешно! Вошёл как: @{me.username or me.first_name}")
    
    session_string = client.session.save()
    print()
    print("=" * 50)
    print("СТРОКА СЕССИИ (скопируй полностью):")
    print("=" * 50)
    print(session_string)
    print("=" * 50)
    print()
    print("Эту строку добавь на Render как переменную TG_SESSION")
    print("А также добавь:")
    print(f"TG_API_ID  = {API_ID}")
    print(f"TG_API_HASH = {API_HASH}")
    
    await client.disconnect()

asyncio.run(main())
