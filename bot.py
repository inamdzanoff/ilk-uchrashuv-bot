import os
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# ===== SOZLAMALAR =====
BOT_TOKEN = "8229151254:AAEXHvhQQajyQhRAqYzDPaGwiOQjqnCqxqM"
DATABASE_FILE = "tanishuvlar_bot.db"
# Conversation states
REGISTER_NAME, REGISTER_AGE, REGISTER_GENDER, REGISTER_REGION = range(4)
BROADCAST_PHOTO, BROADCAST_CAPTION = range(4, 6)
# Viloyatlar ro'yxati
REGIONS = [
    "Toshkent", "Samarqand", "Buxoro", "Andijon", "Farg'ona",
    "Namangan", "Qashqadaryo", "Surxondaryo", "Xorazm", "Navoiy",
    "Jizzax", "Sirdaryo", "Qoraqalpog'iston"
]
# Premium narxlari (so'mda)
PREMIUM_PRICES = {
    "1_day": 3000,
    "3_days": 7000,
    "1_week": 15000,
    "1_month": 55000
}
# Referral yulduzlar bilan premium narxlari
STAR_PRICES = {
    "1_day": 10,
    "1_week": 30,
    "1_month": 60
}
# ===== DATABASE FUNKSIYALARI =====
def get_db_connection():
    """Database ulanishini olish"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn
def init_database():
    """Databaseni yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            region TEXT NOT NULL,
            is_searching INTEGER DEFAULT 0,
            current_partner_id INTEGER,
            is_premium INTEGER DEFAULT 0,
            premium_expires_at TEXT,
            stars INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Referral code ustunini qo'shish (agar mavjud bo'lmasa)
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN stars INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN referral_code TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN referred_by INTEGER')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_referral_code ON users(referral_code)')
    except:
        pass

    # Chat sessions jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user2_id INTEGER NOT NULL,
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT,
            ended_by INTEGER,
            FOREIGN KEY (user1_id) REFERENCES users(id),
            FOREIGN KEY (user2_id) REFERENCES users(id)
        )
    ''')
    
    # Payments jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            screenshot_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Bot settings jadvali
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number TEXT DEFAULT '9860 0121 1489 8153',
            card_holder_name TEXT DEFAULT 'Admin',
            price_1_day INTEGER DEFAULT 3000,
            price_3_days INTEGER DEFAULT 7000,
            price_1_week INTEGER DEFAULT 15000,
            price_1_month INTEGER DEFAULT 55000
        )
    ''')
    
    # Default settings qo'shish
    cursor.execute('SELECT COUNT(*) FROM bot_settings')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO bot_settings (card_number, card_holder_name)
            VALUES ('9860 0121 1489 8153', 'Sarvarbek Inomjonov')
        ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")
def generate_referral_code(telegram_id: int) -> str:
    """Foydalanuvchi uchun referral kod yaratish"""
    import hashlib
    hash_object = hashlib.md5(str(telegram_id).encode())
    return hash_object.hexdigest()[:8].upper()
def get_user(telegram_id: int):
    """Foydalanuvchini bazadan olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def get_user_by_id(user_id: int):
    """Foydalanuvchini ID bo'yicha olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def get_user_by_referral_code(referral_code: str):
    """Foydalanuvchini referral kod bo'yicha olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE referral_code = ?', (referral_code.upper(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def create_user(telegram_id: int, username: str, full_name: str, age: int, gender: str, region: str, referred_by: int = None):
    """Yangi foydalanuvchi yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    referral_code = generate_referral_code(telegram_id)
    cursor.execute('''
        INSERT INTO users (telegram_id, username, full_name, age, gender, region, referral_code, referred_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (telegram_id, username, full_name, age, gender, region, referral_code, referred_by))
    conn.commit()
    conn.close()
def update_user(user_id: int, **kwargs):
    """Foydalanuvchini yangilash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    set_clause = ', '.join([f'{key} = ?' for key in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    
    cursor.execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
    conn.commit()
    conn.close()
def add_stars(user_id: int, stars: int):
    """Foydalanuvchiga yulduz qo'shish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET stars = stars + ? WHERE id = ?', (stars, user_id))
    conn.commit()
    conn.close()
def use_stars(user_id: int, stars: int) -> bool:
    """Foydalanuvchidan yulduz ayirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT stars FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] >= stars:
        cursor.execute('UPDATE users SET stars = stars - ? WHERE id = ?', (stars, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False
def increment_referral_count(user_id: int):
    """Referral hisoblagichini oshirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET referral_count = referral_count + 1 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
def get_bot_settings():
    """Bot sozlamalarini olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bot_settings LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def find_searching_user(exclude_user_id: int, gender: str = None):
    """Qidirayotgan foydalanuvchini topish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if gender:
        cursor.execute('''
            SELECT * FROM users 
            WHERE is_searching = 1 AND id != ? AND gender = ?
            LIMIT 1
        ''', (exclude_user_id, gender))
    else:
        cursor.execute('''
            SELECT * FROM users 
            WHERE is_searching = 1 AND id != ?
            LIMIT 1
        ''', (exclude_user_id,))
    
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def create_chat_session(user1_id: int, user2_id: int):
    """Chat sessiyasini yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO chat_sessions (user1_id, user2_id)
        VALUES (?, ?)
    ''', (user1_id, user2_id))
    conn.commit()
    conn.close()
def end_chat_session(user1_id: int, user2_id: int, ended_by: int):
    """Chat sessiyasini tugatish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE chat_sessions 
        SET ended_at = ?, ended_by = ?
        WHERE ((user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?))
        AND ended_at IS NULL
    ''', (datetime.now().isoformat(), ended_by, user1_id, user2_id, user2_id, user1_id))
    conn.commit()
    conn.close()
def create_payment(user_id: int, plan: str, amount: int):
    """To'lov yaratish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments (user_id, plan, amount)
        VALUES (?, ?, ?)
    ''', (user_id, plan, amount))
    payment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return payment_id
def get_pending_payment(user_id: int):
    """Kutilayotgan to'lovni olish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM payments 
        WHERE user_id = ? AND status = 'pending'
        ORDER BY created_at DESC
        LIMIT 1
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
def update_payment(payment_id: int, **kwargs):
    """To'lovni yangilash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    set_clause = ', '.join([f'{key} = ?' for key in kwargs.keys()])
    values = list(kwargs.values()) + [payment_id]
    
    cursor.execute(f'UPDATE payments SET {set_clause} WHERE id = ?', values)
    conn.commit()
    conn.close()
def check_expired_premiums():
    """Muddati o'tgan premiumlarni tekshirish va o'chirish"""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        UPDATE users 
        SET is_premium = 0, premium_expires_at = NULL
        WHERE is_premium = 1 AND premium_expires_at < ?
    ''', (now,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    if affected > 0:
        logger.info(f"Expired {affected} premium subscriptions")
    return affected
# ===== YORDAMCHI FUNKSIYALAR =====
def is_premium(user: dict) -> bool:
    """Foydalanuvchi premiummi tekshirish"""
    if not user or not user.get("is_premium"):
        return False
    expires = user.get("premium_expires_at")
    if expires:
        try:
            expires_dt = datetime.fromisoformat(expires)
            if expires_dt <= datetime.now():
                # Premium muddati tugagan, yangilash
                update_user(user['id'], is_premium=0, premium_expires_at=None)
                return False
            return True
        except Exception:
            return False
    return False
def get_main_keyboard(user: dict):
    """Asosiy klaviatura"""
    premium = is_premium(user)
    
    keyboard = [
        ["🔍 Suhbatdosh izlash"],
        ["👤 Mening profilim", "💎 Premium"],
        ["🌟 Referral"]
    ]
    
    if premium:
        keyboard.insert(1, ["👦 O'g'il izlash", "👧 Qiz izlash"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
# ===== BOT HANDLERLARI =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    # Referral kodni tekshirish
    referral_code = None
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        context.user_data['referral_code'] = referral_code
    
    if user:
        # Premium muddatini tekshirish
        check_expired_premiums()
        user = get_user(telegram_id)  # Yangilangan ma'lumotni olish
        
        await update.message.reply_text(
            f"Salom, {user['full_name']}! 👋\n\nSuhbatdosh izlash uchun tugmani bosing.",
            reply_markup=get_main_keyboard(user)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "🌟 Tanishuvlar botiga xush kelibsiz!\n\n"
            "Ro'yxatdan o'tish uchun ismingizni kiriting:",
            reply_markup=ReplyKeyboardRemove()
        )
        return REGISTER_NAME
async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ism qabul qilish"""
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Yoshingizni kiriting (masalan: 20):")
    return REGISTER_AGE
async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yosh qabul qilish"""
    try:
        age = int(update.message.text)
        if age < 14 or age > 100:
            await update.message.reply_text("Yosh 14 dan 100 gacha bo'lishi kerak. Qaytadan kiriting:")
            return REGISTER_AGE
        context.user_data['age'] = age
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting:")
        return REGISTER_AGE
    
    keyboard = ReplyKeyboardMarkup([["👦 Erkak", "👧 Ayol"]], resize_keyboard=True)
    await update.message.reply_text("Jinsingizni tanlang:", reply_markup=keyboard)
    return REGISTER_GENDER
async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jins qabul qilish"""
    text = update.message.text
    if "Erkak" in text:
        context.user_data['gender'] = "male"
    elif "Ayol" in text:
        context.user_data['gender'] = "female"
    else:
        await update.message.reply_text("Iltimos, tugmalardan birini tanlang:")
        return REGISTER_GENDER
    
    keyboard = ReplyKeyboardMarkup(
        [[r] for r in REGIONS[:7]] + [[r] for r in REGIONS[7:]],
        resize_keyboard=True
    )
    await update.message.reply_text("Viloyatingizni tanlang:", reply_markup=keyboard)
    return REGISTER_REGION
async def register_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Viloyat qabul qilish va ro'yxatdan o'tkazish"""
    region = update.message.text
    if region not in REGIONS:
        await update.message.reply_text("Iltimos, ro'yxatdan viloyat tanlang:")
        return REGISTER_REGION
    
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    
    # Referral tekshirish
    referred_by = None
    referral_code = context.user_data.get('referral_code')
    if referral_code:
        referrer = get_user_by_referral_code(referral_code)
        if referrer and referrer['telegram_id'] != telegram_id:
            referred_by = referrer['id']
            # Referrerga 3 yulduz qo'shish
            add_stars(referrer['id'], 3)
            increment_referral_count(referrer['id'])
            # Referrerga xabar yuborish
            try:
                await context.bot.send_message(
                    chat_id=referrer['telegram_id'],
                    text=f"🎉 Tabriklaymiz! Sizning referral havolangiz orqali yangi foydalanuvchi qo'shildi!\n\n"
                         f"⭐ +3 yulduz qo'shildi!\n"
                         f"💫 Jami yulduzlaringiz: {referrer['stars'] + 3}"
                )
            except:
                pass
    
    try:
        create_user(
            telegram_id=telegram_id,
            username=username,
            full_name=context.user_data['full_name'],
            age=context.user_data['age'],
            gender=context.user_data['gender'],
            region=region,
            referred_by=referred_by
        )
        user = get_user(telegram_id)
        
        welcome_msg = (
            f"✅ Ro'yxatdan o'tdingiz!\n\n"
            f"👤 Ism: {user['full_name']}\n"
            f"🎂 Yosh: {user['age']}\n"
            f"📍 Viloyat: {user['region']}\n\n"
            f"Endi suhbatdosh izlashingiz mumkin!"
        )
        
        if referred_by:
            welcome_msg += "\n\n🎁 Siz referral orqali keldingiz!"
        
        await update.message.reply_text(
            welcome_msg,
            reply_markup=get_main_keyboard(user)
        )
    except Exception as e:
        logger.error(f"Registration error: {e}")
        await update.message.reply_text("Xatolik yuz berdi. Qaytadan urinib ko'ring: /start")
    
    return ConversationHandler.END
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Referral menyusi"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    # Referral kodni yaratish (agar mavjud bo'lmasa)
    if not user.get('referral_code'):
        referral_code = generate_referral_code(telegram_id)
        update_user(user['id'], referral_code=referral_code)
        user['referral_code'] = referral_code
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌟 Yulduzlar bilan premium olish", callback_data="star_premium")]
    ])
    
    await update.message.reply_text(
        f"🌟 <b>REFERRAL TIZIMI</b>\n\n"
        f"📊 Sizning statistikangiz:\n"
        f"⭐ Yulduzlar: <b>{user.get('stars', 0)}</b>\n"
        f"👥 Taklif qilganlar: <b>{user.get('referral_count', 0)}</b>\n\n"
        f"🔗 Sizning referral havolangiz:\n"
        f"<code>{referral_link}</code>\n\n"
        f"📌 Qanday ishlaydi:\n"
        f"1️⃣ Havolani do'stlaringizga yuboring\n"
        f"2️⃣ Har bir ro'yxatdan o'tgan do'st uchun <b>3 yulduz</b> olasiz\n"
        f"3️⃣ Yulduzlar bilan premium sotib oling!\n\n"
        f"💎 <b>Premium narxlari (yulduzlarda):</b>\n"
        f"• 1 kun - 10 ⭐\n"
        f"• 1 hafta - 30 ⭐\n"
        f"• 1 oy - 60 ⭐",
        parse_mode="HTML",
        reply_markup=keyboard
    )
async def star_premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yulduzlar bilan premium olish menyusi"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = get_user(telegram_id)
    
    if not user:
        await query.edit_message_text("Avval ro'yxatdan o'ting: /start")
        return
    
    stars = user.get('stars', 0)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"1 kun - 10 ⭐ {'✅' if stars >= 10 else '❌'}", callback_data="buy_star_1_day")],
        [InlineKeyboardButton(f"1 hafta - 30 ⭐ {'✅' if stars >= 30 else '❌'}", callback_data="buy_star_1_week")],
        [InlineKeyboardButton(f"1 oy - 60 ⭐ {'✅' if stars >= 60 else '❌'}", callback_data="buy_star_1_month")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_referral")]
    ])
    
    await query.edit_message_text(
        f"💎 <b>YULDUZLAR BILAN PREMIUM</b>\n\n"
        f"⭐ Sizning yulduzlaringiz: <b>{stars}</b>\n\n"
        f"Quyidagi tariflardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
async def buy_star_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yulduzlar bilan premium sotib olish"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = get_user(telegram_id)
    
    if not user:
        await query.edit_message_text("Avval ro'yxatdan o'ting: /start")
        return
    
    plan = query.data.replace("buy_star_", "")
    star_cost = STAR_PRICES.get(plan, 0)
    
    if user.get('stars', 0) < star_cost:
        await query.answer(f"Sizda yetarli yulduz yo'q! Kerak: {star_cost} ⭐", show_alert=True)
        return
    
    days_map = {"1_day": 1, "1_week": 7, "1_month": 30}
    days = days_map.get(plan)
    
    if not days:
        await query.answer("Xatolik yuz berdi!", show_alert=True)
        return
    
    # Yulduzlarni ayirish
    if use_stars(user['id'], star_cost):
        # Premiumni faollashtirish
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        update_user(user['id'], is_premium=1, premium_expires_at=expires_at)
        
        user = get_user(telegram_id)
        
        await query.edit_message_text(
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"💎 Premium {days} kunga faollashtirildi!\n"
            f"⏰ Amal qilish: {datetime.fromisoformat(expires_at).strftime('%d.%m.%Y %H:%M')}\n\n"
            f"⭐ Qolgan yulduzlaringiz: {user.get('stars', 0)}",
            parse_mode="HTML"
        )
        
        # Asosiy klaviaturani yangilash
        await context.bot.send_message(
            chat_id=telegram_id,
            text="Endi premium imkoniyatlardan foydalanishingiz mumkin!",
            reply_markup=get_main_keyboard(user)
        )
    else:
        await query.answer("Xatolik yuz berdi!", show_alert=True)
async def back_to_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Referral menyusiga qaytish"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = get_user(telegram_id)
    
    if not user:
        return
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌟 Yulduzlar bilan premium olish", callback_data="star_premium")]
    ])
    
    await query.edit_message_text(
        f"🌟 <b>REFERRAL TIZIMI</b>\n\n"
        f"📊 Sizning statistikangiz:\n"
        f"⭐ Yulduzlar: <b>{user.get('stars', 0)}</b>\n"
        f"👥 Taklif qilganlar: <b>{user.get('referral_count', 0)}</b>\n\n"
        f"🔗 Sizning referral havolangiz:\n"
        f"<code>{referral_link}</code>\n\n"
        f"📌 Qanday ishlaydi:\n"
        f"1️⃣ Havolani do'stlaringizga yuboring\n"
        f"2️⃣ Har bir ro'yxatdan o'tgan do'st uchun <b>3 yulduz</b> olasiz\n"
        f"3️⃣ Yulduzlar bilan premium sotib oling!\n\n"
        f"💎 <b>Premium narxlari (yulduzlarda):</b>\n"
        f"• 1 kun - 10 ⭐\n"
        f"• 1 hafta - 30 ⭐\n"
        f"• 1 oy - 60 ⭐",
        parse_mode="HTML",
        reply_markup=keyboard
    )
async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbatdosh izlash"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    # Premium muddatini tekshirish
    check_expired_premiums()
    user = get_user(telegram_id)
    
    # Foydalanuvchini qidiruv rejimiga o'tkazish
    update_user(user['id'], is_searching=1, current_partner_id=None)
    
    # Boshqa qidiruvchini topish
    partner = find_searching_user(user['id'])
    
    if partner:
        # Ikkalasini ham chat holatiga o'tkazish
        update_user(user['id'], is_searching=0, current_partner_id=partner['id'])
        update_user(partner['id'], is_searching=0, current_partner_id=user['id'])
        
        # Chat sessiyasini yaratish
        create_chat_session(user['id'], partner['id'])
        
        stop_keyboard = ReplyKeyboardMarkup([["🛑 Suhbatni tugatish"]], resize_keyboard=True)
        
        # Foydalanuvchiga
        user_msg = "✅ Suhbatdosh topildi!\n\n"
        if is_premium(user):
            user_msg += f"👤 Ism: {partner['full_name']}\n🎂 Yosh: {partner['age']}\n📍 Viloyat: {partner['region']}\n\n"
        user_msg += "Xabar yozing, u sizning suhbatdoshingizga yuboriladi.\n\n⚠️ Faqat matn xabarlari yuboriladi."
        
        await update.message.reply_text(user_msg, reply_markup=stop_keyboard)
        
        # Partnerga
        partner_user = get_user(partner['telegram_id'])
        partner_msg = "✅ Suhbatdosh topildi!\n\n"
        if is_premium(partner_user):
            partner_msg += f"👤 Ism: {user['full_name']}\n🎂 Yosh: {user['age']}\n📍 Viloyat: {user['region']}\n\n"
        partner_msg += "Xabar yozing, u sizning suhbatdoshingizga yuboriladi.\n\n⚠️ Faqat matn xabarlari yuboriladi."
        
        await context.bot.send_message(
            chat_id=partner['telegram_id'],
            text=partner_msg,
            reply_markup=stop_keyboard
        )
    else:
        await update.message.reply_text(
            "🔍 Suhbatdosh izlanmoqda...\n\n"
            "Kutib turing, tez orada topiladi!",
            reply_markup=ReplyKeyboardMarkup([["❌ Qidiruvni bekor qilish"]], resize_keyboard=True)
        )
async def search_by_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jins bo'yicha qidirish (faqat premium)"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    # Premium muddatini tekshirish
    check_expired_premiums()
    user = get_user(telegram_id)
    
    if not is_premium(user):
        await update.message.reply_text(
            "⭐ Bu funksiya faqat Premium foydalanuvchilar uchun!\n\n"
            "Premium sotib olish uchun 💎 Premium tugmasini bosing."
        )
        return
    
    text = update.message.text
    target_gender = "male" if "O'g'il" in text else "female"
    
    # Foydalanuvchini qidiruv rejimiga o'tkazish
    update_user(user['id'], is_searching=1, current_partner_id=None)
    
    # Jins bo'yicha qidirish
    partner = find_searching_user(user['id'], target_gender)
    
    if partner:
        # Ikkalasini ham chat holatiga o'tkazish
        update_user(user['id'], is_searching=0, current_partner_id=partner['id'])
        update_user(partner['id'], is_searching=0, current_partner_id=user['id'])
        
        # Chat sessiyasini yaratish
        create_chat_session(user['id'], partner['id'])
        
        stop_keyboard = ReplyKeyboardMarkup([["🛑 Suhbatni tugatish"]], resize_keyboard=True)
        
        await update.message.reply_text(
            f"✅ Suhbatdosh topildi!\n\n"
            f"👤 Ism: {partner['full_name']}\n"
            f"🎂 Yosh: {partner['age']}\n"
            f"📍 Viloyat: {partner['region']}\n\n"
            "Xabar yozing!\n\n⚠️ Faqat matn xabarlari yuboriladi.",
            reply_markup=stop_keyboard
        )
        
        partner_user = get_user(partner['telegram_id'])
        partner_msg = "✅ Suhbatdosh topildi!\n\n"
        if is_premium(partner_user):
            partner_msg += f"👤 Ism: {user['full_name']}\n🎂 Yosh: {user['age']}\n📍 Viloyat: {user['region']}\n\n"
        partner_msg += "Xabar yozing!\n\n⚠️ Faqat matn xabarlari yuboriladi."
        
        await context.bot.send_message(
            chat_id=partner['telegram_id'],
            text=partner_msg,
            reply_markup=stop_keyboard
        )
    else:
        gender_text = "o'g'il bolalar" if target_gender == "male" else "qiz bolalar"
        await update.message.reply_text(
            f"🔍 {gender_text.capitalize()} orasida izlanmoqda...\n\n"
            "Kutib turing!",
            reply_markup=ReplyKeyboardMarkup([["❌ Qidiruvni bekor qilish"]], resize_keyboard=True)
        )
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suhbatni tugatish"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        return
    
    partner_id = user.get('current_partner_id')
    
    if partner_id:
        partner = get_user_by_id(partner_id)
        
        if partner:
            # Chat sessiyasini yopish
            end_chat_session(user['id'], partner_id, user['id'])
            
            # Ikkalasini ham bo'shatish
            update_user(user['id'], is_searching=0, current_partner_id=None)
            update_user(partner_id, is_searching=0, current_partner_id=None)
            
            # Partnerga xabar
            partner_user = get_user(partner['telegram_id'])
            await context.bot.send_message(
                chat_id=partner['telegram_id'],
                text="😔 Suhbatdosh suhbatni tugatdi.",
                reply_markup=get_main_keyboard(partner_user)
            )
    
    # Qidiruvni ham bekor qilish
    update_user(user['id'], is_searching=0, current_partner_id=None)
    
    user = get_user(telegram_id)
    await update.message.reply_text(
        "✅ Suhbat tugatildi.",
        reply_markup=get_main_keyboard(user)
    )
async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qidiruvni bekor qilish"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if user:
        update_user(user['id'], is_searching=0)
        user = get_user(telegram_id)
        await update.message.reply_text(
            "❌ Qidiruv bekor qilindi.",
            reply_markup=get_main_keyboard(user)
        )
async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profil ko'rish"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    # Premium muddatini tekshirish
    check_expired_premiums()
    user = get_user(telegram_id)
    
    premium_status = "✅ Premium" if is_premium(user) else "❌ Oddiy"
    expires = ""
    if user.get('premium_expires_at') and is_premium(user):
        try:
            expires_dt = datetime.fromisoformat(user['premium_expires_at'])
            expires = f"\n⏰ Amal qilish: {expires_dt.strftime('%d.%m.%Y %H:%M')}"
        except Exception:
            pass
    
    await update.message.reply_text(
        f"👤 Sizning profilingiz:\n\n"
        f"📝 Ism: {user['full_name']}\n"
        f"🎂 Yosh: {user['age']}\n"
        f"👤 Jins: {'Erkak' if user['gender'] == 'male' else 'Ayol'}\n"
        f"📍 Viloyat: {user['region']}\n"
        f"⭐ Yulduzlar: {user.get('stars', 0)}\n"
        f"⭐ Status: {premium_status}{expires}"
    )
async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium menyu"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    # Premium muddatini tekshirish
    check_expired_premiums()
    user = get_user(telegram_id)
    
    settings = get_bot_settings()
    
    if is_premium(user):
        try:
            expires_dt = datetime.fromisoformat(user['premium_expires_at'])
            await update.message.reply_text(
                f"⭐ Siz Premium foydalanuvchisiz!\n\n"
                f"⏰ Amal qilish muddati: {expires_dt.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Premium imkoniyatlari:\n"
                f"✅ Suhbatdosh haqida ma'lumot (ism, yosh, viloyat)\n"
                f"✅ Jins bo'yicha qidirish"
            )
        except Exception:
            await update.message.reply_text("⭐ Siz Premium foydalanuvchisiz!")
    else:
        prices = {
            'price_1_day': settings.get('price_1_day', 3000) if settings else 3000,
            'price_3_days': settings.get('price_3_days', 7000) if settings else 7000,
            'price_1_week': settings.get('price_1_week', 15000) if settings else 15000,
            'price_1_month': settings.get('price_1_month', 55000) if settings else 55000,
        }
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 kun - {prices['price_1_day']} so'm", callback_data="buy_1_day")],
            [InlineKeyboardButton(f"3 kun - {prices['price_3_days']} so'm", callback_data="buy_3_days")],
            [InlineKeyboardButton(f"1 hafta - {prices['price_1_week']} so'm", callback_data="buy_1_week")],
            [InlineKeyboardButton(f"1 oy - {prices['price_1_month']} so'm", callback_data="buy_1_month")],
        ])
        
        await update.message.reply_text(
            "⭐ Premium imkoniyatlari:\n\n"
            "✅ Suhbatdosh haqida ma'lumot (ism, yosh, viloyat)\n"
            "✅ Jins bo'yicha qidirish (o'g'il/qiz)\n\n"
            "💎 Narxlar:",
            reply_markup=keyboard
        )
async def buy_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Premium sotib olish"""
    query = update.callback_query
    await query.answer()
    
    telegram_id = query.from_user.id
    user = get_user(telegram_id)
    
    if not user:
        await query.edit_message_text("Avval ro'yxatdan o'ting: /start")
        return
    
    plan = query.data.replace("buy_", "")
    settings = get_bot_settings()
    
    prices = {
        "1_day": settings.get('price_1_day', 3000) if settings else 3000,
        "3_days": settings.get('price_3_days', 7000) if settings else 7000,
        "1_week": settings.get('price_1_week', 15000) if settings else 15000,
        "1_month": settings.get('price_1_month', 55000) if settings else 55000,
    }
    
    amount = prices.get(plan, 0)
    card_number = settings.get('card_number', '9860 0121 1489 8153') if settings else '9860 0121 1489 8153'
    card_holder = settings.get('card_holder_name', 'Admin') if settings else 'Admin'
    
    # To'lov yaratish
    create_payment(user['id'], plan, amount)
    
    plan_names = {
        "1_day": "1 kun",
        "3_days": "3 kun",
        "1_week": "1 hafta",
        "1_month": "1 oy"
    }
    
    await query.edit_message_text(
        f"💳 To'lov ma'lumotlari:\n\n"
        f"📦 Tarif: {plan_names.get(plan, plan)}\n"
        f"💰 Summa: {amount} so'm\n\n"
        f"💳 Karta raqami:\n`{card_number}`\n"
        f"👤 Egasi: {card_holder}\n\n"
        f"To'lovni amalga oshiring va screenshotini yuboring.",
        parse_mode='Markdown'
    )
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Screenshot qabul qilish (faqat to'lov uchun)"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        return
    
    # Agar chatda bo'lsa, rasm yuborishga ruxsat yo'q
    if user.get('current_partner_id'):
        await update.message.reply_text(
            "⚠️ Suhbatda rasm yuborish mumkin emas!\n"
            "Faqat matn xabarlari yuboriladi."
        )
        return
    
    # Oxirgi pending to'lovni topish
    payment = get_pending_payment(user['id'])
    
    if payment:
        # Rasmni saqlash
        photo = update.message.photo[-1]
        file = await photo.get_file()
        file_url = file.file_path
        
        update_payment(payment['id'], screenshot_url=file_url)
        
        await update.message.reply_text(
            "✅ Screenshot qabul qilindi!\n\n"
            "Admin tekshirgandan so'ng Premium faollashtiriladi.\n"
            "Odatda bu 1-24 soat davom etadi.",
            reply_markup=get_main_keyboard(user)
        )
async def handle_media_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chatda media yuborishga ruxsat bermash"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        return
    
    if user.get('current_partner_id'):
        await update.message.reply_text(
            "⚠️ Suhbatda media yuborish mumkin emas!\n"
            "Faqat matn xabarlari yuboriladi."
        )
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xabarlarni forward qilish"""
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    
    if not user:
        await update.message.reply_text("Avval ro'yxatdan o'ting: /start")
        return
    
    text = update.message.text
    
    # Tugmalarni tekshirish
    if text == "🔍 Suhbatdosh izlash":
        await search_partner(update, context)
        return
    elif text in ["👦 O'g'il izlash", "👧 Qiz izlash"]:
        await search_by_gender(update, context)
        return
    elif text == "👤 Mening profilim":
        await my_profile(update, context)
        return
    elif text == "💎 Premium":
        await premium_menu(update, context)
        return
    elif text == "🌟 Referral":
        await referral_menu(update, context)
        return
    elif text == "🛑 Suhbatni tugatish":
        await stop_chat(update, context)
        return
    elif text == "❌ Qidiruvni bekor qilish":
        await cancel_search(update, context)
        return
    
    # Agar partner bilan chatda bo'lsa
    if user.get('current_partner_id'):
        partner = get_user_by_id(user['current_partner_id'])
        if partner:
            await context.bot.send_message(
                chat_id=partner['telegram_id'],
                text=text
            )
# ===== ADMIN SOZLAMALARI =====
ADMIN_IDS = [1652304805]  # O'zingizning telegram ID larni qo'shing
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
# ===== ADMIN BUYRUQLARI =====
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 /stats - Umumiy statistika"""
    if not is_admin(update.effective_user.id):
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1 AND premium_expires_at > ?", 
              (datetime.now().isoformat(),))
    premium_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_searching = 1")
    searching = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM users WHERE current_partner_id IS NOT NULL")
    chatting = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    pending_payments = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments WHERE status = 'approved'")
    approved_payments = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'")
    total_income = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM chat_sessions")
    total_chats = c.fetchone()[0]
    
    c.execute("SELECT SUM(stars) FROM users")
    total_stars = c.fetchone()[0] or 0
    
    c.execute("SELECT SUM(referral_count) FROM users")
    total_referrals = c.fetchone()[0] or 0
    
    # Bugungi statistika
    today = datetime.now().date().isoformat()
    c.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?", (today,))
    today_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments WHERE status = 'approved' AND DATE(created_at) = ?", (today,))
    today_payments = c.fetchone()[0]
    
    conn.close()
    
    await update.message.reply_text(
        f"📊 <b>BOT STATISTIKASI</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"➕ Bugun qo'shilgan: <b>{today_users}</b>\n\n"
        f"💎 Premium foydalanuvchilar: <b>{premium_users}</b>\n"
        f"🔍 Hozir qidirayotgan: <b>{searching}</b>\n"
        f"💬 Hozir suhbatda: <b>{chatting // 2}</b> juft\n\n"
        f"💳 Kutilayotgan to'lovlar: <b>{pending_payments}</b>\n"
        f"✅ Tasdiqlangan to'lovlar: <b>{approved_payments}</b>\n"
        f"💰 Jami daromad: <b>{total_income:,}</b> so'm\n\n"
        f"⭐ Jami yulduzlar: <b>{total_stars}</b>\n"
        f"👥 Jami referrallar: <b>{total_referrals}</b>\n\n"
        f"📈 Jami suhbatlar: <b>{total_chats}</b>",
        parse_mode="HTML"
    )
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """👥 /users - Foydalanuvchilar ro'yxati"""
    if not is_admin(update.effective_user.id):
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Oxirgi 20 ta foydalanuvchi
    c.execute("""
        SELECT telegram_id, full_name, age, gender, region, is_premium, stars, referral_count, created_at 
        FROM users 
        ORDER BY created_at DESC 
        LIMIT 20
    """)
    users = c.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("👥 Foydalanuvchilar yo'q")
        return
    
    text = "👥 <b>OXIRGI 20 FOYDALANUVCHI:</b>\n\n"
    for u in users:
        gender = "👦" if u['gender'] == 'male' else "👧"
        premium = "💎" if u['is_premium'] else ""
        text += f"{gender} {u['full_name']}, {u['age']} yosh {premium}\n"
        text += f"   ⭐{u['stars'] or 0} 👥{u['referral_count'] or 0} ID: <code>{u['telegram_id']}</code>\n\n"
    
    await update.message.reply_text(text, parse_mode="HTML")
async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """💳 /payments - Kutilayotgan to'lovlar"""
    if not is_admin(update.effective_user.id):
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("""
        SELECT p.id, p.plan, p.amount, p.screenshot_url, p.created_at,
               u.telegram_id, u.full_name, u.username
        FROM payments p
        JOIN users u ON u.id = p.user_id
        WHERE p.status = 'pending'
        ORDER BY p.created_at DESC
    """)
    payments = c.fetchall()
    conn.close()
    
    if not payments:
        await update.message.reply_text("✅ Kutilayotgan to'lovlar yo'q!")
        return
    
    plan_names = {"1_day": "1 kun", "3_days": "3 kun", "1_week": "1 hafta", "1_month": "1 oy"}
    
    for p in payments:
        text = (
            f"💳 <b>TO'LOV #{p['id']}</b>\n\n"
            f"👤 Ism: {p['full_name']}\n"
            f"🆔 Telegram ID: <code>{p['telegram_id']}</code>\n"
            f"📦 Tarif: {plan_names.get(p['plan'], p['plan'])}\n"
            f"💰 Summa: {p['amount']:,} so'm\n"
            f"📅 Vaqt: {p['created_at']}\n\n"
            f"Tasdiqlash: /approve {p['telegram_id']} {p['plan']}"
        )
        
        if p['screenshot_url']:
            try:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=p['screenshot_url'],
                    caption=text,
                    parse_mode="HTML"
                )
            except:
                await update.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text + "\n\n⚠️ Screenshot yuklanmagan!", parse_mode="HTML")
async def admin_approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✅ /approve <telegram_id> <plan> - To'lovni tasdiqlash"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Foydalanish: /approve <telegram_id> <plan>\n\n"
                "Plan: 1_day, 3_days, 1_week, 1_month"
            )
            return
        
        user_telegram_id = int(args[0])
        plan = args[1]
        
        days_map = {"1_day": 1, "3_days": 3, "1_week": 7, "1_month": 30}
        days = days_map.get(plan)
        
        if not days:
            await update.message.reply_text("❌ Noto'g'ri plan! (1_day, 3_days, 1_week, 1_month)")
            return
        
        user = get_user(user_telegram_id)
        if not user:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
            return
        
        # Premiumni faollashtirish
        expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        update_user(user['id'], is_premium=1, premium_expires_at=expires_at)
        
        # To'lovni yangilash
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            UPDATE payments SET status = 'approved' 
            WHERE user_id = ? AND status = 'pending'
        """, (user['id'],))
        conn.commit()
        conn.close()
        
        # Foydalanuvchiga xabar
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"🎉 Tabriklaymiz!\n\n"
                 f"💎 Premium {days} kunga faollashtirildi!\n"
                 f"⏰ Amal qilish: {datetime.fromisoformat(expires_at).strftime('%d.%m.%Y %H:%M')}",
            reply_markup=get_main_keyboard(get_user(user_telegram_id))
        )
        
        await update.message.reply_text(f"✅ {user['full_name']} uchun {days} kunlik premium faollashtirildi!")
        
    except ValueError:
        await update.message.reply_text("❌ Telegram ID raqam bo'lishi kerak!")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
async def admin_remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ /removepremium <telegram_id> - Premiumni olib tashlash"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        args = context.args
        if len(args) < 1:
            await update.message.reply_text("❌ Foydalanish: /removepremium <telegram_id>")
            return
        
        user_telegram_id = int(args[0])
        
        user = get_user(user_telegram_id)
        if not user:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
            return
        
        if not user.get('is_premium'):
            await update.message.reply_text("❌ Bu foydalanuvchi premium emas!")
            return
        
        # Premiumni olib tashlash
        update_user(user['id'], is_premium=0, premium_expires_at=None)
        
        # Foydalanuvchiga xabar
        try:
            await context.bot.send_message(
                chat_id=user_telegram_id,
                text="⚠️ Sizning Premium obunangiz bekor qilindi.",
                reply_markup=get_main_keyboard(get_user(user_telegram_id))
            )
        except:
            pass
        
        await update.message.reply_text(f"✅ {user['full_name']} dan premium olib tashlandi!")
        
    except ValueError:
        await update.message.reply_text("❌ Telegram ID raqam bo'lishi kerak!")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
async def admin_reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ /reject <telegram_id> <sabab> - To'lovni rad etish"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        args = context.args
        if len(args) < 1:
            await update.message.reply_text("❌ Foydalanish: /reject <telegram_id> [sabab]")
            return
        
        user_telegram_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "To'lov tasdiqlanmadi"
        
        user = get_user(user_telegram_id)
        if not user:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
            return
        
        # To'lovni rad etish
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            UPDATE payments SET status = 'rejected' 
            WHERE user_id = ? AND status = 'pending'
        """, (user['id'],))
        conn.commit()
        conn.close()
        
        # Foydalanuvchiga xabar
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"❌ To'lov rad etildi\n\nSabab: {reason}\n\n"
                 f"Iltimos, qaytadan urinib ko'ring yoki admin bilan bog'laning."
        )
        
        await update.message.reply_text(f"❌ {user['full_name']} to'lovi rad etildi!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
# Broadcast uchun kontekst saqlash
broadcast_data = {}
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 /broadcast - Hammaga xabar yuborish (yangi usul)"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📸 Habarni yuboring:\n\n"
        "Rasm yuklang (izoh bilan yoki izohsiz) yoki faqat matn yuboring.\n\n"
        "Bekor qilish: /cancel"
    )
    return BROADCAST_PHOTO
async def admin_broadcast_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast uchun rasm va caption qabul qilish"""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    
    if update.message.photo:
        # Rasm yuklandi
        photo = update.message.photo[-1]
        caption = update.message.caption or ""
        
        broadcast_data[user_id] = {
            'type': 'photo',
            'photo_id': photo.file_id,
            'caption': caption
        }
        
        # Hammaga yuborish
        return await send_broadcast(update, context, broadcast_data[user_id])
        
    elif update.message.text:
        # Faqat matn
        if update.message.text == "/cancel":
            await update.message.reply_text("❌ Broadcast bekor qilindi.")
            return ConversationHandler.END
        
        broadcast_data[user_id] = {
            'type': 'text',
            'text': update.message.text
        }
        
        # Hammaga yuborish
        return await send_broadcast(update, context, broadcast_data[user_id])
    
    await update.message.reply_text("❌ Rasm yoki matn yuboring!")
    return BROADCAST_PHOTO
async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict):
    """Broadcast yuborish"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM users")
    users = c.fetchall()
    conn.close()
    
    success = 0
    failed = 0
    
    await update.message.reply_text(f"📢 {len(users)} ta foydalanuvchiga yuborilmoqda...")
    
    for user in users:
        try:
            if data['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=user['telegram_id'],
                    photo=data['photo_id'],
                    caption=data.get('caption', ''),
                    parse_mode="HTML"
                )
            else:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=data['text'],
                    parse_mode="HTML"
                )
            success += 1
        except Exception:
            failed += 1
    
    await update.message.reply_text(
        f"✅ Yuborildi: {success}\n❌ Xato: {failed}"
    )
    return ConversationHandler.END
async def admin_broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast bekor qilish"""
    await update.message.reply_text("❌ Broadcast bekor qilindi.")
    return ConversationHandler.END
async def admin_setcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """💳 /setcard <karta_raqami> - Karta raqamini o'zgartirish"""
    if not is_admin(update.effective_user.id):
        return
    
    card = " ".join(context.args)
    if not card:
        await update.message.reply_text("❌ Foydalanish: /setcard <karta_raqami>")
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_settings SET card_number = ?", (card,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Karta raqami o'zgartirildi:\n<code>{card}</code>", parse_mode="HTML")
async def admin_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """💰 /setprice <plan> <narx> - Narxni o'zgartirish"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Foydalanish: /setprice <plan> <narx>\n\n"
                "Plan: 1_day, 3_days, 1_week, 1_month"
            )
            return
        
        plan = args[0]
        price = int(args[1])
        
        plan_columns = {
            "1_day": "price_1_day",
            "3_days": "price_3_days", 
            "1_week": "price_1_week",
            "1_month": "price_1_month"
        }
        
        column = plan_columns.get(plan)
        if not column:
            await update.message.reply_text("❌ Noto'g'ri plan!")
            return
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(f"UPDATE bot_settings SET {column} = ?", (price,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ {plan} narxi o'zgartirildi: {price:,} so'm")
        
    except ValueError:
        await update.message.reply_text("❌ Narx raqam bo'lishi kerak!")
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🚫 /ban <telegram_id> - Foydalanuvchini bloklash"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        user_telegram_id = int(context.args[0])
        user = get_user(user_telegram_id)
        
        if not user:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
            return
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE telegram_id = ?", (user_telegram_id,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"🚫 {user['full_name']} bloklandi va o'chirildi!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
async def admin_premium_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """💎 /premiums - Premium foydalanuvchilar"""
    if not is_admin(update.effective_user.id):
        return
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT telegram_id, full_name, premium_expires_at 
        FROM users 
        WHERE is_premium = 1 AND premium_expires_at > ?
        ORDER BY premium_expires_at DESC
    """, (datetime.now().isoformat(),))
    users = c.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("💎 Premium foydalanuvchilar yo'q")
        return
    
    text = "💎 <b>PREMIUM FOYDALANUVCHILAR:</b>\n\n"
    for u in users:
        expires = datetime.fromisoformat(u['premium_expires_at']).strftime('%d.%m.%Y %H:%M')
        text += f"👤 {u['full_name']} - {expires} gacha\n"
        text += f"   ID: <code>{u['telegram_id']}</code>\n"
        text += f"   /removepremium {u['telegram_id']}\n\n"
    
    await update.message.reply_text(text, parse_mode="HTML")
async def admin_add_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⭐ /addstars <telegram_id> <amount> - Yulduz qo'shish"""
    if not is_admin(update.effective_user.id):
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("❌ Foydalanish: /addstars <telegram_id> <amount>")
            return
        
        user_telegram_id = int(args[0])
        amount = int(args[1])
        
        user = get_user(user_telegram_id)
        if not user:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi!")
            return
        
        add_stars(user['id'], amount)
        user = get_user(user_telegram_id)
        
        await update.message.reply_text(
            f"✅ {user['full_name']} ga {amount} yulduz qo'shildi!\n"
            f"⭐ Jami: {user.get('stars', 0)}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ ID va miqdor raqam bo'lishi kerak!")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📚 /admin - Admin buyruqlari"""
    if not is_admin(update.effective_user.id):
        return
    
    await update.message.reply_text(
        "🔧 <b>ADMIN BUYRUQLARI:</b>\n\n"
        "📊 /stats - Umumiy statistika\n"
        "👥 /users - Oxirgi foydalanuvchilar\n"
        "💎 /premiums - Premium ro'yxati\n\n"
        "💳 /payments - Kutilayotgan to'lovlar\n"
        "✅ /approve [id] [plan] - Tasdiqlash\n"
        "❌ /reject [id] [sabab] - Rad etish\n"
        "🚫 /removepremium [id] - Premium olib tashlash\n\n"
        "📢 /broadcast - Hammaga xabar (rasm + matn)\n"
        "🚫 /ban [id] - Bloklash\n\n"
        "⭐ /addstars [id] [amount] - Yulduz qo'shish\n\n"
        "⚙️ /setcard [raqam] - Karta o'zgartirish\n"
        "💰 /setprice [plan] [narx] - Narx o'zgartirish\n\n"
        "<i>Plan: 1_day, 3_days, 1_week, 1_month</i>",
        parse_mode="HTML"
    )
def main():
    """Botni ishga tushirish"""
    init_database()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Ro'yxatdan o'tish conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REGISTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)],
            REGISTER_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_gender)],
            REGISTER_REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_region)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    # Broadcast conversation
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", admin_broadcast_start)],
        states={
            BROADCAST_PHOTO: [
                MessageHandler(filters.PHOTO, admin_broadcast_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_broadcast_cancel)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(broadcast_handler)
    application.add_handler(CommandHandler("premium", premium_menu))
    application.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_(?!star)"))
    application.add_handler(CallbackQueryHandler(star_premium_menu, pattern="^star_premium$"))
    application.add_handler(CallbackQueryHandler(buy_star_premium, pattern="^buy_star_"))
    application.add_handler(CallbackQueryHandler(back_to_referral, pattern="^back_to_referral$"))
    
    # Admin handlerlari
    application.add_handler(CommandHandler("admin", admin_help))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("users", admin_users))
    application.add_handler(CommandHandler("payments", admin_payments))
    application.add_handler(CommandHandler("approve", admin_approve_payment))
    application.add_handler(CommandHandler("reject", admin_reject_payment))
    application.add_handler(CommandHandler("removepremium", admin_remove_premium))
    application.add_handler(CommandHandler("setcard", admin_setcard))
    application.add_handler(CommandHandler("setprice", admin_setprice))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("premiums", admin_premium_list))
    application.add_handler(CommandHandler("addstars", admin_add_stars))
    
    # Media handlerlar - chatda taqiqlangan
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_media_in_chat))
    application.add_handler(MessageHandler(filters.VOICE, handle_media_in_chat))
    application.add_handler(MessageHandler(filters.VIDEO, handle_media_in_chat))
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_media_in_chat))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_media_in_chat))
    application.add_handler(MessageHandler(filters.AUDIO, handle_media_in_chat))
    
    # Matn xabarlari
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))
    
    logger.info("Bot ishga tushdi! Database: " + DATABASE_FILE)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__ == "__main__":
    main()

