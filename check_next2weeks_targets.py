import os
import csv
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# ====== 設定（環境変数 / slots.json で上書き可） ======
# デフォルト：再来週（2週間後）、月/木/日で固定
DEFAULT_WEEKS_AHEAD = int(os.getenv("WEEKS_AHEAD", "2"))
DEFAULT_TARGETS = [
    ("Mon", "20:00"),  # 月 20:00-21:30
    ("Thu", "20:00"),  # 木 20:00-21:30
    ("Sun", "14:00"),  # 日 14:00-15:30
]
DURATION_PREFERRED = "1,5 uur"  # なければ 1 uur を使用

BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
RESULTS_CSV = Path("results.csv")
SCREENSHOT_DIR = Path("screenshots")

# HEADLESS 切替：ローカル確認時は `HEADLESS=false` で可視モード
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

MONTH_ABBR = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
WD_IDX = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}


def load_slots_json():
    """
    任意：同じフォルダに slots.json があれば読み込んで
    weeks_ahead / targets を上書きします。
    例:
    {
      "weeks_ahead": 2,
      "targets": [
        {"weekday":"Mon","start":"20:00"},
        {"weekday":"Thu","start":"20:00"},
        {"weekday":"Sun","start":"14:00"}
      ]
    }
    """
    cfg_path = Path("slots.json")
    if not cfg_path.exists():
        return DEFAULT_WEEKS_AHEAD, DEFAULT_TARGETS
    try:
        import json
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        weeks = int(cfg.get("weeks_ahead", DEFAULT_WEEKS_AHEAD))
        targets = []
        for t in cfg.get("targets", []):
            targets.append((t["weekday"], t["start"]))
        if not targets:
            targets = DEFAULT_TARGETS
        return weeks, targets
    except Exception:
        return DEFAULT_WEEKS_AHEAD, DEFAULT_TARGETS


def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int) -> datetime:
    base = datetime(base.year, base.month, base.day)
    days = (weekday_idx - base.weekday() + 7) % 7
    days += 7 * (weeks_ahead - 1)
    return base + timedelta(days=days)


def set_duration(page):
    """
    可視の <select> 群の中から『1,5 uur / 1 uur ... 8 uur』が並ぶものを探し、
    1,5 uur があれば選択、無ければ 1 uur を選択。
    """
    page.wait_for_selector("select", timeout=10000)
    sels = page.locator("select")
    target_sel = None
    for i in range(sels.count()):
        el = sels.nth(i)
        if not el.is_visible():
            continue
        txt = (el.inner_text() or "").lower()
        if ("1 uur" in txt or "1,5 uur" in txt) and "8 uur" in txt:
            target_sel = el
            break
    if not target_sel:
        return
    txt = target_sel.inner_text()
    want = DURATION_PREFERRED if DURATION_PREFERRED in txt else "1 uur"
    opts = target_sel.locator("option")
    for i in range(opts.count()):
        if opts.nth(i).inner_text().strip() == want:
            target_sel.select_option(opts.nth(i).get_attribute("value") or want)
            return


def open_datepicker(page):
    """
    日付ピッカーを確実に開く（入力欄 or カレンダーアイコン or 既知のセレクタ候補を順に試す）
    """
    # ラベル紐付けの input
    try:
        el = page.get_by_label("Voor wanneer?")
        el.click()
        return True
    except:
        pass
    # アイコン
    try:
        page.locator(".ui-datepicker-trigger").first.click()
        return True
    except:
        pass
    # よくある候補
    for sel in ["input.hasDatepicker", "input[id*='date']", "input[name*='date']"]:
        try:
            inp = page.locator(sel).first
            if inp.count():
                inp.click()
                return True
        except:
            continue
    return False


def set_month_year_in_datepicker(page, d: datetime):
    """
    datepicker 内の 月/年 <select> を force 指定で合わせる。
    - 年: '2025' など
    - 月: 0始まり or 1始まり or 略称('sep','okt'...) のいずれにも対応
    """
    month_sel = page.locator(".ui-datepicker select.ui-datepicker-month").first
    year_sel  = page.locator(".ui-datepicker select.ui-datepicker-year").first

    if year_sel.count():
        try:
            year_sel.select_option(str(d.year), force=True)
        except:
            pass

    if month_sel.count():
        # 0始まり/1始まりの両対応
        for val in (str(d.month-1), str(d.month)):
            try:
                month_sel.select_option(val, force=True)
                return
            except:
                pass
        # 表示テキスト一致
        want = MONTH_ABBR[d.month-1]
        opts = month_sel.locator("option")
        for i in range(opts.count()):
            t = opts.nth(i).inner_text().strip().lower()
            v = (opts.nth(i).get_attribute("value") or "").lower()
            if t == want or v == want:
                month_sel.select_option(opts.nth(i).get_attribute("value") or t, force=True)
                return


def click_day_in_calendar(page, day: int) -> bool:
    """有効な日（a.ui-state-default）をクリック。"""
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


def time_has_start(page, start_hhmm: str) -> tuple[bool, str]:
    """
    「Welke tijd」の <select> を検出し、開始時刻が一致する option があるかを確認。
    戻り値：(見つかったか, "20:00 - 21:30" のような表示テキスト)
    """
    sels = page.locator("select")
    time_sel = None
    for i in range(sels.count()):
        el = sels.nth(i)
        txt = el.inner_text()
        if ":" in txt:
            time_sel = el
            break
    if not time_sel:
        return (False, "")
    opts = time_sel.locator("option")
    for i in range(opts.count()):
        t = opts.nth(i).inner_text().strip()  # 例: "20:00 - 21:30"
        if t.startswith(start_hhmm):
            return (True, t)
    return (False, "")


def ensure_csv_header(csv_path: Path):
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["run_ts", "date", "weekday", "start", "available", "slot_label"])


def append_csv(csv_path: Path, rows: list[dict]):
    ensure_csv_header(csv_path)
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        ts = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            w.writerow([ts, r["date"], r["weekday"], r["start"], r["available"], r["slot_label"]])


def main():
    weeks_ahead, target_pairs = load_slots_json()

    # チェックする実日付の算出
    today = datetime.now()
    targets = []
    for wd, hhmm in target_pairs:
        d = next_weekday(today, WD_IDX[wd], weeks_ahead)
        targets.append((d, wd, hhmm))

    results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=HEADLESS)
    page = browser.new_page()
    page.set_default_timeout(20000)  # 20秒に延長

    page.goto(BOOK_URL, wait_until="networkidle")



        # 1) 所要時間（1,5 uur 優先）を選択
        set_duration(page)

        # 2) datepicker を開いておく
        open_datepicker(page)
        try:
            page.wait_for_selector(".ui-datepicker", timeout=8000)
        except:
            # うまく開かない場合も後続で動くケースがあるので続行
            pass

        for d, wd, hhmm in targets:
            # 年月合わせ → 日クリック
            set_month_year_in_datepicker(page, d)
            page.wait_for_timeout(250)
            clicked = click_day_in_calendar(page, d.day)

            ok, label = (False, "")
            if clicked:
                ok, label = time_has_start(page, hhmm)

            results.append({
                "date": d.strftime("%Y-%m-%d"),
                "weekday": wd,
                "start": hhmm,
                "available": "YES" if ok else "NO",
                "slot_label": label
            })

            # 空きを見つけたら、証跡スクショを保存
            if ok:
                SCREENSHOT_DIR.mkdir(exist_ok=True)
                shot_name = f"{d.strftime('%Y%m%d')}_{wd}_{hhmm.replace(':','')}.png"
                page.screenshot(path=str(SCREENSHOT_DIR / shot_name), full_page=True)

        browser.close()

    # 出力（コンソール）
    for r in results:
        status = "Available ✅" if r["available"] == "YES" else "Not available ❌"
        extra = f" [{r['slot_label']}]" if r["slot_label"] else ""
        print(f"{r['date']} ({r['weekday']}) {r['start']} → {status}{extra}")

    # CSV に追記（履歴管理）
    append_csv(RESULTS_CSV, results)


if __name__ == "__main__":
    main()
