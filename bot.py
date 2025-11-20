import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Настройки бота
TOKEN = "8328644326:AAHFbb_z9o1A3MsWwZm9eCl1onk30TJNNOc"
ADMIN_CHAT_ID = 7973988177

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            invited_count INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица каналов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            channel_link TEXT
        )
    ''')
    
    # Добавляем админа
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, balance) VALUES (?, ?, ?)', 
                  (ADMIN_CHAT_ID, 'admin', 0))
    
    conn.commit()
    conn.close()

# Функции для работы с базой данных
def get_user(user_id: int):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'user_id': user[0],
            'username': user[1],
            'first_name': user[2],
            'last_name': user[3],
            'balance': user[4],
            'referrer_id': user[5],
            'invited_count': user[6],
            'registered_at': user[7]
        }
    return None

def add_user(user_id: int, username: str, first_name: str, last_name: str, referrer_id: int = None):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, referrer_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, referrer_id))
    
    # Если есть реферер, начисляем бонусы (7 монет рефереру)
    if referrer_id:
        cursor.execute('UPDATE users SET balance = balance + 7, invited_count = invited_count + 1 WHERE user_id = ?', (referrer_id,))
        cursor.execute('UPDATE users SET balance = balance + 5 WHERE user_id = ?', (user_id,))
    
    conn.commit()
    conn.close()

def update_balance(user_id: int, amount: int):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users')
    users = cursor.fetchall()
    conn.close()
    return users

def get_channels():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM channels')
    channels = cursor.fetchall()
    conn.close()
    return channels

def add_channel(channel_id: str, channel_name: str, channel_link: str):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO channels (channel_id, channel_name, channel_link) VALUES (?, ?, ?)', 
                   (channel_id, channel_name, channel_link))
    conn.commit()
    conn.close()

def remove_channel(channel_id: str):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

# Проверка подписки на каналы
async def check_subscriptions(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # Админ всегда имеет доступ
    if user_id == ADMIN_CHAT_ID:
        return True
        
    channels = get_channels()
    
    if not channels:
        return True
    
    for channel in channels:
        channel_id = channel[0]
        try:
            member = await context.bot.get_chat_member(channel_id, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Ошибка проверки подписки на канал {channel_id}: {e}")
            return False
    
    return True

# Клавиатура для подписки
def get_subscription_keyboard():
    channels = get_channels()
    keyboard = []
    
    for channel in channels:
        keyboard.append([InlineKeyboardButton(
            f"📢 Подписаться на {channel[1]}", 
            url=channel[2]
        )])
    
    keyboard.append([InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")])
    return InlineKeyboardMarkup(keyboard)

# Главное меню
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    user_id = update.effective_user.id if update.effective_user else query.from_user.id
    user_data = get_user(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🎁 Вывод брайнротов", callback_data="withdraw_menu")],
        [InlineKeyboardButton("👥 Реферальная система", callback_data="referral_system")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="my_balance")]
    ]
    
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (f"👋 Добро пожаловать!\n\n"
           f"💰 Ваш баланс: {user_data['balance']} монет\n\n"
           f"Выберите действие:")
    
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Проверяем реферальную ссылку
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            # Проверяем, существует ли реферер
            if not get_user(referrer_id) or referrer_id == user_id:
                referrer_id = None
        except ValueError:
            referrer_id = None
    
    # Добавляем пользователя если его нет
    if not get_user(user_id):
        add_user(user_id, user.username, user.first_name, user.last_name, referrer_id)
    
    # Если пользователь - админ, сразу даем доступ
    if user_id == ADMIN_CHAT_ID:
        await show_main_menu(update, context)
        return
    
    # Для обычных пользователей проверяем подписки
    has_access = await check_subscriptions(user_id, context)
    
    if has_access:
        await show_main_menu(update, context)
    else:
        channels = get_channels()
        if channels:
            await update.message.reply_text(
                "❌ Доступ ограничен!\n\n"
                "Для использования бота необходимо подписаться на наши каналы:",
                reply_markup=get_subscription_keyboard()
            )
        else:
            await show_main_menu(update, context)

# Обработка кнопки проверки подписки
async def check_subscription_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Для админа всегда пропускаем
    if user_id == ADMIN_CHAT_ID:
        await show_main_menu(update, context, query=query)
        return
    
    is_subscribed = await check_subscriptions(user_id, context)
    
    if is_subscribed:
        await show_main_menu(update, context, query=query)
    else:
        await query.edit_message_text(
            "❌ Вы еще не подписались на все каналы!\n\n"
            "Пожалуйста, подпишитесь на все каналы ниже:",
            reply_markup=get_subscription_keyboard()
        )

# Меню вывода брайнротов
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = get_user(user_id)
    
    keyboard = [
        [InlineKeyboardButton("Los 67 - 10 монет", callback_data="withdraw_los67")],
        [InlineKeyboardButton("Spooky Grande - 20 монет", callback_data="withdraw_spooky")],
        [InlineKeyboardButton("Dragon Cannelloni - 30 монет", callback_data="withdraw_dragon")],
        [InlineKeyboardButton("strawberry elephant - 80 монет", callback_data="withdraw_strawberry")],
        [InlineKeyboardButton("meowl - 85 монет", callback_data="withdraw_meowl")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎁 Вывод брайнротов\n\n"
        f"💰 Ваш баланс: {user_data['balance']} монет\n\n"
        f"Выберите брайнрот для вывода:",
        reply_markup=reply_markup
    )

# Обработка вывода брайнротов
async def process_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    brainrot_type = query.data.replace('withdraw_', '')
    
    brainrots = {
        'los67': {'name': 'Los 67', 'price': 10},
        'spooky': {'name': 'Spooky Grande', 'price': 20},
        'dragon': {'name': 'Dragon Cannelloni', 'price': 30},
        'strawberry': {'name': 'strawberry elephant', 'price': 80},
        'meowl': {'name': 'meowl', 'price': 85}
    }
    
    selected = brainrots.get(brainrot_type)
    if not selected:
        return
    
    user_data = get_user(user_id)
    balance = user_data['balance']
    
    if balance >= selected['price']:
        # Списание монет
        update_balance(user_id, -selected['price'])
        
        await query.edit_message_text(
            f"🎉 Поздравляем! Вы успешно вывели {selected['name']}!\n\n"
            f"💎 Брайнрот: {selected['name']}\n"
            f"💰 Списано: {selected['price']} монет\n"
            f"💵 Остаток: {balance - selected['price']} монет\n\n"
            f"Свяжитесь с администратором для получения вашего брайнрота."
        )
        
        # Уведомление админа
        try:
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                f"🔄 Новый вывод брайнрота!\n\n"
                f"👤 Пользователь: @{query.from_user.username or 'Нет username'} (ID: {user_id})\n"
                f"🎁 Брайнрот: {selected['name']}\n"
                f"💰 Стоимость: {selected['price']} монет"
            )
        except:
            pass
    else:
        await query.edit_message_text(
            f"❌ Недостаточно монет!\n\n"
            f"💎 Брайнрот: {selected['name']}\n"
            f"💰 Требуется: {selected['price']} монет\n"
            f"💵 Ваш баланс: {balance} монет\n\n"
            f"Приглашайте друзей, чтобы получить больше монет!"
        )

# Реферальная система
async def referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = get_user(user_id)
    
    # Получаем реферальную ссылку
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"👥 Реферальная система\n\n"
        f"🔗 Ваша реферальная ссылка:\n`{referral_link}`\n\n"
        f"📊 Статистика:\n"
        f"• Приглашено друзей: {user_data['invited_count']}\n"
        f"• Доход с рефералов: {user_data['invited_count'] * 7} монет\n\n"
        f"💎 Бонусы:\n"
        f"• Вы получаете: 7 монет за каждого друга\n"
        f"• Друг получает: 5 монет при регистрации\n\n"
        f"Приглашайте друзей и получайте монеты!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Показ баланса
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = get_user(user_id)
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"💰 Ваш баланс: {user_data['balance']} монет\n\n"
        f"💡 Монеты можно получить:\n"
        f"• Приглашая друзей (+7 монет)\n"
        f"• При регистрации по реферальной ссылке (+5 монет)",
        reply_markup=reply_markup
    )

# Админ панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("❌ У вас нет доступа к админ панели!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("💰 Изменить баланс", callback_data="admin_balance")],
        [InlineKeyboardButton("📢 Управление каналами", callback_data="admin_channels")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ Админ панель\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Статистика админа
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = get_all_users()
    total_users = len(users)
    total_balance = sum(user[4] for user in users)
    total_refs = sum(user[6] for user in users)
    channels = get_channels()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"💰 Общий баланс: {total_balance} монет\n"
        f"👥 Всего приглашено: {total_refs} друзей\n"
        f"📢 Каналов для подписки: {len(channels)}",
        reply_markup=reply_markup
    )

# Управление каналами
async def admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    channels = get_channels()
    channels_text = "📢 Текущие каналы:\n\n"
    if channels:
        for i, channel in enumerate(channels, 1):
            channels_text += f"{i}. {channel[1]} ({channel[0]})\n"
    else:
        channels_text += "Каналы не добавлены\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton("➖ Удалить канал", callback_data="remove_channel")],
        [InlineKeyboardButton("🔙 Назад в админку", callback_data="admin_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        channels_text + "\nВыберите действие:",
        reply_markup=reply_markup
    )

# Обработка добавления/удаления каналов
async def channel_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "add_channel":
        context.user_data['awaiting_channel'] = True
        await query.edit_message_text(
            "📝 Отправьте данные канала в формате:\n"
            "`@username Название_канала ссылка`\n\n"
            "Пример: `@mychannel МойКанал https://t.me/mychannel`",
            parse_mode='Markdown'
        )
    elif action == "remove_channel":
        channels = get_channels()
        if not channels:
            await query.edit_message_text("❌ Нет каналов для удаления!")
            return
        
        keyboard = []
        for channel in channels:
            keyboard.append([InlineKeyboardButton(
                f"❌ {channel[1]}", 
                callback_data=f"remove_{channel[0]}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_channels")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Выберите канал для удаления:",
            reply_markup=reply_markup
        )

# Удаление конкретного канала
async def remove_specific_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    channel_id = query.data.replace('remove_', '')
    remove_channel(channel_id)
    
    await query.edit_message_text(f"✅ Канал {channel_id} удален!")
    await admin_channels(update, context)

# Обработка текстовых сообщений для админа
async def handle_admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_CHAT_ID:
        # Для обычных пользователей проверяем подписки при любом сообщении
        user_id = update.message.from_user.id
        is_subscribed = await check_subscriptions(user_id, context)
        
        if not is_subscribed:
            await update.message.reply_text(
                "❌ Доступ ограничен!\n\n"
                "Для использования бота необходимо подписаться на наши каналы:",
                reply_markup=get_subscription_keyboard()
            )
        return
    
    # Код для админа
    text = update.message.text
    
    if context.user_data.get('awaiting_channel'):
        try:
            parts = text.split(' ', 2)
            if len(parts) == 3:
                channel_id, channel_name, channel_link = parts
                add_channel(channel_id, channel_name, channel_link)
                del context.user_data['awaiting_channel']
                await update.message.reply_text(f"✅ Канал {channel_name} добавлен!")
            else:
                await update.message.reply_text("❌ Неверный формат! Используйте: @username Название ссылка")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    elif context.user_data.get('awaiting_balance'):
        try:
            parts = text.split()
            target_user_id = int(parts[0])
            amount = int(parts[1])
            
            update_balance(target_user_id, amount)
            user_data = get_user(target_user_id)
            
            await update.message.reply_text(
                f"✅ Баланс пользователя {target_user_id} изменен!\n"
                f"💰 Новый баланс: {user_data['balance']} монет"
            )
            
            context.user_data['awaiting_balance'] = False
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    elif context.user_data.get('awaiting_broadcast'):
        users = get_all_users()
        success_count = 0
        
        for user in users:
            try:
                await context.bot.send_message(chat_id=user[0], text=text)
                success_count += 1
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user[0]}: {e}")
        
        await update.message.reply_text(
            f"✉️ Рассылка завершена!\n"
            f"✅ Успешно отправлено: {success_count}/{len(users)}"
        )
        
        context.user_data['awaiting_broadcast'] = False

# Обработка callback запросов админа
async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if user_id != ADMIN_CHAT_ID:
        return
    
    if data == "admin_balance":
        context.user_data['awaiting_balance'] = True
        await query.edit_message_text(
            "💰 Изменение баланса\n\n"
            "Отправьте сообщение в формате:\n"
            "`user_id amount`\n\n"
            "Например: `123456789 10`\n"
            "Для добавления монет используйте положительное число\n"
            "Для списания - отрицательное",
            parse_mode='Markdown'
        )
    
    elif data == "admin_broadcast":
        context.user_data['awaiting_broadcast'] = True
        await query.edit_message_text(
            "✉️ Рассылка сообщений\n\n"
            "Отправьте сообщение которое хотите разослать всем пользователям:"
        )

def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    
    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(check_subscription_button, pattern="^check_subscription$"))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(withdraw_menu, pattern="^withdraw_menu$"))
    application.add_handler(CallbackQueryHandler(process_withdraw, pattern="^withdraw_"))
    application.add_handler(CallbackQueryHandler(referral_system, pattern="^referral_system$"))
    application.add_handler(CallbackQueryHandler(show_balance, pattern="^my_balance$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_channels, pattern="^admin_channels$"))
    application.add_handler(CallbackQueryHandler(channel_management, pattern="^(add_channel|remove_channel)$"))
    application.add_handler(CallbackQueryHandler(remove_specific_channel, pattern="^remove_"))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^(admin_balance|admin_broadcast)$"))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_messages))
    
    # Запуск бота
    application.run_polling()
    print("Бот запущен!")

if __name__ == '__main__':
    main()
