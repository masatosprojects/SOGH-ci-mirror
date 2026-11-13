"""Read-only local status API for the Raspberry Pi.

Scope (G3): only what the Pi itself can measure; every other device and the M1 status are reported as
NOT_OBSERVED / UNVERIFIED so the display never implies something that was not measured.
Binds to loopback only. No write endpoints. No SOGH database, no real applicant data, no model.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCHEMA_VERSION = "sogh-pi-state/0.2"
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _ntp_synced() -> bool | None:
    """True/False when systemd-timesyncd reports it; None when the source is not available (e.g. not on a Pi)."""
    if not Path("/run/systemd/timesync").exists():
        return None
    return Path("/run/systemd/timesync/synchronized").exists()


def _port_open(port: int) -> bool | None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _sd_written_mib(diskstats: str | None = None, device: str = "mmcblk0") -> float | None:
    """MiB written to the SD card since boot, from /proc/diskstats (sectors written x 512). None when the device or the file is not available (never a guess)."""
    text = diskstats if diskstats is not None else _read("/proc/diskstats")
    if not text:
        return None
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 10 and f[2] == device:
            try:
                return round(int(f[9]) * 512 / 2**20, 1)
            except ValueError:
                return None
    return None


def measure_pi() -> dict:
    """Measurements the Pi can take about itself. Missing sources give None (never a guess)."""
    temp_raw = _read("/sys/class/thermal/thermal_zone0/temp")
    mem = {}
    meminfo = _read("/proc/meminfo")
    if meminfo:
        for line in meminfo.splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.strip().split()[0]) // 1024  # MiB
    up = _read("/proc/uptime")
    load = _read("/proc/loadavg")
    usage = shutil.disk_usage("/")
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": int(float(up.split()[0])) if up else None,
        "loadavg_1_5_15": [float(x) for x in load.split()[:3]] if load else None,
        "cpu_temp_c": round(int(temp_raw) / 1000, 1) if temp_raw and temp_raw.lstrip("-").isdigit() else None,
        "mem_total_mib": mem.get("MemTotal"),
        "mem_available_mib": mem.get("MemAvailable"),
        "disk_root_total_gib": round(usage.total / 2**30, 1),
        "disk_root_free_gib": round(usage.free / 2**30, 1),
        "clock_is_ntp_synced": _ntp_synced(),
        "mem_used_percent": round(100 - 100 * mem["MemAvailable"] / mem["MemTotal"], 1) if mem.get("MemTotal") and mem.get("MemAvailable") is not None else None,
        "disk_root_used_percent": round(100 * (usage.total - usage.free) / usage.total, 1),
        "ssh_port_open": _port_open(22),
        "sd_written_mib_since_boot": _sd_written_mib(),
        "cpu_count": os.cpu_count(),
    }


def build_state(now: datetime | None = None, pi: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "data_class": "LOCAL_MEASUREMENT_ONLY",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "devices": {
            "pi": {"status": "OBSERVED", "measured_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "values": pi if pi is not None else measure_pi()},
            "gaming_pc": {"status": "NOT_OBSERVED", "note": "no link to this device is established"},
            "main_pc": {"status": "NOT_OBSERVED", "note": "no link to this device is established"},
        },
        "m1": {"status": "UNVERIFIED", "source": None, "checked_at_utc": None,
               "note": "the formal M1 status lives on GitHub; this service does not fetch it"},
        "authority": {"read_only": True, "formal_acceptance": False, "execution_authorized": False},
    }


INDEX_HTML = """<!doctype html>
<html lang="ja" translate="no"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="google" content="notranslate"><meta http-equiv="Content-Language" content="ja">
<title>SOGH オペレーションセンター（SOC）Pi ミニ版</title>
<style>
:root{color-scheme:dark;--bg:#0f1419;--card:#1a222b;--ok:#4cc38a;--warn:#e5a93d;--bad:#e5484d;--mute:#8b98a5;--tx:#e6edf3}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:20px/1.45 system-ui,"Noto Sans CJK JP",sans-serif;padding:18px 22px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:10px}
h1{font-size:26px;margin:0} .sub{color:var(--mute);font-size:15px}
#clock{font-size:40px;font-variant-numeric:tabular-nums;text-align:right;line-height:1.1} #date{font-size:16px;color:var(--mute);text-align:right}
#banner{padding:9px 14px;border-radius:8px;margin:8px 0 14px;font-weight:600;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.ok{background:#12301f;color:var(--ok)} .stale{background:#3a2a0b;color:var(--warn)} .err{background:#3a1416;color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}
.card{background:var(--card);border-radius:12px;padding:14px 16px;border-left:6px solid var(--mute)}
.card.obs{border-left-color:var(--ok)} .card.dim{opacity:.55} .card.wide{grid-column:1/-1}
.tag{display:inline-block;padding:2px 10px;border-radius:999px;background:#26323d;font-size:15px;margin-bottom:6px}
.row{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #243039;padding:3px 0}
.row .k{color:var(--mute);font-size:16px} .row .v{font-size:20px;text-align:right}
.good{color:var(--ok)} .caution{color:var(--warn)} .bad{color:var(--bad)}
canvas{width:100%;height:70px;display:block;margin-top:6px;background:#141b22;border-radius:6px}
.note{color:var(--mute);font-size:15px;margin-top:6px}
footer{margin-top:12px;color:var(--mute);font-size:15px}
</style></head><body>
<header>
 <div><h1>SOGH オペレーションセンター <span class="sub">SOC ／ Pi ミニ版</span></h1>
 <div class="sub">この画面は表示専用です。承認・実行・公開の権限はありません。</div></div>
 <div><div id="clock">--:--:--</div><div id="date"></div></div>
</header>
<div id="banner" class="stale"><span id="bmsg">取得中…</span><span id="bnext"></span></div>
<div class="grid" id="grid"></div>
<footer id="foot"></footer>
<script>
"use strict";
const REFRESH_SEC = 5;      // 画面が Pi に測り直しを依頼する間隔
const STALE_SEC = 30;       // この秒数を超えて更新できないと「古い可能性」に切り替える
const HIST_MAX = 120;       // 10 分ぶん（5 秒 x 120）
const TZ = "Asia/Tokyo";
const hist = {temp: [], load: []};
let lastOk = 0, nextAt = Date.now() + REFRESH_SEC*1000;
const fmtDT = new Intl.DateTimeFormat("ja-JP",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
const fmtT = new Intl.DateTimeFormat("ja-JP",{timeZone:TZ,hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
const fmtD = new Intl.DateTimeFormat("ja-JP",{timeZone:TZ,year:"numeric",month:"long",day:"numeric",weekday:"long"});
function jst(iso){ const d=new Date(iso); return isNaN(d)?"不明":fmtDT.format(d)+" JST"; }
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined) e.textContent=text; return e; }
function row(card,k,v,cls){ const r=el("div","row"); r.appendChild(el("span","k",k)); r.appendChild(el("span","v"+(cls?" "+cls:""),v===null||v===undefined?"不明":String(v))); card.appendChild(r); }
function dur(sec){ if(sec==null) return null; const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60); return (d?d+"日 ":"")+h+"時間 "+m+"分"; }
function level(v,warn,bad){ return v==null?"":(v>=bad?"bad":(v>=warn?"caution":"good")); }
function spark(cv, arr, lo, hi, color){
  const w=cv.width=(cv.clientWidth||300)*2, h=cv.height=140, ctx=cv.getContext("2d"); ctx.clearRect(0,0,w,h);
  if(arr.length<2) return; ctx.strokeStyle=color; ctx.lineWidth=3; ctx.beginPath();
  arr.forEach((v,i)=>{ const x=i*(w/(HIST_MAX-1)), y=h-8-(Math.min(Math.max(v,lo),hi)-lo)/(hi-lo)*(h-16); i?ctx.lineTo(x,y):ctx.moveTo(x,y); }); ctx.stroke();
}
function render(d, stale){
  const grid=document.getElementById("grid"); grid.replaceChildren();
  const pi=d.devices.pi, v=pi.values||{};
  const c=el("div","card "+(stale?"dim":"obs")); c.appendChild(el("span","tag","Raspberry Pi（実測）"));
  row(c,"ホスト名",v.hostname); row(c,"稼働時間",dur(v.uptime_seconds));
  row(c,"CPU 温度",v.cpu_temp_c==null?null:v.cpu_temp_c+" ℃",level(v.cpu_temp_c,70,80));
  row(c,"負荷（1/5/15分）",v.loadavg_1_5_15?v.loadavg_1_5_15.join(" / "):null,level(v.loadavg_1_5_15?v.loadavg_1_5_15[0]/(v.cpu_count||4)*100:null,70,100));
  row(c,"メモリ使用",v.mem_used_percent==null?null:v.mem_used_percent+" %（空き "+v.mem_available_mib+" MiB）",level(v.mem_used_percent,80,92));
  row(c,"ディスク使用",v.disk_root_used_percent==null?null:v.disk_root_used_percent+" %（空き "+v.disk_root_free_gib+" GiB）",level(v.disk_root_used_percent,80,92));
  row(c,"時計の同期（NTP）",v.clock_is_ntp_synced===true?"同期済み":(v.clock_is_ntp_synced===false?"未同期":"不明"),v.clock_is_ntp_synced===true?"good":(v.clock_is_ntp_synced===false?"caution":""));
  row(c,"SDカードへの書込（起動後）",v.sd_written_mib_since_boot==null?null:v.sd_written_mib_since_boot+" MiB");
  row(c,"SSH（22番）",v.ssh_port_open===true?"待受中":(v.ssh_port_open===false?"停止":"不明"));
  row(c,"測定時刻",jst(pi.measured_at_utc));
  grid.appendChild(c);
  const g=el("div","card "+(stale?"dim":"obs")); g.appendChild(el("span","tag","ここ 10 分の推移"));
  g.appendChild(el("div","k","CPU 温度（℃）")); const c1=el("canvas"); g.appendChild(c1);
  g.appendChild(el("div","k","負荷（1分平均）")); const c2=el("canvas"); g.appendChild(c2);
  grid.appendChild(g); spark(c1,hist.temp,20,90,"#e5a93d"); spark(c2,hist.load,0,4,"#4cc38a");
  for(const [name,label] of [["gaming_pc","ゲーミング PC"],["main_pc","メイン PC"]]){
    const cc=el("div","card dim"); cc.appendChild(el("span","tag",label));
    row(cc,"状態","未観測（接続なし）"); cc.appendChild(el("div","note","この機器との通信は未設定です（将来の連携は別の許可が必要）。")); grid.appendChild(cc);
  }
  const m=el("div","card dim"); m.appendChild(el("span","tag","M1（入試データベース）"));
  row(m,"状態","未確認"); m.appendChild(el("div","note","正式な状況は GitHub の master と Issue #199 にあります。この画面は取得しません。")); grid.appendChild(m);
  const h=el("div","card wide dim"); h.appendChild(el("span","tag","この画面の見方"));
  h.appendChild(el("div","note","更新は "+REFRESH_SEC+" 秒ごと。"+STALE_SEC+" 秒を超えて更新できないと上の帯が「古い可能性」（黄）、取得に失敗すると「取得失敗」（赤）に変わります。温度は 70℃ で黄、80℃ で赤。時刻は日本時間（JST）です。"));
  grid.appendChild(h);
}
async function tick(){
  const b=document.getElementById("banner"), msg=document.getElementById("bmsg");
  nextAt = Date.now() + REFRESH_SEC*1000;
  try{
    const r=await fetch("/state",{cache:"no-store"}); if(!r.ok) throw new Error("HTTP "+r.status);
    const d=await r.json(); lastOk=Date.now();
    const vals=d.devices.pi.values||{};
    if(vals.cpu_temp_c!=null){ hist.temp.push(vals.cpu_temp_c); if(hist.temp.length>HIST_MAX) hist.temp.shift(); }
    if(vals.loadavg_1_5_15){ hist.load.push(vals.loadavg_1_5_15[0]); if(hist.load.length>HIST_MAX) hist.load.shift(); }
    render(d,false);
    b.className="ok"; msg.textContent="最新（"+jst(d.generated_at_utc)+"）";
    document.getElementById("foot").textContent="データの種類："+d.data_class+" ／ 権限：読み取り専用 ／ 形式："+d.schema_version;
  }catch(e){
    const age=lastOk?Math.round((Date.now()-lastOk)/1000):null;
    const stale=age!==null && age<=STALE_SEC;
    b.className=stale?"stale":"err";
    msg.textContent=stale?"古い可能性：最終更新から "+age+" 秒（"+STALE_SEC+" 秒を超えると警告が赤になります）":"取得失敗：表示中の値は信用できません（"+e.message+"）";
    for(const c of document.querySelectorAll(".card")) c.classList.add("dim");
  }
}
function clock(){
  const n=new Date(); document.getElementById("clock").textContent=fmtT.format(n); document.getElementById("date").textContent=fmtD.format(n)+"（JST）";
  const s=Math.max(0,Math.round((nextAt-Date.now())/1000)); document.getElementById("bnext").textContent="次の更新まで "+s+" 秒";
}
tick(); setInterval(tick,REFRESH_SEC*1000); clock(); setInterval(clock,1000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "sogh-pi-state"

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self._send(200, {"ok": True, "schema_version": SCHEMA_VERSION})
        elif self.path == "/state":
            self._send(200, build_state())
        else:
            self._send(404, {"error": "not found"})

    def _no_write(self):
        try:  # drain a small body so the client sees the 405 instead of a reset connection
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            if n:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass
        self.close_connection = True
        self._send(405, {"error": "read-only service"})

    do_POST = do_PUT = do_DELETE = do_PATCH = _no_write  # noqa: N815

    def log_message(self, fmt, *args):  # keep stdout quiet; no request data in logs
        return


def make_server(host: str = "127.0.0.1", port: int = 8765) -> HTTPServer:
    if host not in LOOPBACK:
        raise ValueError(f"refusing to bind a non-loopback address: {host!r}")
    return HTTPServer((host, port), Handler)


def main() -> None:
    port = int(os.environ.get("SOGH_STATE_PORT", "8765"))
    srv = make_server("127.0.0.1", port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
