import os, requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Click search icon and input
        search_icon = page.query_selector("button[aria-label*='search' i]")
        if search_icon:
            search_icon.click()
            page.wait_for_timeout(1000)

        search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
        if not search_input:
            send_telegram("No search input found")
            browser.close()
            return

        search_input.fill("Arsenal")
        search_input.press("Enter")
        page.wait_for_timeout(5000)

        # Find first football result containing Arsenal
        result_elements = page.query_selector_all("div[class*='event']")
        clicked = False
        for elem in result_elements:
            text = elem.inner_text()
            text_lower = text.lower()
            if 'football' in text_lower and 'arsenal' in text_lower:
                try:
                    elem.click()
                    page.wait_for_timeout(5000)
                    clicked = True
                    break
                except Exception as e:
                    continue
        if not clicked:
            send_telegram("Could not click Arsenal match")
            browser.close()
            return

        # Capture URL and title, and verify away team
        url = page.url
        title = page.title()
        body_text = page.inner_text("body")

        if 'Manchester City' not in body_text:
            send_telegram(f"Clicked wrong match.\nURL: {url}\nTitle: {title}\nBody snippet: {body_text[:400]}")
            browser.close()
            return

        # Find the element containing "1X2 | Full Time"
        target = page.locator("text=1X2 | Full Time").first
        if target.count() == 0:
            send_telegram("Could not find 1X2 market")
            browser.close()
            return

        # Get parent HTML (the market container with odds)
        parent_html = target.evaluate("el => el.parentElement.outerHTML")

        # Send first 3000 chars of that HTML
        send_telegram(f"✅ Correct match: {url}\nTitle: {title}\n1X2 Market HTML:\n{parent_html[:3000]}")
        browser.close()

if __name__ == "__main__":
    main()
