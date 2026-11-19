const ratingNames={good:'Gut',medium:'Mittel',bad:'Schlecht'};
const ratingAnimations=new Map();
const performanceDetails=new Set();
const performancePanels=new Set();
function reviewIcon(kind){
  const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.7');svg.setAttribute('stroke-linecap','round');svg.setAttribute('aria-hidden','true');
  const path=d=>{const p=document.createElementNS(ns,'path');p.setAttribute('d',d);svg.append(p)};
  if(kind==='performance'){path('M4 4v16h16M8 15l4-5 4 2 4-7');return svg}
  const circle=document.createElementNS(ns,'circle');circle.setAttribute('cx','12');circle.setAttribute('cy','12');circle.setAttribute('r','9');svg.append(circle);
  path('M8 9h.01M16 9h.01');path(kind==='good'?'M8 14q4 5 8 0':kind==='bad'?'M8 17q4-5 8 0':'M8 15h8');return svg;
}
function fmtNumber(value){return value===null||value===undefined?'—':Number(value).toLocaleString('de-DE')}
function fmtAge(seconds){const m=Math.max(0,Math.round(seconds/60));return m<60?`${m} Min.`:`${Math.floor(m/60)} Std. ${m%60} Min.`}
async function rateVideo(job,value,card){
  const buttons=card.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
  const status=card.querySelector('.rating-status');status.textContent='Wird gespeichert …';status.classList.remove('rating-error');
  try{
    const response=await fetch('/api/rating',{method:'POST',headers:{'Content-Type':'application/json','X-ClipMac-Token':token},body:JSON.stringify({id:job.id,value})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Bewertung konnte nicht gespeichert werden.');
    ratingAnimations.set(job.id,Date.now());previousJobsKey='';await refresh();
    document.querySelector(`[data-rating-clip="${job.id}"] [data-value="${value||'good'}"]`)?.focus({preventScroll:true});
  }catch(error){status.textContent=error.message;status.classList.add('rating-error');buttons.forEach(b=>b.disabled=false)}
}
function renderLearning(row,job,learning){
  if(!job.result.file)return;
  const card=el('section',undefined,'review-card');card.dataset.ratingClip=job.id;card.setAttribute('aria-label','Schnitt bewerten');
  const heading=el('div',undefined,'review-heading');heading.append(el('b','Wie ist der Schnitt?'),el('span','Deine persönliche Einschätzung'));card.append(heading);
  const rating=(learning.ratings||[]).find(r=>r.clip_id===job.id);
  const chosen=rating?.current_revision?rating.value:null;
  const group=el('div',undefined,'rating-group');group.setAttribute('role','group');group.setAttribute('aria-label','Deine Schnittbewertung');
  for(const value of ['good','medium','bad']){
    const button=el('button',undefined,'rating-button');button.type='button';button.dataset.value=value;
    button.setAttribute('aria-pressed',String(chosen===value));button.setAttribute('aria-label',ratingNames[value]);
    button.append(reviewIcon(value),el('span',ratingNames[value]));
    if(chosen===value&&Date.now()-(ratingAnimations.get(job.id)||0)<1500)button.classList.add('rating-pop');
    button.onclick=()=>rateVideo(job,value,card);group.append(button);
  }
  card.append(group);
  const footer=el('div',undefined,'rating-footer');const status=el('small',chosen?`${ratingNames[chosen]} · gespeichert`:rating?.value&&!rating.current_revision?'Neue Schnittfassung · bitte neu bewerten':'Ein Klick genügt. Du kannst deine Meinung ändern.','rating-status'+(chosen?' rating-saved':''));status.setAttribute('role','status');footer.append(status);
  if(chosen){const reset=el('button','Zurücksetzen','rating-reset');reset.type='button';reset.onclick=()=>rateVideo(job,null,card);footer.append(reset)}card.append(footer);
  if(chosen==='bad')card.append(el('small','Etwas Konkretes kaputt? Nutze „Problem melden“. Deine Bewertung allein stoppt keinen Upload.'));
  if(job.status==='published'){
    const data=learning.performance?.[job.id]||{};const samples=data.samples||[];const last=samples[samples.length-1];
    const details=el('details',undefined,'card-performance');details.open=performancePanels.has(job.id);
    details.ontoggle=()=>{if(details.open)performancePanels.add(job.id);else performancePanels.delete(job.id)};
    details.append(el('summary',last?.availability==='public'?`YouTube · ${fmtNumber(last.views)} Aufrufe · ${fmtNumber(last.likes)} Likes`:'YouTube-Messwerte'));
    renderPerformance(details,job,data);card.append(details);
  }
  else card.append(el('p','YouTube-Verlauf erscheint nach der Veröffentlichung.','performance-empty'));
  row.append(card);
}
function renderPerformance(card,job,data){
  const area=el('div',undefined,'performance-card');const heading=el('div',undefined,'performance-heading');heading.append(reviewIcon('performance'),el('b','Reaktion auf YouTube'));area.append(heading);
  const samples=data.samples||[];const latest=samples[samples.length-1];
  if(latest?.availability==='public'){
    const metrics=el('div',undefined,'performance-metrics');
    for(const [key,label,cls] of [['views','Aufrufe',''],['likes','Likes','minor'],['comments','Kommentare','minor']]){const cell=el('div',undefined,cls);cell.append(el('b',fmtNumber(latest[key])),el('span',label));metrics.append(cell)}area.append(metrics);
    area.append(el('small',`Gemessen ${fmtAge(latest.age_seconds)} nach Veröffentlichung · ${new Date(latest.observed_at*1000).toLocaleString('de-DE')}`));
  }else area.append(el('small',latest?'Video oder Statistik momentan nicht verfügbar.':'Die erste Messung wird geladen …'));
  const grid=el('div',undefined,'checkpoint-grid');
  for(const hour of [1,2,24]){
    const checkpoint=(data.checkpoints||[]).find(c=>c.hour===hour);const sample=samples.find(s=>s.id===checkpoint?.sample_id);
    const cell=el('div',undefined,'checkpoint'+(checkpoint?.state==='missed'?' missed':''));cell.append(el('b',`Nach ${hour} Std.`));
    if(sample){cell.append(el('span',`${fmtNumber(sample.views)} Aufrufe`),el('small',`Erfasst bei ${fmtAge(sample.age_seconds)}`))}
    else if(checkpoint?.state==='missed')cell.append(el('span','Nicht erfasst'),el('small','Zeitfenster verpasst'));
    else cell.append(el('span','Ausstehend'),el('small','Wird automatisch geprüft'));
    grid.append(cell);
  }area.append(grid);
  const comparison=data.comparison||{};area.append(el('small',comparison.text||'Vergleich folgt mit passenden Stundenwerten.','performance-comparison'));
  if(comparison.hour)area.append(el('small',`Vergleich mit ${comparison.peers} anderen Kanalvideos nach ${comparison.hour} Std.; Median: ${fmtNumber(comparison.median_views)} Aufrufe.`));
  if(data.sync?.error)area.append(el('small',data.sync.error));
  const details=el('details',undefined,'performance-history');details.open=performanceDetails.has(job.id);details.ontoggle=()=>{if(details.open)performanceDetails.add(job.id);else performanceDetails.delete(job.id)};
  details.append(el('summary','Messwerte & Einordnung'));details.append(el('p','Aufrufe, Likes und Kommentare sind ein zweites Signal. Thema, Zeitpunkt und Ausspielung beeinflussen sie ebenfalls. Wenige Aufrufe beweisen keinen schlechten Schnitt. Die Zahlen sind vorläufig; Wiedergabedauer und Zuschauerbindung sind hier noch nicht angebunden.','performance-empty'));
  if(samples.length){const table=el('table');const head=el('tr');for(const text of ['Videoalter','Aufrufe','Likes','Kommentare']){const th=el('th',text);th.scope='col';head.append(th)}table.append(head);for(const s of samples){const tr=el('tr');for(const value of [fmtAge(s.age_seconds),fmtNumber(s.views),fmtNumber(s.likes),fmtNumber(s.comments)])tr.append(el('td',value));table.append(tr)}details.append(table)}
  area.append(details);card.append(area);
}
