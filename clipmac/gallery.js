let galleryState=null, galleryFilter='all', galleryLimit=24, previewClipId=null;
const galleryControls={query:'',creator:'',sort:'recent'};
const playSvg='<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 5 11 7-11 7V5Z" fill="currentColor"/></svg>';
function hasOpenReport(s,id){return (s.reports||[]).some(r=>r.clip_id===id&&r.status==='open')}
function currentRating(s,id){return (s.learning?.ratings||[]).find(r=>r.clip_id===id&&r.current_revision)?.value}
function galleryMatches(job,s){
  const text=[job.result.metadata?.title,job.clip.title,job.clip.broadcaster_name].join(' ').toLocaleLowerCase('de');
  if(galleryControls.query&&!text.includes(galleryControls.query.toLocaleLowerCase('de')))return false;
  if(galleryControls.creator&&job.clip.broadcaster_name!==galleryControls.creator)return false;
  if(galleryFilter==='unrated')return Boolean(job.result.file)&&!currentRating(s,job.id)&&job.status!=='skipped';
  if(galleryFilter==='ready')return job.status==='ready';
  if(galleryFilter==='published')return ['published','uploaded_private'].includes(job.status);
  if(galleryFilter==='problems')return hasOpenReport(s,job.id)||['failed','upload_unknown'].includes(job.status);
  return true;
}
function invalidateGallery(){previousJobsKey='';galleryLimit=24;if(galleryState)renderGallery(galleryState)}
for(const button of document.querySelectorAll('[data-filter]'))button.onclick=()=>{galleryFilter=button.dataset.filter;invalidateGallery()};
$('clip-search').oninput=()=>{galleryControls.query=$('clip-search').value.trim();invalidateGallery()};
$('creator-filter').onchange=()=>{galleryControls.creator=$('creator-filter').value;invalidateGallery()};
$('clip-sort').onchange=()=>{galleryControls.sort=$('clip-sort').value;invalidateGallery()};
$('load-more').onclick=()=>{galleryLimit+=24;previousJobsKey='';renderGallery(galleryState)};
$('open-settings').onclick=()=>$('settings-dialog').showModal();
$('close-settings').onclick=()=>$('settings-dialog').close();
$('preview-close').onclick=()=>$('preview-dialog').close();
$('preview-dialog').addEventListener('close',()=>{$('preview-video').pause();$('preview-video').removeAttribute('src');$('preview-video').load();previewClipId=null});
$('preview-report').onclick=()=>{const job=galleryState.jobs.find(j=>j.id===previewClipId);$('preview-dialog').close();if(job)openReport(job)};
function updatePreviewReview(){
  if(!previewClipId)return;const job=galleryState.jobs.find(j=>j.id===previewClipId);if(!job)return;
  $('preview-review').replaceChildren();renderLearning($('preview-review'),job,galleryState.learning||{});
}
function openPreview(job){
  previewClipId=job.id;$('preview-title').textContent=job.result.metadata?.title||job.clip.title||job.id;
  $('preview-video').src='/video/'+encodeURIComponent(job.id);updatePreviewReview();$('preview-dialog').showModal();
}
function renderGallery(s){
  galleryState=s;
  const names=[...new Set(s.jobs.map(j=>j.clip.broadcaster_name).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  const selector=$('creator-filter');
  if(selector.dataset.names!==JSON.stringify(names)){
    selector.replaceChildren(new Option('Alle Streamer',''),...names.map(n=>new Option(n,n)));selector.value=galleryControls.creator;selector.dataset.names=JSON.stringify(names);
  }
  const jobsKey=JSON.stringify([s.jobs,s.reports,s.learning,galleryFilter,galleryControls,galleryLimit]);
  if(jobsKey===previousJobsKey)return;previousJobsKey=jobsKey;
  const all=s.jobs.filter(j=>galleryMatches(j,s)).sort(galleryControls.sort==='views'?(a,b)=>(b.clip.view_count||0)-(a.clip.view_count||0):(a,b)=>b.created-a.created);
  $('library-count').textContent=s.jobs.length;
  $('library-subtitle').textContent=`${s.settings.streamers.length} Streamer · Deine Auswahl, dein Schnitt, dein Feedback.`;
  for(const b of document.querySelectorAll('[data-filter]'))b.setAttribute('aria-pressed',String(b.dataset.filter===galleryFilter));
  const jobs=$('jobs');jobs.replaceChildren();
  if(!all.length){const empty=el('div',undefined,'empty');empty.append(el('b','Keine Clips in dieser Auswahl.'),el('div','Wähle einen anderen Filter oder ändere deinen Suchbegriff.'));jobs.append(empty)}
  for(const job of all.slice(0,galleryLimit))jobs.append(videoCard(job,s));
  $('visible-count').textContent=`${Math.min(galleryLimit,all.length)} von ${all.length} Clips`;
  $('load-more').hidden=all.length<=galleryLimit;
  updatePreviewReview();
}
function videoCard(job,s){
  const synthetic=job.result.synthetic===true;
  const title=job.result.metadata?.title||job.clip.title||job.id;
  const row=el('article',undefined,'job video-card');row.dataset.status=job.status;row.dataset.clipId=job.id;
  const thumbnail=el(job.result.file||synthetic?'button':'a',undefined,'video-thumbnail');
  thumbnail.setAttribute('aria-label',job.result.file?'Vorschau: '+title:'Originalclip auf Twitch: '+title);
  if(job.result.file){thumbnail.type='button';thumbnail.onclick=()=>openPreview(job)}
  else if(synthetic){thumbnail.disabled=true;thumbnail.setAttribute('aria-label','Synthetisches Vorschaubild ohne Video')}
  else{thumbnail.href=job.clip.url||'https://www.twitch.tv/';thumbnail.target='_blank';thumbnail.rel='noreferrer'}
  const placeholder=el('span',undefined,'thumbnail-placeholder');placeholder.innerHTML=playSvg;placeholder.append(el('span','Vorschau wird geladen'));thumbnail.append(placeholder);
  const img=el('img');img.alt='Twitch-Vorschaubild: '+title;img.loading='lazy';img.decoding='async';img.width=480;img.height=272;
  const remote=job.clip.thumbnail_url;
  if(typeof remote==='string'&&(remote.startsWith('https://')||(s.development&&remote==='/dev-thumbnail.svg'))){
    img.src=remote;img.onload=()=>placeholder.hidden=true;img.onerror=()=>{img.hidden=true;placeholder.lastChild.textContent='Kein Vorschaubild'};thumbnail.append(img);
  }else placeholder.lastChild.textContent='Kein Vorschaubild';
  const held=hasOpenReport(s,job.id)&&['queued','downloading','editing','ready','failed'].includes(job.status);
  thumbnail.append(el('span',held?'Problem gemeldet':labels[job.status]||job.status,'thumbnail-status status-'+(held?'failed':job.status)));
  const play=el('span',undefined,'thumbnail-play');play.innerHTML=playSvg;thumbnail.append(play);
  thumbnail.append(el('span',synthetic?'Synthetische Vorschau':'Twitch-Vorschau','thumbnail-source'));
  const seconds=Math.round(job.clip.duration||0);thumbnail.append(el('span',`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`,'thumbnail-duration'));
  row.append(thumbnail);
  const body=el('div',undefined,'video-card-body');
  const byline=el('div',undefined,'creator-line');const avatar=el('span',(job.clip.broadcaster_name||'?').slice(0,1).toUpperCase(),'creator-avatar');
  byline.append(avatar,el('span',job.clip.broadcaster_name||'Streamer'),el('span',Number(job.clip.view_count||0).toLocaleString('de-DE')+' Twitch-Aufrufe','source-views'));body.append(byline);
  const heading=el('h3',title,'job-title');heading.title=title;body.append(heading);
  if(job.error){const details=el('details',undefined,'job-error');details.append(el('summary','Hinweis zur Verarbeitung'),el('small',job.error));body.append(details)}
  renderLearning(body,job,s.learning||{});
  if(!job.result.file)body.append(el('p',['editing','downloading'].includes(job.status)?'Dein Short wird gerade vorbereitet.':'Bewertung verfügbar, sobald der Schnitt fertig ist.','preparing-note'));
  const actions=el('div',undefined,'buttons card-actions');const report=el('button','Problem melden');report.onclick=()=>openReport(job);actions.append(report);
  if(job.youtube_id&&!synthetic){const a=el('a','YouTube ↗','linkbutton');a.href='https://youtu.be/'+encodeURIComponent(job.youtube_id);a.target='_blank';a.rel='noreferrer';actions.append(a)}
  for(const [states,route,text] of [[['failed'],'retry','Erneut schneiden'],[['queued','failed','ready'],'skip','Überspringen']])if(states.includes(job.status)){const b=el('button',text);b.onclick=()=>post(route,{id:job.id}).catch(e=>show(e.message));actions.append(b)}
  if(job.status==='upload_unknown'){const b=el('button','YouTube-ID übernehmen');b.onclick=()=>{const id=prompt('Falls bereits auf YouTube vorhanden: 11-stellige Video-ID eingeben.');if(id)post('reconcile',{id:job.id,video_id:id.trim()}).catch(e=>show(e.message))};actions.append(b)}
  body.append(actions);renderReports(body,job,s.reports||[]);row.append(body);return row;
}
