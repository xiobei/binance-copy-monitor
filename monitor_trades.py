"""
监控带单员的交易记录(开仓/平仓),有新记录就推送到手机(Telegram,没配置则 ntfy)。

默认直接轮询币安公开接口(和"最新紀錄"页签同一个数据源,不需要登录、不需要浏览器),
约每 4 秒一次,延迟只有几秒。接口连续失败时,自动退回到"无头浏览器读页面"的老办法。
全程只读,不会下单,不会碰你的账户。

用法:
    python monitor_trades.py --url "<带单员主页链接>"
    python monitor_trades.py --url "<链接>" --once      # 只读一次并打印,不推送(用来测试)
"""
import argparse
import json
import random
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import notifier as core  # Telegram/ntfy 推送、心跳、防休眠

SEEN_FILE = "seen_trades.json"   # 页面模式用
SEEN_API = "seen_orders.json"    # 接口模式用
TIME_RE = re.compile(r"(\d\d-\d\d, \d\d:\d\d:\d\d)")
API = "https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/order-history"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
TZ8 = timezone(timedelta(hours=8))


def load_seen(path):
    try:
        return set(json.load(open(path, encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen, path):
    json.dump(sorted(seen)[-500:], open(path, "w", encoding="utf-8"), ensure_ascii=False)


# ---------------------------------------------------------------- 接口模式
def fetch_orders(pid, size=30):
    now = int(time.time() * 1000)
    body = json.dumps({"portfolioId": pid, "startTime": now - 30 * 86400000,
                       "endTime": now, "pageSize": size, "pageNumber": 1}).encode()
    req = urllib.request.Request(
        API, data=body, method="POST",
        headers={"Content-Type": "application/json", "clienttype": "web", "User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if d.get("code") != "000000":
        raise RuntimeError(f"接口返回 {d.get('code')} {d.get('message')}")
    return d["data"]["list"] or []  # 最新的在前


def fmt(x):
    return f"{float(x):.6f}".rstrip("0").rstrip(".")


def describe(o):
    side, ps = o["side"], o["positionSide"]
    if ps in ("LONG", "SHORT"):
        opening = (side == "SELL" and ps == "SHORT") or (side == "BUY" and ps == "LONG")
        action = ("开" if opening else "平") + ("多" if ps == "LONG" else "空")
    else:
        opening = True
        action = "买入" if side == "BUY" else "卖出"
    t = datetime.fromtimestamp(o["orderTime"] / 1000, TZ8).strftime("%m-%d %H:%M:%S")
    desc = f'{o["symbol"]} {action} 数量{fmt(o["executedQty"])} 均价{fmt(o["avgPrice"])}'
    pnl = float(o.get("totalPnl") or 0)
    if not opening and pnl:
        desc += f" 盈亏{pnl:+.2f}"
    return t, action, desc


def order_key(o):
    return f'{o["orderTime"]}|{o["symbol"]}|{o["side"]}|{o["positionSide"]}|{o["executedQty"]}'


def run_api(args, pid, topic):
    """返回 'fallback' 表示接口连续失败,需要改用页面模式;其他情况正常结束。"""
    seen = load_seen(SEEN_API)
    first_run = not seen
    fails = 0
    deadline = time.time() + args.duration if args.duration else None
    while True:
        core.heartbeat()
        try:
            orders = fetch_orders(pid)
            fails = 0
            ts = time.strftime("%H:%M:%S")
            if args.once:
                for o in orders[:10]:
                    print(" | ".join(describe(o)))
                return None
            new = [o for o in orders if order_key(o) not in seen]
            if first_run:
                first_run = False
                cutoff = (time.time() - args.lookback * 60) * 1000
                # 第一次只记下历史;--lookback 分钟内的还是要推(云端重启衔接用)
                for o in list(new):
                    if args.lookback <= 0 or o["orderTime"] < cutoff:
                        seen.add(order_key(o))
                        new.remove(o)
                save_seen(seen, SEEN_API)
                if orders:
                    t, a, d = describe(orders[0])
                    core.push(topic, "交易监控已启动", f"当前最新一条:{t} {a}\n{d}", priority=3)
                print(f"[{ts}] 接口模式启动,已记录现有记录")
            if new:
                for o in reversed(new):  # 旧的先推
                    t, a, d = describe(o)
                    print(f"[{ts}] 新记录: {t} {a} {d}")
                    core.push(topic, f"带单员新操作:{a}", f"{t}\n{d}")
                    seen.add(order_key(o))
                save_seen(seen, SEEN_API)
            elif not first_run:
                print(f"[{ts}] 无新记录")
        except KeyboardInterrupt:
            print("已停止")
            return None
        except Exception as e:
            fails += 1
            print(f"接口异常({fails}/5): {str(e).splitlines()[0] if str(e) else e}", file=sys.stderr)
            if args.check_once:
                sys.exit(1)
            if fails >= 5:
                return "fallback"
            if "429" in str(e):
                time.sleep(30)  # 被限速,先歇一会
        if args.check_once or (deadline and time.time() >= deadline):
            return None
        time.sleep(args.interval + random.uniform(0, args.interval * 0.3))


# ---------------------------------------------------------------- 页面模式(备用)
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
        records.append((t, lines[0], lines[1]))
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


def run_browser(args, topic):
    from playwright.sync_api import sync_playwright
    seen = load_seen(SEEN_FILE)
    first_run = not seen
    fails = 0
    deadline = time.time() + args.duration if args.duration else None
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
                        seen.update(keys)
                        save_seen(seen, SEEN_FILE)
                        first_run = False
                        t, a, d = recs[0]
                        core.push(topic, "交易监控已启动(页面模式)", f"当前最新一条:{t} {a}\n{d}", priority=3)
                        print(f"[{ts}] 已记录 {len(recs)} 条现有记录,开始监控")
                    elif new:
                        for (t, a, d), k in reversed(new):
                            print(f"[{ts}] 新记录: {t} {a} {d}")
                            core.push(topic, f"带单员新操作:{a}", f"{t}\n{d}")
                            seen.add(k)
                        save_seen(seen, SEEN_FILE)
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
            if args.check_once or (deadline and time.time() >= deadline):
                break
            time.sleep(max(args.interval, 10.0) + random.uniform(0, 5))
        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--interval", type=float, default=4.0, help="轮询间隔(秒),默认4")
    ap.add_argument("--once", action="store_true", help="只读取一次并打印,不推送")
    ap.add_argument("--check-once", action="store_true", help="检查一次并推送新记录后退出")
    ap.add_argument("--duration", type=float, default=0, help="持续运行多少秒后正常退出(云端用),0=一直跑")
    ap.add_argument("--lookback", type=float, default=0,
                    help="首次运行时,这么多分钟内的记录也当作新记录推送(云端重启衔接用)")
    ap.add_argument("--mode", choices=["auto", "api", "browser"], default="auto")
    args = ap.parse_args()
    args.interval = max(args.interval, 2.0)

    core.keep_awake()
    topic = core.get_topic()
    m = re.search(r"lead-details/(\d+)", args.url)
    if args.mode != "browser" and m:
        res = run_api(args, m.group(1), topic)
        if res != "fallback":
            return
        if args.mode == "api":
            sys.exit(1)  # 云端没装浏览器,直接报失败
        core.push(topic, "监控提醒", "币安接口连续失败,已切换到页面读取模式(会慢一些)", priority=3)
    elif args.mode == "api":
        sys.exit("链接里没找到带单员 ID(lead-details/数字)")
    run_browser(args, topic)


if __name__ == "__main__":
    main()
