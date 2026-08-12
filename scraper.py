import os, json, re, requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BETPAWA_USER = os.environ.get('BETPAWA_USERNAME', '')
BETPAWA_PASS = os.environ.get('BETPAWA_PASSWORD', '')
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

def parse_match_text(text):
    """
    Given the inner text of a match element, extract:
    - kickoff datetime (UTC)
    - home team, away team
    - odds: {home, draw, away}
    Returns None if parsing fails.
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if len(lines) < 6:
        return None

    # First line usually contains time and date: "8:30 am Wed 12/08"
    time_pattern = r"(\d{1,2}:\d{2}\s*[ap]m)\s*\w{3}\s*(\d{2}/\d{2})"
    time_match = re.search(time_pattern, lines[0], re.IGNORECASE)
    if not time_match:
        return None

    time_str = time_match.group(1)  # e.g., "8:30 am"
    date_str = time_match.group(2)  # e.g., "12/08"
    # Convert to datetime
    try:
        # Assume year is current year (we'll get from real UTC now)
        now = get_real_utc_now()
        dt = datetime.strptime(f"{now.year} {date_str} {time_str}", "%Y %m/%d %I:%M %p")
        # Make it timezone-aware (Betpawa times are likely local Nigeria time, which is UTC+1)
        # We'll assume UTC+1 for now. To be safe, we could treat as UTC if no timezone given.
        from datetime import timedelta
        kickoff_utc = dt - timedelta(hours=1)  # convert from WAT (UTC+1) to UTC
        kickoff_utc = kickoff_utc.replace(tzinfo=timezone.utc)
    except:
        return None

    # Teams are the next two lines after the time line
    # But there may be league info between teams and odds. We'll look for the odds block.
    # The odds typically appear as "1\n2.05\nX\n3.30\n2\n3.59"
    odds_idx = None
    for i, line in enumerate(lines):
        if line == '1' and i+1 < len(lines) and re.match(r'\d+\.\d+', lines[i+1]):
            odds_idx = i
            break

    if odds_idx is None or odds_idx < 2:
        return None

    home_team = lines[1] if odds_idx > 1 else None
    away_team = lines[2] if odds_idx > 2 else None
    if not home_team or not away_team:
        return None

    # Extract odds
    try:
        home_odds = float(lines[odds_idx+1])
        draw_odds = float(lines[odds_idx+3])
        away_odds = float(lines[odds_idx+5])
    except (IndexError, ValueError):
        return None

    return {
        "kickoff_utc": kickoff_utc,
        "home": home_team,
        "away": away_team,
        "odds": {"home": home_odds, "draw": draw_odds, "away": away_odds}
    }

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    alerts = []
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Optional login
        try:
            page.goto("https://www.betpawa.ng/", timeout=30000, wait_until="networkidle")
            login_btn = page.query_selector("text=Login") or page.query_selector("a:has-text('Login')")
            if login_btn:
                login_btn.click()
                page.wait_for_timeout(2000)
                if BETPAWA_USER:
                    page.fill('input[type="tel"], input[placeholder="Phone number"]', BETPAWA_USER)
                    page.fill('input[type="password"]', BETPAWA_PASS)
                    page.click("button:has-text('Login')")
                    page.wait_for_timeout(5000)
        except Exception as e:
            debug_info.append(f"Login optional: {e}")

        # Navigate directly to 1X2 events
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Scroll to load more matches
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        # Extract match elements
        match_elements = page.query_selector_all("div[class*='event']")
        debug_info.append(f"Found {len(match_elements)} matches")

        # Fetch all Firestore matches that are within our window
        fs_matches = db.collection("matches").where("kickoff", ">=", now_utc.isoformat()).where("kickoff", "<", window_end.isoformat()).stream()
        firestore_data = {}
        for doc in fs_matches:
            data = doc.to_dict()
            firestore_data[doc.id] = data

        for elem in match_elements:
            text = elem.inner_text()
            parsed = parse_match_text(text)
            if not parsed:
                continue

            kickoff = parsed["kickoff_utc"]
            if not (now_utc <= kickoff < window_end):
                continue

            # Find matching Firestore entry using fuzzy team name + time
            best_match = None
            best_score = 0
            for match_id, fs in firestore_data.items():
                try:
                    fs_kickoff = datetime.fromisoformat(fs["kickoff"].replace("Z", "+00:00"))
                except:
                    continue
                if abs((fs_kickoff - kickoff).total_seconds()) > 300:  # within 5 minutes
                    continue
                score_home = fuzz.ratio(parsed["home"], fs.get("home", ""))
                score_away = fuzz.ratio(parsed["away"], fs.get("away", ""))
                score = (score_home + score_away) / 2
                if score > best_score and score > 70:
                    best_score = score
                    best_match = fs

            if not best_match:
                continue

            # Get Pinnacle true probabilities
            true_probs = best_match.get("true_probs_1x2")
            if not true_probs:
                continue

            # Calculate EV for each selection
            odds = parsed["odds"]
            ev_home = (true_probs["home"] * odds["home"]) - 1
            ev_draw = (true_probs["draw"] * odds["draw"]) - 1
            ev_away = (true_probs["away"] * odds["away"]) - 1

            match_name = f"{parsed['home']} vs {parsed['away']}"
            if ev_home > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Home @ {odds['home']} (EV +{ev_home*100:.1f}%)\nBetpawa")
            if ev_draw > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Draw @ {odds['draw']} (EV +{ev_draw*100:.1f}%)\nBetpawa")
            if ev_away > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Away @ {odds['away']} (EV +{ev_away*100:.1f}%)\nBetpawa")

        browser.close()

    if alerts:
        send_telegram(f"🚀 +EV Betpawa Alerts:\n" + "\n\n".join(alerts[:10]))
    else:
        send_telegram(f"ℹ️ No +EV bets. Matches scraped: {len(match_elements)}. Debug: {'; '.join(debug_info)}")

if __name__ == "__main__":
    main()
