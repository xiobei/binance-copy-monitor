"""手机推送、心跳、防休眠等通用小工具(只依赖标准库)。"""
import json
import os
import secrets
import time
import urllib.request

TOPIC_FILE = "ntfy_topic.txt"
TG_FILE = "telegram.json"  # {"token": "...", "chat_id": 123456}
HB_FILE = "heartbeat_url.txt"  # 里面放 healthchecks.io 给你的 ping 链接(可选)
_last_hb = 0.0


def keep_awake():
    """脚本运行期间阻止电脑自动休眠(只对本进程生效,脚本退出即恢复,不改系统设置)。"""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # CONTINUOUS | SYSTEM_REQUIRED
    except Exception:
        pass


def heartbeat():
    """每 60 秒向心跳服务报一次平安。断了超时,心跳服务会通知你"掉线了"。"""
    global _last_hb
    if time.time() - _last_hb < 60:
        return
    _last_hb = time.time()
    url = os.environ.get("HEARTBEAT_URL", "").strip()
    if not url and os.path.exists(HB_FILE):
        url = open(HB_FILE, encoding="utf-8").read().strip()
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).read()
    except Exception as e:
        print(f"心跳发送失败: {e}")


def get_topic() -> str:
    """ntfy 频道名(没配置 Telegram 时用)。第一次运行自动生成随机名并保存。"""
    if os.path.exists(TOPIC_FILE):
        t = open(TOPIC_FILE, encoding="utf-8").read().strip()
        if t:
            return t
    t = "binance-" + secrets.token_hex(6)
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        f.write(t)
    return t


def tg_load():
    """读取 Telegram 配置;没有 chat_id 时自动从机器人收到的消息里找并保存。"""
    # 优先读环境变量(给 GitHub Actions 的 Secrets 用,避免把令牌写进文件)
    if os.environ.get("TG_TOKEN") and os.environ.get("TG_CHAT_ID"):
        return {"token": os.environ["TG_TOKEN"], "chat_id": os.environ["TG_CHAT_ID"]}
    if not os.path.exists(TG_FILE):
        return None
    cfg = json.load(open(TG_FILE, encoding="utf-8"))
    if not cfg.get("token"):
        return None
    if not cfg.get("chat_id"):
        try:
            url = f"https://api.telegram.org/bot{cfg['token']}/getUpdates"
            data = json.loads(urllib.request.urlopen(url, timeout=10).read())
            for u in reversed(data.get("result", [])):
                m = u.get("message")
                if m:
                    cfg["chat_id"] = m["chat"]["id"]
                    json.dump(cfg, open(TG_FILE, "w", encoding="utf-8"))
                    break
        except Exception as e:
            print(f"Telegram 获取 chat_id 失败: {e}")
    return cfg if cfg.get("chat_id") else None


def tg_send(cfg, text: str) -> bool:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
        data=json.dumps({"chat_id": cfg["chat_id"], "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"Telegram 推送失败: {e}")
        return False


def push(topic: str, title: str, message: str, priority: int = 5):
    """优先用 Telegram 推送;没配置 Telegram 时用 ntfy.sh。"""
    cfg = tg_load()
    if cfg:
        if tg_send(cfg, f"{title}\n{message}"):
            return True
        print("Telegram 失败,改用 ntfy")
    body = json.dumps({
        "topic": topic, "title": title, "message": message,
        "priority": priority, "tags": ["rotating_light"],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ntfy.sh/", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"手机推送失败: {e}")
        return False
