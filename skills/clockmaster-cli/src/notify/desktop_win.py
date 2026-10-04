"""Windows toast through stock PowerShell's WinRT bindings — nothing to install.

The AppId must be an AUMID Windows already knows, or the toast is dropped
silently; PowerShell's own always exists. Title and body travel in env vars,
so no quoting; the script is one line (a newline cannot cross a Windows
command line). Toasts play a sound unless <audio silent> says otherwise.
"""
import os
import subprocess

import notify

AUMID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
SCRIPT = "; ".join((
    "$ErrorActionPreference='Stop'",
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
    " ContentType=WindowsRuntime] | Out-Null",
    "$doc=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02)",
    "$txt=$doc.GetElementsByTagName('text')",
    "$txt.Item(0).AppendChild($doc.CreateTextNode($env:CM_TITLE)) | Out-Null",
    "$txt.Item(1).AppendChild($doc.CreateTextNode($env:CM_BODY)) | Out-Null",
    "if ($env:CM_SOUND -ne '1') { $au=$doc.CreateElement('audio');"
    " $au.SetAttribute('silent','true'); $doc.DocumentElement.AppendChild($au) | Out-Null }",
    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($doc))",
))


def argv_env(msg):
    env = {**os.environ, "CM_TITLE": msg.title, "CM_BODY": msg.body,
           "CM_SOUND": "0" if msg.sound == "off" else "1"}
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", SCRIPT], env


def send(msg):
    argv, env = argv_env(msg)
    try:
        subprocess.run(argv, env=env, capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        notify.note(f"{msg.title} {msg.run_id}: toast failed ({e})")
