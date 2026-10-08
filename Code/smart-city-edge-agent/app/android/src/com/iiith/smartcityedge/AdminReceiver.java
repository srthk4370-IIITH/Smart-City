package com.iiith.smartcityedge;

import android.app.admin.DeviceAdminReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Device-admin receiver. While the app is an active device administrator Android refuses to uninstall
 * it (launcher, Settings and `adb uninstall` all fail) until it is deactivated under
 * Settings > Security > Device admin apps. It requests no policies; it exists only so the monitor and
 * its on-device model backup cannot be removed by accident (e.g. while the QIDK is lent out).
 */
public class AdminReceiver extends DeviceAdminReceiver {
    @Override
    public CharSequence onDisableRequested(Context c, Intent i) {
        return "Smart City Edge keeps the on-device NPU monitor and its model backup. Deactivate only if you "
                + "really want to remove it.";
    }
}
