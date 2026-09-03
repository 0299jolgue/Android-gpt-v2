import json
import shutil
from pathlib import Path

from . import apk_builder_v3 as builder
from ..config import settings

_MARKER = settings.generated / ".launcher_source_fix_v1"
_ORIGINAL = builder.write_android_project

_JAVA = '''package __PACKAGE__;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Timer;
import java.util.TimerTask;
import java.util.UUID;

public class MainActivity extends Activity {
    private final String deviceId = UUID.randomUUID().toString();
    private final String server = "__SERVER__";
    private TextView status;
    private Timer heartbeat;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        buildUi();
        registerDevice();
    }

    @Override protected void onDestroy() {
        if (heartbeat != null) heartbeat.cancel();
        super.onDestroy();
    }

    private TextView text(String value, int size) {
        TextView t = new TextView(this);
        t.setText(value);
        t.setTextSize(size);
        t.setPadding(20, 16, 20, 16);
        return t;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(20, 24, 20, 20);
        root.addView(text("__APP__", 26));
        root.addView(text("Android GPT Agent · dispositivo autorizado", 15));
        root.addView(text("ID: " + deviceId, 11));
        status = text("A ligar ao servidor…", 14);
        root.addView(status);

        Button check = new Button(this);
        check.setText("Testar ligação");
        check.setOnClickListener(v -> registerDevice());
        root.addView(check);

        Button heartbeatButton = new Button(this);
        heartbeatButton.setText("Enviar heartbeat");
        heartbeatButton.setOnClickListener(v -> sendHeartbeat());
        root.addView(heartbeatButton);

        ScrollView scroll = new ScrollView(this);
        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.addView(text("Estado: sessão visível e autorizada.", 13));
        info.addView(text("Fabricante: " + Build.MANUFACTURER, 13));
        info.addView(text("Modelo: " + Build.MODEL, 13));
        info.addView(text("Android: " + Build.VERSION.RELEASE, 13));
        scroll.addView(info);
        root.addView(scroll);
        setContentView(root);
    }

    private void setStatus(String value) {
        runOnUiThread(() -> status.setText(value));
    }

    private void registerDevice() {
        new Thread(() -> {
            try {
                String body = "{\\"id\\":\\"" + deviceId + "\\",\\"name\\":\\"" +
                    Build.MANUFACTURER + " " + Build.MODEL + "\\",\\"model\\":\\"" +
                    Build.MODEL + "\\",\\"android_version\\":\\"" + Build.VERSION.RELEASE + "\\"}";
                post(server + "/api/devices/register", body);
                setStatus("Online · " + Build.MODEL);
                startHeartbeat();
            } catch (Exception e) {
                setStatus("Servidor indisponível");
            }
        }).start();
    }

    private void startHeartbeat() {
        if (heartbeat != null) heartbeat.cancel();
        heartbeat = new Timer();
        heartbeat.scheduleAtFixedRate(new TimerTask() {
            @Override public void run() { sendHeartbeat(); }
        }, 1000, 30000);
    }

    private void sendHeartbeat() {
        new Thread(() -> {
            try {
                post(server + "/api/devices/" + deviceId + "/heartbeat", "{}");
                setStatus("Online · heartbeat recebido");
            } catch (Exception e) {
                setStatus("Servidor indisponível · a tentar novamente");
            }
        }).start();
    }

    private void post(String address, String body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(address).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(8000);
        c.setReadTimeout(8000);
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json");
        c.getOutputStream().write(body.getBytes("UTF-8"));
        int code = c.getResponseCode();
        c.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code);
    }
}
'''


def _write_fixed_launcher(project, app_name, server_url):
    package = "com.jolgue.androidgptagent"
    target = project / "app" / "src" / "main" / "java" / Path(*package.split(".")) / "MainActivity.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    java = (_JAVA.replace("__PACKAGE__", package)
            .replace("__SERVER__", server_url.rstrip("/")))
    java = java.replace("__APP__", app_name.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n'))
    target.write_text(java, encoding="utf-8")
    if not target.is_file() or target.stat().st_size < 500:
        raise RuntimeError("Falha ao criar MainActivity.java no projeto Android gerado.")


def _patched_write(project, app_name, server_url, features):
    result = _ORIGINAL(project, app_name, server_url, features)
    _write_fixed_launcher(project, app_name, server_url)
    return result


builder.write_android_project = _patched_write

# Invalidate APKs generated before the launcher source fix exactly once.
try:
    if not _MARKER.exists():
        root = settings.generated / "apks"
        if root.exists():
            for apk in root.glob("*.apk"):
                apk.unlink(missing_ok=True)
            for meta in root.glob("*.json"):
                meta.unlink(missing_ok=True)
        _MARKER.parent.mkdir(parents=True, exist_ok=True)
        _MARKER.write_text(json.dumps({"version": 1}), encoding="utf-8")
except OSError:
    pass
