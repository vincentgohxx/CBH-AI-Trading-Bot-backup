import os
import logging
import base64
from datetime import date
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, 
                          CallbackContext, PicklePersistence, CallbackQueryHandler)
import requests
from openai import OpenAI
from PIL import Image
from supabase import create_client, Client
from prompts import PROMPT_ANALYST_V2 # 确保您使用的是v2

# --- 日志设置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 配置读取 ---
AI_MODEL_NAME = 'gpt-4o'
client = None
if api_key := os.getenv("OPENAI_API_KEY"):
    client = OpenAI(api_key=api_key)
else:
    logger.warning("OPENAI_API_KEY 未设置！AI分析功能将不可用。")

FMP_API_KEY = os.getenv("FMP_API_KEY")

supabase: Client = None
try:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase 客户端初始化成功。")
    else:
        logger.warning("Supabase URL或Key未设置，数据库功能将不可用。")
except Exception as e:
    logger.error(f"Supabase 初始化失败: {e}")

# --- 多语言支持 ---
LANGUAGES = {
    "start_welcome": { "cn": "欢迎使用 CBH AI 交易助手！", "en": "Welcome to CBH AI Trading Assistant!" },
    "start_features": { "cn": "**核心功能:**\n1️⃣ **/analyze**: 上传图表\n2️⃣ **/price**: 实时行情\n3️⃣ **/language**: 切换语言\n4️⃣ **/help**: 所有指令\n5️⃣ **/user**: 查看使用次数", "en": "**Features:**\n1️⃣ /analyze\n2️⃣ /price\n3️⃣ /language\n4️⃣ /help\n5️⃣ /user" }
}

def get_text(key, context: CallbackContext):
    lang_pref = context.user_data.get('lang', 'both')
    if lang_pref == 'en': return LANGUAGES[key].get('en', '...')
    if lang_pref == 'cn': return LANGUAGES[key].get('cn', '...')
    return f"{LANGUAGES[key].get('en', '...')}\n\n{LANGUAGES[key].get('cn', '...')}"

# --- 指令处理 ---
def start(update: Update, context: CallbackContext) -> None:
    context.user_data.setdefault('lang', 'both')
    welcome_text = get_text('start_welcome', context)
    features_text = get_text('start_features', context)
    update.message.reply_text(f"{welcome_text}\n\n{features_text}", parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Available Commands:\n/start\n/help\n/price\n/analyze\n/language\n/user")

def language(update: Update, context: CallbackContext) -> None:
    keyboard = [["English Only"], ["中文"], ["English + 中文 (Both)"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("Please select your preferred language:", reply_markup=reply_markup)

def set_language(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    lang_map = {"English Only": "en", "中文": "cn", "English + 中文 (Both)": "both"}
    lang = lang_map.get(text, 'both')
    context.user_data['lang'] = lang
    update.message.reply_text(f"Language set to: {lang}")

# --- 行情 ---
def get_price(symbol: str) -> dict:
    if not FMP_API_KEY: return {"error": "行情服务未配置。"}
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
        logger.error(f"获取价格失败: {e}")
        return {"error": "API请求失败"}

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
        response_text = f"**{data.get('name', symbol)} ({symbol})**\n当前价格: `{data['price']}`\n{change_sign} 变化: `{data['change']} ({data['changesPercentage']:.2f}%)`"
        query.edit_message_text(response_text, parse_mode='Markdown')

# --- 图像分析 ---
def analyze_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Please upload a chart image (JPG/PNG) now.")

# 【修复】修正了此函数的严重语法错误
def analyze_chart(image_path: str, lang: str) -> str:
    if not client: return "❌ AI服务未配置 (OPENAI_API_KEY缺失)。"
    
    prompt_text = PROMPT_ANALYST_V2.get(lang, PROMPT_ANALYST_V2['en'])
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
        response = client.chat.completions.create(
            model=AI_MODEL_NAME,
            messages=[  # <--- 这里是方括号 [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ], # <--- 这里也必须是配对的方括号 ]
            max_tokens=600
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"图像分析失败: {e}")
        return f"❌ 图像分析失败: {e}"

def handle_photo(update: Update, context: CallbackContext) -> None:
    if supabase:
        user_id = str(update.effective_user.id)
        today = str(date.today())
        try:
            # 使用 .select() with count="exact" 来获取行数
            record = supabase.table("usage_logs").select("user_id", count="exact").eq("user_id", user_id).eq("date", today).execute()
            count = record.count
            
            if count >= 3:
                update.message.reply_text("📌 今日上传次数已达上限（3次/天）。\n🚀 订阅 Pro 版本可享受无限图表分析。")
                return
            
            # 使用 upsert 简化逻辑
            supabase.rpc('increment_usage', {'p_user_id': user_id, 'p_date': today}).execute()

        except Exception as e:
            logger.error(f"日志记录失败: {e}")
    
    reply = update.message.reply_text("🧠 分析中，请稍候...")
    photo_file = update.message.photo[-1].get_file()
    path = f"temp_{photo_file.file_id}.jpg"
    photo_file.download(path)
    lang = context.user_data.get("lang", "cn")
    result = analyze_chart(path, lang)
    reply.edit_text(result)
    os.remove(path)

def user_command(update: Update, context: CallbackContext) -> None:
    if not supabase:
        update.message.reply_text("❌ 数据库服务当前不可用。")
        return
        
    user_id = str(update.effective_user.id)
    today = str(date.today())
    try:
        result = supabase.table("usage_logs").select("count").eq("user_id", user_id).eq("date", today).execute()
        count = result.data[0]['count'] if result.data else 0
        update.message.reply_text(f"📊 今日已使用图像分析：{count} 次\n📌 剩余次数：{max(0, 3 - count)} 次")
    except Exception as e:
        logger.error(f"查询用户次数失败: {e}")
        update.message.reply_text(f"❌ 查询失败: {e}")

def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.critical("BOT_TOKEN 未设置")
        return

    persistence = PicklePersistence(filename='bot_data')
    updater = Updater(bot_token, use_context=True, persistence=persistence)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("price", price_command))
    dispatcher.add_handler(CommandHandler("analyze", analyze_command))
    dispatcher.add_handler(CommandHandler("language", language))
    dispatcher.add_handler(CommandHandler("user", user_command))
    dispatcher.add_handler(CallbackQueryHandler(button_callback_handler))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
    dispatcher.add_handler(MessageHandler(Filters.regex("^(English Only|中文|English \+ 中文 \(Both\))$"), set_language))

    updater.start_polling()
    logger.info("✅ CBH AI 交易助手已启动")
    updater.idle()

if __name__ == '__main__':
    main()
