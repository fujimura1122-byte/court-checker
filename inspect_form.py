from playwright.sync_api import sync_playwright
from pathlib import Path

URL = "https://avo.hta.nl/uithoorn/Accommodation/Detail/106"
OUT_IMG = Path("snap_form.png")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 画面を出して確認もしやすい
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")

        # 画面を少し待つ
        page.wait_for_timeout(1500)

        # 画面キャプチャ（フォーム全体の確認用）
        try:
            page.screenshot(path=str(OUT_IMG), full_page=True)
            print(f"[+] Screenshot saved -> {OUT_IMG.resolve()}")
        except Exception as e:
            print("[-] Screenshot failed:", e)

        # 全selectのラベル名・選択肢を列挙
        selects = page.locator("select")
        count = selects.count()
        print(f"[+] Found {count} <select> elements")
        for i in range(count):
            sel = selects.nth(i)
            # labelを推定（for属性 or 近傍テキスト）
            label_text = None
            try:
                sel_id = sel.get_attribute("id")
                if sel_id:
                    label = page.locator(f"label[for='{sel_id}']")
                    if label.count() > 0:
                        label_text = label.nth(0).inner_text().strip()
            except:
                pass
            if not label_text:
                # 近傍テキストで代替
                try:
                    label_text = sel.locator("xpath=preceding::label[1]").inner_text().strip()
                except:
                    label_text = "(label not found)"

            # option列挙
            options = sel.locator("option")
            opts = []
            for j in range(options.count()):
                txt = options.nth(j).inner_text().strip()
                val = options.nth(j).get_attribute("value")
                opts.append((txt, val))

            print(f"\n== SELECT #{i+1} | Label: {label_text} ==")
            for (txt, val) in opts:
                print(f" - option: '{txt}' (value='{val}')")

        # ボタン類（検索・予約へ）
        buttons = page.locator("button, input[type=submit], a[role=button]")
        btn_texts = []
        for i in range(buttons.count()):
            t = buttons.nth(i).inner_text().strip()
            if t:
                btn_texts.append(t)
        print("\n[+] Buttons found:", btn_texts)

        browser.close()

if __name__ == "__main__":
    main()
