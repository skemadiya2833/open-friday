"""Desktop toast notifications (Windows). Local only, fire-and-forget, never raises.

A toast carries a link back to the Friday UI (``/?reminder=<id>``); clicking it opens Friday, which then shows
the reminder. Text is passed through environment variables and XML-escaped, never interpolated into the script.
"""

from __future__ import annotations

import os
import subprocess

_PS = r"""
$t=$env:FRIDAY_T; $b=$env:FRIDAY_B; $u=$env:FRIDAY_U
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$e = [System.Security.SecurityElement]
$xml = "<toast activationType='protocol' launch='$($e::Escape($u))' scenario='reminder'><visual><binding template='ToastGeneric'><text>$($e::Escape($t))</text><text>$($e::Escape($b))</text></binding></visual><actions><action content='Open Friday' activationType='protocol' arguments='$($e::Escape($u))'/><action content='Dismiss' activationType='system' arguments='dismiss'/></actions><audio src='ms-winsoundevent:Notification.Reminder'/></toast>"
$d = New-Object Windows.Data.Xml.Dom.XmlDocument
$d.LoadXml($xml)
$n = New-Object Windows.UI.Notifications.ToastNotification $d
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)
"""


def toasts_enabled() -> bool:
    return os.name == "nt" and os.getenv("FRIDAY_TOASTS", "on").strip().lower() not in ("0", "off", "false", "no")


def ui_url(notification_id: str = "") -> str:
    from friday.config import SERVER_PORT, ui_host

    return f"http://{ui_host()}:{SERVER_PORT}/" + (f"?reminder={notification_id}" if notification_id else "")


def toast(title: str, body: str, url: str = "") -> bool:
    if not toasts_enabled():
        return False
    try:
        env = {**os.environ, "FRIDAY_T": title[:120], "FRIDAY_B": body[:300], "FRIDAY_U": url or ui_url()}
        subprocess.Popen(  # noqa: S603
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS],  # noqa: S607
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[Notify] toast failed: {exc}")
        return False
