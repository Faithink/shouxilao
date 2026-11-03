#!/bin/bash
# 把项目里的 Python 源码、网页和出厂数据拷进安卓工程(云端构建和本地构建都先跑一遍)
set -e
R="$(cd "$(dirname "$0")/../.." && pwd)"
A="$R/android-standalone/app/src/main"
mkdir -p "$A/python"
cp "$R/app.py" "$R/paths.py" "$R/datasrc.py" "$R/fetch_data.py" "$A/python/"
rm -rf "$A/assets/app"; mkdir -p "$A/assets/app/seed/data"
cp -R "$R/web" "$A/assets/app/web"
cp "$R/VERSION" "$A/assets/app/VERSION"
cp "$R/stocks.csv" "$A/assets/app/seed/stocks.csv"
cp "$R/data/pool.json" "$A/assets/app/seed/data/"
cp -R "$R/data/stocks" "$A/assets/app/seed/data/stocks"
[ -d "$R/data/cache" ] && cp -R "$R/data/cache" "$A/assets/app/seed/data/cache"
echo "prepared"
