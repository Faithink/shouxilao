"""安卓独立版入口:由 MainActivity 通过 Chaquopy 调用。
把本机服务跑在手机里(只监听 127.0.0.1),网页视图再去打开它。"""
import json
import os
import threading

_started = {"port": None}
_lock = threading.Lock()


_BK_DIR = "Download/收息佬备份/"      # 公共「下载」目录下的子文件夹,卸载 App 不会被删
_BK_KEEP = 7


def _backup_to_downloads(name, data):
    """每次保存持仓后,把当天的备份写一份到 下载/收息佬备份/(同名覆盖,只留最近 7 份)。
    写在公共目录是为了卸载重装后还能找回;重装后用「从备份恢复」选这个文件。Android 10 以下不做。"""
    from com.chaquo.python import Python
    from java import jarray, jbyte, jclass
    if jclass("android.os.Build$VERSION").SDK_INT < 29:
        return
    cr = Python.getPlatform().getApplication().getContentResolver()
    MS = jclass("android.provider.MediaStore$Downloads")
    CV = jclass("android.content.ContentValues")
    ContentUris = jclass("android.content.ContentUris")
    Str = jclass("java.lang.String")
    uri = MS.EXTERNAL_CONTENT_URI
    cur = cr.query(uri, jarray(Str)(["_id"]), "_display_name=? AND relative_path=?", jarray(Str)([name, _BK_DIR]), None)
    target = None
    try:
        if cur is not None and cur.moveToFirst():
            target = ContentUris.withAppendedId(uri, cur.getLong(0))
    finally:
        if cur is not None:
            cur.close()
    if target is None:
        v = CV()
        v.put("_display_name", name)
        v.put("mime_type", "application/json")
        v.put("relative_path", _BK_DIR)
        target = cr.insert(uri, v)
    if target is None:
        return
    out = cr.openOutputStream(target, "wt")
    try:
        out.write(jarray(jbyte)(data))
    finally:
        out.close()
    # 只清理本 App 建的、超过 7 份的旧备份
    cur = cr.query(uri, jarray(Str)(["_id"]), "_display_name LIKE ? AND relative_path=?", jarray(Str)(["收息佬自动备份-%", _BK_DIR]), "_display_name DESC")
    ids = []
    try:
        while cur is not None and cur.moveToNext():
            ids.append(cur.getLong(0))
    finally:
        if cur is not None:
            cur.close()
    for i in ids[_BK_KEEP:]:
        cr.delete(ContentUris.withAppendedId(uri, i), None, None)


def start(home, res):
    """启动本地服务,返回端口。App 进程里重复调用只会返回第一次的端口。"""
    with _lock:                       # 界面重建时可能同时来两次,只启动一次
        return _start_locked(home, res)


def _start_locked(home, res):
    if _started["port"]:
        return _started["port"]
    os.environ.update(SHOUXI_ANDROID="1", SHOUXI_HOME=home, SHOUXI_RES=res,
                      SHOUXI_BIND="127.0.0.1", SHOUXI_SOURCE="native")
    import app
    app.EXTRA_BACKUP = _backup_to_downloads
    last = None
    for p in range(18890, 18900):     # 端口固定,网页里存的偏好(深浅色等)才不会丢
        os.environ["SHOUXI_PORT"] = str(p)
        try:
            srv, port = app.start()
            break
        except SystemExit as e:
            last = e
    else:
        raise RuntimeError(f"本机端口都被占用: {last}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    def _warm():                      # pypinyin 第一次用要加载字典,提前在后台做,免得第一次打开页面等很久
        try:
            import json as _j
            import paths
            names = [s["name"] for s in _j.loads((paths.DATA / "pool.json").read_text(encoding="utf-8"))["stocks"]]
            for n in names:
                app.pinyin_of(n)
        except Exception:
            pass
    threading.Thread(target=_warm, daemon=True).start()
    _started["port"] = port
    return port


def selftest():
    """模拟器自测:在手机上实际刷新两只股票(一只个股、一只 ETF),看网络、证书和计算是否正常。"""
    import datasrc
    import fetch_data
    import paths
    errs = fetch_data.run(only=["563020", "600285"], log=lambda s: None)
    pool = json.loads((paths.DATA / "pool.json").read_text(encoding="utf-8"))
    out = {"source": datasrc.SOURCE, "errors": errs, "version": paths.VERSION, "n": len(pool["stocks"])}
    for s in pool["stocks"]:
        if s["code"] in ("563020", "600285"):
            out[s["code"]] = {"price": s["price"], "yield": round(s["yield"], 4), "status": s["status"]}
    return json.dumps(out, ensure_ascii=False)
