import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from firebase_admin import credentials, firestore, initialize_app

# ───────────────────────── INIT ─────────────────────────
API_KEY = os.environ['ODDS_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

# Configuration
MIN_EV_THRESHOLD = 0.05
STAKE = 100.0
BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT_KEY = "upcoming"  # We'll fetch all football matches
REGIONS = "eu"          # Pinnacle
MARKETS = "h2h,totals,btts,double_chance"
ODDS_FORMAT = "decimal"

# ──────────────── DE‑VIG FUNCTIONS ─────────────────
def de_vig_two_way(odds1, odds2):
    imp1 = 1.0 / odds1
    imp2 = 1.0 / odds2
    overround = imp1 + imp2
    return imp1 / overround, imp2 / overround

def de_vig_three_way(o1, o2, o3):
    imp1 = 1.0 / o1
    imp2 = 1.0 / o2
    imp3 = 1.0 / o3
    overround = imp1 + imp2 + imp3
    return imp1 / overround, imp2 / overround, imp3 / overround

# ──────────────── TELEGRAM SENDER ─────────────────
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram send error: {e}")

# ──────────────── MAIN SCANNER ─────────────────
def scan():
    now_utc = datetime.now(timezone.utc)

    # Only run if current time is a multiple of 90 minutes from midnight UTC
    minutes_since_midnight = now_utc.hour * 60 + now_utc.minute
    if minutes_since_midnight % 90 != 0:
        print(f"Skipping scan at {now_utc.isoformat()} (not a 90‑min interval).")
        return

    print(f"Starting scan at {now_utc.isoformat()}")

    # 1. Fetch Pinnacle odds for matches starting in the next 90 minutes
    commence_from = now_utc.isoformat()
    commence_to = (now_utc + timedelta(minutes=90)).isoformat()

    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "commenceTimeFrom": commence_from,
        "commenceTimeTo": commence_to
    }

    try:
        resp = requests.get(f"{BASE_URL}/upcoming/odds", params=params, timeout=30)
        resp.raise_for_status()
        pinnacle_data = resp.json()
    except Exception as e:
        print(f"API error: {e}")
        return

    # 2. Process each match
    alerts = []
    for match in pinnacle_data:
        match_id = match['id']
        home = match['home_team']
        away = match['away_team']
        kickoff = match['commence_time']

        # Find Pinnacle odds
        pinnacle_book = None
        for bk in match.get('bookmakers', []):
            if bk['key'] == 'pinnacle':
                pinnacle_book = bk
                break
        if not pinnacle_book:
            continue

        # For each market, de‑vig and compare with soft books (we'll simulate soft books later via scraping)
        # For MVP, we only have Pinnacle; we'll still log the true odds for later scraping comparison.
        # However, you'll add scraping logic for Nigerian books here in future iterations.
        for market in pinnacle_book.get('markets', []):
            market_key = market['key']
            outcomes = {o['name']: o['price'] for o in market['outcomes']}

            if market_key == 'h2h' and len(outcomes) == 3:
                try:
                    true_h, true_d, true_a = de_vig_three_way(outcomes['Home'], outcomes['Draw'], outcomes['Away'])
                except:
                    continue
                # Placeholder: here you'd later compare with Bet9ja/SportyBet odds
                # For now, just store the true probabilities for analysis
                doc_ref = db.collection('matches').document(match_id)
                doc_ref.set({
                    'home': home,
                    'away': away,
                    'kickoff': kickoff,
                    'true_home': true_h,
                    'true_draw': true_d,
                    'true_away': true_a
                }, merge=True)

            elif market_key == 'totals' and len(outcomes) == 2:
                try:
                    true_over, true_under = de_vig_two_way(outcomes['Over'], outcomes['Under'])
                except:
                    continue
                db.collection('matches').document(match_id).set({
                    'true_over': true_over,
                    'true_under': true_under
                }, merge=True)

            elif market_key == 'btts' and len(outcomes) == 2:
                try:
                    true_yes, true_no = de_vig_two_way(outcomes['Yes'], outcomes['No'])
                except:
                    continue
                db.collection('matches').document(match_id).set({
                    'true_btts_yes': true_yes,
                    'true_btts_no': true_no
                }, merge=True)

    # 3. Auto‑confirm pending bets (simplified: we'll mark all unconfirmed bets older than 90 min as auto‑confirmed)
    cutoff = now_utc - timedelta(minutes=90)
    pending_bets = db.collection('bets').where('status', '==', 'pending').where('created_at', '<', cutoff).stream()
    for bet in pending_bets:
        db.collection('bets').document(bet.id).update({'status': 'auto_confirmed'})
        # Later, we'll fetch results and update profit; for now just mark as settled.

    # 4. Send summary Telegram alert (if any new matches logged)
    if alerts:
        message = "\n".join(alerts[:10])  # limit to 10 to avoid long messages
        send_telegram(f"⚽ +EV Alerts:\n{message}")
    else:
        send_telegram("ℹ️ No +EV bets found in this window.")

if __name__ == "__main__":
    scan()
