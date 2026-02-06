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

# --- الإعدادات ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- قاموس الأسهم ---
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

STOCK_KEYWORDS = list(TICKER_MAP.keys()) + [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال",
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب",
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية"
]

# --- ملفات ---
FAIR_VALUES_FILE = "fair_values.json"
SENT_NEWS_DB_FILE = "sent_news_db.json"
FAIR_VALUES_DB = {}

def load_fair_values():
    global FAIR_VALUES_DB
    if os.path.exists(FAIR_VALUES_FILE):
        try:
            with open(FAIR_VALUES_FILE, 'r', encoding='utf-8') as f:
                FAIR_VALUES_DB = json.load(f)
                print(f"✅ Loaded {len(FAIR_VALUES_DB)} fair values")
        except Exception as e:
            print(f"⚠️ Error loading fair values: {e}")

# --- Gemini ---
client = None
model_name = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        model_name = "gemini-2.0-flash-exp"
        print(f"✅ Gemini ready: {model_name}")
    except Exception as e:
        print(f"⚠️ Gemini init error: {e}")

# --- مصادر الأخبار ---
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]

MUBASHER_URL = "https://www.mubasher.info/news/eg/pulse/stocks"

# --- دوال منع التكرار ---
def is_similar(t1, t2, threshold=0.70):
    if not t1 or not t2:
        return False
    return SequenceMatcher(None, t1.lower().strip(), t2.lower().strip()).ratio() >= threshold

def gen_hash(title, link):
    return hashlib.md5(f"{title}_{link}".encode('utf-8')).hexdigest()

def is_duplicate(title, link, db):
    h = gen_hash(title, link)
    if h in db:
        return True, "hash"
    for _, data in db.items():
        if is_similar(title, data.get('title', '')):
            return True, "similar"
    return False, None

# --- قاعدة البيانات ---
def load_db():
    if os.path.exists(SENT_NEWS_DB_FILE):
        try:
            with open(SENT_NEWS_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_db(db):
    try:
        if len(db) > 3000:
            keys = list(db.keys())[-3000:]
            db = {k: db[k] for k in keys}
        with open(SENT_NEWS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Save error: {e}")

# --- البحث عن الأسهم ---
def find_tickers(text):
    found = set()
    text_lower = text.lower()
    for company, ticker in TICKER_MAP.items():
        if company.lower() in text_lower:
            found.add(ticker)
    return list(found)

def get_fv_data(tickers):
    data = {}
    for ticker in tickers:
        if ticker in FAIR_VALUES_DB:
            data[ticker] = FAIR_VALUES_DB[ticker]
    return data

# --- التحليل الذكي (احتياطي) ---
def smart_fallback_analysis(title, fv_data):
    """تحليل احتياطي ذكي إذا فشل Gemini"""
    
    title_lower = title.lower()
    
    # كلمات إيجابية
    positive_words = ['ارتفاع', 'نمو', 'زيادة', 'أرباح', 'توسع', 'شراكة', 'استحواذ', 'اكتتاب', 'توزيع']
    # كلمات سلبية
    negative_words = ['انخفاض', 'خسائر', 'تراجع', 'هبوط', 'تحذير']
    
    positive_count = sum(1 for w in positive_words if w in title_lower)
    negative_count = sum(1 for w in negative_words if w in title_lower)
    
    # استخراج الأرقام
    numbers = re.findall(r'(\d+(?:\.\d+)?)\s*(?:مليار|مليون|ألف|%)', title)
    number_text = f"القيمة: {numbers[0]} {title[title.find(numbers[0]):title.find(numbers[0])+30]}" if numbers else "تحليل نوعي"
    
    # التحليل حسب القيمة العادلة
    if fv_data:
        ticker = list(fv_data.keys())[0]
        data = fv_data[ticker]
        upside = data.get('upside_percent', 0)
        curr_price = data.get('current_price', 0)
        fv = data.get('fair_value', 0)
        
        if upside > 15:
            valuation = "فرصة شراء قوية"
            target = fv * 0.95
            decision = f"شراء تدريجي | الهدف {target:.2f} ج.م"
            confidence = 7
        elif upside < -10:
            valuation = "تقييم مرتفع"
            target = fv * 1.05
            decision = f"بيع جزئي | الهدف {target:.2f} ج.م"
            confidence = 6
        else:
            valuation = "تقييم متوازن"
            target = (curr_price + fv) / 2
            decision = f"احتفاظ | الهدف {target:.2f} ج.م"
            confidence = 5
    else:
        valuation = "متابعة"
        decision = "انتظار بيانات إضافية"
        confidence = 4
    
    # تحديد الاتجاه
    if positive_count > negative_count:
        direction = "إيجابي - يدعم الأداء"
        impact = f"الخبر إيجابي ويدعم استمرار النمو"
    elif negative_count > positive_count:
        direction = "سلبي - ضغط محتمل"
        impact = "الخبر قد يؤثر سلباً على الأداء قصير المدى"
    else:
        direction = "محايد - متابعة"
        impact = "تأثير محدود على الأداء العام"
    
    return {
        'impact': impact,
        'number': number_text,
        'direction': direction,
        'confidence': str(confidence),
        'recommendation': decision
    }

# --- التحليل بـ Gemini ---
async def analyze_with_gemini(title, desc, fv_data):
    """محاولة التحليل بـ Gemini مع fallback ذكي"""
    
    if not client or not model_name:
        return smart_fallback_analysis(title, fv_data)
    
    # تجهيز البيانات
    fv_text = ""
    if fv_data:
        for ticker, data in fv_data.items():
            curr = data.get('current_price', 0)
            fv = data.get('fair_value', 0)
            upside = data.get('upside_percent', 0)
            fv_text += f"السعر {curr:.2f} | القيمة العادلة {fv:.2f} | فرصة {upside:.1f}%"
    
    prompt = f"""حلل بإيجاز:
الخبر: {title}
البيانات: {fv_text}

أجب في 5 أسطر فقط:
1. التأثير: [جملة واحدة]
2. الأرقام: [نسبة/رقم]
3. الاتجاه: [إيجابي/سلبي/محايد]
4. الثقة: [1-10]
5. التوصية: [شراء/بيع/احتفاظ والسعر]"""

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt
            ),
            timeout=10.0
        )
        
        text = response.text.strip()
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        analysis = {
            'impact': '',
            'number': '',
            'direction': '',
            'confidence': '5',
            'recommendation': ''
        }
        
        for line in lines:
            if any(x in line for x in ['التأثير', '1.']):
                analysis['impact'] = re.sub(r'^[\d\.\s:]*(التأثير:?)?\s*', '', line)
            elif any(x in line for x in ['الأرقام', 'الرقم', '2.']):
                analysis['number'] = re.sub(r'^[\d\.\s:]*(الأرقام:?|الرقم:?)?\s*', '', line)
            elif any(x in line for x in ['الاتجاه', '3.']):
                analysis['direction'] = re.sub(r'^[\d\.\s:]*(الاتجاه:?)?\s*', '', line)
            elif any(x in line for x in ['الثقة', '4.']):
                m = re.search(r'(\d+)', line)
                if m:
                    analysis['confidence'] = m.group(1)
            elif any(x in line for x in ['التوصية', '5.']):
                analysis['recommendation'] = re.sub(r'^[\d\.\s:]*(التوصية:?)?\s*', '', line)
        
        # تحقق من جودة النتيجة
        if len(analysis['impact']) < 10 or not analysis['recommendation']:
            return smart_fallback_analysis(title, fv_data)
        
        return analysis
        
    except Exception as e:
        print(f"⚠️ Gemini → fallback: {str(e)[:40]}")
        return smart_fallback_analysis(title, fv_data)

def is_stock_related(title, desc):
    content = (title + ' ' + desc).lower()
    return any(kw.lower() in content for kw in STOCK_KEYWORDS)

async def process_news(bot, title, desc, link, db):
    """معالجة خبر واحد"""
    
    # فحص الارتباط
    if not is_stock_related(title, desc):
        return False, "not_related"
    
    # فحص التكرار
    is_dup, reason = is_duplicate(title, link, db)
    if is_dup:
        return False, f"dup_{reason}"
    
    # البحث عن الأسهم
    tickers = find_tickers(title + ' ' + desc)
    if not tickers:
        return False, "no_tickers"
    
    # بيانات القيمة العادلة
    fv_data = get_fv_data(tickers)
    if not fv_data:
        return False, "no_fv"
    
    print(f"\n📰 {title[:50]}...")
    
    # التحليل (مع fallback تلقائي)
    analysis = await analyze_with_gemini(title, desc, fv_data)
    
    # إرسال
    h = gen_hash(title, link)
    sent = 0
    
    for ticker in tickers:
        if ticker not in fv_data:
            continue
        
        data = fv_data[ticker]
        company = data.get('company_names', [ticker])[0]
        curr = data.get('current_price', 0)
        fv = data.get('fair_value', 0)
        upside = data.get('upside_percent', 0)
        
        icon = "📈" if upside > 0 else "📉" if upside < 0 else "↔️"
        
        msg = (
            f"🏛️ <b>{company} (#{ticker})</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 {title}\n\n"
            f"📊 <b>المؤشرات:</b>\n"
            f"  • السعر: {curr:.2f} ج.م\n"
            f"  • القيمة العادلة: {fv:.2f} ج.م\n"
            f"  • الفرصة: {icon} {abs(upside):.1f}%\n\n"
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
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            sent += 1
            print(f"✅ {ticker}")
            await asyncio.sleep(1.5)  # تأخير بين الرسائل
        except Exception as e:
            print(f"❌ {ticker}: {e}")
    
    if sent > 0:
        db[h] = {
            'title': title,
            'link': link,
            'tickers': tickers,
            'time': datetime.now().isoformat()
        }
        return True, f"sent_{sent}"
    
    return False, "no_send"

async def fetch_mubasher(bot, db):
    """جلب أخبار من موقع مباشر"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(MUBASHER_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # البحث عن الأخبار في الصفحة
        news_items = soup.find_all('article', class_=re.compile('news|story|item'), limit=20)
        
        if not news_items:
            # محاولة بديلة
            news_items = soup.find_all(['div', 'li'], class_=re.compile('news|story|article'), limit=20)
        
        count = 0
        for item in news_items:
            try:
                # استخراج العنوان
                title_tag = item.find(['h2', 'h3', 'h4', 'a'])
                if not title_tag:
                    continue
                
                title = title_tag.get_text(strip=True)
                
                # استخراج الرابط
                link_tag = item.find('a', href=True)
                if not link_tag:
                    continue
                
                link = link_tag['href']
                if not link.startswith('http'):
                    link = 'https://www.mubasher.info' + link
                
                # استخراج الوصف
                desc_tag = item.find(['p', 'span'], class_=re.compile('desc|summary|excerpt'))
                desc = desc_tag.get_text(strip=True) if desc_tag else ''
                
                if len(title) > 15:  # التأكد من أن العنوان معقول
                    await process_news(bot, title, desc, link, db)
                    count += 1
                    await asyncio.sleep(0.3)
                    
            except Exception as e:
                continue
        
        if count > 0:
            print(f"✅ Mubasher: processed {count} news")
        else:
            print(f"⚠️ Mubasher: no news found")
            
    except Exception as e:
        print(f"⚠️ Mubasher error: {str(e)[:50]}")

async def fetch_rss(bot, db):
    """جلب الأخبار من RSS"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for url in RSS_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            feed = feedparser.parse(r.content)
            
            for entry in feed.entries[:15]:
                await process_news(
                    bot,
                    entry.title,
                    entry.get('summary', ''),
                    entry.link,
                    db
                )
                await asyncio.sleep(0.2)
                
        except Exception as e:
            print(f"⚠️ RSS {url[:25]}: {e}")

async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID]):
        print("❌ Missing tokens!")
        return
    
    load_fair_values()
    db = load_db()
    bot = Bot(token=TELEGRAM_TOKEN)
    
    print(f"\n🤖 EGX Bot v10.0 - Final Edition")
    print(f"📊 Gemini: {model_name or 'Smart Fallback Only'}")
    print(f"📰 DB: {len(db)} news")
    print(f"🌐 Sources: RSS (3) + Mubasher\n")
    
    cycle = 0
    
    while True:
        try:
            cycle += 1
            print(f"\n🔄 Cycle {cycle} - {datetime.now().strftime('%H:%M:%S')}")
            
            # جلب من RSS
            await fetch_rss(bot, db)
            
            # جلب من مباشر
            await fetch_mubasher(bot, db)
            
            save_db(db)
            
            print(f"✅ Cycle done. DB: {len(db)}")
            
            # انتظار دقيقة ونصف
            await asyncio.sleep(90)
            
        except KeyboardInterrupt:
            print("\n👋 Stopping...")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Stopped")
