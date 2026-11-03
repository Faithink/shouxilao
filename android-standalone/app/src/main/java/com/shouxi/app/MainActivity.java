package com.shouxi.app;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Log;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;

/**
 * 收息佬 · 安卓独立版。
 * 手机里自己跑一份 Python 服务(Chaquopy),再用 WebView 打开它,数据、持仓、计算全在手机上,不依赖电脑。
 */
public class MainActivity extends Activity {
    private static final String TAG = "Shouxi";
    private WebView web;
    private TextView status;
    private String base = "";
    private String pendingRoute = null;
    private ValueCallback<Uri[]> fileCb = null;
    private static final int REQ_FILE = 7;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        FrameLayout root = new FrameLayout(this);
        root.setFitsSystemWindows(true);
        web = new WebView(this);
        web.setVisibility(android.view.View.INVISIBLE);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        status = new TextView(this);
        status.setText("正在准备数据…\n第一次打开要几秒钟");
        status.setTextSize(16);
        status.setTextColor(Color.parseColor("#7E8493"));
        status.setGravity(Gravity.CENTER);
        root.addView(status, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " ShouxiApp/" + version());
        // 持仓备份:网页里「导出」调用 saveFile 存到「下载」文件夹,「从备份恢复」用文件选择器
        web.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public boolean saveFile(String name, String text) {
                try {
                    if (Build.VERSION.SDK_INT >= 29) {
                        ContentValues v = new ContentValues();
                        v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                        v.put(MediaStore.Downloads.MIME_TYPE, "application/json");
                        Uri u = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                        if (u == null) return false;
                        try (OutputStream o = getContentResolver().openOutputStream(u)) {
                            o.write(text.getBytes("UTF-8"));
                        }
                        return true;
                    }
                    Intent send = new Intent(Intent.ACTION_SEND);      // 旧系统:用分享面板把备份内容发给自己
                    send.setType("text/plain");
                    send.putExtra(Intent.EXTRA_TEXT, text);
                    startActivity(Intent.createChooser(send, "分享持仓备份"));
                    return true;
                } catch (Exception e) {
                    Log.e(TAG, "保存备份失败", e);
                    return false;
                }
            }
        }, "ShouxiAndroid");
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView w, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (fileCb != null) fileCb.onReceiveValue(null);
                fileCb = cb;
                try {
                    Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.setType("*/*");
                    startActivityForResult(Intent.createChooser(i, "选择持仓备份文件"), REQ_FILE);
                } catch (Exception e) {
                    fileCb = null;
                    cb.onReceiveValue(null);
                    return false;
                }
                return true;
            }

            @Override
            public boolean onConsoleMessage(android.webkit.ConsoleMessage m) {
                Log.i("ShouxiJS", m.messageLevel() + " " + m.message() + " @" + m.sourceId() + ":" + m.lineNumber());
                return true;
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(final WebView v, String url) {
                if (!getIntent().getBooleanExtra("selftest", false)) return;
                v.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        v.evaluateJavascript("(function(){var m=document.getElementById('main');return document.title+' | main='+(m?m.innerText.length:-1)+' | '+(m?m.innerText.slice(0,160).replace(/\\n+/g,' / '):'')})()",
                                new android.webkit.ValueCallback<String>() {
                                    @Override
                                    public void onReceiveValue(String val) {
                                        Log.i("ShouxiPage", url + " => " + val);
                                    }
                                });
                    }
                }, 4000);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (!base.isEmpty() && u.startsWith(base)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, r.getUrl()));
                } catch (Exception ignored) { }
                return true;
            }
        });

        pendingRoute = routeOf(getIntent().getStringExtra("route"));
        final boolean selftest = getIntent().getBooleanExtra("selftest", false);
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    prepareAssets();
                    final int port = startPython();
                    base = "http://127.0.0.1:" + port;
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            status.setVisibility(android.view.View.GONE);
                            web.setVisibility(android.view.View.VISIBLE);
                            web.loadUrl(base + (pendingRoute == null ? "" : pendingRoute));
                        }
                    });
                    if (selftest) {
                        String r = Python.getInstance().getModule("android_entry").callAttr("selftest").toString();
                        Log.i("ShouxiTest", r);
                    }
                } catch (final Throwable t) {
                    StringWriter sw = new StringWriter();
                    t.printStackTrace(new PrintWriter(sw));
                    Log.e(TAG, "启动失败", t);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            status.setTextSize(12);
                            status.setText("启动失败：\n" + sw);
                        }
                    });
                }
            }
        }).start();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_FILE) {
            if (fileCb != null) {
                Uri[] r = null;
                if (res == RESULT_OK && data != null && data.getData() != null) r = new Uri[]{data.getData()};
                fileCb.onReceiveValue(r);
                fileCb = null;
            }
            return;
        }
        super.onActivityResult(req, res, data);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String r = routeOf(intent.getStringExtra("route"));
        if (r != null && !base.isEmpty()) web.loadUrl(base + r);
        else pendingRoute = r;
    }

    /** 测试用:adb 传 route=hold 之类(# 会被设备上的 shell 当成注释,所以不直接传) */
    private static String routeOf(String r) {
        if (r == null) return null;
        return r.equals("pool") ? "" : "#/" + r;
    }

    private String version() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "0";
        }
    }

    /** 把 APK 里的网页和出厂数据解压到手机私有目录(版本变了才重新解压;用户数据在 home 里,不动) */
    private void prepareAssets() throws Exception {
        synchronized (LOCK) {
            prepareAssetsLocked();
        }
    }

    private void prepareAssetsLocked() throws Exception {
        SharedPreferences sp = getSharedPreferences("shouxi", MODE_PRIVATE);
        File res = new File(getFilesDir(), "res");
        String ver = version();
        if (!ver.equals(sp.getString("res_ver", "")) || !res.exists()) {
            deleteRecursive(res);
            copyAssetDir(getAssets(), "app", res);
            sp.edit().putString("res_ver", ver).apply();
        }
        new File(getFilesDir(), "home").mkdirs();
    }

    private static final Object LOCK = new Object();

    private int startPython() {
        synchronized (LOCK) {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
        }
        PyObject m = Python.getInstance().getModule("android_entry");
        return m.callAttr("start", new File(getFilesDir(), "home").getAbsolutePath(), new File(getFilesDir(), "res").getAbsolutePath()).toInt();
    }

    private static void copyAssetDir(AssetManager am, String path, File dst) throws Exception {
        String[] list = am.list(path);
        if (list == null || list.length == 0) {
            dst.getParentFile().mkdirs();
            try (InputStream in = am.open(path); OutputStream out = new FileOutputStream(dst)) {
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            return;
        }
        dst.mkdirs();
        for (String name : list) copyAssetDir(am, path + "/" + name, new File(dst, name));
    }

    private static void deleteRecursive(File f) {
        if (f == null || !f.exists()) return;
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteRecursive(k);
        f.delete();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
