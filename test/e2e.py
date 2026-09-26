#!/usr/bin/env python3
"""
端到端自动化测试（fake 模式）
用法：
    python3 test/e2e.py                 # 本机模式：自动起 server，打 http://127.0.0.1:8018
    python3 test/e2e.py https://zhibo.jack-sun.com   # 线上模式（secret 自动 ssh 从服务器取）
- host：headless Edge/Chrome，?fake=1&autostart=1（canvas 假画面 + 假音频）
- viewer：另一个 headless 实例，加入房间
- 通过 DevTools /json 轮询 document.title 判定：
    host: H:ok:r<room> → H:live:v1（观众连上）
    viewer: V:playing（视频字节持续增长且 videoWidth>0）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.path.expanduser("~/Documents/screen-share-live")
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
CHROME = next((p for p in CHROME_CANDIDATES if os.path.exists(p)), None)
PORT = 8018
REMOTE_BASE = sys.argv[1] if len(sys.argv) > 1 else None  # 如 https://zhibo.jack-sun.com

FLAGS = [
    "--headless=new",
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
]


def launch(port, profile, url):
    return subprocess.Popen(
        [CHROME, *FLAGS, f"--remote-debugging-port={port}",
         f"--user-data-dir=/tmp/ssl-e2e-{profile}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def title(port):
    """取本项目页面的 title（按 URL 匹配，跳过 Edge 首启欢迎页等杂页）"""
    host_frag = (REMOTE_BASE or f"127.0.0.1:{PORT}").split("//")[-1]
    try:
        data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
        pages = [t for t in data
                 if t.get("type") == "page" and host_frag in t.get("url", "")]
        return pages[0].get("title", "") if pages else ""
    except Exception:
        return ""


def wait_for(pred, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            print(f"  [ok] {what}（{time.time()-t0:.1f}s）")
            return v
        time.sleep(1)
    return None


def main():
    if not CHROME:
        print("FAIL: 找不到 Chrome/Edge"); sys.exit(1)

    if REMOTE_BASE:
        # 线上模式：secret 从服务器取，不打印；server 无需本机起
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "jacksun-tencent",
             "node -e 'console.log(require(\"/home/ubuntu/screen-share-live/config.json\").hostSecret)'"],
            capture_output=True, text=True, timeout=15)
        secret = r.stdout.strip()
        if not secret:
            print("FAIL: 取不到线上 secret"); sys.exit(1)
        base = REMOTE_BASE
    else:
        with open(os.path.join(BASE, "config.json")) as f:
            secret = json.load(f)["hostSecret"]
        base = f"http://127.0.0.1:{PORT}"

    procs = []
    try:
        if not REMOTE_BASE:
            server = subprocess.Popen(
                ["node", os.path.join(BASE, "server.js")],
                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            )
            procs.append(server)
            if not wait_for(lambda: _http_ok(PORT), 10, "信令服务就绪"):
                print("FAIL: server 起不来"); sys.exit(1)

        host = launch(9222, "host",
                      f"{base}/host.html?fake=1&autostart=1&secret={secret}")
        procs.append(host)
        h_title = wait_for(lambda: (_t := title(9222)) and "H:ok:r" in _t and _t, 25, "host 开播")
        if not h_title:
            print(f"FAIL: host 未开播，title={title(9222)!r}"); sys.exit(1)
        room = h_title.split("r")[-1].strip()
        print(f"  房间号 {room}")

        viewer = launch(9223, "viewer",
                        f"{base}/viewer.html?fake=1&autostart=1&r={room}"
                        + ("&relay=1" if len(sys.argv) > 2 and sys.argv[2] == "relay" else ""))
        procs.append(viewer)

        v_ok = wait_for(lambda: title(9223) == "V:playing", 30, "viewer 收到视频流并在播放")
        h_live = wait_for(lambda: title(9222).startswith("H:live:v"), 10, "host 看到观众在线")
        h_audio = wait_for(lambda: ":A" in title(9222), 20, "host 收到观众回传音频")
        h_cam = wait_for(lambda: ":C" in title(9222), 25, "host 收到观众摄像头回传")

        print(f"\n  host   title = {title(9222)!r}")
        print(f"  viewer title = {title(9223)!r}")

        if v_ok and h_live and h_audio and h_cam:
            print("\nPASS：信令、建连、视频传输、音频回传、摄像头回传全链路通了")
            sys.exit(0)
        elif v_ok and h_live and h_audio and not h_cam:
            print("\nFAIL：音频通了但摄像头回传不通（重点查观众端 cam 链路与 host 端 renegotiate/ontrack）")
            sys.exit(1)
        elif v_ok and h_live and not h_audio:
            print("\nFAIL：视频通但音频回传不通（重点查观众端 mic track 与 host 端 ontrack）")
            sys.exit(1)
        else:
            print("\nFAIL：见上方 title 状态")
            sys.exit(1)
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        subprocess.run(["pkill", "-f", "ssl-e2e-"], capture_output=True)


def _http_ok(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=2)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
