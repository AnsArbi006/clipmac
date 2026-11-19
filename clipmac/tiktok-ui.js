(() => {
  const phases={idle:'Gestoppt',waiting:'Stundenpause / wartet',starting:'Startet …',preparing:'Clips prüfen',uploading:'Uploads laufen',checking:'Status prüfen',connecting:'Anmeldung offen',stopping:'Wird gestoppt …',paused:'Gestoppt',complete:'Abgeschlossen',error:'Aktion erforderlich',interrupted:'Unterbrochen',external:'Separater Lauf aktiv'};
  const statuses={verified:'Öffentlich bestätigt',pending_review:'TikTok prüft noch',cancelled_before_post:'Vor dem Post gestoppt',posting:'In Bearbeitung',confirmation_received:'Upload bestätigt · prüfen',upload_unknown:'Ergebnis unklar',visibility_review:'Sichtbarkeit prüfen'};
  let requestRunning=false,actionRunning=false,actionMessage='';
  const error=text=>{const e=$('tiktok-error');e.textContent=text;e.classList.toggle('show',Boolean(text));};
  function render(s){
    $('tiktok-account').textContent=s.account?'@'+s.account:'Noch nicht verbunden';
    $('tiktok-phase').textContent=phases[s.phase]||s.phase;
    $('tiktok-phase').dataset.phase=s.phase;
    $('tiktok-start').textContent=s.automatic?'Automatik aktiv':'TikTok-Automatik starten';
    $('tiktok-start').disabled=actionRunning||!s.can_start;
    $('tiktok-stop').disabled=actionRunning||(!s.running&&!s.automatic)||s.phase==='stopping';
    $('tiktok-check').disabled=actionRunning||s.running||!s.account;
    $('tiktok-connect').disabled=actionRunning||s.running||!s.account;
    $('tiktok-progress').max=Math.max(1,s.total);$('tiktok-progress').value=s.completed;
    $('tiktok-progress-label').textContent=s.total?(s.running&&s.action==='upload'?'Aktueller Auftrag':'Letzter Auftrag'):'Noch kein Uploadauftrag';
    $('tiktok-progress-number').textContent=s.total?s.completed+' / '+s.total+' übernommen':'';
    $('tiktok-current').textContent=s.phase==='stopping'?'Kein weiterer Post. Ein bereits abgeschicktes Video wird noch zugeordnet.':s.current_title||'';
    let message=s.message||'Bereit für deinen nächsten Uploadlauf.';if(s.phase==='waiting')message='Automatik aktiv: übernimmt veröffentlichte YouTube-Pakete mit höchstens fünf Videos.'+(s.next_at*1000>Date.now()?' Nächster Lauf frühestens '+new Date(s.next_at*1000).toLocaleString('de-DE')+'.':' Wartet auf das nächste passende Paket.');
    if(s.phase==='interrupted')message='Der frühere Lauf wurde beendet. Noch offene Ergebnisse zuerst prüfen.';
    if(s.unavailable)message+=' '+s.unavailable+' Dateien sind nicht lokal verfügbar. Bitte in Finder laden.';
    if(s.needs_review&&!s.running)message+=' '+s.needs_review+' Ergebnis(se) unklar. „Status prüfen“ startet keinen Upload.';
    $('tiktok-message').textContent=message;
    for(const [id,value] of [['ready',s.ready],['public',s.public],['review',s.pending_review],['unclear',s.needs_review]])$('tiktok-'+id).textContent=value;
    const list=$('tiktok-recent');const key=JSON.stringify(s.recent);
    if(list.dataset.key!==key){list.dataset.key=key;list.replaceChildren();
      for(const item of s.recent){const row=el('div',undefined,'tiktok-history-row');row.append(el('span',item.title),el('small',statuses[item.status]||item.status));if(item.url){const link=el('a','Auf TikTok ↗');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';row.append(link)}list.append(row)}
      if(!s.recent.length)list.append(el('small','Noch keine TikTok-Uploads erfasst.'));
    }
  }
  async function refreshTikTok(){
    if(requestRunning)return;requestRunning=true;
    try{const r=await fetch('/api/tiktok/state',{signal:AbortSignal.timeout(8000)});const s=await r.json();if(!r.ok)throw Error(s.error||'TikTok-Status nicht erreichbar.');render(s);if(!actionRunning)error(actionMessage);}
    catch(e){$('tiktok-start').disabled=true;$('tiktok-phase').textContent='Verbindung unterbrochen';error('MacClip ist nicht erreichbar oder der Status konnte nicht gelesen werden. Es wurde kein neuer Start ausgelöst.');}
    finally{requestRunning=false;}
  }
  for(const [id,route] of [['start','start'],['stop','stop'],['check','check'],['connect','connect']]){
    $('tiktok-'+id).onclick=async()=>{actionRunning=true;for(const b of document.querySelectorAll('.tiktok-controls button'))b.disabled=true;
      try{const r=await fetch('/api/tiktok/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-ClipMac-Token':token},body:'{}'});const result=await r.json();if(!r.ok)throw Error(result.error||'TikTok-Aktion fehlgeschlagen.');actionMessage='';error('');}
      catch(e){actionMessage=e.message;error(actionMessage);}
      finally{actionRunning=false;await refreshTikTok();}
    };
  }
  async function poll(){await refreshTikTok();setTimeout(poll,document.hidden?10000:3000)}
  poll();
})();
