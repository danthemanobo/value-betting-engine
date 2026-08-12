import os, json, re, requests
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
from firebase_admin import credentials, firestore, initialize_app

# ── Init Firebase & Config ──
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BETPAWA_USER = os.environ['BETPAWA_USERNAME']
BETPAWA_PASS = os.environ['BETPAWA_PASSWORD']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

MIN_EV = 0.05   # 5% edge

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Log into Betpawa
        page.goto("https://www.betpawa.ng/", timeout=30000)
        try:
            page.click("text=Login")  # adjust selector if needed
            page.fill('input[type="tel"], input[placeholder="Phone number"]', BETPAWA_USER)
            page.fill('input[type="password"]', BETPAWA_PASS)
            page.click("button:has-text('Login')")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Login might have failed: {e}")

        # 2. Go to football matches
        page.goto("https://www.betpawa.ng/sport/soccer", timeout=30000)
        page.wait_for_timeout(3000)

        # 3. Extract match rows (this selector depends on site structure; inspect Betpawa's HTML)
        # For illustration, assume each match is in a div with class 'event'
        matches = page.query_selector_all("div.event")
        for match_elem in matches:
            try:
                teams_text = match_elem.query_selector(".event__title").inner_text()
                kickoff_text = match_elem.query_selector(".event__time").inner_text()
                odds_1x2 = {
                    "home": float(match_elem.query_selector(".odd.home").inner_text()),
                    "draw": float(match_elem.query_selector(".odd.draw").inner_text()),
                    "away": float(match_elem.query_selector(".odd.away").inner_text())
                }
                odds_ou = {
                    "over": float(match_elem.query_selector(".odd.over").inner_text()),
                    "under": float(match_elem.query_selector(".odd.under").inner_text())
                }
            except:
                continue

            # Parse team names and kickoff time (simplified)
            home, away = teams_text.split(" vs ")
            # Convert kickoff text to datetime (assume format "12/08 15:30")
            try:
                kickoff_dt = datetime.strptime(kickoff_text, "%d/%m %H:%M").replace(year=now_utc.year, tzinfo=timezone.utc)
            except:
                continue

            if not (now_utc <= kickoff_dt < window_end):
                continue

            # 4. Find matching Firestore document by fuzzy team name + time
            matches_ref = db.collection("matches")
            # Query by home team (we'll fuzzy‑match from results)
            candidates = matches_ref.where("kickoff", "==", kickoff_dt.isoformat()).stream()
            for doc in candidates:
                data = doc.to_dict()
                home_sim = fuzz.ratio(data.get("home", ""), home)
                away_sim = fuzz.ratio(data.get("away", ""), away)
                if home_sim > 70 and away_sim > 70:
                    # Found match
                    true_probs = data.get("true_probs_1x2")
                    if true_probs:
                        ev_home = (true_probs["home"] * odds_1x2["home"]) - 1
                        if ev_home > MIN_EV:
                            alerts.append(f"⚽ {home} vs {away}\n1X2 Home @ {odds_1x2['home']} (EV {ev_home*100:.1f}%)\nBetpawa")

                        ev_draw = (true_probs["draw"] * odds_1x2["draw"]) - 1
                        if ev_draw > MIN_EV:
                            alerts.append(f"⚽ {home} vs {away}\n1X2 Draw @ {odds_1x2['draw']} (EV {ev_draw*100:.1f}%)\nBetpawa")

                        ev_away = (true_probs["away"] * odds_1x2["away"]) - 1
                        if ev_away > MIN_EV:
                            alerts.append(f"⚽ {home} vs {away}\n1X2 Away @ {odds_1x2['away']} (EV {ev_away*100:.1f}%)\nBetpawa")

                    true_totals = data.get("true_probs_totals")
                    if true_totals:
                        ev_over = (true_totals["over"] * odds_ou["over"]) - 1
                        if ev_over > MIN_EV:
                            alerts.append(f"⚽ {home} vs {away}\nO2.5 Over @ {odds_ou['over']} (EV {ev_over*100:.1f}%)\nBetpawa")

                        ev_under = (true_totals["under"] * odds_ou["under"]) - 1
                        if ev_under > MIN_EV:
                            alerts.append(f"⚽ {home} vs {away}\nO2.5 Under @ {odds_ou['under']} (EV {ev_under*100:.1f}%)\nBetpawa")
                    break  # stop searching once match found

        browser.close()

    if alerts:
        msg = "\n\n".join(alerts[:10])  # limit to 10 to avoid Telegram message size limits
        send_telegram(f"🚀 +EV Betpawa Alerts:\n{msg}")
    else:
        send_telegram("ℹ️ No +EV bets found on Betpawa in this window.")

if __name__ == "__main__":
    main()
