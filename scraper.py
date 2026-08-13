import os, json, re, requests
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

def parse_betpawa_time(text):
    """Extract datetime from Betpawa result text like '5:15 pm Thu 13/08'."""
    # Try to find time and date pattern
    match = re.search(r'(\d{1,2}):(\d{2})\s*([ap]m)\s*\w{3}\s*(\d{2}/\d{2})', text, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3).lower()
    day_month = match.group(4)  # format '13/08'
    if ampm == 'pm' and hour != 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0
    now = get_real_utc_now()
    # Use current year (Betpawa shows current/future matches, but year not shown)
    day, month = map(int, day_month.split('/'))
    # Build datetime in UTC, assuming Betpawa time is West Africa Time (UTC+1)
    dt_wat = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Override day/month
    dt_wat = dt_wat.replace(day=day, month=month)
    # Convert to UTC
    dt_utc = dt_wat - timedelta(hours=1)
    return dt_utc.replace(tzinfo=timezone.utc)

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
    debug_lines = []

    fs_matches = db.collection("matches").where("kickoff", ">=", now_utc.isoformat()).where("kickoff", "<", window_end.isoformat()).stream()
    matches_list = []
    for doc in fs_matches:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        # Parse Pinnacle kickoff to UTC
        try:
            kickoff_utc = datetime.fromisoformat(data["kickoff"].replace("Z", "+00:00"))
            data["kickoff_utc"] = kickoff_utc
        except:
            data["kickoff_utc"] = None
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
            pinnacle_kickoff = match.get("kickoff_utc")
            debug_line = ""

            if not pinnacle_kickoff:
                debug_line = f"❌ Invalid Pinnacle kickoff for {home_raw} vs {away_raw}"
                debug_lines.append(debug_line)
                continue

            try:
                # Go to Betpawa events page
                page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(3000)

                # Click search icon
                search_icon = page.query_selector("button[aria-label*='search' i]")
                if search_icon:
                    search_icon.click()
                    page.wait_for_timeout(1500)

                search_input = page.query_selector('input[type="search"], input[type="text"], input:not([type])')
                if not search_input:
                    debug_line = f"❌ Search input missing for {home_raw} vs {away_raw}"
                    debug_lines.append(debug_line)
                    continue

                # Search using home team name (will bring up multiple results, we'll filter by time)
                search_input.click()
                search_input.fill("")
                page.wait_for_timeout(200)
                search_input.fill(home_raw)
                page.wait_for_timeout(500)
                search_input.press("Enter")
                page.wait_for_timeout(4000)

                result_elements = page.query_selector_all("div[class*='event']")
                clicked = False
                for elem in result_elements:
                    text = elem.inner_text()
                    if 'eFootball' in text or 'Simulated' in text or 'Esoccer' in text:
                        continue
                    bet_time = parse_betpawa_time(text)
                    if not bet_time:
                        continue
                    # Compare times (within 5 minutes)
                    if abs((bet_time - pinnacle_kickoff).total_seconds()) <= 300:
                        anchor = elem.query_selector("a")
                        if anchor:
                            href = anchor.get_attribute("href")
                            if href:
                                full_url = "https://www.betpawa.ng" + href if href.startswith('/') else href
                                page.goto(full_url, timeout=30000, wait_until="networkidle")
                                page.wait_for_timeout(5000)
                                odds = parse_odds_from_page(page)
                                true_probs = match.get("true_probs_1x2")

                                debug_line = f"✅ {home_raw} vs {away_raw}\nURL: {full_url}\nOdds: {odds['home']}/{odds['draw']}/{odds['away']}"
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
                                clicked = True
                                break
                if not clicked:
                    # Show sample times for diagnosis
                    sample_times = []
                    for e in result_elements[:3]:
                        t = parse_betpawa_time(e.inner_text())
                        sample_times.append(f"{e.inner_text()[:80]} -> {t}")
                    sample_text = "\n".join(sample_times) if sample_times else "No times parsed"
                    debug_line = f"❌ No match by time for {home_raw} vs {away_raw}\nPinnacle kickoff: {pinnacle_kickoff}\nSample results:\n{sample_text}"
            except Exception as e:
                debug_line = f"⚠️ Exception for {home_raw} vs {away_raw}: {e}"
            debug_lines.append(debug_line)

        browser.close()

    report = f"🔍 Betpawa time-based scraper:\n- Matches processed: {len(matches_list)}\n"
    if alerts:
        report += f"\n🚀 +EV Alerts ({len(alerts)}):\n" + "\n".join(alerts[:10])
    else:
        report += "\nℹ️ No +EV bets found."
    report += "\n\n📋 Detailed Debug:\n" + "\n\n".join(debug_lines)
    send_telegram(report)

if __name__ == "__main__":
    main()
