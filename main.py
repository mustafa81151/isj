import telebot
import sqlite3
import time
import threading
from datetime import datetime, timedelta
import logging
import os

TOKEN = "8661468668:AAFDhmy3auafDTkMZHLiDR6shp7jWxxNx2g"
ADMIN_ID = 8401168362
BOT_USERNAME = "TBADOLEbot"  # ⚠️ غير هذا بدون @

bot = telebot.TeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

# ================= قاعدة البيانات =================

def init_db():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        join_date TIMESTAMP,
        is_banned INTEGER DEFAULT 0,
        is_muted INTEGER DEFAULT 0,
        muted_until TIMESTAMP,
        total_donated INTEGER DEFAULT 0,
        avg_rating REAL DEFAULT 0,
        rating_count INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        stars_amount INTEGER,
        donation_date TIMESTAMP,
        telegram_payment_id TEXT,
        status TEXT DEFAULT 'completed'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS user_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        rated_by INTEGER,
        rating INTEGER,
        rating_date TIMESTAMP
    )''')

    # channel_link = رابط خاص يحدده الأدمن (اختياري — إذا فارغ يُستخدم channel_id@)
    c.execute('''CREATE TABLE IF NOT EXISTS force_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT,
        channel_name TEXT,
        channel_link TEXT,
        added_by INTEGER,
        added_date TIMESTAMP
    )''')

    # إضافة عمود channel_link إذا كانت DB قديمة
    try:
        c.execute("ALTER TABLE force_channels ADD COLUMN channel_link TEXT")
    except:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS exchange_channels (
        owner_id INTEGER,
        channel_id INTEGER,
        channel_username TEXT,
        channel_name TEXT,
        added_date TIMESTAMP,
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS completed_exchanges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER,
        user1_channel TEXT,
        user1_channel_id INTEGER,
        user2_id INTEGER,
        user2_channel TEXT,
        user2_channel_id INTEGER,
        exchange_date TIMESTAMP,
        user1_confirmed INTEGER DEFAULT 0,
        user2_confirmed INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS user_exchanges_history (
        user_id INTEGER,
        partner_id INTEGER,
        partner_channel TEXT,
        partner_channel_id INTEGER,
        partner_username TEXT,
        exchange_date TIMESTAMP,
        exchange_id INTEGER,
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS waiting_queue (
        user_id INTEGER,
        channel_username TEXT,
        channel_id INTEGER,
        waiting_time TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bot_warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT,
        channel_name TEXT,
        owner_id INTEGER,
        warning_date TIMESTAMP,
        is_resolved INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()

# ================= دوال مساعدة =================

def is_admin(user_id):
    return user_id == ADMIN_ID

def save_user(user_id, username, first_name):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    try:
        c.execute("""INSERT OR IGNORE INTO users
                     (user_id, username, first_name, join_date, is_banned, is_muted, total_donated)
                     VALUES (?, ?, ?, ?, 0, 0, 0)""",
                  (user_id, username, first_name, datetime.now()))
        # تحديث اليوزر والاسم دائماً
        c.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                  (username, first_name, user_id))
        conn.commit()
    except: pass
    conn.close()

def get_user_info(user_id):
    try:
        chat = bot.get_chat(user_id)
        return {
            'username': chat.username,
            'first_name': chat.first_name or f"User_{user_id}",
            'user_link': f"https://t.me/{chat.username}" if chat.username else f"tg://user?id={user_id}",
            'user_id': user_id
        }
    except:
        # fallback من DB
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT username, first_name FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            uname, fname = row
            return {
                'username': uname,
                'first_name': fname or f"User_{user_id}",
                'user_link': f"https://t.me/{uname}" if uname else f"tg://user?id={user_id}",
                'user_id': user_id
            }
        return {'username': None, 'first_name': f"User_{user_id}",
                'user_link': f"tg://user?id={user_id}", 'user_id': user_id}

def resolve_user(text):
    """
    يحل المستخدم من يوزر (@username) أو ID رقمي.
    يرجع (user_id, first_name) أو None إذا لم يوجد.
    يبحث في DB أولاً ثم يحاول Telegram API.
    """
    text = text.strip().lstrip('@')
    conn = sqlite3.connect('data.db')
    c = conn.cursor()

    # بحث بـ ID رقمي
    if text.isdigit() or (text.startswith('-') and text[1:].isdigit()):
        uid = int(text)
        c.execute("SELECT user_id, first_name FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
        # جرب API مباشرة
        try:
            chat = bot.get_chat(uid)
            return chat.id, chat.first_name or f"User_{uid}"
        except:
            return None

    # بحث بيوزر
    c.execute("SELECT user_id, first_name FROM users WHERE username=?", (text,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    # جرب API
    try:
        chat = bot.get_chat(f"@{text}")
        return chat.id, chat.first_name or text
    except:
        return None

def get_total_donations():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT SUM(stars_amount) FROM donations WHERE status='completed'")
    r = c.fetchone()
    conn.close()
    return r[0] if r[0] else 0

def get_user_donations(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT total_donated FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else 0

def get_rating_stars(rating):
    full = "⭐" * int(rating)
    if rating - int(rating) >= 0.5:
        full += "½"
    empty = "☆" * (5 - int(rating) - (1 if rating - int(rating) >= 0.5 else 0))
    return full + empty

def get_user_rating_display(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT avg_rating, rating_count FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    if r and r[1] > 0:
        return f"{get_rating_stars(r[0])} ({r[0]:.1f}/5 — {r[1]} تقييم)"
    return "لا توجد تقييمات"

def get_bot_rating():
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT AVG(rating), COUNT(*) FROM user_ratings WHERE user_id=0")
    r = c.fetchone()
    conn.close()
    if r and r[1] > 0:
        return f"{get_rating_stars(r[0])} ({r[0]:.1f}/5 — {r[1]} تقييم)"
    return "لا توجد تقييمات بعد"

def check_force_subscription(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT channel_id FROM force_channels")
    channels = c.fetchall()
    conn.close()
    if not channels:
        return True
    for (channel_id,) in channels:
        is_invite = channel_id.startswith("https://") or channel_id.startswith("http://")
        if is_invite:
            # روابط الدعوة الخاصة لا يمكن التحقق منها عبر get_chat_member
            # نفترض الاشتراك — المستخدم يضغط الرابط ويشترك بنفسه
            continue
        try:
            m = bot.get_chat_member(channel_id, user_id)
            if m.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True

def check_bot_admin_status(channel_ref):
    try:
        m = bot.get_chat_member(channel_ref, bot.get_me().id)
        return m.status in ['administrator', 'creator']
    except:
        return False

def is_user_subscribed_to_channel(user_id, channel_ref):
    try:
        m = bot.get_chat_member(channel_ref, user_id)
        return m.status not in ['left', 'kicked']
    except Exception as e:
        print(f"خطأ فحص اشتراك {user_id} في {channel_ref}: {e}")
        return False

def get_channel_current_username(channel_ref):
    try:
        chat = bot.get_chat(channel_ref)
        return f"@{chat.username}" if chat.username else str(channel_ref)
    except:
        return str(channel_ref)

def is_user_banned(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    try:
        c.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
        r = c.fetchone()
    except:
        r = None
    conn.close()
    return r and r[0] == 1

def is_user_muted(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    try:
        c.execute("SELECT is_muted, muted_until FROM users WHERE user_id=?", (user_id,))
        r = c.fetchone()
    except:
        r = None
    conn.close()
    if r and r[0] == 1:
        if r[1]:
            try:
                if datetime.now() > datetime.strptime(r[1], '%Y-%m-%d %H:%M:%S'):
                    _unmute_user(user_id)
                    return False
            except:
                pass
        return True
    return False

def _unmute_user(user_id):
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET is_muted=0, muted_until=NULL WHERE user_id=?", (user_id,))
        conn.commit()
    except: pass
    conn.close()

def send_stars_invoice(chat_id, amount):
    try:
        bot.send_invoice(
            chat_id=chat_id, title=f"دعم البوت بـ {amount} ⭐",
            description="شكراً لدعمك! ❤️",
            invoice_payload=f"donation_{amount}_{chat_id}",
            provider_token="", currency="XTR",
            prices=[telebot.types.LabeledPrice(label="دعم", amount=amount)],
            start_parameter="donate")
        return True
    except Exception as e:
        print(f"خطأ فاتورة: {e}")
        return False

def have_exchanged_before(user_id, partner_channel_id, partner_channel_username):
    """
    المنع بالقناة لا بالشخص.
    نفس الشخص بقناة مختلفة = مسموح.
    """
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    found = False
    if partner_channel_id:
        c.execute("""SELECT COUNT(*) FROM user_exchanges_history
                     WHERE user_id=? AND partner_channel_id=?""",
                  (user_id, partner_channel_id))
        found = c.fetchone()[0] > 0
    if not found and partner_channel_username:
        c.execute("""SELECT COUNT(*) FROM user_exchanges_history
                     WHERE user_id=? AND partner_channel=?
                     AND (partner_channel_id IS NULL OR partner_channel_id=0)""",
                  (user_id, partner_channel_username))
        found = c.fetchone()[0] > 0
    conn.close()
    return found

def get_channel_invite_url(channel_id, channel_link, channel_username):
    """يرجع أفضل رابط للقناة حسب الأولوية"""
    if channel_link and channel_link.strip():
        return channel_link.strip()
    if channel_username and channel_username.startswith('@'):
        return f"https://t.me/{channel_username.lstrip('@')}"
    return None

# ================= فحص صلاحيات البوت كل 6 ساعات =================

def check_all_channels_periodically():
    while True:
        time.sleep(21600)
        try:
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT owner_id, channel_id, channel_username, channel_name FROM exchange_channels WHERE is_active=1")
            channels = c.fetchall()
            for owner_id, ch_id, ch_username, ch_name in channels:
                ref = ch_id if ch_id else ch_username
                if not check_bot_admin_status(ref):
                    c.execute("INSERT INTO bot_warnings (channel_id,channel_name,owner_id,warning_date,is_resolved) VALUES (?,?,?,?,0)",
                              (ch_username, ch_name, owner_id, datetime.now()))
                    if ch_id:
                        c.execute("UPDATE exchange_channels SET is_active=0 WHERE channel_id=?", (ch_id,))
                        c.execute("SELECT DISTINCT user_id FROM user_exchanges_history WHERE partner_channel_id=? AND is_active=1", (ch_id,))
                    else:
                        c.execute("UPDATE exchange_channels SET is_active=0 WHERE channel_username=?", (ch_username,))
                        c.execute("SELECT DISTINCT user_id FROM user_exchanges_history WHERE partner_channel=? AND is_active=1", (ch_username,))
                    partners = c.fetchall()
                    oinfo = get_user_info(owner_id)
                    try:
                        bot.send_message(owner_id,
                            f"⚠️ <b>البوت أُزيل من الاشراف في قناتك!</b>\n\n📢 {ch_name}\n\n"
                            f"🔹 أضف @{bot.get_me().username} كمشرف مجدداً\n👥 متأثرين: {len(partners)}",
                            parse_mode='HTML')
                    except: pass
                    for (pid,) in partners:
                        try:
                            bot.send_message(pid,
                                f"⚠️ <b>البوت لم يعد مشرفاً في قناة شريكك!</b>\n\n📢 {ch_name}\n👤 {oinfo['first_name']}",
                                parse_mode='HTML')
                        except: pass
                    if ch_id:
                        c.execute("UPDATE user_exchanges_history SET is_active=0 WHERE partner_channel_id=?", (ch_id,))
                    else:
                        c.execute("UPDATE user_exchanges_history SET is_active=0 WHERE partner_channel=?", (ch_username,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"خطأ الفحص الدوري: {e}")

# ================= فحص اشتراكات التبادل كل دقيقة =================

def check_all_exchanges_subscriptions():
    while True:
        time.sleep(60)
        try:
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("""SELECT id, user1_id, user1_channel, user1_channel_id,
                                user2_id, user2_channel, user2_channel_id
                         FROM completed_exchanges
                         WHERE user1_confirmed=1 AND user2_confirmed=1""")
            exchanges = c.fetchall()
            for exchange_id, u1_id, u1_ch, u1_ch_id, u2_id, u2_ch, u2_ch_id in exchanges:
                u1_ref = u1_ch_id if u1_ch_id else u1_ch
                u2_ref = u2_ch_id if u2_ch_id else u2_ch
                u1_display = get_channel_current_username(u1_ref)
                u2_display = get_channel_current_username(u2_ref)
                u1_info = get_user_info(u1_id)
                u2_info = get_user_info(u2_id)

                # فحص user1 في قناة user2
                u1_sub = is_user_subscribed_to_channel(u1_id, u2_ref)
                c.execute("SELECT is_active FROM user_exchanges_history WHERE user_id=? AND exchange_id=?", (u1_id, exchange_id))
                row = c.fetchone()
                u1_was = row[0] if row else 1

                if u1_was == 1 and not u1_sub:
                    c.execute("UPDATE user_exchanges_history SET is_active=0 WHERE user_id=? AND exchange_id=?", (u1_id, exchange_id))
                    rm = telebot.types.InlineKeyboardMarkup()
                    u2_url = f"https://t.me/{u2_display.lstrip('@')}"
                    rm.add(telebot.types.InlineKeyboardButton("🔄 أعد الاشتراك الآن", url=u2_url))
                    rm.add(telebot.types.InlineKeyboardButton("✅ اشتركت — أبلغ الشريك", callback_data=f"rejoin_confirm_{exchange_id}_u1"))
                    try:
                        bot.send_message(u1_id,
                            f"⚠️ <b>غادرت قناة شريكك!</b>\n\n"
                            f"📢 {u2_display} | <code>{u2_ref}</code>\n"
                            f"👤 {u2_info['first_name']} | {u2_info['user_link']}\n\n"
                            f"❌ مخالف لشروط التبادل — أعد الاشتراك:",
                            reply_markup=rm, parse_mode='HTML', disable_web_page_preview=True)
                    except: pass
                    try:
                        bot.send_message(u2_id,
                            f"🚨 <b>شريكك غادر قناتك!</b>\n\n"
                            f"📢 قناتك: {u2_display} | <code>{u2_ref}</code>\n\n"
                            f"👤 {u1_info['first_name']} | {u1_info['user_link']}\n"
                            f"📢 قناته: {u1_display} | <code>{u1_ref}</code>\n\n"
                            f"💡 سيصلك إشعار إذا رجع.",
                            parse_mode='HTML', disable_web_page_preview=True)
                    except: pass

                elif u1_was == 0 and u1_sub:
                    c.execute("UPDATE user_exchanges_history SET is_active=1 WHERE user_id=? AND exchange_id=?", (u1_id, exchange_id))
                    try:
                        bot.send_message(u2_id,
                            f"✅ <b>شريكك عاد!</b>\n\n👤 {u1_info['first_name']} | {u1_info['user_link']}\n"
                            f"📢 قناته: {u1_display}\n\n🎉 التبادل نشط مجدداً!",
                            parse_mode='HTML', disable_web_page_preview=True)
                    except: pass

                # فحص user2 في قناة user1
                u2_sub = is_user_subscribed_to_channel(u2_id, u1_ref)
                c.execute("SELECT is_active FROM user_exchanges_history WHERE user_id=? AND exchange_id=?", (u2_id, exchange_id))
                row2 = c.fetchone()
                u2_was = row2[0] if row2 else 1

                if u2_was == 1 and not u2_sub:
                    c.execute("UPDATE user_exchanges_history SET is_active=0 WHERE user_id=? AND exchange_id=?", (u2_id, exchange_id))
                    rm2 = telebot.types.InlineKeyboardMarkup()
                    u1_url = f"https://t.me/{u1_display.lstrip('@')}"
                    rm2.add(telebot.types.InlineKeyboardButton("🔄 أعد الاشتراك الآن", url=u1_url))
                    rm2.add(telebot.types.InlineKeyboardButton("✅ اشتركت — أبلغ الشريك", callback_data=f"rejoin_confirm_{exchange_id}_u2"))
                    try:
                        bot.send_message(u2_id,
                            f"⚠️ <b>غادرت قناة شريكك!</b>\n\n"
                            f"📢 {u1_display} | <code>{u1_ref}</code>\n"
                            f"👤 {u1_info['first_name']} | {u1_info['user_link']}\n\n"
                            f"❌ مخالف لشروط التبادل — أعد الاشتراك:",
                            reply_markup=rm2, parse_mode='HTML', disable_web_page_preview=True)
                    except: pass
                    try:
                        bot.send_message(u1_id,
                            f"🚨 <b>شريكك غادر قناتك!</b>\n\n"
                            f"📢 قناتك: {u1_display} | <code>{u1_ref}</code>\n\n"
                            f"👤 {u2_info['first_name']} | {u2_info['user_link']}\n"
                            f"📢 قناته: {u2_display} | <code>{u2_ref}</code>\n\n"
                            f"💡 سيصلك إشعار إذا رجع.",
                            parse_mode='HTML', disable_web_page_preview=True)
                    except: pass

                elif u2_was == 0 and u2_sub:
                    c.execute("UPDATE user_exchanges_history SET is_active=1 WHERE user_id=? AND exchange_id=?", (u2_id, exchange_id))
                    try:
                        bot.send_message(u1_id,
                            f"✅ <b>شريكك عاد!</b>\n\n👤 {u2_info['first_name']} | {u2_info['user_link']}\n"
                            f"📢 قناته: {u2_display}\n\n🎉 التبادل نشط مجدداً!",
                            parse_mode='HTML', disable_web_page_preview=True)
                    except: pass

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"خطأ فحص الاشتراكات: {e}")

# ================= إرسال DB كل 30 دقيقة =================

def send_db_backup_periodically():
    while True:
        time.sleep(1800)
        try:
            if not os.path.exists('data.db'):
                continue
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users"); uc = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM exchange_channels WHERE is_active=1"); ac = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM completed_exchanges WHERE user1_confirmed=1 AND user2_confirmed=1"); cc = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM waiting_queue"); wc = c.fetchone()[0]
            c.execute("SELECT SUM(stars_amount) FROM donations WHERE status='completed'"); ts = c.fetchone()[0] or 0
            conn.close()
            caption = (f"🗄 <b>نسخة احتياطية</b>\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"👥 {uc} | 📢 {ac} | ✅ {cc} | ⏳ {wc} | ⭐ {ts}")
            with open('data.db', 'rb') as f:
                bot.send_document(ADMIN_ID, f, caption=caption, parse_mode='HTML',
                                  visible_file_name=f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
            print(f"✅ نسخة DB أُرسلت {datetime.now().strftime('%H:%M')}")
        except Exception as e:
            print(f"خطأ إرسال DB: {e}")

# ================= القوائم =================

def get_main_menu(user_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel"),
        telebot.types.InlineKeyboardButton("🔄 بحث عن تبادل", callback_data="find_exchange"))
    markup.add(
        telebot.types.InlineKeyboardButton("📝 قناتي", callback_data="my_channel"),
        telebot.types.InlineKeyboardButton("❌ حذف قناتي", callback_data="delete_channel"))
    markup.add(
        telebot.types.InlineKeyboardButton("⭐ تقييم مستخدم", callback_data="rate_user"),
        telebot.types.InlineKeyboardButton("📊 تقييم البوت", callback_data="rate_bot"))
    markup.add(
        telebot.types.InlineKeyboardButton("💰 دعم البوت", callback_data="support_bot"),
        telebot.types.InlineKeyboardButton("📋 تبادلاتي", callback_data="my_exchanges"))
    markup.add(telebot.types.InlineKeyboardButton("⏳ قائمة الانتظار", callback_data="show_queue"))
    if is_admin(user_id):
        markup.add(telebot.types.InlineKeyboardButton("👑 لوحة التحكم", callback_data="admin_panel"))
    return markup

def get_force_channels_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT channel_id, channel_name, channel_link FROM force_channels")
    channels = c.fetchall()
    conn.close()
    for channel_id, channel_name, channel_link in channels:
        url = get_channel_invite_url(channel_id, channel_link, channel_id)
        if url:
            markup.add(telebot.types.InlineKeyboardButton(f"📢 {channel_name}", url=url))
        else:
            markup.add(telebot.types.InlineKeyboardButton(f"📢 {channel_name}", callback_data="noop"))
    markup.add(telebot.types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription"))
    return markup

def get_admin_panel():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("➕ قناة اجباري", callback_data="admin_add_channel"),
        telebot.types.InlineKeyboardButton("➖ حذف قناة اجباري", callback_data="admin_remove_channel"))
    markup.add(
        telebot.types.InlineKeyboardButton("⚠️ حظر مستخدم", callback_data="admin_ban"),
        telebot.types.InlineKeyboardButton("🔓 فك حظر", callback_data="admin_unban"))
    markup.add(
        telebot.types.InlineKeyboardButton("🔇 كتم مستخدم", callback_data="admin_mute"),
        telebot.types.InlineKeyboardButton("🔊 فك كتم", callback_data="admin_unmute"))
    markup.add(
        telebot.types.InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search_user"),
        telebot.types.InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin_users_list"))
    markup.add(
        telebot.types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
        telebot.types.InlineKeyboardButton("🔍 فحص الاشتراكات", callback_data="admin_check_subs"))
    markup.add(
        telebot.types.InlineKeyboardButton("📢 إشعار عام", callback_data="admin_broadcast"),
        telebot.types.InlineKeyboardButton("🔍 فحص القنوات", callback_data="check_all_channels"))
    markup.add(
        telebot.types.InlineKeyboardButton("⚠️ تحذيرات البوت", callback_data="admin_warnings"),
        telebot.types.InlineKeyboardButton("📋 التبادلات المكتملة", callback_data="admin_completed"))
    markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    return markup

def get_donation_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    for i, amount in enumerate([5, 10, 15, 20, 25, 50, 100, 200]):
        if i % 2 == 0:
            row = [telebot.types.InlineKeyboardButton(f"{amount} ⭐", callback_data=f"pay_{amount}")]
        else:
            row.append(telebot.types.InlineKeyboardButton(f"{amount} ⭐", callback_data=f"pay_{amount}"))
            markup.add(*row)
    markup.add(telebot.types.InlineKeyboardButton("✏️ مبلغ مخصص", callback_data="pay_custom"))
    markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    return markup

def get_rating_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=5)
    markup.add(*[telebot.types.InlineKeyboardButton(f"{i}⭐", callback_data=f"rate_bot_{i}") for i in range(1, 6)])
    markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    return markup

def user_action_menu(target_id, target_name):
    """قائمة إجراءات على مستخدم محدد"""
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("⚠️ حظر", callback_data=f"act_ban_{target_id}"),
        telebot.types.InlineKeyboardButton("🔓 فك حظر", callback_data=f"act_unban_{target_id}"))
    markup.add(
        telebot.types.InlineKeyboardButton("🔇 كتم 24h", callback_data=f"act_mute_{target_id}_24"),
        telebot.types.InlineKeyboardButton("🔊 فك كتم", callback_data=f"act_unmute_{target_id}"))
    markup.add(
        telebot.types.InlineKeyboardButton("📋 تبادلاته", callback_data=f"act_exchanges_{target_id}"),
        telebot.types.InlineKeyboardButton("📊 معلوماته", callback_data=f"act_info_{target_id}"))
    markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع للوحة", callback_data="admin_panel"))
    return markup

# ================= /start =================

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    save_user(user_id, message.from_user.username, message.from_user.first_name)
    if is_user_banned(user_id):
        bot.reply_to(message, "🚫 <b>تم حظرك من استخدام البوت.</b>", parse_mode='HTML')
        return
    if not check_force_subscription(user_id):
        bot.reply_to(message,
            "👋 <b>اهلاً بك في بوت تبادل القنوات</b>\n\n⚠️ <b>اشترك في القنوات التالية أولاً:</b>",
            reply_markup=get_force_channels_keyboard(), parse_mode='HTML')
    else:
        bot.reply_to(message,
            f"👋 <b>اهلاً بك في بوت تبادل القنوات</b>\n\n"
            f"📊 <b>تقييم البوت:</b> {get_bot_rating()}\n"
            f"💰 <b>إجمالي التبرعات:</b> {get_total_donations()} ⭐\n\n📌 <b>اختر الخدمة:</b>",
            reply_markup=get_main_menu(user_id), parse_mode='HTML')

# ================= كولباك رئيسي =================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id

    # noop زر وهمي
    if call.data == "noop":
        bot.answer_callback_query(call.id)
        return

    if is_user_banned(user_id):
        bot.answer_callback_query(call.id, "🚫 تم حظرك!", show_alert=True)
        return
    if is_user_muted(user_id):
        bot.answer_callback_query(call.id, "🔇 أنت مكتوم!", show_alert=True)
        return

    # ===== رجوع =====
    if call.data == "back_to_main":
        bot.edit_message_text(
            f"👋 <b>القائمة الرئيسية</b>\n\n📊 {get_bot_rating()}\n💰 {get_total_donations()} ⭐\n\n📌 <b>اختر:</b>",
            chat_id=call.message.chat.id, message_id=call.message.message_id,
            reply_markup=get_main_menu(user_id), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== تحقق اشتراك =====
    if call.data == "check_subscription":
        if check_force_subscription(user_id):
            bot.edit_message_text(
                f"✅ <b>تم التحقق!</b>\n\n📊 {get_bot_rating()}\n💰 {get_total_donations()} ⭐\n\n📌 <b>اختر:</b>",
                chat_id=call.message.chat.id, message_id=call.message.message_id,
                reply_markup=get_main_menu(user_id), parse_mode='HTML')
        else:
            bot.edit_message_text(
                "⚠️ <b>لا يزال يتعين عليك الاشتراك:</b>",
                chat_id=call.message.chat.id, message_id=call.message.message_id,
                reply_markup=get_force_channels_keyboard(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== إعادة اشتراك بعد مغادرة =====
    if call.data.startswith("rejoin_confirm_"):
        try:
            parts = call.data.split("_")
            exchange_id = int(parts[2])
            who = parts[3]
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT user1_id,user1_channel,user1_channel_id,user2_id,user2_channel,user2_channel_id FROM completed_exchanges WHERE id=?", (exchange_id,))
            ex = c.fetchone()
            if not ex:
                bot.answer_callback_query(call.id, "❌ التبادل غير موجود!", show_alert=True)
                conn.close()
                return
            u1_id, u1_ch, u1_ch_id, u2_id, u2_ch, u2_ch_id = ex
            if who == "u1" and user_id == u1_id:
                check_ref = u2_ch_id if u2_ch_id else u2_ch
                partner_id = u2_id
                my_display = get_channel_current_username(u1_ch_id if u1_ch_id else u1_ch)
            elif who == "u2" and user_id == u2_id:
                check_ref = u1_ch_id if u1_ch_id else u1_ch
                partner_id = u1_id
                my_display = get_channel_current_username(u2_ch_id if u2_ch_id else u2_ch)
            else:
                bot.answer_callback_query(call.id, "❌ لا تملك صلاحية!", show_alert=True)
                conn.close()
                return
            ch_display = get_channel_current_username(check_ref)
            if not is_user_subscribed_to_channel(user_id, check_ref):
                bot.answer_callback_query(call.id, "❌ لم يُرصد اشتراكك بعد!\nاشترك أولاً.", show_alert=True)
                conn.close()
                return
            c.execute("UPDATE user_exchanges_history SET is_active=1 WHERE user_id=? AND exchange_id=?", (user_id, exchange_id))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ تم التحقق! تم إبلاغ شريكك.")
            uinfo = get_user_info(user_id)
            try:
                bot.send_message(partner_id,
                    f"✅ <b>شريكك عاد واشترك في قناتك!</b>\n\n"
                    f"👤 {uinfo['first_name']} | {uinfo['user_link']}\n📢 قناته: {my_display}\n\n🎉 التبادل نشط مجدداً!",
                    parse_mode='HTML', disable_web_page_preview=True)
            except: pass
            bot.send_message(user_id, f"✅ تم التأكيد — شريكك علم بعودتك إلى {ch_display} 🎉", parse_mode='HTML')
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")
        return

    # ===== إضافة قناة =====
    if call.data == "add_channel":
        if not check_force_subscription(user_id):
            bot.answer_callback_query(call.id, "❌ اشترك في القنوات الاجبارية أولاً!", show_alert=True)
            return
        msg = bot.send_message(call.message.chat.id,
            "📢 <b>أرسل معرف قناتك</b>\n\nمثال: @my_channel\n\n"
            "⚠️ يجب أن يكون البوت مشرفاً مع صلاحية النشر\n"
            "🔒 يُحفظ ID الرقمي الثابت تلقائياً", parse_mode='HTML')
        bot.register_next_step_handler(msg, save_channel_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== قناتي =====
    if call.data == "my_channel":
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT channel_id,channel_username,channel_name,is_active FROM exchange_channels WHERE owner_id=?", (user_id,))
        ch = c.fetchone()
        conn.close()
        if ch:
            ch_id, ch_uname, ch_name, is_active = ch
            current = get_channel_current_username(ch_id if ch_id else ch_uname)
            status = "✅ نشطة" if is_active else "❌ معطلة"
            text = (f"📢 <b>قناتك:</b>\n\n📌 {ch_name}\n🔗 {current}\n🔢 ID: <code>{ch_id}</code>\n📊 {status}")
            if not is_active:
                text += "\n\n⚠️ أضف البوت كمشرف مجدداً."
        else:
            text = "📭 لم تضف قناة بعد — استخدم '➕ إضافة قناة'"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)
        bot.answer_callback_query(call.id)
        return

    # ===== حذف قناتي =====
    if call.data == "delete_channel":
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT channel_username,channel_name FROM exchange_channels WHERE owner_id=?", (user_id,))
        ch = c.fetchone()
        if ch:
            c.execute("DELETE FROM exchange_channels WHERE owner_id=?", (user_id,))
            c.execute("DELETE FROM waiting_queue WHERE user_id=?", (user_id,))
            c.execute("UPDATE user_exchanges_history SET is_active=0 WHERE user_id=?", (user_id,))
            conn.commit()
            text = f"✅ <b>تم حذف قناتك</b>\n📢 {ch[1]}\n🔗 {ch[0]}"
        else:
            text = "📭 ليس لديك قناة مسجلة"
        conn.close()
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== بحث عن تبادل =====
    if call.data == "find_exchange":
        if not check_force_subscription(user_id):
            bot.answer_callback_query(call.id, "❌ اشترك في القنوات الاجبارية أولاً!", show_alert=True)
            return
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT channel_id,channel_username,channel_name,is_active FROM exchange_channels WHERE owner_id=?", (user_id,))
        uch = c.fetchone()
        if not uch:
            bot.answer_callback_query(call.id, "❌ أضف قناة أولاً!", show_alert=True)
            conn.close()
            return
        ch_id, ch_uname, ch_name, is_active = uch
        check_ref = ch_id if ch_id else ch_uname
        if not check_bot_admin_status(check_ref):
            bot.answer_callback_query(call.id, "❌ البوت ليس مشرفاً في قناتك!", show_alert=True)
            c.execute("UPDATE exchange_channels SET is_active=0 WHERE owner_id=?", (user_id,))
            conn.commit()
            conn.close()
            return
        current_uname = get_channel_current_username(check_ref)

        # بحث عن شريك جديد فقط (قناة لم يتبادل معها)
        c.execute("SELECT user_id,channel_username,channel_id FROM waiting_queue WHERE user_id!=? ORDER BY waiting_time ASC", (user_id,))
        partner = None
        for cand_id, cand_ch, cand_ch_id in c.fetchall():
            if have_exchanged_before(user_id, cand_ch_id, cand_ch):
                continue
            if have_exchanged_before(cand_id, ch_id, current_uname):
                continue
            partner = (cand_id, cand_ch, cand_ch_id)
            break

        if partner:
            p_id, p_ch, p_ch_id = partner
            p_ref = p_ch_id if p_ch_id else p_ch
            p_current = get_channel_current_username(p_ref)
            c.execute("DELETE FROM waiting_queue WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM waiting_queue WHERE user_id=?", (p_id,))
            c.execute("""INSERT INTO completed_exchanges
                         (user1_id,user1_channel,user1_channel_id,user2_id,user2_channel,user2_channel_id,
                          exchange_date,user1_confirmed,user2_confirmed)
                         VALUES (?,?,?,?,?,?,?,0,0)""",
                      (user_id, current_uname, ch_id, p_id, p_current, p_ch_id, datetime.now()))
            ex_id = c.lastrowid
            p_info = get_user_info(p_id)
            u_info = get_user_info(user_id)
            c.execute("""INSERT INTO user_exchanges_history
                         (user_id,partner_id,partner_channel,partner_channel_id,partner_username,exchange_date,exchange_id,is_active)
                         VALUES (?,?,?,?,?,?,?,1)""",
                      (user_id, p_id, p_current, p_ch_id, p_info['username'], datetime.now(), ex_id))
            c.execute("""INSERT INTO user_exchanges_history
                         (user_id,partner_id,partner_channel,partner_channel_id,partner_username,exchange_date,exchange_id,is_active)
                         VALUES (?,?,?,?,?,?,?,1)""",
                      (p_id, user_id, current_uname, ch_id, u_info['username'], datetime.now(), ex_id))
            conn.commit()

            cm = telebot.types.InlineKeyboardMarkup()
            cm.add(telebot.types.InlineKeyboardButton("✅ أكد اشتراكي في قناة الشريك", callback_data=f"confirm_exchange_{ex_id}"))

            bot.send_message(user_id,
                f"🤝 <b>تم العثور على شريك!</b>\n\n📢 قناتك: {current_uname}\n\n"
                f"👤 {p_info['first_name']} | {p_info['user_link']}\n"
                f"📢 قناة الشريك: {p_current}\n🔗 https://t.me/{p_current.lstrip('@')}\n\n"
                f"1️⃣ اشترك في قناة الشريك\n2️⃣ اضغط الزر للتأكيد",
                reply_markup=cm, parse_mode='HTML', disable_web_page_preview=True)
            bot.send_message(p_id,
                f"🤝 <b>تم العثور على شريك!</b>\n\n📢 قناتك: {p_current}\n\n"
                f"👤 {u_info['first_name']} | {u_info['user_link']}\n"
                f"📢 قناة الشريك: {current_uname}\n🔗 https://t.me/{current_uname.lstrip('@')}\n\n"
                f"1️⃣ اشترك في قناة الشريك\n2️⃣ اضغط الزر للتأكيد",
                reply_markup=cm, parse_mode='HTML', disable_web_page_preview=True)
            bot.edit_message_text("✅ <b>تم العثور على شريك!</b>\nتفاصيله في رسالة منفصلة.",
                                  chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML')
        else:
            c.execute("SELECT COUNT(*) FROM waiting_queue WHERE user_id=?", (user_id,))
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO waiting_queue (user_id,channel_username,channel_id,waiting_time) VALUES (?,?,?,?)",
                          (user_id, current_uname, ch_id, datetime.now()))
                conn.commit()
            c.execute("SELECT COUNT(*) FROM waiting_queue")
            qc = c.fetchone()[0]
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
            bot.edit_message_text(
                f"⏳ <b>أنت في قائمة الانتظار</b>\n👥 المنتظرين: {qc}\n\n📌 لن يُقرَن معك من تبادلت معه بنفس القناة مسبقاً.",
                chat_id=call.message.chat.id, message_id=call.message.message_id,
                reply_markup=markup, parse_mode='HTML')
        conn.close()
        bot.answer_callback_query(call.id)
        return

    # ===== تأكيد التبادل =====
    if call.data.startswith("confirm_exchange_"):
        try:
            ex_id = int(call.data.split("_")[2])
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT user1_id,user1_channel,user1_channel_id,user2_id,user2_channel,user2_channel_id,user1_confirmed,user2_confirmed FROM completed_exchanges WHERE id=?", (ex_id,))
            ex = c.fetchone()
            if not ex:
                bot.answer_callback_query(call.id, "❌ التبادل غير موجود!", show_alert=True)
                conn.close()
                return
            u1_id, u1_ch, u1_ch_id, u2_id, u2_ch, u2_ch_id, u1_conf, u2_conf = ex
            if user_id == u1_id:
                check_ref = u2_ch_id if u2_ch_id else u2_ch
            elif user_id == u2_id:
                check_ref = u1_ch_id if u1_ch_id else u1_ch
            else:
                bot.answer_callback_query(call.id, "❌ لا تملك صلاحية!", show_alert=True)
                conn.close()
                return
            ch_display = get_channel_current_username(check_ref)
            if not is_user_subscribed_to_channel(user_id, check_ref):
                bot.answer_callback_query(call.id, "❌ لم يُرصد اشتراكك بعد!\nاشترك أولاً.", show_alert=True)
                bot.send_message(user_id,
                    f"❌ <b>لم يُتحقق من اشتراكك!</b>\n\n📢 {ch_display}\n🔗 https://t.me/{ch_display.lstrip('@')}\n\nاشترك ثم اضغط التأكيد.",
                    parse_mode='HTML', disable_web_page_preview=True)
                conn.close()
                return
            if user_id == u1_id and u1_conf == 0:
                c.execute("UPDATE completed_exchanges SET user1_confirmed=1 WHERE id=?", (ex_id,))
            elif user_id == u2_id and u2_conf == 0:
                c.execute("UPDATE completed_exchanges SET user2_confirmed=1 WHERE id=?", (ex_id,))
            else:
                bot.answer_callback_query(call.id, "قمت بالتأكيد مسبقاً!")
                conn.close()
                return
            conn.commit()
            c.execute("SELECT user1_confirmed,user2_confirmed FROM completed_exchanges WHERE id=?", (ex_id,))
            final = c.fetchone()
            if final[0] == 1 and final[1] == 1:
                bot.answer_callback_query(call.id, "✅ اكتمل التبادل! 🎉")
                msg = "✅ <b>اكتمل التبادل بنجاح!</b>\n\nكلاكما أكّد الاشتراك.\n⭐ قيّم تجربتك من '⭐ تقييم مستخدم'"
                bot.send_message(u1_id, msg, parse_mode='HTML')
                bot.send_message(u2_id, msg, parse_mode='HTML')
            else:
                bot.answer_callback_query(call.id, "✅ تم التحقق! انتظر الشريك...")
                other = u2_id if user_id == u1_id else u1_id
                bot.send_message(other, "✅ <b>شريكك أكد اشتراكه في قناتك!</b>\nاضغط زر التأكيد لإكمال التبادل.", parse_mode='HTML')
            conn.close()
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")
        return

    # ===== قائمة الانتظار =====
    if call.data == "show_queue":
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM waiting_queue")
        count = c.fetchone()[0]
        c.execute("SELECT user_id,channel_username,waiting_time FROM waiting_queue ORDER BY waiting_time ASC LIMIT 10")
        items = c.fetchall()
        conn.close()
        text = f"⏳ <b>قائمة الانتظار</b>\n👥 {count} مستخدم\n\n"
        for i, (uid, ch, wt) in enumerate(items, 1):
            ui = get_user_info(uid)
            text += f"{i}. {ui['first_name']} — {ch}\n"
        if count > 0:
            text += "\n📌 يُقرَن معك شركاء بقنوات جديدة فقط."
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== تبادلاتي =====
    if call.data == "my_exchanges":
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("""SELECT partner_id,partner_channel,partner_channel_id,partner_username,exchange_date,is_active
                     FROM user_exchanges_history WHERE user_id=? ORDER BY exchange_date DESC LIMIT 20""", (user_id,))
        exs = c.fetchall()
        conn.close()
        if not exs:
            text = "📭 <b>ليس لديك تبادلات سابقة</b>"
        else:
            text = "📋 <b>تبادلاتي:</b>\n\n"
            for i, (pid, pch, pch_id, puname, ex_date, is_active) in enumerate(exs[:10], 1):
                ref = pch_id if pch_id else pch
                cur_ch = get_channel_current_username(ref)
                plink = f"https://t.me/{puname}" if puname else f"tg://user?id={pid}"
                sub_st = "✅" if is_active else "❌ غادر"
                text += f"{i}. <a href='{plink}'>{pid}</a>\n   📢 {cur_ch} {sub_st}\n   ⭐ {get_user_rating_display(pid)}\n   📅 {ex_date[:16]}\n\n"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)
        bot.answer_callback_query(call.id)
        return

    # ===== دعم البوت =====
    if call.data == "support_bot":
        bot.edit_message_text(
            f"💰 <b>دعم البوت</b>\n\n📊 الإجمالي: {get_total_donations()} ⭐\n💝 تبرعاتك: {get_user_donations(user_id)} ⭐\n\n✨ اختر المبلغ:",
            chat_id=call.message.chat.id, message_id=call.message.message_id,
            reply_markup=get_donation_keyboard(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    if call.data.startswith("pay_"):
        if call.data == "pay_custom":
            msg = bot.send_message(call.message.chat.id, "✏️ <b>أرسل عدد النجوم (1-1000):</b>", parse_mode='HTML')
            bot.register_next_step_handler(msg, custom_payment_step, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        try:
            amount = int(call.data.split("_")[1])
            if send_stars_invoice(call.message.chat.id, amount):
                bot.answer_callback_query(call.id, "✅ تم إرسال الفاتورة!")
                bot.edit_message_text(f"💰 فاتورة {amount} ⭐ — اضغط 'دفع'",
                                      chat_id=call.message.chat.id, message_id=call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "❌ خطأ في إنشاء الفاتورة")
        except:
            bot.answer_callback_query(call.id, "❌ خطأ")
        return

    # ===== تقييم البوت =====
    if call.data == "rate_bot":
        bot.edit_message_text(
            f"⭐ <b>تقييم البوت</b>\n\nالحالي: {get_bot_rating()}\n\nاختر:",
            chat_id=call.message.chat.id, message_id=call.message.message_id,
            reply_markup=get_rating_keyboard(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    if call.data.startswith("rate_bot_"):
        try:
            rating = int(call.data.split("_")[2])
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM user_ratings WHERE rated_by=? AND user_id=0", (user_id,))
            if c.fetchone()[0] > 0:
                bot.answer_callback_query(call.id, "❌ قيّمت البوت مسبقاً!", show_alert=True)
                conn.close()
                return
            c.execute("INSERT INTO user_ratings (user_id,rated_by,rating,rating_date) VALUES (0,?,?,?)", (user_id, rating, datetime.now()))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, f"✅ شكراً! {rating} نجوم")
            bot.edit_message_text(f"✅ <b>شكراً!</b>\n{get_rating_stars(rating)}\n📊 {get_bot_rating()}",
                                  chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  reply_markup=get_main_menu(user_id), parse_mode='HTML')
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")
        return

    # ===== تقييم مستخدم =====
    if call.data == "rate_user":
        msg = bot.send_message(call.message.chat.id,
            "⭐ <b>أرسل يوزر أو ID المستخدم:</b>\nمثال: @username أو 123456789", parse_mode='HTML')
        bot.register_next_step_handler(msg, get_user_to_rate_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== لوحة التحكم =====
    if call.data == "admin_panel" and is_admin(user_id):
        bot.edit_message_text("🎛 <b>لوحة التحكم</b>",
                              chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== إضافة قناة اجبارية =====
    if call.data == "admin_add_channel" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id,
            "📢 <b>إضافة قناة اجبارية</b>\n\n"
            "أرسل أي من الصيغ التالية:\n\n"
            "1️⃣ <b>قناة عامة (@username):</b>\n"
            "<code>@mychannel</code>\n\n"
            "2️⃣ <b>قناة عامة (ID):</b>\n"
            "<code>-1001234567890</code>\n\n"
            "3️⃣ <b>رابط دعوة خاص فقط:</b>\n"
            "<code>https://t.me/+AbCdEfGhIjK</code>\n\n"
            "4️⃣ <b>رابط دعوة + اسم مخصص (سطرين):</b>\n"
            "<code>https://t.me/+AbCdEfGhIjK</code>\n"
            "<code>اسم قناتي</code>",
            parse_mode='HTML')
        bot.register_next_step_handler(msg, add_force_channel_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== حذف قناة اجبارية =====
    if call.data == "admin_remove_channel" and is_admin(user_id):
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT id,channel_id,channel_name FROM force_channels")
        channels = c.fetchall()
        conn.close()
        if channels:
            markup = telebot.types.InlineKeyboardMarkup(row_width=1)
            for rid, cid, cname in channels:
                markup.add(telebot.types.InlineKeyboardButton(f"❌ {cname} ({cid})", callback_data=f"del_force_{rid}"))
            markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            bot.edit_message_text("🗑 <b>اختر القناة للحذف:</b>",
                                  chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  reply_markup=markup, parse_mode='HTML')
        else:
            bot.answer_callback_query(call.id, "📭 لا توجد قنوات اجبارية")
        return

    if call.data.startswith("del_force_") and is_admin(user_id):
        rid = int(call.data.split("_")[2])
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("DELETE FROM force_channels WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ تم الحذف")
        bot.edit_message_text("✅ <b>تم حذف القناة</b>",
                              chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        return

    # ===== حظر / فك حظر / كتم / فك كتم =====
    if call.data == "admin_ban" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id, "⚠️ <b>أرسل يوزر أو ID المستخدم للحظر:</b>", parse_mode='HTML')
        bot.register_next_step_handler(msg, ban_user_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if call.data == "admin_unban" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id, "🔓 <b>أرسل يوزر أو ID المستخدم لفك الحظر:</b>", parse_mode='HTML')
        bot.register_next_step_handler(msg, unban_user_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if call.data == "admin_mute" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id,
            "🔇 <b>أرسل يوزر أو ID والمدة بالساعات:</b>\n"
            "مثال: @username 24\n"
            "مثال: 123456789 0 (دائم)", parse_mode='HTML')
        bot.register_next_step_handler(msg, mute_user_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if call.data == "admin_unmute" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id, "🔊 <b>أرسل يوزر أو ID لفك الكتم:</b>", parse_mode='HTML')
        bot.register_next_step_handler(msg, unmute_user_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== بحث عن مستخدم =====
    if call.data == "admin_search_user" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id,
            "🔍 <b>ابحث عن مستخدم</b>\n\nأرسل يوزر أو ID:\nمثال: @username أو 123456789", parse_mode='HTML')
        bot.register_next_step_handler(msg, search_user_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== إجراءات سريعة على مستخدم =====
    if call.data.startswith("act_") and is_admin(user_id):
        parts = call.data.split("_")
        action = parts[1]
        target_id = int(parts[2])
        extra = parts[3] if len(parts) > 3 else None

        if action == "ban":
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ تم الحظر")
            try: bot.send_message(target_id, "🚫 <b>تم حظرك.</b>", parse_mode='HTML')
            except: pass

        elif action == "unban":
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, "✅ تم فك الحظر")
            try: bot.send_message(target_id, "✅ <b>تم فك الحظر.</b>", parse_mode='HTML')
            except: pass

        elif action == "mute":
            hours = int(extra) if extra else 24
            muted_until = (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S') if hours > 0 else None
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("UPDATE users SET is_muted=1, muted_until=? WHERE user_id=?", (muted_until, target_id))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, f"✅ تم الكتم {hours}h")
            try: bot.send_message(target_id, f"🔇 <b>تم كتمك {hours} ساعة.</b>", parse_mode='HTML')
            except: pass

        elif action == "unmute":
            _unmute_user(target_id)
            bot.answer_callback_query(call.id, "✅ تم فك الكتم")
            try: bot.send_message(target_id, "🔊 <b>تم فك الكتم.</b>", parse_mode='HTML')
            except: pass

        elif action == "info":
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT username,first_name,join_date,is_banned,is_muted,total_donated,avg_rating,rating_count FROM users WHERE user_id=?", (target_id,))
            row = c.fetchone()
            c.execute("SELECT COUNT(*) FROM user_exchanges_history WHERE user_id=?", (target_id,))
            ex_count = c.fetchone()[0]
            c.execute("SELECT channel_username,channel_name,is_active FROM exchange_channels WHERE owner_id=?", (target_id,))
            ch = c.fetchone()
            conn.close()
            if row:
                uname, fname, jdate, banned, muted, donated, avg_r, r_count = row
                status = "🔴 محظور" if banned else ("🟡 مكتوم" if muted else "🟢 نشط")
                text = (f"📊 <b>معلومات المستخدم</b>\n\n"
                        f"👤 {fname}\n🆔 <code>{target_id}</code>\n"
                        f"📛 @{uname}\n📅 {jdate[:10]}\n"
                        f"📊 {status}\n💰 {donated}⭐\n"
                        f"⭐ {get_rating_stars(avg_r)} ({r_count} تقييم)\n"
                        f"🔄 {ex_count} تبادل\n")
                if ch:
                    text += f"📢 قناته: {ch[1]} {'✅' if ch[2] else '❌'}"
            else:
                text = f"❌ مستخدم <code>{target_id}</code> غير موجود في DB"
            markup = user_action_menu(target_id, fname if row else str(target_id))
            try:
                bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                      reply_markup=markup, parse_mode='HTML')
            except:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
            bot.answer_callback_query(call.id)
            return

        elif action == "exchanges":
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("""SELECT partner_id,partner_channel,exchange_date,is_active
                         FROM user_exchanges_history WHERE user_id=? ORDER BY exchange_date DESC LIMIT 10""", (target_id,))
            exs = c.fetchall()
            conn.close()
            text = f"📋 <b>تبادلات</b> <code>{target_id}</code>:\n\n"
            for pid, pch, exdate, active in exs:
                text += f"• {pch} {'✅' if active else '❌'} | {exdate[:16]}\n"
            if not exs:
                text += "لا توجد تبادلات."
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🔙 رجوع", callback_data=f"act_info_{target_id}"))
            try:
                bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                      reply_markup=markup, parse_mode='HTML')
            except:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
            bot.answer_callback_query(call.id)
            return

        # بعد حظر/كتم/فك — أعد تحميل info
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT username,first_name,is_banned,is_muted,total_donated,avg_rating,rating_count FROM users WHERE user_id=?", (target_id,))
        row = c.fetchone()
        conn.close()
        if row:
            uname, fname, banned, muted, donated, avg_r, r_count = row
            status = "🔴 محظور" if banned else ("🟡 مكتوم" if muted else "🟢 نشط")
            text = (f"📊 <b>معلومات المستخدم</b>\n\n"
                    f"👤 {fname} | 🆔 <code>{target_id}</code>\n"
                    f"📛 @{uname}\n📊 {status}\n💰 {donated}⭐")
            try:
                bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                      reply_markup=user_action_menu(target_id, fname), parse_mode='HTML')
            except: pass
        return

    # ===== إحصائيات =====
    if call.data == "admin_stats" and is_admin(user_id):
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); uc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM exchange_channels WHERE is_active=1"); ac = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM exchange_channels"); tc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM waiting_queue"); wc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM completed_exchanges WHERE user1_confirmed=1 AND user2_confirmed=1"); cc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM donations"); dc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bot_warnings WHERE is_resolved=0"); warnc = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM force_channels"); fc = c.fetchone()[0]
        conn.close()
        text = (f"📊 <b>إحصائيات البوت</b>\n\n"
                f"👥 المستخدمين: <b>{uc}</b>\n📢 قنوات اجبارية: <b>{fc}</b>\n"
                f"🔄 قنوات التبادل: <b>{tc}</b> (نشطة: {ac})\n"
                f"⏳ الانتظار: <b>{wc}</b>\n✅ تبادلات مكتملة: <b>{cc}</b>\n"
                f"💰 تبرعات: <b>{dc}</b>\n⚠️ تحذيرات: <b>{warnc}</b>\n⭐ {get_bot_rating()}")
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== قائمة المستخدمين =====
    if call.data == "admin_users_list" and is_admin(user_id):
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT user_id,first_name,username,is_banned,is_muted,total_donated,join_date FROM users ORDER BY join_date DESC LIMIT 30")
        users = c.fetchall()
        conn.close()
        text = "📋 <b>المستخدمين (آخر 30):</b>\n\n"
        for uid, fname, uname, banned, muted, donated, jdate in users:
            st = "🔴" if banned else ("🟡" if muted else "🟢")
            text += f"{st} <b>{fname}</b> <code>{uid}</code>"
            if uname: text += f" @{uname}"
            if donated > 0: text += f" 💰{donated}⭐"
            text += f"\n"
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== فحص الاشتراكات =====
    if call.data == "admin_check_subs" and is_admin(user_id):
        bot.answer_callback_query(call.id, "🔄 جاري الفحص...")
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        users = c.fetchall()
        conn.close()
        not_sub = [u[0] for u in users if not check_force_subscription(u[0])]
        text = f"🔍 <b>فحص الاشتراكات الاجبارية</b>\n\n👥 {len(users)} | ✅ {len(users)-len(not_sub)} | ❌ {len(not_sub)}\n\n"
        for uid in not_sub[:10]:
            ui = get_user_info(uid)
            text += f"• {ui['first_name']} <code>{uid}</code>\n"
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        return

    # ===== إشعار عام =====
    if call.data == "admin_broadcast" and is_admin(user_id):
        msg = bot.send_message(call.message.chat.id, "📢 <b>أرسل نص الإشعار:</b>", parse_mode='HTML')
        bot.register_next_step_handler(msg, broadcast_step, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    # ===== فحص القنوات =====
    if call.data == "check_all_channels" and is_admin(user_id):
        bot.answer_callback_query(call.id, "🔄 جاري الفحص...")
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT owner_id,channel_id,channel_username,channel_name FROM exchange_channels WHERE is_active=1")
        channels = c.fetchall()
        checked = removed = 0
        for owner_id, ch_id, ch_uname, ch_name in channels:
            checked += 1
            ref = ch_id if ch_id else ch_uname
            if not check_bot_admin_status(ref):
                removed += 1
                c.execute("UPDATE exchange_channels SET is_active=0 WHERE " + ("channel_id=?" if ch_id else "channel_username=?"), (ch_id if ch_id else ch_uname,))
                try: bot.send_message(owner_id, f"⚠️ البوت ليس مشرفاً في {ch_name}!", parse_mode='HTML')
                except: pass
        conn.commit()
        conn.close()
        bot.edit_message_text(f"🔍 <b>نتيجة الفحص</b>\n✅ فُحص: {checked}\n⚠️ مُعطَّل: {removed}",
                              chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        return

    # ===== تحذيرات البوت =====
    if call.data == "admin_warnings" and is_admin(user_id):
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT id,channel_id,channel_name,owner_id,warning_date FROM bot_warnings WHERE is_resolved=0 ORDER BY warning_date DESC LIMIT 20")
        warnings = c.fetchall()
        conn.close()
        text = "⚠️ <b>التحذيرات:</b>\n\n" if warnings else "📭 لا توجد تحذيرات"
        for wid, cid, cname, oid, wdate in warnings:
            oi = get_user_info(oid)
            text += f"#{wid} {cname} | {oi['first_name']} <code>{oid}</code> | {wdate[:16]}\n"
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

    # ===== التبادلات المكتملة =====
    if call.data == "admin_completed" and is_admin(user_id):
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("""SELECT id,user1_id,user1_channel,user2_id,user2_channel,exchange_date
                     FROM completed_exchanges WHERE user1_confirmed=1 AND user2_confirmed=1
                     ORDER BY exchange_date DESC LIMIT 15""")
        exs = c.fetchall()
        conn.close()
        text = "✅ <b>التبادلات المكتملة:</b>\n\n" if exs else "📭 لا توجد تبادلات"
        for ex_id, u1_id, u1_ch, u2_id, u2_ch, ex_date in exs:
            u1i = get_user_info(u1_id)
            u2i = get_user_info(u2_id)
            text += f"#{ex_id} {u1i['first_name']} ↔ {u2i['first_name']}\n{u1_ch} ↔ {u2_ch}\n📅 {ex_date[:16]}\n\n"
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              reply_markup=get_admin_panel(), parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return

# ================= دوال الخطوات =================

def save_channel_step(message, original_msg_id):
    user_id = message.from_user.id
    channel = message.text.strip()
    try:
        chat = bot.get_chat(channel)
        if chat.type != 'channel':
            bot.reply_to(message, "❌ ليس معرف قناة — يجب أن يبدأ بـ @")
            return
        if not check_bot_admin_status(channel):
            bot.reply_to(message,
                f"❌ <b>البوت ليس مشرفاً في {channel}</b>\n\n"
                f"1. اذهب لقناتك\n2. إدارة القناة ← المشرفين\n"
                f"3. أضف @{bot.get_me().username} كمشرف\n"
                f"4. فعّل صلاحية نشر المحتوى\n5. أعد المحاولة", parse_mode='HTML')
            return
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("DELETE FROM exchange_channels WHERE owner_id=?", (user_id,))
        c.execute("INSERT INTO exchange_channels (owner_id,channel_id,channel_username,channel_name,added_date,is_active) VALUES (?,?,?,?,?,1)",
                  (user_id, chat.id, channel, chat.title, datetime.now()))
        conn.commit()
        conn.close()
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔙 للقائمة", callback_data="back_to_main"))
        bot.reply_to(message,
            f"✅ <b>تم إضافة القناة</b>\n\n📢 {chat.title}\n🔗 {channel}\n🔢 ID: <code>{chat.id}</code>\n\n🔒 الفحص يعمل حتى لو تغير اليوزر",
            reply_markup=markup, parse_mode='HTML', disable_web_page_preview=True)
        try: bot.delete_message(message.chat.id, original_msg_id)
        except: pass
    except Exception as e:
        bot.reply_to(message, f"❌ لا يمكن الوصول للقناة\n({e})")

def add_force_channel_step(message, original_msg_id):
    """
    يقبل أي من:
    - @username          (قناة عامة)
    - -100ID             (قناة عامة بـ ID)
    - https://t.me/+xxx  (رابط دعوة خاص — يُستخدم للزر والتحقق)
    - https://t.me/+xxx\nاسم مخصص  (رابط + اسم)
    """
    lines = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
    if not lines:
        bot.reply_to(message, "❌ أرسل معرف القناة أو رابط الدعوة")
        return

    first = lines[0]
    is_invite_link = first.startswith("https://t.me/+") or first.startswith("http://t.me/+")

    if is_invite_link:
        # رابط دعوة خاص — لا يمكن get_chat عليه
        invite_link = first
        # الاسم: السطر الثاني إذا موجود، وإلا "قناة خاصة"
        channel_name = lines[1] if len(lines) > 1 else "قناة خاصة"
        # channel_id = الرابط نفسه (يُستخدم للتحقق من الاشتراك)
        channel_id = invite_link
        channel_link = invite_link

        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM force_channels WHERE channel_id=?", (channel_id,))
        if c.fetchone()[0] > 0:
            bot.reply_to(message, "❌ هذا الرابط موجود مسبقاً")
            conn.close()
            return
        c.execute("INSERT INTO force_channels (channel_id,channel_name,channel_link,added_by,added_date) VALUES (?,?,?,?,?)",
                  (channel_id, channel_name, channel_link, message.from_user.id, datetime.now()))
        conn.commit()
        conn.close()
        bot.reply_to(message,
            f"✅ <b>تم إضافة القناة الاجبارية</b>\n\n"
            f"📢 {channel_name}\n🔗 {invite_link}\n\n"
            f"⚠️ <b>ملاحظة:</b> التحقق من الاشتراك في القنوات الخاصة يعتمد على أن البوت عضو فيها.",
            parse_mode='HTML')
        try: bot.delete_message(message.chat.id, original_msg_id)
        except: pass
    else:
        # @username أو ID رقمي — نتحقق عبر API
        channel = first
        custom_link = lines[1] if len(lines) > 1 and lines[1].startswith("http") else None
        try:
            chat = bot.get_chat(channel)
            if chat.type != 'channel':
                bot.reply_to(message, "❌ ليس قناة — تأكد من المعرف")
                return
            conn = sqlite3.connect('data.db')
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM force_channels WHERE channel_id=?", (channel,))
            if c.fetchone()[0] > 0:
                bot.reply_to(message, "❌ القناة موجودة مسبقاً")
                conn.close()
                return
            c.execute("INSERT INTO force_channels (channel_id,channel_name,channel_link,added_by,added_date) VALUES (?,?,?,?,?)",
                      (channel, chat.title, custom_link, message.from_user.id, datetime.now()))
            conn.commit()
            conn.close()
            link_info = f"\n🔗 رابط خاص: {custom_link}" if custom_link else ""
            bot.reply_to(message,
                f"✅ <b>تم إضافة القناة الاجبارية</b>\n\n📢 {chat.title}\n🆔 {channel}{link_info}",
                parse_mode='HTML')
            try: bot.delete_message(message.chat.id, original_msg_id)
            except: pass
        except Exception as e:
            bot.reply_to(message, f"❌ لا يمكن الوصول للقناة\n({e})")

def ban_user_step(message, original_msg_id):
    result = resolve_user(message.text.strip())
    if not result:
        bot.reply_to(message, "❌ المستخدم غير موجود — تأكد من اليوزر أو ID")
        return
    target_id, target_name = result
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id=?", (target_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(message, f"❌ المستخدم <code>{target_id}</code> لم يستخدم البوت بعد", parse_mode='HTML')
        conn.close()
        return
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ <b>تم حظر {target_name}</b> (<code>{target_id}</code>)", parse_mode='HTML')
    try: bot.send_message(target_id, "🚫 <b>تم حظرك من استخدام البوت.</b>", parse_mode='HTML')
    except: pass
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

def unban_user_step(message, original_msg_id):
    result = resolve_user(message.text.strip())
    if not result:
        bot.reply_to(message, "❌ المستخدم غير موجود")
        return
    target_id, target_name = result
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ <b>تم فك الحظر عن {target_name}</b>", parse_mode='HTML')
    try: bot.send_message(target_id, "✅ <b>تم فك الحظر عنك.</b>", parse_mode='HTML')
    except: pass
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

def mute_user_step(message, original_msg_id):
    parts = message.text.strip().split()
    if not parts:
        bot.reply_to(message, "❌ أرسل يوزر أو ID")
        return
    result = resolve_user(parts[0])
    if not result:
        bot.reply_to(message, "❌ المستخدم غير موجود")
        return
    target_id, target_name = result
    try:
        hours = int(parts[1]) if len(parts) > 1 else 24
    except ValueError:
        hours = 24
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    muted_until = (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S') if hours > 0 else None
    dur = f"{hours} ساعة" if hours > 0 else "دائم"
    c.execute("UPDATE users SET is_muted=1, muted_until=? WHERE user_id=?", (muted_until, target_id))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ <b>تم كتم {target_name} — {dur}</b>", parse_mode='HTML')
    try: bot.send_message(target_id, f"🔇 <b>تم كتمك {dur}</b>", parse_mode='HTML')
    except: pass
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

def unmute_user_step(message, original_msg_id):
    result = resolve_user(message.text.strip())
    if not result:
        bot.reply_to(message, "❌ المستخدم غير موجود")
        return
    target_id, target_name = result
    _unmute_user(target_id)
    bot.reply_to(message, f"✅ <b>تم فك الكتم عن {target_name}</b>", parse_mode='HTML')
    try: bot.send_message(target_id, "🔊 <b>تم فك الكتم عنك.</b>", parse_mode='HTML')
    except: pass
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

def search_user_step(message, original_msg_id):
    result = resolve_user(message.text.strip())
    if not result:
        bot.reply_to(message, "❌ لم يُعثر على المستخدم — تأكد من اليوزر أو ID")
        return
    target_id, target_name = result
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT username,first_name,join_date,is_banned,is_muted,total_donated,avg_rating,rating_count FROM users WHERE user_id=?", (target_id,))
    row = c.fetchone()
    c.execute("SELECT COUNT(*) FROM user_exchanges_history WHERE user_id=?", (target_id,))
    ex_count = c.fetchone()[0]
    c.execute("SELECT channel_username,channel_name,is_active FROM exchange_channels WHERE owner_id=?", (target_id,))
    ch = c.fetchone()
    conn.close()
    if row:
        uname, fname, jdate, banned, muted, donated, avg_r, r_count = row
        status = "🔴 محظور" if banned else ("🟡 مكتوم" if muted else "🟢 نشط")
        text = (f"📊 <b>معلومات المستخدم</b>\n\n"
                f"👤 {fname}\n🆔 <code>{target_id}</code>\n"
                f"📛 @{uname}\n📅 {jdate[:10] if jdate else 'غير معروف'}\n"
                f"📊 {status}\n💰 {donated}⭐\n"
                f"⭐ {get_rating_stars(avg_r) if avg_r else '—'} ({r_count} تقييم)\n"
                f"🔄 {ex_count} تبادل\n")
        if ch:
            text += f"📢 قناته: {ch[1]} ({ch[0]}) {'✅' if ch[2] else '❌'}"
    else:
        text = f"⚠️ المستخدم <code>{target_id}</code> غير موجود في DB\n(لم يستخدم البوت بعد)", 
        text = text[0]
    try:
        bot.edit_message_text(text, chat_id=message.chat.id, message_id=original_msg_id,
                              reply_markup=user_action_menu(target_id, target_name), parse_mode='HTML')
    except:
        bot.reply_to(message, text, reply_markup=user_action_menu(target_id, target_name), parse_mode='HTML')
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass

def broadcast_step(message, original_msg_id):
    text = message.text
    conn = sqlite3.connect('data.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned=0")
    users = c.fetchall()
    conn.close()
    success = fail = 0
    status_msg = bot.reply_to(message, f"🔄 إرسال لـ {len(users)} مستخدم...")
    for (uid,) in users:
        try:
            bot.send_message(uid, f"📢 <b>إشعار:</b>\n\n{text}", parse_mode='HTML')
            success += 1
            time.sleep(0.05)
        except:
            fail += 1
    try:
        bot.edit_message_text(f"✅ {success} نجح | ❌ {fail} فشل",
                              chat_id=status_msg.chat.id, message_id=status_msg.message_id)
    except: pass
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

def custom_payment_step(message, original_msg_id):
    try:
        amount = int(message.text.strip())
        if not 1 <= amount <= 1000:
            bot.reply_to(message, "❌ بين 1 و 1000")
            return
        if send_stars_invoice(message.chat.id, amount):
            bot.reply_to(message, f"✅ فاتورة {amount} ⭐ — اضغط 'دفع'")
        else:
            bot.reply_to(message, "❌ خطأ في إنشاء الفاتورة")
        try: bot.delete_message(message.chat.id, original_msg_id)
        except: pass
    except ValueError:
        bot.reply_to(message, "❌ أدخل رقماً صحيحاً")

def get_user_to_rate_step(message, original_msg_id):
    result = resolve_user(message.text.strip())
    if not result:
        bot.reply_to(message, "❌ لم يُعثر على المستخدم")
        return
    target_id, target_name = result
    if target_id == message.from_user.id:
        bot.reply_to(message, "❌ لا يمكنك تقييم نفسك!")
        return
    markup = telebot.types.InlineKeyboardMarkup(row_width=5)
    markup.add(*[telebot.types.InlineKeyboardButton(f"{i}⭐", callback_data=f"rate_user_{target_id}_{i}") for i in range(1, 6)])
    bot.reply_to(message, f"⭐ <b>تقييم {target_name}:</b>\n\nاختر:", reply_markup=markup, parse_mode='HTML')
    try: bot.delete_message(message.chat.id, original_msg_id)
    except: pass

# ================= الدفع =================

@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout(query):
    try:
        bot.answer_pre_checkout_query(query.id, ok=True)
    except Exception as e:
        print(f"خطأ pre_checkout: {e}")

@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    try:
        payment = message.successful_payment
        user_id = message.from_user.id
        stars = payment.total_amount
        pay_id = payment.telegram_payment_charge_id
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        uinfo = get_user_info(user_id)
        c.execute("INSERT INTO donations (user_id,username,stars_amount,donation_date,telegram_payment_id,status) VALUES (?,?,?,?,?,'completed')",
                  (user_id, uinfo['username'], stars, datetime.now(), pay_id))
        c.execute("UPDATE users SET total_donated=total_donated+? WHERE user_id=?", (stars, user_id))
        conn.commit()
        conn.close()
        bot.send_message(user_id, f"🎉 <b>شكراً لدعمك!</b>\n\n💰 {stars} ⭐\n📊 إجمالي تبرعاتك: {get_user_donations(user_id)} ⭐ 🙏", parse_mode='HTML')
        bot.send_message(ADMIN_ID, f"💰 <b>تبرع جديد!</b>\n👤 {uinfo['first_name']} <code>{user_id}</code>\n⭐ {stars}\n📊 الإجمالي: {get_total_donations()} ⭐", parse_mode='HTML')
    except Exception as e:
        print(f"خطأ الدفع: {e}")

# ================= تقييم المستخدم (callback منفصل) =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_user_"))
def save_user_rating(call):
    try:
        parts = call.data.split("_")
        target_id = int(parts[2])
        rating = int(parts[3])
        rated_by = call.from_user.id
        if rated_by == target_id:
            bot.answer_callback_query(call.id, "❌ لا يمكنك تقييم نفسك!", show_alert=True)
            return
        conn = sqlite3.connect('data.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_ratings WHERE user_id=? AND rated_by=?", (target_id, rated_by))
        if c.fetchone()[0] > 0:
            bot.answer_callback_query(call.id, "❌ قيّمته مسبقاً!", show_alert=True)
            conn.close()
            return
        c.execute("INSERT INTO user_ratings (user_id,rated_by,rating,rating_date) VALUES (?,?,?,?)", (target_id, rated_by, rating, datetime.now()))
        c.execute("SELECT AVG(rating),COUNT(*) FROM user_ratings WHERE user_id=?", (target_id,))
        avg, count = c.fetchone()
        c.execute("UPDATE users SET avg_rating=?,rating_count=? WHERE user_id=?", (avg, count, target_id))
        conn.commit()
        conn.close()
        uinfo = get_user_info(target_id)
        bot.answer_callback_query(call.id, f"✅ {uinfo['first_name']} — {rating} نجوم")
        bot.edit_message_text(f"✅ <b>تم التقييم!</b>\n👤 {uinfo['first_name']}\n⭐ {get_rating_stars(rating)} ({rating}/5)",
                              chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML')
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

# ================= تشغيل البوت =================

if __name__ == "__main__":
    init_db()
    threading.Thread(target=check_all_channels_periodically, daemon=True).start()
    threading.Thread(target=check_all_exchanges_subscriptions, daemon=True).start()
    threading.Thread(target=send_db_backup_periodically, daemon=True).start()

    print("=" * 60)
    print("✅ بوت تبادل القنوات يعمل")
    print(f"👤 المالك: {ADMIN_ID}")
    print("=" * 60)
    print("📢 القنوات الاجبارية تدعم روابط خاصة (خاصة/عامة)")
    print("🔍 أوامر الأدمن تقبل @username أو ID")
    print("🚫 المنع بالقناة لا بالشخص")
    print("💾 DB محفوظة بين كل إعادة تشغيل")
    print("🔄 فحص اشتراكات التبادل كل دقيقة")
    print("🗄 نسخة DB كل 30 دقيقة")
    print("=" * 60)

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"خطأ: {e}")
            time.sleep(10)
