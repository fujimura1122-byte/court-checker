from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
OUT = Path("snap_book.png")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 画面見えるモード
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # 画面キャプチャ
        try:
            page.screenshot(path=str(OUT), full_page=True)
            print(f"[+] Screenshot -> {OUT.resolve()}")
        except Exception as e:
            print("[-] screenshot failed:", e)

        # select要素の列挙（ラベル推定＋option一覧）
        selects = page.locator("select")
        print(f"[+] Found {selects.count()} <select> elements")
        for i in range(selects.count()):
            sel = selects.nth(i)
            label = "(label not found)"
            try:
                sel_id = sel.get_attribute("id")
                if sel_id:
                    lab = page.locator(f"label[for='{sel_id}']")
                    if lab.count() > 0:
                        label = lab.nth(0).inner_text().strip()
            except:
                pass
            # 直前にあるlabelで代替
            if label == "(label not found)":
                try:
                    label = sel.locator("xpath=preceding::label[1]").inner_text().strip()
                except:
                    pass

            print(f"\n== SELECT #{i+1} | Label: {label} ==")
            opts = sel.locator("option")
            for j in range(opts.count()):
                t = opts.nth(j).inner_text().strip()
                v = opts.nth(j).get_attribute("value")
                print(f" - option: '{t}' (value='{v}')")

        # input[type=date] があるかチェック
        date_inputs = page.locator("input[type='date']")
        print(f"\n[+] date inputs count: {date_inputs.count()}")

        # 「Welke tijd」っぽいセレクトのテキストを特定
        time_sel = None
        for i in range(selects.count()):
            if ":" in selects.nth(i).inner_text():
                time_sel = selects.nth(i)
                break
        print("[+] Time select found:", bool(time_sel))
        if time_sel:
            print("[+] Time select text sample:\n", time_sel.inner_text())

        browser.close()

if __name__ == "__main__":
    main()
