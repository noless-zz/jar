package com.noam.jar

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.noam.jar.core.PairingLink
import com.noam.jar.core.ServerList

/**
 * The first run: connect this phone to the family PC (scan the invite's code or paste its link),
 * then allow the microphone and notifications and pick a look. Shown while the phone isn't paired,
 * and once more right after pairing.
 */
@Composable
fun WelcomeScreen(data: HomeData, paired: Boolean) {
    val jar = LocalJar.current
    val c = jar.colors
    val ctx = LocalContext.current
    val actions = LocalActions.current
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val pair = { raw: String? ->
        val problem = Pairing.apply(ctx, raw)
        if (problem != null) status = ctx.getString(problem)
        else {
            actions.onboarding(true)        // paired: on to "you're in" while the connection is checked
            busy = true
            status = ctx.getString(R.string.testing)
            val prefs = Prefs(ctx)
            actions.background({ Uploader.testConnection(prefs) }, { check ->
                busy = false
                status = Pairing.describe(ctx, check)
                if (check.problem == null) UploadWorker.now(ctx)
            }, { e -> busy = false; status = e.message })
        }
    }
    val askPermissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 28.dp).testTag("welcome"),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Spacer(Modifier.height(24.dp))
        Hero()
        val title = if (paired && data.myName.isNotEmpty()) ctx.getString(R.string.ui_ready_title, data.myName)
            else if (paired) stringResource(R.string.ui_ready_title_noname) else stringResource(R.string.ui_welcome_title)
        Text(title, color = c.ink, fontSize = if (jar.style == JarStyle.NIGHT) 34.sp else 30.sp,
            fontWeight = if (jar.style == JarStyle.PLAYFUL) FontWeight.ExtraBold else FontWeight.Bold, fontFamily = jar.display, textAlign = TextAlign.Center)
        Text(stringResource(if (paired) R.string.ui_ready_sub else R.string.ui_welcome_sub), color = c.muted, fontSize = 16.sp,
            fontFamily = jar.font, textAlign = TextAlign.Center)
        Spacer(Modifier.height(8.dp))
        if (!paired) {
            MainButton(stringResource(R.string.ui_scan_invite), Modifier.testTag("scan"), enabled = !busy) {
                val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                GmsBarcodeScanning.getClient(ctx, options).startScan()
                    .addOnSuccessListener { code -> pair(code.rawValue) }
                    .addOnFailureListener { e -> status = ctx.getString(R.string.pair_scan_failed, e.javaClass.simpleName) }
            }
            SideButton(stringResource(R.string.ui_paste_invite), Modifier.testTag("paste")) {
                val clip = ctx.getSystemService(ClipboardManager::class.java)?.primaryClip
                pair(clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString())
            }
        } else {
            SideButton(stringResource(R.string.ui_allow_permissions)) {
                askPermissions.launch(buildList {
                    add(Manifest.permission.RECORD_AUDIO)
                    if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
                }.toTypedArray())
            }
            SideButton(stringResource(R.string.ui_pick_look)) { actions.open(LookActivity::class.java) }
            MainButton(stringResource(R.string.ui_start), Modifier.testTag("start")) { actions.onboarding(false) }
        }
        status?.let { Muted(it, Modifier.testTag("pair_status")) }
        if (!paired) Text(stringResource(R.string.ui_advanced_connection), color = c.muted, fontSize = 14.sp, fontFamily = jar.font,
            modifier = Modifier.clip(RoundedCornerShape(10.dp)).clickable(role = Role.Button) { actions.open(MainActivity::class.java) }.padding(10.dp))
    }
}

/** The jar mark in the style's voice: a soft disc (Calm), a glowing orb (Night), an ink sticker (Playful). */
@Composable
private fun Hero() {
    val jar = LocalJar.current
    val c = jar.colors
    when (jar.style) {
        JarStyle.CALM -> Box(Modifier.size(120.dp).clip(CircleShape).background(c.accentSoft), contentAlignment = Alignment.Center) {
            Box(Modifier.size(76.dp).clip(CircleShape).background(c.accent), contentAlignment = Alignment.Center) {
                Icon(JarIcons.Mic, null, tint = c.onAccent, modifier = Modifier.size(36.dp))
            }
        }
        JarStyle.NIGHT -> Box(Modifier.size(150.dp), contentAlignment = Alignment.Center) {
            Box(Modifier.size(150.dp).clip(CircleShape).background(Brush.radialGradient(listOf(c.accent.copy(alpha = 0.35f), c.bg))))
            Box(Modifier.size(84.dp).shadow(24.dp, CircleShape, ambientColor = c.accent, spotColor = c.accent).clip(CircleShape)
                .background(Brush.radialGradient(listOf(c.accent.copy(alpha = 0.8f), c.accent))), contentAlignment = Alignment.Center) {
                Icon(JarIcons.Mic, null, tint = c.onAccent, modifier = Modifier.size(38.dp))
            }
        }
        JarStyle.PLAYFUL -> Box {
            Box(Modifier.size(120.dp).offset(5.dp, 5.dp).clip(RoundedCornerShape(36.dp)).background(c.ink))
            Box(Modifier.size(120.dp).clip(RoundedCornerShape(36.dp)).background(c.accent).border(3.dp, c.ink, RoundedCornerShape(36.dp)),
                contentAlignment = Alignment.Center) {
                Icon(JarIcons.Mic, null, tint = c.ink, modifier = Modifier.size(48.dp))
            }
        }
    }
}

/** The pairing link (jar://pair?…): the token and the PC's addresses, stored on this phone. */
object Pairing {
    /** Stores what the link says; returns a string id describing the problem, or null when it was a good link. */
    fun apply(ctx: Context, raw: String?): Int? {
        val link = PairingLink.parse(raw) ?: return R.string.pair_bad
        val prefs = Prefs(ctx)
        val known = prefs.lastGoodUrl().isNotEmpty() || prefs.serverUrls().size > 1
        if (link.urls.isEmpty() && !known) return R.string.pair_no_address
        if (link.token != prefs.token()) TaskCache(ctx).clearAll()     // someone else's phone now
        prefs.setToken(link.token)
        if (link.urls.isNotEmpty()) prefs.setServerUrls(link.urls)
        val n = prefs.serverUrls().size
        prefs.addHistory(ctx.resources.getQuantityString(R.plurals.history_paired, n, Jar.localTime(), n))
        return null
    }

    fun describe(ctx: Context, c: Uploader.Check): String {
        val host = c.url?.replaceFirst(Regex("^https?://"), "") ?: ""
        return when {
            c.problem == null -> ctx.getString(when {
                ServerList.isPublic(c.url) -> R.string.test_ok_public
                ServerList.isTailscale(c.url) -> R.string.test_ok_tailscale
                else -> R.string.test_ok_home
            }, host)
            c.problem == Uploader.BAD_TOKEN -> ctx.getString(R.string.test_bad_token)
            c.url != null -> ctx.getString(R.string.test_failed, c.problem)
            else -> ctx.getString(R.string.test_unreachable, Prefs(ctx).serverUrls().size, c.problem)
        }
    }
}
