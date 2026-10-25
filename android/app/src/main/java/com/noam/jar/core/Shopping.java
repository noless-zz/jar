package com.noam.jar.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Shopping lists (server worker/shopping.py): one per family member, holding what that person will buy.
 * Pure Java so the grouping is unit-tested; TaskApi turns the JSON into {@link Item}s.
 */
public final class Shopping {
    private Shopping() { }

    public static final class Item {
        public String id = "";
        public String title = "";
        public String notes = "";
        public String buyer = "";
        public String requestedBy = "";
        public boolean bought;
        public String createdAt = "";

        public Item() { }

        public Item(String id, String title, String buyer, String requestedBy, boolean bought) {
            this.id = id;
            this.title = title;
            this.buyer = buyer;
            this.requestedBy = requestedBy;
            this.bought = bought;
        }
    }

    /**
     * The lists to show: mine first, then the family in the PC's order, then anyone else who has items.
     * Inside a list: still to buy first (oldest first), then what was bought. Empty lists of others are left out.
     */
    public static Map<String, List<Item>> groups(List<Item> items, String me, List<String> familyOrder) {
        Map<String, List<Item>> out = new LinkedHashMap<>();
        out.put(me, new ArrayList<>());
        for (String id : familyOrder) if (!id.equals(me)) out.put(id, new ArrayList<>());
        for (Item i : items) {
            List<Item> l = out.get(i.buyer);
            if (l == null) {
                l = new ArrayList<>();
                out.put(i.buyer, l);
            }
            l.add(i);
        }
        Map<String, List<Item>> shown = new LinkedHashMap<>();
        for (Map.Entry<String, List<Item>> e : out.entrySet()) {
            if (e.getValue().isEmpty() && !e.getKey().equals(me)) continue;
            List<Item> l = new ArrayList<>(e.getValue());
            l.sort((a, b) -> a.bought != b.bought ? (a.bought ? 1 : -1) : a.createdAt.compareTo(b.createdAt));
            shown.put(e.getKey(), l);
        }
        return shown;
    }

    /** How many items are still to buy on someone's list. */
    public static int open(List<Item> items, String buyer) {
        int n = 0;
        for (Item i : items) if (!i.bought && buyer.equals(i.buyer)) n++;
        return n;
    }

    /** Whether this person may remove or change the item (the server checks too). */
    public static boolean mayChange(Item i, String me, boolean parent) {
        return parent || me.equals(i.buyer) || me.equals(i.requestedBy);
    }
}
