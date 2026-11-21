"""
监控带单员的"最新紀錄"(开仓/平仓记录),有新记录就推送到手机(Telegram,没配置则 ntfy)。

"最新紀錄"页签是公开的,不需要登录。脚本用无头浏览器读取页面文字,不会碰你的账户,
全程只读,不会下单。

用法:
    python monitor_trades.py --url "<带单员主页链接>"
    python monitor_trades.py --url "<链接>" --once      # 只读一次并打印,不推送(用来测试)
"""
import argparse
import json
import os
import random
import re
import sys
import time

from playwright.sync_api import sync_playwright

import notifier as core  # Telegram/ntfy 推送、心跳、防休眠

SEEN_FILE = "seen_trades.json"
TIME_RE = re.compile(r"(\d\d-\d\d, \d\d:\d\d:\d\d)")


def load_seen():
    try:
        return set(json.load(open(SEEN_FILE, encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen):
    json.dump(sorted(seen)[-500:], open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False)


def parse_records(body: str):
    """从页面文字里解析出 [(时间, 动作, 描述)],最新的在前。"""
    i = body.find("轉帳歷史")
    if i < 0:
        i = body.find("转账历史")
    text = body[i:] if i >= 0 else body
    parts = TIME_RE.split(text)  # [前缀, 时间1, 内容1, 时间2, 内容2, ...]
    records = []
    for k in range(1, len(parts) - 1, 2):
        t = parts[k]
        lines = [x.strip() for x in parts[k + 1].strip().split("\n") if x.strip()]
        if len(lines) < 2:
            continue
        action, desc = lines[0], lines[1]
        records.append((t, action, desc))
    return records


def fetch_records(page, url):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for name in ("最新紀錄", "最新记录", "Latest Records"):
        tab = page.get_by_role("tab", name=name)
        if tab.count():
            tab.first.click()
            break
    page.wait_for_timeout(2500)
    return parse_records(page.inner_text("body"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--interval", type=float, default=20.0, help="轮询间隔(秒),默认20")
    ap.add_argument("--once", action="store_true", help="只读取一次并打印,不推送")
    ap.add_argument("--check-once", action="store_true",
                    help="检查一次并推送新记录后退出(给 GitHub Actions 等定时任务用)")
    args = ap.parse_args()
    args.interval = max(args.interval, 10.0)

    core.keep_awake()
    topic = core.get_topic()
    seen = load_seen()
    first_run = not seen
    fails = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(locale="zh-TW").new_page()
        while True:
            core.heartbeat()
            try:
                recs = fetch_records(page, args.url)
                fails = 0
                ts = time.strftime("%H:%M:%S")
                if not recs:
                    print(f"[{ts}] 没读到记录(页面可能没加载完、结构变了,或该网络被币安限制访问)")
                    if args.check_once:
                        sys.exit(1)
                elif args.once:
                    for r in recs[:10]:
                        print(" | ".join(r))
                    break
                else:
                    keys = [f"{t}|{a}|{d}" for t, a, d in recs]
                    new = [(r, k) for r, k in zip(recs, keys) if k not in seen]
                    if first_run:
                        # 第一次只记下已有记录,避免把历史当成新交易狂推
                        seen.update(keys)
                        save_seen(seen)
                        first_run = False
                        t, a, d = recs[0]
                        core.push(topic, "交易监控已启动", f"当前最新一条:{t} {a}\n{d}", priority=3)
                        print(f"[{ts}] 已记录 {len(recs)} 条现有记录,开始监控")
                    elif new:
                        for (t, a, d), k in reversed(new):  # 旧的先推
                            print(f"[{ts}] 新记录: {t} {a} {d}")
                            core.push(topic, f"带单员新操作:{a}", f"{t}\n{d}")
                            seen.add(k)
                        save_seen(seen)
                    else:
                        print(f"[{ts}] 无新记录(共 {len(recs)} 条)")
            except KeyboardInterrupt:
                print("已停止")
                break
            except Exception as e:
                fails += 1
                if args.check_once:
                    print(f"异常: {e}", file=sys.stderr)
                    sys.exit(1)
                print(f"异常({fails}/5): {str(e).splitlines()[0] if str(e) else e}", file=sys.stderr)
                if fails >= 5:
                    sys.exit(1)  # 交给外层 bat 自动重启
            if args.check_once:
                break
            time.sleep(args.interval + random.uniform(0, 5))
        browser.close()


if __name__ == "__main__":
    main()
