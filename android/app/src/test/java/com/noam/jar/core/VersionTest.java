package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class VersionTest {
    @Test
    public void codesMatchBuildGradle() {
        assertEquals(300, Version.code("v0.3.0"));
        assertEquals(10203, Version.code("1.2.3"));
        assertEquals(10200, Version.code("v1.2"));
        assertEquals(10200, Version.code("v1.2.rc1"));
        assertEquals(-1, Version.code("latest"));
        assertEquals(-1, Version.code(null));
        assertEquals(-1, Version.code("v1.100.0"));
    }

    @Test
    public void newer() {
        assertTrue(Version.newer("v0.3.1", 300));
        assertFalse(Version.newer("v0.3.0", 300));
        assertFalse(Version.newer("nightly", 300));
    }
}
