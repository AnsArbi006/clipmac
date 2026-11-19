let reportClip=null;
function openReport(job){
  reportClip=job;
  $('report-title').textContent='Problem melden';
  $('report-clip').textContent=job.result.metadata?.title||job.clip.title||job.id;
  $('report-note').value='';$('report-position').value='';$('report-error').textContent='';
  $('report-save').disabled=false;
  const video=$('report-video');video.pause();video.removeAttribute('src');
  video.hidden=!job.result.file;$('report-use-time').hidden=!job.result.file;
  if(job.result.file)video.src='/video/'+encodeURIComponent(job.id);
  $('report-effect').textContent=['published','uploaded_private'].includes(job.status)?
    'Das Video ist bereits hochgeladen. Die Meldung verändert oder löscht den YouTube-Upload nicht.':
    ['uploading','upload_unknown'].includes(job.status)?'Ein bereits gestarteter Upload wird durch die Meldung nicht abgebrochen.':
    'Nach dem Melden wird dieses Video bis zur Klärung nicht automatisch veröffentlicht. Andere Videos laufen weiter.';
  $('report-dialog').showModal();$('report-note').focus();
}
$('report-close').onclick=()=>$('report-dialog').close();
$('report-dialog').addEventListener('close',()=>$('report-video').pause());
$('report-use-time').onclick=()=>{$('report-video').pause();$('report-position').value=$('report-video').currentTime.toFixed(1)};
$('report-form').onsubmit=async e=>{
  e.preventDefault();$('report-save').disabled=true;$('report-error').textContent='';
  try{
    const raw=$('report-position').value;
    await post('report',{id:reportClip.id,note:$('report-note').value,position:raw===''?null:Number(raw)});
    $('report-dialog').close();
    show('Meldung gespeichert. Vergleich und Prüffall werden vorbereitet. Die anschließende Korrektur erfolgt mit Codex.');
  }catch(error){$('report-error').textContent=error.message;$('report-save').disabled=false}
};
const reportOpenDetails=new Set();
function renderReports(row,job,reports){
  const related=reports.filter(r=>r.clip_id===job.id);
  if(!related.length)return;
  const area=el('div',undefined,'report-list');
  for(const r of related){
    const details=document.createElement('details');details.open=reportOpenDetails.has(r.id);
    details.addEventListener('toggle',()=>{if(details.open)reportOpenDetails.add(r.id);else reportOpenDetails.delete(r.id)});
    const title=r.status==='withdrawn'?'Meldung zurückgezogen':r.status==='resolved'?'Problem behoben':
      r.evidence_state==='ready'?'Prüffall bereit · Korrektur offen':r.evidence_state==='failed'?'Meldung gespeichert · Auswertung fehlgeschlagen':'Meldung gespeichert · Prüffall wird vorbereitet';
    details.append(el('summary',title));
    details.append(el('p',r.note,'report-note'));
    details.append(el('small',r.position===null?'Keine genaue Stelle angegeben.':`Gemeldete Stelle im fertigen Video: ${r.position} Sekunden`));
    const a=r.analysis||{};
    if(a.facts?.length){details.append(el('b','Technischer Befund'));for(const fact of a.facts)details.append(el('p',fact))}
    if(a.hypothesis){details.append(el('b','Mögliche Ursache – noch zu prüfen'),el('p',a.hypothesis))}
    if(a.checks?.length){details.append(el('b','Für die Korrektur prüfen'));const list=el('ul');for(const check of a.checks)list.append(el('li',check));details.append(list)}
    const pair=a.frames?.find(f=>Math.abs(f.output_time-a.sample_time)<.1)||a.frames?.[0];
    if(pair){
      details.append(el('small',`${a.time_selected_by_user?'Vergleich nahe deiner Zeitangabe':'Automatisch gewählte Vergleichsstelle'}: ${pair.output_time} s im fertigen Video`));
      const comparison=el('div',undefined,'report-comparison');
      for(const [key,label] of [['source','Original'],['output','Bearbeitet']])if(pair[key]){const figure=el('figure');const img=el('img');img.src=pair[key];img.alt=label+' an der Vergleichsstelle';img.loading='lazy';figure.append(img,el('figcaption',label));comparison.append(figure)}
      details.append(comparison);
    }
    for(const note of a.evidence_notes||[])details.append(el('small',note));
    if(r.error)details.append(el('small',r.error));
    if(r.status==='open'){
      details.append(el('small','Prüffall gespeichert. Codex kann damit die Ursache untersuchen und eine geprüfte Korrektur umsetzen. Noch keine automatische Modell- oder Codeänderung.'));
      const withdraw=el('button','Meldung zurückziehen');withdraw.type='button';
      withdraw.onclick=()=>post('report-withdraw',{report_id:r.id}).catch(e=>show(e.message));details.append(withdraw);
      if(!['published','uploaded_private','skipped','uploading','upload_unknown'].includes(job.status))details.append(el('small','Upload dieses Videos wartet auf Klärung. Zurückziehen hebt diese Meldung als Upload-Sperre auf.'));
    }
    area.append(details);
  }
  row.append(area);
}

refresh().catch(e=>show(e.message));setInterval(()=>refresh().catch(()=>{}),3000);
