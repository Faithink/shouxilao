#!/bin/bash
# 一键打包:种子数据 → PyInstaller → 菜单栏小程序 → 图标 → 组装 .app → 签名 → .dmg
# 用法: bash packaging/build.sh      产物: packaging/build/收息佬.app 和 packaging/build/收息佬.dmg
# 依赖: uv(会自动装 Python 3.12)、Xcode 命令行工具(swiftc/iconutil/hdiutil);图标只需生成一次
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
B="$R/packaging/build"
PY="$R/.build-venv/bin/python"
VER="$(tr -d '[:space:]' < "$R/VERSION")"
mkdir -p "$B"

# 0. 构建环境(便携 Python 3.12,最低 macOS 11)
if [ ! -x "$PY" ]; then
  uv venv --python 3.12 "$R/.build-venv"
  uv pip install --python "$PY" pyinstaller certifi pypinyin segno
fi

# 1. 种子数据:只放股票池和行情缓存,绝不带 holdings/access/status/log
rm -rf "$R/packaging/seed"; mkdir -p "$R/packaging/seed/data"
cp "$R/stocks.csv" "$R/packaging/seed/stocks.csv"
cp "$R/data/pool.json" "$R/packaging/seed/data/"
cp -R "$R/data/stocks" "$R/packaging/seed/data/stocks"
[ -d "$R/data/cache" ] && cp -R "$R/data/cache" "$R/packaging/seed/data/cache"

# 2. 服务端
rm -rf "$B/dist" "$B/work"
"$R/.build-venv/bin/pyinstaller" --noconfirm --clean --onedir --name shouxi-server --strip \
  --distpath "$B/dist" --workpath "$B/work" --specpath "$B" \
  --add-data "$R/web:web" --add-data "$R/packaging/seed:seed" --add-data "$R/VERSION:." \
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc_data --exclude-module test \
  --exclude-module distutils --exclude-module setuptools --exclude-module pkg_resources "$R/app.py"

# 3. 菜单栏小程序
swiftc -O -target arm64-apple-macos11.0 "$R/packaging/launcher.swift" -o "$B/ShouxiLauncher"

# 4. 图标(已有就不重做;原图在 packaging/logo_full.png)
if [ ! -f "$B/icon/AppIcon.icns" ]; then
  "$R/.venv/bin/python" "$R/packaging/make_icon.py" "$R/packaging/logo_full.png" "$B/icon"
fi

# 5. 组装
APP="$B/收息佬.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$R/packaging/Info.plist" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" -c "Set :CFBundleVersion $VER" "$APP/Contents/Info.plist"
cp "$B/ShouxiLauncher" "$APP/Contents/MacOS/ShouxiLauncher"
cp "$B/icon/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp -R "$B/dist/shouxi-server" "$APP/Contents/Resources/server"
codesign --force --deep --sign - "$APP"

# 6. dmg
STAGE="$B/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "$R/packaging/INSTALL.txt" "$STAGE/安装说明.txt"
rm -f "$B"/收息佬*.dmg
hdiutil create -volname "收息佬 $VER" -srcfolder "$STAGE" -ov -format ULMO "$B/收息佬-$VER.dmg" >/dev/null

du -sh "$APP" "$B/收息佬-$VER.dmg"
