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

def de_vig_two_way(o1, o2):
    imp1 = 1/o1; imp2 = 1/o2; ov = imp1+imp2
    return imp1/ov, imp2/ov

def de_vig_three_way(o1, o2, o3):
    imp1 = 1/o1; imp2 = 1/o2; imp3 = 1/o3; ov = imp1+imp2+imp3
    return imp1/ov, imp2/ov, imp3/ov

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    print(f"Scanning from {now_utc.isoformat()} to {window_end.isoformat()}")

    params = {
        "apiKey": API_KEY,
        "regions": "eu",   # Pinnacle
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports/soccer/odds", params=params, timeout=30)
        resp.raise_for_status()
        all_matches = resp.json()
    except Exception as e:
        send_telegram(f"❌ API error: {e}")
        print(f"API error: {e}")
        return

    print(f"Fetched {len(all_matches)} matches from API")

    stored_count = 0
    for match in all_matches:
        try:
            kickoff = datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
        except:
            continue
        if not (now_utc <= kickoff < window_end):
            continue

        pinnacle = None
        for bk in match.get("bookmakers", []):
            if bk["key"] == "pinnacle":
                pinnacle = bk
                break
        if not pinnacle:
            continue

        data = {
            "home": match["home_team"],
            "away": match["away_team"],
            "kickoff": match["commence_time"],
            "stored_at": now_utc.isoformat()
        }

        for market in pinnacle.get("markets", []):
            if market["key"] == "h2h":
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if len(outcomes) == 3:
                    try:
                        tp_home, tp_draw, tp_away = de_vig_three_way(outcomes["Home"], outcomes["Draw"], outcomes["Away"])
                        data["pinnacle_1x2"] = {"home": outcomes["Home"], "draw": outcomes["Draw"], "away": outcomes["Away"]}
                        data["true_probs_1x2"] = {"home": tp_home, "draw": tp_draw, "away": tp_away}
                    except:
                        pass
            elif market["key"] == "totals":
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if "Over" in outcomes and "Under" in outcomes:
                    try:
                        tp_over, tp_under = de_vig_two_way(outcomes["Over"], outcomes["Under"])
                        data["pinnacle_totals"] = {"over": outcomes["Over"], "under": outcomes["Under"]}
                        data["true_probs_totals"] = {"over": tp_over, "under": tp_under}
                    except:
                        pass

        if "true_probs_1x2" in data or "true_probs_totals" in data:
            doc_id = f"{match['home_team']}-{match['away_team']}-{kickoff.strftime('%Y%m%d%H%M')}"
            db.collection("matches").document(doc_id).set(data, merge=True)
            stored_count += 1

    send_telegram(f"✅ Pinnacle scan done. Matches in window: {stored_count}")
    print("Done")

if __name__ == "__main__":
    main()
