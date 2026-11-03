"""数据源:只用标准库请求三个公开接口,不依赖 pandas / numpy / akshare。

- 分红送配   东方财富数据中心 RPT_SHAREBONUS_DET
- 日线行情   腾讯财经 fqkline(JSON;单次最多 640 条,所以按 2 年分段)
- 财务摘要   新浪财经 getFinanceReport2022
"""
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # 没有 certifi 时用系统证书
    _CTX = ssl.create_default_context()

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


# 各站点两次请求之间的最小间隔(秒),避免被限流
_MIN_GAP = {"money.finance.sina.com.cn": 0.4, "web.ifzq.gtimg.cn": 0.6, "datacenter-web.eastmoney.com": 0.25, "quotes.sina.cn": 0.35, "push2his.eastmoney.com": 0.3}
_last_req = {}


def _throttle(url):
    host = urllib.parse.urlparse(url).netloc
    gap = _MIN_GAP.get(host, 0.0)
    wait = _last_req.get(host, 0.0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_req[host] = time.time()


def http_json(url, params=None, tries=5, wait=4.0, timeout=25):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",")
    err = None
    for i in range(tries):
        try:
            _throttle(url)
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 接口偶发断连/限流,退避重试
            err = e
            time.sleep(wait * (i + 1))
    raise err


def _date(s):
    """'2026-10-23 00:00:00' → date"""
    if not s or not isinstance(s, str):
        return None
    try:
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None


def _float(v):
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 2/29
        return d.replace(year=d.year + n, day=28)


def _native_fetch_dividends(code):
    """→ [{period, ex, reg, cash10, bonus10, eps, plan, progress}],按报告期升序。cash10 = 每10股派现(含税,元)。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"sortColumns": "REPORT_DATE", "sortTypes": "-1", "pageSize": "500", "pageNumber": "1",
              "reportName": "RPT_SHAREBONUS_DET", "columns": "ALL", "quoteColumns": "",
              "js": '{"data":(x),"pages":(tp)}', "source": "WEB", "client": "WEB",
              "filter": f'(SECURITY_CODE="{code}")'}
    rows, page = [], 1
    while True:
        params["pageNumber"] = str(page)
        res = (http_json(url, params) or {}).get("result") or {}
        rows += res.get("data") or []
        if page >= int(res.get("pages") or 1):
            break
        page += 1
    out = []
    for r in rows:
        plan, prog = r.get("IMPL_PLAN_PROFILE"), r.get("ASSIGN_PROGRESS")
        out.append({
            "period": _date(r.get("REPORT_DATE")), "ex": _date(r.get("EX_DIVIDEND_DATE")),
            "reg": _date(r.get("EQUITY_RECORD_DATE")),
            "cash10": _float(r.get("PRETAX_BONUS_RMB")) or 0.0, "bonus10": _float(r.get("BONUS_IT_RATIO")) or 0.0,
            "eps": _float(r.get("BASIC_EPS")),
            "plan": plan if isinstance(plan, str) else None, "progress": prog if isinstance(prog, str) else None,
        })
    out.sort(key=lambda x: (x["period"] is None, x["period"] or date.min))
    return out


def kind(code):
    """a = 沪深 A 股 / ETF;b = 沪深 B 股(200xxx/201xxx 深B、900xxx 沪B);hk = 港股(5 位代码)"""
    if len(code) == 5:
        return "hk"
    return "b" if code.startswith(("20", "900")) else "a"


def ccy_of(code):
    """交易币种:港股 = 港元;深 B = 港元;沪 B = 美元;其余人民币"""
    k = kind(code)
    return "HKD" if k == "hk" or code.startswith("20") else "USD" if k == "b" else "CNY"


_fx_cache = {}


def fx_rate(ccy):
    """1 单位该币种 = 多少人民币(新浪外汇;取不到时用近似值,只影响「折合人民币」的显示)"""
    if ccy == "CNY":
        return 1.0
    hit = _fx_cache.get(ccy)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    sym = {"HKD": "fx_shkdcny", "USD": "fx_susdcny"}[ccy]
    rate = {"HKD": 0.91, "USD": 7.1}[ccy]
    try:
        req = urllib.request.Request(f"https://hq.sinajs.cn/list={sym}", headers={**UA, "Referer": "https://finance.sina.com.cn"})
        with urllib.request.urlopen(req, timeout=10, context=_CTX) as r:
            parts = r.read().decode("gbk", "ignore").split('"')[1].split(",")
        v = float(parts[1])
        if 0.3 < v < 20:
            rate = v
    except Exception:
        pass
    _fx_cache[ccy] = (time.time(), rate)
    return rate


def _market(code):
    if kind(code) == "hk":
        return "hk" + code
    return ("sh" if code.startswith(("5", "6", "9")) else "bj" if code.startswith(("4", "8")) else "sz") + code


def _sina_prices(code, start, end):
    """新浪 JSON 日线(不复权):一次请求取回最近 N 条,不分段。"""
    n = min(3000, max(30, int((end - start).days * 0.72) + 15))
    j = http_json("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                  {"symbol": _market(code), "scale": "240", "ma": "no", "datalen": str(n)})
    out = [(_date(r["day"]), float(r["close"])) for r in j]
    if not out:
        raise ValueError("新浪日线为空")
    return sorted(x for x in out if start <= x[0] <= end)


_em_dead_until = 0.0     # 东方财富日线连续失败时,一段时间内不再尝试(否则每只港股/B 股都白等一分多钟)


def _em_prices(code, start, end):
    """东方财富日线(不复权):一次请求取回整段历史。港股、B 股用;腾讯偶尔会对港股返回 501 限流。"""
    k = kind(code)
    secid = f"116.{code}" if k == "hk" else (f"0.{code}" if code.startswith("20") else f"1.{code}")
    global _em_dead_until
    if time.time() < _em_dead_until:
        raise ValueError("东方财富日线暂不可用")
    try:
        j = http_json("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                      {"secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f53", "klt": "101", "fqt": "0",
                       "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d")}, tries=3, wait=3.0)
    except Exception:
        _em_dead_until = time.time() + 600
        raise
    out = []
    for row in ((j or {}).get("data") or {}).get("klines") or []:
        d_, c_ = row.split(",")[:2]
        out.append((_date(d_ + " 00:00:00"), float(c_)))
    if not out:
        raise ValueError("东方财富日线为空")
    return sorted(out)


def _native_fetch_prices(code, start, end, adjust=""):
    """日线收盘价 → [(date, close)] 升序。adjust: ''=不复权(新浪为主,失败时用腾讯),'hfq'=后复权(仅腾讯)。"""
    if adjust == "" and kind(code) != "hk":
        try:
            return _sina_prices(code, start, end)
        except Exception:
            pass
    if adjust == "" and kind(code) != "a":
        try:
            return _em_prices(code, start, end)
        except Exception:
            pass
    key = {"": "day", "hfq": "hfqday"}[adjust]
    sym, got, cur = _market(code), {}, start
    while cur <= end:
        nxt = min(add_years(cur, 2) - timedelta(days=1), end)
        j = http_json("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get", {"param": f"{sym},day,{cur},{nxt},640,{adjust}"})
        d = ((j or {}).get("data") or {}).get(sym) or {}
        for r in d.get(key) or d.get("day") or []:
            got[r[0]] = float(r[2])
        cur = nxt + timedelta(days=1)
    return sorted((_date(k), v) for k, v in got.items())


def fetch_etf_dividends(code):
    """ETF 分红:新浪的复权因子文件里有「累计每份分红」,相邻两期相减就是每期每份派息。
    返回和 fetch_dividends 同样的字典(cash10 = 每 10 份派现);日期取除息日。"""
    import re
    req = urllib.request.Request(f"https://finance.sina.com.cn/realstock/company/{_market(code)}/hfq.js", headers=UA)
    last = None
    for i in range(4):
        try:
            _throttle(req.full_url)
            with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
                text = r.read().decode("utf-8", "ignore")
            break
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    else:
        raise last
    m = re.search(r"=\s*(\{.*?\})\s*(?:/\*|$)", text, re.S)
    if not m:
        return []
    rows = json.loads(m.group(1)).get("data") or []
    pts = sorted((_date(r["d"] + " 00:00:00"), _float(r.get("u")) or 0.0) for r in rows if r.get("d", "") > "1900-01-01")
    out, prev = [], 0.0
    for d, cum in pts:
        per = round(cum - prev, 6)
        prev = cum
        if per > 0:
            out.append({"period": None, "ex": d, "reg": None, "cash10": per * 10, "bonus10": 0.0, "eps": None,
                        "plan": f"每份派 {per:.4f} 元", "progress": "实施分配"})
    return out


# B 股和同公司的 A 股共用财务报表(人民币):体检用 A 股代码取财务数据。沪 B 与 A 的代码没有规律,逐个对应;其余深 B 是 20xxxx→00xxxx、201xxx→001xxx。
B_TO_A = {"900905": "600612"}


def b_share_a_code(code):
    if code in B_TO_A:
        return B_TO_A[code]
    if code.startswith("200"):
        return "000" + code[3:]
    if code.startswith("201"):
        return "001" + code[3:]
    return None


def fetch_hk_finance(code):
    """港股财务指标:东方财富港股 F10「主要指标」。返回和 A 股 _native_fetch_finance 同样的 {指标名: {报告期: 数值}}。
    只支持 12 月财年、以港元计的公司(接口已把每股数据折成港元);其余抛错,体检就不显示(宁可不显示,不显示错的)。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_HKF10_FN_MAININDICATOR", "columns": "ALL", "filter": f'(SECURITY_CODE="{code}")',
              "pageSize": "60", "pageNumber": "1", "sortColumns": "REPORT_DATE", "sortTypes": "-1", "source": "WEB", "client": "WEB"}
    rows = ((http_json(url, params) or {}).get("result") or {}).get("data") or []
    if not rows:
        raise ValueError("没有港股财务数据")
    if any((r.get("FISCAL_YEAR") or "12-31") != "12-31" for r in rows):
        raise ValueError("非 12 月财年,暂不做体检")
    if any((r.get("CURRENCY") or "HKD") != "HKD" for r in rows):
        raise ValueError("财务数据币种不是港元,暂不做体检")
    cols = {"归母净利润": "HOLDER_PROFIT", "经营现金流量净额": "NETCASH_OPERATE", "基本每股收益": "BASIC_EPS", "每股净资产": "BPS",
            "每股经营现金流": "PER_NETCASH_OPERATE", "净资产收益率(ROE)": "ROE_AVG", "资产负债率": "DEBT_ASSET_RATIO"}
    out = {k: {} for k in cols}
    for r in rows:
        p = _date((r.get("REPORT_DATE") or "")[:10] + " 00:00:00")
        if not p:
            continue
        for k, c in cols.items():
            v = _float(r.get(c))
            if v is not None:
                out[k][p] = v
    if not out["基本每股收益"]:
        raise ValueError("没有每股收益数据")
    return out


def fetch_hk_dividends(code):
    """港股分红:东方财富港股 F10。方案文字里有「每股派港币 X 元」或「每股派人民币 X 元(相当于港币 Y 元)」,统一折成港币。
    返回格式同 fetch_dividends(cash10 = 每 10 股;币种 = 该股交易币种港元)。period 取 年度分配→当年 12-31,其余→6-30/9-30。"""
    import re
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_HKF10_MAIN_DIVBASIC", "columns": "ALL", "filter": f'(SECURITY_CODE="{code}")',
              "pageSize": "200", "pageNumber": "1", "sortColumns": "NOTICE_DATE", "sortTypes": "-1", "source": "WEB", "client": "WEB"}
    rows = ((http_json(url, params) or {}).get("result") or {}).get("data") or []
    out = []
    for r in rows:
        text = r.get("PLAN_EXPLAIN") or ""
        m = re.search(r"相当于港[币元]\s*([\d.]+)", text) or re.search(r"派(?:发)?(?:现金|股息)?港[币元]\s*([\d.]+)", text)
        amt = float(m.group(1)) if m else None
        if amt is None:                       # 只写人民币/美元:按汇率折成港元
            m = re.search(r"人民币\s*([\d.]+)", text)
            if m:
                amt = float(m.group(1)) * fx_rate("CNY") / fx_rate("HKD")
            else:
                m = re.search(r"美[元币]\s*([\d.]+)", text)
                if m:
                    amt = float(m.group(1)) * fx_rate("USD") / fx_rate("HKD")
        ex = _date((r.get("EX_DIVIDEND_DATE") or "").replace("/", "-") + " 00:00:00") if r.get("EX_DIVIDEND_DATE") else None
        if not amt or not ex:
            continue
        y = int(r.get("YEAR") or ex.year)
        typ = r.get("REPORT_TYPE") or ""
        period = date(y, 12, 31) if "年度" in typ else date(y, 6, 30) if "中期" in typ else date(y, 9, 30)
        out.append({"period": period, "ex": ex, "reg": None, "cash10": amt * 10, "bonus10": 0.0, "eps": None,
                    "plan": text or None, "progress": "实施分配"})
    out.sort(key=lambda x: x["ex"])
    return out


def fetch_b_dividends(code):
    """B 股分红:新浪「分红送配」页面(每 10 股派息,人民币,税前),按交易币种折算成港元/美元。"""
    import re
    url = f"https://money.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml"
    html = None
    for i in range(4):
        try:
            _throttle(url)
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25, context=_CTX) as r:
                html = r.read().decode("gbk", "ignore")
            break
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    if html is None:
        raise err
    k = fx_rate("CNY") / fx_rate(ccy_of(code))          # 1 元人民币 = k 单位交易币种
    i = html.find('id="sharebonus_1"')
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html[i:] if i >= 0 else html, re.S):
        c = [re.sub(r"<.*?>|\s+|&nbsp;", "", x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(c) < 8 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0]) or c[4] != "实施":
            continue
        ex, cash = _date(c[5] + " 00:00:00"), _float(c[3]) or 0.0
        bonus = (_float(c[1]) or 0.0) + (_float(c[2]) or 0.0)
        if not ex or (cash <= 0 and bonus <= 0):
            continue
        ann = _date(c[0] + " 00:00:00")
        period = date(ann.year - 1, 12, 31) if ann.month <= 6 else date(ann.year, 6, 30)
        out.append({"period": period, "ex": ex, "reg": _date(c[6] + " 00:00:00"), "cash10": cash * k, "bonus10": bonus, "eps": None,
                    "plan": f"每10股派 {cash:g} 元人民币" + (f"，送转 {bonus:g} 股" if bonus else ""), "progress": "实施分配"})
    out.sort(key=lambda x: x["ex"])
    return out


FIN_ITEMS = ("归母净利润", "经营现金流量净额", "基本每股收益", "每股净资产", "每股经营现金流", "净资产收益率(ROE)", "资产负债率")


def _native_fetch_finance(code):
    """→ {指标名: {报告期date: 数值}}(同名指标取第一次出现的,即「常用指标」那一组)"""
    j = http_json("https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
                  {"paperCode": f"sh{code}", "source": "gjzb", "type": "0", "page": "1", "num": "1000"})
    report_list = j["result"]["data"]["report_list"]
    out = {k: {} for k in FIN_ITEMS}
    for pk, rep in report_list.items():
        p = date(int(pk[:4]), int(pk[4:6]), int(pk[6:8]))
        seen = set()
        for it in rep.get("data") or []:
            t = it.get("item_title")
            if t in out and t not in seen:
                seen.add(t)
                v = _float(it.get("item_value"))
                if v is not None:
                    out[t][p] = v
    return out


# ---------------------------------------------------------------- akshare 后端
# 开发机装了 akshare 就优先用它(有人维护、接口改了会跟进);失败时退回上面自己写的请求。
# 打包给别人的 .app 不带 akshare,自动走自带的请求。SHOUXI_SOURCE=native 可强制不用 akshare。
import os

try:
    if os.environ.get("SHOUXI_SOURCE") == "native":
        raise ImportError
    import akshare as _ak
    import pandas as _pd
except Exception:
    _ak = None

SOURCE = "akshare" if _ak else "native"


def _ak_dividends(code):
    df = _ak.stock_fhps_detail_em(symbol=code)
    out = []
    for _, r in df.iterrows():
        def d(k):
            t = _pd.to_datetime(r.get(k), errors="coerce")
            return None if _pd.isna(t) else t.date()
        plan, prog = r.get("方案进度"), None
        out.append({
            "period": d("报告期"), "ex": d("除权除息日"), "reg": d("股权登记日"),
            "cash10": _float(r.get("现金分红-现金分红比例")) or 0.0,
            "bonus10": _float(r.get("送转股份-送转总比例")) or 0.0,
            "eps": _float(r.get("每股收益")),
            "plan": r.get("现金分红-现金分红比例描述") if isinstance(r.get("现金分红-现金分红比例描述"), str) else None,
            "progress": plan if isinstance(plan, str) else None,
        })
    out.sort(key=lambda x: (x["period"] is None, x["period"] or date.min))
    return out


def _ak_prices(code, start, end):
    df = _ak.stock_zh_a_daily(symbol=_market(code), start_date=start.strftime("%Y%m%d"),
                              end_date=end.strftime("%Y%m%d"), adjust="")
    out = [(_pd.to_datetime(r["date"]).date(), float(r["close"])) for _, r in df.iterrows()]
    if not out:
        raise ValueError("akshare 日线为空")
    return sorted(out)


def _ak_finance(code):
    a = _ak.stock_financial_abstract(symbol=code)
    out = {k: {} for k in FIN_ITEMS}
    for k in FIN_ITEMS:
        r = a[a["指标"] == k]
        if r.empty:
            continue
        r = r.iloc[0]
        for c in a.columns[2:]:
            v = _float(r[c])
            t = _pd.to_datetime(str(c), errors="coerce")
            if v is not None and not _pd.isna(t):
                out[k][t.date()] = v
    return out


def _with_fallback(ak_fn, native_fn):
    def run(*a, **kw):
        if _ak and kind(a[0]) == "a" and not (kw.get("adjust") or (len(a) > 3 and a[3])):
            for i in range(2):
                try:
                    return ak_fn(*a[:3] if ak_fn is _ak_prices else a)
                except Exception:
                    time.sleep(2)
        return native_fn(*a, **kw)
    return run


_a_dividends = _with_fallback(_ak_dividends, _native_fetch_dividends)


def fetch_dividends(code):
    k = kind(code)
    return fetch_hk_dividends(code) if k == "hk" else fetch_b_dividends(code) if k == "b" else _a_dividends(code)
fetch_prices = _with_fallback(_ak_prices, _native_fetch_prices)
fetch_finance = _with_fallback(_ak_finance, _native_fetch_finance)
