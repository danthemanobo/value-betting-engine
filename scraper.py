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

def normalize(name):
    return re.sub(r'\s+', ' ', name.replace('-', ' ').strip())

def parse_odds_from_page(page):
    odds = {"home": None, "draw": None, "away": None}
    try:
        price_elements = page.query_selector_all("span[class*='price'], span[class*='odd'], button[class*='price']")
        if not price_elements:
            numbers = page.evaluate("""() => {
                const res = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (/^\\d+\\.\\d{2}$/.test(t)) res.push(t);
                }
                return res;
            }""")
            numbers = [float(x) for x in numbers if float(x) > 1.0]
            if len(numbers) >= 3:
                odds = {"home": numbers[0], "draw": numbers[1], "away": numbers[2]}
        else:
            prices = []
            for el in price_elements:
                txt = el.inner_text().strip()
                try:
                    val = float(txt)
                    if val > 1.0:
                        prices.append(val)
                except:
                    continue
            if len(prices) >= 3:
                odds = {"home": prices[0], "draw": prices[1], "away": prices[2]}
    except Exception as e:
        print(f"Odds extraction error: {e}")
    return odds

def main():
    now_utc = get_real_utc_now()
    window_end = now_utc + timedelta(minutes=90)
    alerts = []
    matched_count = 0
    failed_count = 0

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

        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        for match in matches_list:
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            home_norm = normalize(home_raw)
            away_norm = normalize(away_raw)

            # Every iteration: click search icon, then get fresh input
            search_icon = page.query_selector("button[aria-label*='search' i]")
            if search_icon:
                search_icon.click()
                page.wait_for_timeout(1500)

            search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
            if not search_input:
                send_telegram("❌ Search input not found. Aborting.")
                browser.close()
                return

            # Clear, type, and submit search
            search_input.click()
            search_input.fill("")
            page.wait_for_timeout(300)
            search_input.fill(home_norm)
            page.wait_for_timeout(500)
            search_input.press("Enter")
            page.wait_for_timeout(4000)

            result_elements = page.query_selector_all("div[class*='event']")
            found_match = False
            for elem in result_elements:
                text = elem.inner_text()
                if 'eFootball' in text or 'Simulated' in text or 'Esoccer' in text:
                    continue

                if fuzz.partial_ratio(home_norm, text) > 70 and fuzz.partial_ratio(away_norm, text) > 70:
                    found_match = True
                    anchor = elem.query_selector("a")
                    if anchor:
                        href = anchor.get_attribute("href")
                        if href:
                            full_url = "https://www.betpawa.ng" + href if href.startswith('/') else href
                            page.goto(full_url, timeout=30000, wait_until="networkidle")
                            page.wait_for_timeout(5000)
                            odds = parse_odds_from_page(page)
                            if odds["home"] and odds["draw"] and odds["away"]:
                                true_probs = match.get("true_probs_1x2")
                                if true_probs:
                                    ev_home = (true_probs["home"] * odds["home"]) - 1
                                    ev_draw = (true_probs["draw"] * odds["draw"]) - 1
                                    ev_away = (true_probs["away"] * odds["away"]) - 1
                                    match_name = f"{home_raw} vs {away_raw}"
                                    if ev_home > MIN_EV:
                                        alerts.append(f"⚽ {match_name}\n1X2 Home @ {odds['home']} (EV +{ev_home*100:.1f}%)\nBetpawa")
                                    if ev_draw > MIN_EV:
                                        alerts.append(f"⚽ {match_name}\n1X2 Draw @ {odds['draw']} (EV +{ev_draw*100:.1f}%)\nBetpawa")
                                    if ev_away > MIN_EV:
                                        alerts.append(f"⚽ {match_name}\n1X2 Away @ {odds['away']} (EV +{ev_away*100:.1f}%)\nBetpawa")
                                    matched_count += 1
                            else:
                                failed_count += 1
                                body_snippet = page.inner_text("body")[:500]
                                print(f"Odds extraction failed for {home_raw} vs {away_raw}. Snippet: {body_snippet}")

                            # Return to events page
                            page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                            page.wait_for_timeout(2000)
                            break
            if not found_match:
                failed_count += 1
                print(f"Match not found on Betpawa: {home_raw} vs {away_raw}")

        browser.close()

    report = f"🔍 Betpawa search-based scraper:\n- Matches processed: {len(matches_list)}\n- Successfully compared: {matched_count}\n- Failures: {failed_count}"
    if alerts:
        report += f"\n\n🚀 +EV Alerts ({len(alerts)}):\n" + "\n".join(alerts[:10])
    else:
        report += "\nℹ️ No +EV bets found."
    send_telegram(report)

if __name__ == "__main__":
    main()
