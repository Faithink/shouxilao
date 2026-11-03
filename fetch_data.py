"""采集 A 股红利股数据并计算指标(纯标准库,不依赖 pandas / numpy / akshare)。

命令行:
    python fetch_data.py            # 全量刷新 stocks.csv 里的所有股票
    python fetch_data.py 601088     # 只刷新指定代码
也可被 app 以线程调用:run(only=None)。

输出(在 paths.DATA 下):
    pool.json            股票池汇总
    stocks/<code>.json   个股详情(分红明细、年度表、月度走势、公司体检)
    status.json          刷新进度
"""
import bisect
import csv
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta
from statistics import fmean, median

import datasrc
from datasrc import add_years
from paths import DATA, STOCKS_CSV, load_json, read_text_any

YEARS = 10


def get_today():
    return date.fromisoformat(os.environ["SHOUXI_TODAY"]) if os.environ.get("SHOUXI_TODAY") else date.today()


def write_status(**kw):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "status.json").write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 小工具
def pct_linear(vals, q):
    """与 numpy.percentile 默认(线性插值)一致。"""
    s = sorted(vals)
    n = len(s)
    if n == 1:
        return s[0]
    k = (n - 1) * q / 100.0
    f = math.floor(k)
    c = min(f + 1, n - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def month_last(dates, vals):
    """每个自然月取最后一个非空值 → [((年, 月), 值)](时间升序)"""
    out, order = {}, []
    for d, v in zip(dates, vals):
        if v is None:
            continue
        ym = (d.year, d.month)
        if ym not in out:
            order.append(ym)
        out[ym] = v
    return [(ym, out[ym]) for ym in order]


def ym_str(ym):
    return f"{ym[0]:04d}-{ym[1]:02d}"


def step_series(items, dates):
    """items: [(生效日, 值)] 升序 → 每个日期取已生效的最新值,没有则 None"""
    keys = [a for a, _ in items]
    out = []
    for d in dates:
        pos = bisect.bisect_right(keys, d)
        out.append(items[pos - 1][1] if pos > 0 else None)
    return out


# ------------------------------------------------------------------ 公司体检
FIN_IND = {"银行", "券商", "保险"}                 # 金融业:负债率、经营现金流不适用
INFRA_IND = {"电力", "交通", "公用事业"}   # 重资产公用事业:负债率天然偏高
CYC_IND = {"煤炭", "油气", "航运", "建材", "有色金属", "建筑"}  # 周期股:盈利波动大,估值用 PB


def avail_date(p):
    """财报披露截止日(避免用到当时还没公布的数据)"""
    return {3: date(p.year, 4, 30), 6: date(p.year, 8, 31), 9: date(p.year, 10, 31), 12: date(p.year + 1, 4, 30)}[p.month]


def compute_health(industry, px_dates, px_vals, price, fy_dps, fy_done, consec, splits, fin_raw, today):
    np_, ocf, eps = fin_raw["归母净利润"], fin_raw["经营现金流量净额"], fin_raw["基本每股收益"]
    bv, ocfps = fin_raw["每股净资产"], fin_raw["每股经营现金流"]
    roe, debt = fin_raw["净资产收益率(ROE)"], fin_raw["资产负债率"]
    is_fin = industry in FIN_IND

    # 年度指标(最近10个完整财年)
    years = sorted({d.year for d in list(np_) + list(roe) + list(eps) if d.month == 12 and d.year >= today.year - 10})
    fin = []
    for y in years:
        d, prev = date(y, 12, 31), date(y - 1, 12, 31)
        n, pn = np_.get(d), np_.get(prev)
        dps = fy_dps.get(y) if y in fy_done else None
        e, o = eps.get(d), ocfps.get(d)
        fin.append({
            "year": y, "np": n, "np_yoy": (n / pn - 1) if n is not None and pn and pn > 0 else None,
            "roe": roe.get(d), "debt": debt.get(d), "eps": e, "bvps": bv.get(d), "ocf_ps": o,
            "cash_conv": (ocf[d] / n) if d in ocf and n and n > 0 else None,
            "dps": dps, "payout": (dps / e) if dps and e and e > 0 else None,
            "cover": (o / dps) if o is not None and dps else None,
        })

    # 估值:TTM 每股收益 / 每股净资产 → PE、PB 及近5年分位
    ttm = {}
    for p, v in eps.items():
        if p.month == 12:
            ttm[p] = v
        else:
            pf, ps = date(p.year - 1, 12, 31), date(p.year - 1, p.month, p.day)
            if pf in eps and ps in eps:
                ttm[p] = v + eps[pf] - eps[ps]
    ttm_now = ttm[max(ttm)] if ttm else None
    bv_now = bv[max(bv)] if bv else None
    pe_now = price / ttm_now if ttm_now and ttm_now > 0 else None
    pb_now = price / bv_now if bv_now and bv_now > 0 else None
    # 同一披露截止日有多个报告期时(年报和一季报都是 4/30),以较新的报告期为准
    e_items = sorted(((avail_date(p), p, v) for p, v in ttm.items()))
    b_items = sorted(((avail_date(p), p, v) for p, v in bv.items()))
    e_s = step_series([(a, v) for a, _, v in e_items], px_dates)
    b_s = step_series([(a, v) for a, _, v in b_items], px_dates)
    pe_vals = [(p / e if e is not None and e > 0 else None) for p, e in zip(px_vals, e_s)]
    pb_vals = [(p / b if b is not None and b > 0 else None) for p, b in zip(px_vals, b_s)]
    lim5 = add_years(today, -5)
    split5 = any(s["ex"] > lim5 for s in splits)  # 期间有送转:历史 EPS 口径不一,分位不可靠

    def dist(vals, now):
        h = [(d, v) for d, v in zip(px_dates, vals) if d >= lim5 and v is not None]
        if now is None or split5 or len(h) < 250:
            return {"now": now, "pct": None, "med": None, "series": []}
        hv = [v for _, v in h]
        return {"now": now, "pct": sum(1 for v in hv if v < now) / len(hv), "med": float(median(hv)),
                "series": [[ym_str(ym), round(float(v), 2)] for ym, v in month_last([d for d, _ in h], hv)]}
    pe, pb = dist(pe_vals, pe_now), dist(pb_vals, pb_now)

    # ---- 五项红绿灯 ----
    ORD = {"g": 0, "y": 1, "r": 2}
    worst = lambda ls: max(ls, key=lambda x: ORD[x]) if ls else "na"
    last5 = fin[-5:]
    lights = {}

    # ① 分红能力:分红率、经营现金流覆盖
    cur = fin[-1] if fin else {}
    ls, tx = [], []
    if cur.get("payout") is not None:
        po = cur["payout"]; ls.append("g" if po <= 0.8 else "y" if po <= 1.0 else "r"); tx.append(f"分红率 {po:.0%}")
    covs = [r["cover"] for r in fin[-3:] if r["cover"] is not None]
    if not is_fin and covs:
        cv = fmean(covs); ls.append("g" if cv >= 1.5 else "y" if cv >= 1.0 else "r")
        tx.append(f"近3年经营现金流平均是分红的 {cv:.1f} 倍" + (f"(最近一年 {cur['cover']:.1f})" if cur.get("cover") is not None else ""))
    lights["div"] = {"lv": worst(ls), "head": f"分红率 {cur['payout']:.0%}" if cur.get("payout") is not None else "数据不足",
                     "text": ";".join(tx) + ("。分红率 ≤80% 为健康,>100% 为透支(分的比赚的多);现金流覆盖 ≥1.5 倍为稳。" if tx else "缺少分红率数据。")}

    # ② 盈利质量:ROE、利润下滑次数、利润含金量
    roes = [r["roe"] for r in last5 if r["roe"] is not None]
    yoys = [r["np_yoy"] for r in last5 if r["np_yoy"] is not None]
    downs = [y for y in yoys if y < -0.10]                    # 明显下滑:同比降超10%
    streak = mx = 0
    for y in yoys:
        streak = streak + 1 if y < 0 else 0; mx = max(mx, streak)  # 连续下滑年数
    crash = bool(yoys) and last5[-1]["np_yoy"] is not None and last5[-1]["np_yoy"] < -0.30
    ccs = [r["cash_conv"] for r in last5 if r["cash_conv"] is not None]
    ls, tx = [], []
    if roes:
        av = fmean(roes); g = 9 if is_fin else 10
        ls.append("g" if av >= g else "y" if av >= 6 else "r"); tx.append(f"近5年平均 ROE {av:.1f}%")
    if yoys:
        k = len(downs)
        ls.append("r" if crash or k >= 2 else "y" if k == 1 or mx >= 3 else "g")
        tx.append(f"净利润明显下滑(降超10%){k} 次" + (f",连续下滑 {mx} 年" if mx >= 2 else "") + (f";最近一年骤降 {last5[-1]['np_yoy']:.0%}" if crash else ""))
    if not is_fin and ccs:
        cc = fmean(ccs); ls.append("g" if cc >= 0.8 else "y" if cc >= 0.5 else "r"); tx.append(f"经营现金流/净利润 {cc:.1f}")
    lights["earn"] = {"lv": worst(ls), "head": f"ROE {fmean(roes):.1f}%" if roes else "数据不足",
                      "text": ";".join(tx) + ("。ROE ≥10%、利润少下滑、现金流能兑现利润为佳。" if tx else "缺少盈利数据。")}

    # ③ 分红稳定:近5年分红是否被砍、连续年数、是否含特别分红
    pairs = [(r["dps"], r["payout"]) for r in fin if r["dps"] is not None][-6:]
    ds = [p_[0] for p_ in pairs]
    # 上年分红率已超过 100%(分的比赚的多,属于特殊高分红年份)的,从它回落不算"被砍"
    is_cut = lambda i: ds[i] < ds[i - 1] * 0.9 and not (pairs[i - 1][1] is not None and pairs[i - 1][1] > 1.0)
    drops = [(ds[i] / ds[i - 1] - 1) for i in range(1, len(ds)) if is_cut(i)]
    special = len(ds) >= 4 and ds[-1] > 1.5 * fmean(ds[-4:-1])
    if ds:
        big = bool(drops) and min(drops) <= -0.25                     # 单次砍掉1/4以上
        back2 = len(ds) >= 3 and ds[-1] < ds[-2] * 0.9 and ds[-2] < ds[-3] * 0.9   # 最近两年连续下降超10%
        cut_red = big or len(drops) >= 3
        # 已恢复:最严重的那次下降发生在两年前,分红回到被砍前的水平,最近两年稳定,分红率正常 → 红灯降为黄灯
        recovered = False
        if drops:
            wi = min((i for i in range(1, len(ds)) if is_cut(i)), key=lambda i: ds[i] / ds[i - 1])
            stable2 = len(ds) >= 3 and ds[-1] >= ds[-2] * 0.9 and ds[-2] >= ds[-3] * 0.9
            pay_ok = cur.get("payout") is not None and cur["payout"] <= 1.0
            recovered = wi <= len(ds) - 3 and ds[-1] >= ds[wi - 1] * 0.95 and stable2 and pay_ok
        lv = "r" if (cut_red and not recovered) or back2 or consec < 3 else "y" if drops or special or consec < 5 else "g"
        tx = f"连续分红 {consec} 年;近5年分红下降 {len(drops)} 次" + (f"(最大 {min(drops):.0%})" if drops else "")
        if cut_red and recovered:
            tx += ";但已恢复到被砍前的水平,最近两年稳定,分红率正常"
        if special:
            tx += ";最近一年分红明显高于往年,可能含特别分红"
        lights["stab"] = {"lv": lv, "head": f"连续 {consec} 年",
                          "text": tx + "。每股分红较上年降超10%算一次下降(上年分红率超过100%的特殊高分红年份不算);单次降超25%、连续两年下降或降3次判红,已恢复且稳定的降为黄灯。"}
    else:
        lights["stab"] = {"lv": "na", "head": "数据不足", "text": "缺少分红数据。"}

    # ④ 财务安全:资产负债率(金融业不适用)
    dt = cur.get("debt")
    if is_fin:
        lights["safe"] = {"lv": "na", "head": "金融业", "text": "银行/保险的高负债是行业特点,不用资产负债率衡量。"}
    elif dt is not None:
        gy = (60, 75) if industry in INFRA_IND else (50, 70)
        lights["safe"] = {"lv": "g" if dt <= gy[0] else "y" if dt <= gy[1] else "r", "head": f"负债率 {dt:.0f}%",
                          "text": f"资产负债率 {dt:.1f}%。本行业参考:≤{gy[0]}% 稳健,>{gy[1]}% 偏高。"}
    else:
        lights["safe"] = {"lv": "na", "head": "数据不足", "text": "缺少负债数据。"}

    # ⑤ 估值:金融/周期看 PB,其余看 PE;与自身近5年比
    use_pb = is_fin or industry in CYC_IND
    m = pb if use_pb else pe
    nm = "PB" if use_pb else "PE"
    if not use_pb and pe_now is None and ttm_now is not None and ttm_now <= 0:
        lights["val"] = {"lv": "r", "head": "亏损", "text": "最近12个月每股收益为负,市盈率不可用。"}
    elif m["now"] is None:
        lights["val"] = {"lv": "na", "head": "数据不足", "text": "缺少估值数据。"}
    elif m["pct"] is None:
        lights["val"] = {"lv": "na", "head": f"{nm} {m['now']:.1f}", "text": f"{nm} {m['now']:.2f} 倍;期间有送转或数据不足,无法给出历史分位。"}
    else:
        pc = m["pct"]
        lights["val"] = {"lv": "g" if pc <= 0.4 else "y" if pc <= 0.75 else "r", "head": f"{nm} {m['now']:.1f}",
                         "text": f"{nm} {m['now']:.2f} 倍,高于自身近5年 {pc:.0%} 的时间(越低越便宜)"
                                 + ("。周期/金融股用 PB,避免景气高点 PE 虚低。" if use_pb else "。")}
    return {"fin": fin, "pe": pe, "pb": pb, "ttm_eps": ttm_now, "bvps": bv_now, "lights": lights,
            "basis": "PB" if use_pb else "PE", "is_fin": is_fin}


# ------------------------------------------------------------------ 日线缓存(不复权收盘价历史不会变,只需增量补最近几天)
def load_prices(code, start, today):
    cdir = DATA / "cache"
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / f"{code}.json"
    have = {}
    if path.exists():
        try:
            j = json.loads(path.read_text(encoding="utf-8"))
            have = {date(d // 10000, d // 100 % 100, d % 100): c for d, c in zip(j["d"], j["c"])}
        except Exception:
            have = {}
    fetch_from = max(start, max(have) - timedelta(days=20)) if have else start
    try:
        for d, v in datasrc.fetch_prices(code, fetch_from, today, ""):
            have[d] = v
    except Exception:
        if not have:
            raise            # 没有缓存又取不到,才算失败;有缓存就先用旧数据
    items = sorted((d, v) for d, v in have.items() if d >= start)
    path.write_text(json.dumps({"d": [d.year * 10000 + d.month * 100 + d.day for d, _ in items], "c": [v for _, v in items]}), encoding="utf-8")
    return items


# ------------------------------------------------------------------ 单只股票
def compute(code, name, industry, today):
    is_etf = industry == "ETF"
    mk = datasrc.kind(code)                 # a / b / hk
    rolling = is_etf or mk != "a"           # ETF、B 股、港股没有统一财年:分红基准用「最近 365 天已除息的分红合计」
    ccy = datasrc.ccy_of(code)
    div = datasrc.fetch_etf_dividends(code) if is_etf else datasrc.fetch_dividends(code)
    start = add_years(today, -(YEARS + 1))
    raw = load_prices(code, start, today)
    lim10 = add_years(today, -YEARS)
    series = [(d, v) for d, v in raw if d >= lim10]
    if not series:
        raise ValueError("没有行情数据")
    px_dates = [d for d, _ in series]
    px = [v for _, v in series]
    # 已实施(已除息)的现金分红事件
    events = sorted(((r["ex"], r["cash10"] / 10.0) for r in div if r["ex"] and r["ex"] <= today and r["cash10"] > 0))

    # 送转 + 分红事件(按除权除息日合并)
    splits = [r for r in div if r["ex"] and r["ex"] <= today and r["bonus10"] > 0]
    ev_by_ex = {}
    for r in div:
        if r["ex"] and r["ex"] <= today:
            e = ev_by_ex.setdefault(r["ex"], [0.0, 1.0])    # [每股现金分红, 送转倍数]
            e[0] += r["cash10"] / 10.0
            e[1] *= 1 + r["bonus10"] / 10.0
    ex_days = sorted(ev_by_ex)
    j = bisect.bisect_right(ex_days, px_dates[0])
    adj_px, tri = [px[0]], [px[0]]   # 价格指数(只含送转,不含现金分红) / 总回报指数(现金分红按除息日收盘价买回)
    for i in range(1, len(px)):
        cash, mult = 0.0, 1.0
        while j < len(ex_days) and ex_days[j] <= px_dates[i]:
            cash += ev_by_ex[ex_days[j]][0]
            mult *= ev_by_ex[ex_days[j]][1]
            j += 1
        adj_px.append(adj_px[-1] * (mult * px[i]) / px[i - 1])
        tri.append(tri[-1] * (mult * px[i] + cash) / px[i - 1])
    hfq = tri   # 下文沿用 hfq 这个名字表示总回报指数

    if rolling:
        # ETF、B 股、港股没有统一财年:每份分红基准 = 最近 365 天已除息的分红合计(滚动),历史不足一年的日期不算股息率
        exec_rows = [{"period": ex, "ex": ex, "cash10": c * 10} for ex, c in events]
        fy_dps, fy_done = {}, {}
        for ex, c in events:
            fy_dps[ex.year] = fy_dps.get(ex.year, 0.0) + c
        for y in fy_dps:
            if y < today.year:
                fy_done[y] = date(y, 12, 31)
        first_ex = events[0][0] if events else None
        base_year = None
        base = []
        for d in px_dates:
            if first_ex is None or d < first_ex + timedelta(days=365):
                base.append(None)
            else:
                lo = d - timedelta(days=365)
                s_ = sum(c for ex, c in events if lo < ex <= d)
                base.append(s_ if s_ > 0 else None)
        base3 = base
    else:
        # 每股分红基准:按"所属财年"(报告期)归集,取已分完的最近一个完整财年。
        # 不用"365天内除息合计",因为中期分红提前/推后会让窗口里出现3次分红,把股息率虚高。
        exec_rows = [r for r in div if r["ex"] and r["ex"] <= today and r["cash10"] > 0 and r["period"]]
        fy_dps = {}
        for r in exec_rows:
            fy_dps[r["period"].year] = fy_dps.get(r["period"].year, 0.0) + r["cash10"] / 10.0
        fy_done = {}
        for r in exec_rows:
            if r["period"].month == 12:
                y = r["period"].year
                fy_done[y] = max(fy_done.get(y, r["ex"]), r["ex"])  # 财年分完的日期=年度分红除息日
        steps = sorted((d, fy_dps[y], y) for y, d in fy_done.items())
        cd = [t[0] for t in steps]
        if steps:
            vals = [t[1] for t in steps]
            avgvals = [fmean(vals[max(0, i - 2):i + 1]) for i in range(len(steps))]
            base_year = steps[-1][2]
            base = step_series(list(zip(cd, vals)), px_dates)
            base3 = step_series(list(zip(cd, avgvals)), px_dates)
        else:
            base_year, base, base3 = None, [None] * len(px), [None] * len(px)
    yld = [(b / p if b is not None and b > 0 else None) for b, p in zip(base, px)]
    yld3 = [(b / p if b is not None and b > 0 else None) for b, p in zip(base3, px)]

    lim5 = add_years(today, -5)
    avg3_now = float(base3[-1]) if base3[-1] is not None else 0.0
    y3_5 = [v for d, v in zip(px_dates, yld3) if d >= lim5 and v is not None]
    zones_avg_y = {str(k): float(pct_linear(y3_5, k)) for k in (15, 30, 50, 70, 85)} if len(y3_5) > 100 and avg3_now > 0 else None
    yield_series_avg = [[ym_str(ym), round(float(v), 5)] for ym, v in month_last([d for d in px_dates if d >= lim5], [v for d, v in zip(px_dates, yld3) if d >= lim5])]

    last_date = px_dates[-1]
    price = float(px[-1])
    ttm_now = float(base[-1]) if base[-1] is not None else 0.0
    y_now = ttm_now / price if price else 0.0

    # 近5年股息率分布 → 买卖区间
    y5 = [v for d, v in zip(px_dates, yld) if d >= lim5 and v is not None]
    zones, pct_rank = None, None
    if len(y5) > 100 and ttm_now > 0:
        q = {k: float(pct_linear(y5, k)) for k in (15, 30, 50, 70, 85)}
        pct_rank = sum(1 for v in y5 if v < y_now) / len(y5)
        zones = {"heavy": ttm_now / q[85], "buy": ttm_now / q[70], "hold": ttm_now / q[30], "profit": ttm_now / q[15],
                 "y": {str(k): v for k, v in q.items()}}

    if zones is None:
        status = "无足够数据"
    elif price <= zones["heavy"]:
        status = "重仓区"      # 内部状态键(页面显示为「低位」)
    elif price <= zones["buy"]:
        status = "买入区"      # 偏低
    elif price <= zones["hold"]:
        status = "持有区"      # 适中
    elif price < zones["profit"]:
        status = "偏高"
    else:
        status = "止盈区"      # 高位

    # 年度表(按所属财年)
    annual, eps_year = [], {}
    for r in div:
        if r["period"] and r["period"].month == 12 and r["eps"] is not None:
            eps_year[r["period"].year] = float(r["eps"])
    for y in range(today.year - YEARS, today.year + 1):
        ye = [v for d, v in zip(px_dates, px) if d.year == y]
        if not ye:
            continue
        dps = fy_dps.get(y, 0.0)
        n = sum(1 for r in exec_rows if r["period"].year == y)
        close = float(ye[-1])
        payout = dps / eps_year[y] if y in eps_year and eps_year[y] > 0 and dps > 0 else None
        annual.append({"year": y, "dps": round(dps, 4), "n": n, "close": round(close, 2),
                       "yield": dps / close if close and dps else None, "payout": payout, "partial": y not in fy_done})

    # 连续分红年数(只数已完整的财年)
    consec = 0
    for a_ in reversed(annual):
        if a_["partial"]:
            continue
        if a_["dps"] > 0:
            consec += 1
        else:
            break

    # 未来12个月预计分红事件:每个分红期(中期/年度…)取最新一笔,已公告用公告日期,否则按去年同期顺延一年
    forward = []
    if rolling:
        # 已公告(除息日在未来)的方案优先;其余按去年同期顺延一年,但已有公告落在附近的就不再重复估算
        decl = sorted((r["ex"], r["cash10"] / 10.0) for r in div if r["ex"] and r["ex"] > today and r["cash10"] > 0)
        forward = [{"date": e.isoformat(), "cash": c, "declared": True} for e, c in decl]
        for e, c in events:
            if e > today - timedelta(days=365):
                nd = e + timedelta(days=365)
                if not any(abs((nd - x).days) <= 150 for x, _ in decl):
                    forward.append({"date": nd.isoformat(), "cash": c, "declared": False})
        forward.sort(key=lambda x: x["date"])
    elif base_year is not None:
        allrows = [r for r in div if r["cash10"] > 0 and r["period"]]
        months = {r["period"].month for r in exec_rows if r["period"].year == base_year}
        for m in sorted(months):
            rm = sorted((r for r in allrows if r["period"].month == m), key=lambda r: r["period"])
            last_r = rm[-1]
            declared = True
            if last_r["ex"] and last_r["ex"] > today:
                dt_ = last_r["ex"]
            elif last_r["ex"] is None:
                prev = [r for r in rm if r["ex"]]
                dt_ = prev[-1]["ex"] + timedelta(days=365) if prev else today + timedelta(days=90)
                while dt_ <= today:
                    dt_ += timedelta(days=365)
            else:
                dt_, declared = last_r["ex"] + timedelta(days=365), False
                while dt_ <= today:
                    dt_ += timedelta(days=365)
            forward.append({"date": dt_.isoformat(), "cash": float(last_r["cash10"]) / 10.0, "declared": declared})
        forward.sort(key=lambda f: f["date"])

    # 分红节奏:近3个完整日历年里,出现在>=2年的除息月份
    mcount = {}
    yrs = [today.year - 1, today.year - 2, today.year - 3]
    for y in yrs:
        for m in {d.month for d, _ in events if d.year == y}:
            mcount[m] = mcount.get(m, 0) + 1
    months_f = sorted(m for m, c in mcount.items() if c >= 2)
    per_year = [sum(1 for d, _ in events if d.year == y) for y in yrs]
    freq_n = int(median(per_year)) if per_year else 0
    freq_text = (f"年{freq_n}次 · " + "、".join(f"{m}月" for m in months_f)) if months_f else (f"年{freq_n}次" if freq_n else "无规律")

    # 收益:股价(送转调整) vs 含分红再投
    years_span = (px_dates[-1] - px_dates[0]).days / 365.25
    price_ret = float(adj_px[-1] / adj_px[0] - 1)
    tr_ret = float(hfq[-1] / hfq[0] - 1)
    cagr = lambda r: (1 + r) ** (1 / years_span) - 1 if years_span > 0 and r > -1 else None

    # DPS 增长
    dps_cagr = None
    full = [a for a in annual if not a["partial"] and a["dps"] > 0]
    if len(full) >= 3:
        a0, a1 = full[0], full[-1]
        n = a1["year"] - a0["year"]
        if n > 0:
            dps_cagr = (a1["dps"] / a0["dps"]) ** (1 / n) - 1

    # 月度走势(图表):送转调整价、后复权总回报、不复权收盘,均取每月最后一个交易日
    m_adj = month_last(px_dates, adj_px)
    m_hfq = dict(month_last(px_dates, hfq))
    m_raw = dict(month_last(px_dates, px))
    base_p, base_t = adj_px[0], hfq[0]
    monthly = [[ym_str(ym), round(float(p / base_p * 100), 2), round(float(m_hfq[ym] / base_t * 100), 2), round(float(m_raw[ym]), 2)]
               for ym, p in m_adj]

    # 近5年股息率月度序列
    yield_series = [[ym_str(ym), round(float(v), 5)] for ym, v in
                    month_last([d for d in px_dates if d >= lim5], [v for d, v in zip(px_dates, yld) if d >= lim5])]

    # 明细:分红记录 + 待实施预案
    records, pending = [], []
    for r in sorted(div, key=lambda r: (r["ex"] is None, -(r["ex"].toordinal()) if r["ex"] else 0)):
        if r["cash10"] <= 0 and r["bonus10"] <= 0:
            continue
        item = {"period": r["period"].isoformat() if r["period"] else None, "plan": r["plan"],
                "cash10": float(r["cash10"]), "bonus10": float(r["bonus10"]),
                "reg": r["reg"].isoformat() if r["reg"] else None, "ex": r["ex"].isoformat() if r["ex"] else None,
                "progress": r["progress"]}
        if r["ex"] is None or r["ex"] > today:
            if item["cash10"] > 0:
                pending.append(item)
        else:
            records.append(item)

    health = None
    if not rolling or (mk in ("hk", "b") and not is_etf):
        try:
            if mk == "hk":
                # 港股分红按所属财年归集(年度分配=上年财年的末期息,中期=当年上半年),和财务指标的财年对齐
                h_dps, h_done = {}, {}
                for r in div:
                    if r["ex"] and r["ex"] <= today and r["cash10"] > 0 and r["period"]:
                        y = r["period"].year
                        h_dps[y] = h_dps.get(y, 0.0) + r["cash10"] / 10.0
                        if r["period"].month == 12:
                            h_done[y] = r["ex"]          # 有末期息(年度分配)已除息 → 该财年分完
                for y in list(h_dps):
                    if y not in h_done and today >= date(y + 1, 7, 1):
                        h_done[y] = date(y + 1, 7, 1)    # 没有标成年度分配的(如按季派息),次年 6 月底后视为分完
                health = compute_health(industry, px_dates, px, price, h_dps, h_done, consec, splits, datasrc.fetch_hk_finance(code), today)
            elif mk == "b":
                # B 股:财务报表和分红(人民币)与同公司 A 股共用;价格按当前汇率折回人民币再算估值
                ac = datasrc.b_share_a_code(code)
                if not ac:
                    raise ValueError("找不到对应的 A 股代码")
                k = datasrc.fx_rate(ccy)
                b_dps, b_done = {}, {}
                for r in datasrc.fetch_dividends(ac):       # 同公司 A 股的分红记录:人民币,报告期归属准确
                    if r["ex"] and r["ex"] <= today and r["cash10"] > 0 and r["period"]:
                        y = r["period"].year
                        b_dps[y] = b_dps.get(y, 0.0) + r["cash10"] / 10.0
                        if r["period"].month == 12:
                            b_done[y] = r["ex"]
                for y in list(b_dps):
                    if y not in b_done and today >= date(y + 1, 7, 1):
                        b_done[y] = date(y + 1, 7, 1)
                health = compute_health(industry, px_dates, [v * k for v in px], price * k, b_dps, b_done, consec, splits, datasrc.fetch_finance(ac), today)
            else:
                health = compute_health(industry, px_dates, px, price, fy_dps, fy_done, consec, splits, datasrc.fetch_finance(code), today)
        except Exception as e:  # 财务数据取不到不影响分红主流程
            print("  health FAIL", code, str(e)[:80], flush=True)
            health = None

    detail = {
        "health": health, "code": code, "name": name, "industry": industry,
        "market": mk, "ccy": ccy, "fx": datasrc.fx_rate(ccy),
        "price": price, "date": last_date.isoformat(),
        "ttm_dps": ttm_now, "yield": y_now, "zones": zones, "status": status,
        "pct_rank": pct_rank, "freq": freq_text, "freq_n": freq_n, "months": months_f,
        "consec": consec, "annual": annual, "records": records, "pending": pending,
        "monthly": monthly, "yield_series": yield_series,
        "ret": {"years": years_span, "price": price_ret, "total": tr_ret,
                "price_cagr": cagr(price_ret), "total_cagr": cagr(tr_ret)},
        "dps_cagr": dps_cagr,
        "last_events": [[d.isoformat(), c] for d, c in events[-6:]],
        "forward": forward, "base_year": base_year,
        "avg3_dps": avg3_now, "zones_avg_y": zones_avg_y, "yield_series_avg": yield_series_avg,
    }
    (DATA / "stocks").mkdir(parents=True, exist_ok=True)
    (DATA / "stocks" / f"{code}.json").write_text(json.dumps(detail, ensure_ascii=False, default=float), encoding="utf-8")

    return {
        "code": code, "name": name, "industry": industry, "market": mk, "ccy": ccy, "fx": detail["fx"],
        "price": price, "date": detail["date"],
        "ttm_dps": ttm_now, "base_year": base_year, "avg3_dps": avg3_now, "zones_avg_y": zones_avg_y, "yield": y_now, "status": status,
        "pct_rank": pct_rank, "zones": zones, "freq": freq_text, "consec": consec,
        "lights": {k: v["lv"] for k, v in health["lights"].items()} if health else None,
        "total_cagr": detail["ret"]["total_cagr"], "price_cagr": detail["ret"]["price_cagr"],
        "dps_cagr": dps_cagr, "pending": len(pending),
    }


def run(only=None, log=print):
    """刷新股票池(only=代码集合时只刷新这些)。进度写到 status.json。"""
    today = get_today()
    only = set(only or [])
    DATA.mkdir(parents=True, exist_ok=True)
    import io
    rows = list(csv.DictReader(io.StringIO(read_text_any(STOCKS_CSV))))
    pool_file = DATA / "pool.json"
    old = {s["code"]: s for s in (load_json(pool_file, {}) or {}).get("stocks", [])}
    todo = [r for r in rows if not only or r["code"] in only]
    result, errors = dict(old), {}
    for i, r in enumerate(todo, 1):
        write_status(running=True, done=i - 1, total=len(todo), current=r["name"], errors=errors)
        try:
            result[r["code"]] = compute(r["code"], r["name"], r["industry"], today)
            log(f"[{i}/{len(todo)}] {r['code']} {r['name']} ok")
        except Exception as e:
            errors[r["code"]] = str(e)[:120]
            log(f"[{i}/{len(todo)}] {r['code']} {r['name']} FAIL {e}")
    order = [r["code"] for r in rows]
    stocks = [result[c] for c in order if c in result]
    pool_file.write_text(json.dumps({"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "stocks": stocks},
                                    ensure_ascii=False, default=float), encoding="utf-8")
    write_status(running=False, done=len(todo), total=len(todo), current="", errors=errors,
                 finished=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return errors


if __name__ == "__main__":
    run(sys.argv[1:], log=lambda s: print(s, flush=True))
