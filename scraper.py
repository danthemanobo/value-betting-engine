import os, json, re, requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BETPAWA_USER = os.environ['BETPAWA_USERNAME']
BETPAWA_PASS = os.environ['BETPAWA_PASSWORD']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

MIN_EV = 0.05

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_real_utc_now():
    try:
        resp = requests.get("http://worldtimeapi.org/api/timezone/Etc/UTC", timeout=5)
        if resp.status_code == 200:
            return datetime.fromisoformat(resp.json()["datetime"]).replace(tzinfo=timezone.utc)
    except:
        pass
    return datetime.now(timezone.utc)

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    debug_info = []
    alerts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Login
        print("Logging in...")
        page.goto("https://www.betpawa.ng/", timeout=30000, wait_until="networkidle")
        try:
            login_btn = page.query_selector("text=Login") or page.query_selector("a:has-text('Login')")
            if login_btn:
                login_btn.click()
                page.wait_for_timeout(2000)
            page.fill('input[type="tel"], input[placeholder="Phone number"]', BETPAWA_USER)
            page.fill('input[type="password"]', BETPAWA_PASS)
            page.click("button:has-text('Login')")
            page.wait_for_timeout(5000)
        except Exception as e:
            debug_info.append(f"Login skipped: {e}")

        # 2. Go directly to the upcoming matches URL (1X2 market)
        target_url = "https://www.betpawa.ng/events?categoryId=2&marketId=1X2"
        print(f"Navigating to {target_url}")
        page.goto(target_url, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # 3. Scroll down to load more matches
        for i in range(5):  # scroll 5 times
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        # 4. Try to find match elements with common betting site selectors
        selectors = [
            "div.event", "div.match-row", "div[class*='event']", "div[class*='match']",
            "div[class*='game']", "article", "div.row", "div.col"  # very generic last
        ]
        match_elements = []
        used_selector = None
        for sel in selectors:
            elems = page.query_selector_all(sel)
            if len(elems) > 3:  # at least a few matches
                match_elements = elems
                used_selector = sel
                break

        if not match_elements:
            # Fallback: get a chunk of page text for debugging
            body_text = page.inner_text("body")[:600]
            debug_info.append(f"No match elements found. Body snippet: {body_text}")
            # Also try to get all text nodes that look like "vs"
            vs_elements = page.query_selector_all("text=/.* vs .*/")
            if vs_elements:
                debug_info.append(f"Found {len(vs_elements)} elements containing 'vs'")
                for e in vs_elements[:3]:
                    debug_info.append(f"Sample vs element: {e.inner_text()[:100]}")
        else:
            debug_info.append(f"Found {len(match_elements)} elements using '{used_selector}'")
            # Sample first element's full inner text
            sample = match_elements[0].inner_text()[:300]
            debug_info.append(f"Sample match text:\n{sample}")
            # Attempt to extract odds and teams from the first element using regex
            # (This will be refined after we see the real text)

        # 5. (Placeholder) When selectors are confirmed, we'll loop through match_elements,
        #    extract teams, kickoff time, 1X2 odds, match with Firestore, compute EV.
        browser.close()

    send_telegram(f"🔍 Scraper Debug:\n" + "\n".join(debug_info))
    if alerts:
        send_telegram(f"🚀 +EV Betpawa Alerts:\n" + "\n\n".join(alerts[:10]))
    else:
        send_telegram("ℹ️ No +EV bets found on Betpawa in this window.")

if __name__ == "__main__":
    main()
