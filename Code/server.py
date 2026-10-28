
import argparse
import csv
import json
import platform
import re
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 8000
HERE = Path(__file__).parent
LOG_FILE = HERE / "log.csv"

history = []   # mỗi phần tử: {"t", "id", "rssi"}
MAX_HISTORY = 2000


lock = threading.Lock()


def add_sample(dev, rssi):
    """Luu 1 mau RSSI (dung chung cho thiet bi gui qua HTTP va cho chinh laptop nay)."""
    row = {"t": time.time(), "id": dev, "rssi": rssi}
    with lock:
        history.append(row)
        del history[:-MAX_HISTORY]
        new_file = not LOG_FILE.exists()
        with open(LOG_FILE, "a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "id", "rssi"])
            w.writerow([f"{row['t']:.2f}", dev, rssi])
    print(f"{dev}: {rssi} dBm")


# ---------- Doc RSSI WiFi cua chinh laptop nay ----------
def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout


def parse_windows(text):
    m = re.search(r"Rssi\s*:\s*(-?\d+)", text, re.I)      # Windows 11 moi co dong Rssi
    if m:
        return int(m.group(1))
    m = re.search(r":\s*(\d+)\s*%", text)                  # cu hon: chi co Signal %
    return round(int(m.group(1)) / 2 - 100) if m else None  # xap xi dBm = % / 2 - 100


def parse_linux(text):
    m = re.search(r"signal:\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


def parse_macos(text):
    m = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


def read_own_rssi():
    system = platform.system()
    if system == "Windows":
        return parse_windows(_run(["netsh", "wlan", "show", "interfaces"]))
    if system == "Darwin":
        out = _run(["system_profiler", "SPAirPortDataType"])
        return parse_macos(out.split("Other Local Wi-Fi Networks")[0])
    iface = re.search(r"Interface\s+(\S+)", _run(["iw", "dev"]))
    return parse_linux(_run(["iw", "dev", iface.group(1), "link"])) if iface else None


def anchor_loop(dev_id, interval, server_url=None):
    """Doc RSSI cua laptop nay moi `interval` giay. Co server_url thi gui qua HTTP, khong thi luu truc tiep."""
    while True:
        t0 = time.time()
        try:
            r = read_own_rssi()
            if r is None:
                print("Khong doc duoc RSSI: laptop co dang ket noi WiFi khong?")
            elif server_url:
                urllib.request.urlopen(f"{server_url}/rssi?id={dev_id}&rssi={r}", timeout=3).read()
                print(f"{dev_id}: {r} dBm")
            else:
                add_sample(dev_id, r)
        except Exception as e:
            print("Loi:", e)
        time.sleep(max(0, interval - (time.time() - t0)))


def local_ip():
    """Đoán IP của laptop trong mạng hotspot."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


SEND_PAGE = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gui RSSI</title>
<style>
 body{font:18px system-ui,sans-serif;margin:0;padding:20px;background:#f3f6f4;color:#14231c}
 label{display:block;margin-top:16px;font-size:15px;color:#5d6f66}
 input[type=text],input[type=number]{width:100%;font-size:28px;padding:10px;border:1px solid #bcc9c2;border-radius:10px}
 .row{display:flex;gap:10px;margin-top:10px}
 button{flex:1;font-size:26px;padding:16px;border:0;border-radius:10px;background:#0f6b4f;color:#fff}
 button.alt{background:#5d6f66}
 #msg{margin-top:16px;min-height:2em;color:#0f6b4f}
 #msg.err{color:#d6342c}
</style></head><body>
<h2>Gui RSSI ve laptop</h2>
<label>Ten thiet bi (id)</label>
<input type="text" id="id" value="anchor1" autocapitalize="off" autocorrect="off">
<label>RSSI doc tu AirPort Utility (dBm, so am)</label>
<input type="number" id="rssi" value="-50" inputmode="numeric">
<div class="row">
 <button class="alt" onclick="bump(-1)">-1</button>
 <button class="alt" onclick="bump(1)">+1</button>
</div>
<label><input type="checkbox" id="auto"> Tu dong gui lai moi giay (giu gia tri hien tai)</label>
<div class="row"><button onclick="send()">Gui</button></div>
<div id="msg"></div>
<script>
const $=id=>document.getElementById(id);
function bump(d){$("rssi").value=(parseInt($("rssi").value)||0)+d; if($("auto").checked) send();}
async function send(){
  const id=$("id").value.trim(), r=parseInt($("rssi").value);
  if(!id||isNaN(r)){$("msg").textContent="Nhap id va RSSI";$("msg").className="err";return;}
  try{
    const j=await (await fetch("/rssi?id="+encodeURIComponent(id)+"&rssi="+r)).json();
    $("msg").textContent=j.ok?("Da gui "+id+": "+r+" dBm luc "+new Date().toLocaleTimeString()):"Loi";
    $("msg").className=j.ok?"":"err";
  }catch(e){$("msg").textContent="Khong ket noi duoc laptop";$("msg").className="err";}
}
setInterval(()=>{if($("auto").checked) send();},1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)

        if url.path == "/":
            html = (HERE / "index.html").read_text(encoding="utf-8")
            self._send(200, html, "text/html")

        elif url.path == "/send":
            self._send(200, SEND_PAGE, "text/html")

        elif url.path == "/rssi":
            # Chap nhan "-52", "-52.5", "-52 dBm" (Phim tat cua iPhone co the tra ve dang chu)
            try:
                dev = q["id"][0]
                m = re.search(r"-?\d+(?:\.\d+)?", q["rssi"][0])
                rssi = round(float(m.group()))
                if rssi > 0:
                    rssi = -rssi          # RSSI luon am; neu nhan so duong thi doi dau
                if not -110 <= rssi <= 0:
                    raise ValueError
            except (KeyError, AttributeError, ValueError):
                self._send(400, json.dumps({"error": "can id va rssi hop le (vi du -52)"}))
                return
            add_sample(dev, rssi)
            self._send(200, json.dumps({"ok": True}))

        elif url.path == "/data":
            since = float(q.get("since", ["0"])[0])
            rows = [r for r in history if r["t"] > since]
            self._send(200, json.dumps({"now": time.time(), "rows": rows}))

        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass  # tắt log mặc định cho gọn


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", metavar="ID", help="laptop nay cung la anchor, vi du anchor1")
    ap.add_argument("--send", metavar="URL", help="chi gui RSSI toi server o may khac, vi du http://172.20.10.2:8000")
    ap.add_argument("--id", help="ten anchor khi dung --send")
    ap.add_argument("--interval", type=float, default=0.5, help="giay giua 2 lan do (mac dinh 0.5)")
    args = ap.parse_args()

    if args.send:                                   # che do chi gui
        if not args.id:
            ap.error("--send can di kem --id")
        print(f"Gui RSSI cua '{args.id}' toi {args.send} (Ctrl+C de dung)")
        anchor_loop(args.id, args.interval, args.send.rstrip("/"))
    else:                                           # che do server
        ip = local_ip()
        print(f"Mo trinh duyet:  http://localhost:{PORT}")
        print(f"Dien thoai gui toi: http://{ip}:{PORT}/rssi?id=anchor1&rssi=-55")
        print(f"iPhone nhap tay: http://{ip}:{PORT}/send")
        print(f"Laptop khac gui: python server.py --send http://{ip}:{PORT} --id anchor2")
        if args.anchor:
            threading.Thread(target=anchor_loop, args=(args.anchor, args.interval), daemon=True).start()
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
