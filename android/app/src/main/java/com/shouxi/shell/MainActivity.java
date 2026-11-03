package com.shouxi.shell;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

/**
 * 收息佬 · 安卓壳:一个只装 WebView 的 App,打开电脑上正在运行的收息佬。
 * 第一次启动输入电脑地址(收息佬「设置 → 手机使用」里二维码下面那行),之后直接进。
 * 数据和计算都在电脑上,手机只是显示。
 */
public class MainActivity extends Activity {
    private WebView web;
    private SharedPreferences sp;
    private String base = "";
    private boolean failed = false;
    private boolean asking = false;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        sp = getSharedPreferences("shouxi", MODE_PRIVATE);
        base = sp.getString("url", "");

        FrameLayout root = new FrameLayout(this);
        root.setFitsSystemWindows(true);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(false);
        s.setUserAgentString(s.getUserAgentString() + " ShouxiShell/1.6.0");
        web.addJavascriptInterface(new Bridge(), "ShouxiShell");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (!base.isEmpty() && u.startsWith(base)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, r.getUrl()));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageStarted(WebView v, String url, Bitmap icon) {
                failed = false;
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame() && !failed) {
                    failed = true;
                    showFail();
                }
            }
        });

        if (base.isEmpty()) askUrl(); else web.loadUrl(base);
    }

    /** 网页里的「更改电脑地址」按钮会调用它 */
    private class Bridge {
        @JavascriptInterface
        public void changeAddress() {
            runOnUiThread(MainActivity.this::askUrl);
        }
    }

    private String normalize(String raw) {
        String u = raw == null ? "" : raw.trim();
        if (u.isEmpty()) return "";
        if (!u.startsWith("http://") && !u.startsWith("https://")) u = "http://" + u;
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    private void askUrl() {
        if (asking) return;
        asking = true;
        final EditText et = new EditText(this);
        et.setHint("例如 192.168.1.5:8890");
        et.setSingleLine(true);
        et.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        et.setText(base.isEmpty() ? "http://192.168." : base);
        et.setSelection(et.getText().length());
        AlertDialog.Builder d = new AlertDialog.Builder(this)
                .setTitle("电脑上的收息佬地址")
                .setMessage("在电脑的收息佬里打开「设置 → 手机使用」，把二维码下面那行地址填到这里。手机和电脑要连同一个 WiFi。")
                .setView(et)
                .setCancelable(!base.isEmpty())
                .setPositiveButton("打开", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface di, int w) {
                        String u = normalize(et.getText().toString());
                        if (u.isEmpty()) {
                            Toast.makeText(MainActivity.this, "地址不能为空", Toast.LENGTH_SHORT).show();
                            asking = false;
                            askUrl();
                            return;
                        }
                        base = u;
                        sp.edit().putString("url", u).apply();
                        asking = false;
                        web.loadUrl(u);
                    }
                })
                .setOnDismissListener(new DialogInterface.OnDismissListener() {
                    @Override
                    public void onDismiss(DialogInterface di) {
                        asking = false;
                    }
                });
        if (!base.isEmpty()) d.setNegativeButton("取消", null);
        d.show();
    }

    private void showFail() {
        new AlertDialog.Builder(this)
                .setTitle("连不上电脑")
                .setMessage("地址：" + base + "\n\n请检查：\n1. 电脑上的收息佬是不是开着\n2. 手机和电脑是不是同一个 WiFi\n3. 电脑的 IP 地址有没有变（重新看「设置 → 手机使用」）")
                .setPositiveButton("重试", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface di, int w) {
                        failed = false;
                        web.loadUrl(base);
                    }
                })
                .setNeutralButton("改地址", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface di, int w) {
                        askUrl();
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
