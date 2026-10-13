package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

public class PairingTest {
    // Exactly what the server's /pair page produced in testing.
    private static final String LINK = "jar://pair?v=1&t=test-token-123"
            + "&u=http%3A%2F%2F192.168.1.87%3A8080&u=http%3A%2F%2F100.101.102.103%3A8080"
            + "&u=http%3A%2F%2Fmy-pc.tail1234.ts.net%3A8080";

    @Test
    public void parsesServerLink() {
        PairingLink p = PairingLink.parse(LINK);
        assertEquals("test-token-123", p.token);
        assertEquals(Arrays.asList("http://192.168.1.87:8080", "http://100.101.102.103:8080",
                "http://my-pc.tail1234.ts.net:8080"), p.urls);
    }

    @Test
    public void decodesSpecialCharactersInToken() {
        PairingLink p = PairingLink.parse("jar://pair?v=1&t=tok+en%26x&u=http%3A%2F%2Fa%3A1%2F");
        assertEquals("tok en&x", p.token);
        assertEquals(Arrays.asList("http://a:1"), p.urls);   // trailing slash removed
    }

    @Test
    public void rejectsOtherCodes() {
        assertNull(PairingLink.parse("https://example.com"));
        assertNull(PairingLink.parse("jar://pair?v=2&t=x&u=http%3A%2F%2Fa"));          // unknown version
        assertNull(PairingLink.parse("jar://pair?v=1&u=http%3A%2F%2Fa"));              // no token
        assertEquals(0, PairingLink.parse("jar://pair?v=1&t=x&u=ftp%3A%2F%2Fa").urls.size());   // code only
        assertNull(PairingLink.parse(null));
        assertNull(PairingLink.parse("https://pc.ts.net/v1/join#"));                    // empty
    }

    @Test
    public void lastGoodAddressIsTriedFirst() {
        List<String> urls = Arrays.asList("http://192.168.1.87:8080", "http://100.101.102.103:8080");
        assertEquals(Arrays.asList("http://100.101.102.103:8080", "http://192.168.1.87:8080"),
                ServerList.ordered(urls, "http://100.101.102.103:8080"));
        assertEquals(urls, ServerList.ordered(urls, "http://gone:1"));   // stale last-good ignored
        assertEquals(urls, ServerList.ordered(urls, null));
    }

    @Test
    public void storageRoundTrip() {
        List<String> urls = Arrays.asList("http://a:1", "http://b:2");
        assertEquals(urls, ServerList.split(ServerList.join(urls)));
        assertTrue(ServerList.split("").isEmpty());
    }

    @Test
    public void recognisesTailscaleAddresses() {
        assertTrue(ServerList.isTailscale("http://100.101.102.103:8080"));
        assertTrue(ServerList.isTailscale("http://my-pc.tail1234.ts.net:8080"));
        assertFalse(ServerList.isTailscale("http://192.168.1.87:8080"));
        assertFalse(ServerList.isTailscale("http://100.1.2.3:8080"));     // 100.x outside 100.64/10
        assertFalse(ServerList.isTailscale("http://10.0.2.2:8080"));
        assertFalse(ServerList.isTailscale("https://my-pc.tail1234.ts.net"));   // public Funnel address
        assertTrue(ServerList.isPublic("https://my-pc.tail1234.ts.net"));
        assertFalse(ServerList.isPublic("http://192.168.1.87:8080"));
    }

    @Test
    public void pcAddressesMergeIntoSavedOnes() {
        java.util.List<String> saved = java.util.Arrays.asList("http://192.168.1.87:8080", "http://100.101.102.103:8080");
        java.util.List<String> pc = java.util.Arrays.asList("http://192.168.1.87:8080", "https://pc.ts.net/",
                "http://100.101.102.103:8080");
        assertEquals(java.util.Arrays.asList("http://192.168.1.87:8080", "https://pc.ts.net",
                "http://100.101.102.103:8080"), ServerList.merge(saved, pc));
        assertEquals(java.util.Arrays.asList("https://pc.ts.net", "http://my-typed:8080"),
                ServerList.merge(java.util.Collections.singletonList("http://my-typed:8080"),
                        java.util.Collections.singletonList("https://pc.ts.net")));
    }

    @Test
    public void parsesJoinPageAndWholeMessage() {
        String q = "v=1&t=abc&u=http%3A%2F%2F192.168.1.5%3A8080&u=https%3A%2F%2Fpc.ts.net";
        PairingLink p = PairingLink.parse("https://pc.ts.net/v1/join#" + q);
        assertEquals("abc", p.token);
        assertEquals(Arrays.asList("http://192.168.1.5:8080", "https://pc.ts.net"), p.urls);
        String msg = "היי ליבנה!\n\n3. לוחצים על הקישור האישי שלך:\nhttps://pc.ts.net/v1/join#" + q + "\nוזהו";
        assertEquals("abc", PairingLink.parse(msg).token);
        assertEquals("abc", PairingLink.parse("copy: jar://pair?" + q + " thanks").token);
    }

    @Test
    public void deviceNameIsHeaderSafe() {
        assertEquals("phone", ServerList.cleanDeviceId("ליבנה"));
        assertEquals("livne-s23", ServerList.cleanDeviceId(" livne s23 "));
        assertEquals("phone-01", ServerList.cleanDeviceId("phone-01"));
        assertEquals(32, ServerList.cleanDeviceId("x".repeat(40)).length());
    }
}
