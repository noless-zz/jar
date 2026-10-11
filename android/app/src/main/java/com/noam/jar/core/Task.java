package com.noam.jar.core;

/**
 * One task from the family list on the PC (GET /v1/tasks). Plain fields so the
 * logic around it can be unit-tested without Android.
 * Times are local wall-clock strings, "yyyy-MM-dd" or "yyyy-MM-ddTHH:mm".
 */
public final class Task {
    public String id = "";
    public String title = "";
    public String notes = "";
    public String assignee = "";
    public String createdBy = "";
    public String status = "open";      // open | done | requested | declined
    public String due;                  // null = no date
    public String snoozedUntil;         // null = not snoozed
    public String doneAt;
    public String doneBy;
    public String updatedAt = "";
    /** "task", or "message" = a prepared WhatsApp message the person sends themselves. */
    public String kind = "task";
    public String message = "";
    public String to = "";
    public String phone = "";       // digits only, "" = let WhatsApp ask which chat

    public boolean isMessage() {
        return "message".equals(kind);
    }

    /** Opens WhatsApp with the text filled in (and the chat, when the number is known). */
    public String whatsappUrl() {
        String text;
        try {
            text = java.net.URLEncoder.encode(message == null ? "" : message, "UTF-8").replace("+", "%20");
        } catch (java.io.UnsupportedEncodingException e) {
            text = "";
        }
        return "https://wa.me/" + (phone == null ? "" : phone) + "?text=" + text;
    }

    public boolean isOpen() {
        return "open".equals(status);
    }

    public boolean isDone() {
        return "done".equals(status);
    }

    public boolean isRequested() {
        return "requested".equals(status);
    }

    /** "yyyy-MM-dd" of the due date, or null. */
    public String dueDay() {
        return due == null || due.length() < 10 ? null : due.substring(0, 10);
    }

    public boolean dueHasTime() {
        return due != null && due.length() >= 16;
    }

    /**
     * When the phone should ring for this task: the snooze time if snoozed, else the due
     * date-and-time. Null when there is nothing to ring for (no time, done, or waiting for approval).
     */
    public String alertAt() {
        if (!isOpen()) return null;
        if (snoozedUntil != null && snoozedUntil.length() >= 16) return snoozedUntil;
        if (snoozedUntil != null && snoozedUntil.length() == 10) return snoozedUntil + "T08:00";
        return dueHasTime() ? due : null;
    }
}
