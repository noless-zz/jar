package com.noam.jar.core;

import java.io.UnsupportedEncodingException;
import java.net.URLDecoder;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The link inside the dashboard's pairing QR code:
 *   jar://pair?v=1&t=<token>&u=http://192.168.1.87:8080&u=http://100.101.102.103:8080
 * or the WhatsApp invite's join page, which carries the same fields after #:
 *   https://my-pc.tailnet.ts.net/v1/join#v=1&t=<token>&u=...
 * Either may sit inside a longer pasted text (the whole invite message). Parsed by hand
 * (no Android Uri) so it is unit-tested on the JVM.
 */
public final class PairingLink {
    public final String token;
    public final List<String> urls;

    private PairingLink(String token, List<String> urls) {
        this.token = token;
        this.urls = Collections.unmodifiableList(urls);
    }

    /** Returns null for anything that isn't a valid Jar pairing link. */
    public static PairingLink parse(String text) {
        if (text == null) return null;
        String query = null;
        String lower = text.toLowerCase(java.util.Locale.ROOT);
        for (String marker : new String[] {"jar://pair?", "/v1/join#"}) {
            int at = lower.indexOf(marker);
            if (at < 0) continue;
            int start = at + marker.length(), end = start;
            while (end < text.length() && !Character.isWhitespace(text.charAt(end))) end++;
            query = text.substring(start, end);
            break;
        }
        if (query == null) return null;
        String token = null;
        String version = null;
        List<String> urls = new ArrayList<>();
        for (String part : query.split("&")) {
            int eq = part.indexOf('=');
            if (eq <= 0) continue;
            String key = part.substring(0, eq);
            String value = decode(part.substring(eq + 1));
            if (value == null) return null;
            switch (key) {
                case "v": version = value; break;
                case "t": token = value; break;
                case "u":
                    String u = value.trim();
                    while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
                    if ((u.startsWith("http://") || u.startsWith("https://")) && !urls.contains(u)) urls.add(u);
                    break;
                default: break;  // newer servers may add fields; ignore them
            }
        }
        if (!"1".equals(version) || token == null || token.isEmpty() || urls.isEmpty()) return null;
        return new PairingLink(token, urls);
    }

    private static String decode(String v) {
        try {
            return URLDecoder.decode(v, "UTF-8");
        } catch (UnsupportedEncodingException | IllegalArgumentException e) {
            return null;
        }
    }
}
