package com.iiith.smartcityedge;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * "I'm on it" on an incident notification (EdgeService.postIncident): records the acknowledgement on the
 * local backend exactly like the dashboard's "I'm on it" button (POST /api/incidents/{id}/ack, workflow.go),
 * off the main thread, then replaces the notification with the result. Not exported: only our own
 * PendingIntents reach it.
 */
public class IncidentActionReceiver extends BroadcastReceiver {
    static final String ACTION_ACK = "com.iiith.smartcityedge.action.ACK_INCIDENT";
    static final String EXTRA_ID = "incident";
    static final String EXTRA_CHANNEL = "channel";
    static final String EXTRA_TITLE = "title";
    static final String EXTRA_TEXT = "text";
    /** The dashboard has no default operator (each person picks a name); acks from a notification use this. */
    static final String OPERATOR = "on-call (notification)";

    @Override
    public void onReceive(Context ctx, Intent in) {
        if (!ACTION_ACK.equals(in.getAction())) return;
        final String id = in.getStringExtra(EXTRA_ID);
        if (id == null || !id.matches("INC-\\d{1,8}")) return; // it ends up in the request path
        final Context app = ctx.getApplicationContext();
        final String channel = in.getStringExtra(EXTRA_CHANNEL);
        final String title = in.getStringExtra(EXTRA_TITLE);
        final String text = in.getStringExtra(EXTRA_TEXT);
        final PendingResult pr = goAsync();
        new Thread(() -> {
            try {
                String err = ack(id);
                NotificationManager nm = app.getSystemService(NotificationManager.class);
                if (err == null) {
                    // short-lived confirmation; the next EdgeService poll sees workflow=in_progress and clears it anyway
                    nm.notify(id, EdgeService.NOTIF_ID, EdgeService.incidentNotification(app,
                            channel != null ? channel : EdgeService.CH_ALERTS, id,
                            "You're on it - " + id, text, false)
                            .setTimeoutAfter(8000).build());
                } else {
                    nm.notify(id, EdgeService.NOTIF_ID, EdgeService.incidentNotification(app,
                            channel != null ? channel : EdgeService.CH_ALERTS, id,
                            title != null ? title : id, "Could not record \"I'm on it\": " + err
                                    + (text != null && !text.isEmpty() ? "\n" + text : ""), true).build());
                }
            } catch (Exception e) {
                Log.w(EdgeService.TAG, "ack from notification failed", e);
            } finally {
                pr.finish();
            }
        }, "incident-ack").start();
    }

    /** null on success, else a short reason for the notification. */
    private static String ack(String id) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("http://127.0.0.1:8000/api/incidents/" + id + "/ack").openConnection();
            c.setConnectTimeout(2000);
            c.setReadTimeout(5000);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("X-Requested-With", "SmartCityEdge-notification"); // csrf_strict profiles
            byte[] body = new org.json.JSONObject().put("operator", OPERATOR).toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream o = c.getOutputStream()) {
                o.write(body);
            }
            int code = c.getResponseCode();
            if (code == 200) return null;
            String msg = "";
            InputStream es = c.getErrorStream();
            if (es != null) {
                try (InputStream e = es) {
                    msg = new String(e.readAllBytes(), StandardCharsets.UTF_8).trim();
                }
            }
            if (msg.length() > 120) msg = msg.substring(0, 120);
            return msg.isEmpty() ? "HTTP " + code : msg;
        } catch (Exception e) {
            return "backend not reachable";
        } finally {
            if (c != null) c.disconnect();
        }
    }
}
