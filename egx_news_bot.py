import feedparser
import asyncio
import os
import json
import requests
import random
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot
from telegram.constants import ParseMode
import hashlib
from difflib import SequenceMatcher

# --- الإعدادات الأساسية ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- قاموس أكواد الأسهم (Ticker-Company Mapping) ---
TICKER_MAP = {
    "البنك التجاري الدولي": "COMI",
    "التجاري الدولي": "COMI",
    "مجموعة طلعت مصطفى": "TMGH",
    "طلعت مصطفى": "TMGH",
    "السويدي إليكتريك": "SWDY",
    "السويدي": "SWDY",
    "مجموعة إي إف جي القابضة": "HRHO",
    "اي اف جي": "HRHO",
    "حديد عز": "ESRS",
    "عز الدخيلة": "ESRS",
    "أبو قير للأسمدة": "ABUK",
    "فوري": "FWRY",
    "مصر لإنتاج الأسمدة - موبكو": "MFPC",
    "موبكو": "MFPC",
    "الإسكندرية لتداول الحاويات": "ALCN",
    "الشرقية - ايسترن كومباني": "EAST",
    "ايسترن كومباني": "EAST",
    "بالم هيلز": "PHDC",
    "سيدي كرير للبتروكيماويات": "SKPC",
    "سيدبك": "SKPC",
    "أوراسكوم كونستراكشون": "ORAS",
    "جي بي كورب": "AUTO",
    "إعمار مصر": "EMFD",
    "جورميه": "Gourmet_IPO"
}

# --- ملفات البيانات الخارجية ---
FAIR_VALUES_FILE = "fair_values.json"
FAIR_VALUES_DB = {}

def load_fair_values():
    global FAIR_VALUES_DB
    if os.path.exists(FAIR_VALUES_FILE):
        try:
            with open(FAIR_VALUES_FILE, "r", encoding="utf-8") as f:
                FAIR_VALUES_DB = json.load(f)
                print(f"✅ Loaded {len(FAIR_VALUES_DB)} fair value entries.")
        except Exception as e:
            print(f"⚠️ Error loading fair_values.json: {e}")
    else:
        print("⚠️ fair_values.json not found. Fair value data will be skipped.")

# --- إعداد Gemini مع نظام احتياطي ---
model = None
selected_model_name = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    MODEL_LIST = ["gemini-1.5-flash", "gemini-pro"]
    for m in MODEL_LIST:
        try:
            model = genai.GenerativeModel(m)
            selected_model_name = m
            print(f"✅ Model initialized: {selected_model_name}")
            break
        except Exception as e:
            print(f"⚠️ Model {m} not available: {str(e)[:50]}")
            continue
if not model:
    print("❌ Critical Error: No Gemini model found.")

# --- مصادر الأخبار ---
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]
MUBASHER_PULSE_URL = "https://www.mubasher.info/news/eg/pulse/stocks"

# --- الكلمات المفتاحية للفلترة ---
STOCK_KEYWORDS = [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال",
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب",
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية", "موازنة"
]

# --- ملفات الحالة ---
SENT_NEWS_DB_FILE = "sent_news_db.json"

# --- دوال منع التكرار الذكي ---
def is_similar(title1, title2, threshold=0.85):
    """التحقق من تشابه عنوانين بنسبة معينة"""
    return SequenceMatcher(None, title1, title2).ratio() >= threshold

def generate_news_hash(title, link):
    """توليد hash فريد للخبر"""
    return hashlib.md5(f"{title.strip()}_{link.strip()}".encode("utf-8")).hexdigest()

# --- دوال إدارة قاعدة البيانات ---
def load_sent_news_db():
    if os.path.exists(SENT_NEWS_DB_FILE):
        try:
            with open(SENT_NEWS_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Error loading DB: {e}. Starting fresh.")
            return {}
    return {}

def save_sent_news_db(db):
    try:
        # الاحتفاظ بآخر 500 خبر فقط
        keys_to_keep = list(db.keys())[-500:]
        trimmed_db = {k: db[k] for k in keys_to_keep}
        with open(SENT_NEWS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed_db, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"⚠️ Error saving DB: {e}")

# --- دوال التحليل والتنسيق ---
def find_tickers(text):
    """البحث عن أسماء الشركات في النص وإرجاع أكوادها"""
    found_tickers = set()
    for company, ticker in TICKER_MAP.items():
        if company in text:
            found_tickers.add(f"#{ticker}")
    return list(found_tickers)

def get_fair_value_data(tickers):
    """جلب بيانات القيمة العادلة من قاعدة البيانات المحلية"""
    data = {}
    for ticker_tag in tickers:
        ticker = ticker_tag.replace("#", "")
        if ticker in FAIR_VALUES_DB:
            data[ticker] = FAIR_VALUES_DB[ticker]
    return data

def format_fair_value_for_prompt(fair_value_data):
    """تنسيق بيانات القيمة العادلة لتكون مقروءة داخل البرومبت"""
    if not fair_value_data:
        return "لا توجد بيانات قيمة عادلة متاحة لهذا الخبر."
    
    formatted_data = []
    for ticker, data in fair_value_data.items():
        company_name = data["company_names"][0] if data["company_names"] else ticker
        fv = f"{data['fair_value']:.2f}" if data['fair_value'] is not None else "N/A"
        upside = f"{data['upside_percent']:.1f}%" if data['upside_percent'] is not None else "N/A"
        valuation = data['valuation'] if data['valuation'] else "N/A"
        
        formatted_data.append(
            f"- {company_name} ({ticker}): القيمة العادلة {fv} ج.م، إمكانية الصعود {upside}، التقييم الحالي {valuation}."
        )
    return "\n".join(formatted_data)

async def analyze_news_with_gemini(title, description, tickers, fair_value_data):
    if not model:
        return "⚠️ نموذج الذكاء الاصطناعي غير متاح حالياً."

    prompt = f"""أنت محلل أسهم أول في Investing Pro. قم بتحليل الخبر التالي:

**الخبر:** {title}
**التفاصيل:** {description}
**الأسهم المرتبطة:** {', '.join(tickers) if tickers else 'غير محدد'}

**بيانات القيمة العادلة المتاحة (من Investing Pro):**
{format_fair_value_for_prompt(fair_value_data)}

**المطلوب (بأسلوب Investing Pro):**
1.  **التحليل الأساسي:** تأثير الخبر على الأرباح، الإيرادات، والقيمة الدفترية.
2.  **القيمة العادلة (Fair Value):** بناءً على البيانات المتاحة، هل يمكنك تقدير تأثير الخبر على القيمة العادلة للسهم؟ (اذكر "لا يمكن التقدير" إذا كانت البيانات غير كافية).
3.  **التأثير على السهم:** التأثير المتوقع على السعر (صعود/هبوط)، ومستويات الدعم والمقاومة الرئيسية.
4.  **التوصية:** توصية واضحة (شراء/احتفاظ/بيع) مع أفق زمني.

**الأسلوب:** احترافي، موجز، قائم على الأرقام."""

    try:
        response = await model.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        return f"⚠️ خطأ في التحليل: {str(e)[:80]}"

def is_stock_related(title, description):
    content = (title + " " + description).lower()
    return any(keyword in content for keyword in STOCK_KEYWORDS)

# --- الدالة الرئيسية للمعالجة والإرسال ---
async def process_and_send(bot, title, description, link, sent_db):
    # 1. التحقق من الفلترة والكلمات المفتاحية
    if not is_stock_related(title, description):
        return False, "Not stock related"

    # 2. نظام منع التكرار الذكي
    news_hash = generate_news_hash(title, link)
    if news_hash in sent_db:
        return False, "Duplicate hash"

    for existing_hash, existing_data in sent_db.items():
        if is_similar(title, existing_data["title"]):
            print(f"⚠️ Smart De-duplication: Similar title found for '{title[:50]}...'")
            return False, "Similar title"

    # 3. البحث عن أكواد الأسهم
    tickers = find_tickers(title + " " + description)

    # 4. التحليل باستخدام Gemini
    print(f"📰 Processing: {title[:60]}...")
    fair_value_data = get_fair_value_data(tickers)
    analysis = await analyze_news_with_gemini(title, description, tickers, fair_value_data)

    # 5. تنسيق الرسالة
    ticker_hashtags = " ".join(tickers) if tickers else ""
    
    # دمج بيانات القيمة العادلة
    fair_value_section = ""
    if fair_value_data:
        fair_value_section += "\n\n💎 <b>التقييم المالي (Investing Pro Data):</b>\n"
        for ticker, data in fair_value_data.items():
            company_name = data["company_names"][0] if data["company_names"] else ticker
            fv = f"{data['fair_value']:.2f}" if data['fair_value'] is not None else "N/A"
            upside = f"{data['upside_percent']:.1f}%" if data['upside_percent'] is not None else "N/A"
            valuation = data['valuation'] if data['valuation'] else "N/A"
            
            fair_value_section += (
                f"• <b>{company_name} ({ticker}):</b>\n"
                f"  - القيمة العادلة: {fv} ج.م\n"
                f"  - إمكانية الصعود: {upside}\n"
                f"  - التقييم الحالي: {valuation}\n"
            )

    message = (
        f"🏛️ <b>تقرير بحوث البورصة المصرية</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>العنوان:</b>\n{title}\n\n"
        f"🔬 <b>التحليل البحثي المتعمق (Investing Pro Style):</b>\n{analysis}\n"
        f"{fair_value_section}\n"
        f"🔗 <a href='{link}'>المصدر الأصلي</a>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ticker_hashtags}"
    )

    # 6. الإرسال وتحديث قاعدة البيانات
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
        sent_db[news_hash] = {"title": title, "link": link}
        print(f"✅ Sent: {title[:60]}...")
        return True, "Sent"
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False, f"Telegram error: {e}"

# --- دوال جلب الأخبار ---
async def fetch_rss_feeds(bot, sent_db):
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in RSS_FEEDS:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:15]:
                await process_and_send(bot, entry.title, entry.get("summary", ""), entry.link, sent_db)
                await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️ Error fetching RSS {url[:50]}: {e}")

async def fetch_pulse(bot, sent_db):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(MUBASHER_PULSE_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, "html.parser")
        for a in soup.find_all("a", href=True, limit=10):
            if "/news/" in a["href"] and len(a.get_text(strip=True)) > 20:
                link = a["href"] if a["href"].startswith("http") else "https://www.mubasher.info" + a["href"]
                await process_and_send(bot, a.get_text(strip=True), "خبر عاجل من نبض الأسهم", link, sent_db)
                await asyncio.sleep(1)
    except Exception as e:
        print(f"⚠️ Error fetching Pulse: {e}")

# --- نقطة الدخول الرئيسية ---
async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    sent_db = load_sent_news_db()

    print(f"\n🤖 EGX News Bot v4 Started | Model: {selected_model_name or 'N/A'} | Tracked: {len(sent_db)}")
    load_fair_values()

    await fetch_rss_feeds(bot, sent_db)
    await fetch_pulse(bot, sent_db)

    save_sent_news_db(sent_db)
    print(f"\n✅ Cycle completed. Total tracked news: {len(sent_db)}\n")

if __name__ == "__main__":
    asyncio.run(main())
