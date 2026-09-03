document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-time]').forEach((el) => { const v=Number(el.dataset.time); if(!Number.isNaN(v)&&v>0) el.textContent=new Date(v*1000).toLocaleString('pt-PT'); });
  const form=document.querySelector('[data-apk-generator]'); const result=document.querySelector('[data-apk-result]');
  if(form&&result){
    const count=()=>{const n=form.querySelectorAll('input[type="checkbox"]:checked').length; const el=form.querySelector('[data-feature-count]'); if(el)el.textContent=n;};
    form.querySelectorAll('input[type="checkbox"]').forEach(x=>x.addEventListener('change',count)); count();
    let activeJob=null;
    const notify=async(t,b)=>{try{if(!('Notification'in window))return;if(Notification.permission==='default')await Notification.requestPermission();if(Notification.permission==='granted')new Notification(t,{body:b,tag:'android-gpt-build'});}catch(_){}};
    const save=j=>localStorage.setItem('android-gpt-apk-job',JSON.stringify(j));
    const load=()=>{try{return JSON.parse(localStorage.getItem('android-gpt-apk-job')||'null')}catch(_){return null}};
    const show=(s,button)=>{result.hidden=false;if(s.status==='ready'){const publicUrl=s.public_url||s.download;result.innerHTML=`<strong>APK pronta ✓</strong><p>${escapeHtml(s.message||'A compilação terminou.')}</p><div class="result-actions"><a class="button" href="${s.download}">Baixar APK</a><button class="button ghost" type="button" data-copy-link="${publicUrl}">Copiar link público</button></div><p class="mono public-link">${escapeHtml(new URL(publicUrl,window.location.origin).href)}</p>`;if(button)button.disabled=false;if(activeJob&&!activeJob.notified){notify('Android GPT','A APK terminou de compilar.');activeJob.notified=true;save(activeJob)}return true}if(s.status==='error'){result.innerHTML=`<strong>Erro na compilação</strong><p>${escapeHtml(s.message||'Erro desconhecido.')}</p>`;if(button)button.disabled=false;return true}result.innerHTML=`<strong>${s.status==='queued'?'Na fila…':'A compilar…'}</strong><p>${escapeHtml(s.message||'A preparar…')}</p>`;return false};
    const poll=async(j,button)=>{activeJob=j;try{const r=await fetch(j.status_url,{cache:'no-store'});const s=await r.json();if(!r.ok||!s.ok)throw new Error(s.error||'Job indisponível.');save({...j,lastStatus:s.status});if(!show(s,button))setTimeout(()=>poll(j,button),2000)}catch(e){result.hidden=false;result.innerHTML=`<strong>Acompanhamento interrompido</strong><p>${escapeHtml(e.message||String(e))}</p>`;if(button)button.disabled=false}};
    form.addEventListener('submit',async e=>{e.preventDefault();result.hidden=false;result.innerHTML='<strong>A iniciar…</strong><p>A preparar o APK com as capacidades selecionadas.</p>';const button=form.querySelector('button[type="submit"]');if(button)button.disabled=true;try{const r=await fetch(form.action,{method:'POST',body:new FormData(form)});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Não foi possível iniciar.');activeJob={job_id:d.job_id,status_url:d.status_url,notified:false};save(activeJob);poll(activeJob,button)}catch(e){result.innerHTML=`<strong>Erro</strong><p>${escapeHtml(e.message||String(e))}</p>`;if(button)button.disabled=false}});
    const old=load(); if(old&&old.status_url){result.hidden=false;result.innerHTML='<strong>A recuperar compilação…</strong><p>A verificar o build anterior.</p>';poll(old,form.querySelector('button[type="submit"]'))}
  }

  const library=document.querySelector('[data-apk-library]');
  if(library){
    const list=library.querySelector('[data-apk-list]');
    const refresh=library.querySelector('[data-refresh-apks]');
    const fmtSize=(bytes)=>{if(bytes<1024*1024)return `${Math.max(1,Math.round(bytes/1024))} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`};
    const loadApks=async()=>{list.innerHTML='<div class="empty">A carregar APKs…</div>';try{const r=await fetch('/api/apks',{cache:'no-store'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Não foi possível carregar as APKs.');if(!d.apks.length){list.innerHTML='<div class="empty">Ainda não existem APKs gerados.</div>';return;}list.innerHTML=d.apks.map(a=>{const full=new URL(a.public_url,window.location.origin).href;return `<article class="apk-item"><div class="apk-main"><strong>${escapeHtml(a.name)}</strong><small>${fmtSize(a.size)} · ${new Date(a.created_at*1000).toLocaleString('pt-PT')}</small><code>${escapeHtml(full)}</code></div><div class="apk-actions"><a class="button" href="${a.public_url}">Baixar</a><button class="button ghost" type="button" data-copy-link="${a.public_url}">Copiar link</button></div></article>`}).join('')}catch(e){list.innerHTML=`<div class="empty">${escapeHtml(e.message||String(e))}</div>`}};
    loadApks(); if(refresh)refresh.addEventListener('click',loadApks);
  }

  document.addEventListener('click',async(e)=>{const button=e.target.closest('[data-copy-link]');if(!button)return;const value=new URL(button.dataset.copyLink,window.location.origin).href;try{await navigator.clipboard.writeText(value);const old=button.textContent;button.textContent='Copiado ✓';setTimeout(()=>button.textContent=old,1400)}catch(_){window.prompt('Copia o link público:',value)}});
});
function escapeHtml(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');}
