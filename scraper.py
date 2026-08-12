import os, json, re, requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

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
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if len(lines) < 6:
        return None

    time_pattern = r"(\d{1,2}:\d{2}\s*[ap]m)\s*\w{3}\s*(\d{2}/\d{2})"
    time_match = re.search(time_pattern, lines[0], re.IGNORECASE)
    if not time_match:
        return None

    time_str = time_match.group(1)
    date_str = time_match.group(2)
    try:
        now = get_real_utc_now()
        dt = datetime.strptime(f"{now.year} {date_str} {time_str}", "%Y %m/%d %I:%M %p")
        # Assume Betpawa shows West Africa Time (UTC+1), convert to UTC
        kickoff_utc = dt - timedelta(hours=1)
        kickoff_utc = kickoff_utc.replace(tzinfo=timezone.utc)
    except:
        return None

    # Find odds block
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Go directly to the events page (no login needed)
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Scroll to load more
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        match_elements = page.query_selector_all("div[class*='event']")
        print(f"Scraped {len(match_elements)} matches from Betpawa")

        # Load Firestore matches in window
        fs_matches = db.collection("matches").where("kickoff", ">=", now_utc.isoformat()).where("kickoff", "<", window_end.isoformat()).stream()
        firestore_data = {doc.id: doc.to_dict() for doc in fs_matches}
        print(f"Firestore matches in window: {len(firestore_data)}")

        for elem in match_elements:
            parsed = parse_match_text(elem.inner_text())
            if not parsed:
                continue
            kickoff = parsed["kickoff_utc"]
            if not (now_utc <= kickoff < window_end):
                continue

            # Find matching Firestore document
            best_match = None
            best_score = 0
            for match_id, fs in firestore_data.items():
                try:
                    fs_kickoff = datetime.fromisoformat(fs["kickoff"].replace("Z", "+00:00"))
                except:
                    continue
                if abs((fs_kickoff - kickoff).total_seconds()) > 300:
                    continue
                score = (fuzz.ratio(parsed["home"], fs.get("home", "")) + fuzz.ratio(parsed["away"], fs.get("away", ""))) / 2
                if score > best_score and score > 70:
                    best_score = score
                    best_match = fs

            if not best_match or "true_probs_1x2" not in best_match:
                continue

            true_probs = best_match["true_probs_1x2"]
            odds = parsed["odds"]
            ev_home = (true_probs["home"] * odds["home"]) - 1
            ev_draw = (true_probs["draw"] * odds["draw"]) - 1
            ev_away = (true_probs["away"] * odds["away"]) - 1

            match_name = f"{parsed['home']} vs {parsed['away']}"
            if ev_home > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Home @ {odds['home']} (EV +{ev_home*100:.1f}%)")
            if ev_draw > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Draw @ {odds['draw']} (EV +{ev_draw*100:.1f}%)")
            if ev_away > MIN_EV:
                alerts.append(f"⚽ {match_name}\n1X2 Away @ {odds['away']} (EV +{ev_away*100:.1f}%)")

        browser.close()

    if alerts:
        send_telegram(f"🚀 +EV Alerts (Betpawa):\n" + "\n\n".join(alerts[:10]))
    else:
        send_telegram(f"ℹ️ No +EV bets. Betpawa matches: {len(match_elements)}, Firestore matches in window: {len(firestore_data)}")

if __name__ == "__main__":
    main()
