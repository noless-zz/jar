package com.noam.jar.core;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

public class ShoppingTest {
    private static Shopping.Item item(String id, String buyer, String by, boolean bought, String at) {
        Shopping.Item i = new Shopping.Item(id, id, buyer, by, bought);
        i.createdAt = at;
        return i;
    }

    private final List<Shopping.Item> items = Arrays.asList(
            item("milk", "livne", "noam", false, "2026-10-25T10:00:00Z"),
            item("epoxy", "noam", "livne", false, "2026-10-25T11:00:00Z"),
            item("eggs", "livne", "sveta", true, "2026-10-25T09:00:00Z"),
            item("bread", "livne", "sveta", false, "2026-10-25T08:00:00Z"));
    private final List<String> family = Arrays.asList("noam", "sveta", "livne", "alona");

    @Test
    public void mineFirstThenFamilyOrderWithoutEmptyOnes() {
        Map<String, List<Shopping.Item>> g = Shopping.groups(items, "alona", family);
        assertEquals(Arrays.asList("alona", "noam", "livne"), new ArrayList<>(g.keySet()));
        assertTrue(g.get("alona").isEmpty());                    // my own list shows even when empty
    }

    @Test
    public void toBuyFirstOldestFirstThenBought() {
        List<Shopping.Item> l = Shopping.groups(items, "noam", family).get("livne");
        assertEquals(Arrays.asList("bread", "milk", "eggs"), Arrays.asList(l.get(0).id, l.get(1).id, l.get(2).id));
    }

    @Test
    public void countsAndRights() {
        assertEquals(2, Shopping.open(items, "livne"));
        assertTrue(Shopping.mayChange(items.get(1), "livne", false));    // she asked for it
        assertFalse(Shopping.mayChange(items.get(1), "alona", false));
        assertTrue(Shopping.mayChange(items.get(1), "alona", true));      // a parent
    }

    @Test
    public void someoneOutsideTheFamilyListStillShows() {
        Map<String, List<Shopping.Item>> g = Shopping.groups(
                Arrays.asList(item("x", "guest", "noam", false, "a")), "noam", family);
        assertTrue(g.containsKey("guest"));
    }
}
