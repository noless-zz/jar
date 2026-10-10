package com.noam.jar.core;

/**
 * Release tags ("v1.2.3") to version codes, the same formula as app/build.gradle:
 * major*10000 + minor*100 + patch. -1 when the tag isn't a version.
 */
public final class Version {
    private Version() {}

    public static int code(String tag) {
        if (tag == null) return -1;
        String t = tag.trim();
        if (t.startsWith("v") || t.startsWith("V")) t = t.substring(1);
        String[] p = t.split("[.\\-]");
        try {
            int major = Integer.parseInt(p[0]);
            int minor = p.length > 1 ? Integer.parseInt(p[1]) : 0;
            int patch = 0;
            if (p.length > 2) {
                try {
                    patch = Integer.parseInt(p[2]);
                } catch (NumberFormatException ignored) {
                    patch = 0;     // "1.2.rc1": treat as 1.2.0
                }
            }
            if (minor > 99 || patch > 99 || major < 0) return -1;
            return major * 10000 + minor * 100 + patch;
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    public static boolean newer(String tag, int installedCode) {
        int c = code(tag);
        return c > 0 && c > installedCode;
    }
}
