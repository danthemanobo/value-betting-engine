import os, json, requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Load Leagues page
        print("Loading leagues page...")
        page.goto("https://www.pinnacle.com/en/soccer/leagues/", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # 2. Extract top league links, filtering out highlights/live/futures
        links = page.eval_on_selector_all(
            "a",
            """els => els
                .filter(e => e.href && e.href.includes('/soccer/') && e.href.includes('/matchups/'))
                .filter(e => !e.href.includes('/matchups/highlights/') && !e.href.includes('/matchups/live/') && !e.href.includes('/matchups/futures/'))
                .map(e => ({href: e.href, text: e.innerText.trim()}))
                .filter(x => x.text.length > 0)
                .slice(0, 10)"""
        )
        debug_info.append(f"Filtered league links: {len(links)}")
        for i, l in enumerate(links[:10], 1):
            debug_info.append(f"{i}. {l['text']} -> {l['href']}")

        if not links:
            debug_info.append("No real league links found.")
            send_telegram(f"🔍 Pinnacle League Debug:\n" + "\n".join(debug_info))
            browser.close()
            return

        # 3. Visit the first real league link
        first_league = links[0]
        debug_info.append(f"\nVisiting first real league: {first_league['text']}")
        page.goto(first_league['href'], timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # 4. Scroll to load matches
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(1000)

        # 5. Find match elements
        match_elements = page.query_selector_all("div[class*='match']")
        debug_info.append(f"Found {len(match_elements)} match elements.")

        if match_elements:
            # Get outerHTML of the first match element
            first_html = match_elements[0].evaluate("el => el.outerHTML")
            # Truncate to avoid Telegram limit
            debug_info.append(f"First match outerHTML (truncated):\n{first_html[:3000]}")
        else:
            body_text = page.inner_text("body")[:1000]
            debug_info.append(f"No match elements found. Body snippet:\n{body_text}")

        browser.close()

    send_telegram(f"🔍 Pinnacle League Debug:\n" + "\n\n".join(debug_info)[:4000])
    print("Debug sent.")

if __name__ == "__main__":
    main()
