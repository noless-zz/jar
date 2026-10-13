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
    /** Notes and questions between whoever asked for it and whoever does it, oldest first. */
    public java.util.List<Note> thread = new java.util.ArrayList<>();
    /** Who a question is waiting on ("" = nobody). */
    public String waitingOn = "";
    /** Coins: what a done task paid, or what an open one will pay (0 = none, or not rated yet). */
    public int coins;
    public boolean paid;
    /** The effort rating 1-10 (0 = not rated) and whether the task is excluded from the game. */
    public int effort;
    public boolean noCoins;
    /** "ai", "parent", "rule" or "default": who rated it. */
    public String ratedBy = "";

    public static final class Note {
        public int id;
        public String by = "";
        public String text = "";
        public String at = "";
        public boolean ask;
        public boolean edited;
    }

    public Note lastNote() {
        return thread.isEmpty() ? null : thread.get(thread.size() - 1);
    }

    public boolean waitingOn(String person) {
        return person != null && !person.isEmpty() && person.equals(waitingOn);
    }

    /** Who my question would go to: the one doing it, or (if that's me) whoever asked for it. "" = nobody. */
    public String counterpart(String me) {
        if (!me.equals(assignee)) return assignee;
        return createdBy.equals(me) ? "" : createdBy;
    }

    public boolean isMessage() {
        return "message".equals(kind);
    }

    /** A lesson a child logged: finished already, its note is what earned the coins. */
    public boolean isLesson() {
        return "lesson".equals(kind);
    }

    /** Can a parent change what this is worth? (WhatsApp drafts never earn.) */
    public boolean canRate() {
        return !isMessage() && (isOpen() || isDone() || isRequested()) && !isLesson();
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
