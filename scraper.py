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
    alerts = []
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Login
        print("Navigating to Betpawa login...")
        page.goto("https://www.betpawa.ng/", timeout=30000, wait_until="networkidle")
        try:
            # Try to click login button (adjust if site has a different flow)
            login_btn = page.query_selector("text=Login") or page.query_selector("a:has-text('Login')")
            if login_btn:
                login_btn.click()
                page.wait_for_timeout(2000)
            page.fill('input[type="tel"], input[placeholder="Phone number"]', BETPAWA_USER)
            page.fill('input[type="password"]', BETPAWA_PASS)
            page.click("button:has-text('Login')")
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Login exception (may be already logged in): {e}")

        # 2. Navigate to football section
        print("Navigating to football...")
        page.goto("https://www.betpawa.ng/sport/soccer", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        debug_info.append(f"Page title: {page.title()}")

        # 3. Try to find match elements (broad selector)
        # We'll try multiple common selectors and see which one catches anything
        selectors = [
            "div.event",
            "div.match",
            "div[class*='event']",
            "div[class*='match']",
            "div[class*='game']",
            "article",
            "div.row"  # very generic, just to see if something exists
        ]
        match_elements = []
        used_selector = None
        for sel in selectors:
            elems = page.query_selector_all(sel)
            if len(elems) > 0:
                match_elements = elems
                used_selector = sel
                break
        if not match_elements:
            # No matches found with any selector – grab page text to diagnose
            body_text = page.inner_text("body")[:500]
            debug_info.append(f"No match elements found. Body text sample: {body_text}")
            print("No match elements found.")
        else:
            debug_info.append(f"Found {len(match_elements)} elements using selector '{used_selector}'")
            # Try to extract first element's text for inspection
            first_elem_text = match_elements[0].inner_text()[:200]
            debug_info.append(f"First element text: {first_elem_text}")

        # ... (rest of the matching logic kept as is, but we'll also print match count)
        # For now, we skip the matching loop if no matches found
        if match_elements:
            # Placeholder for actual extraction – we'll implement proper parsing after seeing the structure
            pass

        browser.close()

    # Send debug info to Telegram as a message so you can see it immediately
    full_debug = "\n".join(debug_info) if debug_info else "No debug info collected"
    send_telegram(f"🔍 Scraper Debug:\n{full_debug}")
    if alerts:
        send_telegram(f"🚀 +EV Betpawa Alerts:\n" + "\n\n".join(alerts[:10]))
    else:
        send_telegram("ℹ️ No +EV bets found on Betpawa in this window.")

if __name__ == "__main__":
    main()
