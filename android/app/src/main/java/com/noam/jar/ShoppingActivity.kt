package com.noam.jar

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.noam.jar.core.Shopping
import java.util.concurrent.Executors

/**
 * Shopping lists: one per family member, with what that person is going to buy. Anyone adds to anyone's list
 * ("Dad, buy epoxy" goes on Dad's), and anyone ticks what they bought. Memos fill them too, and Home Assistant
 * shows them on the family panel. Opened from the menu in both designs.
 */
class ShoppingActivity : ComponentActivity() {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val items = mutableStateOf<List<Shopping.Item>?>(null)
    private val defaultBuyer = mutableStateOf("")
    private val error = mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val cache = TaskCache(this)
        val look = LookPrefs.load(this, cache.myId().isNotEmpty() && !cache.iAmParent())
        setContent {
            JarThemed(look) {
                SystemBars()
                ShoppingScreen(cache.myId(), cache.iAmParent(), cache.names(), items.value, defaultBuyer.value, error.value,
                    onBack = { finish() }, onAdd = ::add, onAct = ::act)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    override fun onDestroy() {
        io.shutdown()
        super.onDestroy()
    }

    private fun load() {
        val prefs = Prefs(this)
        io.execute {
            try {
                val who = arrayOf("")
                val got = TaskApi.shopping(prefs, who)
                main.post { items.value = got; defaultBuyer.value = who[0]; error.value = null }
            } catch (e: Exception) {
                main.post { error.value = getString(R.string.shop_offline) }
            }
        }
    }

    private fun add(text: String, buyer: String) {
        val titles = text.split(',', '\n', '،').map { it.trim() }.filter { it.isNotEmpty() }
        if (titles.isEmpty()) return
        val prefs = Prefs(this)
        io.execute {
            try {
                TaskApi.shoppingAdd(prefs, titles, buyer, "")
                main.post { load() }
            } catch (e: Exception) {
                main.post { Toast.makeText(this, R.string.shop_failed, Toast.LENGTH_SHORT).show() }
            }
        }
    }

    private fun act(item: Shopping.Item, action: String) {
        val prefs = Prefs(this)
        // Show it at once; the PC's answer comes with the reload.
        items.value = items.value?.mapNotNull {
            if (it.id != item.id) it
            else if (action == "delete") null
            else Shopping.Item(it.id, it.title, it.buyer, it.requestedBy, action == "bought").also { n ->
                n.notes = it.notes; n.createdAt = it.createdAt
            }
        }
        io.execute {
            try {
                TaskApi.shoppingAct(prefs, item.id, action)
            } catch (e: Exception) {
                main.post { Toast.makeText(this, R.string.shop_failed, Toast.LENGTH_SHORT).show() }
            }
            main.post { load() }
        }
    }
}

@Composable
fun ShoppingScreen(me: String, parent: Boolean, names: Map<String, String>, items: List<Shopping.Item>?, defaultBuyer: String,
                   error: String?, onBack: () -> Unit, onAdd: (String, String) -> Unit, onAct: (Shopping.Item, String) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    val homeName = stringResource(R.string.home_assistant_name)
    val name = { id: String -> if (id == "home") homeName else names[id] ?: id }
    var text by remember { mutableStateOf("") }
    var buyer by remember { mutableStateOf("") }          // "" = whoever does the family shopping
    val groups = Shopping.groups(items ?: emptyList(), me, names.keys.toList())
    LazyColumn(
        Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).testTag("shopping"),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 40.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item(key = "title") {
            Column(Modifier.padding(top = 14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                BackButton(onBack)
                Text(stringResource(R.string.shop_title), color = c.ink, fontSize = 26.sp, fontWeight = FontWeight.Bold,
                    fontFamily = jar.display, modifier = Modifier.padding(horizontal = 6.dp))
                Text(stringResource(R.string.shop_hint), color = c.muted, fontSize = 14.sp, fontFamily = jar.font,
                    modifier = Modifier.padding(horizontal = 6.dp))
            }
        }
        item(key = "add") {
            Block {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    val send = { if (text.isNotBlank()) { onAdd(text, buyer); text = "" } }
                    OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().testTag("shop_input"),
                        placeholder = { Text(stringResource(R.string.shop_add_hint)) }, singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { send() }),
                        trailingIcon = { IconButton(onClick = send, Modifier.testTag("shop_add")) { Icon(JarIcons.Plus, stringResource(R.string.shop_add)) } })
                    Text(stringResource(R.string.shop_who_buys), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item {
                            val shopper = if (defaultBuyer.isNotEmpty()) " (" + name(defaultBuyer) + ")" else ""
                            ChoiceChip(stringResource(R.string.shop_whoever) + shopper, buyer.isEmpty()) { buyer = "" }
                        }
                        items(names.keys.toList()) { id ->
                            ChoiceChip(if (id == me) stringResource(R.string.shop_me) else name(id), buyer == id) { buyer = id }
                        }
                    }
                }
            }
        }
        if (error != null) item(key = "error") { Text(error, color = c.danger, fontSize = 14.sp, fontFamily = jar.font) }
        if (items == null && error == null) item(key = "loading") { Text(stringResource(R.string.syncing), color = c.muted, fontFamily = jar.font) }
        for ((who, list) in groups) {
            item(key = "list_$who") {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    val open = list.count { !it.bought }
                    Text((if (who == me) stringResource(R.string.shop_mine) else stringResource(R.string.shop_of, name(who)))
                            + if (open > 0) " · $open" else "",
                        color = c.ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, fontFamily = jar.display,
                        modifier = Modifier.padding(horizontal = 6.dp))
                    Block {
                        Column {
                            if (list.isEmpty()) Text(stringResource(R.string.shop_empty), color = c.muted, fontSize = 14.sp,
                                fontFamily = jar.font, modifier = Modifier.padding(14.dp))
                            list.forEachIndexed { i, it ->
                                if (i > 0) HorizontalDivider(color = c.line)
                                ShopRow(it, me, parent, name, onAct)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ShopRow(item: Shopping.Item, me: String, parent: Boolean, name: (String) -> String,
                    onAct: (Shopping.Item, String) -> Unit) {
    val jar = LocalJar.current
    val c = jar.colors
    Row(Modifier.fillMaxWidth().clickable { onAct(item, if (item.bought) "unbought" else "bought") }
        .padding(horizontal = 6.dp, vertical = 4.dp).testTag("shop_item"), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(item.bought, { onAct(item, if (item.bought) "unbought" else "bought") })
        Column(Modifier.weight(1f)) {
            Text(item.title, color = if (item.bought) c.muted else c.ink, fontSize = 16.sp, fontFamily = jar.font,
                textDecoration = if (item.bought) TextDecoration.LineThrough else null)
            val sub = buildList {
                if (item.requestedBy.isNotEmpty() && item.requestedBy != item.buyer)
                    add(stringResource(R.string.shop_asked_by, name(item.requestedBy)))
                if (item.notes.isNotEmpty()) add(item.notes)
            }
            if (sub.isNotEmpty()) Text(sub.joinToString(" · "), color = c.muted, fontSize = 13.sp, fontFamily = jar.font)
        }
        if (Shopping.mayChange(item, me, parent)) {
            IconButton(onClick = { onAct(item, "delete") }, Modifier.size(40.dp)) {
                Icon(JarIcons.Trash, stringResource(R.string.shop_remove), tint = c.muted, modifier = Modifier.size(18.dp))
            }
        }
    }
}
