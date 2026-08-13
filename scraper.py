import os, json, re, requests, unicodedata
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
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
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=15)
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

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def normalize(name):
    return re.sub(r'\s+', ' ', strip_accents(name).replace('-', ' ')).strip().lower()

def parse_1x2_odds(page):
    """Extract 1X2 Full Time odds by locating the heading and grabbing next three numbers."""
    odds = {"home": None, "draw": None, "away": None}
    try:
        body_text = page.inner_text("body")
        lines = body_text.split('\n')
        for i, line in enumerate(lines):
            if "1X2 | Full Time" in line:
                nums = []
                j = i + 1
                while j < len(lines) and len(nums) < 3:
                    s = lines[j].strip()
                    if re.match(r'^\d+\.\d+$', s):
                        nums.append(float(s))
                    j += 1
                if len(nums) == 3:
                    odds = {"home": nums[0], "draw": nums[1], "away": nums[2]}
                    break
    except Exception as e:
        print(f"Odds extraction error: {e}")
    return odds

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    alerts = []
    debug_lines = []

    fs_matches = db.collection("matches").where("kickoff", ">=", now_utc.isoformat()).where("kickoff", "<", window_end.isoformat()).stream()
    matches_list = []
    for doc in fs_matches:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        matches_list.append(data)

    if not matches_list:
        send_telegram("ℹ️ No Pinnacle matches in window for Betpawa comparison.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for match in matches_list:
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            home_norm = normalize(home_raw)
            away_norm = normalize(away_raw)
            debug_line = ""

            try:
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                search_icon = page.query_selector("button[aria-label*='search' i]")
                if search_icon:
                    search_icon.click()
                    page.wait_for_timeout(1500)

                search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                if not search_input:
                    debug_line = f"❌ Search input missing for {home_raw} vs {away_raw}"
                    debug_lines.append(debug_line)
                    continue

                search_input.click()
                search_input.fill("")
                page.wait_for_timeout(200)
                search_input.fill(home_raw)
                page.wait_for_timeout(500)
                search_input.press("Enter")
                page.wait_for_timeout(5000)

                result_elements = page.query_selector_all("div[class*='event']")
                if not result_elements:
                    debug_line = f"❌ No results for {home_raw} vs {away_raw}"
                    debug_lines.append(debug_line)
                    continue

                first_elem = result_elements[0]
                first_elem.click()
                page.wait_for_timeout(5000)

                current_url = page.url
                odds = parse_1x2_odds(page)
                true_probs = match.get("true_probs_1x2")

                debug_line = f"🔗 URL: {current_url}\nOdds: {odds['home']}/{odds['draw']}/{odds['away']}"
                if true_probs:
                    ev_home = (true_probs["home"] * odds["home"]) - 1
                    ev_draw = (true_probs["draw"] * odds["draw"]) - 1
                    ev_away = (true_probs["away"] * odds["away"]) - 1
                    debug_line += f"\nTP: {true_probs['home']:.2f}/{true_probs['draw']:.2f}/{true_probs['away']:.2f}\nEV%: {ev_home*100:.1f}/{ev_draw*100:.1f}/{ev_away*100:.1f}"
                    if ev_home > MIN_EV:
                        alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Home @ {odds['home']} (EV +{ev_home*100:.1f}%)\nBetpawa")
                    if ev_draw > MIN_EV:
                        alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Draw @ {odds['draw']} (EV +{ev_draw*100:.1f}%)\nBetpawa")
                    if ev_away > MIN_EV:
                        alerts.append(f"⚽ {home_raw} vs {away_raw}\n1X2 Away @ {odds['away']} (EV +{ev_away*100:.1f}%)\nBetpawa")
                else:
                    debug_line += "\n⚠️ Missing true_probs_1x2"
            except Exception as e:
                debug_line = f"⚠️ Exception for {home_raw} vs {away_raw}: {e}"
            debug_lines.append(debug_line)

        browser.close()

    report = f"🔍 Betpawa final:\n- Matches processed: {len(matches_list)}\n"
    if alerts:
        report += f"\n🚀 +EV Alerts ({len(alerts)}):\n" + "\n".join(alerts[:10])
    else:
        report += "\nℹ️ No +EV bets found."
    report += "\n\n📋 Detailed Debug:\n" + "\n\n".join(debug_lines)
    send_telegram(report)

if __name__ == "__main__":
    main()
