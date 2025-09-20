# -*- coding: utf-8 -*-
"""
Uithoorn 体育館の予約可否を「再来週の 月/木/日 固定時間」でチェック。
- 実行結果は標準出力と results.csv に残す
- 空きが見つかった日の画面を screenshots/ に保存
- CI( GitHub Actions )でも落ちにくいように待機時間拡大・リトライ・トレース保存

切替：
  - HEADLESS=false でローカル目視（既定はヘッドレス）
  - slots.json があれば weeks_ahead / targets を上書き
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

import os
import csv
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# ----------------- 設定 -----------------
BOOK_URL = "https://avo.hta.nl/uithoorn/Accommodation/Book/106"
RESULTS_CSV = Path("results.csv")
SCREENSHOT_DIR = Path("screenshots")

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
DEFAULT_WEEKS_AHEAD = int(os.getenv("WEEKS_AHEAD", "2"))
DEFAULT_TARGETS = [
    ("Mon", "20:00"),  # 月 20:00-21:30
    ("Thu", "20:00"),  # 木 20:00-21:30
    ("Sun", "14:00"),  # 日 14:00-15:30
]
DURATION_PREFERRED = "1,5 uur"

MONTH_ABBR = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
WD_IDX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
# ---------------------------------------


# ========= ユーティリティ =========
def load_slots_json():
    cfg = Path("slots.json")
    if not cfg.exists():
        return DEFAULT_WEEKS_AHEAD, DEFAULT_TARGETS
    try:
        import json
        data = json.loads(cfg.read_text(encoding="utf-8"))
        weeks = int(data.get("weeks_ahead", DEFAULT_WEEKS_AHEAD))
        targets = []
        for t in data.get("targets", []):
            targets.append((t["weekday"], t["start"]))
        if not targets:
            targets = DEFAULT_TARGETS
        return weeks, targets
    except Exception:
        return DEFAULT_WEEKS_AHEAD, DEFAULT_TARGETS


def next_weekday(base: datetime, weekday_idx: int, weeks_ahead: int) -> datetime:
    base = datetime(base.year, base.month, base.day)
    delta = (weekday_idx - base.weekday() + 7) % 7
    delta += 7 * (weeks_ahead - 1)
    return base + timedelta(days=delta)


def ensure_csv_header(path: Path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["run_ts", "date", "weekday", "start", "available", "slot_label"])


def append_csv(path: Path, rows: list[dict]):
    ensure_csv_header(path)
    ts = datetime.now().isoformat(timespec="seconds")
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([ts, r["date"], r["weekday"], r["start"], r["available"], r["slot_label"]])


# ========= 画面操作 =========
def set_duration(page):
    """1,5 uur が選べれば選択、無ければ 1 uur を選択。"""
    page.wait_for_selector("select", timeout=20000)
    sels = page.locator("select")
    target = None
    for i in range(sels.count()):
        el = sels.nth(i)
        if not el.is_visible():
            continue
        txt = (el.inner_text() or "").lower()
        if ("1 uur" in txt or "1,5 uur" in txt) and "8 uur" in txt:
            target = el
            break
    if not target:
        return
    txt = target.inner_text()
    want = DURATION_PREFERRED if DURATION_PREFERRED in txt else "1 uur"
    opts = target.locator("option")
    for i in range(opts.count()):
        opt = opts.nth(i)
        if opt.inner_text().strip() == want:
            target.select_option(opt.get_attribute("value") or want)
            return


def open_datepicker(page) -> bool:
    """日付ピッカーを開く（複数の候補で試行）。"""
    try:
        el = page.get_by_label("Voor wanneer?")
        el.click()
        return True
    except Exception:
        pass
    try:
        page.locator(".ui-datepicker-trigger").first.click()
        return True
    except Exception:
        pass
    for sel in ["input.hasDatepicker", "input[id*='date']", "input[name*='date']"]:
        try:
            inp = page.locator(sel).first
            if inp.count():
                inp.click()
                return True
        except Exception:
            continue
    return False


def set_month_year_in_datepicker(page, d: datetime):
    """datepicker の月/年セレクタに合わせる（0/1始まり・略称の両対応）。"""
    month_sel = page.locator(".ui-datepicker select.ui-datepicker-month").first
    year_sel = page.locator(".ui-datepicker select.ui-datepicker-year").first

    if year_sel.count():
        try:
            year_sel.select_option(str(d.year), force=True)
        except Exception:
            pass

    if month_sel.count():
        for val in (str(d.month - 1), str(d.month)):
            try:
                month_sel.select_option(val, force=True)
                return
            except Exception:
                pass
        want = MONTH_ABBR[d.month - 1]
        opts = month_sel.locator("option")
        for i in range(opts.count()):
            t = opts.nth(i).inner_text().strip().lower()
            v = (opts.nth(i).get_attribute("value") or "").lower()
            if t == want or v == want:
                month_sel.select_option(opts.nth(i).get_attribute("value") or t, force=True)
                return


def click_day_in_calendar(page, day: int) -> bool:
    cal = page.locator(".ui-datepicker .ui-datepicker-calendar")
    if not cal.count():
        return False
    links = cal.locator("a.ui-state-default")
    for i in range(links.count()):
        if links.nth(i).inner_text().strip() == str(day):
            try:
                links.nth(i).click()
                return True
            except Exception:
                pass
    return False


def time_has_start(page, start_hhmm: str) -> tuple[bool, str]:
    """『Welke tijd』のセレクトから指定開始時刻オプションの有無を確認。"""
    sels = page.locator("select")
    time_sel = None
    for i in range(sels.count()):
        el = sels.nth(i)
        if ":" in (el.inner_text() or ""):
            time_sel = el
            break
    if not time_sel:
        return False, ""
    opts = time_sel.locator("option")
    for i in range(opts.count()):
        t = opts.nth(i).inner_text().strip()  # "20:00 - 21:30"
        if t.startswith(start_hhmm):
            return True, t
    return False, ""


# ========= メイン =========
def main():
    weeks_ahead, base_targets = load_slots_json()

    # チェック対象の日付リスト作成
    today = datetime.now()
    targets = []
    for wd, hhmm in base_targets:
        d = next_weekday(today, WD_IDX[wd], weeks_ahead)
        targets.append((d, wd, hhmm))

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        # 解析用トレース
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(30000)  # 30s

        # 画面遷移はリトライ
        def goto_with_retry(url: str, attempts: int = 3):
            last = None
            for _ in range(attempts):
                try:
                    page.goto(url, wait_until="networkidle", timeout=45000)
                    return
                except Exception as e:
                    last = e
                    page.wait_for_timeout(1500)
            raise last

        try:
            goto_with_retry(BOOK_URL)

            # 1) 所要時間選択
            set_duration(page)

            # 2) datepicker を開く（再試行あり）
            opened = open_datepicker(page)
            if not opened:
                page.wait_for_timeout(700)
                opened = open_datepicker(page)
            if opened:
                try:
                    page.wait_for_selector(".ui-datepicker", timeout=12000)
                except Exception:
                    pass

            # 3) それぞれの日付で可否判定
            for d, wd, hhmm in targets:
                try:
                    set_month_year_in_datepicker(page, d)
                    page.wait_for_timeout(300)
                    clicked = click_day_in_calendar(page, d.day)

                    ok, label = (False, "")
                    if clicked:
                        ok, label = time_has_start(page, hhmm)

                    results.append({
                        "date": d.strftime("%Y-%m-%d"),
                        "weekday": wd,
                        "start": hhmm,
                        "available": "YES" if ok else "NO",
                        "slot_label": label,
                    })

                    if ok:
                        SCREENSHOT_DIR.mkdir(exist_ok=True)
                        name = f"{d.strftime('%Y%m%d')}_{wd}_{hhmm.replace(':','')}.png"
                        page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=True)

                except Exception as e:
                    # 1件失敗しても続行
                    results.append({
                        "date": d.strftime("%Y-%m-%d"),
                        "weekday": wd,
                        "start": hhmm,
                        "available": "ERROR",
                        "slot_label": str(e)[:120],
                    })
                    try:
                        page.reload(wait_until="networkidle")
                    except Exception:
                        pass

        finally:
            # トレース保存（失敗時の解析用）
            try:
                context.tracing.stop(path="trace.zip")
            except Exception:
                pass
            browser.close()

    # 出力
    for r in results:
        if r["available"] == "YES":
            status = "Available ✅"
        elif r["available"] == "NO":
            status = "Not available ❌"
        else:
            status = f"ERROR ⚠️"
        extra = f" [{r['slot_label']}]" if r["slot_label"] else ""
        print(f"{r['date']} ({r['weekday']}) {r['start']} → {status}{extra}")

    append_csv(RESULTS_CSV, results)


if __name__ == "__main__":
    main()
