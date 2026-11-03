#!/bin/bash
# 双击启动:开服务并打开浏览器(终端里会打印手机访问用的局域网地址)。关闭此终端窗口即停止。
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "首次运行,安装依赖…"
  python3 -m venv .venv && .venv/bin/pip install -q certifi pypinyin akshare segno || exit 1
fi
.venv/bin/python -c "import segno" 2>/dev/null || .venv/bin/pip install -q segno   # 旧环境补装二维码库
[ -f data/pool.json ] || .venv/bin/python fetch_data.py
(sleep 1.5 && open http://127.0.0.1:8890) &
.venv/bin/python app.py
