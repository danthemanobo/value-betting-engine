import os, json, requests
from datetime import datetime, timedelta, timezone
from firebase_admin import credentials, firestore, initialize_app

API_KEY = os.environ['ODDS_API_KEY']
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

def get_real_utc_now():
    try:
        resp = requests.get("http://worldtimeapi.org/api/timezone/Etc/UTC", timeout=5)
        if resp.status_code == 200:
            dt_str = resp.json()["datetime"]
            return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Real-time API failed: {e}")
    return datetime.now(timezone.utc)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def de_vig_two_way(o1, o2):
    imp1 = 1.0 / o1
    imp2 = 1.0 / o2
    overround = imp1 + imp2
    return imp1 / overround, imp2 / overround

def de_vig_three_way(o1, o2, o3):
    imp1 = 1.0 / o1
    imp2 = 1.0 / o2
    imp3 = 1.0 / o3
    overround = imp1 + imp2 + imp3
    return imp1 / overround, imp2 / overround, imp3 / overround

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    print(f"Real UTC now: {now_utc.isoformat()}")
    print(f"Scanning matches up to {window_end.strftime('%H:%M')} UTC")

    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports/soccer/odds", params=params, timeout=30)
        resp.raise_for_status()
        all_matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ Pinnacle API error: {e}")
        print(f"API error: {e}")
        return

    print(f"Total matches from API: {len(all_matches)}")

    # Filter matches in our 90-min window
    filtered = []
    for match in all_matches:
        try:
            kickoff = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
        except:
            continue
        if now_utc <= kickoff < window_end:
            filtered.append(match)

    print(f"Matches in window: {len(filtered)}")

    if not filtered:
        send_telegram("ℹ️ No matches in the next 90 minutes.")
        return

    # For each match, extract Pinnacle odds and store true probabilities
    stored_count = 0
    for match in filtered:
        match_id = match["id"]
        home = match["home_team"]
        away = match["away_team"]
        kickoff = match["commence_time"]

        # Find Pinnacle odds
        pinnacle = None
        for bk in match.get("bookmakers", []):
            if bk["key"] == "pinnacle":
                pinnacle = bk
                break
        if not pinnacle:
            continue

        data = {
            "home": home,
            "away": away,
            "kickoff": kickoff,
            "stored_at": now_utc.isoformat()
        }

        # Process 1X2 market
        for market in pinnacle.get("markets", []):
            if market["key"] == "h2h":
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if len(outcomes) == 3:
                    try:
                        tp_home, tp_draw, tp_away = de_vig_three_way(
                            outcomes["Home"], outcomes["Draw"], outcomes["Away"]
                        )
                        data["pinnacle_1x2"] = {
                            "home": outcomes["Home"],
                            "draw": outcomes["Draw"],
                            "away": outcomes["Away"]
                        }
                        data["true_probs_1x2"] = {
                            "home": tp_home,
                            "draw": tp_draw,
                            "away": tp_away
                        }
                    except Exception as e:
                        print(f"Error de‑vigging 1X2 for {match_id}: {e}")

            elif market["key"] == "totals":
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                # Usually "Over" and "Under" for total 2.5
                if "Over" in outcomes and "Under" in outcomes:
                    try:
                        tp_over, tp_under = de_vig_two_way(outcomes["Over"], outcomes["Under"])
                        data["pinnacle_totals"] = {
                            "over": outcomes["Over"],
                            "under": outcomes["Under"]
                        }
                        data["true_probs_totals"] = {
                            "over": tp_over,
                            "under": tp_under
                        }
                    except Exception as e:
                        print(f"Error de‑vigging totals for {match_id}: {e}")

        if "true_probs_1x2" in data or "true_probs_totals" in data:
            db.collection("matches").document(match_id).set(data, merge=True)
            stored_count += 1

    send_telegram(f"⚽ Pinnacle scan done. {len(filtered)} matches in window, {stored_count} stored with true odds.")
    print("Done")

if __name__ == "__main__":
    main()
