import os
import asyncio
import logging
import aiosqlite
from datetime import timedelta, datetime
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, ChatPermissions, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен берём из Secrets (Replit или GitHub)
OWNER_ID = 7322925570  # твой id (овнер)

DB_PATH = "bot.db"
LOG_FILE = "violations.log"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================== FSM СОСТОЯНИЯ ==================
class AdminStates(StatesGroup):
    add_word = State()
    del_word = State()
    add_link = State()
    del_link = State()

# ================== ИНИЦИАЛИЗАЦИЯ БАЗЫ ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS bad_words (word TEXT PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS allowed_links (link TEXT PRIMARY KEY)")
        await db.commit()

# ================== ХЕЛПЕРЫ ==================
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def log_violation(text: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")

# ================== КОМАНДЫ ==================
@dp.message(F.text == "/dante")
async def cmd_help(message: Message):
    text = (
        "<b>📜 Список команд:</b>\n"
        "/dante – показать список команд\n"
        "/admin – открыть админ-панель (только в ЛС для овнера/админов)\n\n"
        "📌 Модерация:\n"
        "🚫 Запрещённые слова → мут на 10 минут\n"
        "⛔ Запрещённые ссылки → бан\n"
    )
    await message.answer(text)

@dp.message(F.text == "/admin")
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        await message.answer("⚠️ Админ-панель доступна только в ЛС с ботом.")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить слово", callback_data="add_word")
    kb.button(text="➖ Удалить слово", callback_data="del_word")
    kb.button(text="📜 Список слов", callback_data="list_words")
    kb.button(text="➕ Добавить ссылку", callback_data="add_link")
    kb.button(text="➖ Удалить ссылку", callback_data="del_link")
    kb.button(text="📜 Список ссылок", callback_data="list_links")
    kb.button(text="⬇️ Скачать логи", callback_data="download_logs")
    kb.button(text="🗑 Очистить логи", callback_data="clear_logs")
    kb.adjust(2)

    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=kb.as_markup())

# ================== КНОПКИ АДМИН-ПАНЕЛИ ==================
@dp.callback_query(F.data == "list_words")
async def cb_list_words(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM bad_words") as cur:
            words = [row[0] for row in await cur.fetchall()]
    text = "🚫 Запрещённые слова:\n" + "\n".join(words) if words else "❌ Нет запрещённых слов"
    await call.message.answer(text)

@dp.callback_query(F.data == "list_links")
async def cb_list_links(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT link FROM allowed_links") as cur:
            links = [row[0] for row in await cur.fetchall()]
    text = "✅ Разрешённые ссылки:\n" + "\n".join(links) if links else "❌ Нет разрешённых ссылок"
    await call.message.answer(text)

@dp.callback_query(F.data == "download_logs")
async def cb_download_logs(call: CallbackQuery):
    await call.answer()
    if os.path.exists(LOG_FILE):
        file = FSInputFile(LOG_FILE)
        await call.message.answer_document(file)
    else:
        await call.message.answer("📂 Лог-файл пуст")

@dp.callback_query(F.data == "clear_logs")
async def cb_clear_logs(call: CallbackQuery):
    await call.answer()
    open(LOG_FILE, "w").close()
    await call.message.answer("🧹 Логи успешно очищены")

# ================== ДОБАВИТЬ/УДАЛИТЬ СЛОВО ==================
@dp.callback_query(F.data == "add_word")
async def cb_add_word(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("✏️ Введите слово для добавления в запрещённые:")
    await state.set_state(AdminStates.add_word)

@dp.message(AdminStates.add_word)
async def add_word_handler(message: Message, state: FSMContext):
    word = message.text.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO bad_words (word) VALUES (?)", (word,))
        await db.commit()
    await message.answer(f"✅ Слово <b>{word}</b> добавлено.")
    await state.clear()

@dp.callback_query(F.data == "del_word")
async def cb_del_word(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("🗑 Введите слово для удаления из запрещённых:")
    await state.set_state(AdminStates.del_word)

@dp.message(AdminStates.del_word)
async def del_word_handler(message: Message, state: FSMContext):
    word = message.text.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bad_words WHERE word=?", (word,))
        await db.commit()
    await message.answer(f"❌ Слово <b>{word}</b> удалено.")
    await state.clear()

# ================== ДОБАВИТЬ/УДАЛИТЬ ССЫЛКУ ==================
@dp.callback_query(F.data == "add_link")
async def cb_add_link(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("🔗 Введите ссылку для добавления в разрешённые:")
    await state.set_state(AdminStates.add_link)

@dp.message(AdminStates.add_link)
async def add_link_handler(message: Message, state: FSMContext):
    link = message.text.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO allowed_links (link) VALUES (?)", (link,))
        await db.commit()
    await message.answer(f"✅ Ссылка <b>{link}</b> добавлена.")
    await state.clear()

@dp.callback_query(F.data == "del_link")
async def cb_del_link(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("🗑 Введите ссылку для удаления из разрешённых:")
    await state.set_state(AdminStates.del_link)

@dp.message(AdminStates.del_link)
async def del_link_handler(message: Message, state: FSMContext):
    link = message.text.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM allowed_links WHERE link=?", (link,))
        await db.commit()
    await message.answer(f"❌ Ссылка <b>{link}</b> удалена.")
    await state.clear()

# ================== ФИЛЬТР СООБЩЕНИЙ ==================
@dp.message(F.text)
async def filter_messages(message: Message):
    if message.chat.type == "private":
        return

    text = message.text.lower()

    # Проверка запрещённых слов
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM bad_words") as cur:
            bad_words = [row[0] for row in await cur.fetchall()]

    for word in bad_words:
        if word in text.split():
            await message.delete()
            until_date = datetime.now() + timedelta(minutes=10)
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            warn = f'🚫 Пользователь <b>{message.from_user.full_name}</b> (id={message.from_user.id}) написал запрещённое слово и получил мут на 10 минут.\nПожалуйста соблюдайте правила чата!'
            await bot.send_message(chat_id=message.chat.id, message_thread_id=message.message_thread_id, text=warn)
            await log_violation(warn)
            return

    # Проверка запрещённых ссылок
    if "http://" in text or "https://" in text:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT link FROM allowed_links") as cur:
                allowed_links = [row[0].lower() for row in await cur.fetchall()]
        if not any(link in text for link in allowed_links):
            await message.delete()
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            warn = f'⛔ Пользователь <b>{message.from_user.full_name}</b> (id={message.from_user.id}) отправил запрещённую ссылку и был забанен.'
            await bot.send_message(chat_id=message.chat.id, message_thread_id=message.message_thread_id, text=warn)
            await log_violation(warn)

# ================== СТАРТ ==================
async def main():
    await init_db()
    print("✅ Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
