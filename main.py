import asyncio
import logging
import aiosqlite
from datetime import timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ChatPermissions
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

# === НАСТРОЙКИ ===
TOKEN = "YOUR_BOT_TOKEN"
OWNER_ID = 7322925570
DB_PATH = "bot.db"
LOG_FILE = "violations.log"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# === FSM состояния ===
class AdminStates(StatesGroup):
    add_chat = State()
    del_chat = State()
    add_word = State()
    del_word = State()
    add_link = State()
    del_link = State()
    add_immunity_chat = State()
    add_immunity_user = State()
    del_immunity_chat = State()
    del_immunity_user = State()
    unmute_chat = State()
    unmute_user = State()

# === БАЗА ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS bad_words (chat_id INTEGER, word TEXT, PRIMARY KEY(chat_id, word))")
        await db.execute("CREATE TABLE IF NOT EXISTS allowed_links (chat_id INTEGER, link TEXT, PRIMARY KEY(chat_id, link))")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
                                chat_id INTEGER PRIMARY KEY,
                                mute_enabled INTEGER DEFAULT 1,
                                ban_enabled INTEGER DEFAULT 1,
                                bot_enabled INTEGER DEFAULT 1
                            )""")
        await db.execute("CREATE TABLE IF NOT EXISTS immunity (chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id, user_id))")
        await db.commit()

# === ХЕЛПЕРЫ ===
def get_display_name(user) -> str:
    return f"@{user.username}" if user.username else f"id={user.id}"

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def log_violation(text: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")

# === КОМАНДЫ ===
@dp.message(F.text == "/dante")
async def cmd_dante(message: Message):
    text = (
        "📜 <b>Список команд:</b>\n\n"
        "🛠 <b>Админские:</b>\n"
        "/admin — открыть админ-панель (только в ЛС)\n"
        "/onbot — включить функционал бота\n"
        "/offbot — выключить функционал бота\n"
        "/unmute — снять мут с пользователя (только в ЛС)\n"
        "/checkid — узнать Chat ID и Topic ID\n\n"
        "⚡️ <b>Функционал:</b>\n"
        "• Авто-мут на 10 минут за запрещённые слова\n"
        "• Авто-бан за запрещённые ссылки\n"
        "• Разрешённые ссылки можно настраивать\n"
        "• Пользователям можно выдавать иммунитет\n"
        "• Логи нарушений (скачать/очистить через админку)\n\n"
        "👑 Управлять ботом может только овнер и добавленные админы."
    )
    await message.answer(text)

@dp.message(F.text == "/checkid")
async def cmd_checkid(message: Message):
    await message.answer(
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Topic ID: <code>{message.message_thread_id}</code>"
    )

@dp.message(F.text == "/onbot")
async def cmd_onbot(message: Message):
    if not await is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET bot_enabled=1")
        await db.commit()
    await message.answer("✅ Бот включён и снова работает.")

@dp.message(F.text == "/offbot")
async def cmd_offbot(message: Message):
    if not await is_admin(message.from_user.id): return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET bot_enabled=0")
        await db.commit()
    await message.answer("⛔ Бот выключен.")

# === АНТИ-СПАМ ФИЛЬТР ===
@dp.message()
async def filter_messages(message: Message):
    if message.chat.type == "private":
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT bot_enabled FROM settings WHERE chat_id=?", (message.chat.id,)) as cur:
            row = await cur.fetchone()
            if row is not None and row[0] == 0:
                return

        # иммунитет
        async with db.execute("SELECT 1 FROM immunity WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id)) as cur:
            if await cur.fetchone():
                return

        # запрещённые слова
        async with db.execute("SELECT word FROM bad_words WHERE chat_id=?", (message.chat.id,)) as cur:
            bad_words = [r[0] for r in await cur.fetchall()]

        # разрешённые ссылки
        async with db.execute("SELECT link FROM allowed_links WHERE chat_id=?", (message.chat.id,)) as cur:
            allowed_links = [r[0] for r in await cur.fetchall()]

        async with db.execute("SELECT mute_enabled, ban_enabled FROM settings WHERE chat_id=?", (message.chat.id,)) as cur:
            row = await cur.fetchone()
            mute_enabled, ban_enabled = (1, 1) if not row else row

    text = message.text.lower() if message.text else ""

    # мут за слово
    if mute_enabled:
        for word in bad_words:
            if word in text.split():
                await message.delete()
                await bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=timedelta(minutes=10)
                )
                warn = f"🚫 Пользователь {get_display_name(message.from_user)} написал запрещённое слово и получил мут на 10 минут."
                await bot.send_message(message.chat.id, warn, message_thread_id=message.message_thread_id)
                await log_violation(warn)
                return

    # бан за ссылку
    if ban_enabled and ("http://" in text or "https://" in text):
        if not any(allowed in text for allowed in allowed_links):
            await message.delete()
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            warn = f"⛔ Пользователь {get_display_name(message.from_user)} отправил запрещённую ссылку и был забанен."
            await bot.send_message(message.chat.id, warn, message_thread_id=message.message_thread_id)
            await log_violation(warn)
            return

# === СТАРТ ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
