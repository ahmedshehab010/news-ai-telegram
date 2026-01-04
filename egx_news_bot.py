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

# الإعدادات من متغيرات البيئة
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# إعداد Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # استخدام موديل Pro لقدرات بحث وتحليل أعمق
    model = genai.GenerativeModel('gemini-1.5-pro')

# مصادر الأخبار
RSS_FEEDS = [
    "https://www.arabfinance.com/ar/rss/rssbycat/2",
    "https://www.arabfinance.com/ar/rss/rssbycat/3",
    "http://feeds.mubasher.info/ar/EGX/news",
]
MUBASHER_PULSE_URL = "https://www.mubasher.info/news/eg/pulse/stocks"

STOCK_KEYWORDS = [
    "سهم", "أسهم", "بورصة", "ارباح", "أرباح", "خسائر", "نتائج أعمال", 
    "زيادة رأس مال", "توزيع كوبون", "استحواذ", "اندماج", "اكتتاب", 
    "القوائم المالية", "مجلس إدارة", "إفصاح", "تداول", "البورصة المصرية",
    "EGX", "كوبون", "جمعية عمومية", "هيئة الرقابة المالية", "موازنة"
]

SENT_NEWS_FILE = "sent_news.json"

async def analyze_news(title, description):
    prompt = f"""
    أنت رئيس قسم البحوث المالية (Head of Equity Research) في بنك استثمار مرموق. 
    مهمتك هي تقديم "تقرير بحثي مصغر" (Mini Research Report) حول الخبر التالي لتقديم قيمة حقيقية للمستثمرين في البورصة المصرية.
    
    الخبر: {title}
    التفاصيل: {description}
    
    المطلوب في التقرير البحثي:
    1. **السياق الاستراتيجي (Strategic Context)**: اربط الخبر بوضع الشركة الحالي في السوق المصري. هل هذا الخبر يعزز حصتها السوقية؟ هل يحل مشكلة سيولة؟
    2. **التحليل المالي العميق (Financial Deep Dive)**: حلل الأرقام المذكورة. إذا كانت أرباحاً، قارنها بالتوقعات أو الأداء التاريخي (بناءً على معرفتك). إذا كان استحواذاً، حلل مضاعف الاستحواذ المحتمل.
    3. **تأثير القيمة (Value Impact)**: كيف سيؤثر هذا الخبر على "القيمة العادلة" (Fair Value) للسهم على المدى المتوسط والبعيد؟
    4. **مصفوفة المخاطر والفرص (Risk/Reward Matrix)**: اذكر أهم فرصة يخلقها الخبر وأخطر ريسك قد يواجه التنفيذ.
    5. **التوصية الاستثمارية النهائية (Investment Verdict)**: (شراء / احتفاظ / بيع / مراقبة) مع تبرير منطقي قوي جداً للمستثمر الذكي.

    اجعل الأسلوب: احترافي، تحليلي، بعيد عن السطحية، وباللغة العربية الفصحى المهنية. استخدم الرموز التعبيرية (Emojis) بشكل طفيف للتنظيم فقط.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "عذراً، تعذر إجراء البحث المالي المتعمق حالياً."

def is_stock_related(title, description):
    content = (title + " " + description).lower()
    return any(keyword in content for keyword in STOCK_KEYWORDS)

def load_sent_news():
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, "r") as f:
            try: return json.load(f)
            except: return []
    return []

def save_sent_news(sent_news):
    with open(SENT_NEWS_FILE, "w") as f:
        json.dump(sent_news[-500:], f)

async def process_and_send(bot, news_id, title, description, link, sent_news):
    if news_id not in sent_news and is_stock_related(title, description):
        print(f"Researching: {title}")
        analysis = await analyze_news(title, description)
        
        # تنسيق الرسالة لتظهر كتقرير رسمي
        message = (
            f"🏛 <b>تقرير بحوث البورصة المصرية</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 <b>العنوان:</b> {title}\n\n"
            f"📰 <b>ملخص الخبر:</b>\n{description[:300]}...\n\n"
            f"🔬 <b>التحليل البحثي المتعمق:</b>\n{analysis}\n\n"
            f"🔗 <a href='{link}'>المصدر الأصلي</a>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ <i>هذا التحليل تم بواسطة ذكاء اصطناعي متطور لأغراض استرشادية فقط.</i>"
        )
        
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
            sent_news.append(news_id)
            return True
        except Exception as e:
            print(f"Error sending: {e}")
    return False

async def scrape_mubasher_pulse(bot, sent_news):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(MUBASHER_PULSE_URL, headers=headers, timeout=20)
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all('a', class_='mi-article-list-item__title') or soup.find_all('a', href=True)
        count = 0
        for a in articles:
            title = a.get_text(strip=True)
            link = a['href']
            if not link.startswith('http'): link = "https://www.mubasher.info" + link
            news_id = link.split('/')[-1] or link
            if news_id not in sent_news and "/news/" in link and len(title) > 20:
                if await process_and_send(bot, news_id, title, "خبر عاجل من نبض الأسهم.", link, sent_news):
                    count += 1
                    await asyncio.sleep(5) # زيادة الوقت للتحليل العميق
            if count >= 3: break # تقليل العدد لضمان جودة البحث لكل خبر
    except: pass

async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("Missing environment variables!")
        return
        
    bot = Bot(token=TELEGRAM_TOKEN)
    sent_news = load_sent_news()
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=headers, timeout=20)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:5]:
                news_id = entry.get("guid", entry.link)
                await process_and_send(bot, news_id, entry.title, entry.get("description", ""), entry.link, sent_news)
        except: pass
    
    await scrape_mubasher_pulse(bot, sent_news)
    save_sent_news(sent_news)

if __name__ == "__main__":
    asyncio.run(main())
