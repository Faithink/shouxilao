"""生成网页版(PWA):把 web/ + 每天更新的数据快照打成纯静态文件,放在静态站点上就能在手机浏览器里用,
"添加到主屏幕"后像 App 一样打开。持仓只存在用户自己的浏览器里。
用法: python tools/build_pwa.py [输出目录,默认 site-app]
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "site-app")
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(ROOT / "web", out)

sys.path.insert(0, str(ROOT))
import app  # noqa: E402  只用它的拼音函数(搜索支持拼音缩写)

d = ROOT / "data"
pool = json.loads((d / "pool.json").read_text(encoding="utf-8"))
for st in pool["stocks"]:
    st["py"], st["pyfull"] = app.pinyin_of(st["name"])
data = out / "data"
(data / "stocks").mkdir(parents=True)
(data / "pool.json").write_text(json.dumps(pool, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
for f in (d / "stocks").glob("*.json"):
    shutil.copy(f, data / "stocks" / f.name)
ver = (ROOT / "VERSION").read_text().strip()
(data / "version.json").write_text(json.dumps({"version": ver, "updated": pool.get("updated", "")}), encoding="utf-8")

shutil.copy(ROOT / "tools/demo/pwa.js", out / "pwa.js")
(out / "sw.js").write_text((ROOT / "tools/demo/sw.js").read_text(encoding="utf-8").replace("__VER__", ver + "-" + (pool.get("updated") or "").replace(" ", "").replace(":", "").replace("-", "")), encoding="utf-8")

html = (out / "index.html").read_text(encoding="utf-8")
html = re.sub(r'(href|src)="/(?!/)', r'\1="./', html)
html = re.sub(r'srcset="([^"]*)"', lambda m: 'srcset="' + re.sub(r'(^|,\s*)/(?!/)', r'\1./', m.group(1)) + '"', html)
html = html.replace("<head>", '<head>\n<script src="./pwa.js"></script>', 1)
(out / "index.html").write_text(html, encoding="utf-8")
m = out / "manifest.webmanifest"
m.write_text(m.read_text(encoding="utf-8").replace('"start_url": "/"', '"start_url": "./"').replace('"scope": "/"', '"scope": "./"').replace('"/icon-', '"./icon-'), encoding="utf-8")
(out / ".nojekyll").write_text("")
print("网页版已生成:", out, f"({len(pool['stocks'])} 只股票, 数据截至 {pool.get('updated')})")
