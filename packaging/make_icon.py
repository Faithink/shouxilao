"""生成 macOS 应用图标 AppIcon.icns(开发时用一次,需要 Pillow + numpy)。
用法: .venv/bin/python packaging/make_icon.py <原图 1100x1100 png> <输出目录>
做法:把白纸黑线的原图转成「白底 + 深墨线条」,只保留头部(椭圆柔边遮罩),
再放进 macOS 标准的圆角方块里(1024 画布、824 图标区、留透明边)。"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
BG = np.array([0xFF, 0xFF, 0xFF], np.float32)
LINE = np.array([0x1F, 0x24, 0x30], np.float32)

a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
H, W, _ = a.shape
alpha = np.clip(1 - a.min(axis=2) / 255.0, 0, 1)
C = np.clip((a - (1 - alpha)[..., None] * 255.0) / np.maximum(alpha, 1e-3)[..., None], 0, 255)
lum = (C[..., 0] * .299 + C[..., 1] * .587 + C[..., 2] * .114) / 255
sat = (C.max(axis=2) - C.min(axis=2)) / 255
C = np.where(((sat < .25) & (lum < .45))[..., None], LINE, C)         # 近黑线条 → 深墨色,金/红保留
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
cx, cy = 560, 350
rx = np.where(xx > cx, 262, 325)
ry = np.where(yy > cy, 330, 405)
d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
fade = np.clip((1.0 - d) / 0.10, 0, 1)
fade = fade * fade * (3 - 2 * fade)
alpha = alpha * fade                                                  # 椭圆柔边:只留头部
img = np.clip(alpha[..., None] * C + (1 - alpha[..., None]) * BG, 0, 255).astype(np.uint8)
face = Image.fromarray(img).crop((200, 0, 920, 720))                  # 720 方形

S = 1024
plate_px = 824
plate = Image.new("RGB", (plate_px, plate_px), tuple(int(x) for x in BG))
art = face.resize((int(plate_px * .94), int(plate_px * .94)), Image.LANCZOS)
plate.paste(art, ((plate_px - art.size[0]) // 2, (plate_px - art.size[1]) // 2))
mask = Image.new("L", (plate_px * 4, plate_px * 4), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, plate_px * 4 - 1, plate_px * 4 - 1), radius=185 * 4, fill=255)
mask = mask.resize((plate_px, plate_px), Image.LANCZOS)
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(plate, ((S - plate_px) // 2, (S - plate_px) // 2), mask)
# 白底在浅色桌面上要有边:加一圈很淡的描边
edge = Image.new("L", (plate_px * 4, plate_px * 4), 0)
ImageDraw.Draw(edge).rounded_rectangle((0, 0, plate_px * 4 - 1, plate_px * 4 - 1), radius=185 * 4, outline=255, width=6)
edge = edge.resize((plate_px, plate_px), Image.LANCZOS)
icon.paste(Image.new("RGB", (plate_px, plate_px), (0xD9, 0xD5, 0xCA)), ((S - plate_px) // 2, (S - plate_px) // 2), edge)
icon.save(out / "icon_1024.png")

iconset = out / "AppIcon.iconset"
iconset.mkdir(exist_ok=True)
for base in (16, 32, 128, 256, 512):
    icon.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
    icon.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "AppIcon.icns")], check=True)
print("icns:", (out / "AppIcon.icns").stat().st_size // 1024, "KB")
