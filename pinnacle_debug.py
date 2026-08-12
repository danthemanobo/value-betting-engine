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

        print("Navigating to Pinnacle Leagues page...")
        page.goto("https://www.pinnacle.com/en/soccer/leagues/", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll down to load content
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(1000)

        debug_info.append(f"Page title: {page.title()}")
        debug_info.append(f"Current URL: {page.url}")

        # Try to find league links or cards
        # Common selectors for league items on bookmaker sites
        selectors = [
            "a[href*='league']",
            "a[href*='soccer']",
            "div[class*='league']",
            "div[class*='sport']",
            "div[class*='competition']",
            "div[class*='event']",
            "article",
            "div.row"
        ]
        found_counts = {}
        for sel in selectors:
            count = page.locator(sel).count()
            if count > 0:
                found_counts[sel] = count

        debug_info.append(f"Selector counts: {found_counts}")

        # Capture a snippet of page text for structure analysis
        body_text = page.inner_text("body")[:1000]
        debug_info.append(f"Body text sample:\n{body_text}")

        # Also get all unique hrefs that might be league links
        links = page.eval_on_selector_all("a", "els => els.map(e => e.href).filter(h => h && h.includes('league') || h.includes('soccer'))")
        debug_info.append(f"Potential league links (first 10): {links[:10]}")

        browser.close()

    full_debug = "\n\n".join(debug_info)
    send_telegram(f"🔍 Pinnacle Debug:\n{full_debug[:4000]}")  # Telegram limit ~4096 chars
    print("Debug sent.")

if __name__ == "__main__":
    main()
