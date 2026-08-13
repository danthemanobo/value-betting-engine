import os, requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram_chunks(text):
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

        def search_for_arsenal():
            search_icon = page.query_selector("button[aria-label*='search' i]")
            if search_icon:
                search_icon.click()
                page.wait_for_timeout(1000)
            search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
            if not search_input:
                return False
            search_input.fill("Arsenal")
            search_input.press("Enter")
            page.wait_for_timeout(5000)
            return True

        correct_found = False
        attempts = 0
        max_attempts = 15

        while not correct_found and attempts < max_attempts:
            attempts += 1
            if not search_for_arsenal():
                send_telegram_chunks("Search input not found.")
                break

            result_elements = page.query_selector_all("div[class*='event']")
            for idx in range(len(result_elements)):
                if not search_for_arsenal():
                    break
                result_elements = page.query_selector_all("div[class*='event']")
                if idx >= len(result_elements):
                    break
                elem = result_elements[idx]
                text = elem.inner_text()
                text_lower = text.lower()
                if 'football' not in text_lower:
                    continue

                try:
                    elem.click()
                    page.wait_for_timeout(5000)
                except:
                    continue

                body_text = page.inner_text("body")
                body_lower = body_text.lower()
                if 'arsenal' in body_lower and 'manchester city' in body_lower:
                    correct_found = True
                    # Send confirmation without URL
                    send_telegram_chunks("✅ Correct match found (Arsenal vs Manchester City).")

                    lines = body_text.split('\n')
                    start_idx = None
                    for i, line in enumerate(lines):
                        if "1X2 | Full Time" in line:
                            start_idx = i
                            break
                    if start_idx is not None:
                        end_idx = min(start_idx + 80, len(lines))
                        market_text = "\n".join(lines[start_idx:end_idx])
                        send_telegram_chunks(market_text)
                    else:
                        send_telegram_chunks("No 1X2 market section located.")
                    break
                else:
                    page.go_back()
                    page.wait_for_timeout(3000)

        if not correct_found:
            send_telegram_chunks("Could not find correct match after attempts.")

        browser.close()

if __name__ == "__main__":
    main()
