import feedparser
import asyncio
import os
import json
import requests
import random
from bs4 import BeautifulSoup
from openai import OpenAI
from telegram import Bot
from telegram.constants import ParseMode

# الإعدادات من متغيرات البيئة (للحماية في GitHub)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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
AI_MODELS = ["gpt-4.1-mini", "gpt-4.1-nano", "gemini-2.5-flash"]

client = OpenAI(api_key=OPENAI_API_KEY)

async def analyze_news(title, description):
    selected_model = random.choice(AI_MODELS)
    prompt = f"""
    أنت محلل مالي خبير متخصص في التحليل الأساسي (Fundamental Analysis) بالبورصة المصرية. 
    قم بتحليل الخبر التالي وتقديم رؤية استثمارية مختصرة:
    العنوان: {title}
    التفاصيل: {description}
    
    المطلوب في التحليل:
    1. **تحليل أساسي سريع**: (كيف يؤثر الخبر على القوائم المالية، الربحية، أو الملاءة المالية للشركة؟).
    2. **تأثير الخبر على الشركة**: (هل هو محفز للنمو، أم مخاطرة تشغيلية، أم إجراء روتيني؟).
    3. **التقييم**: (إيجابي / سلبي / متعادل) مع ذكر السبب باختصار.
    4. **نصيحة للمستثمر**: (ماذا يجب أن يفعل حامل السهم أو الراغب في الشراء؟).

    اجعل التحليل باللغة العربية، بأسلوب مهني، وبشكل نقاط واضحة ومختصرة جداً.
    """
    try:
        response = client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return "عذراً، تعذر تحليل الخبر في الوقت الحالي."

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
        print(f"Processing: {title}")
        analysis = await analyze_news(title, description)
        message = (
            f"<b>📈 تحليل سهم: {title}</b>\n\n"
            f"📝 <b>الخبر:</b> {description}\n\n"
            f"🔍 <b>التحليل الأساسي (AI):</b>\n{analysis}\n\n"
            f"🔗 <a href='{link}'>المصدر والتفاصيل</a>"
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
                    await asyncio.sleep(2)
            if count >= 5: break
    except: pass

async def main():
    if not all([TELEGRAM_TOKEN, CHANNEL_ID, OPENAI_API_KEY]):
        print("Missing environment variables!")
        return
        
    bot = Bot(token=TELEGRAM_TOKEN)
    sent_news = load_sent_news()
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=headers, timeout=20)
            feed = feedparser.parse(response.content)
            for entry in feed.entries[:10]:
                news_id = entry.get("guid", entry.link)
                await process_and_send(bot, news_id, entry.title, entry.get("description", ""), entry.link, sent_news)
        except: pass
    
    await scrape_mubasher_pulse(bot, sent_news)
    save_sent_news(sent_news)

if __name__ == "__main__":
    asyncio.run(main())
