# ✅ CBH-AI-Trading-Bot: 修复后的 main.py
import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, 
                          CallbackContext, PicklePersistence, CallbackQueryHandler)
import requests
from openai import OpenAI
import base64
from PIL import Image
from datetime import datetime, date
from supabase import create_client
from prompts import PROMPT_ANALYST_V2

# --- 日志设置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 配置读取 ---
AI_MODEL_NAME = 'gpt-4o'
client = None
if api_key := os.getenv("OPENAI_API_KEY"):
    client = OpenAI(api_key=api_key)
else:
    logger.critical("OPENAI_API_KEY 未设置！")

FMP_API_KEY = os.getenv("FMP_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 多语言支持 ---
LANGUAGES = {
    "start_welcome": {
        "cn": "欢迎使用 CBH AI 交易助手 (MVP v1.1 - 交互版)！",
        "en": "Welcome to CBH AI Trading Assistant (MVP v1.1 - Interactive)!"
    },
    "start_features": {
        "cn": "**核心功能:**\n1️⃣ **/analyze**: 上传图表，获取专业AI分析。\n2️⃣ **/price**: 获取实时行情。\n3️⃣ **/language**: 切换语言。\n4️⃣ **/help**: 所有指令",
        "en": "**Core Features:**\n1️⃣ **/analyze**: Upload a chart for AI analysis.\n2️⃣ **/price**: Get real-time price.\n3️⃣ **/language**: Set your language.\n4️⃣ **/help**: List commands."
    }
}

def get_text(key, lang_code):
    lang = lang_code if lang_code in ["en", "cn"] else "en"
    return LANGUAGES[key][lang]

# --- 指令处理 ---
def start(update: Update, context: CallbackContext) -> None:
    context.user_data.setdefault('lang', 'both')
    lang = context.user_data['lang']
    update.message.reply_text(
        f"{get_text('start_welcome', lang)}\n\n{get_text('start_features', lang)}",
        parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Available Commands:\n/start\n/help\n/price\n/analyze\n/language\n/user")

def language(update: Update, context: CallbackContext) -> None:
    keyboard = [["English Only"], ["中文"], ["English + 中文 (Both)"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("Please select your preferred language:", reply_markup=reply_markup)

def set_language(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    lang_map = {"English Only": "en", "中文": "cn", "English + 中文 (Both)": "both"}
    context.user_data['lang'] = lang_map.get(text, 'both')
    update.message.reply_text(f"语言设置为: {context.user_data['lang']}")

# --- 行情 ---
def get_price(symbol: str) -> dict:
    url = f"https://financialmodelingprep.com/api/v3/quote/{symbol.upper()}?apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            q = data[0]
            return {"name": q.get("name", symbol), "price": q.get("price"), "change": q.get("change", 0), "changesPercentage": q.get("changesPercentage", 0)}
        return {"error": "无数据"}
    except Exception as e:
        return {"error": str(e)}

def price_command(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton("🥇 黄金 (XAUUSD)", callback_data='price_XAUUSD')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('请选择您想查询的交易对:', reply_markup=reply_markup)

def button_callback_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    _, symbol = query.data.split('_', 1)
    query.edit_message_text(f"正在查询 {symbol}...")
    data = get_price(symbol)
    if "error" in data:
        query.edit_message_text(f"❌ {data['error']}")
    else:
        change_sign = "📈" if data["change"] > 0 else "📉"
        query.edit_message_text(f"**{symbol}**\n当前价格: `{data['price']}`\n{change_sign} 变化: `{data['change']} ({data['changesPercentage']:.2f}%)`", parse_mode='Markdown')

# --- 图像分析 ---
def analyze_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Please upload a chart image (JPG/PNG) now.")

def analyze_chart(image_path: str, lang: str) -> str:
    prompt = PROMPT_ANALYST_V2.get(lang, PROMPT_ANALYST_V2['en'])
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = client.chat.completions.create(
            model=AI_MODEL_NAME,
            messages = [
              {"role": "user", "content": [
        {"type": "text", "text": prompt_text},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
    ),
            max_tokens=600
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ 图像分析失败: {e}"

def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = str(update.effective_user.id)
    today = str(date.today())
    reply = update.message.reply_text("🧠 分析中，请稍候...")
    try:
        record = supabase.table("usage_logs").select("*").eq("user_id", user_id).eq("date", today).execute()
        count = record.data[0]["count"] if record.data else 0
        if count >= 3:
            update.message.reply_text("📌 今日上传次数已达上限（3次/天）。\n🚀 订阅 Pro 版本可享受无限图表分析。")
            return
        elif record.data:
            supabase.table("usage_logs").update({"count": count + 1}).eq("user_id", user_id).eq("date", today).execute()
        else:
            supabase.table("usage_logs").insert({"user_id": user_id, "date": today, "count": 1}).execute()
    except Exception as e:
        logger.error(f"日志记录失败: {e}")

    photo_file = update.message.photo[-1].get_file()
    path = f"temp_{photo_file.file_id}.jpg"
    photo_file.download(path)
    lang = context.user_data.get("lang", "en")
    result = analyze_chart(path, lang)
    reply.edit_text(result)
    os.remove(path)

def user_command(update: Update, context: CallbackContext) -> None:
    user_id = str(update.effective_user.id)
    today = str(date.today())
    try:
        result = supabase.table("usage_logs").select("*").eq("user_id", user_id).eq("date", today).execute()
        count = result.data[0]["count"] if result.data else 0
        update.message.reply_text(f"📊 今日已使用图像分析：{count} 次\n📌 剩余次数：{max(0, 3 - count)} 次")
    except Exception as e:
        update.message.reply_text(f"❌ 查询失败: {e}")

def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.critical("BOT_TOKEN 未设置")
        return

    updater = Updater(bot_token, use_context=True, persistence=PicklePersistence(filename='bot_data'))
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("price", price_command))
    dp.add_handler(CommandHandler("analyze", analyze_command))
    dp.add_handler(CommandHandler("language", language))
    dp.add_handler(CommandHandler("user", user_command))
    dp.add_handler(CallbackQueryHandler(button_callback_handler))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.regex("^(English Only|中文|English \+ 中文 \(Both\))$"), set_language))

    updater.start_polling()
    logger.info("✅ CBH AI 交易助手已启动")
    updater.idle()

if __name__ == '__main__':
    main()
