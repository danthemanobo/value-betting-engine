import os, requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram_plain(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    debug = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Mobile viewport
        page = browser.new_page(viewport={"width": 390, "height": 844})
        debug.append("Viewport set to 390x844 (mobile)")

        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Initial count
        count = page.locator("div[class*='event']").count()
        debug.append(f"Initial match count: {count}")

        # Scroll using mouse wheel (simulates real user) inside the page
        for step in range(1, 16):
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(2000)
            new_count = page.locator("div[class*='event']").count()
            debug.append(f"After wheel scroll {step}: count={new_count}")
            if new_count > count:
                debug.append("Count increased!")
            count = new_count

        # Try container scrolling again (just in case)
        container = page.query_selector(".ScrollableWrapper_container__U3Z_d")
        if container:
            debug.append("Found scroll container, scrolling it directly...")
            for i in range(10):
                page.evaluate("""(sel) => {
                    const el = document.querySelector(sel);
                    if (el) el.scrollTop = el.scrollHeight;
                }""", ".ScrollableWrapper_container__U3Z_d")
                page.wait_for_timeout(1500)
                count = page.locator("div[class*='event']").count()
                debug.append(f"After container scroll {i+1}: count={count}")

        browser.close()

    send_telegram_plain("🔍 Betpawa Mobile Debug:\n" + "\n".join(debug))

if __name__ == "__main__":
    main()
