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
    home_original = match.get("home", "")
    away_original = match.get("away", "")
    debug = []

    # Generate candidate search terms
    candidates = []
    normalized = home_original.replace("-", " ").strip()
    if normalized != home_original:
        candidates.append(normalized)
    if " " in normalized:
        candidates.append(normalized.split(" ")[0])  # first word
    candidates.append(home_original)  # original as fallback

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Click search icon
        search_icon = page.query_selector("button[aria-label*='search' i]")
        if search_icon:
            search_icon.click()
            page.wait_for_timeout(1500)

        search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
        if not search_input:
            debug.append("No search input found.")
            send_telegram_plain("🔍 Normalize Debug:\n" + "\n".join(debug))
            browser.close()
            return

        for term in candidates:
            # Clear input
            search_input.click()
            search_input.fill("")
            page.wait_for_timeout(500)
            search_input.fill(term)
            page.wait_for_timeout(500)
            search_input.press("Enter")
            page.wait_for_timeout(4000)
            count = page.locator("div[class*='event']").count()
            debug.append(f"Search term: '{term}' -> {count} results")
            if count > 0:
                # Show first 2 results
                events = page.query_selector_all("div[class*='event']")
                for i, e in enumerate(events[:2], 1):
                    debug.append(f"  Match {i}: {e.inner_text()[:150]}")
                break  # stop after first successful term

        browser.close()

    send_telegram_plain("🔍 Normalize Debug:\n" + "\n".join(debug))

if __name__ == "__main__":
    main()
