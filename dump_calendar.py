from playwright.sync_api import sync_playwright
from pathlib import Path

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
OUT = Path("calendar_dump.html")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # タイムアウトを短く設定（10秒）
            page.goto(BOOK_URL, timeout=10000)
        except Exception as e:
            print("Goto timeout or error:", e)

        page.wait_for_timeout(3000)  # 強制的に3秒待機

        html = page.content()
        OUT.write_text(html, encoding="utf-8")
        print(f"[+] Saved HTML to {OUT.resolve()} (size={len(html)} chars)")

        page.screenshot(path="calendar_dump.png", full_page=True)
        print("[+] Screenshot saved -> calendar_dump.png")

        browser.close()

if __name__ == "__main__":
    main()
