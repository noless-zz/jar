package com.noam.jar.core;

import java.util.ArrayList;
import java.util.List;

/**
 * The PC's addresses, in the order to try them: the last one that worked first
 * (so at home the LAN address answers at once, and away Tailscale does), then the rest
 * in pairing order. Plain Java, unit-tested.
 */
public final class ServerList {
    private ServerList() {}

    public static List<String> ordered(List<String> urls, String lastGood) {
        List<String> out = new ArrayList<>();
        if (lastGood != null && !lastGood.isEmpty() && urls.contains(lastGood)) out.add(lastGood);
        for (String u : urls) if (!out.contains(u)) out.add(u);
        return out;
    }

    public static String join(List<String> urls) {
        return String.join("\n", urls);
    }

    public static List<String> split(String stored) {
        List<String> out = new ArrayList<>();
        if (stored == null) return out;
        for (String line : stored.split("\n")) {
            String u = line.trim();
            if (!u.isEmpty() && !out.contains(u)) out.add(u);
        }
        return out;
    }

    /** "Tailscale" or "home network", for messages like "Connected via Tailscale". */
    public static boolean isTailscale(String url) {
        String host = url.replaceFirst("^https?://", "").replaceFirst("[:/].*$", "");
        if (host.endsWith(".ts.net")) return true;
        String[] p = host.split("\\.");
        if (p.length != 4) return false;
        try {
            int a = Integer.parseInt(p[0]);
            int b = Integer.parseInt(p[1]);
            return a == 100 && b >= 64 && b <= 127;   // 100.64.0.0/10, Tailscale's range
        } catch (NumberFormatException e) {
            return false;
        }
    }
}
