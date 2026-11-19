"""收息佬本地服务(只用标准库)。  python app.py
本机:http://127.0.0.1:8890   局域网内的手机/电脑:http://<本机IP>:8890
只接受内网地址(192.168.x.x / 10.x.x.x / 172.16-31.x.x / 本机)的访问;可用 passcode.py 加访问密码。
"""
import gzip
import hashlib
from html import escape as _esc
import hmac
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import datasrc
import fetch_data
from paths import ACCESS, DATA, HOLDINGS, HOME, VERSION, WEB, ensure_home, load_json

PORT_RANGE = range(8890, 8900)
_lock = threading.Lock()
_refresh = {"t": None}
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")


def read_json(path, default):
    return load_json(path, default)


# ---------------------------------------------------------------- 拼音(搜索用,pypinyin 缺失时跳过)
try:
    from pypinyin import Style, lazy_pinyin
except Exception:  # pragma: no cover
    lazy_pinyin = None
_py = {}


def pinyin_of(name):
    if name not in _py:
        if lazy_pinyin is None:
            _py[name] = ("", "")
        else:
            _py[name] = ("".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).lower(), "".join(lazy_pinyin(name)).lower())
    return _py[name]


# ---------------------------------------------------------------- 检查更新
# 读一个公开的 latest.json(只有版本号、更新说明、下载页),不上传任何用户数据;失败不影响使用。
UPDATE_URLS = ["https://cdn.jsdelivr.net/gh/Faithink/shouxi-update@main/latest.json",
               "https://raw.githubusercontent.com/Faithink/shouxi-update/main/latest.json"]
_upd = {"t": 0.0, "data": None}


def _vtuple(v):
    import re
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def check_update(force=False):
    now = time.time()
    if not force and _upd["data"] and now - _upd["t"] < 6 * 3600:
        return _upd["data"]
    urls = [os.environ["SHOUXI_UPDATE_URL"]] if os.environ.get("SHOUXI_UPDATE_URL") else UPDATE_URLS
    last = "无法连接更新服务器"
    for u in urls:
        try:
            j = datasrc.http_json(u, tries=1, wait=1, timeout=8)
            latest = str(j.get("version", "")).strip()
            if not latest:
                continue
            dl = str(j.get("download", "")).strip()
            if dl and not dl.startswith(("http://", "https://")):
                dl = ""
            notes = j.get("notes") or []
            res = {"current": VERSION, "latest": latest, "newer": VERSION != "dev" and _vtuple(latest) > _vtuple(VERSION),
                   "released": str(j.get("released", "")), "notes": [str(n) for n in notes][:8] if isinstance(notes, list) else [str(notes)],
                   "download": dl, "code": str(j.get("code", "")), "contact": str(j.get("contact", ""))}
            _upd.update(t=now, data=res)
            return res
        except Exception as e:
            last = "无法连接更新服务器（" + type(e).__name__ + "）"
    return {"current": VERSION, "error": last}


# ---------------------------------------------------------------- 局域网地址
def lan_urls(port):
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # 不会真的发包,只为拿到出口网卡的 IP
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    if not ips:   # 取不到出口网卡时才退回按主机名解析(虚拟机/容器的虚拟网卡地址手机访问不到,不再列出)
        try:
            ips += [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")][:1]
        except OSError:
            pass
    urls = [f"http://{ip}:{port}" for ip in ips if not ip.startswith("127.")]
    host = socket.gethostname()
    if host.endswith(".local"):
        urls.append(f"http://{host}:{port}")
    return urls


# ---------------------------------------------------------------- 登录页
OPEN_PATHS = {"/login", "/manifest.webmanifest", "/favicon.png", "/logo.png", "/apple-touch-icon.png",
              "/icon-192.png", "/icon-512.png"}   # 登录页和安装 webapp 需要的图标、清单不要求登录

LOGIN_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>收息佬 · 登录</title>
<link rel="icon" href="/favicon.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f3f5f8;font:16px -apple-system,"PingFang SC",sans-serif;color:#18202e}
@media(prefers-color-scheme:dark){body{background:#0f1319;color:#e8ecf2}input{background:#171d26;color:#e8ecf2;border-color:#283140!important}.c{background:#171d26!important;border-color:#283140!important}}
.c{width:min(340px,88vw);padding:28px 24px;background:#fff;border:1px solid #e6eaf0;border-radius:16px;text-align:center}
img{width:84px;height:84px;border-radius:20px;border:1px solid #e6eaf0;background:#fff}h1{font-size:22px;margin:10px 0 2px}p{margin:0 0 18px;color:#667085;font-size:13px}
input{width:100%;box-sizing:border-box;padding:12px;font-size:17px;border:1px solid #e6eaf0;border-radius:10px;text-align:center;letter-spacing:4px}
button{margin-top:12px;width:100%;padding:12px;font-size:16px;border:0;border-radius:10px;background:#0f9d75;color:#fff;font-weight:600}.e{color:#d92d20;font-size:13px;margin-top:10px;min-height:18px}</style></head>
<body><form class="c" method="post" action="/login"><img src="/logo.png" alt=""><h1>收息佬</h1><p>股息攒得好,退休晚不了</p>
<input type="password" name="passcode" placeholder="访问密码" autofocus autocomplete="current-password"><button>进入</button><div class="e">__ERR__</div></form></body></html>"""


def valid_code(code):
    return code.isascii() and code.isdigit() and len(code) in (5, 6)


def stock_codes():
    import io
    import csv
    rows = csv.DictReader(io.StringIO(fetch_data.read_text_any(fetch_data.STOCKS_CSV)))
    return {(r.get("code") or "").strip() for r in rows}


def lookup_name(code):
    """腾讯行情里查股票简称(A 股、B 股、ETF、港股都行);查不到返回空串"""
    try:
        req = urllib.request.Request(f"https://qt.gtimg.cn/q={datasrc._market(code)}", headers=datasrc.UA)
        with urllib.request.urlopen(req, timeout=10, context=datasrc._CTX) as r:
            parts = r.read().decode("gbk", "ignore").split("~")
        name = re.sub(r"^(XD|XR|DR|N|C)+(?=[\u4e00-\u9fa5])", "", parts[1].replace("\u3000", "").replace(" ", "")) if len(parts) > 3 else ""
        return name if name and parts[2].strip() == code else ""
    except Exception:
        return ""


BACKUP_DIR = HOME / "backups"
BACKUP_KEEP = 7                      # 保留最近 7 天(每天一份,当天多次保存只留最后一份)
_BK_NAME = re.compile(r"^holdings-\d{8}\.json$")
EXTRA_BACKUP = None                  # 安卓独立版会设成「同时写一份到下载文件夹」的函数:f(文件名, 字节)


def rolling_backup():
    """保存持仓后留一份按天的备份:holdings-YYYYMMDD.json,只留最近 BACKUP_KEEP 份。误删误改时可以在设置页恢复。"""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HOLDINGS, BACKUP_DIR / time.strftime("holdings-%Y%m%d.json"))
        for f in sorted(BACKUP_DIR.glob("holdings-*.json"))[:-BACKUP_KEEP]:
            f.unlink()
    except OSError:
        pass
    if EXTRA_BACKUP:
        try:
            EXTRA_BACKUP(time.strftime("收息佬自动备份-%Y%m%d.json"), HOLDINGS.read_bytes())
        except Exception as e:           # 额外备份失败不能影响正常保存
            print("extra backup failed:", e)


def list_backups():
    out = []
    for f in sorted(BACKUP_DIR.glob("holdings-*.json"), reverse=True) if BACKUP_DIR.exists() else []:
        if not _BK_NAME.match(f.name):
            continue
        d = read_json(f, None) or {}
        out.append({"name": f.name, "date": f.name[9:13] + "-" + f.name[13:15] + "-" + f.name[15:17], "size": f.stat().st_size,
                    "lots": len(d.get("lots") or []), "sells": len(d.get("sells") or []), "favorites": len((d.get("settings") or {}).get("favorites") or [])})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Shouxi"
    port = 8890

    def log_message(self, *a):   # 不在终端刷请求日志
        pass

    # ---- 基础响应 ----
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        # 文本类响应超过 1KB 且浏览器支持时压缩(页面 245KB、股票池 170KB,局域网/手机上能快很多)
        gz = (len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or "")
              and (ctype.startswith(("text/", "application/json", "application/manifest", "image/svg"))))
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200, headers=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers)

    def _not_found(self, path):
        """接口路径返回 JSON;其他路径(多半是手输地址不对)返回说明页,告诉用户地址要带端口"""
        if path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        url = "http://" + (self.headers.get("Host") or "127.0.0.1") + path
        body = NOT_FOUND_HTML.replace("__URL__", _esc(url[:200])).replace("__PORT__", str(self.port)).encode("utf-8")
        self._send(404, body, "text/html; charset=utf-8")

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n < 0 or n > MAX_BODY:       # 负数会让 read() 一直等到连接关闭;过大的请求体直接当空处理(随后按 bad json 拒绝)
            n = 0
        return self.rfile.read(n) if n else b""

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    # ---- 访问控制 ----
    def _authed(self):
        a = read_json(ACCESS, None)
        if not a:
            return True
        return hmac.compare_digest(self._cookie("sx"), a.get("hash", ""))

    def _guard(self, path):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            self._send(403, b"forbidden")
            return False
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):   # 只允许内网,防止被路由器端口映射暴露到公网
            self._send(403, "仅限局域网访问".encode())
            return False
        if path in OPEN_PATHS or self._authed():
            return True
        if path.startswith("/api/"):
            self._json({"error": "unauthorized"}, 401)
        else:
            self._send(302, b"", headers={"Location": "/login"})
        return False

    # ---- 路由 ----
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if not self._guard(path):
            return
        if path == "/login":
            if not read_json(ACCESS, None):
                return self._send(302, b"", headers={"Location": "/"})
            return self._send(200, LOGIN_HTML.replace("__ERR__", "").encode(), "text/html; charset=utf-8")
        if path == "/api/pool":
            d = read_json(DATA / "pool.json", {"updated": None, "stocks": []})
            for st in d["stocks"]:
                st["py"], st["pyfull"] = pinyin_of(st["name"])
            return self._json(d)
        if path.startswith("/api/stock/"):
            code = path.rsplit("/", 1)[-1]
            if not (code.isascii() and code.isdigit()):
                return self._json({"error": "bad code"}, 400)
            d = read_json(DATA / "stocks" / f"{code}.json", None)
            return self._json(d) if d else self._json({"error": "not found"}, 404)
        if path == "/api/lookup":      # 添加个股时按代码查名称
            code = (urllib.parse.parse_qs(url.query).get("code") or [""])[0].strip()
            if not valid_code(code):
                return self._json({"error": "代码格式不对：A 股、B 股、ETF 填 6 位，港股填 5 位（如 00941）"}, 400)
            name = lookup_name(code)
            if not name:
                return self._json({"error": "查不到这个代码，请核对后再试"}, 404)
            return self._json({"code": code, "name": name, "market": datasrc.kind(code), "ccy": datasrc.ccy_of(code),
                               "exists": code in stock_codes()})
        if path == "/api/holdings":
            return self._json(read_json(HOLDINGS, {"settings": {"capital": 0, "maxPct": 15}, "lots": []}))
        if path == "/api/backups":
            return self._json(list_backups())
        if path == "/api/missing":      # 已写入 stocks.csv 但没有数据(下载失败)的股票
            have = {x.get("code") for x in (read_json(DATA / "pool.json", None) or {}).get("stocks", [])}
            import csv, io
            rows = csv.DictReader(io.StringIO(fetch_data.read_text_any(fetch_data.STOCKS_CSV)))
            return self._json([{"code": r["code"], "name": r["name"], "industry": r["industry"]} for r in rows if r.get("code") not in have])
        if path == "/api/status":
            s = read_json(DATA / "status.json", {"running": False})
            t = _refresh["t"]
            s["running"] = bool(t and t.is_alive())
            return self._json(s)
        if path == "/api/version":
            return self._json({"version": VERSION, "sandbox": bool(os.environ.get("SHOUXI_HOME")) and Path(HOME).resolve() != Path(__file__).resolve().parent})
        if path == "/api/update":
            force = "force" in urllib.parse.parse_qs(url.query)
            return self._json(check_update(force))
        if path == "/api/access":
            return self._json({"enabled": ACCESS.exists(), "urls": lan_urls(self.port), "port": self.port})
        if path == "/api/qr":          # 设置页的手机二维码;只给内网地址生成,避免被拿来当通用二维码服务
            u = (urllib.parse.parse_qs(url.query).get("u") or [""])[0]
            pu = urllib.parse.urlparse(u)
            host = pu.hostname or ""
            try:
                ok = ipaddress.ip_address(host).is_private
            except ValueError:
                ok = host.endswith(".local")
            if pu.scheme != "http" or not ok or len(u) > 100:
                return self._json({"error": "bad url"}, 400)
            import io
            import segno
            buf = io.BytesIO()
            segno.make(u, error="m").save(buf, kind="svg", scale=5, border=1, xmldecl=False, svgns=True, dark="#1f2430", light="#ffffff")
            return self._send(200, buf.getvalue(), "image/svg+xml")
        return self._static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard(path):
            return
        if path == "/login":
            a = read_json(ACCESS, None)
            if not a:
                return self._send(302, b"", headers={"Location": "/"})
            form = urllib.parse.parse_qs(self._body().decode("utf-8", "ignore"))
            h = hashlib.sha256((a["salt"] + (form.get("passcode") or [""])[0]).encode()).hexdigest()
            if hmac.compare_digest(h, a["hash"]):
                return self._send(302, b"", headers={"Location": "/", "Set-Cookie": f"sx={h}; Max-Age=31536000; HttpOnly; SameSite=Lax; Path=/"})
            time.sleep(0.8)   # 拖慢暴力尝试
            return self._send(401, LOGIN_HTML.replace("__ERR__", "密码不对").encode(), "text/html; charset=utf-8")
        if path == "/api/passcode":
            try:
                pc = (json.loads(self._body() or b"{}").get("passcode") or "").strip()
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            if not pc:
                ACCESS.unlink(missing_ok=True)
                return self._json({"ok": True, "enabled": False}, headers={"Set-Cookie": "sx=; Max-Age=0; Path=/"})
            if len(pc) < 4:
                return self._json({"error": "密码至少 4 位"}, 400)
            salt = secrets.token_hex(8)
            h = hashlib.sha256((salt + pc).encode()).hexdigest()
            ACCESS.write_text(json.dumps({"salt": salt, "hash": h}), encoding="utf-8")
            return self._json({"ok": True, "enabled": True}, headers={"Set-Cookie": f"sx={h}; Max-Age=31536000; HttpOnly; SameSite=Lax; Path=/"})
        if path == "/api/stocks":
            try:
                body = json.loads(self._body() or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            code, industry = str(body.get("code", "")).strip(), str(body.get("industry", "")).strip()
            if not valid_code(code):
                return self._json({"error": "代码格式不对：A 股、B 股、ETF 填 6 位，港股填 5 位（如 00941）"}, 400)
            if not industry or any(c in industry for c in ",\n\r\""):
                return self._json({"error": "请选择行业"}, 400)
            t = _refresh["t"]
            if t and t.is_alive():
                return self._json({"error": "正在刷新数据，等刷新完再添加"}, 409)
            pool = read_json(DATA / "pool.json", None) or {}
            in_pool = any(x.get("code") == code for x in pool.get("stocks", []))
            if code in stock_codes() and in_pool:
                return self._json({"error": "这只股票已经在股票池里了"}, 409)
            name = str(body.get("name", "")).strip() or lookup_name(code)
            if not name or any(c in name for c in ",\n\r\""):
                return self._json({"error": "查不到这个代码，请核对后再试"}, 404)
            if code not in stock_codes():       # 已在 stocks.csv 但上次下载失败(不在股票池):只重试下载,不重复写入
                with _lock:
                    text = fetch_data.read_text_any(fetch_data.STOCKS_CSV)
                    if text and not text.endswith("\n"):
                        text += "\n"
                    # 整体重写为 UTF-8:原文件若是 GBK,直接追加会形成混合编码
                    fetch_data.STOCKS_CSV.write_text(text + f"{code},{name},{industry}\n", encoding="utf-8")
            _refresh["t"] = threading.Thread(target=lambda: fetch_data.run(only={code}, log=lambda s: None), daemon=True)
            _refresh["t"].start()
            return self._json({"started": True, "code": code, "name": name})
        if path == "/api/backups/restore":
            try:
                name = str((json.loads(self._body() or b"{}") or {}).get("name", ""))
            except (ValueError, AttributeError):
                return self._json({"error": "bad json"}, 400)
            f = BACKUP_DIR / name
            if not _BK_NAME.match(name) or not f.exists():
                return self._json({"error": "没有这份备份"}, 404)
            data = read_json(f, None)
            if not isinstance(data, dict):
                return self._json({"error": "备份文件损坏"}, 400)
            with _lock:
                if HOLDINGS.exists():
                    shutil.copyfile(HOLDINGS, HOLDINGS.with_suffix(".json.bak"))     # 恢复前的当前持仓也留一份
                shutil.copyfile(f, HOLDINGS)
            return self._json({"ok": True})
        if path == "/api/refresh":
            t = _refresh["t"]
            if t and t.is_alive():
                return self._json({"started": False, "msg": "已在刷新中"})
            try:
                mode = (json.loads(self._body() or b"{}") or {}).get("mode")
            except (ValueError, AttributeError):
                mode = None
            mode = "quick" if mode == "quick" else "full"
            _refresh["t"] = threading.Thread(target=lambda: fetch_data.run(log=lambda s: None, mode=mode), daemon=True)
            _refresh["t"].start()
            return self._json({"started": True, "mode": mode})
        self._send(404, b"not found")

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard(path):
            return
        if path.startswith("/api/stocks/"):
            code = path.rsplit("/", 1)[-1]
            t = _refresh["t"]
            if t and t.is_alive():
                return self._json({"error": "正在刷新数据，等刷新完再操作"}, 409)
            if not valid_code(code) or code not in stock_codes():
                return self._json({"error": "股票池里没有这只股票"}, 404)
            hd = read_json(HOLDINGS, None) or {}
            if any(x.get("code") == code for x in (hd.get("lots") or []) + (hd.get("sells") or [])):
                return self._json({"error": "你的持仓里还有这只股票的记录，请先在「我的持仓」里删除相关记录，再移出股票池"}, 409)
            with _lock:
                lines = fetch_data.read_text_any(fetch_data.STOCKS_CSV).splitlines()
                keep = [ln for i, ln in enumerate(lines) if i == 0 or ln.split(",")[0].strip().lstrip("\ufeff") != code]
                fetch_data.STOCKS_CSV.write_text("\n".join(keep) + "\n", encoding="utf-8")
                pf = DATA / "pool.json"
                pool = read_json(pf, None)
                if pool:
                    pool["stocks"] = [x for x in pool.get("stocks", []) if x.get("code") != code]
                    pf.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
                for sub in ("stocks", "cache"):
                    (DATA / sub / f"{code}.json").unlink(missing_ok=True)
            return self._json({"ok": True})
        self._send(404, b"not found")

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard(path):
            return
        if path == "/api/holdings":
            try:
                body = json.loads(self._body())
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            # 结构校验:必须是对象,买入/卖出记录必须是列表,否则前端读到会整页出错
            if (not isinstance(body, dict) or not isinstance(body.get("lots", []), list)
                    or not isinstance(body.get("sells", []), list) or not isinstance(body.get("divs", []), list)
                    or not isinstance(body.get("settings", {}), dict)):
                return self._json({"error": "持仓数据格式不对"}, 400)
            with _lock:
                HOLDINGS.parent.mkdir(parents=True, exist_ok=True)
                # 先写临时文件再替换,中途失败不会损坏原文件;替换前留一份 .bak
                tmp = HOLDINGS.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
                if HOLDINGS.exists():
                    shutil.copyfile(HOLDINGS, HOLDINGS.with_suffix(".json.bak"))
                os.replace(tmp, HOLDINGS)
                rolling_backup()
            return self._json({"ok": True})
        self._send(404, b"not found")

    def _static(self, path):
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        try:
            target = (WEB / rel).resolve()
        except (ValueError, OSError):
            return self._not_found(path)
        if WEB.resolve() not in target.parents and target != WEB.resolve() / "index.html":
            return self._not_found(path)
        try:
            is_file = target.is_file()
        except OSError:                 # Linux 上超长文件名会抛 ENAMETOOLONG,当作不存在
            is_file = False
        if not is_file:
            return self._not_found(path)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/manifest+json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


MAX_BODY = 8 * 1024 * 1024        # 请求体上限(持仓文件通常只有几十 KB)
NOT_FOUND_HTML = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>找不到这个页面 · 收息佬</title>
<style>:root{color-scheme:light dark}body{font:16px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:520px;margin:12vh auto;padding:0 20px;background:#f9f8f4;color:#1f2430}
@media(prefers-color-scheme:dark){body{background:#0c1018;color:#e3e8f2}}h1{font-size:22px;margin:0 0 12px}code{background:rgba(127,127,127,.18);padding:2px 8px;border-radius:6px;word-break:break-all}
.s{opacity:.7;font-size:14px}a.b{display:inline-block;margin-top:12px;padding:9px 22px;border-radius:10px;background:#9a7229;color:#fff;text-decoration:none}</style>
<h1>找不到这个页面</h1><p>你访问的是 <code>__URL__</code>，收息佬里没有这个页面。</p>
<p>收息佬在这台电脑本机运行，正确的地址要<b>带端口号</b>：</p><p><code>http://127.0.0.1:__PORT__</code></p>
<p class="s">手输地址时别漏了最后的「:__PORT__」。不带端口的话，浏览器访问的是 80 端口，那里往往是电脑上别的程序，会显示它自己的 404。电脑右下角（Mac 在菜单栏）的收息佬图标里，点「打开收息佬」最省事。</p>
<a class="b" href="/">回到收息佬首页</a>"""


def _safe(fn):
    """请求处理里没捕获的异常(缺库、数据文件损坏等)返回 500,而不是直接断开连接让页面报"请检查网络"。"""
    def wrapper(self):
        try:
            return fn(self)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:
            try:
                self._json({"error": f"服务出错：{type(e).__name__}"}, 500)
            except Exception:
                pass
    return wrapper


for _m in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
    setattr(Handler, _m, _safe(getattr(Handler, _m)))


class Server(ThreadingHTTPServer):
    request_queue_size = 128        # 默认只有 5:页面一次并发十几个请求(手机、多标签)时,多出来的连接会被直接重置
    daemon_threads = True


def pick_port():
    want = int(os.environ.get("SHOUXI_PORT") or 0)
    for p in ([want] if want else PORT_RANGE):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # 刚关掉的服务留下的 TIME_WAIT 不算占用
        try:
            s.bind((os.environ.get("SHOUXI_BIND", "0.0.0.0"), p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise SystemExit("8890~8899 端口都被占用了")


def start():
    """建好数据目录并绑定端口,返回 (服务对象, 端口);调用方负责 serve_forever()。"""
    ensure_home()
    port = pick_port()
    Handler.port = port
    srv = Server((os.environ.get("SHOUXI_BIND", "0.0.0.0"), port), Handler)
    srv.daemon_threads = True
    (HOME / "server.port").write_text(str(port), encoding="utf-8")
    return srv, port


def main():
    srv, port = start()
    if os.environ.get("SHOUXI_WATCH_PARENT"):   # 由菜单栏程序启动时:它不在了就跟着退出
        def _watch():
            while True:
                time.sleep(2)
                if os.getppid() == 1:
                    os._exit(0)
        threading.Thread(target=_watch, daemon=True).start()
    print("本机:  http://127.0.0.1:%d" % port, flush=True)
    for u in lan_urls(port):
        print("局域网: " + u, flush=True)
    print("访问密码:", "已设置" if ACCESS.exists() else "未设置(同一 WiFi 下的人都能看到你的持仓;可用 passcode.py 设置)", flush=True)
    print("数据目录:", HOME, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
