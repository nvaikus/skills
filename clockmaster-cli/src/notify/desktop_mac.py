"""macOS banner from our own notifier.app, so it shows our name and icon.

Rules learned the hard way (details: references/notify.md):
- A banner is attributed to the bundle of the POSTING process, and usernoted
  silently drops one posted by anything but the bundle's main executable. So
  the main executable posts in-process (NSAppleScript) — a hand-off to
  osascript, by exec or spawn, loses the banner without a trace.
- The launcher source and click.zsh are BYTE-CONSTANT: they are sealed by the
  ad-hoc signature, the signature is the app's identity, and the notification
  permission hangs on that identity. Anything machine-specific lives OUTSIDE the
  bundle in notifier.conf, which click.zsh sources.
- The bundle id is stable (permission is per id); never reuse it for a test build.
- No compiler: a copy of /usr/bin/osascript as main executable still posts, but
  cannot answer a click (marker suffix `.osa`, so it is not rebuilt every run).
- Click: macOS passes no payload. notify writes last-notify.json before posting;
  sourcing notifier.conf (= a click happened) moves it to notify-click.json and
  touches it; the UI consumes that once within CLICK_TTL.
- Rebuilt when RECIPE or the icon changes (marker in CFBundleVersion).
"""
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys

import identity
import notify

RECIPE = 1
OSA_SUFFIX = ".osa"
TIMEOUT = 10
CLICK_TTL = 120
EXE_NAME = "notifier"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks"
              "/LaunchServices.framework/Support/lsregister")

# argv shape shared by the launcher, the osascript-copy fallback and bare
# /usr/bin/osascript: `-e <script lines> -- <title> <body> [<sound>]`.
OSA_LINES = ("on run argv",
             'if item 3 of argv is not "" then',
             "display notification (item 2 of argv) with title (item 1 of argv) sound name (item 3 of argv)",
             "else",
             "display notification (item 2 of argv) with title (item 1 of argv)",
             "end if",
             "end run")

LAUNCHER_SRC = r"""#import <Foundation/Foundation.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* notifier launcher — generated, do not edit. Two modes by argv:
   "... -- <title> <body> [<sound>]" posts a banner in-process;
   no arguments (= the app was activated by a banner click) runs click.zsh. */

static NSString *quoted(const char *s)
{
	NSString *v = [NSString stringWithUTF8String:s ? s : ""];
	v = [[v stringByReplacingOccurrencesOfString:@"\\" withString:@"\\\\"]
	        stringByReplacingOccurrencesOfString:@"\"" withString:@"\\\""];
	return [NSString stringWithFormat:@"\"%@\"", v];
}

int main(int argc, char **argv)
{
	int dash = -1;
	for (int i = 1; i < argc; i++)
		if (strcmp(argv[i], "--") == 0) { dash = i; break; }

	if (dash >= 0 && argc >= dash + 3) {
		@autoreleasepool {
			const char *snd = argc >= dash + 4 ? argv[dash + 3] : "";
			NSString *src = [NSString stringWithFormat:@"display notification %@ with title %@%@",
			    quoted(argv[dash + 2]), quoted(argv[dash + 1]),
			    snd[0] ? [NSString stringWithFormat:@" sound name %@", quoted(snd)] : @""];
			NSDictionary *err = nil;
			[[[NSAppleScript alloc] initWithSource:src] executeAndReturnError:&err];
			if (err) {
				fprintf(stderr, "%s\n", [[err description] UTF8String]);
				return 1;
			}
		}
		return 0;
	}

	char exe[PATH_MAX];
	uint32_t n = sizeof(exe);
	if (_NSGetExecutablePath(exe, &n) != 0)
		return 1;
	char *cut = strrchr(exe, '/');
	if (!cut)
		return 1;
	*cut = '\0';
	char script[PATH_MAX];
	if (snprintf(script, sizeof(script), "%s/../Resources/click.zsh", exe) >= (int)sizeof(script))
		return 1;
	char *args[] = { "/bin/zsh", script, NULL };
	execv("/bin/zsh", args);
	return 127;
}
"""

CLICK_SRC = f"""#!/bin/zsh
# notifier click handler — generated, do not edit.
# Activated (banner click or `open -b`): show the UI, start it only if it is down.
DATA="${{0:A:h:h:h:h}}"
[[ -r "$DATA/notifier.conf" ]] && source "$DATA/notifier.conf"
URL="http://127.0.0.1:${{CM_PORT:-{identity.UI_PORT}}}"
if ! /usr/bin/curl -sf -o /dev/null --max-time 2 "$URL"; then
	if [[ -x "$CM_PY" && -r "$CM_ENTRY" ]]; then
		{identity.ENV_HOME}="$DATA" "$CM_PY" "$CM_ENTRY" ui --port "${{CM_PORT:-{identity.UI_PORT}}}" >/dev/null 2>&1
	fi
fi
/usr/bin/open "$URL"
"""


def app_dir():
    return identity.data_dir() / "notifier.app"


def conf_path():
    return identity.data_dir() / "notifier.conf"


def crumb_path():
    return identity.data_dir() / "last-notify.json"


def click_path():
    return identity.data_dir() / "notify-click.json"


def icon_path():
    return identity.ASSETS / "notifier.icns"


def marker():
    icon = icon_path()
    tag = hashlib.sha256(icon.read_bytes()).hexdigest()[:12] if icon.exists() else "noicon"
    return f"{RECIPE}.{tag}"


def conf_text():
    """Machine-specific values for click.zsh + the line that turns the crumb of
    the last banner into the click crumb (mv keeps it atomic, touch stamps the
    click time the UI checks against CLICK_TTL)."""
    q = shlex.quote
    body = "".join(f"{k}={q(v)}\n" for k, v in (
        ("CM_PY", sys.executable), ("CM_ENTRY", str(identity.ENTRY)), ("CM_PORT", str(identity.UI_PORT))))
    return body + (f"/bin/mv -f {q(str(crumb_path()))} {q(str(click_path()))} 2>/dev/null"
                   f" && /usr/bin/touch {q(str(click_path()))}\n")


def write_conf():
    try:
        want = conf_text()
        path = conf_path()
        if not path.exists() or path.read_text(encoding="utf-8") != want:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(want, encoding="utf-8")
    except OSError:
        pass  # a click then just opens the URL


def write_crumb(task, run_id):
    try:
        crumb_path().parent.mkdir(parents=True, exist_ok=True)
        crumb_path().write_text(json.dumps({"task": task, "runId": run_id}), encoding="utf-8")
    except OSError:
        pass


def info_plist(mark):
    return plistlib.dumps({
        "CFBundleExecutable": EXE_NAME, "CFBundleIconFile": "notifier",
        "CFBundleIdentifier": identity.NOTIFIER_ID,
        "CFBundleName": identity.NOTIFIER_NAME, "CFBundleDisplayName": identity.NOTIFIER_NAME,
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": mark, "LSUIElement": True, "NSHighResolutionCapable": True,
    })


def compile_launcher(exe):
    """clang from the Xcode CLT; source on stdin + fixed output path keep the
    bytes reproducible (the Mach-O UUID is content-derived)."""
    try:
        sdk = subprocess.run(["xcrun", "--show-sdk-path"], capture_output=True, text=True, timeout=TIMEOUT)
        if sdk.returncode:
            return False
        return subprocess.run(
            ["clang", "-isysroot", sdk.stdout.strip(), "-x", "objective-c", "-fobjc-arc",
             "-framework", "Foundation", "-O2", "-o", str(exe), "-"],
            input=LAUNCHER_SRC.encode(), capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def build(mark):
    app = app_dir()
    contents = app / "Contents"
    exe = contents / "MacOS" / EXE_NAME
    try:
        shutil.rmtree(app, ignore_errors=True)
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir(parents=True)
        if compile_launcher(exe):
            click = contents / "Resources" / "click.zsh"
            click.write_text(CLICK_SRC, encoding="utf-8")
            click.chmod(0o755)
        else:
            shutil.copy("/usr/bin/osascript", exe)  # copy, not copy2: no SIP flags
            mark += OSA_SUFFIX
        exe.chmod(0o755)
        if icon_path().exists():
            shutil.copy(icon_path(), contents / "Resources" / "notifier.icns")
        (contents / "Info.plist").write_bytes(info_plist(mark))
        # sign LAST and the whole bundle: it seals plist + icon and re-identifies
        # an osascript copy (an unsigned copy of a system binary is SIGKILLed)
        if subprocess.run(["codesign", "--force", "--sign", "-", str(app)],
                          capture_output=True, timeout=TIMEOUT).returncode:
            return None
        os.utime(app, None)
        subprocess.run([LSREGISTER, "-f", str(app)], capture_output=True, timeout=TIMEOUT)
        return exe if exe.exists() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def binary():
    """A current notifier executable (built when missing/stale), else None."""
    write_conf()
    exe = app_dir() / "Contents" / "MacOS" / EXE_NAME
    plist = app_dir() / "Contents" / "Info.plist"
    mark = marker()
    if exe.exists() and plist.exists():
        try:
            if plistlib.loads(plist.read_bytes()).get("CFBundleVersion") in (mark, mark + OSA_SUFFIX):
                return exe
        except (OSError, ValueError):
            pass
    return build(mark)


def argv(exe, msg):
    out = [str(exe)]
    for line in OSA_LINES:
        out += ["-e", line]
    return out + ["--", msg.title, msg.body, "" if msg.sound == "off" else msg.sound]


def send(msg):
    write_crumb(msg.title, msg.run_id)  # before the post: a click can race it
    exe = binary() or "/usr/bin/osascript"
    p = subprocess.run(argv(exe, msg), capture_output=True, text=True, timeout=TIMEOUT)
    if p.returncode:
        notify.note(f"{msg.title} {msg.run_id}: banner failed: {(p.stderr or '').strip()[:200]}")
