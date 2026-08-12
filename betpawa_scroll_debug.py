import os, json, requests, re
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
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Initial count
        count = page.locator("div[class*='event']").count()
        debug.append(f"Initial match count: {count}")

        # Determine scroll container: use document.scrollingElement or body
        scroll_info = page.evaluate("""() => {
            const el = document.scrollingElement || document.body;
            return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, scrollTop: el.scrollTop };
        }""")
        debug.append(f"Scroll info before: scrollHeight={scroll_info['scrollHeight']}, clientHeight={scroll_info['clientHeight']}, scrollTop={scroll_info['scrollTop']}")

        # Scroll in steps using mouse wheel and window scroll
        for step in range(1, 11):
            # Scroll down by 800px
            page.evaluate("window.scrollTo(0, window.scrollY + 800)")
            page.wait_for_timeout(2000)

            new_count = page.locator("div[class*='event']").count()
            scroll_info2 = page.evaluate("""() => {
                const el = document.scrollingElement || document.body;
                return { scrollTop: el.scrollTop, scrollHeight: el.scrollHeight };
            }""")
            debug.append(f"After scroll {step}: count={new_count}, scrollTop={scroll_info2['scrollTop']}, scrollHeight={scroll_info2['scrollHeight']}")

            # If count hasn't increased, try to find load more button
            if new_count <= count:
                # Look for buttons with text containing 'load', 'more', 'show'
                buttons = page.query_selector_all("button")
                load_btn = None
                for btn in buttons:
                    txt = (btn.inner_text() or "").strip().lower()
                    if any(word in txt for word in ['load', 'more', 'show', 'next']):
                        load_btn = btn
                        break
                if load_btn:
                    debug.append(f"Found possible load button: '{load_btn.inner_text()}' – clicking it")
                    load_btn.click()
                    page.wait_for_timeout(3000)
                    new_count = page.locator("div[class*='event']").count()
                    debug.append(f"After click, count={new_count}")
                else:
                    debug.append("No load button found in current view.")
            else:
                debug.append("Count increased.")
            count = new_count

        browser.close()

    send_telegram_plain("🔍 Betpawa Scroll Debug:\n" + "\n".join(debug))

if __name__ == "__main__":
    main()
