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
    """Fetch the most recent match from Firestore matches collection."""
    try:
        docs = db.collection("matches").order_by("stored_at", direction=firestore.Query.DESCENDING).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            return doc.id, data
    except Exception as e:
        print(f"Firestore query error: {e}")
    return None, None

def main():
    # 1. Get a match
    match_id, match_data = get_latest_match()
    if not match_data:
        send_telegram_plain("No matches found in Firestore.")
        return

    home = match_data.get("home", "")
    away = match_data.get("away", "")
    print(f"Using match: {home} vs {away}")

    # 2. Build search query
    query = f"{home} {away} betpawa"
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&hl=en&gl=us"
    print(f"Search URL: {search_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 3. Navigate to Google search
        page.goto(search_url, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # 4. Extract all links that contain betpawa.ng
        links = page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a'));
            return anchors
                .map(a => a.href)
                .filter(href => href && href.includes('betpawa.ng'))
                .slice(0, 10);
        }""")

        if not links:
            send_telegram_plain("No Betpawa.ng links found on Google first page. Could be CAPTCHA or different results.")
            browser.close()
            return

        target_url = links[0]
        print(f"Opening first Betpawa link: {target_url}")

        # 5. Open the match page directly
        page.goto(target_url, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # 6. Extract page text (first 2500 characters)
        body_text = page.inner_text("body")[:2500]
        browser.close()

    # 7. Send to Telegram
    message = f"🔍 Google search test successful\nMatch: {home} vs {away}\nURL: {target_url}\n\nPage text snippet:\n{body_text}"
    send_telegram_plain(message[:4000])  # split if needed

if __name__ == "__main__":
    main()
