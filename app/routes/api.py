import json
import re
import time
import uuid
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from ..config import settings
from ..database import get_device, list_devices, set_device_status, upsert_device
from ..security import is_authenticated
from ..services import apk_builder_v3 as apk_builder
from ..services.apk_builder_v3 import build_apk
from ..services.generator import FEATURES, create_project

# The generated manifest uses @style/AppTheme. Keep the generated Android
# project self-contained even when the builder template has no style resource.
_original_write_android_project = apk_builder.write_android_project

def _write_android_project_with_theme(project, app_name, server_url, features):
    result = _original_write_android_project(project, app_name, server_url, features)
    values = project / 'app' / 'src' / 'main' / 'res' / 'values'
    values.mkdir(parents=True, exist_ok=True)
    (values / 'styles.xml').write_text('''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar">
        <item name="android:fontFamily">sans</item>
        <item name="android:windowActionModeOverlay">true</item>
        <item name="android:colorAccent">#5B8CFF</item>
    </style>
</resources>
''', encoding='utf-8')
    return result

apk_builder.write_android_project = _write_android_project_with_theme

router=APIRouter(); _executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='apk-builder'); _jobs={}

def _public_server_url(request: Request):
    """Prefer the browser-visible origin so generated APKs never target 0.0.0.0/internal hosts."""
    origin = request.headers.get('origin', '').strip().rstrip('/')
    if origin and re.match(r'^https?://[^/]+$', origin):
        return origin

    forwarded_host = request.headers.get('x-forwarded-host', '').split(',')[0].strip()
    forwarded_proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip()
    host = forwarded_host or request.headers.get('host', '').strip() or request.url.netloc
    proto = forwarded_proto or request.url.scheme

    # Never embed container-only bind addresses in an Android build.
    if host in {'0.0.0.0', '127.0.0.1', 'localhost', '::1'}:
        return ''
    return f'{proto}://{host}'.rstrip('/')

def _safe_slug(v): return (re.sub(r'[^A-Za-z0-9._-]+','_',v.strip()).strip('._-') or 'android_gpt_agent')[:48]
def _cache_paths(app_name):
    base=_safe_slug(app_name); root=settings.generated/'apks'; return root/f'{base}.apk',root/f'{base}.json'
def _metadata_for(apk, metadata):
    try:saved=json.loads(metadata.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError):return None
    if not isinstance(saved, dict): return None
    token=saved.get('public_token')
    if not token:
        token=secrets.token_urlsafe(24)
        saved['public_token']=token
        try: metadata.write_text(json.dumps(saved,indent=2),encoding='utf-8')
        except OSError: pass
    return saved

def _cached_apk(app_name,server_url,features):
    apk,metadata=_cache_paths(app_name)
    if not apk.is_file() or not metadata.is_file(): return None
    saved=_metadata_for(apk,metadata)
    if not saved:
        return None
    return apk if (
        saved.get('app_name') == app_name and
        saved.get('server_url') == server_url.rstrip('/') and
        saved.get('features') == features and
        bool(saved.get('public_token'))
    ) else None

def _save_cache_metadata(app_name,server_url,features):
    _,metadata=_cache_paths(app_name); metadata.parent.mkdir(parents=True,exist_ok=True)
    metadata.write_text(json.dumps({'app_name':app_name,'server_url':server_url.rstrip('/'),'features':features,'public_token':secrets.token_urlsafe(24)},indent=2),encoding='utf-8')

def _run_build(job_id,app_name,server_url,features):
    _jobs[job_id].update(status='building',message='A preparar o ambiente Android e a compilar o APK…')
    try:
        if not server_url:
            raise RuntimeError('Não foi possível determinar o URL público do servidor. Abra o painel através do endereço público do ShardCloud e gere o APK novamente.')
        apk=_cached_apk(app_name,server_url,features); project=None
        if apk is None: apk,project=build_apk(app_name,server_url,features); _save_cache_metadata(app_name,server_url,features)
        public_url=f'/api/public/apk/{_metadata_for(apk,settings.generated/"apks"/(apk.stem+".json")).get("public_token")}' if apk else None
        _jobs[job_id].update(status='ready',message='APK pronta.',download=f'/api/generator/download/{apk.name}',public_url=public_url,project=str(project.relative_to(settings.generated)) if project else None)
    except Exception as exc:_jobs[job_id].update(status='error',message=str(exc))

@router.get('/health')
def health():return {'ok':True,'service':'android-gpt'}
@router.get('/stats')
def stats():
    devices=list_devices(); online=sum(d['status']=='online' for d in devices); return {'total':len(devices),'online':online,'offline':len(devices)-online}
@router.post('/generator')
async def generator(request:Request):
    if not is_authenticated(request):return JSONResponse({'ok':False,'error':'login_required'},status_code=401)
    data=await request.form(); app_name=str(data.get('app_name','Android GPT Agent')).strip() or 'Android GPT Agent'; server_url=_public_server_url(request); features={name:bool(data.get(name)) for name in FEATURES}; create_project(app_name,server_url,features); job_id=uuid.uuid4().hex; cached=_cached_apk(app_name,server_url,features)
    if cached is not None:_jobs[job_id]={'status':'ready','message':'APK já existente para esta configuração.','app_name':app_name,'download':f'/api/generator/download/{cached.name}','public_url':f'/api/public/apk/{_metadata_for(cached,settings.generated/"apks"/(cached.stem+".json"))["public_token"]}'}; return {'ok':True,'job_id':job_id,'status_url':f'/api/generator/status/{job_id}'}
    _jobs[job_id]={'status':'queued','message':'APK colocada na fila de compilação.','app_name':app_name}; _executor.submit(_run_build,job_id,app_name,server_url,features); return {'ok':True,'job_id':job_id,'status_url':f'/api/generator/status/{job_id}'}
@router.get('/generator/status/{job_id}')
def generator_status(request:Request,job_id:str):
    if not is_authenticated(request):return JSONResponse({'ok':False,'error':'login_required'},status_code=401)
    job=_jobs.get(job_id)
    if not job:return JSONResponse({'ok':False,'error':'job_not_found'},status_code=404)
    if job.get('status')=='ready' and not job.get('public_url'):
        apk_name=Path(job.get('download','')).name
        metadata=settings.generated/'apks'/(Path(apk_name).stem+'.json')
        saved=_metadata_for(settings.generated/'apks'/apk_name,metadata) if (settings.generated/'apks'/apk_name).is_file() else None
        if saved: job['public_url']=f'/api/public/apk/{saved["public_token"]}'
    return {'ok':True,'job_id':job_id,**job}
@router.get('/generator/download/{filename}')
def generator_download(request:Request,filename:str):
    if not is_authenticated(request):return JSONResponse({'ok':False,'error':'login_required'},status_code=401)
    safe=Path(filename).name; path=settings.generated/'apks'/safe
    if path.parent!=settings.generated/'apks' or not path.is_file() or path.suffix.lower()!='.apk':return JSONResponse({'ok':False,'error':'apk_not_found'},status_code=404)
    return FileResponse(path,media_type='application/vnd.android.package-archive',filename=safe)
@router.get('/public/apk/{token}')
def public_apk(token:str):
    root=settings.generated/'apks'
    for metadata in root.glob('*.json'):
        saved=_metadata_for(root/(metadata.stem+'.apk'),metadata)
        if saved and secrets.compare_digest(str(saved.get('public_token','')),token):
            apk=root/(metadata.stem+'.apk')
            if apk.is_file():
                return FileResponse(apk,media_type='application/vnd.android.package-archive',filename=apk.name,headers={'Content-Disposition':f'attachment; filename="{apk.name}"'})
    return JSONResponse({'ok':False,'error':'apk_not_found'},status_code=404)
@router.get('/apks')
def list_apks(request:Request):
    if not is_authenticated(request):return JSONResponse({'ok':False,'error':'login_required'},status_code=401)
    root=settings.generated/'apks'; items=[]
    for apk in sorted(root.glob('*.apk'),key=lambda p:p.stat().st_mtime,reverse=True):
        metadata=root/(apk.stem+'.json'); saved=_metadata_for(apk,metadata) if metadata.is_file() else {}
        public_token=(saved or {}).get('public_token')
        items.append({'name':apk.name,'size':apk.stat().st_size,'created_at':apk.stat().st_mtime,'public_url':f'/api/public/apk/{public_token}' if public_token else None,'download_url':f'/api/generator/download/{apk.name}'})
    return {'ok':True,'apks':items}
@router.post('/devices/register')
async def register(request:Request):
    data=await request.json(); device_id=str(data.get('id','')).strip()
    if not device_id:return {'ok':False,'error':'id is required'}
    token=upsert_device(device_id,str(data.get('name','Android device')),str(data.get('model','')),str(data.get('android_version',''))); return {'ok':True,'device_id':device_id,'token':token}
@router.get('/devices/{device_id}')
def device_info(device_id:str):
    device=get_device(device_id)
    if not device:return JSONResponse({'ok':False,'error':'not_found'},status_code=404)
    return {'ok':True,'device':dict(device)}
@router.post('/devices/{device_id}/heartbeat')
def heartbeat(device_id:str):
    if not get_device(device_id):return JSONResponse({'ok':False,'error':'not_found'},status_code=404)
    set_device_status(device_id,'online'); return {'ok':True,'timestamp':time.time()}
@router.get('/devices')
def devices():return {'devices':[dict(d) for d in list_devices()]}
@router.get('/admin/status')
def admin_status(request:Request):
    if not is_authenticated(request):return JSONResponse({'ok':False,'error':'login_required'},status_code=401)
    return stats()
