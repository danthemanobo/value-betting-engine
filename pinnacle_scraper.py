import os, json, re, requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

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

def de_vig_three_way(o1, o2, o3):
    imp1 = 1/o1; imp2 = 1/o2; imp3 = 1/o3; ov = imp1+imp2+imp3
    return imp1/ov, imp2/ov, imp3/ov

def parse_match_row(row):
    """Extract home, away, kickoff_utc, odds dict from a row element."""
    try:
        # Team names
        team_labels = row.query_selector_all("span.gameInfoLabel-EDDYv5xEfd")
        if len(team_labels) < 2:
            return None
        home = team_labels[0].inner_text().replace(" (Match)", "").strip()
        away = team_labels[1].inner_text().replace(" (Match)", "").strip()

        # Kickoff time
        time_elem = row.query_selector("div.matchupDate-tnomIYorwa")
        if not time_elem:
            return None
        time_str = time_elem.inner_text().strip()  # e.g., "22:00"
        # parse time assuming GMT (Pinnacle shows GMT)
        now = get_real_utc_now()
        try:
            hour, minute = map(int, time_str.split(":"))
        except:
            return None
        kickoff = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # if time is earlier than now, assume tomorrow
        if kickoff < now:
            kickoff += timedelta(days=1)
        kickoff = kickoff.replace(tzinfo=timezone.utc)

        # 1X2 odds (three buttons)
        odds_spans = row.query_selector_all("span.price-r5BU0ynJha")
        if len(odds_spans) < 3:
            return None
        odds = {
            "home": float(odds_spans[0].inner_text().strip()),
            "draw": float(odds_spans[1].inner_text().strip()),
            "away": float(odds_spans[2].inner_text().strip())
        }
        return {"home": home, "away": away, "kickoff": kickoff, "odds": odds}
    except Exception as e:
        print(f"Row parse error: {e}")
        return None

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    stored_count = 0
    total_rows = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Load leagues page
        print("Loading leagues page...")
        page.goto("https://www.pinnacle.com/en/soccer/leagues/", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # 2. Extract top league links (real leagues)
        league_links = page.eval_on_selector_all(
            "a",
            """els => els
                .filter(e => e.href && e.href.includes('/soccer/') && e.href.includes('/matchups/'))
                .filter(e => !e.href.includes('/matchups/highlights/') && !e.href.includes('/matchups/live/') && !e.href.includes('/matchups/futures/'))
                .map(e => ({href: e.href, text: e.innerText.trim()}))
                .filter(x => x.text.length > 0)
                .slice(0, 10)"""
        )
        print(f"Found {len(league_links)} league links")

        # 3. Visit each league page and scrape matches
        for league in league_links:
            league_name = league['text']
            print(f"Scraping league: {league_name}")
            try:
                page.goto(league['href'], timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(4000)

                # Scroll a few times
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                    page.wait_for_timeout(1000)

                # Get all match rows (class contains row-u9F3b9WCM3)
                rows = page.query_selector_all("div.row-u9F3b9WCM3")
                print(f"  Rows found: {len(rows)}")
                total_rows += len(rows)

                for row in rows:
                    parsed = parse_match_row(row)
                    if not parsed:
                        continue
                    kickoff = parsed['kickoff']
                    # Filter by 90-minute window
                    if not (now_utc <= kickoff < window_end):
                        continue

                    # De-vig 1X2
                    true_home, true_draw, true_away = de_vig_three_way(
                        parsed['odds']['home'],
                        parsed['odds']['draw'],
                        parsed['odds']['away']
                    )

                    # Firestore document ID: slug from teams + kickoff
                    doc_id = f"{parsed['home']}-{parsed['away']}-{kickoff.strftime('%Y%m%d%H%M')}"
                    db.collection("matches").document(doc_id).set({
                        "home": parsed['home'],
                        "away": parsed['away'],
                        "kickoff": kickoff.isoformat(),
                        "pinnacle_1x2": parsed['odds'],
                        "true_probs_1x2": {
                            "home": true_home,
                            "draw": true_draw,
                            "away": true_away
                        },
                        "stored_at": now_utc.isoformat()
                    }, merge=True)
                    stored_count += 1
                    print(f"  Stored: {parsed['home']} vs {parsed['away']} ({kickoff.strftime('%H:%M')})")
            except Exception as e:
                print(f"Error scraping {league_name}: {e}")

        browser.close()

    send_telegram(f"✅ Pinnacle scrape done. Rows scanned: {total_rows}, Matches stored in window: {stored_count}")
    print("Pinnacle scraper finished.")

if __name__ == "__main__":
    main()
