package com.noam.jar.core;

/**
 * The 44-byte header of a plain PCM WAV file: 16 kHz, mono, 16-bit, exactly what
 * the pendant firmware writes. We write a placeholder first and patch the sizes
 * when recording ends, because we don't know the length up front.
 */
public final class Wav {
    public static final int HEADER_BYTES = 44;
    public static final int SAMPLE_RATE = 16000;
    public static final int BYTES_PER_SECOND = SAMPLE_RATE * 2;

    private Wav() {}

    public static byte[] header(long dataBytes) {
        byte[] h = new byte[HEADER_BYTES];
        ascii(h, 0, "RIFF");
        le32(h, 4, 36 + dataBytes);
        ascii(h, 8, "WAVE");
        ascii(h, 12, "fmt ");
        le32(h, 16, 16);              // size of the fmt chunk
        le16(h, 20, 1);               // PCM
        le16(h, 22, 1);               // mono
        le32(h, 24, SAMPLE_RATE);
        le32(h, 28, BYTES_PER_SECOND);
        le16(h, 32, 2);               // bytes per sample frame
        le16(h, 34, 16);              // bits per sample
        ascii(h, 36, "data");
        le32(h, 40, dataBytes);
        return h;
    }

    public static long durationMs(long dataBytes) {
        return dataBytes * 1000L / BYTES_PER_SECOND;
    }

    private static void ascii(byte[] b, int at, String s) {
        for (int i = 0; i < 4; i++) b[at + i] = (byte) s.charAt(i);
    }

    private static void le16(byte[] b, int at, int v) {
        b[at] = (byte) v;
        b[at + 1] = (byte) (v >> 8);
    }

    private static void le32(byte[] b, int at, long v) {
        for (int i = 0; i < 4; i++) b[at + i] = (byte) (v >> (8 * i));
    }
}
