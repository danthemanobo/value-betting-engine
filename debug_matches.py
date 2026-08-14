import os, json, requests
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    # Specify the matches we want to inspect
    queries = [
        ("Angers", "Lille"),
        ("Arsenal", "Coventry City"),
        ("Arsenal", "Manchester City")
    ]

    lines = []
    for home_q, away_q in queries:
        docs = db.collection("matches").where("home", "==", home_q).where("away", "==", away_q).stream()
        found = False
        for doc in docs:
            data = doc.to_dict()
            if "markets" not in data:
                continue
            found = True
            lines.append(f"\n⚽ {data['home']} vs {data['away']}")
            for m in data["markets"]:
                lines.append(f"Key: {m.get('key')} | Type: {m.get('type')} | Name: {m.get('market_name')}")
                for s in m.get("selections", []):
                    lines.append(f"   {s['name']}: decimal={s['decimal']}, true_prob={s['true_prob']}")
            break
        if not found:
            lines.append(f"\n❌ No market data for {home_q} vs {away_q}")

    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
