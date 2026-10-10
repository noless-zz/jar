package com.noam.jar.core;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class UploadResultTest {
    private static final String SHA = "3f806962fcdcc982acaca0e5180c701391a59c2635d82e4b0660dc148c01f528";

    @Test
    public void deletesOnlyWhenServerConfirmsSameChecksum() {
        assertEquals(UploadResult.DELETE_LOCAL, UploadResult.decide(201, SHA, SHA));
        assertEquals(UploadResult.DELETE_LOCAL, UploadResult.decide(200, SHA, SHA.toUpperCase()));  // duplicate
        assertEquals(UploadResult.RETRY, UploadResult.decide(201, SHA, "00"));
        assertEquals(UploadResult.RETRY, UploadResult.decide(201, SHA, ""));
    }

    @Test
    public void transientProblemsRetry() {
        assertEquals(UploadResult.RETRY, UploadResult.decide(-1, SHA, ""));   // no connection
        assertEquals(UploadResult.RETRY, UploadResult.decide(422, SHA, ""));  // damaged in transit
        assertEquals(UploadResult.RETRY, UploadResult.decide(500, SHA, ""));
        assertEquals(UploadResult.RETRY, UploadResult.decide(503, SHA, ""));
    }

    @Test
    public void permanentRefusalsAreFlagged() {
        assertEquals(UploadResult.KEEP_AND_FLAG, UploadResult.decide(401, SHA, ""));
        assertEquals(UploadResult.KEEP_AND_FLAG, UploadResult.decide(409, SHA, ""));
        assertEquals(UploadResult.KEEP_AND_FLAG, UploadResult.decide(400, SHA, ""));
    }
}
