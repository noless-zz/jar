package com.noam.jar.core;

/** An area of responsibility (תחום אחריות): the kitchen is Noam's, the floors Sveta's… ("areas" in GET /v1/tasks). */
public final class Area {
    public String id = "";
    public String name = "";
    public String emoji = "";
    public String owner = "";
    public String description = "";
    public java.util.List<String> keywords = new java.util.ArrayList<>();

    /** "🍳 מטבח" */
    public String label() {
        return (emoji == null || emoji.isEmpty() ? "" : emoji + " ") + name;
    }
}
