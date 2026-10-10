package com.noam.jar;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;

/**
 * What the app can know about Tailscale without controlling it (Android doesn't let
 * one app configure another's VPN): is it installed, and is a VPN up right now.
 * Signing in and connecting stay in the Tailscale app, one tap away.
 */
public final class TailscaleHelper {
    public static final String PACKAGE = "com.tailscale.ipn";

    public enum State { NOT_INSTALLED, INSTALLED_OFF, CONNECTED }

    private TailscaleHelper() {}

    public static State state(Context c) {
        if (!installed(c)) return State.NOT_INSTALLED;
        return vpnActive(c) ? State.CONNECTED : State.INSTALLED_OFF;
    }

    public static boolean installed(Context c) {
        try {
            c.getPackageManager().getPackageInfo(PACKAGE, 0);   // needs <queries> in the manifest
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    /** True when any VPN carries traffic; with Tailscale installed that is, in practice, Tailscale. */
    @SuppressWarnings("deprecation")   // getAllNetworks: still the simplest one-shot check
    public static boolean vpnActive(Context c) {
        ConnectivityManager cm = c.getSystemService(ConnectivityManager.class);
        if (cm == null) return false;
        for (Network n : cm.getAllNetworks()) {
            NetworkCapabilities nc = cm.getNetworkCapabilities(n);
            if (nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return true;
        }
        return false;
    }

    /** Opens Tailscale if installed, else its Play Store page. */
    public static void openOrInstall(Activity a) {
        Intent launch = a.getPackageManager().getLaunchIntentForPackage(PACKAGE);
        if (launch != null) {
            a.startActivity(launch);
            return;
        }
        try {
            a.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=" + PACKAGE)));
        } catch (ActivityNotFoundException e) {
            a.startActivity(new Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://play.google.com/store/apps/details?id=" + PACKAGE)));
        }
    }
}
