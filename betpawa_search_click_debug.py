import os, json, re, requests
from playwright.sync_api import sync_playwright
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

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

def get_latest_match():
    try:
        docs = db.collection("matches").order_by("stored_at", direction=firestore.Query.DESCENDING).limit(1).stream()
        for doc in docs:
            return doc.to_dict()
    except Exception as e:
        print(f"Firestore error: {e}")
    return None

def main():
    match = get_latest_match()
    if not match:
        send_telegram_plain("No match in Firestore.")
        return
    home = match.get("home", "")
    away = match.get("away", "")
    debug = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Identify search input and button
        search_input = page.query_selector('input[type="search"], input[type="text"], input[placeholder*="search" i], input[placeholder*="Search"]')
        if not search_input:
            debug.append("No search input found.")
            send_telegram_plain("🔍 Betpawa Search Click Debug:\n" + "\n".join(debug))
            browser.close()
            return

        debug.append(f"Search input found. Typing: {home}")
        search_input.click()
        search_input.fill(home)
        page.wait_for_timeout(1000)

        # Try to click search button (common patterns: button with text 'Search', or icon button)
        search_button = page.query_selector('button:has-text("Search"), button:has-text("search"), button[aria-label*="search" i]')
        if search_button:
            debug.append("Clicking search button.")
            search_button.click()
            page.wait_for_timeout(3000)
        else:
            debug.append("No explicit search button found. Pressing Enter.")
            search_input.press("Enter")
            page.wait_for_timeout(3000)

        # Count events after search
        count = page.locator("div[class*='event']").count()
        debug.append(f"Event count after search: {count}")

        # Extract text of first 5 events
        events = page.query_selector_all("div[class*='event']")
        for i, e in enumerate(events[:5], 1):
            debug.append(f"Match {i}: {e.inner_text()[:200]}")

        browser.close()

    send_telegram_plain("🔍 Betpawa Search Click Debug:\n" + "\n".join(debug))

if __name__ == "__main__":
    main()
