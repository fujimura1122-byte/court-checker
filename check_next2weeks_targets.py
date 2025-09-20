from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"

# チェック対象（固定）
TARGETS = [
    ("Mon", "20:00"),
    ("Thu", "20:00"),
    ("Sun", "14:00"),
]
WEEKS_AHEAD = 2  # 再来週

MONTH_ABBR = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
WD_IDX = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}

def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int) -> datetime:
    base = datetime(base.year, base.month, base.day)
    days = (weekday_idx - base.weekday() + 7) % 7
    days += 7*(weeks_ahead-1)
    return base + timedelta(days=days)

def set_duration(page):
    # 可視の select 群から「1,5 uur / 1 uur」を含むものを探して選択
    page.wait_for_selector("select", timeout=10000)
    sels = page.locator("select")
    dur = None
    for i in range(sels.count()):
        el = sels.nth(i)
        if not el.is_visible():
            continue
        txt = el.inner_text().lower()
        if ("1 uur" in txt or "1,5 uur" in txt) and "8 uur" in txt:
            dur = el
            break
    if not dur:
        return
    want = "1,5 uur" if "1,5 uur" in dur.inner_text() else "1 uur"
    opts = dur.locator("option")
    for i in range(opts.count()):
        if opts.nth(i).inner_text().strip() == want:
            dur.select_option(opts.nth(i).get_attribute("value") or want)
            return

def open_datepicker(page):
    # 入力 or アイコンをクリックして datepicker を開く
    for sel in ["label:has-text('Voor wanneer?') ~ * input", ".ui-datepicker-trigger", "input.hasDatepicker", "input[id*='date']"]:
        try:
            el = page.locator(sel).first
            if el.count():
                el.click()
                return True
        except:
            pass
    return False

def set_month_year_in_datepicker(page, d: datetime):
    # datepicker 内の select を force で選択
    month_sel = page.locator(".ui-datepicker select.ui-datepicker-month").first
    year_sel  = page.locator(".ui-datepicker select.ui-datepicker-year").first
    if year_sel.count():
        try:
            year_sel.select_option(str(d.year), force=True)
        except:
            pass
    if month_sel.count():
        # 0始まり/数字/略称のどれでも対応
        for val in (str(d.month-1), str(d.month)):
            try:
                month_sel.select_option(val, force=True)
                return
            except:
                pass
        want = MONTH_ABBR[d.month-1]
        opts = month_sel.locator("option")
        for i in range(opts.count()):
            t = opts.nth(i).inner_text().strip().lower()
            v = (opts.nth(i).get_attribute("value") or "").lower()
            if t == want or v == want:
                month_sel.select_option(opts.nth(i).get_attribute("value") or t, force=True)
                return

def click_day_in_calendar(page, day: int) -> bool:
    # 有効な日 (= a.ui-state-default) をクリック
    cal = page.locator(".ui-datepicker .ui-datepicker-calendar")
    if not cal.count():
        return False
    links = cal.locator("a.ui-state-default")
    for i in range(links.count()):
        if links.nth(i).inner_text().strip() == str(day):
            try:
                links.nth(i).click()
                return True
            except:
                pass
    return False

def time_has_start(page, start_hhmm: str) -> tuple[bool,str]:
    # 「Welke tijd」から開始が一致する option を探す
    sels = page.locator("select")
    time_sel = None
    for i in range(sels.count()):
        el = sels.nth(i)
        if ":" in el.inner_text():
            time_sel = el
            break
    if not time_sel:
        return (False, "")
    opts = time_sel.locator("option")
    for i in range(opts.count()):
        t = opts.nth(i).inner_text().strip()  # "20:00 - 21:30"
        if t.startswith(start_hhmm):
            return (True, t)
    return (False, "")

def main():
    today = datetime.now()
    targets = []
    for wd, hhmm in TARGETS:
        d = next_weekday(today, WD_IDX[wd], WEEKS_AHEAD)
        targets.append((d, wd, hhmm))

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 目視確認しやすく
        page = browser.new_page()
        page.set_default_timeout(8000)

        page.goto(BOOK_URL, wait_until="domcontentloaded")
        set_duration(page)

        # datepicker を開いておく
        open_datepicker(page)
        page.wait_for_selector(".ui-datepicker", timeout=8000)

        for d, wd, hhmm in targets:
            # 年月を合わせる→日クリック
            set_month_year_in_datepicker(page, d)
            page.wait_for_timeout(300)
            clicked = click_day_in_calendar(page, d.day)

            ok, label = (False, "")
            if clicked:
                # 時間セレクトに希望開始があるか
                ok, label = time_has_start(page, hhmm)

            results.append((d.strftime("%Y-%m-%d"), wd, hhmm, ok, label))

        browser.close()

    # 出力
    for date_str, wd, hhmm, ok, label in results:
        status = "Available ✅" if ok else "Not available ❌"
        extra = f" [{label}]" if label else ""
        print(f"{date_str} ({wd}) {hhmm} → {status}{extra}")

if __name__ == "__main__":
    main()
