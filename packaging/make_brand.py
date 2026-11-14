"""用吉祥物原图(packaging/mascot_light.jpg 白底、mascot_dark.jpg 黑底)生成全部图标和 logo。
用法: .venv/bin/python packaging/make_brand.py        (需要 Pillow + numpy)
输出: web/ 下的页面 logo(浅色白底 / 深色深蓝底,不透明方图)、网页图标;packaging/icon_1024.png(Mac/Windows 图标源);两个安卓工程的 ic_launcher。
Mac 的 AppIcon.icns 在 packaging/build.sh 里用 make_icon.py 另外生成。"""
from pathlib import Path

from PIL import Image, ImageDraw

R = Path(__file__).resolve().parent.parent
BOX = (224, 134, 1784, 1694)          # 两张原图的作品区域一致:正方形裁切,四周留白
light = Image.open(R / "packaging/mascot_light.jpg").convert("RGB").crop(BOX)
dark = Image.open(R / "packaging/mascot_dark.jpg").convert("RGB").crop(BOX)


def plate(size, scale=0.9, bg=(255, 255, 255)):
    """白底方块,作品居中、占 scale"""
    p = Image.new("RGB", (size, size), bg)
    art = light.resize((int(size * scale),) * 2, Image.LANCZOS)
    p.paste(art, ((size - art.size[0]) // 2, (size - art.size[1]) // 2))
    return p


# 页面 logo(浅色 / 深色):不透明方图,贴在对应底色的圆角方块里,保持原图线条粗细。
# 页头 logo 显示 50px:预先用 LANCZOS 缩成 1x/2x/3x 三档,用 srcset 让浏览器按屏幕选,避免浏览器自己大比例缩小造成发糊。
W = R / "web"
TIGHT = (294, 204, 1714, 1624)          # 作品范围 + 少量留白
lt_t = Image.open(R / "packaging/mascot_light.jpg").convert("RGB").crop(TIGHT)
dk_t = Image.open(R / "packaging/mascot_dark.jpg").convert("RGB").crop(TIGHT)
for suffix, px in (("", 50), ("@2x", 100), ("@3x", 150)):
    lt_t.resize((px, px), Image.LANCZOS).save(W / f"logo-sm{suffix}.png", optimize=True)
    dk_t.resize((px, px), Image.LANCZOS).save(W / f"logo-sm-dark{suffix}.png", optimize=True)
light.resize((450, 450), Image.LANCZOS).save(W / "logo.png", optimize=True)         # 登录页和设置页大图(150px 显示的 3 倍)
light.resize((450, 450), Image.LANCZOS).save(W / "logo-full.webp", quality=92)
dark.resize((450, 450), Image.LANCZOS).save(W / "logo-full-dark.webp", quality=92)
for name, px, sc in (("favicon.png", 64, .98), ("apple-touch-icon.png", 180, .9), ("icon-192.png", 192, .92), ("icon-512.png", 512, .92)):
    plate(px, sc).save(W / name, optimize=True)

# Mac / Windows 图标源:白色圆角方块(1024 画布、824 图标区、留透明边),带很淡的描边
S, P = 1024, 824
pl = plate(P, .94)
mask = Image.new("L", (P * 4, P * 4), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, P * 4 - 1, P * 4 - 1), radius=185 * 4, fill=255)
mask = mask.resize((P, P), Image.LANCZOS)
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(pl, ((S - P) // 2, (S - P) // 2), mask)
edge = Image.new("L", (P * 4, P * 4), 0)
ImageDraw.Draw(edge).rounded_rectangle((0, 0, P * 4 - 1, P * 4 - 1), radius=185 * 4, outline=255, width=6)
edge = edge.resize((P, P), Image.LANCZOS)
icon.paste(Image.new("RGB", (P, P), (0xD9, 0xD5, 0xCA)), ((S - P) // 2, (S - P) // 2), edge)
icon.save(R / "packaging/icon_1024.png", optimize=True)

# 安卓启动图标(两个工程)
for proj in ("android", "android-standalone"):
    for d, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        out = R / proj / "app/src/main/res" / f"mipmap-{d}" / "ic_launcher.png"
        if out.parent.exists():
            plate(px, .9).save(out, optimize=True)
print("done")
