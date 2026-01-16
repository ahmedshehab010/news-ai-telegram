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

# الإعدادات من متغيرات البيئة
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# إعداد Gemini مع نظام الاحتياطي
model = None
selected_model_name = None

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # قائمة النماذج المتاحة مع الأولوية (الأسرع والأكثر استقراراً أولاً)
    MODEL_LIST = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-2.5-pro']
    
    # اختيار النموذج الأول المتاح
    for m in MODEL_LIST:
        try:
            # التحقق من توفر النموذج
            genai.get_model(m)
            model = genai.GenerativeModel(m)
            selected_model_name = m
            print(f"✅ Model initialized: {selected_model_name}")
            break
        except Exception as e:
            print(f"⚠️ Model {m} not available: {str(e)[:50]}")
            continue

if not model:
    print("❌ Error: No available Gemini model found. Bot will run but analysis will be limited.")

# مصادر الأخبار (تم توسيعها لتشمل مصادر متعددة)
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",  # اقتصاد
    "https://www.arabfinance.com/ar/rss/rssbycat/3",  # شركات
    "http://feeds.mubasher.info/ar/EGX/news",         # مباشر EGX
]

MUBASHER_PULSE_URL = "https://www.mubasher.info/news/eg/pulse/stocks"

# الكلمات المفتاحية للأسهم والبورصة
STOCK_KEYWORDS = [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال",
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب",
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية", "موازنة",
    "الأسهم", "المؤشر", "الإغلاق", "الافتتاح", "الحد الأدنى", "الحد الأقصى"
]

SENT_NEWS_FILE = "sent_news.json"

def generate_news_hash(title, link):
    """توليد hash فريد للخبر لمنع التكرار"""
    content = f"{title}_{link}".encode('utf-8')
    return hashlib.md5(content).hexdigest()

async def analyze_news_with_gemini(title, description):
    """
    تحليل الخبر باستخدام Gemini مع دعم البحث المتقدم والتحليل المالي العميق.
    يحاكي أسلوب محللي Investing.com و Bloomberg.
    """
    if not model:
        return "⚠️ نموذج الذكاء الاصطناعي غير متاح حالياً. يتم إعادة المحاولة في الدورة التالية."

    # البرومبت المتقدم - محاكاة محلل مالي احترافي
    prompt = f"""أنت محلل أسهم محترف (Senior Equity Analyst) في منصة Investing.com المالية العالمية.
قم بتقديم تقرير بحثي شامل حول الخبر التالي:

📰 الخبر: {title}
📝 التفاصيل: {description}

المطلوب في التقرير (بصيغة احترافية):

1️⃣ **التحليل الأساسي (Fundamental Analysis)**
   - تأثير الخبر على القوائم المالية (الأرباح، الإيرادات، الأصول)
   - تقييم تأثره على نسب الربحية (P/E, ROE, ROA)
   - تقييم القيمة العادلة للسهم (Fair Value) إن أمكن

2️⃣ **التأثير على السهم**
   - التأثير المتوقع على سعر السهم (صعود/هبوط/محايد)
   - مستويات الدعم والمقاومة المتوقعة
   - الأفق الزمني للتأثير (فوري/قصير/متوسط/طويل الأجل)

3️⃣ **تحليل المخاطر والفرص**
   - المخاطر الرئيسية المرتبطة بالخبر
   - فرص النمو المحتملة
   - تقييم مستوى المخاطر (منخفض/متوسط/عالي)

4️⃣ **التوصية الاستثمارية**
   - توصية واضحة: 🟢 شراء (BUY) / 🟡 احتفاظ (HOLD) / 🔴 بيع (SELL)
   - السعر المستهدف (إن أمكن تقديره)
   - الأفق الزمني للتوصية

الأسلوب: احترافي، موجز، يشبه تقارير Investing Pro والمحللين المعتمدين.
الطول: 150-250 كلمة فقط (مختصر وفعال)."""

    try:
        response = model.generate_content(prompt, stream=False)
        if response and response.text:
            return response.text.strip()
        else:
            return "⚠️ لم يتمكن النموذج من تقديم تحليل. يرجى المحاولة لاحقاً."
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error in analyze_news_with_gemini: {error_msg[:100]}")

        # رسائل خطأ محسّنة
        if "404" in error_msg or "not found" in error_msg:
            return "⚠️ النموذج غير متاح حالياً. سيتم إعادة المحاولة في الدورة التالية."
        elif "quota" in error_msg.lower() or "rate" in error_msg.lower():
            return "⚠️ تم تجاوز حد الاستخدام المسموح. سيتم الانتظار قبل المحاولة التالية."
        elif "api_key" in error_msg.lower():
            return "⚠️ مشكلة في مفتاح API. يرجى التحقق من الإعدادات."
        else:
            return f"⚠️ خطأ في التحليل: {error_msg[:80]}"

def is_stock_related(title, description):
    """التحقق من أن الخبر متعلق بالأسهم والبورصة"""
    content = (title + " " + description).lower()
    return any(keyword in content for keyword in STOCK_KEYWORDS)

def load_sent_news():
    """تحميل قائمة الأخبار المرسلة سابقاً"""
    if os.path.exists(SENT_NEWS_FILE):
        try:
            with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading sent_news.json: {e}")
            return []
    return []

def save_sent_news(sent_news):
    """حفظ قائمة الأخبار المرسلة"""
    try:
        with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
            # الاحتفاظ بآخر 500 خبر فقط لتقليل حجم الملف
            json.dump(sent_news[-500:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving sent_news.json: {e}")

async def process_and_send(bot, news_hash, title, description, link, sent_news):
    """معالجة الخبر وإرساله إلى قناة Telegram"""
    if news_hash not in sent_news and is_stock_related(title, description):
        print(f"📰 Processing: {title[:60]}...")
        analysis = await analyze_news_with_gemini(title, description)

        # تنسيق الرسالة بشكل احترافي
        message = (
            f"🏛️ <b>تقرير بحوث البورصة المصرية</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>العنوان:</b>\n{title}\n\n"
            f"🔬 <b>التحليل البحثي المتعمق:</b>\n{analysis}\n\n"
            f"🔗 <a href='{link}'>المصدر الأصلي</a>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
            sent_news.append(news_hash)
            print(f"✅ Sent: {title[:60]}...")
            return True
        except Exception as e:
            print(f"❌ Error sending message: {e}")
    return False

async def fetch_and_process_rss(bot, sent_news):
    """جلب ومعالجة أخبار RSS"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for feed_url in RSS_FEEDS:
        try:
            print(f"🔄 Fetching: {feed_url[:50]}...")
            response = requests.get(feed_url, headers=headers, timeout=15)
            response.encoding = 'utf-8'
            feed = feedparser.parse(response.content)

            for entry in feed.entries[:15]:  # معالجة أحدث 15 خبر من كل مصدر
                try:
                    title = entry.get("title", "")
                    description = entry.get("description", entry.get("summary", ""))
                    link = entry.get("link", "")

                    if title and link:
                        news_hash = generate_news_hash(title, link)
                        await process_and_send(bot, news_hash, title, description, link, sent_news)
                        await asyncio.sleep(1)  # تأخير صغير بين الرسائل
                except Exception as e:
                    print(f"⚠️ Error processing entry: {str(e)[:50]}")
                    continue

        except Exception as e:
            print(f"⚠️ Error fetching {feed_url[:50]}: {str(e)[:50]}")
            continue

async def fetch_and_process_pulse(bot, sent_news):
    """جلب ومعالجة نبض الأسهم من مباشر"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    try:
        print(f"🔄 Fetching Mubasher Pulse...")
        response = requests.get(MUBASHER_PULSE_URL, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.content, 'html.parser')

        articles = soup.find_all('a', href=True)
        processed_count = 0

        for a in articles:
            if processed_count >= 10:  # معالجة أحدث 10 أخبار فقط
                break

            try:
                title = a.get_text(strip=True)
                link = a['href']

                if "/news/" in link and len(title) > 20:
                    if not link.startswith('http'):
                        link = "https://www.mubasher.info" + link

                    news_hash = generate_news_hash(title, link)
                    if await process_and_send(bot, news_hash, title, "خبر عاجل من نبض الأسهم", link, sent_news):
                        processed_count += 1
                        await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Error processing pulse entry: {str(e)[:50]}")
                continue

    except Exception as e:
        print(f"⚠️ Error fetching Mubasher Pulse: {str(e)[:50]}")

async def main():
    """الدالة الرئيسية للبوت"""
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("❌ Missing environment variables!")
        print(f"   TELEGRAM_TOKEN: {'✓' if TELEGRAM_TOKEN else '✗'}")
        print(f"   CHANNEL_ID: {'✓' if CHANNEL_ID else '✗'}")
        print(f"   GEMINI_API_KEY: {'✓' if GEMINI_API_KEY else '✗'}")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    sent_news = load_sent_news()

    # رسالة اختبار للتأكد من أن البوت يعمل
    if not sent_news:
        try:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text="🚀 <b>تم تفعيل نظام البحوث المالية بنجاح!</b>\n"
                     "البوت الآن يراقب أخبار البورصة المصرية 24/7 بتحليلات احترافية.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"⚠️ Error sending startup message: {e}")

    print(f"\n{'='*60}")
    print(f"🤖 EGX News Bot Started")
    print(f"📊 Model: {selected_model_name or 'Not available'}")
    print(f"📰 RSS Feeds: {len(RSS_FEEDS)}")
    print(f"📚 Tracked News: {len(sent_news)}")
    print(f"{'='*60}\n")

    # معالجة RSS Feeds
    await fetch_and_process_rss(bot, sent_news)

    # معالجة نبض الأسهم
    await fetch_and_process_pulse(bot, sent_news)

    # حفظ الحالة
    save_sent_news(sent_news)

    print(f"\n✅ Cycle completed. Total tracked news: {len(sent_news)}\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
