package com.noam.jar.core;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;

/**
 * The on-phone memo queue, laid out exactly like the pendant's SD card:
 *   <id>.wav.part  while recording (survives a crash, fixed up on next start)
 *   <id>.wav + <id>.properties  once finished, until the server confirms it
 * Plain Java (no Android imports) so it is unit-tested on the JVM.
 */
public final class MemoQueue {
    private static final String PART = ".wav.part";
    private static final String WAV = ".wav";
    private static final String META = ".properties";
    private static final SecureRandom RANDOM = new SecureRandom();

    private final File dir;

    public MemoQueue(File dir) {
        this.dir = dir;
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
    }

    /** 16 lowercase hex characters, the same id format the firmware uses. */
    public static String newId() {
        byte[] b = new byte[8];
        RANDOM.nextBytes(b);
        return hex(b);
    }

    public File partFile(String id) {
        return new File(dir, id + PART);
    }

    /** Called when recording stops: patch the WAV header, save metadata, make it visible to uploads. */
    public boolean finish(String id, String recordedAt) throws IOException {
        File part = partFile(id);
        long dataBytes = fixHeader(part);
        if (dataBytes <= 0) {
            //noinspection ResultOfMethodCallIgnored
            part.delete();
            return false;
        }
        writeMeta(id, recordedAt, Wav.durationMs(dataBytes));
        return part.renameTo(new File(dir, id + WAV));
    }

    /** Throws away a recording that was too short to be a real memo. */
    public void discard(String id) {
        //noinspection ResultOfMethodCallIgnored
        partFile(id).delete();
    }

    /**
     * A recording cut off by a crash or a killed process is left as .wav.part.
     * Keep whatever audio made it to disk, as the firmware does after a power loss.
     */
    public int recoverPartials(String fallbackTime) throws IOException {
        int recovered = 0;
        for (File f : list(PART)) {
            String id = f.getName().substring(0, f.getName().length() - PART.length());
            if (finish(id, fallbackTime)) recovered++;
        }
        return recovered;
    }

    /** Finished memos, oldest first. */
    public List<Memo> ready() {
        List<Memo> out = new ArrayList<>();
        for (File wav : list(WAV)) {
            String id = wav.getName().substring(0, wav.getName().length() - WAV.length());
            Properties p = readMeta(id);
            long duration = parseLong(p.getProperty("duration_ms"),
                    Wav.durationMs(Math.max(0, wav.length() - Wav.HEADER_BYTES)));
            out.add(new Memo(id, wav, p.getProperty("recorded_at", ""), duration));
        }
        return out;
    }

    public int readyCount() {
        return list(WAV).size();
    }

    /** Only after the server has confirmed the same checksum. */
    public void remove(Memo memo) {
        //noinspection ResultOfMethodCallIgnored
        memo.wav.delete();
        //noinspection ResultOfMethodCallIgnored
        new File(dir, memo.id + META).delete();
    }

    public static String sha256(File file) throws IOException {
        try (InputStream in = new FileInputStream(file)) {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
            return hex(md.digest());
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
    }

    // ---- internals ----

    private long fixHeader(File part) throws IOException {
        if (!part.exists() || part.length() <= Wav.HEADER_BYTES) return 0;
        long dataBytes = part.length() - Wav.HEADER_BYTES;
        try (RandomAccessFile raf = new RandomAccessFile(part, "rw")) {
            raf.seek(0);
            raf.write(Wav.header(dataBytes));
        }
        return dataBytes;
    }

    private void writeMeta(String id, String recordedAt, long durationMs) throws IOException {
        Properties p = new Properties();
        p.setProperty("id", id);
        p.setProperty("recorded_at", recordedAt == null ? "" : recordedAt);
        p.setProperty("duration_ms", Long.toString(durationMs));
        try (OutputStream out = new FileOutputStream(new File(dir, id + META))) {
            p.store(out, null);
        }
    }

    private Properties readMeta(String id) {
        Properties p = new Properties();
        File f = new File(dir, id + META);
        if (f.exists()) {
            try (InputStream in = new FileInputStream(f)) {
                p.load(in);
            } catch (IOException ignored) {
                // Missing or damaged metadata: fall back to values from the WAV itself.
            }
        }
        return p;
    }

    private List<File> list(String suffix) {
        File[] files = dir.listFiles((d, name) -> name.endsWith(suffix));
        if (files == null) return new ArrayList<>();
        Arrays.sort(files, (a, b) -> Long.compare(a.lastModified(), b.lastModified()));
        return new ArrayList<>(Arrays.asList(files));
    }

    private static long parseLong(String s, long fallback) {
        try {
            return s == null ? fallback : Long.parseLong(s);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) sb.append(String.format("%02x", b & 0xff));
        return sb.toString();
    }
}
