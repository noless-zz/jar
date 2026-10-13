"""The "how to install and join Jar" message, shared by the AI tool and the app's Invite button.

A family member gets their own link. When the PC has a public address (Tailscale Funnel), the link is
https://<pc>.ts.net/v1/join#<pairing>: WhatsApp makes it tappable, and the page opens Jar with the
pairing. The part after # never reaches any server; it holds the person's code and the PC's addresses.
Without a public address it falls back to the jar://pair link, pasted in the app's settings.
"""

from __future__ import annotations

from urllib.parse import urlsplit

DOWNLOAD = "https://github.com/noless-zz/jar/releases/latest"


def join_url(urls: list[str], pair_link: str) -> str:
    """https://…/v1/join#v=1&t=…&u=… on the first public address, or "" when there is none."""
    public = next((u for u in urls if u.startswith("https://")), "")
    if not public or not pair_link.startswith("jar://pair?"):
        return ""
    return public.rstrip("/") + "/v1/join#" + urlsplit(pair_link).query


def steps(download: str, pair_link: str, link: str = "", language: str = "he") -> list[str]:
    """Numbered steps. `link` is the tappable join page; without it the jar:// link is pasted in the app."""
    en = (language or "he").lower().startswith("en")
    if en:
        out = [f"1. On your Android phone open {download} and tap the .apk file under Assets to install Jar "
               "(allow installing from the browser if asked).",
               "2. Open Jar once and allow notifications and the microphone."]
        if link:
            out.append(f"3. Then tap your personal link and press “Open in Jar” (don't share it):\n{link}")
            out.append("That's it: it works at home and outside, nothing else to install.")
        elif pair_link:
            out.append(f"3. Copy this personal link, then in Jar tap ⋮ → Settings & pairing → Paste link:\n{pair_link}")
            out.append("4. It works over the home Wi-Fi.")
        else:
            out.append("3. Then ask me for your personal pairing code.")
        out.append("In Jar you see your tasks, tick them off, and record a voice memo with the mic button.")
    else:
        out = [f"1. בטלפון (אנדרואיד) פתחו את הקישור {download} ולחצו על קובץ ה-apk שתחת Assets כדי להתקין את Jar "
               "(אם שואלים – לאשר התקנה מהדפדפן).",
               "2. פותחים את Jar פעם אחת ומאשרים התראות ומיקרופון."]
        if link:
            out.append(f"3. לוחצים על הקישור האישי שלך ואז על „פתיחה ב-Jar” (לא להעביר לאחרים):\n{link}")
            out.append("וזהו – עובד בבית וגם בחוץ, בלי להתקין שום דבר נוסף.")
        elif pair_link:
            out.append(f"3. מעתיקים את הקישור האישי הזה, ובאפליקציה: ⋮ ← הגדרות וצימוד ← הדבקת קישור:\n{pair_link}")
            out.append("4. זה עובד דרך ה-WiFi בבית.")
        else:
            out.append("3. אחר כך תבקשו ממני את קוד הצימוד האישי.")
        out.append("ב-Jar רואים את המשימות, מסמנים מה בוצע, ומקליטים הודעה קולית בכפתור המיקרופון.")
    return out


def message(name: str, download: str, pair_link: str, link: str = "", language: str = "he",
            greeting: str = "") -> str:
    en = (language or "he").lower().startswith("en")
    hello = (greeting or "").strip() or (
        (f"Hi {name}! " if name else "Hi! ") + "Here's how to install Jar and join:" if en else
        (f"היי {name}! " if name else "היי! ") + "ככה מתקינים את Jar ומתחברים:")
    return hello + "\n\n" + "\n".join(steps(download, pair_link, link, language))


JOIN_PAGE = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex">
<title>Jar</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:28rem;margin:0 auto;padding:1.5rem 1rem;background:#f6f5f2;color:#222}
 h1{font-size:1.6rem;margin:.2rem 0 1rem} p{line-height:1.5}
 a.b{display:block;text-align:center;padding:1rem;margin:.8rem 0;border-radius:.8rem;font-size:1.15rem;
     text-decoration:none;color:#fff;background:#3b6d5a} a.s{background:#777}
 small{color:#666} .en{direction:ltr;text-align:left;margin-top:2rem;border-top:1px solid #ddd;padding-top:1rem}
 @media (prefers-color-scheme:dark){body{background:#1c1c1c;color:#eee}small{color:#aaa}}
</style></head><body>
<h1>הצטרפות ל-Jar</h1>
<p>אם Jar כבר מותקן – לחצו:</p>
<a class="b" id="open" href="#">פתיחה ב-Jar</a>
<p><small>עוד לא מותקן? מתקינים קודם, פותחים פעם אחת, וחוזרים לכאן.</small></p>
<a class="b s" href="__DOWNLOAD__">הורדת Jar</a>
<p id="bad" hidden>הקישור לא שלם – בקשו קישור חדש.</p>
<div class="en"><p>Already have Jar? Tap <b>פתיחה ב-Jar</b> (Open in Jar). Not yet? Tap <b>הורדת Jar</b>
(Download), install, open it once, and come back to this link.</p></div>
<script>
 var q = location.hash.replace(/^#/, "");
 if (/(^|&)t=/.test(q)) {
   document.getElementById("open").href = "intent://pair?" + q + "#Intent;scheme=jar;package=com.noam.jar;S.browser_fallback_url=" +
       encodeURIComponent("__DOWNLOAD__") + ";end";
 } else { document.getElementById("open").hidden = true; document.getElementById("bad").hidden = false; }
</script>
</body></html>
"""


def page(download: str = DOWNLOAD) -> str:
    return JOIN_PAGE.replace("__DOWNLOAD__", download)
