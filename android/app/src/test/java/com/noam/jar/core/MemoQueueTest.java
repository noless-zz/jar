package com.noam.jar.core;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.List;

public class MemoQueueTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private static void writePart(File f, int dataBytes) throws IOException {
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write(Wav.header(0));           // placeholder, like the recorder writes
            out.write(new byte[dataBytes]);
        }
    }

    @Test
    public void idsAreSixteenHexChars() {
        String id = MemoQueue.newId();
        assertTrue(id.matches("[0-9a-f]{16}"));
        assertFalse(id.equals(MemoQueue.newId()));
    }

    @Test
    public void finishFixesHeaderAndQueuesMemo() throws IOException {
        MemoQueue q = new MemoQueue(tmp.getRoot());
        String id = MemoQueue.newId();
        writePart(q.partFile(id), Wav.BYTES_PER_SECOND * 2);   // 2 seconds of silence

        assertTrue(q.finish(id, "2026-10-08T09:00:00Z"));
        List<Memo> ready = q.ready();
        assertEquals(1, ready.size());
        Memo m = ready.get(0);
        assertEquals(id, m.id);
        assertEquals(2000, m.durationMs);
        assertEquals("2026-10-08T09:00:00Z", m.recordedAt);

        byte[] head = new byte[Wav.HEADER_BYTES];
        try (RandomAccessFile raf = new RandomAccessFile(m.wav, "r")) {
            raf.readFully(head);
        }
        assertArrayEquals(Wav.header(Wav.BYTES_PER_SECOND * 2), head);
        assertFalse(q.partFile(id).exists());
    }

    @Test
    public void emptyRecordingIsDropped() throws IOException {
        MemoQueue q = new MemoQueue(tmp.getRoot());
        String id = MemoQueue.newId();
        writePart(q.partFile(id), 0);
        assertFalse(q.finish(id, "x"));
        assertEquals(0, q.readyCount());
        assertFalse(q.partFile(id).exists());
    }

    @Test
    public void interruptedRecordingIsRecovered() throws IOException {
        MemoQueue q = new MemoQueue(tmp.getRoot());
        writePart(q.partFile(MemoQueue.newId()), 3200);   // 0.1 s, header still says 0
        assertEquals(1, q.recoverPartials("2026-10-08T10:00:00Z"));
        assertEquals(1, q.readyCount());
        assertEquals(100, q.ready().get(0).durationMs);
    }

    @Test
    public void removeDeletesWavAndMetadata() throws IOException {
        MemoQueue q = new MemoQueue(tmp.getRoot());
        String id = MemoQueue.newId();
        writePart(q.partFile(id), 6400);
        q.finish(id, "t");
        q.remove(q.ready().get(0));
        assertEquals(0, q.readyCount());
        String[] left = tmp.getRoot().list();
        assertEquals(0, left == null ? 0 : left.length);
    }

    @Test
    public void sha256MatchesKnownValue() throws IOException {
        File f = tmp.newFile("abc.bin");
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write("abc".getBytes("US-ASCII"));
        }
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", MemoQueue.sha256(f));
    }
}
