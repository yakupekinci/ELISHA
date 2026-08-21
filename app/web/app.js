const chat = document.getElementById('chat');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const micBtn = document.getElementById('mic');
const wakeBtn = document.getElementById('wake');
const hint = document.getElementById('hint');
const orb = document.getElementById('orb');
const orbLabel = document.getElementById('orbLabel');
const orbHint = document.getElementById('orbHint');
const wave = document.getElementById('wave');
const cnt = document.getElementById('cnt');
const statusText = document.getElementById('statusText');
const badge = document.getElementById('badge');
const ttsToggle = document.getElementById('ttsToggle');

let wakeOn = true;
let listening = false;
let mediaRecorder = null;
let audioChunks = [];

function addBubble(text, who){
  const b = document.createElement('div');
  b.className = 'bubble ' + who;
  const span = document.createElement('span');
  span.textContent = text;
  b.appendChild(span);
  const m = document.createElement('div');
  m.className = 'meta';
  m.textContent = new Date().toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'});
  b.appendChild(m);
  chat.appendChild(b);
  chat.scrollTop = chat.scrollHeight;
  updateCnt();
  return span;
}
function addSys(t){
  const b=document.createElement('div'); b.className='bubble sys'; b.textContent=t; chat.appendChild(b); chat.scrollTop=chat.scrollHeight; updateCnt();
}
let agentStatusEl = null;
function setAgentStatus(t){
  statusText.textContent = t;
  hint.textContent = t;
}
function updateCnt(){
  const n = chat.querySelectorAll('.bubble').length;
  cnt.textContent = n + ' mesaj';
}
function setOrb(state){
  orb.className='orb ' + (state||'');
  const bars = ()=>{ wave.innerHTML=''; for(let i=0;i<22;i++){const s=document.createElement('span'); s.style.animationDelay=(i*28)+'ms'; wave.appendChild(s);} };
  if(state==='listening'){ orbLabel.textContent='dinliyorum...'; orbHint.textContent='konuş, sessizlikte duracak'; wave.className='wave listening'; bars(); }
  else if(state==='speaking'){ orbLabel.textContent='konuşuyorum...'; orbHint.textContent='ELİŞA cevap veriyor'; wave.className='wave speaking'; bars(); }
  else if(state==='thinking'){ orbLabel.textContent='düşünüyor...'; orbHint.textContent='ELİŞA kafasını kurcalıyor'; wave.className='wave speaking'; bars(); }
  else { orbLabel.textContent=wakeOn?'uyuyor':'hazır'; orbHint.textContent="'hey elişa uyan' de"; wave.className='wave idle'; bars(); }
}
setOrb();

async function fetchStatus(){
  try{
    const r=await fetch('/api/status'); const j=await r.json();
    statusText.textContent = `STT:${j.stt} TTS:${j.tts} LLM:${j.llm}`;
    badge.textContent = `${j.stt} • ${j.tts} • ${j.llm}`;
    document.querySelector('.dot').style.background='#22c55e';
  }catch{ statusText.textContent='server yok — python3 app/server.py çalıştır'; }
}
fetchStatus(); setInterval(fetchStatus, 10000);

async function sendText(text){
  if(!text.trim()) return;
  addBubble(text, 'user');
  input.value='';
  hint.textContent='ELİŞA düşünüyor...';
  setOrb('thinking');
  const span = addBubble('', 'bot');
  let full = '';
  try{
    const r = await fetch('/api/chat_stream', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
    if(!r.ok || !r.body) throw new Error('server '+r.status);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let sbuf = '';
    while(true){
      const {done, value} = await reader.read();
      if(done) break;
      sbuf += dec.decode(value, {stream:true});
      let idx;
      while((idx = sbuf.indexOf('\n\n')) >= 0){
        const raw = sbuf.slice(0, idx).trim(); sbuf = sbuf.slice(idx+2);
        if(!raw.startsWith('data: ')) continue;
        let ev; try{ ev = JSON.parse(raw.slice(6)); }catch{ continue; }
        if(ev.type==='status'){
          setAgentStatus(ev.text);
          span.className = 'agent-status';
          span.textContent = ev.text;
        } else if(ev.type==='token'){
          full += ev.text;
          span.className = '';
          span.parentElement.classList.add('bot');
          span.textContent = full;
          chat.scrollTop = chat.scrollHeight;
        } else if(ev.type==='done'){
          full = ev.reply || full;
          span.textContent = full;
        } else if(ev.type==='error'){
          full = full || ('Hata: ' + ev.error);
          span.textContent = full;
        }
      }
    }
    if(!full){ span.textContent = 'Bir şey diyemedim'; }
    setAgentStatus('Hazır');
    hint.textContent='Hazır';
    setOrb(wakeOn?'':'');
    if(ttsToggle.checked && full && !full.startsWith('Hata:')) speak(full);
  }catch(e){
    // SSE yoksa eski yola düş
    try{
      const r2 = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
      const j = await r2.json();
      span.textContent = j.reply || 'Bir şey diyemedim';
      setAgentStatus('Hazır'); hint.textContent='Hazır'; setOrb(wakeOn?'':'');
      if(ttsToggle.checked) speak(j.reply || '');
    }catch(e2){
      addSys('Bağlantı hatası: '+e.message+' — server ayakta mı?');
      hint.textContent='Hata'; setOrb('');
    }
  }
}

function speak(text){
  const clean = (text||'').replace(/\[ACTION:[^\]]+\]/g,'').trim().slice(0,400);
  if(!clean) return;
  fetch('/api/tts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: clean})})
    .then(r=>{ if(!r.ok) throw 0; return r.json(); })
    .then(j=>{
      if(!j.audio) return fallbackSpeak(clean);
      const bytes = Uint8Array.from(atob(j.audio), c=>c.charCodeAt(0));
      const a = new Audio(URL.createObjectURL(new Blob([bytes], {type:'audio/wav'})));
      setOrb('speaking');
      a.onended = ()=> setOrb(wakeOn?'':'');
      a.play().catch(()=> fallbackSpeak(clean));
    }).catch(()=> fallbackSpeak(clean));
}
function fallbackSpeak(t){
  if('speechSynthesis' in window){
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(t);
    u.lang='tr-TR'; u.rate=1; u.pitch=1.05;
    setOrb('speaking');
    u.onend=()=> setOrb(wakeOn?'':'');
    speechSynthesis.speak(u);
  }
}

sendBtn.onclick = ()=> sendText(input.value);
input.addEventListener('keydown', e=>{ if(e.key==='Enter') sendText(input.value); });

// ---- MIC: %100 OFFLINE (MediaRecorder -> /api/stt -> local whisper) ----
micBtn.onclick = async ()=>{
  if(listening){ // ikinci tık = iptal
    try{ mediaRecorder && mediaRecorder.state!=='inactive' && mediaRecorder.stop(); }catch{}
    return;
  }
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    listening = true;
    micBtn.textContent='⏹ Dinliyorum...'; micBtn.style.background='linear-gradient(135deg,#ff2e97,#a855f7)';
    hint.textContent='Dinliyorum... konuş ve dur'; setOrb('listening');

    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = e=>{ if(e.data.size>0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async ()=>{
      stream.getTracks().forEach(t=>t.stop());
      micBtn.textContent='🎙️ Dinle'; micBtn.style.background='';
      const blob = new Blob(audioChunks, {type: mediaRecorder.mimeType || 'audio/webm'});
      if(blob.size < 2000){ listening=false; hint.textContent='Ses çok kısa'; setOrb(wakeOn?'':''); return; }
      hint.textContent='Anlıyorum... (local whisper)';
      setOrb('thinking');
      try{
        const r = await fetch('/api/stt', {method:'POST', headers:{'Content-Type': blob.type}, body: blob});
        const j = await r.json();
        const txt = (j.text||'').trim();
        listening=false;
        if(txt){
          addBubble('(ses) '+txt, 'user');
          sendText(txt);
        }else{
          hint.textContent='Ses anlaşılmadı, tekrar dene'; setOrb(wakeOn?'':'');
        }
      }catch(e){
        listening=false; hint.textContent='STT hatası: '+e.message; setOrb(wakeOn?'':'');
      }
    };
    // max 8sn otomatik kes
    mediaRecorder.start();
    setTimeout(()=>{ if(mediaRecorder && mediaRecorder.state==='recording') mediaRecorder.stop(); }, 8000);
  }catch(e){
    listening=false;
    addSys('Mikrofon izni gerek: '+e.message);
    hint.textContent='Mikrofon izni ver';
  }
};

// ---- WAKE: sadece daemon (local whisper). Browser wake kaldırıldı (offline çalışmıyor) ----
wakeBtn.onclick = ()=>{
  wakeOn = !wakeOn;
  if(wakeOn){
    wakeBtn.classList.add('active'); wakeBtn.textContent='✨ Hey ELİŞA açık';
    hint.textContent="Uyuyor — 'hey elişa uyan' de"; setOrb('');
    addSys("✨ Hey ELİŞA açık — sadece 'hey elişa uyan' deyince uyanırım");
    try{ fetch('/api/wake_enable', {method:'POST'}); }catch{}
  }else{
    wakeBtn.classList.remove('active'); wakeBtn.textContent='✨ Hey ELİŞA uyuyor';
    hint.textContent='Uyku modu'; setOrb('');
    addSys("Hey ELİŞA uyuyor");
    try{ fetch('/api/wake_disable', {method:'POST'}); }catch{}
  }
};

// daemon poll — local whisper tetiklemesi
setInterval(async ()=>{
  if(!wakeOn) return;
  try{
    const r = await fetch('/api/wake_check');
    const j = await r.json();
    if(j.wake){
      addSys("✨ Hey ELİŞA duydum: '"+(j.text||'')+"'");
      hint.textContent='Uyandı! Konuş (10sn)';
      setOrb('listening');
      speak('Buyurun, sizi dinliyorum');
      setTimeout(()=>{ if(wakeOn && !listening) micBtn.click(); }, 1200);
      setTimeout(()=>{ if(wakeOn){ hint.textContent="Uyuyor — 'hey elişa uyan' de"; setOrb(''); } }, 12000);
    }
  }catch{}
}, 900);

// ilk mesaj
setTimeout(()=>{
  addSys("Merhaba, ben ELİŞA ✨ — gizli moddayım. 'hey elişa uyan' de ya da menü çubuğundaki ✦'dan Uyan'a bas.");
  wakeBtn.classList.add('active'); wakeBtn.textContent='✨ Hey ELİŞA açık';
}, 400);

// ---- SİRİ MODU: dış tetik (python wake daemon → show_overlay) ----
window.ELISHA_EXTERNAL_WAKE = function(reason){
  try{ wakeOn = true; }catch{}
  addSys("✨ Uyandım! ("+(reason||'hey elişa uyan')+") — konuş, 10 sn");
  hint.textContent='Uyandı! Konuş (10sn)';
  setOrb('listening');
  speak('Buyurun, sizi dinliyorum');
  setTimeout(()=>{ if(!listening) micBtn.click(); }, 1300);
  setTimeout(()=>{ if(wakeOn){ hint.textContent="Uyuyor"; setOrb(''); if(window.pywebview){ pywebview.api.hide_app(); } } }, 14000);
};

// panelde gizle butonu (frameless pencere için)
const hideBtn = document.createElement('button');
hideBtn.textContent = '–';
hideBtn.style.cssText = 'position:fixed;top:10px;right:12px;z-index:99;width:28px;height:28px;border-radius:50%;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);color:#fff;cursor:pointer;font-size:14px';
hideBtn.onclick = ()=>{ if(window.pywebview) pywebview.api.hide_app(); };
document.body.appendChild(hideBtn);
// sürükleme alanı (frameless başlık yerine): header'a basılı tutup taşı
document.addEventListener('mousedown', e=>{
  if(e.target.closest('header') && window.pywebview && window.pywebview.api){
    // pywebview easy_drag kapalı; basit taşıma yok — sağ tık gerekmez
  }
});
// her etkileşimde otomatik gizleme sayacını uzat
['click','keydown'].forEach(ev=> document.addEventListener(ev, ()=>{
  if(window.pywebview) { try{ pywebview.api.keep_alive(); }catch{} }
}));
