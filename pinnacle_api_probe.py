import os, json, requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

def send_telegram_plain(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=15)
        except Exception as e:
            print(f"Telegram error: {e}")

def main():
    captured_headers = {}
    captured_urls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Listen to all requests to guest.api.arcadia.pinnacle.com
        def on_request(req):
            if "guest.api.arcadia.pinnacle.com" in req.url:
                captured_urls.append(req.url)
                # Capture headers for this request
                headers = req.headers
                if "x-api-key" in headers:
                    captured_headers["x-api-key"] = headers["x-api-key"]
                # Also capture any other interesting headers
                if not captured_headers and "authorization" in headers:
                    captured_headers["authorization"] = headers["authorization"]

        page.on("request", on_request)

        # Navigate to Pinnacle soccer leagues page
        page.goto("https://www.pinnacle.com/en/soccer/leagues/", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Optionally click a league to trigger matchups API
        # Try to click first league link
        league_link = page.query_selector("a[href*='/matchups/']")
        if league_link:
            league_link.click()
            page.wait_for_timeout(5000)

        browser.close()

    # Build message
    lines = []
    lines.append("🔍 Pinnacle API Probe Results:")
    lines.append(f"Captured URLs ({len(captured_urls)}):")
    for u in captured_urls[:5]:
        lines.append(f"  {u}")
    lines.append("Captured Headers:")
    if captured_headers:
        for k, v in captured_headers.items():
            lines.append(f"  {k}: {v}")
    else:
        lines.append("  No x-api-key or authorization header found.")

    full_msg = "\n".join(lines)
    send_telegram_plain(full_msg[:4000])

if __name__ == "__main__":
    main()
