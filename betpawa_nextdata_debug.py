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
    debug_info = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Loading events page...")
        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Extract __NEXT_DATA__ script content
        next_data = page.evaluate("""() => {
            const script = document.querySelector('#__NEXT_DATA__');
            return script ? script.textContent : null;
        }""")

        if next_data:
            debug_info.append(f"__NEXT_DATA__ found. Length: {len(next_data)} characters.")
            # Show a small snippet of the start
            debug_info.append(f"First 800 chars:\n{next_data[:800]}")
            # Try to parse and list top-level keys
            try:
                data = json.loads(next_data)
                props = data.get("props", {})
                page_props = props.get("pageProps", {})
                debug_info.append(f"Top-level keys in pageProps: {list(page_props.keys())}")
                # Look for key containing events/sports/matches
                for key, value in page_props.items():
                    if isinstance(value, (list, dict)) and len(value) > 0:
                        debug_info.append(f"pageProps['{key}'] type={type(value).__name__}, length={len(value)}")
                        if isinstance(value, list):
                            first_item = value[0]
                            debug_info.append(f"First item keys: {list(first_item.keys()) if isinstance(first_item, dict) else 'not dict'}")
                            debug_info.append(f"First item sample: {json.dumps(first_item)[:300]}")
                        break
            except Exception as e:
                debug_info.append(f"JSON parse error: {e}")
        else:
            debug_info.append("No __NEXT_DATA__ script found.")

        browser.close()

    send_telegram_plain("🔍 Betpawa __NEXT_DATA__ Debug:\n" + "\n\n".join(debug_info))

if __name__ == "__main__":
    main()
