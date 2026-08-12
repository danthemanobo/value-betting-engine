import os, json, requests, re
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
    debug = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        page.goto("https://www.betpawa.ng/events?categoryId=2&marketId=1X2", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Get all elements that could be scroll containers
        containers = page.evaluate("""() => {
            const all = document.querySelectorAll('div, section, main, ul');
            const results = [];
            all.forEach(el => {
                const style = getComputedStyle(el);
                const overflowY = style.overflowY;
                if (overflowY === 'auto' || overflowY === 'scroll') {
                    results.push({
                        tag: el.tagName,
                        class: el.className || '',
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        scrollTop: el.scrollTop,
                        childCount: el.children.length
                    });
                }
            });
            return results;
        }""")

        debug.append(f"Found {len(containers)} potential scroll containers")
        for idx, c in enumerate(containers[:10], 1):
            debug.append(f"{idx}. <{c['tag']}> class='{c['class']}' scrollH={c['scrollHeight']} clientH={c['clientHeight']} scrollTop={c['scrollTop']} children={c['childCount']}")

        # Find the best container: one with scrollHeight > clientHeight
        target = None
        for c in containers:
            if c['scrollHeight'] > c['clientHeight'] + 50:
                target = c
                break

        if target:
            class_name = target['class']
            debug.append(f"\nUsing target container: class='{class_name}', scrollH={target['scrollHeight']}, clientH={target['clientHeight']}")
            # Build a CSS selector for the class (if class is not empty)
            if class_name:
                selector = "." + ".".join(class_name.split())
            else:
                # fallback: use tag
                selector = target['tag']

            for step in range(1, 11):
                # Scroll the target container by 800px
                page.evaluate("""(sel) => {
                    const el = document.querySelector(sel);
                    if (el) el.scrollTop += 800;
                }""", selector)
                page.wait_for_timeout(2000)
                count = page.locator("div[class*='event']").count()
                debug.append(f"After scroll {step}: count={count}")
        else:
            debug.append("\nNo suitable scroll container found. Inspecting body overflow...")
            body_info = page.evaluate("""() => {
                const body = document.body;
                const style = getComputedStyle(body);
                return { overflowY: style.overflowY, scrollHeight: body.scrollHeight, clientHeight: body.clientHeight };
            }""")
            debug.append(f"Body: {body_info}")
            page.wait_for_timeout(5000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            count = page.locator("div[class*='event']").count()
            debug.append(f"After scroll to bottom, count={count}")

        browser.close()

    send_telegram_plain("🔍 Betpawa Container Debug:\n" + "\n".join(debug))

if __name__ == "__main__":
    main()
