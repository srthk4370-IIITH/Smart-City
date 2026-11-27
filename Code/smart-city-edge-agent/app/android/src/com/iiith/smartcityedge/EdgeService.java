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
                // genie_bundle_ft_4096 is no longer used (v2 runs on htpd): restoring it meant a 2.5 GB copy
                // out of FUSE /sdcard right after boot, and multi-GB FUSE copies stall system_server until the
                // watchdog reboots the board (2026-10-22: two reboots after large copies)
                + "for d in genie_bundle genie_bundle_ft; do [ -d $K/$d ] || continue; bad=0; "
                + "for f in llama_v3_2_3b_instruct_part_1_of_3.bin llama_v3_2_3b_instruct_part_2_of_3.bin "
                + "llama_v3_2_3b_instruct_part_3_of_3.bin smartcity_agent.json tokenizer.json; do "
                + "[ \"$(stat -c %s $T/$d/$f 2>/dev/null)\" = \"$(stat -c %s $K/$d/$f 2>/dev/null)\" ] || bad=1; done; "
                + "if [ $bad = 1 ]; then mkdir -p $T/$d && cp -r $K/$d/. $T/$d/ && echo RESTORED_$d; fi; done; ";
    }

    private String backendStart(File ext, String lib, long now) {
        return "D=/data/local/tmp/smart_city_edge; L=" + lib + "; X=" + ext.getAbsolutePath() + "; "
                + "mkdir -p $D/state $D/data $D/web; "
                // the backend persists the network-synced offset (clocknet.go); prefer it when newer than the saved one, only on an unsynced (<2025) RTC
                + "NOW=" + now + "; P=$D/state/clock_offset_s; S=" + getFilesDir().getAbsolutePath() + "/clock_offset_s; "
                + "if [ \"$(date +%Y)\" -lt 2025 ] && [ -s $P ] && { [ ! -f $S ] || [ $P -nt $S ]; }; then O=$(cat $P); case $O in \"\"|*[!0-9]*) ;; *) NOW=$(( $(date +%s) + O ));; esac; fi; "
                + "cmp -s $L/libedgeagent.so $D/edge-agent || { cp $L/libedgeagent.so $D/edge-agent.new && mv $D/edge-agent.new $D/edge-agent; }; "
                + "chmod 755 $D/edge-agent; cp -r $X/web/. $D/web/; cp $X/data/*.json $D/data/; "
                // genied (persistent Genie dialog) ships in the APK too; edge-agent launches and
                // supervises it. Kill the old one so a new APK's daemon replaces it cleanly.
                + "if [ -f $L/libgenied.so ]; then cmp -s $L/libgenied.so $D/genied || { cp $L/libgenied.so $D/genied.new && mv $D/genied.new $D/genied; }; chmod 755 $D/genied; fi; "
                + "pkill -x genied; pkill -x edge-agent; sleep 1; "
                // append (rotated at 4 MB): the log from before a board reset used to be overwritten here
                + "cd $D && { [ \"$(stat -c %s state/agent.log 2>/dev/null || echo 0)\" -gt 4194304 ] && mv -f state/agent.log state/agent.log.1; true; } && "
                + "(setsid nohup ./edge-agent --dir $D --genie /data/local/tmp/genie_bundle --mode 3 "
                + "--clock-unix $NOW >> state/agent.log 2>&1 < /dev/null &); "
                + "sleep 2; pgrep -x edge-agent >/dev/null && echo STARTED || echo FAILED";
    }

    // UX v34: one notification per incident, updated in place (tag = incident id), only while the
    // dashboard is not in front: a new Critical incident once its analysis has finished, a re-check
    // that made it worse, and the one reminder for a critical incident nobody took within 15 min.
    // Tapping opens that incident. Taken (in progress) or closed incidents lose their notification.
    // 2026-11-27: + "I'm on it" / "Open" actions (IncidentActionReceiver), a quieter "Warnings" channel
    // for new warning and sensor-fault incidents (once each), the site place (building, level) from
    // /api/topology, and a group summary when more than one incident notification is showing.
    private final java.util.Set<String> seenIncidents = new java.util.HashSet<>();
    private final java.util.Set<String> critNotified = new java.util.HashSet<>();
    private final java.util.Set<String> warnNotified = new java.util.HashSet<>();
    private final java.util.Set<String> remindNotified = new java.util.HashSet<>();
    private final java.util.Map<String, Long> worseNotified = new java.util.HashMap<>();
    private final java.util.Set<String> posted = new java.util.HashSet<>();
    private boolean incidentsPrimed = false;
    static final int NOTIF_ID = 2001;
    static final int SUMMARY_ID = 2002;
    static final String CH_ALERTS = "alerts";
    static final String CH_WARNINGS = "warnings";
    static final String GROUP = "com.iiith.smartcityedge.INCIDENTS";

    private void notifyNewIncidents() {
        try {
            org.json.JSONArray arr = new org.json.JSONArray(httpGet("http://127.0.0.1:8000/api/incidents?limit=50"));
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm.getNotificationChannel(CH_ALERTS) == null) {
                nm.createNotificationChannel(new NotificationChannel(CH_ALERTS, "Sensor alerts",
                        NotificationManager.IMPORTANCE_HIGH));
            }
            if (nm.getNotificationChannel(CH_WARNINGS) == null) {
                NotificationChannel w = new NotificationChannel(CH_WARNINGS, "Warnings",
                        NotificationManager.IMPORTANCE_DEFAULT);
                w.setDescription("New warning-level and sensor-fault incidents (once each)");
                nm.createNotificationChannel(w);
            }
            boolean background = !MainActivity.foreground;
            boolean postedNow = false;
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.getJSONObject(i);
                String id = o.optString("id");
                if (id.isEmpty()) continue;
                String wf = o.optString("workflow", "");
                String sev = o.optString("severity", "");
                boolean done = !"running".equals(o.optString("state"));
                boolean sevFinal = o.optBoolean("severity_final", true);
                boolean critical = done && "critical".equals(sev) && sevFinal;
                // severity is critical | warning | normal | sensor_fault; label can also say sensor_fault (reason.go)
                boolean fault = done && ("sensor_fault".equals(sev) || "sensor_fault".equals(o.optString("label")));
                boolean warning = done && !fault && "warning".equals(sev) && sevFinal;
                long worse = o.optLong("worse_at", 0);
                boolean reminded = o.optBoolean("reminded", false);
                seenIncidents.add(id);
                if (!incidentsPrimed) { // incidents present at start are not re-announced
                    if (critical) critNotified.add(id);
                    if (warning || fault) warnNotified.add(id);
                    if (reminded) remindNotified.add(id);
                    worseNotified.put(id, worse);
                    continue;
                }
                if ("in_progress".equals(wf) || "closed".equals(wf)) { // someone took it, or it is over
                    if (posted.remove(id)) nm.cancel(id, NOTIF_ID);
                    if (critical) critNotified.add(id);
                    if (warning || fault) warnNotified.add(id);
                    worseNotified.put(id, worse);
                    continue;
                }
                String text = null;
                String channel = CH_ALERTS;
                Long seenWorse = worseNotified.get(id);
                if (worse > 0 && (seenWorse == null || worse > seenWorse)) {
                    worseNotified.put(id, worse);
                    text = "Got worse: now " + sev.replace('_', ' ') + (o.optString("owner").isEmpty() ? "" : " - please acknowledge again");
                } else if (seenWorse == null) {
                    worseNotified.put(id, worse);
                }
                if (text == null && reminded && remindNotified.add(id)) text = "Still needs a decision (critical for 15 min)";
                if (text == null && critical && critNotified.add(id)) {
                    text = fault ? "Critical sensor fault" : "New critical incident";
                    warnNotified.add(id); // not announced again as a sensor fault
                }
                if (text == null && (warning || fault) && warnNotified.add(id)) {
                    text = fault ? "Sensor fault" : "New warning";
                    channel = CH_WARNINGS;
                }
                if (text == null || !background) continue; // in front: the dashboard alerts by itself
                String place = placeOf(o.optJSONArray("sensors"));
                String body = o.optString("title");
                if (!place.isEmpty()) body = place + (body.isEmpty() ? "" : " - " + body);
                nm.notify(id, NOTIF_ID, incidentNotification(this, channel, id, text + " - " + id, body, true).build());
                posted.add(id);
                postedNow = true;
            }
            incidentsPrimed = true;
            if (postedNow) updateSummary(nm);
            else if (countActive(nm) <= 1) nm.cancel(SUMMARY_ID); // the rest were taken, closed or swiped away
        } catch (Exception ignored) {
        }
    }

    /**
     * One incident notification: tap or "Open" opens the incident, "I'm on it" acknowledges it
     * (IncidentActionReceiver). Shared with the receiver, which re-posts it with the ack result.
     */
    static Notification.Builder incidentNotification(Context c, String channel, String id, String title, String text,
                                                     boolean withAck) {
        Intent open = new Intent(c, MainActivity.class)
                .putExtra(MainActivity.EXTRA_INCIDENT, id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, id.hashCode(), open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = new Notification.Builder(c, channel)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setSmallIcon(CH_WARNINGS.equals(channel) ? android.R.drawable.stat_sys_warning : android.R.drawable.stat_notify_error)
                .setCategory(Notification.CATEGORY_ALARM)
                .setGroup(GROUP)
                .setOnlyAlertOnce(!withAck) // the ack result replaces the alert quietly
                .setContentIntent(pi).setAutoCancel(true);
        if (withAck) {
            Intent ack = new Intent(c, IncidentActionReceiver.class)
                    .setAction(IncidentActionReceiver.ACTION_ACK)
                    .putExtra(IncidentActionReceiver.EXTRA_ID, id)
                    .putExtra(IncidentActionReceiver.EXTRA_CHANNEL, channel)
                    .putExtra(IncidentActionReceiver.EXTRA_TITLE, title)
                    .putExtra(IncidentActionReceiver.EXTRA_TEXT, text);
            PendingIntent api = PendingIntent.getBroadcast(c, id.hashCode() ^ 0x5ce, ack,
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            b.addAction(new Notification.Action.Builder(null, "I'm on it", api).build());
        }
        b.addAction(new Notification.Action.Builder(null, "Open", pi).build());
        return b;
    }

    /** Incident notifications currently showing (the summary itself excluded). */
    private static int countActive(NotificationManager nm) {
        int n = 0;
        for (android.service.notification.StatusBarNotification s : nm.getActiveNotifications()) {
            if (s.getId() == NOTIF_ID) n++;
        }
        return n;
    }

    /** Group summary (shown by Android as the collapsed group) once more than one incident is showing. */
    private void updateSummary(NotificationManager nm) {
        java.util.List<String> lines = new java.util.ArrayList<>();
        boolean anyAlert = false;
        for (android.service.notification.StatusBarNotification s : nm.getActiveNotifications()) {
            if (s.getId() != NOTIF_ID) continue;
            Notification n = s.getNotification();
            if (CH_ALERTS.equals(n.getChannelId())) anyAlert = true;
            CharSequence t = n.extras.getCharSequence(Notification.EXTRA_TITLE);
            if (t != null) lines.add(t.toString());
        }
        if (lines.size() <= 1) {
            nm.cancel(SUMMARY_ID);
            return;
        }
        Notification.InboxStyle st = new Notification.InboxStyle()
                .setBigContentTitle(lines.size() + " incidents need attention");
        for (int i = 0; i < Math.min(6, lines.size()); i++) st.addLine(lines.get(i));
        if (lines.size() > 6) st.setSummaryText("+" + (lines.size() - 6) + " more");
        PendingIntent home = PendingIntent.getActivity(this, SUMMARY_ID,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        nm.notify(SUMMARY_ID, new Notification.Builder(this, anyAlert ? CH_ALERTS : CH_WARNINGS)
                .setContentTitle(lines.size() + " incidents need attention")
                .setContentText(String.join(", ", lines))
                .setStyle(st)
                .setSmallIcon(anyAlert ? android.R.drawable.stat_notify_error : android.R.drawable.stat_sys_warning)
                .setGroup(GROUP).setGroupSummary(true)
                .setGroupAlertBehavior(Notification.GROUP_ALERT_CHILDREN) // the children already alerted
                .setContentIntent(home).setAutoCancel(true).build());
    }

    // node -> "KH building, level 03", from /api/topology (sensors.json building/level), refreshed every 10 min.
    // The incident summary itself has no place field; it lists flagged sensors as "node metric".
    private final java.util.Map<String, String> nodePlace = new java.util.HashMap<>();
    private long nodePlaceAt = 0;

    private String placeOf(org.json.JSONArray sensors) {
        if (sensors == null || sensors.length() == 0) return "";
        long now = System.currentTimeMillis();
        if (nodePlace.isEmpty() || now - nodePlaceAt > 600_000) {
            try {
                org.json.JSONObject b = new org.json.JSONObject(httpGet("http://127.0.0.1:8000/api/topology"))
                        .getJSONObject("buildings");
                java.util.Map<String, String> m = new java.util.HashMap<>();
                for (java.util.Iterator<String> bi = b.keys(); bi.hasNext(); ) {
                    String bld = bi.next();
                    org.json.JSONObject levels = b.getJSONObject(bld);
                    for (java.util.Iterator<String> li = levels.keys(); li.hasNext(); ) {
                        String lv = li.next();
                        org.json.JSONArray nodes = levels.getJSONArray(lv);
                        for (int k = 0; k < nodes.length(); k++) {
                            String p = bld.isEmpty() ? "" : bld + " building" + (lv.isEmpty() ? "" : ", level " + lv);
                            m.put(nodes.getJSONObject(k).optString("node"), p);
                        }
                    }
                }
                nodePlace.clear();
                nodePlace.putAll(m);
                nodePlaceAt = now;
            } catch (Exception e) {
                nodePlaceAt = now - 540_000; // retry in about a minute
            }
        }
        java.util.LinkedHashSet<String> places = new java.util.LinkedHashSet<>();
        for (int i = 0; i < sensors.length(); i++) {
            String s = sensors.optString(i).trim();
            int sp = s.indexOf(' ');
            String p = nodePlace.get(sp > 0 ? s.substring(0, sp) : s);
            if (p != null && !p.isEmpty()) places.add(p);
        }
        if (places.isEmpty()) return "";
        java.util.Iterator<String> it = places.iterator();
        String first = it.next();
        return places.size() == 1 ? first : first + " +" + (places.size() - 1) + " more";
    }

    private static String httpGet(String url) throws java.io.IOException {
        java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
        c.setConnectTimeout(800);
        c.setReadTimeout(3000);
        try {
            return new String(c.getInputStream().readAllBytes(), "UTF-8");
        } finally {
            c.disconnect();
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
