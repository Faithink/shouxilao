"""收息佬 · Windows 入口:后台服务 + 系统托盘图标(右下角)。
启动本地服务 → 打开浏览器;托盘菜单:打开页面、复制手机访问地址、打开数据文件夹、退出。
只在 Windows 上用(用 PyInstaller 打成无控制台的 收息佬.exe)。"""
import ctypes
import os
import sys
import threading
import webbrowser

# 无控制台时 stdout/stderr 为 None,先指到日志文件,避免 print 报错
import paths

paths.HOME.mkdir(parents=True, exist_ok=True)
_log = open(paths.HOME / "server.log", "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log

import pystray
from PIL import Image

import app


def _single_instance():
    h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ShouxiDividendTray")
    if ctypes.windll.kernel32.GetLastError() == 183:      # 已经在运行:只打开页面
        try:
            port = (paths.HOME / "server.port").read_text().strip()
            webbrowser.open(f"http://127.0.0.1:{port}")
        except OSError:
            pass
        sys.exit(0)
    return h


def main():
    _keep = _single_instance()
    srv, port = app.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    lan = (app.lan_urls(port) or [None])[0]

    def open_page(icon=None, item=None):
        webbrowser.open(url)

    def copy_lan(icon, item):
        if lan:
            import subprocess
            subprocess.run("clip", input=lan.encode("utf-16"), shell=True, creationflags=0x08000000)

    def open_data(icon, item):
        os.startfile(str(paths.HOME))

    def quit_(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开收息佬", open_page, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("手机访问(同一 WiFi)", None, enabled=False),
        pystray.MenuItem(f"  {lan}  · 点击复制" if lan else "  未检测到局域网地址", copy_lan, enabled=bool(lan)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开数据文件夹", open_data),
        pystray.MenuItem("退出收息佬", quit_),
    )
    img = Image.open(paths.RES / "web" / "icon-192.png").convert("RGBA")
    icon = pystray.Icon("shouxi", img, "收息佬", menu)
    threading.Timer(1.0, open_page).start()
    icon.run()
    srv.shutdown()


if __name__ == "__main__":
    main()
