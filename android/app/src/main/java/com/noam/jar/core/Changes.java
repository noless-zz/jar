package com.noam.jar.core;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "What's new" from the release notes, which carry android/CHANGES.md:
 *   0.8.2 | עברית | English
 * Only the versions newer than the installed one, newest first, in the phone's language.
 */
public final class Changes {
    private Changes() {}

    private static final Pattern LINE =
            Pattern.compile("(?m)^\\s*[-*]?\\s*v?(\\d+\\.\\d+\\.\\d+)\\s*\\|([^|\\n]*)\\|([^\\n]*)$");

    public static List<String> since(String notes, int installedCode, boolean hebrew) {
        List<String> out = new ArrayList<>();
        if (notes == null) return out;
        Matcher m = LINE.matcher(notes);
        while (m.find()) {
            if (Version.code(m.group(1)) <= installedCode) continue;
            String text = (hebrew ? m.group(2) : m.group(3)).trim();
            if (text.isEmpty()) text = (hebrew ? m.group(3) : m.group(2)).trim();
            if (!text.isEmpty() && !out.contains(text)) out.add(text);
        }
        return out;
    }

    /** Each version newer than the installed one, newest first: {"1.11.2", "what changed"}. */
    public static List<String[]> entries(String notes, int installedCode, boolean hebrew) {
        List<String[]> out = new ArrayList<>();
        if (notes == null) return out;
        Matcher m = LINE.matcher(notes);
        while (m.find()) {
            if (Version.code(m.group(1)) <= installedCode) continue;
            String text = (hebrew ? m.group(2) : m.group(3)).trim();
            if (text.isEmpty()) text = (hebrew ? m.group(3) : m.group(2)).trim();
            if (!text.isEmpty()) out.add(new String[] {m.group(1), text});
        }
        return out;
    }

    /** One line for the update bar: "x · y · z" (at most {@code max} items, then "…"). */
    public static String oneLine(String notes, int installedCode, boolean hebrew, int max) {
        List<String> all = since(notes, installedCode, hebrew);
        List<String> shown = all.size() > max ? all.subList(0, max) : all;
        String s = String.join(" · ", shown);
        return all.size() > max ? s + " · …" : s;
    }
}
