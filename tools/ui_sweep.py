"""前端全页扫描:用无头 Chromium 打开一个正在运行的收息佬(测试数据目录!),把所有页面走一遍,
检查脚本报错、页面出现 undefined/NaN、同一页面里重复的元素 id、手机宽度下文字溢出。
用法: pip install playwright && playwright install chromium
      SHOUXI_HOME=/tmp/shouxi-test SHOUXI_PORT=8897 SHOUXI_BIND=127.0.0.1 python app.py &
      python tools/ui_sweep.py http://127.0.0.1:8897
会写入测试持仓(PUT /api/holdings),不要对自己的数据目录跑。有问题时退出码为 1。
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8890").rstrip("/")

SAMPLE = {
    "settings": {"capital": 800000, "maxPct": 15, "guideHide": True, "favorites": ["600941", "601318", "00700", "000333"],
                 "overrides": {"000333": 6}, "removed": []},
    "lots": [
        {"id": "a1", "code": "600941", "date": "2025-02-01", "price": 88, "shares": 1000},
        {"id": "a3", "code": "601088", "date": "2024-03-15", "price": 27.5, "shares": 2000},
        {"id": "a4", "code": "601398", "date": "2025-08-05", "price": 6.1, "shares": 10000},
        {"id": "h1", "code": "00941", "date": "2025-04-02", "price": 73, "shares": 1000},
        {"id": "h2", "code": "01088", "date": "2024-03-01", "price": 20, "shares": 2000},
        {"id": "e1", "code": "563020", "date": "2025-05-01", "price": 1.1, "shares": 20000},
        {"id": "b1", "code": "900905", "date": "2025-06-01", "price": 0.5, "shares": 5000},
    ],
    "sells": [{"id": "s1", "code": "601088", "date": "2025-06-01", "price": 40, "shares": 500}],
    "divs": [{"id": "d1", "code": "600941", "date": "2025-07-10", "amount": 1234.5, "note": "测试"}],
}

JS = r"""
async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const probs = [];
  const dup = root => { const m = {}; root.querySelectorAll('[id]').forEach(e => m[e.id] = (m[e.id] || 0) + 1); return Object.entries(m).filter(([k, v]) => v > 1).map(([k]) => k) };
  const bad = t => (t.match(/undefined|NaN|Infinity|\[object|null%/g) || []);
  const chk = label => { const m = document.querySelector('#main'); const b = bad(m.innerText); if (b.length) probs.push([label, '坏文本', b.slice(0, 3).join()]); const d = dup(m); if (d.length) probs.push([label, '重复id', d.join()]) };
  const overflow = label => {
    const root = document.querySelector('#main'); let n = 0, ex = '';
    root.querySelectorAll('*').forEach(e => {
      if (e.closest('.tablewrap,svg,.chips,.tabbar,.zonebar,.ruler')) return;
      const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const r = e.getBoundingClientRect(); if (!r.width || !r.height) return;
      if (![...e.childNodes].some(x => x.nodeType === 3 && x.nodeValue.trim())) return;
      if (r.right > innerWidth + 1) { n++; ex = ex || e.className + ':' + e.textContent.trim().slice(0, 16) }
    });
    if (n) probs.push([label, '溢出屏幕', n + ' 处,如 ' + ex]);
  };
  // 所有个股详情
  for (const c of state.pool.stocks.map(s => s.code)) {
    location.hash = '#/stock/' + c; let ok = false;
    for (let k = 0; k < 60; k++) { await wait(40); const cr = document.querySelector('#main .crumb'); if (cr && cr.innerText.includes(c)) { ok = true; break } }
    if (!ok) { probs.push([c, '详情页未渲染']); continue }
    chk('stock ' + c);
  }
  // 股票池:市场 × 状态
  location.hash = '#/'; await wait(900);
  for (const mk of ['a', 'b', 'hk', '']) {
    document.querySelector('#mkseg [data-mk="' + mk + '"]')?.click(); await wait(250);
    for (const st of ['focus', 'pick', '', 's0', 's1', 's2', 's3', 's4']) { document.querySelector('.chip[data-st="' + st + '"]')?.click(); await wait(150); chk('pool ' + mk + '/' + st) }
  }
  // 持仓、课堂、设置
  for (const h of ['#/hold', '#/learn', '#/settings']) {
    location.hash = h; await wait(1200); document.querySelectorAll('#main details').forEach(d => d.open = true); await wait(200); chk(h); overflow(h);
  }
  for (const a of [...document.querySelectorAll('#toc .tdots a[data-lesson]')]) { location.hash = '#/learn'; await wait(300); a.click(); await wait(200); chk('learn ' + a.dataset.lesson) }
  return probs;
}
"""

with sync_playwright() as pw:
    br = pw.chromium.launch()
    errors, out = [], []
    for name, vp in (("桌面", {"width": 1280, "height": 900}), ("手机", {"width": 375, "height": 812})):
        ctx = br.new_context(viewport=vp)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e, n=name: errors.append((n, "pageerror", str(e)[:200])))
        pg.on("console", lambda m, n=name: errors.append((n, "console.error", m.text[:200])) if m.type == "error" else None)
        r = ctx.request.put(BASE + "/api/holdings", data=json.dumps(SAMPLE), headers={"Content-Type": "application/json"})
        assert r.ok, "保存测试持仓失败: %s" % r.status
        pg.goto(BASE + "/#/")
        pg.wait_for_selector("#main .ph", timeout=15000)
        probs = pg.evaluate(JS)
        out += [(name,) + tuple(p) for p in probs]
        ctx.close()
    br.close()

for e in errors + out:
    print("问题:", *e)
print("\n扫描完成:%d 个问题" % (len(errors) + len(out)))
sys.exit(1 if errors or out else 0)
