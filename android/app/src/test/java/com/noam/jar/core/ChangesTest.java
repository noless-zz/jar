package com.noam.jar.core;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;

public class ChangesTest {
    private static final String NOTES = "# What's new\n\n"
            + "0.9.0 | משימות חכמות | Smarter tasks\n"
            + "0.8.2 | העלאה מתוקנת | Upload fixed\n"
            + "0.8.1 | הדבקת קישור | Paste link\n\n"
            + "**Full Changelog**: https://github.com/x/y/compare/v0.8.1...v0.9.0\n";

    @Test
    public void onlyNewerVersionsInMyLanguage() {
        assertEquals(Arrays.asList("Smarter tasks", "Upload fixed"), Changes.since(NOTES, 801, false));
        assertEquals(Arrays.asList("משימות חכמות", "העלאה מתוקנת"), Changes.since(NOTES, 801, true));
        assertEquals(Collections.emptyList(), Changes.since(NOTES, 900, true));
        assertEquals(Collections.emptyList(), Changes.since(null, 0, true));
    }

    @Test
    public void oneLineIsShort() {
        assertEquals("Smarter tasks · Upload fixed · Paste link", Changes.oneLine(NOTES, 0, false, 5));
        assertEquals("Smarter tasks · …", Changes.oneLine(NOTES, 0, false, 1));
    }

    @Test
    public void entriesKeepEachVersion() {
        String notes = "1.11.2 | ג | C\n1.11.1 | ב | B\n1.11.0 | א | A\n";
        java.util.List<String[]> e = Changes.entries(notes, Version.code("1.11.0"), false);
        org.junit.Assert.assertEquals(2, e.size());
        org.junit.Assert.assertArrayEquals(new String[] {"1.11.2", "C"}, e.get(0));
        org.junit.Assert.assertArrayEquals(new String[] {"1.11.1", "ב"}, Changes.entries(notes, Version.code("1.11.0"), true).get(1));
    }
}
