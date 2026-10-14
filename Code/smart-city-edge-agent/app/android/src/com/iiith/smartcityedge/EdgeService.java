package com.iiith.smartcityedge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.content.res.AssetManager;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Map;

/**
 * Keeps the edge-agent backend (Go, packaged as libedgeagent.so) running with no laptop: started by the
 * launcher and again after every reboot (BootReceiver), supervised from a foreground service.
 *
 * This QIDK's firmware does not let ordinary apps open the Hexagon NPU, but the adb shell user may. The
 * service therefore asks the device's OWN adb daemon (127.0.0.1:5555, see AdbLocal) to install/refresh
 * the backend from this APK into /data/local/tmp/smart_city_edge and start it as the shell user, where
 * Genie can use the NPU. If local adb is unreachable it falls back to an in-app backend in Mode 1.
 */
public class EdgeService extends Service {
    static final String TAG = "SmartCityEdge";
    static final String CHANNEL = "edge";
    private Thread worker;
    private volatile Process proc;
    private PowerManager.WakeLock wake;

    public static void start(Context c) {
        c.startForegroundService(new Intent(c, EdgeService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Edge monitor", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, CHANNEL)
                .setContentTitle("Smart City Edge is running")
                .setContentText("Sensors, statistics and AI agents on the Hexagon NPU")
                .setSmallIcon(android.R.drawable.stat_sys_upload_done)
                .setContentIntent(open)
                .setOngoing(true)
                .build();
        startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        if (wake == null) {
            wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sce:backend");
            wake.acquire();
        }
        if (worker == null) {
            worker = new Thread(this::runLoop, "edge-backend");
            worker.start();
        }
        return START_STICKY;
    }

    private void runLoop() {
        File app = new File(getFilesDir(), "app");
        File ext = new File(getExternalFilesDir(null), "app"); // readable by the shell user
        try {
            syncAssets(app);
            syncAssets(ext);
        } catch (Exception e) {
            Log.e(TAG, "asset copy failed", e);
        }
        AdbLocal adb = new AdbLocal(getFilesDir());
        int misses = 0, ticks = 0;
        boolean fallback = false;
        // After an APK update a HEALTHY backend used to keep running the old binary indefinitely,
        // because startScript only ran when the backend was unhealthy - so a new libedgeagent.so or
        // libgenied.so shipped in the APK never took effect until something crashed. Check once at
        // service start: if the deployed binaries differ from the ones in this APK, redeploy now.
        boolean checkedUpdate = false;
        while (!Thread.currentThread().isInterrupted()) {
            try {
                if (!checkedUpdate && healthy() && AdbLocal.listening()) {
                    checkedUpdate = true;
                    String r = adb.shell(staleScript(ext), 15000).trim();
                    if (r.contains("STALE")) {
                        Log.i(TAG, "APK carries a newer backend/daemon than the running one - redeploying");
                        String out = adb.shell(startScript(ext), 30000);
                        Log.i(TAG, "redeploy: " + out.trim());
                        for (int i = 0; i < 25 && !healthy(); i++) Thread.sleep(1000);
                    }
                }
                if (fallback && AdbLocal.listening()) {
                    // adbd came back (it can take minutes after boot): leave rules-only mode. Without
                    // this the board stayed in Mode 1 until the app was restarted by hand.
                    Log.i(TAG, "local adbd available again - replacing the in-app backend with the NPU backend");
                    if (proc != null) {
                        proc.destroy();
                        proc.waitFor(5, java.util.concurrent.TimeUnit.SECONDS);
                        if (proc.isAlive()) proc.destroyForcibly();
                        proc = null;
                    }
                    fallback = false;
                    misses = 0;
                    String out = adb.shell(startScript(ext), 30000);
                    Log.i(TAG, "NPU backend start via local adbd: " + out.trim());
                    for (int i = 0; i < 25 && !healthy(); i++) Thread.sleep(1000);
                } else if (healthy()) {
                    misses = 0;
                    notifyNewIncidents();
                    if (++ticks % 60 == 0 && AdbLocal.listening()) { // every ~5 min: model files intact?
                        String r = adb.shell(healScript(ext), 300000).trim();
                        if (!r.isEmpty()) Log.w(TAG, "self-heal: " + r);
                    }
                } else if (AdbLocal.listening()) {
                    String out = adb.shell(startScript(ext), 30000);
                    Log.i(TAG, "NPU backend start via local adbd: " + out.trim());
                    for (int i = 0; i < 25 && !healthy(); i++) Thread.sleep(1000);
                } else if (++misses >= 12 && (!fallback || proc == null || !proc.isAlive())) {
                    // first fallback, or the in-app backend itself died: (re)start it
                    // adbd on 127.0.0.1:5555 not reachable for ~1 min: run the backend inside the app.
                    // Apps cannot open the NPU on this firmware, so it runs in Mode 1 (rules only).
                    Log.w(TAG, "local adbd unavailable - starting in-app backend (rules only, NPU offline)");
                    startInApp(app);
                    fallback = true;
                }
                Thread.sleep(5000);
            } catch (InterruptedException ie) {
                return;
            } catch (Exception e) {
                Log.e(TAG, "backend supervisor", e);
                try {
                    Thread.sleep(5000);
                } catch (InterruptedException ie) {
                    return;
                }
            }
        }
    }

    /** Prints STALE if the deployed backend, daemon or dashboard differs from what this APK ships.
     *  The web assets matter as much as the binaries: they are copied to the served directory only
     *  by backendStart, so without this check a new APK's UI never appeared until a crash. */
    private String staleScript(File ext) {
        String lib = getApplicationInfo().nativeLibraryDir;
        String D = "/data/local/tmp/smart_city_edge";
        String W = ext.getAbsolutePath() + "/web";
        return "cmp -s " + lib + "/libedgeagent.so " + D + "/edge-agent || echo STALE; "
                + "[ -f " + lib + "/libgenied.so ] && { cmp -s " + lib + "/libgenied.so " + D + "/genied || echo STALE; }; "
                + "for f in index.html app.js styles.css sw.js; do cmp -s " + W + "/$f " + D + "/web/$f || echo STALE; done; true";
    }

    /** Shell command (run as the adb shell user) that installs/refreshes and starts the NPU backend. */
    private String startScript(File ext) {
        String lib = getApplicationInfo().nativeLibraryDir;
        long now = System.currentTimeMillis() / 1000 + clockOffset();
        // Self-healing: restore any model bundle that was deleted or truncated from the on-device backup
        // (install_app.ps1 copies it into this app's protected external storage).
        return healScript(ext) + backendStart(ext, lib, now);
    }

    private String healScript(File ext) {
        return "K=" + new File(ext.getParentFile(), "backup").getAbsolutePath() + "; T=/data/local/tmp; "
                + "for d in genie_bundle genie_bundle_ft genie_bundle_ft_4096; do [ -d $K/$d ] || continue; bad=0; "
                + "for f in llama_v3_2_3b_instruct_part_1_of_3.bin llama_v3_2_3b_instruct_part_2_of_3.bin "
                + "llama_v3_2_3b_instruct_part_3_of_3.bin smartcity_agent.json tokenizer.json; do "
                + "[ \"$(stat -c %s $T/$d/$f 2>/dev/null)\" = \"$(stat -c %s $K/$d/$f 2>/dev/null)\" ] || bad=1; done; "
                + "if [ $bad = 1 ]; then mkdir -p $T/$d && cp -r $K/$d/. $T/$d/ && echo RESTORED_$d; fi; done; ";
    }

    private String backendStart(File ext, String lib, long now) {
        return "D=/data/local/tmp/smart_city_edge; L=" + lib + "; X=" + ext.getAbsolutePath() + "; "
                + "mkdir -p $D/state $D/data $D/web; "
                + "cmp -s $L/libedgeagent.so $D/edge-agent || { cp $L/libedgeagent.so $D/edge-agent.new && mv $D/edge-agent.new $D/edge-agent; }; "
                + "chmod 755 $D/edge-agent; cp -r $X/web/. $D/web/; cp $X/data/sensors.json $D/data/sensors.json; "
                // genied (persistent Genie dialog) ships in the APK too; edge-agent launches and
                // supervises it. Kill the old one so a new APK's daemon replaces it cleanly.
                + "if [ -f $L/libgenied.so ]; then cmp -s $L/libgenied.so $D/genied || { cp $L/libgenied.so $D/genied.new && mv $D/genied.new $D/genied; }; chmod 755 $D/genied; fi; "
                + "pkill -x genied; pkill -x edge-agent; sleep 1; "
                + "cd $D && (setsid nohup ./edge-agent --dir $D --genie /data/local/tmp/genie_bundle --mode 3 "
                + "--clock-unix " + now + " > state/agent.log 2>&1 < /dev/null &); "
                + "sleep 2; pgrep -x edge-agent >/dev/null && echo STARTED || echo FAILED";
    }

    private final java.util.Set<String> seenIncidents = new java.util.HashSet<>();
    private boolean incidentsPrimed = false;

    /** Posts an Android notification for every new incident (the monitor runs with the screen off too). */
    private void notifyNewIncidents() {
        try {
            java.net.HttpURLConnection c = (java.net.HttpURLConnection)
                    new java.net.URL("http://127.0.0.1:8000/api/incidents?limit=50").openConnection();
            c.setConnectTimeout(800);
            c.setReadTimeout(3000);
            String body;
            try {
                body = new String(c.getInputStream().readAllBytes(), "UTF-8");
            } finally {
                c.disconnect();
            }
            org.json.JSONArray arr = new org.json.JSONArray(body);
            NotificationManager nm = getSystemService(NotificationManager.class);
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.getJSONObject(i);
                String id = o.optString("id");
                if (!seenIncidents.add(id) || !incidentsPrimed) continue;
                if (nm.getNotificationChannel("alerts") == null) {
                    nm.createNotificationChannel(new NotificationChannel("alerts", "Sensor alerts",
                            NotificationManager.IMPORTANCE_HIGH));
                }
                PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                        PendingIntent.FLAG_IMMUTABLE);
                nm.notify(1000 + (id.hashCode() & 0xffff), new Notification.Builder(this, "alerts")
                        .setContentTitle(o.optString("severity", "alert").toUpperCase() + " - " + id)
                        .setContentText(o.optString("title"))
                        .setSmallIcon(android.R.drawable.stat_notify_error)
                        .setContentIntent(open).setAutoCancel(true).build());
            }
            incidentsPrimed = true; // existing incidents at start are not re-announced
        } catch (Exception ignored) {
        }
    }

    private static boolean healthy() {
        try {
            java.net.HttpURLConnection c = (java.net.HttpURLConnection)
                    new java.net.URL("http://127.0.0.1:8000/api/status").openConnection();
            c.setConnectTimeout(800);
            c.setReadTimeout(3000);
            try {
                return c.getResponseCode() == 200;
            } finally {
                c.disconnect(); // one health check every 5 s; leaving it open leaked a socket per check
            }
        } catch (Exception e) {
            return false;
        }
    }

    /** Fallback: backend inside the app process tree (no NPU access for apps on this firmware). */
    private void startInApp(File app) throws Exception {
        String lib = getApplicationInfo().nativeLibraryDir;
        File log = new File(app, "state/agent.log");
        log.getParentFile().mkdirs();
        ProcessBuilder pb = new ProcessBuilder(lib + "/libedgeagent.so", "--dir", app.getAbsolutePath(),
                "--genie", new File(getFilesDir(), "genie_bundle").getAbsolutePath(), "--mode", "1",
                "--addr", "0.0.0.0:8000", "--clock-unix", Long.toString(System.currentTimeMillis() / 1000 + clockOffset()));
        pb.environment().put("SCE_GENIE_BIN", lib + "/libgenie_t2t.so");
        pb.environment().put("SCE_GENIE_LD", lib);
        pb.redirectErrorStream(true);
        pb.redirectOutput(ProcessBuilder.Redirect.appendTo(log));
        proc = pb.start();
    }

    /** Seconds to add to the device clock (the QIDK RTC is set to 2023); written by install_app.ps1. */
    private long clockOffset() {
        // The saved offset fixes the 2023 RTC the QIDK boots with. Once NTP has synced the clock (Wi-Fi),
        // adding it again would put the sensor clock years ahead, so it is only used on an unsynced clock.
        if (java.time.Year.now().getValue() >= 2025) return 0;
        try {
            File f = new File(getFilesDir(), "clock_offset_s");
            if (f.exists()) return Long.parseLong(new String(java.nio.file.Files.readAllBytes(f.toPath())).trim());
        } catch (Exception e) {
            Log.w(TAG, "clock offset unreadable", e);
        }
        return 0;
    }

    /** Copies assets/app/** (dashboard + sensors.json) into files/app when the APK version changes. */
    private void syncAssets(File app) throws Exception {
        app.mkdirs();
        String ver = Long.toString(getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime);
        File stamp = new File(app, ".assets_version");
        if (stamp.exists() && ver.equals(new String(java.nio.file.Files.readAllBytes(stamp.toPath())))) {
            return;
        }
        copyTree(getAssets(), "app", app);
        try (OutputStream o = new FileOutputStream(stamp)) {
            o.write(ver.getBytes());
        }
    }

    private static void copyTree(AssetManager am, String path, File dst) throws Exception {
        String[] kids = am.list(path);
        if (kids == null || kids.length == 0) {
            dst.getParentFile().mkdirs();
            try (InputStream in = am.open(path); OutputStream out = new FileOutputStream(dst)) {
                byte[] b = new byte[1 << 16];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
            }
            return;
        }
        dst.mkdirs();
        for (String k : kids) copyTree(am, path + "/" + k, new File(dst, k));
    }

    @Override
    public void onDestroy() {
        if (proc != null) proc.destroy();
        if (worker != null) worker.interrupt();
        if (wake != null && wake.isHeld()) wake.release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
