import os, json, re, requests, urllib.parse
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
            data = doc.to_dict()
            return doc.id, data
    except Exception as e:
        print(f"Firestore query error: {e}")
    return None, None

def main():
    # Fetch a match
    match_id, match_data = get_latest_match()
    if not match_data:
        send_telegram_plain("No matches found in Firestore.")
        return

    home = match_data.get("home", "")
    away = match_data.get("away", "")
    print(f"Using match: {home} vs {away}")

    query = f"{home} {away} betpawa"
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&hl=en&gl=us"
    print(f"Search URL: {search_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(search_url, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        title = page.title()
        body_text = page.inner_text("body")[:1200]

        # Capture Betpawa links
        links = page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a'));
            return anchors
                .map(a => a.href)
                .filter(href => href && href.includes('betpawa.ng'))
                .slice(0, 10);
        }""")

        browser.close()

    # Compose diagnostic message
    message = f"🔍 Google Search Diagnostic\nMatch: {home} vs {away}\nPage title: {title}\nBetpawa links found: {len(links)}\n\nBody snippet:\n{body_text}"
    send_telegram_plain(message[:4000])

if __name__ == "__main__":
    main()
