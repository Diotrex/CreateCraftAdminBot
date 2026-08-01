import asyncio
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ЗАМЕНИ НА ТОКЕН БОТА
ADMIN_IDS = [6144388776, 6101597477, 8474937012]
ADMIN_USERNAMES = {6144388776: "Difig", 6101597477: "Diotrex", 8474937012: "mozzy"}

# Дефолтные настройки (меняются через админку)
DEFAULT_SETTINGS = {
    "curseforge_link": "https://curseforge.com/your_modpack",
    "google_disk_link": "https://drive.google.com/your_file",
    "radmin_network": "CREATE_CRAFT_DIFIG",
    "radmin_password": "CREATE_CRAFT",
    "server_ip": "26.136.234.59",
    "donationalerts_link": "https://donationalerts.com/your_page",
    "rules": "Правила сервера:\n1. Не гриферить\n2. Быть адекватным\n3. ...",
    "description": "Описание сервера Create Craft...",
}
# =======================================================

# ==================== БАЗА ДАННЫХ ====================
DB_PATH = "bot_database.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_interaction DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                nickname TEXT,
                age TEXT,
                timezone TEXT,
                playtime TEXT,
                create_knowledge_level TEXT,
                create_knowledge_text TEXT,
                idea_role TEXT,
                crash_scenario TEXT,
                telegram_link TEXT,
                discord_link TEXT,
                vk_link TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                type TEXT,
                message_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'open',
                admin_reply TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                admin_username TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()


async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()


async def log_admin_action(admin_id: int, action: str, details: str = ""):
    admin_username = ADMIN_USERNAMES.get(admin_id, f"ID{admin_id}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO admin_logs (admin_id, admin_username, action, details) VALUES (?, ?, ?, ?)",
            (admin_id, admin_username, action, details),
        )
        await db.commit()


async def update_user_interaction(user: types.User):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, first_interaction, last_interaction)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_interaction = CURRENT_TIMESTAMP
        """,
            (user.id, user.username, user.first_name, user.last_name),
        )
        await db.commit()


# ==================== FSM СОСТОЯНИЯ ====================
class ApplicationForm(StatesGroup):
    waiting_for_nickname = State()
    waiting_for_age = State()
    waiting_for_timezone = State()
    waiting_for_playtime = State()
    waiting_for_create_level = State()
    waiting_for_create_knowledge = State()
    waiting_for_idea = State()
    waiting_for_crash = State()
    waiting_for_telegram = State()
    waiting_for_discord = State()
    waiting_for_vk = State()


class AdminStates(StatesGroup):
    waiting_for_rules = State()
    waiting_for_description = State()
    waiting_for_curseforge_link = State()
    waiting_for_google_disk_link = State()
    waiting_for_radmin_network = State()
    waiting_for_radmin_password = State()
    waiting_for_server_ip = State()
    waiting_for_donationalerts_link = State()
    waiting_for_ticket_reply = State()
    waiting_for_application_delete_number = State()
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_id = State()


class TicketStates(StatesGroup):
    waiting_for_support_message = State()
    waiting_for_complaint_message = State()


# ==================== КЛАВИАТУРЫ ====================
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📝 Подать заявку", callback_data="menu_apply"))
    builder.row(InlineKeyboardButton(text="📋 Описание сервера", callback_data="menu_description"))
    builder.row(
        InlineKeyboardButton(text="📦 Сборка", callback_data="menu_assembly"),
        InlineKeyboardButton(text="📖 Инструкция", callback_data="menu_instruction"),
    )
    builder.row(
        InlineKeyboardButton(text="📜 Правила", callback_data="menu_rules"),
        InlineKeyboardButton(text="💰 Пожертвования", callback_data="menu_donations"),
    )
    builder.row(
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support"),
        InlineKeyboardButton(text="🚨 Жалоба", callback_data="menu_complaint"),
    )
    builder.adjust(1, 1, 2, 2, 2)
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data))
    return builder.as_markup()


def get_back_skip_keyboard(back_callback: str = "back_to_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_question"),
        InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback),
    )
    return builder.as_markup()


def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Анкеты", callback_data="admin_applications"))
    builder.row(
        InlineKeyboardButton(text="📦 Сборка", callback_data="admin_assembly"),
        InlineKeyboardButton(text="📖 Инструкция", callback_data="admin_instruction"),
    )
    builder.row(
        InlineKeyboardButton(text="📜 Правила", callback_data="admin_rules"),
        InlineKeyboardButton(text="📋 Описание сервера", callback_data="admin_description"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Пожертвования", callback_data="admin_donations"),
        InlineKeyboardButton(text="📨 Обращения", callback_data="admin_tickets"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_statistics"),
        InlineKeyboardButton(text="📝 Логи", callback_data="admin_logs"),
    )
    builder.row(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.row(InlineKeyboardButton(text="🔙 Выйти из админки", callback_data="admin_exit"))
    builder.adjust(1, 2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def get_applications_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Список анкет", callback_data="admin_app_list"),
        InlineKeyboardButton(text="⚙️ Управление анкетами", callback_data="admin_app_manage"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin"))
    builder.adjust(2, 1)
    return builder.as_markup()


def get_tickets_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🆘 Поддержка (тикеты)", callback_data="admin_tickets_support"),
        InlineKeyboardButton(text="🚨 Жалобы (тикеты)", callback_data="admin_tickets_complaint"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin"))
    builder.adjust(2, 1)
    return builder.as_markup()


def get_assembly_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔗 Изменить CurseForge", callback_data="admin_change_cf"),
        InlineKeyboardButton(text="🔗 Изменить Google Диск", callback_data="admin_change_gd"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin"))
    builder.adjust(2, 1)
    return builder.as_markup()


def get_instruction_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌐 Изменить сеть Radmin", callback_data="admin_change_radmin_net"),
        InlineKeyboardButton(text="🔑 Изменить пароль Radmin", callback_data="admin_change_radmin_pass"),
    )
    builder.row(InlineKeyboardButton(text="🌍 Изменить IP сервера", callback_data="admin_change_ip"))
    builder.row(InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin"))
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Отправить по ID", callback_data="broadcast_by_id"),
        InlineKeyboardButton(text="👥 Отправить всем", callback_data="broadcast_all"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin"))
    builder.adjust(2, 1)
    return builder.as_markup()


# ==================== ХЭНДЛЕРЫ ====================
router = Router()


# Команда /start
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await update_user_interaction(message.from_user)
    await message.answer(
        "👋 Добро пожаловать в бот сервера Create Craft!\nВыберите действие:",
        reply_markup=get_main_menu_keyboard(),
    )


# Команда /admin
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    await update_user_interaction(message.from_user)
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    await message.answer(
        "🔐 Админ-панель. Выберите раздел:",
        reply_markup=get_admin_panel_keyboard(),
    )


# ==================== CALLBACK-ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ====================
@router.callback_query(F.data == "menu_apply")
async def cb_menu_apply(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await update_user_interaction(callback.from_user)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Пройти в боте", callback_data="apply_in_bot"),
        InlineKeyboardButton(text="🌐 Google Forms", url="https://forms.google.com/your_form"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        "📝 Вы можете подать заявку для игры на сервере через Google Forms или оставить её прямо здесь, в боте.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "👋 Главное меню:",
        reply_markup=get_main_menu_keyboard(),
    )


@router.callback_query(F.data == "back_to_admin")
async def cb_back_to_admin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "🔐 Админ-панель. Выберите раздел:",
        reply_markup=get_admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_exit")
async def cb_admin_exit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "👋 Главное меню:",
        reply_markup=get_main_menu_keyboard(),
    )


# ==================== МЕНЮ СБОРКА ====================
@router.callback_query(F.data == "menu_assembly")
async def cb_menu_assembly(callback: CallbackQuery):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    curseforge_link = await get_setting("curseforge_link")
    google_disk_link = await get_setting("google_disk_link")
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📦 Скачать с CurseForge", url=curseforge_link or "#"),
        InlineKeyboardButton(text="💾 Скачать с Google Диска", url=google_disk_link or "#"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        "📦 Сборку сервера можно скачать с CurseForge или Google Диска:",
        reply_markup=builder.as_markup(),
    )


# ==================== МЕНЮ ИНСТРУКЦИЯ ====================
@router.callback_query(F.data == "menu_instruction")
async def cb_menu_instruction(callback: CallbackQuery):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    radmin_network = await get_setting("radmin_network")
    radmin_password = await get_setting("radmin_password")
    server_ip = await get_setting("server_ip")
    text = (
        "📖 Инструкция по подключению:\n\n"
        "1️⃣ Скачайте Radmin VPN\n"
        f"2️⃣ Зайдите в сеть сервера. Логин: {radmin_network} Пароль: {radmin_password}\n"
        f"3️⃣ Скачайте сборку сервера и подключитесь по IP: {server_ip}\n\n"
        "Приятной игры! 🎮"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


# ==================== МЕНЮ ПРАВИЛА ====================
@router.callback_query(F.data == "menu_rules")
async def cb_menu_rules(callback: CallbackQuery):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    rules = await get_setting("rules")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        f"📜 {rules or 'Правила не установлены.'}",
        reply_markup=builder.as_markup(),
    )


# ==================== МЕНЮ ОПИСАНИЕ СЕРВЕРА ====================
@router.callback_query(F.data == "menu_description")
async def cb_menu_description(callback: CallbackQuery):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    description = await get_setting("description")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        f"📋 {description or 'Описание сервера пока не добавлено.'}",
        reply_markup=builder.as_markup(),
    )


# ==================== МЕНЮ ПОЖЕРТВОВАНИЯ ====================
@router.callback_query(F.data == "menu_donations")
async def cb_menu_donations(callback: CallbackQuery):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    donationalerts_link = await get_setting("donationalerts_link")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 DonationAlerts", url=donationalerts_link or "#"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        "💰 Поддержите развитие сервера! Все средства пойдут на апгрейд серверного оборудования.",
        reply_markup=builder.as_markup(),
    )


# ==================== МЕНЮ ПОДДЕРЖКА ====================
@router.callback_query(F.data == "menu_support")
async def cb_menu_support(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    await state.set_state(TicketStates.waiting_for_support_message)
    await callback.message.delete()
    msg = await callback.message.answer(
        "🆘 Опишите вашу проблему, и администраторы свяжутся с вами:",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)


@router.message(TicketStates.waiting_for_support_message)
async def process_support_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or f"ID{user_id}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tickets (user_id, username, type, message_text) VALUES (?, ?, 'support', ?)",
            (user_id, username, message.text),
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Ваше обращение отправлено. Администраторы скоро ответят.", reply_markup=get_main_menu_keyboard())
    for admin_id in ADMIN_IDS:
        try:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply_ticket_{user_id}"))
            await message.bot.send_message(
                admin_id,
                f"🆘 Новая заявка в поддержку!\n👤 От: @{username} (ID: {user_id})\n💬 {message.text}",
                reply_markup=builder.as_markup(),
            )
        except Exception:
            pass


# ==================== МЕНЮ ЖАЛОБА ====================
@router.callback_query(F.data == "menu_complaint")
async def cb_menu_complaint(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await update_user_interaction(callback.from_user)
    await state.set_state(TicketStates.waiting_for_complaint_message)
    await callback.message.delete()
    msg = await callback.message.answer(
        "🚨 Опишите жалобу на игрока, нарушившего правила:",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)


@router.message(TicketStates.waiting_for_complaint_message)
async def process_complaint_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or f"ID{user_id}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tickets (user_id, username, type, message_text) VALUES (?, ?, 'complaint', ?)",
            (user_id, username, message.text),
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Жалоба отправлена. Администраторы рассмотрят её.", reply_markup=get_main_menu_keyboard())
    for admin_id in ADMIN_IDS:
        try:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply_ticket_{user_id}"))
            await message.bot.send_message(
                admin_id,
                f"🚨 Новая жалоба!\n👤 От: @{username} (ID: {user_id})\n💬 {message.text}",
                reply_markup=builder.as_markup(),
            )
        except Exception:
            pass


# ==================== АНКЕТА (FSM) ====================
@router.callback_query(F.data == "apply_in_bot")
async def start_bot_application(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    msg = await callback.message.answer(
        "📝 Начинаем анкету. Введите ваш никнейм в Minecraft (Java Edition):",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_nickname)


@router.message(ApplicationForm.waiting_for_nickname)
async def process_nickname(message: Message, state: FSMContext):
    await state.update_data(nickname=message.text)
    msg = await message.answer("🎂 Сколько вам полных лет?", reply_markup=get_back_keyboard("back_to_main"))
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_age)


@router.message(ApplicationForm.waiting_for_age)
async def process_age(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0 or int(message.text) > 100:
        await message.answer("⚠️ Пожалуйста, введите корректный возраст (число от 1 до 100).")
        return
    await state.update_data(age=message.text)
    msg = await message.answer("🌍 Ваш часовой пояс (например, MSK, GMT+3):", reply_markup=get_back_keyboard("back_to_main"))
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_timezone)


@router.message(ApplicationForm.waiting_for_timezone)
async def process_timezone(message: Message, state: FSMContext):
    await state.update_data(timezone=message.text)
    builder = InlineKeyboardBuilder()
    times = ["<1", "~2", "~3", "~5", "~6", "~8", "~10", ">10"]
    for i in range(0, len(times), 3):
        builder.row(*[InlineKeyboardButton(text=t, callback_data=f"playtime_{t}") for t in times[i:i+3]])
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    msg = await message.answer(
        "⏰ Время в день, которое вы будете уделять игре (часов):",
        reply_markup=builder.as_markup(),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_playtime)


@router.callback_query(F.data.startswith("playtime_"))
async def process_playtime(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    playtime = callback.data.replace("playtime_", "")
    await state.update_data(playtime=playtime)
    builder = InlineKeyboardBuilder()
    for i in range(1, 11):
        builder.add(InlineKeyboardButton(text=str(i), callback_data=f"createlevel_{i}"))
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(
        "⭐ Оцените свои знания в моде Create (1-10):",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplicationForm.waiting_for_create_level)


@router.callback_query(F.data.startswith("createlevel_"))
async def process_create_level(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    level = callback.data.replace("createlevel_", "")
    await state.update_data(create_knowledge_level=level)
    await callback.message.delete()
    msg = await callback.message.answer(
        "🤔 Что вы знаете о моде Create?",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_create_knowledge)


@router.message(ApplicationForm.waiting_for_create_knowledge)
async def process_create_knowledge(message: Message, state: FSMContext):
    await state.update_data(create_knowledge_text=message.text)
    msg = await message.answer(
        "💡 Расскажите о своей идее и роли на сервере. Что будете делать после того как зайдете?",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_idea)


@router.message(ApplicationForm.waiting_for_idea)
async def process_idea(message: Message, state: FSMContext):
    await state.update_data(idea_role=message.text)
    msg = await message.answer(
        "💥 Представьте ситуацию: ваш завод сломался из-за бага/отключения сервера. Ваша первая мысль и действия?",
        reply_markup=get_back_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_crash)


@router.message(ApplicationForm.waiting_for_crash)
async def process_crash(message: Message, state: FSMContext):
    await state.update_data(crash_scenario=message.text)
    msg = await message.answer(
        "📱 Ссылка на ваш Telegram для связи\nПример: t.me/username",
        reply_markup=get_back_keyboard("back_to_main"),
        link_preview_options={"is_disabled": True},
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_telegram)


@router.message(ApplicationForm.waiting_for_telegram)
async def process_telegram(message: Message, state: FSMContext):
    await state.update_data(telegram_link=message.text)
    msg = await message.answer(
        "🎮 Ссылка на ваш Discord для связи:",
        reply_markup=get_back_skip_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_discord)


@router.callback_query(F.data == "skip_question")
async def skip_question_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()
    if current_state == ApplicationForm.waiting_for_discord:
        await state.update_data(discord_link="Не указано")
        await callback.message.delete()
        msg = await callback.message.answer(
            "🌐 Ссылка на ваш VK для связи:",
            reply_markup=get_back_skip_keyboard("back_to_main"),
        )
        await state.update_data(question_message_id=msg.message_id)
        await state.set_state(ApplicationForm.waiting_for_vk)
    elif current_state == ApplicationForm.waiting_for_vk:
        await state.update_data(vk_link="Не указано")
        await finish_application(callback.message, state)


@router.message(ApplicationForm.waiting_for_discord)
async def process_discord(message: Message, state: FSMContext):
    await state.update_data(discord_link=message.text)
    msg = await message.answer(
        "🌐 Ссылка на ваш VK для связи:",
        reply_markup=get_back_skip_keyboard("back_to_main"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(ApplicationForm.waiting_for_vk)


@router.message(ApplicationForm.waiting_for_vk)
async def process_vk(message: Message, state: FSMContext):
    await state.update_data(vk_link=message.text)
    await finish_application(message, state)


async def finish_application(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username or f"ID{user_id}"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO applications (user_id, username, nickname, age, timezone, playtime,
                create_knowledge_level, create_knowledge_text, idea_role, crash_scenario,
                telegram_link, discord_link, vk_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_id, username,
                data.get("nickname"), data.get("age"), data.get("timezone"), data.get("playtime"),
                data.get("create_knowledge_level"), data.get("create_knowledge_text"),
                data.get("idea_role"), data.get("crash_scenario"),
                data.get("telegram_link"), data.get("discord_link"), data.get("vk_link"),
            ),
        )
        await db.commit()

    await state.clear()
    await message.answer(
        "✅ Ваша заявка успешно отправлена! Администраторы рассмотрят её в ближайшее время.",
        reply_markup=get_main_menu_keyboard(),
    )

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"📬 Новая заявка от @{username} (ID: {user_id})!\n"
                f"Проверьте в админ-панели: /admin → Анкеты",
            )
        except Exception:
            pass


# ==================== ОТВЕТ НА ТИКЕТ ====================
@router.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    target_user_id = int(callback.data.replace("reply_ticket_", ""))
    await state.update_data(reply_target=target_user_id)
    await callback.message.answer(
        f"✉️ Введите ответ для пользователя (ID: {target_user_id}):",
        reply_markup=get_back_keyboard("back_to_admin"),
    )
    await state.set_state(AdminStates.waiting_for_ticket_reply)
    await callback.answer()


@router.message(AdminStates.waiting_for_ticket_reply)
async def process_ticket_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("reply_target")
    if not target_user_id:
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_admin_panel_keyboard())
        await state.clear()
        return
    try:
        await message.bot.send_message(
            target_user_id,
            f"✉️ Ответ от администратора:\n\n{message.text}",
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE tickets SET status = 'closed', admin_reply = ? WHERE user_id = ? AND status = 'open'",
                (message.text, target_user_id),
            )
            await db.commit()
        await log_admin_action(message.from_user.id, "Ответил на обращение", f"Пользователь ID {target_user_id}")
        await message.answer(
            "✅ Ответ отправлен пользователю.",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
            ).as_markup(),
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить ответ: {e}",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
            ).as_markup(),
        )
    await state.clear()


# ==================== АДМИНКА: CALLBACK-ОБРАБОТЧИКИ ====================
@router.callback_query(F.data == "admin_applications")
async def cb_admin_applications(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📋 Управление анкетами:", reply_markup=get_applications_menu_keyboard())


@router.callback_query(F.data == "admin_app_list")
async def cb_admin_app_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, status, created_at FROM applications ORDER BY created_at DESC"
        )
        applications = await cursor.fetchall()
    if not applications:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_applications"))
        await callback.message.edit_text("📭 Нет поданных заявок.", reply_markup=builder.as_markup())
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for app in applications:
        app_id, user_id, username, status, created_at = app
        status_emoji = "⏳" if status == "pending" else "✅" if status == "approved" else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} @{username} (ID:{user_id})",
            callback_data=f"view_app_{app_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_applications"))
    await callback.message.edit_text("📋 Список заявок (нажмите для просмотра):", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("view_app_"))
async def view_application(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    app_id = int(callback.data.replace("view_app_", ""))
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        app = await cursor.fetchone()
    if not app:
        await callback.answer("Анкета не найдена", show_alert=True)
        return
    (
        _, user_id, username, status, created_at,
        nickname, age, timezone, playtime, create_level,
        create_knowledge, idea, crash, telegram, discord, vk,
    ) = app
    text = (
        f"📋 Анкета #{app_id}\n"
        f"👤 Пользователь: @{username} (ID: {user_id})\n"
        f"📅 Дата: {created_at}\n"
        f"📊 Статус: {status}\n\n"
        f"1️⃣ Никнейм: {nickname}\n"
        f"2️⃣ Возраст: {age}\n"
        f"3️⃣ Часовой пояс: {timezone}\n"
        f"4️⃣ Время в день: {playtime}\n"
        f"5️⃣ Знание Create (оценка): {create_level}/10\n"
        f"6️⃣ Что знает о Create: {create_knowledge}\n"
        f"7️⃣ Идея и роль: {idea}\n"
        f"8️⃣ Действия при краше: {crash}\n"
        f"9️⃣ Telegram: {telegram}\n"
        f"🔟 Discord: {discord}\n"
        f"1️⃣1️⃣ VK: {vk}"
    )
    builder = InlineKeyboardBuilder()
    if status == "pending":
        builder.row(
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_app_{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_app_{app_id}"),
        )
    builder.row(InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_app_list"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "back_to_app_list")
async def back_to_app_list(callback: CallbackQuery):
    await callback.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, status, created_at FROM applications ORDER BY created_at DESC"
        )
        applications = await cursor.fetchall()
    if not applications:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_applications"))
        await callback.message.edit_text("📭 Нет поданных заявок.", reply_markup=builder.as_markup())
        return
    builder = InlineKeyboardBuilder()
    for app in applications:
        app_id, user_id, username, status, created_at = app
        status_emoji = "⏳" if status == "pending" else "✅" if status == "approved" else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} @{username} (ID:{user_id})",
            callback_data=f"view_app_{app_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_applications"))
    await callback.message.edit_text("📋 Список заявок:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("approve_app_"))
async def approve_application(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    app_id = int(callback.data.replace("approve_app_", ""))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE applications SET status = 'approved' WHERE id = ?", (app_id,))
        cursor = await db.execute("SELECT user_id, nickname FROM applications WHERE id = ?", (app_id,))
        app = await cursor.fetchone()
        await db.commit()
    if app:
        user_id, nickname = app
        try:
            await callback.bot.send_message(
                user_id,
                f"✅ Ваша заявка одобрена!\nНикнейм \"{nickname}\" добавлен в вайтлист сервера.\nДобро пожаловать!",
            )
        except Exception:
            pass
    await log_admin_action(callback.from_user.id, "Одобрил заявку", f"Заявка #{app_id}")
    await callback.answer("✅ Заявка одобрена!", show_alert=True)
    await back_to_app_list(callback)


@router.callback_query(F.data.startswith("reject_app_"))
async def reject_application(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    app_id = int(callback.data.replace("reject_app_", ""))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE applications SET status = 'rejected' WHERE id = ?", (app_id,))
        cursor = await db.execute("SELECT user_id FROM applications WHERE id = ?", (app_id,))
        app = await cursor.fetchone()
        await db.commit()
    if app:
        user_id = app[0]
        try:
            await callback.bot.send_message(
                user_id,
                "❌ К сожалению, ваша заявка отклонена. Вы можете подать новую заявку позже.",
            )
        except Exception:
            pass
    await log_admin_action(callback.from_user.id, "Отклонил заявку", f"Заявка #{app_id}")
    await callback.answer("❌ Заявка отклонена.", show_alert=True)
    await back_to_app_list(callback)


@router.callback_query(F.data == "admin_app_manage")
async def cb_admin_app_manage(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.message.delete()
    msg = await callback.message.answer(
        "🗑️ Введите порядковый номер анкеты для удаления (список анкет: нажмите 'Список анкет'):",
        reply_markup=get_back_keyboard("admin_applications"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_application_delete_number)
    await callback.answer()


@router.message(AdminStates.waiting_for_application_delete_number)
async def delete_application(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введите порядковый номер (число).")
        return
    app_number = int(message.text)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM applications ORDER BY id ASC")
        apps = await cursor.fetchall()
        if app_number < 1 or app_number > len(apps):
            await message.answer(f"⚠️ Неверный номер. Всего анкет: {len(apps)}.")
            return
        app_id = apps[app_number - 1][0]
        await db.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        await db.commit()
    await log_admin_action(message.from_user.id, "Удалил анкету", f"Анкета #{app_id}")
    await message.answer(f"🗑️ Анкета #{app_id} удалена.", reply_markup=get_applications_menu_keyboard())
    await state.clear()


# ==================== АДМИНКА: СБОРКА ====================
@router.callback_query(F.data == "admin_assembly")
async def cb_admin_assembly(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📦 Управление ссылками сборки:", reply_markup=get_assembly_admin_keyboard())


@router.callback_query(F.data == "admin_change_cf")
async def cb_admin_change_cf(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("curseforge_link")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"🔗 Текущая ссылка CurseForge:\n{current}\n\nВведите новую ссылку:",
        reply_markup=get_back_keyboard("admin_assembly"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_curseforge_link)
    await callback.answer()


@router.message(AdminStates.waiting_for_curseforge_link)
async def change_curseforge_done(message: Message, state: FSMContext):
    await set_setting("curseforge_link", message.text)
    await log_admin_action(message.from_user.id, "Изменил ссылку CurseForge", message.text)
    await message.answer(
        "✅ Ссылка CurseForge обновлена!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


@router.callback_query(F.data == "admin_change_gd")
async def cb_admin_change_gd(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("google_disk_link")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"💾 Текущая ссылка Google Диск:\n{current}\n\nВведите новую ссылку:",
        reply_markup=get_back_keyboard("admin_assembly"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_google_disk_link)
    await callback.answer()


@router.message(AdminStates.waiting_for_google_disk_link)
async def change_google_disk_done(message: Message, state: FSMContext):
    await set_setting("google_disk_link", message.text)
    await log_admin_action(message.from_user.id, "Изменил ссылку Google Диск", message.text)
    await message.answer(
        "✅ Ссылка Google Диск обновлена!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== АДМИНКА: ИНСТРУКЦИЯ ====================
@router.callback_query(F.data == "admin_instruction")
async def cb_admin_instruction(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📖 Управление инструкцией:", reply_markup=get_instruction_admin_keyboard())


@router.callback_query(F.data == "admin_change_radmin_net")
async def cb_admin_change_radmin_net(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("radmin_network")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"🌐 Текущая сеть Radmin:\n{current}\n\nВведите новое название сети:",
        reply_markup=get_back_keyboard("admin_instruction"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_radmin_network)
    await callback.answer()


@router.message(AdminStates.waiting_for_radmin_network)
async def change_radmin_network_done(message: Message, state: FSMContext):
    await set_setting("radmin_network", message.text)
    await log_admin_action(message.from_user.id, "Изменил сеть Radmin", message.text)
    await message.answer(
        "✅ Сеть Radmin обновлена!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


@router.callback_query(F.data == "admin_change_radmin_pass")
async def cb_admin_change_radmin_pass(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("radmin_password")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"🔑 Текущий пароль Radmin:\n{current}\n\nВведите новый пароль:",
        reply_markup=get_back_keyboard("admin_instruction"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_radmin_password)
    await callback.answer()


@router.message(AdminStates.waiting_for_radmin_password)
async def change_radmin_password_done(message: Message, state: FSMContext):
    await set_setting("radmin_password", message.text)
    await log_admin_action(message.from_user.id, "Изменил пароль Radmin", message.text)
    await message.answer(
        "✅ Пароль Radmin обновлен!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


@router.callback_query(F.data == "admin_change_ip")
async def cb_admin_change_ip(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("server_ip")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"🌍 Текущий IP сервера:\n{current}\n\nВведите новый IP:",
        reply_markup=get_back_keyboard("admin_instruction"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_server_ip)
    await callback.answer()


@router.message(AdminStates.waiting_for_server_ip)
async def change_server_ip_done(message: Message, state: FSMContext):
    await set_setting("server_ip", message.text)
    await log_admin_action(message.from_user.id, "Изменил IP сервера", message.text)
    await message.answer(
        "✅ IP сервера обновлен!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== АДМИНКА: ПРАВИЛА ====================
@router.callback_query(F.data == "admin_rules")
async def cb_admin_rules(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("rules")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"📜 Текущие правила:\n\n{current}\n\nОтправьте новый текст правил:",
        reply_markup=get_back_keyboard("back_to_admin"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_rules)
    await callback.answer()


@router.message(AdminStates.waiting_for_rules)
async def change_rules_done(message: Message, state: FSMContext):
    await set_setting("rules", message.text)
    await log_admin_action(message.from_user.id, "Изменил правила", "Новые правила установлены")
    await message.answer(
        "✅ Правила обновлены!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== АДМИНКА: ОПИСАНИЕ СЕРВЕРА ====================
@router.callback_query(F.data == "admin_description")
async def cb_admin_description(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("description")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"📋 Текущее описание сервера:\n\n{current}\n\nОтправьте новый текст описания:",
        reply_markup=get_back_keyboard("back_to_admin"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_description)
    await callback.answer()


@router.message(AdminStates.waiting_for_description)
async def change_description_done(message: Message, state: FSMContext):
    await set_setting("description", message.text)
    await log_admin_action(message.from_user.id, "Изменил описание сервера", "Новое описание установлено")
    await message.answer(
        "✅ Описание сервера обновлено!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== АДМИНКА: ПОЖЕРТВОВАНИЯ ====================
@router.callback_query(F.data == "admin_donations")
async def cb_admin_donations(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    current = await get_setting("donationalerts_link")
    await callback.message.delete()
    msg = await callback.message.answer(
        f"💳 Текущая ссылка DonationAlerts:\n{current}\n\nВведите новую ссылку:",
        reply_markup=get_back_keyboard("back_to_admin"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_donationalerts_link)
    await callback.answer()


@router.message(AdminStates.waiting_for_donationalerts_link)
async def change_donations_done(message: Message, state: FSMContext):
    await set_setting("donationalerts_link", message.text)
    await log_admin_action(message.from_user.id, "Изменил ссылку DonationAlerts", message.text)
    await message.answer(
        "✅ Ссылка обновлена!",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== АДМИНКА: ОБРАЩЕНИЯ ====================
@router.callback_query(F.data == "admin_tickets")
async def cb_admin_tickets(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📨 Обращения:", reply_markup=get_tickets_menu_keyboard())


@router.callback_query(F.data == "admin_tickets_support")
async def cb_admin_tickets_support(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, message_text, status, created_at FROM tickets WHERE type = 'support' ORDER BY created_at DESC"
        )
        tickets = await cursor.fetchall()
    if not tickets:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
        await callback.message.edit_text("📭 Нет обращений в поддержку.", reply_markup=builder.as_markup())
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        t_id, user_id, username, msg, status, created_at = ticket
        status_emoji = "🟢" if status == "open" else "🔴"
        short_msg = msg[:50] + "..." if len(msg) > 50 else msg
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} @{username}: {short_msg}",
            callback_data=f"view_ticket_{t_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
    await callback.message.edit_text("🆘 Тикеты поддержки:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin_tickets_complaint")
async def cb_admin_tickets_complaint(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, message_text, status, created_at FROM tickets WHERE type = 'complaint' ORDER BY created_at DESC"
        )
        tickets = await cursor.fetchall()
    if not tickets:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
        await callback.message.edit_text("📭 Нет жалоб.", reply_markup=builder.as_markup())
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        t_id, user_id, username, msg, status, created_at = ticket
        status_emoji = "🟢" if status == "open" else "🔴"
        short_msg = msg[:50] + "..." if len(msg) > 50 else msg
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} @{username}: {short_msg}",
            callback_data=f"view_ticket_{t_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
    await callback.message.edit_text("🚨 Тикеты жалоб:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("view_ticket_"))
async def view_ticket(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    t_id = int(callback.data.replace("view_ticket_", ""))
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT * FROM tickets WHERE id = ?", (t_id,))
        ticket = await cursor.fetchone()
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return
    _, user_id, username, t_type, msg, created_at, status, admin_reply = ticket
    text = (
        f"📨 Тикет #{t_id}\n"
        f"👤 От: @{username} (ID: {user_id})\n"
        f"📅 Дата: {created_at}\n"
        f"📊 Статус: {status}\n"
        f"📝 Тип: {t_type}\n\n"
        f"💬 Сообщение:\n{msg}\n\n"
        f"📩 Ответ админа: {admin_reply or 'Нет'}"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✉️ Ответить", callback_data=f"reply_ticket_{user_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"tickets_back_{t_type}"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("tickets_back_"))
async def tickets_back(callback: CallbackQuery):
    await callback.answer()
    t_type = callback.data.replace("tickets_back_", "")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, message_text, status, created_at FROM tickets WHERE type = ? ORDER BY created_at DESC",
            (t_type,),
        )
        tickets = await cursor.fetchall()
    type_name = "поддержки" if t_type == "support" else "жалоб"
    if not tickets:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
        await callback.message.edit_text(f"📭 Нет тикетов {type_name}.", reply_markup=builder.as_markup())
        return
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        t_id, user_id, username, msg, status, created_at = ticket
        status_emoji = "🟢" if status == "open" else "🔴"
        short_msg = msg[:50] + "..." if len(msg) > 50 else msg
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} @{username}: {short_msg}",
            callback_data=f"view_ticket_{t_id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tickets"))
    await callback.message.edit_text(f"📨 Тикеты {type_name}:", reply_markup=builder.as_markup())


# ==================== АДМИНКА: СТАТИСТИКА ====================
@router.callback_query(F.data == "admin_statistics")
async def cb_admin_statistics(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        users_count = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM applications")
        apps_count = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM applications WHERE status = 'approved'")
        apps_approved = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM applications WHERE status = 'rejected'")
        apps_rejected = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM applications WHERE status = 'pending'")
        apps_pending = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM tickets WHERE type = 'support'")
        support_count = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM tickets WHERE type = 'support' AND status = 'open'")
        support_open = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM tickets WHERE type = 'complaint'")
        complaint_count = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM tickets WHERE type = 'complaint' AND status = 'open'")
        complaint_open = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM admin_logs")
        logs_count = (await cursor.fetchone())[0]

    text = (
        "📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {users_count}\n"
        f"📝 Заявок всего: {apps_count}\n"
        f"   ⏳ Ожидают: {apps_pending}\n"
        f"   ✅ Одобрено: {apps_approved}\n"
        f"   ❌ Отклонено: {apps_rejected}\n\n"
        f"📨 Тикеты поддержки: {support_count} (открыто: {support_open})\n"
        f"🚨 Жалобы: {complaint_count} (открыто: {complaint_open})\n\n"
        f"📝 Записей в логах админов: {logs_count}"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👥 Список пользователей", callback_data="users_list"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "users_list")
async def cb_users_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, username, first_name, first_interaction, last_interaction FROM users"
        )
        users = await cursor.fetchall()
    if not users:
        await callback.answer("Нет пользователей", show_alert=True)
        return
    text = "👥 Список пользователей:\n\n"
    for user in users:
        user_id, username, first_name, first_int, last_int = user
        username_str = f"@{username}" if username else first_name or "Неизвестный"
        text += f"👤 {username_str} (ID: {user_id})\n   🟢 Первый вход: {first_int}\n   🔵 Последний вход: {last_int}\n\n"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад к статистике", callback_data="admin_statistics"))
    await callback.message.edit_text(text[:4000], reply_markup=builder.as_markup())
    await callback.answer()


# ==================== АДМИНКА: ЛОГИ ====================
@router.callback_query(F.data == "admin_logs")
async def cb_admin_logs(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT admin_username, action, details, timestamp FROM admin_logs ORDER BY timestamp DESC LIMIT 50"
        )
        logs = await cursor.fetchall()
    if not logs:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
        await callback.message.edit_text("📝 Логов пока нет.", reply_markup=builder.as_markup())
        await callback.answer()
        return
    text = "📝 Последние логи админов:\n\n"
    for log in logs:
        admin_username, action, details, timestamp = log
        text += f"👤 {admin_username} {action}"
        if details:
            text += f" ({details})"
        text += f"\n   🕐 {timestamp}\n\n"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    await callback.message.edit_text(text[:4000], reply_markup=builder.as_markup())
    await callback.answer()


# ==================== АДМИНКА: РАССЫЛКА ====================
@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📢 Рассылка сообщений:", reply_markup=get_broadcast_menu_keyboard())


@router.callback_query(F.data == "broadcast_by_id")
async def cb_broadcast_by_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.message.delete()
    msg = await callback.message.answer(
        "👤 Введите ID пользователя, которому хотите отправить сообщение:",
        reply_markup=get_back_keyboard("admin_broadcast"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.update_data(broadcast_type="by_id")
    await state.set_state(AdminStates.waiting_for_broadcast_id)
    await callback.answer()


@router.callback_query(F.data == "broadcast_all")
async def cb_broadcast_all(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.message.delete()
    msg = await callback.message.answer(
        "👥 Введите сообщение для рассылки всем пользователям:",
        reply_markup=get_back_keyboard("admin_broadcast"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.update_data(broadcast_type="all")
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast_id)
async def process_broadcast_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введите корректный ID (число).")
        return
    target_id = int(message.text)
    await state.update_data(broadcast_target_id=target_id)
    msg = await message.answer(
        f"✉️ Введите сообщение для пользователя ID {target_id}:",
        reply_markup=get_back_keyboard("admin_broadcast"),
    )
    await state.update_data(question_message_id=msg.message_id)
    await state.set_state(AdminStates.waiting_for_broadcast_message)


@router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type")

    if broadcast_type == "by_id":
        target_id = data.get("broadcast_target_id")
        try:
            await message.bot.send_message(target_id, message.text)
            success_msg = f"✅ Сообщение отправлено пользователю ID {target_id}!"
        except Exception as e:
            success_msg = f"❌ Не удалось отправить сообщение: {e}"
        await log_admin_action(message.from_user.id, "Отправил рассылку по ID", f"Пользователь {target_id}")
    elif broadcast_type == "all":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            users = await cursor.fetchall()
        success_count = 0
        fail_count = 0
        for user in users:
            try:
                await message.bot.send_message(user[0], message.text)
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail_count += 1
        success_msg = f"✅ Рассылка завершена!\nУспешно: {success_count}\nНе удалось: {fail_count}"
        await log_admin_action(message.from_user.id, "Отправил рассылку всем", f"Успешно: {success_count}, Не удалось: {fail_count}")

    await message.answer(
        success_msg,
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад в админку", callback_data="back_to_admin")
        ).as_markup(),
    )
    await state.clear()


# ==================== ЗАПУСК БОТА ====================
async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="admin", description="🔐 Админ-панель"),
    ]
    await bot.set_my_commands(commands)


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await set_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())