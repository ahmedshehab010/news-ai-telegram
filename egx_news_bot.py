import feedparser
import asyncio
import os
import json
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from google import genai
from telegram import Bot
from telegram.constants import ParseMode
import hashlib
from difflib import SequenceMatcher

# --- الإعدادات الأساسية ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- قاموس أكواد الأسهم ---
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

# --- الكلمات المفتاحية ---
STOCK_KEYWORDS = list(TICKER_MAP.keys()) + [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال",
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب",
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية", "موازنة"
]

# --- ملفات البيانات ---
FAIR_VALUES_FILE = "fair_values.json"
SENT_NEWS_DB_FILE = "sent_news_db.json"
HOURLY_SUMMARY_FILE = "hourly_news.json"

FAIR_VALUES_DB = {}

# --- تحميل البيانات ---
def load_fair_values():
    global FAIR_VALUES_DB
    if os.path.exists(FAIR_VALUES_FILE):
        try:
            with open(FAIR_VALUES_FILE, 'r', encoding='utf-8') as f:
                FAIR_VALUES_DB = json.load(f)
                print(f"✅ Loaded {len(FAIR_VALUES_DB)} fair value entries.")
        except Exception as e:
            print(f"⚠️ Error loading fair_values.json: {e}")
    else:
        print("⚠️ fair_values.json not found.")

# --- إعداد Gemini ---
client = None
selected_model_name = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        selected_model_name = "gemini-2.0-flash-exp"
        print(f"✅ Gemini Client initialized: {selected_model_name}")
    except Exception as e:
        print(f"⚠️ Gemini initialization failed: {e}")

# --- مصادر الأخبار ---
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]

# --- دوال منع التكرار ---
def is_similar(title1, title2, threshold=0.85):
    return SequenceMatcher(None, title1.lower(), title2.lower()).ratio() >= threshold

def generate_news_hash(title, link):
    return hashlib.md5(f"{title.strip()}_{link.strip()}".encode('utf-8')).hexdigest()

# --- إدارة قاعدة البيانات ---
def load_sent_news_db():
    if os.path.exists(SENT_NEWS_DB_FILE):
        try:
            with open(SENT_NEWS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading DB: {e}")
            return {}
    return {}

def save_sent_news_db(db):
    try:
        # احتفظ بآخر 1000 خبر فقط
        keys_to_keep = list(db.keys())[-1000:]
        trimmed_db = {k: db[k] for k in keys_to_keep}
        with open(SENT_NEWS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(trimmed_db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving DB: {e}")

def load_hourly_news():
    if os.path.exists(HOURLY_SUMMARY_FILE):
        try:
            with open(HOURLY_SUMMARY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_hourly_news(news_list):
    try:
        with open(HOURLY_SUMMARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(news_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving hourly news: {e}")

# --- دوال التحليل ---
def find_tickers(text):
    found_tickers = set()
    text_lower = text.lower()
    for company, ticker in TICKER_MAP.items():
        if company.lower() in text_lower:
            found_tickers.add(ticker)
    return list(found_tickers)

def get_fair_value_data(tickers):
    data = {}
    for ticker in tickers:
        if ticker in FAIR_VALUES_DB:
            data[ticker] = FAIR_VALUES_DB[ticker]
    return data

async def analyze_news_with_gemini(title, description, fair_value_data):
    if not client or not selected_model_name:
        return {
            'summary': ['تحليل الخبر غير متاح حالياً', 'يرجى المحاولة لاحقاً', 'تحليل يدوي مطلوب'],
            'confidence': '5',
            'decision': 'انتظار | مزيد من التفاصيل'
        }

    # تنسيق بيانات القيمة العادلة
    fv_text = "لا توجد بيانات قيمة عادلة"
    if fair_value_data:
        fv_lines = []
        for ticker, data in fair_value_data.items():
            company = data.get('company_names', [ticker])[0]
            fv = data.get('fair_value', 'N/A')
            upside = data.get('upside_percent', 0)
            fv_lines.append(f"- {company} ({ticker}): قيمة عادلة {fv} ج.م، فرصة صعود {upside:.1f}%")
        fv_text = '\n'.join(fv_lines)

    prompt = f"""أنت محلل مالي محترف. قم بتحليل هذا الخبر بشكل سريع ومباشر:

**الخبر:** {title}
**التفاصيل:** {description[:200] if description else 'لا توجد تفاصيل'}

**بيانات القيمة العادلة:**
{fv_text}

**المطلوب (التزم بالتنسيق التالي بالضبط):**

النقطة الأولى: [تأثير الخبر على السهم في جملة واحدة]
النقطة الثانية: [رقم أو نسبة متوقعة للتأثير]
النقطة الثالثة: [التوصية: إيجابي/سلبي/محايد]
الثقة: [رقم من 1-10]
القرار: [شراء/بيع/احتفاظ] | الهدف: [رقم السعر المستهدف]

مثال:
النقطة الأولى: الشراكة ستعزز محفظة الضيافة وتزيد الإيرادات
النقطة الثانية: نمو متوقع 15-20% في قطاع الضيافة
النقطة الثالثة: إيجابي على المدى المتوسط
الثقة: 7
القرار: شراء | الهدف: 4.20
"""

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=selected_model_name,
            contents=prompt
        )
        
        text = response.text.strip()
        
        # استخراج البيانات
        point1_match = re.search(r'النقطة الأولى:\s*(.+)', text)
        point2_match = re.search(r'النقطة الثانية:\s*(.+)', text)
        point3_match = re.search(r'النقطة الثالثة:\s*(.+)', text)
        confidence_match = re.search(r'الثقة:\s*(\d+)', text)
        decision_match = re.search(r'القرار:\s*(.+)', text)
        
        return {
            'summary': [
                point1_match.group(1).strip() if point1_match else 'تحليل قيد المعالجة',
                point2_match.group(1).strip() if point2_match else 'تحليل قيد المعالجة',
                point3_match.group(1).strip() if point3_match else 'تحليل قيد المعالجة'
            ],
            'confidence': confidence_match.group(1) if confidence_match else '5',
            'decision': decision_match.group(1).strip() if decision_match else 'انتظار | تحليل إضافي'
        }
    except Exception as e:
        print(f"⚠️ Gemini analysis error: {e}")
        return {
            'summary': ['خطأ في التحليل', 'يرجى المحاولة لاحقاً', 'تحليل يدوي مطلوب'],
            'confidence': '3',
            'decision': 'انتظار | خطأ تقني'
        }

def is_stock_related(title, description):
    content = (title + ' ' + description).lower()
    return any(keyword.lower() in content for keyword in STOCK_KEYWORDS)

async def process_and_send(bot, title, description, link, sent_db, hourly_news):
    """معالجة وإرسال الخبر فوراً"""
    
    # التحقق من الارتباط بالأسهم
    if not is_stock_related(title, description):
        return False, "Not stock related"

    # التحقق من التكرار - Hash
    news_hash = generate_news_hash(title, link)
    if news_hash in sent_db:
        return False, "Duplicate hash"

    # التحقق من التكرار - التشابه
    for existing_hash, existing_data in sent_db.items():
        if is_similar(title, existing_data.get('title', '')):
            return False, "Similar title"

    # البحث عن رموز الأسهم
    tickers = find_tickers(title + ' ' + description)
    if not tickers:
        return False, "No tickers found"

    # الحصول على بيانات القيمة العادلة
    fair_value_data = get_fair_value_data(tickers)
    if not fair_value_data:
        return False, "No fair value data"

    print(f"📰 Processing: {title[:50]}...")

    # تحليل الخبر
    analysis = await analyze_news_with_gemini(title, description, fair_value_data)

    # إرسال رسالة لكل سهم
    for ticker in tickers:
        if ticker not in fair_value_data:
            continue
            
        data = fair_value_data[ticker]
        company_name = data.get('company_names', [ticker])[0]
        
        curr_price = data.get('current_price')
        current_price_str = f"{curr_price:.2f}" if curr_price else "N/A"
        
        fv = data.get('fair_value')
        fv_str = f"{fv:.2f}" if fv else "N/A"
        
        upside_percent = data.get('upside_percent', 0)
        upside_icon = "📈" if upside_percent > 0 else ("📉" if upside_percent < 0 else "↔️")
        upside_str = f"{abs(upside_percent):.1f}%"

        message = (
            f"🏛️ <b>تحليل سهم: {company_name} (#{ticker})</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>الخبر:</b> {title}\n\n"
            f"📊 <b>البيانات المالية:</b>\n"
            f"  • السعر الحالي: {current_price_str} ج.م\n"
            f"  • القيمة العادلة: {fv_str} ج.م\n"
            f"  • فرصة الصعود: {upside_icon} {upside_str}\n\n"
            f"💡 <b>التحليل السريع:</b>\n"
            f"  • {analysis['summary'][0]}\n"
            f"  • {analysis['summary'][1]}\n"
            f"  • {analysis['summary'][2]}\n\n"
            f"🎯 <b>توصية المحلل (ثقة {analysis['confidence']}/10):</b>\n"
            f"  {analysis['decision']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<a href=\"{link}\">📰 المصدر</a> | ⏰ {datetime.now().strftime('%H:%M')}"
        )

        try:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            
            # حفظ في قاعدة البيانات
            sent_db[news_hash] = {
                'title': title,
                'link': link,
                'ticker': ticker,
                'timestamp': datetime.now().isoformat()
            }
            
            # إضافة للملخص الساعي
            hourly_news.append({
                'title': title,
                'ticker': ticker,
                'company': company_name,
                'timestamp': datetime.now().isoformat(),
                'analysis': analysis['decision']
            })
            
            print(f"✅ Sent: {ticker}")
            await asyncio.sleep(1.5)  # تأخير بسيط بين الرسائل
            
        except Exception as e:
            print(f"❌ Error sending {ticker}: {e}")

    return True, "Processed and sent"

async def send_hourly_summary(bot, hourly_news):
    """إرسال ملخص ساعي للأخبار"""
    
    if not hourly_news:
        return
    
    # تجميع حسب السهم
    ticker_groups = {}
    for news in hourly_news:
        ticker = news['ticker']
        if ticker not in ticker_groups:
            ticker_groups[ticker] = []
        ticker_groups[ticker].append(news)
    
    summary_text = "📊 <b>ملخص أخبار الساعة الأخيرة</b>\n"
    summary_text += f"━━━━━━━━━━━━━━━━━━\n"
    summary_text += f"⏰ {datetime.now().strftime('%d/%m/%Y - %H:%M')}\n\n"
    
    for ticker, news_list in ticker_groups.items():
        company = news_list[0]['company']
        summary_text += f"🏢 <b>{company} (#{ticker})</b>\n"
        for news in news_list:
            summary_text += f"  • {news['title'][:80]}...\n"
        summary_text += "\n"
    
    summary_text += f"━━━━━━━━━━━━━━━━━━\n"
    summary_text += f"📈 إجمالي الأخبار: {len(hourly_news)} خبر\n"
    summary_text += f"🏛️ الأسهم المتأثرة: {len(ticker_groups)} سهم"
    
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=summary_text,
            parse_mode=ParseMode.HTML
        )
        print("✅ Hourly summary sent")
    except Exception as e:
        print(f"❌ Error sending summary: {e}")

async def fetch_rss_feeds(bot, sent_db, hourly_news):
    """جلب الأخبار من RSS"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for url in RSS_FEEDS:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            
            # معالجة أحدث 20 خبر من كل مصدر
            for entry in feed.entries[:20]:
                await process_and_send(
                    bot,
                    entry.title,
                    entry.get('summary', ''),
                    entry.link,
                    sent_db,
                    hourly_news
                )
                await asyncio.sleep(0.5)  # تأخير صغير بين الأخبار
                
        except Exception as e:
            print(f"⚠️ Error fetching {url[:40]}: {e}")

async def main():
    """الدالة الرئيسية"""
    
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        return

    # تحميل البيانات
    load_fair_values()
    sent_db = load_sent_news_db()
    hourly_news = load_hourly_news()
    
    bot = Bot(token=TELEGRAM_TOKEN)
    
    print(f"\n🤖 EGX News Bot v7.0 Started")
    print(f"📊 Model: {selected_model_name or 'N/A'}")
    print(f"📰 Tracked: {len(sent_db)} news\n")
    
    last_summary_time = datetime.now()
    
    # حلقة مستمرة
    while True:
        try:
            # جلب الأخبار
            await fetch_rss_feeds(bot, sent_db, hourly_news)
            
            # التحقق من الملخص الساعي
            current_time = datetime.now()
            if (current_time - last_summary_time) >= timedelta(hours=1):
                await send_hourly_summary(bot, hourly_news)
                hourly_news = []  # مسح الأخبار بعد الملخص
                last_summary_time = current_time
            
            # حفظ البيانات
            save_sent_news_db(sent_db)
            save_hourly_news(hourly_news)
            
            print(f"✅ Cycle completed. Tracked: {len(sent_db)}, Hourly: {len(hourly_news)}")
            
            # انتظار 3 دقائق قبل الدورة التالية
            await asyncio.sleep(180)
            
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            await asyncio.sleep(60)  # انتظار دقيقة عند الخطأ

if __name__ == "__main__":
    asyncio.run(main())
