import json
import re
from pathlib import Path

from ..config import settings

FEATURE_GROUPS = {
    "remote": {
        "screen": "Remote Screen",
        "touch": "Remote Touch Control",
        "recording": "Live Screen Recording",
        "screenshot": "Remote Screenshot",
    },
    "files": {
        "file_manager": "File Manager",
        "file_upload": "Upload para Android",
        "file_download": "Download do Android",
        "gallery": "Remote Gallery",
    },
    "media": {
        "camera_preview": "Camera Preview",
        "camera_capture": "Camera Capture",
        "microphone": "Microphone Capture",
    },
    "apps": {
        "app_manager": "App Manager",
        "app_launcher": "Remote App Launcher",
        "app_stop": "Authorized App Stop",
        "apk_installer": "APK Installer",
        "apk_analyzer": "APK Analyzer",
    },
    "android": {
        "notifications": "Notification Center",
        "clipboard": "Clipboard Sync",
        "browser": "Remote Browser Launcher",
        "deeplink": "Deep Link Launcher",
    },
    "diagnostics": {
        "logs": "Live Logs",
        "diagnostic_console": "Diagnostic Console",
        "network_diagnostics": "Network Diagnostics",
        "wifi": "Wi-Fi Information",
        "bluetooth": "Bluetooth Manager",
    },
    "sensors": {
        "location": "Location Session",
        "sensors": "Sensor Dashboard",
    },
}

FEATURES = set()
for group in FEATURE_GROUPS.values():
    FEATURES.update(group.keys())

DEFAULT_FEATURES = {
    "screen": True, "touch": True, "recording": True, "screenshot": True,
    "file_manager": True, "file_upload": True, "file_download": True, "gallery": True,
    "camera_preview": False, "camera_capture": False, "microphone": False,
    "app_manager": True, "app_launcher": True, "app_stop": False,
    "apk_installer": True, "apk_analyzer": True,
    "notifications": True, "clipboard": True, "browser": True, "deeplink": True,
    "logs": True, "diagnostic_console": True, "network_diagnostics": True,
    "wifi": True, "bluetooth": True, "location": False, "sensors": True,
}


def _safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    return (value or "Android GPT Agent")[:80]


def create_project(app_name: str, server_url: str, features: dict[str, bool]) -> Path:
    safe_name = _safe_name(app_name)
    out = settings.generated / "android_gpt_agent"
    out.mkdir(parents=True, exist_ok=True)
    enabled = {k: bool(features.get(k)) for k in FEATURES}
    (out / "android-gpt.json").write_text(
        json.dumps({
            "schema": 2,
            "app_name": safe_name,
            "server_url": server_url.rstrip("/"),
            "feature_groups": FEATURE_GROUPS,
            "features": enabled,
        }, indent=2),
        encoding="utf-8",
    )
    return out
