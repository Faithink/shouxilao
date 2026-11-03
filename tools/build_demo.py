"""生成在线演示站(GitHub Pages):把 web/ + 股票池快照 + 虚构持仓打成纯静态文件。
用法: python tools/build_demo.py [输出目录,默认 site]
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "site")
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(ROOT / "web", out)

import app  # noqa: E402  只用它的拼音函数(搜索支持拼音缩写)

d = ROOT / "data"
pool = json.loads((d / "pool.json").read_text(encoding="utf-8"))
for st in pool["stocks"]:
    st["py"], st["pyfull"] = app.pinyin_of(st["name"])
demo = out / "demo"
(demo / "stocks").mkdir(parents=True)
(demo / "pool.json").write_text(json.dumps(pool, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
for f in (d / "stocks").glob("*.json"):
    shutil.copy(f, demo / "stocks" / f.name)
shutil.copy(ROOT / "tools/demo/demo_holdings.json", demo / "holdings.json")
shutil.copy(ROOT / "tools/demo/demo.js", out / "demo.js")
(demo / "version.json").write_text(json.dumps({"version": (ROOT / "VERSION").read_text().strip(), "updated": pool.get("updated", "")}), encoding="utf-8")

# 页面里的绝对路径(/logo.png 等)改成相对路径,放在 github.io/<仓库名>/ 子目录下也能用
html = (out / "index.html").read_text(encoding="utf-8")
html = re.sub(r'(href|src)="/(?!/)', r'\1="./', html)
html = html.replace("<head>", '<head>\n<script src="./demo.js"></script>', 1)
(out / "index.html").write_text(html, encoding="utf-8")
m = (out / "manifest.webmanifest")
m.write_text(m.read_text(encoding="utf-8").replace('"start_url": "/"', '"start_url": "./"').replace('"scope": "/"', '"scope": "./"'), encoding="utf-8")
(out / ".nojekyll").write_text("")
print("演示站已生成:", out, f"({len(pool['stocks'])} 只股票)")
