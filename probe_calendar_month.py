from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import re

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
WEEKS_AHEAD = 2  # 2週間後の“月”を調べる

def log(msg): print("[LOG]", msg, flush=True)

def pick_duration(page):
    # 可視の select 群の中から 'uur' を含むものを探す
    page.wait_for_selector("select", timeout=10000)
    sels = page.locator("select")
    target_sel = None
    for i in range(sels.count()):
        el = sels.nth(i)
        try:
            if not el.is_visible():  # 可視のもののみ
                continue
            txt = el.inner_text(timeout=800).lower()
        except:
            continue
        if ("1 uur" in txt or "1,5 uur" in txt) and "8 uur" in txt:
            target_sel = el
            break
    if not target_sel:
        log("duration select not found (visible)"); return
    txt = target_sel.inner_text()
    want = "1,5 uur" if "1,5 uur" in txt else "1 uur"
    opts = target_sel.locator("option")
    for i in range(opts.count()):
        lab = opts.nth(i).inner_text().strip()
        if lab == want:
            target_sel.select_option(opts.nth(i).get_attribute("value") or lab)
            log(f"duration = {lab}")
            return
    log("duration pick failed")

def open_datepicker(page):
    # 「Voor wanneer?」の入力をクリックして datepicker を開く（候補を総当り）
    # 1) ラベル経由
    try:
        el = page.get_by_label("Voor wanneer?")
        el.click()
        return True
    except:
        pass
    # 2) カレンダーアイコン
    try:
        page.locator(".ui-datepicker-trigger").first.click()
        return True
    except:
        pass
    # 3) hasDatepicker / datepicker っぽい input
    for sel in ["input.hasDatepicker", "input[id*='date']", "input[name*='date']"]:
        try:
            inp = page.locator(sel).first
            if inp.count():
                inp.click()
                return True
        except:
            continue
    return False

def find_datepicker_selects(page):
    # datepicker が開いている前提で、内側の月/年 select を取得（非表示でも force 選択する）
    month_sel = page.locator(".ui-datepicker select.ui-datepicker-month").first
    year_sel  = page.locator(".ui-datepicker select.ui-datepicker-year").first
    return month_sel if month_sel.count() else None, year_sel if year_sel.count() else None

def read_month_availability(page):
    # カレンダーの「選択可の <a> を持つセル」と「不可（unselectable/disabled）」を分けて読む
    cal = page.locator(".ui-datepicker .ui-datepicker-calendar")
    if not cal.count():
        return [], []
    enable = []
    disable = []
    # enable: td の中に a がある
    links = cal.locator("td a.ui-state-default")
    for i in range(links.count()):
        try:
            d = int(links.nth(i).inner_text().strip())
            enable.append(d)
        except:
            pass
    # disable: td に unselectable/disabled クラス
    cells = cal.locator("td.ui-datepicker-unselectable, td.ui-state-disabled")
    for i in range(cells.count()):
        t = cells.nth(i).inner_text().strip()
        if t.isdigit():
            disable.append(int(t))
    return sorted(set(enable)), sorted(set(disable))

def main():
    target_day = datetime.now() + timedelta(weeks=WEEKS_AHEAD)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(8000)

        log("open page")
        page.goto(BOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(600)

        # 1) 所要時間（1,5 uur 優先）を設定
        pick_duration(page)

        # 2) datepicker を必ず開く
        if not open_datepicker(page):
            log("failed to open datepicker (will proceed anyway)")
        page.wait_for_selector(".ui-datepicker", timeout=8000)

        # 3) datepicker 内の月/年 select を取得（非表示でも OK、force=True で選択）
        month_sel, year_sel = find_datepicker_selects(page)
        if not (month_sel and year_sel):
            log("datepicker selects not found")
        else:
            # 年
            try:
                year_sel.select_option(str(target_day.year), force=True)
            except:
                log("year select_option failed (force)")
            # 月（0始まり/略称/数値いずれにも対応）
            # まず 0始まり index を試す
            ok = False
            for val in (str(target_day.month-1), str(target_day.month),):
                try:
                    month_sel.select_option(val, force=True)
                    ok = True
                    break
                except:
                    continue
            if not ok:
                # 表示テキスト一致で拾う
                want = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"][target_day.month-1]
                opts = month_sel.locator("option")
                for i in range(opts.count()):
                    t = opts.nth(i).inner_text().strip().lower()
                    v = (opts.nth(i).get_attribute("value") or "").lower()
                    if t == want or v == want:
                        month_sel.select_option(opts.nth(i).get_attribute("value") or t, force=True)
                        ok = True
                        break
            if not ok:
                log("month select_option failed")

        page.wait_for_timeout(400)

        # 4) その月の選択可/不可日を読む
        enable_days, disable_days = read_month_availability(page)

        print(f"\n=== {target_day.year}-{target_day.month:02d} の状況 ===")
        print("選択可の日:", enable_days)
        print("選択不可の日:", disable_days)

        # スクショ保存（確認用）
        page.screenshot(path="calendar_month_probe.png", full_page=True)
        log("saved screenshot: calendar_month_probe.png")

        browser.close()

if __name__ == "__main__":
    main()
