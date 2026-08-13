import os, json
from firebase_admin import credentials, firestore, initialize_app

FIREBASE_SERVICE_ACCOUNT = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
initialize_app(cred)
db = firestore.client()

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)

def main():
    docs = db.collection("matches").where("home", "==", "Angers").where("away", "==", "Lille").stream()
    found = False
    for doc in docs:
        data = doc.to_dict()
        if "markets" in data:
            found = True
            markets = data["markets"]
            lines = [f"Match: {data['home']} vs {data['away']}"]
            for m in markets:
                lines.append(f"Key: {m.get('key')}, Type: {m.get('type')}, Name: {m.get('market_name')}")
                for s in m.get("selections", []):
                    lines.append(f"   {s['name']}: decimal={s['decimal']}, true_prob={s['true_prob']}")
            send_telegram("\n".join(lines))
            break
    if not found:
        send_telegram("Angers vs Lille doc with markets not found.")

if __name__ == "__main__":
    main()
