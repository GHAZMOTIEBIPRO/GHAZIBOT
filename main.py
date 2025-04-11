import requests
import datetime

BOT_TOKEN = 7861299512:AAGsi-9f4LSWvsP87FdKklYurzhTYYPSq5A
CHAT_ID = 1357518677

us_stocks = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "INTC", "ADBE", "NFLX",
    "JPM", "BAC", "GS", "V", "MA", "BRK.B", "MS",
    "JNJ", "PFE", "MRNA", "MRK", "ABBV", "LLY",
    "BA", "LMT", "GE", "HON",
    "XOM", "CVX", "COP",
    "WMT", "PG", "KO", "PEP", "MCD", "SBUX",
    "VZ", "T", "DIS", "CMCSA",
    "UBER", "ABNB", "ZM", "PLTR"
]

saudi_stocks = [
    "الراجحي", "الأهلي", "سامبا", "الرياض", "البلاد", "الإنماء", "الجزيرة", "العربي الوطني", "السعودي الفرنسي", "الخليجية",
    "سابك", "سابك للمغذيات الزراعية", "كيمانول", "السعودية للصناعات الأساسية (سابك)", "بترو رابغ", "نماء للكيماويات", "لازوردي",
    "مجموعة صيدا", "الدواء", "النهدي", "العربية للخدمات الطبية", "السعودية للخدمات الطبية",
    "الاتصالات السعودية (STC)", "موبايلي", "زين السعودية", "حلول الاتصالات", "تقنية",
    "المراعي", "صافولا", "الأسماك", "نادك", "التنمية الزراعية", "بنده", "جرير", "العثيم",
    "الأسمنت العربية", "اسمنت الجنوبية", "اسمنت القصيم", "اسمنت السعودية", "اسمنت ينبع",
    "دار الأركان", "المملكة", "جبل عمر", "العقارية", "ينبع",
    "التعاونية", "سلام", "أليانز إس إف", "ولاء", "العربية",
    "البحري", "الخطوط السعودية", "الزاهد", "العربية للأنابيب",
    "الكهرباء السعودية", "أكوا باور", "الطاقة", "الغاز"
]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, json=payload)

def fake_analysis(stock_name):
    # تحاكي عملية تحليل فني وهمي لتجربة التنبيه
    if datetime.datetime.now().second % 30 == 0:
        return True, "RSI إيجابي + شمعة انعكاسية + حجم تداول مرتفع"
    return False, ""

def analyze_all_stocks():
    for stock in us_stocks + saudi_stocks:
        match, reason = fake_analysis(stock)
        if match:
            msg = f"""إشارة دخول مضاربية (تجريبية)
السهم: {stock}
نوع الصفقة: يومية / أسبوعية
الفريم: يومي وأسبوعي
السبب: {reason}
التحليل تم: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"""
            send_telegram(msg)

if __name__ == "__main__":
    analyze_all_stocks()
