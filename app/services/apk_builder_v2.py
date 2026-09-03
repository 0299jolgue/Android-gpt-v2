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

_GRADLE_VERSION='9.5.0'
_ANDROID_TOOLS_VERSION='15859902'
BUILD_ROOT=settings.generated/'_build'
TOOLCHAIN_ROOT=settings.generated/'.toolchain'
SDK_ROOT=TOOLCHAIN_ROOT/'android-sdk'
GRADLE_ROOT=TOOLCHAIN_ROOT/f'gradle-{_GRADLE_VERSION}'
JDK_ROOT=TOOLCHAIN_ROOT/'jdk-17'
_lock=threading.Lock()

def _download(url,destination):
    destination.parent.mkdir(parents=True,exist_ok=True); tmp=destination.with_suffix(destination.suffix+'.part'); tmp.unlink(missing_ok=True)
    req=urllib.request.Request(url,headers={'User-Agent':'Android-GPT/3.0'})
    with urllib.request.urlopen(req,timeout=120) as r,tmp.open('wb') as out:
        while True:
            chunk=r.read(1024*1024)
            if not chunk: break
            out.write(chunk)
    tmp.replace(destination)

def _run(cmd,cwd=None,env=None,input_text=None):
    r=subprocess.run(cmd,cwd=str(cwd) if cwd else None,env=env,input=input_text,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=900,check=False)
    if r.returncode: raise RuntimeError(f"Comando falhou ({r.returncode}): {' '.join(cmd)}\n{r.stdout[-12000:]}")
    return r.stdout

def _java_home():
    java=shutil.which('java')
    if java:
        try:
            out=_run([java,'-version'])
            if re.search(r'version "(?:1\\.)?(?:17|18|19|20|21|22|23|24|25)',out): return Path(java).resolve().parent.parent
        except Exception: pass
    if not (JDK_ROOT/'bin'/'java').exists():
        archive=TOOLCHAIN_ROOT/'jdk17.tar.gz'; _download('https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse',archive); JDK_ROOT.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive,'r:gz') as tar:
            top=tar.getmembers()[0].name.split('/',1)[0]
            for m in tar.getmembers():
                if m.name==top or m.name.startswith(top+'/'):
                    m.name=m.name[len(top):].lstrip('/');
                    if m.name: tar.extract(m,JDK_ROOT)
        archive.unlink(missing_ok=True)
    return JDK_ROOT

def _gradle_bin():
    p=GRADLE_ROOT/'bin'/'gradle'
    if not p.exists():
        archive=TOOLCHAIN_ROOT/f'gradle-{_GRADLE_VERSION}.zip'; _download(f'https://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-bin.zip',archive); TOOLCHAIN_ROOT.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as z:z.extractall(TOOLCHAIN_ROOT)
        archive.unlink(missing_ok=True)
    p.chmod(p.stat().st_mode|0o111); return p

def _ensure_sdk():
    sdkmanager=SDK_ROOT/'cmdline-tools'/'latest'/'bin'/'sdkmanager'
    if not sdkmanager.exists():
        archive=TOOLCHAIN_ROOT/'commandlinetools.zip'; _download(f'https://dl.google.com/android/repository/commandlinetools-linux-{_ANDROID_TOOLS_VERSION}_latest.zip',archive); temp=TOOLCHAIN_ROOT/'cmdline-tools-extract'; shutil.rmtree(temp,ignore_errors=True); temp.mkdir(parents=True)
        with zipfile.ZipFile(archive) as z:z.extractall(temp)
        target=SDK_ROOT/'cmdline-tools'/'latest'; target.parent.mkdir(parents=True,exist_ok=True); shutil.rmtree(target,ignore_errors=True); shutil.move(str(temp/'cmdline-tools'),str(target)); shutil.rmtree(temp,ignore_errors=True); archive.unlink(missing_ok=True)
    env=os.environ.copy(); env['ANDROID_HOME']=str(SDK_ROOT); env['ANDROID_SDK_ROOT']=str(SDK_ROOT); env['JAVA_HOME']=str(_java_home())
    if not (SDK_ROOT/'.licenses_accepted').exists(): _run([str(sdkmanager),'--sdk_root='+str(SDK_ROOT),'--licenses'],env=env,input_text='y\n'*40); (SDK_ROOT/'.licenses_accepted').touch()
    missing=[]
    if not (SDK_ROOT/'platforms'/'android-36').exists(): missing.append('platforms;android-36')
    if not (SDK_ROOT/'build-tools'/'36.0.0').exists(): missing.append('build-tools;36.0.0')
    if missing:_run([str(sdkmanager),'--sdk_root='+str(SDK_ROOT),*missing],env=env)
    return SDK_ROOT

def _slug(v): return (re.sub(r'[^A-Za-z0-9._-]+','_',v.strip()).strip('._-') or 'android_gpt_agent')[:48]
def _je(v): return v.replace('\\','\\\\').replace('"','\\"').replace('\r','').replace('\n','\\n')
def _xe(v): return v.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;').replace("'",'&apos;')

def write_android_project(project,app_name,server_url,features):
    package='com.jolgue.androidgptagent'; src=project/'app'/'src'/'main'; java_dir=src/'java'/Path(*package.split('.')); values=src/'res'/'values'; xml=src/'res'/'xml'; java_dir.mkdir(parents=True,exist_ok=True); values.mkdir(parents=True,exist_ok=True); xml.mkdir(parents=True,exist_ok=True)
    enabled={k for k,v in features.items() if v}; name=_je(app_name); label=_xe(app_name); feature_json=_je(json.dumps(sorted(enabled)))
    perms=['INTERNET','ACCESS_NETWORK_STATE','ACCESS_WIFI_STATE','BLUETOOTH','BLUETOOTH_CONNECT','BLUETOOTH_SCAN','ACCESS_FINE_LOCATION','ACCESS_COARSE_LOCATION','CAMERA','RECORD_AUDIO','POST_NOTIFICATIONS','FOREGROUND_SERVICE','FOREGROUND_SERVICE_MEDIA_PROJECTION','READ_MEDIA_IMAGES','READ_MEDIA_VIDEO']
    manifest='''<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'''+''.join(f'    <uses-permission android:name="android.permission.{p}" />\n' for p in perms)+'''    <application android:theme="@style/AppTheme" android:label="@string/app_name" android:usesCleartextTraffic="true" android:allowBackup="false" android:supportsRtl="true">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>\n        </activity>\n    </application>\n</manifest>\n'''
    styles='''<resources><style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar"><item name="android:fontFamily">sans</item><item name="android:colorAccent">#6750A4</item><item name="android:navigationBarColor">#090b10</item></style></resources>\n'''
    java=f'''package {package};
import android.Manifest; import android.app.*; import android.content.*; import android.content.pm.PackageManager; import android.hardware.*; import android.net.Uri; import android.net.ConnectivityManager; import android.os.*; import android.provider.Settings; import android.text.InputType; import android.view.*; import android.widget.*; import java.net.*; import java.util.*;
public class MainActivity extends Activity {{
 TextView log; LinearLayout root; final String deviceId=UUID.randomUUID().toString(); final String server="{_je(server_url.rstrip('/'))}"; final String features="{feature_json}";
 public void onCreate(Bundle b){{super.onCreate(b); build(); register();}}
 TextView tv(String s,int z){{TextView t=new TextView(this);t.setText(s);t.setTextSize(z);t.setTextColor(0xfff3f5f8);t.setPadding(20,16,20,16);return t;}}
 void build(){{root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(20,30,20,20);root.setBackgroundColor(0xff090b10); ScrollView sc=new ScrollView(this);LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.addView(tv("{name}",26));box.addView(tv("Android GPT Agent • sessão autorizada",14));box.addView(tv("Módulos: "+features,11)); log=tv("Pronto.",13);box.addView(log); add(box,"Remote Screen / Screenshot",v->screen()); add(box,"Remote Touch Control",v->accessibility()); add(box,"Screen Recording",v->screen()); add(box,"File Manager",v->files()); add(box,"Gallery",v->gallery()); add(box,"Camera Preview / Capture",v->camera()); add(box,"Microphone",v->mic()); add(box,"App Manager",v->apps()); add(box,"Browser Launcher",v->browser()); add(box,"Deep Link Launcher",v->deeplink()); add(box,"Clipboard Sync",v->clipboard()); add(box,"Live Logs",v->logs()); add(box,"Network Diagnostics",v->network()); add(box,"Wi-Fi / Bluetooth",v->wireless()); add(box,"Location Session",v->location()); add(box,"Sensor Dashboard",v->sensors()); sc.addView(box);setContentView(sc);}}
 void add(LinearLayout p,String s,View.OnClickListener l){{Button b=new Button(this);b.setText(s);b.setOnClickListener(l);p.addView(b);}}
 void note(String s){{runOnUiThread(()->log.setText(s));}}
 void register(){{new Thread(()->{{try{{org.json.JSONObject j=new org.json.JSONObject();j.put("id",deviceId);j.put("name",Build.MANUFACTURER+" "+Build.MODEL);j.put("model",Build.MODEL);j.put("android_version",Build.VERSION.RELEASE);post(server+"/api/devices/register",j.toString());note("Ligado • "+Build.MODEL);}}catch(Exception e){{note("Servidor indisponível • funcionalidades locais continuam disponíveis");}}}}).start();}}
 void post(String u,String body)throws Exception{{HttpURLConnection c=(HttpURLConnection)new URL(u).openConnection();c.setRequestMethod("POST");c.setConnectTimeout(8000);c.setReadTimeout(8000);c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");c.getOutputStream().write(body.getBytes("UTF-8"));c.getResponseCode();c.disconnect();}}
 void screen(){{if(Build.VERSION.SDK_INT>=21){{MediaProjectionManagerHack.request(this);}}else note("MediaProjection não suportado nesta versão.");}}
 void accessibility(){{startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));note("Ativa o serviço de acessibilidade explicitamente para permitir controlo por toque.");}}
 void files(){{startActivity(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE));}}
 void gallery(){{Intent i=new Intent(Intent.ACTION_PICK);i.setType("image/*");startActivityForResult(i,41);}}
 void camera(){{if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{{Manifest.permission.CAMERA}},10);return;}startActivity(new Intent("android.media.action.IMAGE_CAPTURE"));}}
 void mic(){{if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){{requestPermissions(new String[]{{Manifest.permission.RECORD_AUDIO}},11);return;}}note("Microfone autorizado. Inicia uma gravação visível apenas durante a sessão.");}}
 void apps(){{StringBuilder s=new StringBuilder("Apps instaladas:\\n");for(android.content.pm.ApplicationInfo a:getPackageManager().getInstalledApplications(0))s.append(a.packageName).append('\\n');new AlertDialog.Builder(this).setTitle("App Manager").setMessage(s.toString()).setPositiveButton("OK",null).show();}}
 void browser(){{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse("https://example.com")));}}
 void deeplink(){{final EditText e=new EditText(this);e.setHint("https:// ou esquema://");new AlertDialog.Builder(this).setTitle("Deep Link").setView(e).setPositiveButton("Abrir",(d,w)->{{try{{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(e.getText().toString())));}}catch(Exception x){{note("Deep link inválido");}}}}).setNegativeButton("Cancelar",null).show();}}
 void clipboard(){{android.content.ClipboardManager c=(android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE);if(c.hasPrimaryClip())note("Clipboard: "+c.getPrimaryClip().getItemAt(0).coerceToText(this));else note("Clipboard vazio.");}}
 void logs(){{note("Live Logs ativo para eventos da aplicação.\n"+new java.util.Date());}}
 void network(){{new Thread(()->{{try{{long a=System.currentTimeMillis();InetAddress.getByName("example.com");note("DNS OK • "+(System.currentTimeMillis()-a)+" ms");}}catch(Exception e){{note("Network diagnostic: erro DNS");}}}}).start();}}
 void wireless(){{startActivity(new Intent(Settings.ACTION_WIRELESS_SETTINGS));}}
 void location(){{if(Build.VERSION.SDK_INT>=23)requestPermissions(new String[]{{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION}},12);note("Sessão de localização requer permissão explícita.");}}
 void sensors(){{SensorManager sm=(SensorManager)getSystemService(SENSOR_SERVICE);List<Sensor> l=sm.getSensorList(Sensor.TYPE_ALL);note("Sensores disponíveis: "+l.size());}}
 static class MediaProjectionManagerHack{{static void request(Activity a){{android.media.projection.MediaProjectionManager m=(android.media.projection.MediaProjectionManager)a.getSystemService(MEDIA_PROJECTION_SERVICE);a.startActivityForResult(m.createScreenCaptureIntent(),90);}}}}
}}'''
    (project/'settings.gradle').write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name='AndroidGPTAgent'\ninclude ':app'\n",encoding='utf-8')
    (project/'build.gradle').write_text("plugins { id 'com.android.application' version '9.3.0' apply false }\n",encoding='utf-8')
    (project/'gradle.properties').write_text('org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8\norg.gradle.caching=true\norg.gradle.parallel=true\nandroid.useAndroidX=true\n',encoding='utf-8')
    (project/'app'/'build.gradle').write_text("plugins { id 'com.android.application' }\nandroid { namespace 'com.jolgue.androidgptagent'; compileSdk 36; defaultConfig { applicationId 'com.jolgue.androidgptagent'; minSdk 23; targetSdk 36; versionCode 2; versionName '2.0' }; compileOptions { sourceCompatibility JavaVersion.VERSION_17; targetCompatibility JavaVersion.VERSION_17 } }\n",encoding='utf-8')
    (src/'AndroidManifest.xml').write_text(manifest,encoding='utf-8'); (values/'strings.xml').write_text(f'<resources><string name="app_name">{label}</string></resources>\n',encoding='utf-8'); (values/'styles.xml').write_text(styles,encoding='utf-8'); (java_dir/'MainActivity.java').write_text(java,encoding='utf-8'); (project/'android-gpt.json').write_text(json.dumps({'schema':3,'app_name':app_name,'server_url':server_url,'features':features},indent=2),encoding='utf-8')

def build_apk(app_name,server_url,features):
    with _lock:
        BUILD_ROOT.mkdir(parents=True,exist_ok=True); project=BUILD_ROOT/'workspace'; shutil.rmtree(project,ignore_errors=True); project.mkdir(parents=True); write_android_project(project,app_name,server_url,features)
        sdk=_ensure_sdk(); java=_java_home(); gradle=_gradle_bin(); env=os.environ.copy(); env.update({'JAVA_HOME':str(java),'ANDROID_HOME':str(sdk),'ANDROID_SDK_ROOT':str(sdk),'GRADLE_USER_HOME':str(TOOLCHAIN_ROOT/'gradle-user-home')})
        _run([str(gradle),'--daemon','--parallel','--max-workers=8','assembleDebug'],cwd=project,env=env)
        apk=project/'app'/'build'/'outputs'/'apk'/'debug'/'app-debug.apk'
        if not apk.exists(): raise RuntimeError('A compilação terminou sem produzir o APK.')
        out=settings.generated/'apks';out.mkdir(parents=True,exist_ok=True);final=out/f'{_slug(app_name)}.apk';shutil.copy2(apk,final);return final,project
