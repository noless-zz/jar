package com.noam.jar.core;

/**
 * What to do with a memo after an upload attempt. The rule from the spec (NFR-1):
 * delete the local copy only when the server returns the same checksum we sent.
 */
public enum UploadResult {
    /** Server stored it (or already had it) with a matching checksum. */
    DELETE_LOCAL,
    /** Network or server trouble: keep it and try again later. */
    RETRY,
    /** The server refused it in a way retrying won't fix (bad token, conflict). Keep it, flag it. */
    KEEP_AND_FLAG;

    public static UploadResult decide(int httpCode, String localSha, String serverSha) {
        if ((httpCode == 200 || httpCode == 201)
                && localSha != null && localSha.equalsIgnoreCase(serverSha)) {
            return DELETE_LOCAL;
        }
        if (httpCode == 400 || httpCode == 401 || httpCode == 403 || httpCode == 409 || httpCode == 413) {
            return KEEP_AND_FLAG;
        }
        // 200 with a wrong checksum, 422 (corrupted in transit), 5xx, timeouts (code <= 0): try again.
        return RETRY;
    }
}
