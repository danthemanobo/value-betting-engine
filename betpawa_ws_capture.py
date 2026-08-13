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
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Listen to WebSocket connections
        def on_websocket(ws):
            ws_url = ws.url
            captured.append(f"\n=== WebSocket connected: {ws_url} ===")

            def on_frame_received(frame):
                # Capture only text frames, limit size
                try:
                    text = frame.text
                    if text and len(text) > 0:
                        snippet = text[:500]
                        captured.append(f"RECEIVED: {snippet}")
                except:
                    pass

            def on_frame_sent(frame):
                try:
                    text = frame.text
                    if text and len(text) > 0:
                        snippet = text[:500]
                        captured.append(f"SENT: {snippet}")
                except:
                    pass

            ws.on("framereceived", on_frame_received)
            ws.on("framesent", on_frame_sent)

        page.on("websocket", on_websocket)

        # Navigate to Betpawa events page
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)

        # Scroll a few times to encourage data loading
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 500)")
            page.wait_for_timeout(2000)

        browser.close()

    # Send captured data to Telegram
    if not captured:
        send_telegram_plain("No WebSocket frames captured.")
        return

    # Limit to first 15 entries to avoid huge messages
    message = "🔍 BetPawa WebSocket Capture:\n" + "\n".join(captured[:15])
    send_telegram_plain(message[:12000])

if __name__ == "__main__":
    main()
