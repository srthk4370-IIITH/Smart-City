package com.iiith.smartcityedge;

import android.app.Activity;
import android.content.Intent;
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
    static final String EXTRA_INCIDENT = "incident";
    /** true while the dashboard is in front: EdgeService then leaves alerting to the page (UX v34). */
    static volatile boolean foreground = false;
    private volatile String pendingIncident; // opened from a notification before the page loaded
    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        EdgeService.start(this);
        pendingIncident = incidentOf(getIntent());
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
        freshUiAfterUpdate();
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

    /**
     * After an APK update, drop the WebView's web storage once so the new dashboard actually shows.
     *
     * LOAD_NO_CACHE only governs the HTTP cache. The dashboard's service worker keeps its own Cache
     * Storage and registration, which survive app updates and could keep serving the previous app.js
     * (observed: a fixed incident title and CSS stayed stale across two APK installs and relaunches,
     * even with Cache-Control: no-cache from the backend). deleteAllData() clears service workers,
     * Cache Storage and localStorage; the only preference kept there is the theme, whose default is
     * the designed one. Runs once per install, keyed on the APK's lastUpdateTime.
     */
    private void freshUiAfterUpdate() {
        try {
            long installed = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime;
            android.content.SharedPreferences p = getSharedPreferences("ui", MODE_PRIVATE);
            if (p.getLong("uiFor", 0) != installed) {
                android.webkit.WebStorage.getInstance().deleteAllData();
                web.clearCache(true);
                p.edit().putLong("uiFor", installed).apply();
            }
        } catch (Exception ignored) {
            // never block the dashboard over cache housekeeping
        }
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
                        ui.post(() -> {
                            String id = pendingIncident;
                            pendingIncident = null;
                            web.loadUrl(URL_HOME + (id != null ? "#incident/" + id : ""));
                        });
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

    /** The incident id a notification asked to open (validated: it ends up in the page URL). */
    private static String incidentOf(Intent i) {
        String id = i == null ? null : i.getStringExtra(EXTRA_INCIDENT);
        return id != null && id.matches("INC-\\d{1,8}") ? id : null;
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        setIntent(i);
        String id = incidentOf(i);
        if (id == null) return;
        String cur = web.getUrl();
        if (cur != null && cur.startsWith(URL_HOME)) web.evaluateJavascript("location.hash='incident/" + id + "'", null);
        else pendingIncident = id;
    }

    @Override
    protected void onResume() {
        super.onResume();
        foreground = true;
    }

    @Override
    protected void onPause() {
        foreground = false;
        super.onPause();
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
        // Go back only within the dashboard (closes an open sensor sheet, which pushes a history entry).
        // The entry before the dashboard is the black "Starting..." placeholder page (loadData): going
        // back to it left a blank screen with no way out on the kiosk board (found 2026-10-21).
        android.webkit.WebBackForwardList h = web.copyBackForwardList();
        int i = h.getCurrentIndex();
        String prev = i > 0 ? h.getItemAtIndex(i - 1).getUrl() : null;
        if (prev != null && prev.startsWith(URL_HOME)) web.goBack();
        else moveTaskToBack(true); // keep the service running
    }

    @Override
    public void onWindowFocusChanged(boolean f) {
        super.onWindowFocusChanged(f);
        if (f) hideBars();
    }
}
