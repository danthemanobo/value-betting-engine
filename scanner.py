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

def de_vig_two_way(odds1, odds2):
    imp1 = 1/odds1
    imp2 = 1/odds2
    overround = imp1 + imp2
    return imp1/overround, imp2/overround

def de_vig_three_way(odds1, odds2, odds3):
    imp1 = 1/odds1
    imp2 = 1/odds2
    imp3 = 1/odds3
    overround = imp1 + imp2 + imp3
    return imp1/overround, imp2/overround, imp3/overround

def parse_market_key(key):
    parts = key.split(';')
    if len(parts) < 3:
        return key
    period = parts[1]
    period_name = "Full Time" if period == "0" else f"Period {period}"
    code = parts[2]
    if code == 'm':
        return f"{period_name} 1X2"
    elif code == 'ou':
        line = parts[3] if len(parts) > 3 else ""
        return f"{period_name} Over/Under {line}"
    elif code == 's':
        line = parts[3] if len(parts) > 3 else ""
        return f"{period_name} Asian Handicap {line}"
    elif code == 'tt':
        line = parts[3] if len(parts) > 3 else ""
        side = parts[4] if len(parts) > 4 else ""
        side_name = "Home" if side == 'home' else "Away" if side == 'away' else side
        return f"{period_name} Team Total {side_name} {line}"
    else:
        return key

def label_prices_for_market(market, home_name, away_name):
    prices = market.get("prices", [])
    market_type = market.get("type", "")
    key = market.get("key", "")

    has_designation = any('designation' in p for p in prices)

    if market_type == "moneyline":
        if has_designation:
            labels = []
            for p in prices:
                des = p.get("designation", "").lower()
                odds = american_to_decimal(p["price"])
                if des == "home":
                    labels.append((home_name, odds))
                elif des == "draw":
                    labels.append(("Draw", odds))
                elif des == "away":
                    labels.append((away_name, odds))
                else:
                    labels.append((f"sel_{len(labels)+1}", odds))
            ordered = []
            for desired in [home_name, "Draw", away_name]:
                for label, odds in labels:
                    if label == desired:
                        ordered.append((label, odds))
                        break
            if len(ordered) == 3:
                return ordered
            else:
                return labels
        else:
            if len(prices) == 3:
                return [(home_name, american_to_decimal(prices[0]["price"])),
                        ("Draw", american_to_decimal(prices[1]["price"])),
                        (away_name, american_to_decimal(prices[2]["price"]))]
            elif len(prices) == 2:
                return [(home_name, american_to_decimal(prices[0]["price"])),
                        (away_name, american_to_decimal(prices[1]["price"]))]
    elif market_type in ("total", "team_total"):
        if has_designation:
            labels = []
            for p in prices:
                des = p.get("designation", "").lower()
                odds = american_to_decimal(p["price"])
                if des == "over":
                    labels.append(("Over", odds))
                elif des == "under":
                    labels.append(("Under", odds))
                else:
                    labels.append((f"sel_{len(labels)+1}", odds))
            ordered = []
            for desired in ["Over", "Under"]:
                for label, odds in labels:
                    if label == desired:
                        ordered.append((label, odds))
                        break
            if len(ordered) == 2:
                return ordered
            return labels
        else:
            if len(prices) == 2:
                return [("Over", american_to_decimal(prices[0]["price"])),
                        ("Under", american_to_decimal(prices[1]["price"]))]
    elif market_type == "spread":
        if has_designation:
            labels = []
            for p in prices:
                des = p.get("designation", "").lower()
                points = p.get("points", "")
                odds = american_to_decimal(p["price"])
                if des == "home":
                    labels.append((f"{home_name} {points}", odds))
                elif des == "away":
                    labels.append((f"{away_name} {points}", odds))
                else:
                    labels.append((f"{points}", odds))
            return labels
        else:
            if len(prices) == 2:
                home_point = prices[0].get("points", "")
                away_point = prices[1].get("points", "")
                return [(f"{home_name} {home_point}", american_to_decimal(prices[0]["price"])),
                        (f"{away_name} {away_point}", american_to_decimal(prices[1]["price"]))]
    return []

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
    ids = []
    for league in leagues:
        if league.get("name") in TOP_LEAGUES:
            ids.append(league["id"])
    return ids

def process_match(match, headers, now_utc):
    matchup_id = match["id"]
    home_name = None
    away_name = None
    for p in match.get("participants", []):
        if p.get("alignment") == "home":
            home_name = p.get("name")
        elif p.get("alignment") == "away":
            away_name = p.get("name")
    if not home_name or not away_name:
        return 0

    markets_url = f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{matchup_id}/markets/straight"
    try:
        resp = requests.get(markets_url, headers=headers, timeout=20)
        resp.raise_for_status()
        match_markets = resp.json()
    except Exception as e:
        print(f"Error fetching markets for {home_name} vs {away_name}: {e}")
        return 0

    markets_data = []
    for market in match_markets:
        key = market.get("key", "")
        market_name = parse_market_key(key)
        labels = label_prices_for_market(market, home_name, away_name)
        if not labels:
            continue

        decimal_odds = [odds for _, odds in labels]
        true_probs = None
        if len(decimal_odds) == 3:
            tp_home, tp_draw, tp_away = de_vig_three_way(*decimal_odds)
            true_probs = [tp_home, tp_draw, tp_away]
        elif len(decimal_odds) == 2:
            tp1, tp2 = de_vig_two_way(*decimal_odds)
            true_probs = [tp1, tp2]
        else:
            continue

        selections = []
        for (sel_name, odds), tp in zip(labels, true_probs):
            selections.append({
                "name": sel_name,
                "decimal": odds,
                "true_prob": tp
            })

        markets_data.append({
            "key": key,
            "market_name": market_name,
            "type": market.get("type", ""),
            "period": market.get("period", 0),
            "selections": selections
        })

    if not markets_data:
        return 0

    doc_id = f"{home_name}-{away_name}-{match['startTime'].replace(':','-')}"
    db.collection("matches").document(doc_id).set({
        "home": home_name,
        "away": away_name,
        "kickoff": match["startTime"],
        "markets": markets_data,
        "stored_at": now_utc.isoformat()
    }, merge=True)

    return len(markets_data)

def main():
    now_utc = datetime.now(timezone.utc)
    window_end = now_utc + timedelta(minutes=90)
    headers = {
        "x-api-key": PINNACLE_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    league_ids = get_top_league_ids()
    if not league_ids:
        send_telegram("No top leagues found.")
        return

    stored_match_count = 0
    stored_market_count = 0

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
                if now_utc <= start_dt < window_end:
                    selected_matches.append(m)

        for match in selected_matches:
            count = process_match(match, headers, now_utc)
            if count > 0:
                stored_match_count += 1
                stored_market_count += count

    send_telegram(
        f"✅ Pinnacle scan done.\nMode: {'TEST' if TEST_MODE else 'LIVE'}\nMatches stored: {stored_match_count}\nTotal markets stored: {stored_market_count}"
    )
    print(f"Pinnacle scan complete. Matches: {stored_match_count}, Markets: {stored_market_count}")

if __name__ == "__main__":
    main()
