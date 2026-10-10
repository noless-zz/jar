package com.noam.jar.core;

import java.io.File;

/** One recorded memo waiting in the queue: the WAV plus its metadata. */
public final class Memo {
    public final String id;
    public final File wav;
    public final String recordedAt;   // ISO-8601 UTC, e.g. 2026-10-08T09:41:05Z
    public final long durationMs;

    public Memo(String id, File wav, String recordedAt, long durationMs) {
        this.id = id;
        this.wav = wav;
        this.recordedAt = recordedAt;
        this.durationMs = durationMs;
    }
}
