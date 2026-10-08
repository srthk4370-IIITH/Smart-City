package com.iiith.smartcityedge;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.net.HttpURLConnection;
import java.net.URL;

/** Full-screen native shell for the on-device dashboard served by EdgeService on 127.0.0.1:8000. */
public class MainActivity extends Activity {
    static final String URL_HOME = "http://127.0.0.1:8000/";
    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        EdgeService.start(this);
        if (checkSelfPermission("android.permission.POST_NOTIFICATIONS") != 0) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
        }
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) waitAndLoad();
            }
        });
        setContentView(web);
        hideBars();
        web.loadData("<html><body style='background:#000;color:#ccc;font:20px sans-serif;display:flex;"
                + "align-items:center;justify-content:center;height:90vh;text-align:center'>"
                + "<div><b style='color:#fff;font-size:26px'>Smart City Edge</b><br><br>Starting on-device "
                + "monitor and NPU agents&hellip;</div></body></html>", "text/html", "utf-8");
        waitAndLoad();
    }

    /** Polls the local backend until it answers, then loads the dashboard. */
    private void waitAndLoad() {
        new Thread(() -> {
            for (int i = 0; i < 120; i++) {
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(URL_HOME + "api/status").openConnection();
                    c.setConnectTimeout(1000);
                    c.setReadTimeout(3000);
                    if (c.getResponseCode() == 200) {
                        ui.post(() -> web.loadUrl(URL_HOME));
                        return;
                    }
                } catch (Exception ignored) {
                }
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }).start();
    }

    private void hideBars() {
        WindowInsetsController c = getWindow().getInsetsController();
        if (c != null) {
            c.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
        }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else moveTaskToBack(true); // keep the service running
    }

    @Override
    public void onWindowFocusChanged(boolean f) {
        super.onWindowFocusChanged(f);
        if (f) hideBars();
    }
}
