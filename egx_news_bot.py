import feedparser
import asyncio
import os
import json
import requests
import re
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.generativeai.errors import APIError
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
    "البنك التجاري الدولي": "COMI", "التجاري الدولي": "COMI", "مجموعة طلعت مصطفى": "TMGH",
    "طلعت مصطفى": "TMGH", "السويدي إليكتريك": "SWDY", "السويدي": "SWDY",
    "مجموعة إي إف جي القابضة": "HRHO", "اي اف جي": "HRHO", "حديد عز": "ESRS",
    "عز الدخيلة": "ESRS", "أبو قير للأسمدة": "ABUK", "فوري": "FWRY",
    "مصر لإنتاج الأسمدة - موبكو": "MFPC", "موبكو": "MFPC", "الإسكندرية لتداول الحاويات": "ALCN",
    "الشرقية - ايسترن كومباني": "EAST", "ايسترن كومباني": "EAST", "بالم هيلز": "PHDC",
    "سيدي كرير للبتروكيماويات": "SKPC", "سيدبك": "SKPC", "أوراسكوم كونستراكشون": "ORAS",
    "جي بي كورب": "AUTO", "إعمار مصر": "EMFD", "مينا للاستثمار السياحي والعقاري": "MENA",
    "العامة لمنتجات الخزف والصيني": "PRCL", "جنوب الوادى للأسمنت": "SVCE",
    "الدولية للمحاصيل الزراعية": "IFAP", "العربية للخزف سيراميكا": "CERA",
    "العز للسيراميك والبورسلين": "ECAP", "العربية لحليج الأقطان": "ACGC",
    "مجموعة عامر القابضة": "AMER", "النصر للملابس والمنسوجات": "KABO",
    "المطورون العرب القابضة": "ARAB", "طاقة عربية ش.م.م": "TAQA", "العبوات الطبية": "MEPA",
    "المصرف المتحد": "UBEE", "العبور للاستثمار العقاري": "OBRI",
    "الاستثمار العقاري العربي": "RREI", "مصرف أبو ظبي الإسلامي - مصر": "ADIB",
    "نهر الخير للتنمية": "KRDI", "ممفيس للأدوية": "MPCI", "مصر للألومنيوم": "EGAL",
    "مصر للأسمنت": "MCQE", "مصر الوطنية للصلب": "ATQA", "مصر الجديدة للاسكان": "HELI",
    "مدينة نصر للاسكان": "MASR", "ماكرو جروب": "MCRO", "ليسيكو مصر": "LCSW",
    "كونتكت المالية": "CNFN", "فالمور القابضة": "VLMRA", "غاز مصر": "EGAS",
    "عبور لاند": "OLFI", "مستشفى كليوباترا": "CLHO", "القلعة للاستشارات": "CCAP",
    "زهراء المعادي": "ZMID", "راية القابضة": "RAYA", "دايس للملابس": "DSCW",
    "جهينة للصناعات الغذائية": "JUFO", "بي إنفستمنتس": "BINV", "كريدي أجريكول": "CIEB",
    "بنك التعمير والإسكان": "HDBK", "بلتون المالية": "BTFH", "بايونيرز بروبرتيز": "PRDC",
    "اي فاينانس": "EFIH", "ام.ام جروب": "MTIE", "النساجون الشرقيون": "ORWE",
    "المنصورة للدواجن": "MPCO", "الملتقى العربي": "AMIA", "المصرية لمدينة الإنتاج الإعلامي": "MPRC",
    "المصرية للمنتجعات": "EGTS", "المصرية للاتصالات": "ETEL", "المصرية لخدمات النقل": "ETRS",
    "المصرية الدولية للصناعات الدوائية": "PHAR"
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
    MODEL_LIST = ["gemini-1.5-flash-latest", "gemini-1.5-pro-latest", "gemini-pro"]
    for m in MODEL_LIST:
        try:
            model = genai.GenerativeModel(m)
            selected_model_name = m
            print(f"✅ Model initialized: {selected_model_name}")
            break
        except Exception as e:
            print(f"⚠️ Model {m} not available: {str(e)[:50]}")
            continue

# --- مصادر الأخبار ---
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]
MUBASHER_PULSE_URL = "https://www.mubasher.info/news/eg/pulse/stocks"

# --- الكلمات المفتاحية للفلترة ---
STOCK_KEYWORDS = list(TICKER_MAP.keys()) + [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال",
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب",
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية", "موازنة"
]

# --- ملفات الحالة ---
SENT_NEWS_DB_FILE = "sent_news_db.json"

# --- دوال منع التكرار الذكي ---
def is_similar(title1, title2, threshold=0.85):
    return SequenceMatcher(None, title1, title2).ratio() >= threshold

def generate_news_hash(title, link):
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
        keys_to_keep = list(db.keys())[-500:]
        trimmed_db = {k: db[k] for k in keys_to_keep}
        with open(SENT_NEWS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed_db, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"⚠️ Error saving DB: {e}")

# --- دوال التحليل والتنسيق ---
def find_tickers(text):
    found_tickers = set()
    for company, ticker in TICKER_MAP.items():
        if company in text:
            found_tickers.add(f"#{ticker}")
    return list(found_tickers)

def get_fair_value_data(tickers):
    data = {}
    for ticker_tag in tickers:
        ticker = ticker_tag.replace("#", "")
        if ticker in FAIR_VALUES_DB:
            data[ticker] = FAIR_VALUES_DB[ticker]
    return data

def format_fair_value_for_prompt(fair_value_data):
    if not fair_value_data:
        return "لا توجد بيانات قيمة عادلة متاحة لهذا الخبر."
    formatted_data = []
    for ticker, data in fair_value_data.items():
        company_name = data.get('company_names', [ticker])[0]
        fv_val = data.get('fair_value')
        fv = f"{fv_val:.2f}" if fv_val is not None else "N/A"
        upside_val = data.get('upside_percent')
        upside = f"{upside_val:.1f}%" if upside_val is not None else "N/A"
        valuation = data.get('valuation', 'N/A')
        formatted_data.append(
            f"- {company_name} ({ticker}): القيمة العادلة {fv} ج.م، فرصة الصعود {upside}، التقييم الحالي {valuation}."
        )
    return "\n".join(formatted_data)

async def analyze_news_with_gemini(title, fair_value_data):
    if not model:
        return None

    prompt = f"""أنت محلل مالي رقمي سريع. مهمتك هي تحويل الخبر التالي إلى بطاقة تحليل سريعة للمستثمر.

**البيانات المتاحة:**
- **الخبر:** {title}
- **بيانات Investing Pro:**
{format_fair_value_for_prompt(fair_value_data)}

**المطلوب (بشكل مباشر ومختصر جداً، استخدم هذا التنسيق بالضبط):**
الخلاصة:
• [اكتب هنا نقطة موجزة ومباشرة عن تأثير الخبر]
• [اكتب هنا نقطة رقمية إن أمكن، مثال: زيادة متوقعة 10%]
• [اكتب هنا نقطة عن الشعور العام: إيجابي/سلبي/محايد]
مؤشر الثقة: [رقم من 1 إلى 10]
قرار المحلل: [شراء/احتفاظ/بيع] | الهدف: [السعر المستهدف كرقم]
"""

    try:
        response = await model.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ Gemini analysis failed: {e}")
        return None

def is_stock_related(title, description):
    content = (title + " " + description).lower()
    return any(keyword.lower() in content for keyword in STOCK_KEYWORDS)

async def process_and_send(bot, title, description, link, sent_db):
    if not is_stock_related(title, description):
        return False, "Not stock related"

    news_hash = generate_news_hash(title, link)
    if news_hash in sent_db:
        return False, "Duplicate hash"

    for existing_hash, existing_data in sent_db.items():
        if is_similar(title, existing_data["title"]):
            return False, "Similar title"

    tickers = find_tickers(title + " " + description)
    if not tickers:
        return False, "No tickers found"

    fair_value_data = get_fair_value_data(tickers)
    if not fair_value_data:
        return False, "No fair value data for these tickers"

    print(f"📰 Processing: {title[:60]}...")
    analysis_text = await analyze_news_with_gemini(title, fair_value_data)

    # Parsing the structured analysis
    summary_points = re.findall(r"•\s*(.*)", analysis_text) if analysis_text else []
    confidence_match = re.search(r"مؤشر الثقة:\s*(\d+)", analysis_text) if analysis_text else None
    decision_match = re.search(r"قرار المحلل:\s*(.*)", analysis_text) if analysis_text else None
    
    confidence_score = confidence_match.group(1) if confidence_match else "N/A"
    analyst_decision = decision_match.group(1) if decision_match else "التحليل قيد التحديث"

    # Build the message
    for ticker_tag in tickers:
        ticker = ticker_tag.replace("#", "")
        if ticker in fair_value_data:
            data = fair_value_data[ticker]
            company_name = data.get('company_names', [ticker])[0]
            curr_p_val = data.get('current_price')
            current_price = f"{curr_p_val:.2f}" if curr_p_val is not None else "N/A"
            fv_val = data.get('fair_value')
            fv = f"{fv_val:.2f}" if fv_val is not None else "N/A"
            upside_percent = data.get('upside_percent', 0)
            upside_icon = "📈" if upside_percent > 0 else ("📉" if upside_percent < 0 else "↔️")
            upside_val = f"{abs(upside_percent):.1f}%"

            message = (
                f"🏛️ <b>تحليل سهم: {company_name} ({ticker})</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>الخبر:</b> {title}\n\n"
                f"📊 <b>التقييم الرقمي (Investing Pro):</b>\n"
                f"  - السعر الحالي: {current_price} ج.م\n"
                f"  - القيمة العادلة: {fv} ج.م\n"
                f"  - فرصة الصعود: {upside_icon} {upside_val}\n\n"
                f"💡 <b>الخلاصة في 3 نقاط:</b>\n"
                f"  • {summary_points[0] if len(summary_points) > 0 else '...'}\n"
                f"  • {summary_points[1] if len(summary_points) > 1 else '...'}\n"
                f"  • {summary_points[2] if len(summary_points) > 2 else '...'}\n\n"
                f"🎯 <b>قرار المحلل (الثقة: {confidence_score}/10):</b>\n"
                f"  - {analyst_decision}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<a href=\"{link}\">المصدر</a> | {ticker_tag}"
            )

            try:
                await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
                sent_db[news_hash] = {"title": title, "link": link}
                print(f"✅ Sent analysis for {ticker}")
                await asyncio.sleep(2) # Delay between messages
            except Exception as e:
                print(f"❌ Error sending message for {ticker}: {e}")

    return True, "Processed"

async def fetch_rss_feeds(bot, sent_db):
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in RSS_FEEDS:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:15]:
                await process_and_send(bot, entry.title, entry.get("summary", ""), entry.link, sent_db)
        except Exception as e:
            print(f"⚠️ Error fetching RSS {url[:50]}: {e}")

async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    sent_db = load_sent_news_db()
    load_fair_values()

    print(f"\n🤖 EGX News Bot v6.0 Started | Model: {selected_model_name or 'N/A'} | Tracked: {len(sent_db)}")

    await fetch_rss_feeds(bot, sent_db)

    save_sent_news_db(sent_db)
    print(f"\n✅ Cycle completed. Total tracked news: {len(sent_db)}\n")

if __name__ == "__main__":
    asyncio.run(main())
