"""生成 macOS 应用图标 AppIcon.icns。
用法: .venv/bin/python packaging/make_icon.py <icon_1024.png> <输出目录>
icon_1024.png 由 packaging/make_brand.py 用吉祥物原图生成(白色圆角方块,已带透明边)。"""
import subprocess
import sys
from pathlib import Path

from PIL import Image

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
icon = Image.open(src).convert("RGBA")
iconset = out / "AppIcon.iconset"
iconset.mkdir(exist_ok=True)
for base in (16, 32, 128, 256, 512):
    icon.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
    icon.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")
icon.save(out / "icon_1024.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "AppIcon.icns")], check=True)
print("icns:", (out / "AppIcon.icns").stat().st_size // 1024, "KB")
