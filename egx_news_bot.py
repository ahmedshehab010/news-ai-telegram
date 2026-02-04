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

# تشغيل/إيقاف الملخص الساعي
ENABLE_HOURLY_SUMMARY = False  # غيرها لـ True لتفعيل الملخص

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
        print(f"✅ Gemini initialized: {selected_model_name}")
    except Exception as e:
        print(f"⚠️ Gemini error: {e}")

# --- مصادر الأخبار ---
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]

# --- دوال منع التكرار المحسّنة ---
def is_similar(title1, title2, threshold=0.75):
    """فحص التشابه بين عنوانين - عتبة 75%"""
    if not title1 or not title2:
        return False
    return SequenceMatcher(None, title1.lower().strip(), title2.lower().strip()).ratio() >= threshold

def generate_news_hash(title, link):
    """إنشاء hash فريد للخبر"""
    return hashlib.md5(f"{title.strip()}_{link.strip()}".encode('utf-8')).hexdigest()

def is_duplicate(title, link, sent_db):
    """فحص شامل للتكرار"""
    news_hash = generate_news_hash(title, link)
    
    # فحص Hash المباشر
    if news_hash in sent_db:
        return True, "duplicate_hash"
    
    # فحص التشابه مع جميع الأخبار المرسلة
    for existing_hash, existing_data in sent_db.items():
        existing_title = existing_data.get('title', '')
        if is_similar(title, existing_title):
            return True, f"similar_to: {existing_title[:30]}"
    
    return False, None

# --- إدارة قاعدة البيانات ---
def load_sent_news_db():
    if os.path.exists(SENT_NEWS_DB_FILE):
        try:
            with open(SENT_NEWS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sent_news_db(db):
    try:
        # احتفظ بآخر 2000 خبر
        if len(db) > 2000:
            keys_to_keep = list(db.keys())[-2000:]
            db = {k: db[k] for k in keys_to_keep}
        with open(SENT_NEWS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
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
        print(f"⚠️ Error saving hourly: {e}")

# --- دوال التحليل ---
def find_tickers(text):
    """البحث عن رموز الأسهم في النص"""
    found_tickers = set()
    text_lower = text.lower()
    for company, ticker in TICKER_MAP.items():
        if company.lower() in text_lower:
            found_tickers.add(ticker)
    return list(found_tickers)

def get_fair_value_data(tickers):
    """الحصول على بيانات القيمة العادلة"""
    data = {}
    for ticker in tickers:
        if ticker in FAIR_VALUES_DB:
            data[ticker] = FAIR_VALUES_DB[ticker]
    return data

async def analyze_news_with_gemini(title, description, fair_value_data):
    """تحليل الخبر باستخدام Gemini مع معالجة أخطاء محسّنة"""
    
    if not client or not selected_model_name:
        print("⚠️ Gemini not available")
        return None
    
    # تجهيز بيانات القيمة العادلة
    fv_summary = "لا توجد بيانات"
    if fair_value_data:
        fv_parts = []
        for ticker, data in fair_value_data.items():
            company = data.get('company_names', [ticker])[0]
            curr = data.get('current_price', 0)
            fv = data.get('fair_value', 0)
            upside = data.get('upside_percent', 0)
            fv_parts.append(f"{company}: سعر {curr:.2f} ج.م | قيمة عادلة {fv:.2f} ج.م | صعود {upside:.1f}%")
        fv_summary = " | ".join(fv_parts)
    
    # Prompt محسّن وأقصر
    prompt = f"""أنت محلل مالي. حلل هذا الخبر بإيجاز شديد:

الخبر: {title}
البيانات: {fv_summary}

أعطني فقط (سطر واحد لكل نقطة):
1. التأثير: [جملة واحدة عن تأثير الخبر]
2. الرقم: [نسبة أو رقم متوقع]
3. الاتجاه: [إيجابي أو سلبي أو محايد]
4. الثقة: [رقم من 1 إلى 10]
5. التوصية: [شراء أو بيع أو احتفاظ والسعر المستهدف]

مثال:
1. التأثير: زيادة رأس المال تدعم التوسع وتحسن السيولة
2. الرقم: نمو متوقع 20-25% في الإيرادات
3. الاتجاه: إيجابي على المدى المتوسط
4. الثقة: 7
5. التوصية: شراء | الهدف 0.25 ج.م"""

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=selected_model_name,
                contents=prompt
            ),
            timeout=15.0  # timeout بعد 15 ثانية
        )
        
        text = response.text.strip()
        print(f"📝 Gemini response: {text[:100]}...")
        
        # استخراج البيانات بطريقة أكثر مرونة
        lines = text.split('\n')
        analysis = {
            'impact': '',
            'number': '',
            'direction': '',
            'confidence': '5',
            'recommendation': 'انتظار | تحليل إضافي'
        }
        
        for line in lines:
            line = line.strip()
            if 'التأثير:' in line or line.startswith('1.'):
                analysis['impact'] = re.sub(r'^[\d\.]+\s*(التأثير:)?\s*', '', line).strip()
            elif 'الرقم:' in line or line.startswith('2.'):
                analysis['number'] = re.sub(r'^[\d\.]+\s*(الرقم:)?\s*', '', line).strip()
            elif 'الاتجاه:' in line or line.startswith('3.'):
                analysis['direction'] = re.sub(r'^[\d\.]+\s*(الاتجاه:)?\s*', '', line).strip()
            elif 'الثقة:' in line or line.startswith('4.'):
                conf_match = re.search(r'(\d+)', line)
                if conf_match:
                    analysis['confidence'] = conf_match.group(1)
            elif 'التوصية:' in line or line.startswith('5.'):
                analysis['recommendation'] = re.sub(r'^[\d\.]+\s*(التوصية:)?\s*', '', line).strip()
        
        # التحقق من جودة التحليل
        if not analysis['impact'] or len(analysis['impact']) < 10:
            print("⚠️ Analysis too short, skipping")
            return None
            
        return analysis
        
    except asyncio.TimeoutError:
        print("⚠️ Gemini timeout")
        return None
    except Exception as e:
        print(f"⚠️ Gemini error: {str(e)[:100]}")
        return None

def is_stock_related(title, description):
    """فحص ارتباط الخبر بالأسهم"""
    content = (title + ' ' + description).lower()
    return any(keyword.lower() in content for keyword in STOCK_KEYWORDS)

async def process_and_send(bot, title, description, link, sent_db, hourly_news):
    """معالجة وإرسال الخبر"""
    
    # فحص الارتباط بالأسهم
    if not is_stock_related(title, description):
        return False, "Not stock related"
    
    # فحص التكرار الشامل
    is_dup, dup_reason = is_duplicate(title, link, sent_db)
    if is_dup:
        return False, f"Duplicate: {dup_reason}"
    
    # البحث عن الأسهم
    tickers = find_tickers(title + ' ' + description)
    if not tickers:
        return False, "No tickers"
    
    # الحصول على بيانات القيمة العادلة
    fair_value_data = get_fair_value_data(tickers)
    if not fair_value_data:
        return False, "No fair value data"
    
    print(f"\n📰 Processing: {title[:60]}")
    
    # التحليل
    analysis = await analyze_news_with_gemini(title, description, fair_value_data)
    
    if not analysis:
        print("⚠️ Analysis failed, skipping news")
        return False, "Analysis failed"
    
    # إرسال لكل سهم
    news_hash = generate_news_hash(title, link)
    sent_count = 0
    
    for ticker in tickers:
        if ticker not in fair_value_data:
            continue
        
        data = fair_value_data[ticker]
        company_name = data.get('company_names', [ticker])[0]
        
        curr_price = data.get('current_price', 0)
        current_price_str = f"{curr_price:.2f}" if curr_price else "N/A"
        
        fv = data.get('fair_value', 0)
        fv_str = f"{fv:.2f}" if fv else "N/A"
        
        upside_percent = data.get('upside_percent', 0)
        upside_icon = "📈" if upside_percent > 0 else ("📉" if upside_percent < 0 else "↔️")
        upside_str = f"{abs(upside_percent):.1f}%"
        
        message = (
            f"🏛️ <b>تحليل: {company_name} (#{ticker})</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>الخبر:</b> {title}\n\n"
            f"📊 <b>المؤشرات:</b>\n"
            f"  • السعر: {current_price_str} ج.م\n"
            f"  • القيمة العادلة: {fv_str} ج.م\n"
            f"  • الفرصة: {upside_icon} {upside_str}\n\n"
            f"💡 <b>التحليل:</b>\n"
            f"  • {analysis['impact']}\n"
            f"  • {analysis['number']}\n"
            f"  • {analysis['direction']}\n\n"
            f"🎯 <b>التوصية (ثقة {analysis['confidence']}/10):</b>\n"
            f"  {analysis['recommendation']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<a href=\"{link}\">المصدر</a> | {datetime.now().strftime('%H:%M')}"
        )
        
        try:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            
            sent_count += 1
            print(f"✅ Sent: {ticker}")
            await asyncio.sleep(2)
            
        except Exception as e:
            print(f"❌ Send error {ticker}: {e}")
    
    if sent_count > 0:
        # حفظ في قاعدة البيانات
        sent_db[news_hash] = {
            'title': title,
            'link': link,
            'tickers': tickers,
            'timestamp': datetime.now().isoformat()
        }
        
        # إضافة للملخص الساعي
        if ENABLE_HOURLY_SUMMARY:
            for ticker in tickers:
                hourly_news.append({
                    'title': title,
                    'ticker': ticker,
                    'timestamp': datetime.now().isoformat()
                })
        
        return True, f"Sent to {sent_count} ticker(s)"
    
    return False, "No messages sent"

async def send_hourly_summary(bot, hourly_news):
    """إرسال ملخص ساعي"""
    if not hourly_news or not ENABLE_HOURLY_SUMMARY:
        return
    
    ticker_groups = {}
    for news in hourly_news:
        ticker = news['ticker']
        if ticker not in ticker_groups:
            ticker_groups[ticker] = []
        ticker_groups[ticker].append(news)
    
    summary = f"📊 <b>ملخص الساعة</b>\n"
    summary += f"⏰ {datetime.now().strftime('%H:%M')}\n"
    summary += f"━━━━━━━━━━━━━━━━━━\n\n"
    
    for ticker, news_list in list(ticker_groups.items())[:10]:
        summary += f"<b>#{ticker}</b>: {len(news_list)} خبر\n"
    
    summary += f"\n📈 إجمالي: {len(hourly_news)} خبر"
    
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=summary,
            parse_mode=ParseMode.HTML
        )
        print("✅ Summary sent")
    except Exception as e:
        print(f"❌ Summary error: {e}")

async def fetch_rss_feeds(bot, sent_db, hourly_news):
    """جلب الأخبار"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for url in RSS_FEEDS:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries[:15]:
                await process_and_send(
                    bot,
                    entry.title,
                    entry.get('summary', ''),
                    entry.link,
                    sent_db,
                    hourly_news
                )
                await asyncio.sleep(0.3)
                
        except Exception as e:
            print(f"⚠️ RSS error {url[:30]}: {e}")

async def main():
    """الدالة الرئيسية"""
    
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        return
    
    load_fair_values()
    sent_db = load_sent_news_db()
    hourly_news = load_hourly_news()
    
    bot = Bot(token=TELEGRAM_TOKEN)
    
    print(f"\n🤖 EGX News Bot v8.0")
    print(f"📊 Model: {selected_model_name or 'N/A'}")
    print(f"📰 Tracked: {len(sent_db)}\n")
    
    last_summary = datetime.now()
    cycle = 0
    
    while True:
        try:
            cycle += 1
            print(f"\n🔄 Cycle {cycle} - {datetime.now().strftime('%H:%M:%S')}")
            
            await fetch_rss_feeds(bot, sent_db, hourly_news)
            
            # ملخص ساعي
            if ENABLE_HOURLY_SUMMARY and (datetime.now() - last_summary) >= timedelta(hours=1):
                await send_hourly_summary(bot, hourly_news)
                hourly_news = []
                last_summary = datetime.now()
            
            # حفظ البيانات
            save_sent_news_db(sent_db)
            if ENABLE_HOURLY_SUMMARY:
                save_hourly_news(hourly_news)
            
            print(f"✅ Cycle {cycle} done. DB: {len(sent_db)}")
            
            # انتظار 2 دقيقة
            await asyncio.sleep(120)
            
        except KeyboardInterrupt:
            print("\n👋 Stopping...")
            break
        except Exception as e:
            print(f"❌ Main error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Bot stopped")
