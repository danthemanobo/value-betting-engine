import os, json, requests
from datetime import datetime, timedelta, timezone
from firebase_admin import credentials, firestore, initialize_app

PINNACLE_API_KEY = os.environ['PINNACLE_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
TEST_MODE = os.environ.get('TEST_MODE', 'false').lower() == 'true'

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

TOP_LEAGUES = [
    "CONMEBOL - Copa Libertadores",
    "England - Premier League",
    "Spain - La Liga",
    "UEFA - EURO",
    "UEFA - Champions League",
    "CONMEBOL - Copa Sudamericana",
    "England - Community Shield",
    "England - EFL Cup",
    "France - Ligue 1",
    "Germany - Bundesliga",
    "Italy - Cup",
    "Italy - Serie A",
    "USA - Major League Soccer",
    "Korea Republic - K League 1",
    "UEFA - Champions League Qualifiers"
]

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def american_to_decimal(american):
    if american > 0:
        return round(1 + american/100, 3)
    else:
        return round(1 + 100/abs(american), 3)

def de_vig_three_way(o1, o2, o3):
    imp1 = 1/o1; imp2 = 1/o2; imp3 = 1/o3
    overround = imp1 + imp2 + imp3
    return imp1/overround, imp2/overround, imp3/overround

def get_top_league_ids():
    headers = {
        "x-api-key": PINNACLE_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    url = "https://guest.api.arcadia.pinnacle.com/0.1/sports/29/leagues"
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        leagues = resp.json()
    except Exception as e:
        send_telegram(f"Error fetching leagues: {e}")
        return []
    return [l["id"] for l in leagues if l.get("name") in TOP_LEAGUES]

def extract_1x2_selections(market, home_name, away_name):
    prices = market.get("prices", [])
    if len(prices) != 3:
        return None
    # Use designation if all three have it
    if all('designation' in p for p in prices):
        home_odd = draw_odd = away_odd = None
        for p in prices:
            des = p.get("designation", "").lower()
            odd = american_to_decimal(p.get("price"))
            if des == "home":
                home_odd = odd
            elif des == "draw":
                draw_odd = odd
            elif des == "away":
                away_odd = odd
        if home_odd and draw_odd and away_odd:
            return [(home_name, home_odd), ("Draw", draw_odd), (away_name, away_odd)]
    return None  # avoid order-based guesses

def process_match_1x2(match, headers):
    matchup_id = match["id"]
    home_name = away_name = None
    for p in match.get("participants", []):
        if p.get("alignment") == "home":
            home_name = p.get("name")
        elif p.get("alignment") == "away":
            away_name = p.get("name")
    if not home_name or not away_name:
        return None

    markets_url = f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/straight"
    try:
        resp = requests.get(markets_url, headers=headers, timeout=20)
        resp.raise_for_status()
        all_markets = resp.json()
    except Exception as e:
        print(f"Error fetching markets for {home_name} vs {away_name}: {e}")
        return None

    # Find full-time moneyline
    moneyline = None
    for m in all_markets:
        if m.get("key") == "s;0;m":
            moneyline = m
            break
    if not moneyline:
        return None

    selections = extract_1x2_selections(moneyline, home_name, away_name)
    if not selections:
        return None

    odds = [odd for _, odd in selections]
    try:
        tp_home, tp_draw, tp_away = de_vig_three_way(*odds)
    except:
        return None

    return {
        "home": home_name,
        "away": away_name,
        "kickoff": match.get("startTime"),
        "markets": [
            {
                "key": "s;0;m",
                "market_name": "Full Time 1X2",
                "type": "moneyline",
                "period": 0,
                "selections": [
                    {"name": home_name, "decimal": selections[0][1], "true_prob": tp_home},
                    {"name": "Draw", "decimal": selections[1][1], "true_prob": tp_draw},
                    {"name": away_name, "decimal": selections[2][1], "true_prob": tp_away}
                ]
            }
        ],
        "stored_at": datetime.now(timezone.utc).isoformat()
    }

def main():
    now_utc = datetime.now(timezone.utc)
    headers = {
        "x-api-key": PINNACLE_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    league_ids = get_top_league_ids()
    if not league_ids:
        send_telegram("No top leagues found.")
        return

    stored_matches = 0

    for league_id in league_ids:
        matchups_url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups"
        try:
            resp = requests.get(matchups_url, headers=headers, timeout=20)
            resp.raise_for_status()
            matchups = resp.json()
        except Exception as e:
            print(f"Error fetching matchups for league {league_id}: {e}")
            continue

        if TEST_MODE:
            selected_matches = [m for m in matchups if m.get("type") == "matchup"][:3]
        else:
            selected_matches = []
            for m in matchups:
                if m.get("type") != "matchup":
                    continue
                start_str = m.get("startTime")
                if not start_str:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except:
                    continue
                if now_utc <= start_dt < now_utc + timedelta(minutes=90):
                    selected_matches.append(m)

        for match in selected_matches:
            data = process_match_1x2(match, headers)
            if data is None:
                continue
            doc_id = f"{data['home']}-{data['away']}-{data['kickoff'].replace(':','-')}"
            db.collection("matches").document(doc_id).set(data, merge=True)
            stored_matches += 1

    send_telegram(
        f"✅ Pinnacle 1X2 scanner done.\nMode: {'TEST' if TEST_MODE else 'LIVE'}\nMatches stored: {stored_matches}\nMarkets stored: {stored_matches}"
    )
    print(f"Pinnacle 1X2 scanner complete. Matches: {stored_matches}")

if __name__ == "__main__":
    main()
