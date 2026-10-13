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
}
