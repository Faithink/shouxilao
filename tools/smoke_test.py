"""后端冒烟 / 边界测试:对一个正在运行的收息佬服务发请求,检查接口、数据完整性、异常输入。
用法(务必用独立数据目录起测试服务,别拿你自己的数据测):
    SHOUXI_HOME=/tmp/shouxi-test SHOUXI_PORT=8897 SHOUXI_BIND=127.0.0.1 .venv/bin/python app.py &
    .venv/bin/python tools/smoke_test.py http://127.0.0.1:8897
会写入测试用的持仓数据(PUT /api/holdings)并设置/关闭访问密码,所以只能用在测试数据目录上。
退出码:有失败项为 1。
"""
import gzip
import http.client
import json
import sys
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8890").rstrip("/")
U = urllib.parse.urlparse(BASE)
fails, passed = [], 0


def req(method, path, body=None, headers=None, raw=False):
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=30)
    h = dict(headers or {})
    if body is not None and not isinstance(body, (bytes, bytearray)):
        body = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    hd = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    if not raw and hd.get("content-encoding") == "gzip":
        data = gzip.decompress(data)
    return r.status, hd, data


def js(data):
    bad = []
    d = json.loads(data.decode("utf-8"), parse_constant=lambda x: bad.append(x) or 0)
    if bad:
        raise ValueError("JSON 里有 NaN/Infinity: %s" % bad[:2])
    return d


def check(name, cond, extra=""):
    global passed
    if cond:
        passed += 1
    else:
        fails.append(name + (" — " + str(extra) if extra else ""))
        print("FAIL", name, extra)


# ---------- 基础 ----------
s, h, d = req("GET", "/")
check("首页 200", s == 200 and "text/html" in h.get("content-type", ""), s)
s2, h2, d2 = req("GET", "/", headers={"Accept-Encoding": "gzip"}, raw=True)
check("首页支持 gzip", h2.get("content-encoding") == "gzip" and gzip.decompress(d2) == d, h2.get("content-encoding"))
s, h, d = req("HEAD", "/")
check("HEAD 首页", s == 200 and d == b"", s)
s, h, d = req("GET", "/api/version")
check("版本接口", s == 200 and js(d).get("version"), d[:80])
s, h, d = req("GET", "/changelog.md")
check("更新说明", s == 200 and "收息佬" in d.decode("utf-8"), s)
for p in ("/favicon.png", "/logo.png", "/logo-sm.png", "/logo-sm@2x.png", "/logo-sm-dark.png", "/logo-full.webp", "/logo-full-dark.webp",
          "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"):
    s, h, d = req("GET", p)
    check("静态资源 " + p, s == 200 and len(d) > 100, s)

# ---------- 股票池与详情 ----------
s, h, d = req("GET", "/api/pool")
pool = js(d)
stocks = pool["stocks"]
check("股票池非空", len(stocks) > 100, len(stocks))
check("股票池带拼音", all("py" in x and "pyfull" in x for x in stocks))


def one(code):
    s, h, d = req("GET", "/api/stock/" + code)
    if s != 200:
        return code, "HTTP %s" % s
    try:
        det = js(d)
    except Exception as e:
        return code, str(e)
    miss = [k for k in ("code", "name", "price", "zones", "annual", "monthly", "yield_series", "records", "forward", "ret") if k not in det]
    return code, ("缺字段 %s" % miss) if miss else None


with ThreadPoolExecutor(8) as ex:
    bad = [r for r in ex.map(one, [x["code"] for x in stocks]) if r[1]]
check("全部个股详情完整且无 NaN(%d 只)" % len(stocks), not bad, bad[:5])

# ---------- 错误和异常输入 ----------
for path, want, nm in (("/zzz", 404, "未知页面"), ("/api/zzz", 404, "未知接口"), ("/api/stock/abc", 400, "非法代码"), ("/api/stock/999999", 404, "不存在的股票"),
                       ("/api/stock/%C2%B2%C2%B2", 400, "非 ASCII 数字代码"), ("/api/lookup?code=abc", 400, "查询非法代码"), ("/api/lookup", 400, "查询空代码")):
    s, h, d = req("GET", path)
    check(nm, s == want, s)
s, h, d = req("GET", "/zzz")
check("未知页面返回说明页", "text/html" in h.get("content-type", "") and "端口" in d.decode("utf-8"))
s, h, d = req("GET", "/api/zzz")
check("未知接口返回 JSON", "json" in h.get("content-type", ""))
for path in ("/..%2f..%2fapp.py", "/%2e%2e/app.py", "/..%5capp.py", "//etc/passwd", "/web/../app.py", "/%00", "/a%00b", "/%zz", "/" + "a" * 8000):
    try:
        s, h, d = req("GET", path)
        leaked = b"import" in d and b"def " in d
        check("路径穿越/异常路径不泄露 " + path[:20], s in (400, 404) and not leaked, s)
    except Exception as e:
        check("异常路径不崩溃 " + path[:20], False, e)

# ---------- 持仓读写 ----------
good = {"settings": {"capital": 100000, "maxPct": 15, "favorites": ["600941"]}, "lots": [{"id": "t1", "code": "600941", "date": "2025-01-02", "price": 90, "shares": 100}], "sells": []}
s, h, d = req("PUT", "/api/holdings", good)
check("保存持仓", s == 200, d[:80])
s, h, d = req("GET", "/api/holdings")
check("读回持仓一致", s == 200 and js(d) == good)
for nm, body in (("非 JSON", b"not json"), ("非 UTF-8", b"\xff\xfe\x00"), ("数组", b"[1,2]"), ("lots 不是列表", b'{"lots":5}'), ("settings 不是对象", b'{"settings":[]}'), ("空体", b"")):
    s, h, d = req("PUT", "/api/holdings", body, {"Content-Type": "application/json"})
    check("拒绝坏持仓: " + nm, s == 400, s)
s, h, d = req("GET", "/api/holdings")
check("坏数据没有覆盖已保存的持仓", js(d) == good)
c = http.client.HTTPConnection(U.hostname, U.port, timeout=5)
try:
    c.putrequest("PUT", "/api/holdings")
    c.putheader("Content-Length", "-5")
    c.endheaders()
    r = c.getresponse()
    check("负 Content-Length 不会卡住", r.status in (400, 411), r.status)
except Exception as e:
    check("负 Content-Length 不会卡住", False, e)
finally:
    c.close()
req("PUT", "/api/holdings", {"settings": {"capital": 0, "maxPct": 15}, "lots": []})

# ---------- 个股管理接口 ----------
for nm, body, want in (("坏 JSON", b"xx", 400), ("非法代码", {"code": "12", "industry": "银行"}, 400), ("没有行业", {"code": "600941", "industry": ""}, 400),
                       ("已在池里", {"code": "600941", "name": "x", "industry": "通信"}, 409)):
    s, h, d = req("POST", "/api/stocks", body)
    check("添加个股:" + nm, s == want, (s, d[:60]))
s, h, d = req("DELETE", "/api/stocks/abc")
check("移出个股:非法代码", s in (400, 404), s)
s, h, d = req("DELETE", "/api/stocks/999999")
check("移出个股:不存在", s in (400, 404), s)
for p in ("/api/status", "/api/access", "/api/missing"):
    s, h, d = req("GET", p)
    check("接口 " + p, s == 200 and js(d) is not None, s)
s, h, d = req("GET", "/api/update")
check("检查更新接口不抛异常", s == 200 and isinstance(js(d), dict), s)
s, h, d = req("GET", "/api/qr?u=http://8.8.8.8:8890")
check("二维码只给内网地址", s == 400, s)

# ---------- 访问密码 ----------
s, h, d = req("POST", "/api/passcode", {"passcode": "ab"})
check("密码太短被拒绝", s == 400, s)
s, h, d = req("POST", "/api/passcode", {"passcode": "test1234"})
cookie = h.get("set-cookie", "").split(";")[0]
check("设置密码", s == 200 and cookie.startswith("sx="), s)
s, h, d = req("GET", "/api/pool")
check("有密码后未登录被拒", s == 401, s)
s, h, d = req("GET", "/api/pool", headers={"Cookie": cookie})
check("带正确 cookie 可访问", s == 200, s)
s, h, d = req("POST", "/login", b"passcode=wrong", {"Content-Type": "application/x-www-form-urlencoded"})
check("错误密码登录失败", s == 401, s)
s, h, d = req("POST", "/login", b"passcode=test1234", {"Content-Type": "application/x-www-form-urlencoded"})
check("正确密码登录成功", s == 302 and "sx=" in h.get("set-cookie", ""), s)
s, h, d = req("POST", "/api/passcode", {"passcode": ""}, {"Cookie": cookie})
check("关闭密码", s == 200, s)
s, h, d = req("GET", "/api/pool")
check("关闭密码后恢复访问", s == 200, s)

# ---------- 并发 ----------
res = []
lock = threading.Lock()


def hit(_):
    s, _, d = req("GET", "/api/pool")
    with lock:
        res.append(s)


with ThreadPoolExecutor(20) as ex:
    list(ex.map(hit, range(60)))
check("60 次并发请求全部成功", res.count(200) == 60, {k: res.count(k) for k in set(res)})

print("\n通过 %d 项,失败 %d 项" % (passed, len(fails)))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
