"""路径管理:开发时用项目目录;打包后,用户数据放到每台电脑自己的目录里(Mac: Application Support,Windows: %APPDATA%)。

- RES   只读资源(web 页面、初始数据、默认股票池)。打包后在 app 内部。
- HOME  用户数据根目录(持仓、关注、设置、访问密码、股票池、采集到的行情数据)。
可用环境变量 SHOUXI_HOME 覆盖 HOME(测试用)。
"""
import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
ANDROID = bool(os.environ.get("SHOUXI_ANDROID"))      # 安卓独立版:资源和数据目录由 App 通过环境变量传进来
if FROZEN:
    RES = Path(sys._MEIPASS)
    _base = (Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") if sys.platform == "win32"
             else Path.home() / "Library" / "Application Support")
    HOME = Path(os.environ.get("SHOUXI_HOME") or (_base / "收息佬"))
elif ANDROID:
    RES = Path(os.environ["SHOUXI_RES"])
    HOME = Path(os.environ["SHOUXI_HOME"])
else:
    RES = Path(__file__).parent
    HOME = Path(os.environ.get("SHOUXI_HOME") or Path(__file__).parent)
SEEDING = FROZEN or ANDROID                              # 打包版:首次运行从出厂数据复制

try:
    VERSION = (RES / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "dev"
WEB = RES / "web"
DATA = HOME / "data"
HOLDINGS = HOME / "holdings.json"
ACCESS = HOME / "access.json"
STOCKS_CSV = HOME / "stocks.csv"


def read_text_any(path):
    """读文本文件:先按 UTF-8(兼容带 BOM),不行再按 GBK(中文 Windows 记事本另存为"ANSI"、或旧版写出的文件)。"""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def load_json(path, default=None):
    """读 JSON:文件不存在或内容损坏时返回 default。"""
    import json
    try:
        return json.loads(read_text_any(path))
    except (FileNotFoundError, ValueError):
        return default


def _codes(csv_path):
    import csv
    import io
    return [r["code"] for r in csv.DictReader(io.StringIO(read_text_any(csv_path)))]


def ensure_home():
    """首次运行:建目录,并把默认股票池和一份初始数据复制过去(之后用户自己刷新)。
    升级安装:新版出厂股票池里新增的股票,会补进用户自己的股票池(用户自己加、删的不动,持仓不动)。"""
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "stocks").mkdir(parents=True, exist_ok=True)
    if not SEEDING:
        return
    import json
    seed = RES / "seed"
    if not (seed / "stocks.csv").exists():
        return
    marker = HOME / "seed_codes.json"
    seed_codes = _codes(seed / "stocks.csv")
    fresh = not STOCKS_CSV.exists()
    if fresh:
        shutil.copy(seed / "stocks.csv", STOCKS_CSV)
    if not (DATA / "pool.json").exists() and (seed / "data").exists():
        shutil.copytree(seed / "data", DATA, dirs_exist_ok=True)
    elif not fresh:
        mine = set(_codes(STOCKS_CSV))
        try:
            old = set(json.loads(marker.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            old = set(mine)          # 旧版没有记录:把用户现有的当作旧出厂列表
        add = [c for c in seed_codes if c not in old and c not in mine]
        if add:
            import csv
            import io
            rows = {r["code"]: r for r in csv.DictReader(io.StringIO(read_text_any(seed / "stocks.csv")))}
            text = read_text_any(STOCKS_CSV)
            if text and not text.endswith("\n"):
                text += "\n"
            # 整体重写为 UTF-8:原文件若是 GBK,直接追加会形成混合编码
            STOCKS_CSV.write_text(text + "".join(f"{c},{rows[c]['name']},{rows[c]['industry']}\n" for c in add), encoding="utf-8")
            try:
                pool = load_json(DATA / "pool.json")
                sp = {s["code"]: s for s in json.loads((seed / "data" / "pool.json").read_text(encoding="utf-8"))["stocks"]}
                have = {s["code"] for s in pool["stocks"]}
                pool["stocks"] += [sp[c] for c in add if c in sp and c not in have]
                (DATA / "pool.json").write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
            except (OSError, ValueError, KeyError):
                pass
            for c in add:
                for sub in ("stocks", "cache"):
                    src, dst = seed / "data" / sub / f"{c}.json", DATA / sub / f"{c}.json"
                    if src.exists() and not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(src, dst)
    try:
        marker.write_text(json.dumps(seed_codes), encoding="utf-8")
    except OSError:
        pass
