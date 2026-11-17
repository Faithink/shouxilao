"""检查 web/index.html 里主脚本的语法(需要 node)。CI 和本地都能跑:python tools/check_js.py"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")
js = max(re.findall(r"<script>([\s\S]*?)</script>", html), key=len)
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(js)
r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
Path(f.name).unlink(missing_ok=True)
print(r.stderr.strip() or "JS 语法检查通过")
sys.exit(r.returncode)
