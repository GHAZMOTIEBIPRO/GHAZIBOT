import requests
import os

bot_token = os.getenv("BOT_TOKEN")
chat_id = os.getenv("CHAT_ID")

message = '''
إشارة دخول مضاربية (تجريبية)
السهم: AAPL
نوع الصفقة: يومية
الفريم: ساعة
السبب: اختراق مقاومة + شمعة ابتلاعية + RSI إيجابي
السعر الحالي: 172.35
الأهداف: 176.20 / 174.50
وقف الخسارة: 169.90
'''

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "HTML"
}

response = requests.post(url, data=payload)
print(response.text)
