"""设置/关闭局域网访问密码。
    .venv/bin/python passcode.py 1234     设置密码(至少 4 位)
    .venv/bin/python passcode.py --off    关闭密码
"""
import hashlib
import json
import secrets
import sys
from pathlib import Path

ACCESS = Path(__file__).parent / "access.json"
arg = sys.argv[1] if len(sys.argv) > 1 else ""
if arg == "--off":
    ACCESS.unlink(missing_ok=True)
    print("已关闭访问密码")
elif len(arg) >= 4:
    salt = secrets.token_hex(8)
    ACCESS.write_text(json.dumps({"salt": salt, "hash": hashlib.sha256((salt + arg).encode()).hexdigest()}))
    print("已设置访问密码(其他设备需要输入;已登录的设备需要重新登录)")
else:
    print(__doc__)
