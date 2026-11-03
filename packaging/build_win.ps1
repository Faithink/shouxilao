# Windows 打包(GitHub Actions 或本机 PowerShell 运行):生成 dist\收息佬\ 和 收息佬-win.zip
$ErrorActionPreference = "Stop"
$R = Resolve-Path "$PSScriptRoot\.."
Set-Location $R
python -m pip install --quiet pyinstaller certifi pypinyin segno pystray pillow

# 种子数据:只放股票池和行情缓存,不带 holdings/access
Remove-Item -Recurse -Force packaging\seed -ErrorAction SilentlyContinue
New-Item -ItemType Directory packaging\seed\data | Out-Null
Copy-Item stocks.csv packaging\seed\stocks.csv
Copy-Item data\pool.json packaging\seed\data\
Copy-Item -Recurse data\stocks packaging\seed\data\stocks
if (Test-Path data\cache) { Copy-Item -Recurse data\cache packaging\seed\data\cache }

python -c "from PIL import Image; Image.open('packaging/icon_1024.png').save('packaging/AppIcon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"

python -m PyInstaller --noconfirm --clean --onedir --windowed --name 收息佬 `
  --icon "$R\packaging\AppIcon.ico" `
  --paths "$R" --add-data "$R\VERSION;." --add-data "$R\web;web" --add-data "$R\packaging\seed;seed" `
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc_data --exclude-module test `
  --distpath packaging\build\dist --workpath packaging\build\work --specpath packaging\build `
  "$R\packaging\win_main.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Copy-Item packaging\INSTALL_WIN.txt "packaging\build\dist\收息佬\安装说明.txt"
$ver = (Get-Content VERSION).Trim()
Compress-Archive -Path "packaging\build\dist\收息佬" -DestinationPath "packaging\build\收息佬-win-$ver.zip" -Force
"{0:N1} MB" -f ((Get-Item "packaging\build\收息佬-win-$ver.zip").Length / 1MB)
