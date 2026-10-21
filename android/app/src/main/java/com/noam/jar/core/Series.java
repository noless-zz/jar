package com.noam.jar.core;

/** A recurring task as a whole (the rule behind the 🔁 occurrences), from "series" in GET /v1/tasks. */
public final class Series {
    public String id = "";
    public String title = "";
    public String createdBy = "";
    public java.util.List<String> owners = new java.util.ArrayList<>();
    public String rule = "";
    public String time = "";
    /** The rule in words, e.g. "כל ראשון ורביעי ב-20:00". */
    public String label = "";
    public boolean rotate;
    /** active | paused */
    public String status = "active";
    public String nextDue = "";
    public String nextTurn = "";

    public boolean isPaused() {
        return "paused".equals(status);
    }

    /** May {@code me} pause or stop it: whoever made it, the admin, or a parent when it is only the kids'. */
    public boolean canChange(String me, boolean iAmAdmin, boolean iAmParent, java.util.Set<String> parents) {
        if (me.equals(createdBy) || iAmAdmin) return true;
        if (!iAmParent) return false;
        for (String o : owners) if (parents.contains(o)) return false;
        return true;
    }
}
