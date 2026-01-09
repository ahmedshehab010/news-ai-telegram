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
    قم بتقديم تقرير بحثي مصغر حول الخبر التالي:
    الخبر: {title}
    التفاصيل: {description}
    
    المطلوب: تحليل أساسي، تأثير القيمة، مصفوفة المخاطر، وتوصية استثمارية واضحة.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"عذراً، تعذر إجراء البحث المالي: {e}"

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
        message = (
            f"🏛 <b>تقرير بحوث البورصة المصرية</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 <b>العنوان:</b> {title}\n\n"
            f"🔬 <b>التحليل البحثي المتعمق:</b>\n{analysis}\n\n"
            f"🔗 <a href='{link}'>المصدر الأصلي</a>"
        )
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
            sent_news.append(news_id)
            return True
        except Exception as e:
            print(f"Error sending: {e}")
    return False

async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, GEMINI_API_KEY]):
        print("Missing environment variables!")
        return
        
    bot = Bot(token=TELEGRAM_TOKEN)
    sent_news = load_sent_news()
    
    # رسالة اختبار للتأكد من أن البوت يعمل (سيتم إرسالها مرة واحدة فقط إذا كان الملف فارغاً)
    if not sent_news:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text="🚀 <b>تم تفعيل نظام البحوث المالية بنجاح!</b>\nالبوت الآن يراقب أخبار البورصة المصرية 24/7.", parse_mode=ParseMode.HTML)
        except: pass

    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # فحص الـ RSS
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=headers, timeout=20)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:10]:
                news_id = entry.get("guid", entry.link)
                await process_and_send(bot, news_id, entry.title, entry.get("description", ""), entry.link, sent_news)
        except: pass
    
    # فحص نبض الأسهم (كشط مباشر)
    try:
        response = requests.get(MUBASHER_PULSE_URL, headers=headers, timeout=20)
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all('a', href=True)
        for a in articles:
            title = a.get_text(strip=True)
            link = a['href']
            if "/news/" in link and len(title) > 20:
                if not link.startswith('http'): link = "https://www.mubasher.info" + link
                news_id = link.split('/')[-1] or link
                await process_and_send(bot, news_id, title, "خبر عاجل من نبض الأسهم.", link, sent_news)
    except: pass
    
    save_sent_news(sent_news)

if __name__ == "__main__":
    asyncio.run(main())
