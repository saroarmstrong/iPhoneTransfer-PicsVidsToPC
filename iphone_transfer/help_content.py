"""Text for the Help page (HTML for QTextBrowser)."""
from __future__ import annotations

from . import APP_NAME, GITHUB_URL


def help_html(c: dict) -> str:
    muted, ok, fail = c["muted"], c["ok"], c["fail"]
    return f"""
<style>
 h1 {{ margin-bottom: 2px; }}
 h2 {{ margin-top: 22px; margin-bottom: 6px; }}
 p, li {{ line-height: 145%; }}
 td {{ padding: 5px 14px 5px 0; vertical-align: top; }}
 .muted {{ color: {muted}; }}
 .yes {{ color: {ok}; font-weight: 600; }}
 .no {{ color: {fail}; font-weight: 600; }}
</style>

<p class="muted">{APP_NAME} copies the photos and videos on your iPhone to your PC, sorted into
Year-Month folders or one folder per album, with the date at the start of every file name (both can be changed in Options).</p>

<h2>Before you start</h2>
<table>
<tr><td class="yes">✓</td><td><b>Windows 10 or 11</b>, 64-bit.</td></tr>
<tr><td class="yes">✓</td><td><b>Apple Devices</b> (free, Microsoft Store) or <b>iTunes</b>. It brings the Apple driver
  Windows needs to talk to an iPhone. Install it once; you never have to open it.
  <a href="https://apps.microsoft.com/detail/9NP83LWLPZ9K">Get Apple Devices</a></td></tr>
<tr><td class="yes">✓</td><td><b>An iPhone or iPad on iOS 16 or later.</b></td></tr>
<tr><td class="yes">✓</td><td><b>A USB cable that carries data.</b> The one that came with your iPhone is ideal.
  Many cheap cables only charge.</td></tr>
<tr><td class="yes">✓</td><td><b>Room on your PC or external drive.</b> Use an NTFS or exFAT drive; FAT32 drives
  can't store videos over 4 GB.</td></tr>
</table>
<p>No Apple ID, internet connection or iCloud for Windows is needed.</p>

<h2>Is your iPhone really connected?</h2>
<p>Before using the app, check that Windows itself can see your iPhone:</p>
<ol>
<li>Plug the iPhone in and unlock it. If it asks <b>Trust This Computer?</b>, tap <b>Trust</b> and enter your passcode.</li>
<li>Open <b>File Explorer</b> and click <b>This PC</b>.</li>
<li>Open <b>Apple iPhone</b>. You should see <b>Internal Storage</b>, and inside it folders such as <i>202611__</i>.</li>
</ol>
<p>If <i>Apple iPhone</i> is missing, Windows doesn't see the phone: try another cable or USB port.
If it's there but empty, the iPhone is locked or hasn't been trusted yet: unlock it, then unplug and plug it in again.
Once you can see the folders, the app will connect.</p>

<h2>Copying in five steps</h2>
<ol>
<li>Plug in and unlock your iPhone, and tap <b>Trust</b> if asked.</li>
<li>On <b>Connect</b>, press <b>Connect</b>. Reading your library takes from a few seconds to a minute.</li>
<li>On <b>Transfer</b>, choose <b>By Year-Month</b> or <b>By Album</b> and tick what you want.
  Use <b>Date range</b> to pick exact days.</li>
<li>Choose where to save, then press <b>Start Copy</b>.</li>
<li>That's it. You can cancel any time. Press <b>Start Copy</b> again later and it carries on where it stopped,
  skipping everything already copied.</li>
</ol>

<h2>If it won't connect</h2>
<p>Open <b>Troubleshoot</b>. It checks each link in the chain and tells you what to fix.
These solve almost every case:</p>
<ul>
<li><b>Install Apple Devices or iTunes</b>, then restart the PC once.</li>
<li><b>Swap the cable or the port.</b> Plug straight into the PC, not into a hub, keyboard or monitor.
  If the iPhone charges but nothing else happens, it's nearly always the cable.</li>
<li><b>Unlock first.</b> An iPhone that has been locked for a while refuses new USB connections.
  Unlock it before plugging in and keep it on the Home Screen until the app says it's connected.</li>
<li><b>The Trust question never appears</b>, or you once tapped Don't Trust: on the iPhone go to
  <i>Settings → General → Transfer or Reset iPhone → Reset → Reset Location &amp; Privacy</i>,
  then plug in again.</li>
<li><b>Close other iPhone apps</b> such as iTunes, Apple Devices, CopyTrans, iMazing or the Windows Photos importer.
  They can start a sync and take over the connection.</li>
<li><b>Still stuck?</b> Press <i>Restart Apple service</i> in Troubleshoot, then restart the iPhone,
  then restart the PC.</li>
</ul>
<p>A big library is no problem. The app reads only the small part of the iPhone's photo database it needs,
so even a 1 TB iPhone connects in seconds. A full 1 TB copy over USB takes roughly two to three hours;
keep a laptop plugged in. The iPhone can lock its screen once copying has started, and if the cable slips out
the app waits for the iPhone and picks up where it left off.</p>

<h2>What it can't do</h2>
<table>
<tr><td class="no">✗</td><td><b>Copy photos that live only in iCloud.</b> With <i>Optimize iPhone Storage</i> turned on,
  older photos may be kept in iCloud with only a small preview on the phone. Those can't be copied over a cable.
  The app lists them in a <i>_transfer_report</i> file in your folder. To include them, choose
  <i>Settings → Apps → Photos → Download and Keep Originals</i> on the iPhone (it needs free space there),
  wait for the download to finish, and copy again.</td></tr>
<tr><td class="no">✗</td><td><b>Delete photos from the iPhone.</b> That has to happen on the phone, so its library and
  iCloud stay in sync. Tip: in Photos, open <i>Recently Added</i>, tap Select and swipe across.</td></tr>
</table>

<h2>Good to know</h2>
<ul>
<li><b>Exact copies.</b> Files arrive byte-for-byte as they are on the iPhone. HEIC stays HEIC and nothing is
  recompressed. Turn on <i>Verify</i> if you want every file checked against the iPhone.
  Only the optional HEIC → JPG conversion changes files.</li>
<li><b>File names</b> look like <i>20261108_14-03-18_IMG_6454.HEIC</i> and month folders like <i>2026 Nov</i>; you can pick other styles in <i>Options</i>. The date is when the item was added to your
  iPhone, the same order as Recently Added. You can switch to the date it was taken.</li>
<li><b>Edited photos</b> are copied as the original, plus an <i>_edited</i> copy if you keep that option on.</li>
<li><b>Can't open HEIC on your PC?</b> Install Microsoft's free HEIF Image Extensions, or turn on
  <i>Convert HEIC photos to JPG</i>.</li>
<li><b>Windows SmartScreen</b> may warn about the app the first time, because it isn't code-signed.
  Click <i>More info → Run anyway</i>.</li>
<li><b>Private by design.</b> Everything stays on your PC. The app has no account, no internet access and no tracking.</li>
</ul>

<h2>About</h2>
<p>{APP_NAME} is free and open source (GPL-3.0 licence). <a href="{GITHUB_URL}">{GITHUB_URL}</a><br>
The artwork (background, watercolour design, icon) is not part of that licence: all rights reserved.<br>
It's shared as-is, without support or updates.<br>
<span class="muted">Not affiliated with Apple Inc. iPhone is a trademark of Apple Inc.</span><br>&nbsp;</p>
<p class="muted">Background art: AI-generated imagery of <b>FreenBecky</b>, created out of love and inspiration. Not affiliated with or endorsed by them.</p>
<p style="white-space: nowrap;">The app is made by @saroarmstrong - in hope to save more #beckfreen photos/vids ค่ะะ.&nbsp;&nbsp;&nbsp; <b style="color: {muted};">เราก็ขอบใจ (ㅅ´ ˘ `)✧</b></p>
"""
