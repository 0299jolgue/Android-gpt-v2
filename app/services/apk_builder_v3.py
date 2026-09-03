import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from ..config import settings

_GRADLE_VERSION = "9.5.0"
_ANDROID_TOOLS_VERSION = "15859902"
BUILD_ROOT = settings.generated / "_build"
TOOLCHAIN_ROOT = settings.generated / ".toolchain"
SDK_ROOT = TOOLCHAIN_ROOT / "android-sdk"
GRADLE_ROOT = TOOLCHAIN_ROOT / f"gradle-{_GRADLE_VERSION}"
JDK_ROOT = TOOLCHAIN_ROOT / "jdk-17"
_lock = threading.Lock()


def _download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    tmp.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Android-GPT/4.0"})
    with urllib.request.urlopen(req, timeout=180) as response, tmp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(destination)


def _run(cmd, cwd=None, env=None, input_text=None):
    result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=env, input=input_text,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=1200, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Comando falhou ({result.returncode}): {' '.join(cmd)}\n{result.stdout[-16000:]}")
    return result.stdout


def _java_home():
    java = shutil.which("java")
    if java:
        try:
            out = _run([java, "-version"])
            if re.search(r'version "(?:1\\.)?(?:17|18|19|20|21|22|23|24|25)', out):
                return Path(java).resolve().parent.parent
        except Exception:
            pass
    java_bin = JDK_ROOT / "bin" / "java"
    if not java_bin.exists():
        archive = TOOLCHAIN_ROOT / "jdk17.tar.gz"
        _download("https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse", archive)
        JDK_ROOT.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            top = tar.getmembers()[0].name.split("/", 1)[0]
            for member in tar.getmembers():
                if member.name == top or member.name.startswith(top + "/"):
                    member.name = member.name[len(top):].lstrip("/")
                    if member.name:
                        tar.extract(member, JDK_ROOT)
        archive.unlink(missing_ok=True)
    return JDK_ROOT


def _gradle_bin():
    path = GRADLE_ROOT / "bin" / "gradle"
    if not path.exists():
        archive = TOOLCHAIN_ROOT / f"gradle-{_GRADLE_VERSION}.zip"
        _download(f"https://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-bin.zip", archive)
        TOOLCHAIN_ROOT.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            z.extractall(TOOLCHAIN_ROOT)
        archive.unlink(missing_ok=True)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _ensure_sdk():
    sdkmanager = SDK_ROOT / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if not sdkmanager.exists():
        archive = TOOLCHAIN_ROOT / "commandlinetools.zip"
        _download(f"https://dl.google.com/android/repository/commandlinetools-linux-{_ANDROID_TOOLS_VERSION}_latest.zip", archive)
        temp = TOOLCHAIN_ROOT / "cmdline-tools-extract"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True)
        with zipfile.ZipFile(archive) as z:
            z.extractall(temp)
        target = SDK_ROOT / "cmdline-tools" / "latest"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(temp / "cmdline-tools"), str(target))
        shutil.rmtree(temp, ignore_errors=True)
        archive.unlink(missing_ok=True)

    env = os.environ.copy()
    env.update({"ANDROID_HOME": str(SDK_ROOT), "ANDROID_SDK_ROOT": str(SDK_ROOT), "JAVA_HOME": str(_java_home())})
    if not (SDK_ROOT / ".licenses_accepted").exists():
        _run([str(sdkmanager), "--sdk_root=" + str(SDK_ROOT), "--licenses"], env=env, input_text="y\n" * 40)
        (SDK_ROOT / ".licenses_accepted").touch()
    missing = []
    if not (SDK_ROOT / "platforms" / "android-36").exists():
        missing.append("platforms;android-36")
    if not (SDK_ROOT / "build-tools" / "36.0.0").exists():
        missing.append("build-tools;36.0.0")
    if missing:
        _run([str(sdkmanager), "--sdk_root=" + str(SDK_ROOT), *missing], env=env)
    return SDK_ROOT


def _slug(value):
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-") or "android_gpt_agent")[:48]


def _java_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")


def _xml_escape(value):
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def write_android_project(project, app_name, server_url, features):
    package = "com.jolgue.androidgptagent"
    src = project / "app" / "src" / "main"
    java_dir = src / "java" / Path(*package.split("."))
    values = src / "res" / "values"
    for path in (java_dir, values):
        path.mkdir(parents=True, exist_ok=True)

    enabled = sorted(k for k, value in features.items() if value)
    feature_text = _java_escape(json.dumps(enabled, ensure_ascii=False))
    app_label = _java_escape(app_name)
    xml_label = _xml_escape(app_name)
    server = _java_escape(server_url.rstrip("/"))

    permissions = [
        "INTERNET", "ACCESS_NETWORK_STATE", "ACCESS_WIFI_STATE", "CAMERA",
        "RECORD_AUDIO", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
        "POST_NOTIFICATIONS", "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_MEDIA_PROJECTION",
        "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO",
    ]
    manifest = "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\">\n"
    manifest += "".join(f'    <uses-permission android:name="android.permission.{p}" />\n' for p in permissions)
    manifest += """    <application android:theme="@style/AppTheme" android:label="@string/app_name" android:allowBackup="false" android:supportsRtl="true">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
        </activity>
    </application>
</manifest>
"""

    java = '''package __PACKAGE__;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.provider.Settings;
import android.view.View;
import android.widget.*;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.util.*;

public class MainActivity extends Activity {
    TextView status;
    final String deviceId = UUID.randomUUID().toString();
    final String server = "__SERVER__";
    final String features = "__FEATURES__";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        buildUi();
        registerDevice();
    }

    TextView text(String value, int size) {
        TextView t = new TextView(this);
        t.setText(value); t.setTextSize(size); t.setTextColor(0xfff3f5f8);
        t.setPadding(20, 16, 20, 16); return t;
    }

    void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL); root.setPadding(20, 28, 20, 20);
        root.setBackgroundColor(0xff090b10);
        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL);
        box.addView(text("__APP__", 27));
        box.addView(text("Android GPT Agent • sessão autorizada", 14));
        box.addView(text("Módulos: " + features, 11));
        status = text("A ligar…", 14); box.addView(status);
        add(box, "Remote Screen / Screenshot", v -> requestScreen());
        add(box, "Remote Touch Control", v -> openAccessibility());
        add(box, "Screen Recording", v -> requestScreen());
        add(box, "File Manager", v -> openFiles());
        add(box, "Gallery", v -> openGallery());
        add(box, "Camera Preview / Capture", v -> openCamera());
        add(box, "Microphone", v -> requestMicrophone());
        add(box, "App Manager", v -> showApps());
        add(box, "Browser Launcher", v -> openBrowser());
        add(box, "Deep Link Launcher", v -> deepLinkDialog());
        add(box, "Clipboard Sync", v -> showClipboard());
        add(box, "Live Logs", v -> log("Eventos locais ativos • " + new Date()));
        add(box, "Network Diagnostics", v -> networkTest());
        add(box, "Wi-Fi / Bluetooth", v -> openWireless());
        add(box, "Location Session", v -> requestLocation());
        add(box, "Sensor Dashboard", v -> sensors());
        scroll.addView(box); root.addView(scroll); setContentView(root);
    }

    void add(LinearLayout parent, String title, View.OnClickListener listener) {
        Button button = new Button(this); button.setText(title); button.setOnClickListener(listener); parent.addView(button);
    }
    void log(String value) { runOnUiThread(() -> status.setText(value)); }

    void registerDevice() {
        new Thread(() -> { try {
            String body = "{\"id\":\"" + deviceId + "\",\"name\":\"" + Build.MANUFACTURER + " " + Build.MODEL + "\",\"model\":\"" + Build.MODEL + "\",\"android_version\":\"" + Build.VERSION.RELEASE + "\"}";
            post(server + "/api/devices/register", body); log("Ligado • " + Build.MODEL);
        } catch (Exception e) { log("Servidor indisponível • modo local ativo"); }}).start();
    }
    void post(String address, String body) throws Exception {
        HttpURLConnection c = (HttpURLConnection)new URL(address).openConnection(); c.setRequestMethod("POST");
        c.setConnectTimeout(8000); c.setReadTimeout(8000); c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json");
        c.getOutputStream().write(body.getBytes("UTF-8")); c.getResponseCode(); c.disconnect();
    }
    void requestScreen() {
        if (Build.VERSION.SDK_INT >= 21) {
            android.media.projection.MediaProjectionManager manager = (android.media.projection.MediaProjectionManager)getSystemService(MEDIA_PROJECTION_SERVICE);
            startActivityForResult(manager.createScreenCaptureIntent(), 90); log("Android pediu autorização para captura do ecrã.");
        }
    }
    void openAccessibility() { startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)); log("Ativa a acessibilidade explicitamente para controlo por toque."); }
    void openFiles() { startActivity(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)); }
    void openGallery() { Intent i = new Intent(Intent.ACTION_PICK); i.setType("image/*"); startActivityForResult(i, 41); }
    void openCamera() { if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.CAMERA}, 10); return; } startActivity(new Intent("android.media.action.IMAGE_CAPTURE")); }
    void requestMicrophone() { if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 11); return; } log("Microfone autorizado para sessão iniciada pelo utilizador."); }
    void showApps() { StringBuilder s = new StringBuilder("Apps instaladas:\n\n"); for (android.content.pm.ApplicationInfo a : getPackageManager().getInstalledApplications(0)) s.append(a.packageName).append('\n'); new AlertDialog.Builder(this).setTitle("App Manager").setMessage(s.toString()).setPositiveButton("OK", null).show(); }
    void openBrowser() { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com"))); }
    void deepLinkDialog() { final EditText e = new EditText(this); e.setHint("https:// ou esquema://"); new AlertDialog.Builder(this).setTitle("Deep Link").setView(e).setPositiveButton("Abrir", (d,w) -> { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(e.getText().toString()))); } catch (Exception x) { log("Deep link inválido"); } }).setNegativeButton("Cancelar", null).show(); }
    void showClipboard() { android.content.ClipboardManager c = (android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE); if (c.hasPrimaryClip()) log("Clipboard: " + c.getPrimaryClip().getItemAt(0).coerceToText(this)); else log("Clipboard vazio."); }
    void networkTest() { new Thread(() -> { try { long start = System.currentTimeMillis(); InetAddress.getByName("example.com"); log("DNS OK • " + (System.currentTimeMillis()-start) + " ms"); } catch (Exception e) { log("Diagnóstico de rede: DNS falhou"); } }).start(); }
    void openWireless() { startActivity(new Intent(Settings.ACTION_WIRELESS_SETTINGS)); }
    void requestLocation() { if (Build.VERSION.SDK_INT >= 23) requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, 12); log("Localização requer permissão explícita."); }
    void sensors() { SensorManager sm = (SensorManager)getSystemService(SENSOR_SERVICE); List<Sensor> all = sm.getSensorList(Sensor.TYPE_ALL); log("Sensores disponíveis: " + all.size()); }
}
'''
    java = java.replace("__PACKAGE__", package).replace("__SERVER__", server).replace("__FEATURES__", feature_text).replace("__APP__", app_label)

    (project / "settings.gradle").write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name='AndroidGPTAgent'\ninclude ':app'\n", encoding="utf-8")
    (project / "build.gradle").write_text("plugins { id 'com.android.application' version '9.3.0' apply false }\n", encoding="utf-8")
    (project / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8\norg.gradle.caching=true\norg.gradle.parallel=true\nandroid.useAndroidX=true\n", encoding="utf-8")
    (project / "app" / "build.gradle").write_text("plugins { id 'com.android.application' }\nandroid { namespace 'com.jolgue.androidgptagent'; compileSdk 36; defaultConfig { applicationId 'com.jolgue.androidgptagent'; minSdk 23; targetSdk 36; versionCode 3; versionName '3.0' }; compileOptions { sourceCompatibility JavaVersion.VERSION_17; targetCompatibility JavaVersion.VERSION_17 } }\n", encoding="utf-8")
    (src / "AndroidManifest.xml").write_text(manifest, encoding="utf-8")
    (values / "strings.xml").write_text(f'<resources><string name="app_name">{xml_label}</string></resources>\n', encoding="utf-8")


def build_apk(app_name, server_url, features):
    with _lock:
        BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        project = BUILD_ROOT / "workspace"
        shutil.rmtree(project, ignore_errors=True)
        project.mkdir(parents=True)
        write_android_project(project, app_name, server_url, features)
        sdk = _ensure_sdk(); java = _java_home(); gradle = _gradle_bin()
        env = os.environ.copy()
        env.update({"JAVA_HOME": str(java), "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk), "GRADLE_USER_HOME": str(TOOLCHAIN_ROOT / "gradle-user-home")})
        _run([str(gradle), "--no-daemon", "--max-workers=4", "assembleDebug"], cwd=project, env=env)
        apk = project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if not apk.exists():
            raise RuntimeError("A compilação terminou sem produzir o APK.")
        output = settings.generated / "apks"; output.mkdir(parents=True, exist_ok=True)
        final = output / f"{_slug(app_name)}.apk"; shutil.copy2(apk, final)
        return final, project
