package com.iiith.smartcityedge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Starts the on-device monitor after a reboot, so the QIDK needs no laptop at all. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction())) EdgeService.start(c);
    }
}
