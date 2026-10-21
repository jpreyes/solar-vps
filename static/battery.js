/* Battery view: strategy cards, custom thresholds with live estimate, automation rules. */
(function(){
  const $=id=>document.getElementById(id);
  const clp=v=>v===null||v===undefined?'—':'$'+Math.round(v).toLocaleString('es-CL');
  const PRESETS=[
    {key:'balanced',title:'Equilibrada',pill:'Recomendada',low:20,high:30,winter:true,match:r=>r.name.includes('40/50 jun–jul')},
    {key:'cheap',title:'Más barata',low:20,high:30,winter:false,match:r=>r.name==='20/30'||r.name==='20/30 (actual)'},
    {key:'reserve',title:'Más reserva',low:40,high:50,winter:false,match:r=>r.name==='40/50'}];
  let timer=null,lastQuery='',selected=null,loaded=false;
  function setSel(text){$('bSel').textContent='Seleccionado: '+text}
  function values(){return {low:+$('bLow').value,high:+$('bHigh').value,winter:$('ruleWinter').checked,storm:$('ruleStorm').checked}}
  function check(v){
    if(v.high<v.low+5)return 'La vuelta a batería debe ser al menos 5 puntos mayor que la vuelta a red.';
    if(v.low<15)return 'Bajo 15 % no se permite: protege la batería.';
    return '';
  }
  function showValues(){const v=values();$('bLowV').textContent=v.low+' %';$('bHighV').textContent=v.high+' %';const w=check(v);$('bWarn').textContent=w;$('saveRules').disabled=!!w;return v}
  async function estimate(){
    const v=showValues();if(check(v))return;
    const q=new URLSearchParams({low:v.low,high:v.high});if(v.winter&&v.low<40){q.set('winter_low',40);q.set('winter_high',Math.max(50,v.high))}
    if(q.toString()===lastQuery)return;lastQuery=q.toString();
    ['eGrid','eCost','eRes','eFull'].forEach(id=>$(id).textContent='…');
    try{const r=await solarRequest('/api/strategy/estimate?'+q);if(lastQuery!==q.toString())return;
      $('eGrid').textContent=fmt(r.grid_kwh_year,0)+' kWh';$('eCost').textContent=clp(r.cost_clp_year);
      $('eRes').textContent=fmt(r.reserve_kwh)+' kWh'+(r.winter?' · invierno '+fmt(r.winter_reserve_kwh)+' kWh':'');
      $('eFull').textContent=r.winter_full_days===null?'—':fmt(r.winter_full_days*100,0)+' %'}
    catch(error){['eGrid','eCost','eRes','eFull'].forEach(id=>$(id).textContent='—');$('bWarn').textContent=error.message}
  }
  function queue(){showValues();clearTimeout(timer);timer=setTimeout(()=>run(estimate),350)}
  function pick(p){selected=p.key;document.querySelectorAll('.opt').forEach(o=>o.classList.toggle('sel',o.dataset.key===p.key));
    $('bLow').value=p.low;$('bHigh').value=p.high;$('ruleWinter').checked=p.winter;setSel(p.title);queue()}
  function cards(study){
    const box=$('strategyCards');box.replaceChildren();
    for(const p of PRESETS){
      const r=study&&study.ready?study.results.find(p.match):null;
      const b=el('button',{class:'opt',type:'button','data-key':p.key},
        p.pill?el('span',{class:'pill'},p.pill):null,el('b',{},p.title),
        el('span',{class:'sub'},p.low+'/'+p.high+(p.winter?' · 40/50 jun–jul':' todo el año')),
        el('div',{class:'num'},r?clp(r.cost_clp_year)+'/año':'—'),
        el('span',{class:'sub'},r?fmt(r.grid_kwh_year,0)+' kWh de red · '+fmt(r.winter_full_days*100,0)+' % días llenos en invierno':'calculando…'));
      b.addEventListener('click',()=>pick(p));box.append(b);
    }
  }
  function nextChange(cfg,enabled){
    if(!enabled)return 'Ninguno mientras la automatización esté en pausa';
    const m=new Date().getMonth()+1,months=cfg.winter_months||[];
    const [wl,wh]=cfg.winter,[bl,bh]=cfg.base;
    if(!months.length)return 'Sin cambios por temporada'+(cfg.storm?' · 40/50 si hay ráfagas fuertes':'');
    const names=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    if(months.includes(m)){let n=m;while(months.includes(n))n=n%12+1;return '1 '+names[n-1]+' → '+bl+'/'+bh}
    let n=m%12+1;while(!months.includes(n))n=n%12+1;return '1 '+names[n-1]+' → '+wl+'/'+wh;
  }
  async function load(){
    const [ctl,str]=await Promise.all([solarRequest('/api/control'),solarRequest('/api/strategy').catch(()=>null)]);
    const st=ctl.state||{},p=st.last_params||{},cfg=ctl.config;
    $('bNow').textContent=(p.to_grid??'—')+' / '+(p.to_battery??'—');
    $('bCharger').textContent=ctl.charger_labels[p.charger]||'cargador —';
    $('bAuto').textContent=ctl.mode!=='on'?'Control '+({off:'apagado','dry-run':'en simulación'}[ctl.mode]||ctl.mode):st.enabled?'Automatización activa':'Automatización en pausa';
    const active=ctl.mode==='on'&&st.enabled;
    $('bNext').textContent=nextChange(cfg,active);
    const note=$('bPaused');
    if(active){note.hidden=true}
    else{note.hidden=false;note.textContent=(ctl.mode!=='on'?'El control del VPS no está en modo activo (CONTROL_MODE='+ctl.mode+'). ':'')+
      (st.paused_reason?'Pausada: '+st.paused_reason+' ':'')+
      'Mientras esté en pausa no cambia nada sola (por ejemplo, no pasará a 40/50 en junio). Revisa la estrategia y aprieta “Guardar y activar automatización”.'}
    $('gustLimit').textContent=fmt(cfg.storm_gust_kmh,0);
    const side=$('sideLink');if(side)side.textContent=p.cloud_online===true?'online':p.cloud_online===false?'offline':'—';
    if(!loaded){
      $('bLow').value=cfg.base[0];$('bHigh').value=cfg.base[1];$('ruleWinter').checked=(cfg.winter_months||[]).length>0;$('ruleStorm').checked=!!cfg.storm;
      const match=PRESETS.find(x=>x.low===cfg.base[0]&&x.high===cfg.base[1]&&x.winter===$('ruleWinter').checked);
      setSel(match?match.title+' (vigente)':'personalizado (vigente)');selected=match&&match.key;
      cards(str&&str.study);document.querySelectorAll('.opt').forEach(o=>o.classList.toggle('sel',o.dataset.key===selected));
      loaded=true;queue();
    }
  }
  ['bLow','bHigh','ruleWinter','ruleStorm'].forEach(id=>$(id).addEventListener('input',()=>{selected=null;document.querySelectorAll('.opt').forEach(o=>o.classList.remove('sel'));setSel('personalizado');$('bDone').textContent='';queue()}));
  $('saveRules').addEventListener('click',()=>run(async()=>{
    const v=values(),w=check(v);if(w){$('bWarn').textContent=w;return}
    const text=v.low+'/'+v.high+(v.winter?', 40/50 en junio–julio':'')+(v.storm?', reserva por viento':'');
    if(!confirm('¿Guardar '+text+' y activar la automatización? Desde ahora el VPS ajustará el inversor solo: hoy al umbral que corresponda y cada temporada (por ejemplo, 40/50 el 1 de junio y de vuelta el 1 de agosto).'))return;
    $('bDone').textContent='Guardando…';
    try{await solarRequest('/api/control/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base:[v.low,v.high],winter:v.winter,storm:v.storm,enabled:true})});
      $('bDone').textContent='Guardado y automatización activa. El VPS ajustará el inversor en los próximos minutos y lo verificará.'}
    catch(error){$('bDone').textContent=error.message}
    loaded=false;await load();if(typeof updateControl==='function')updateControl().catch(()=>{});
  }));
  window.updateBattery=load;
  run(load);setInterval(()=>{if(!document.hidden)run(load)},120000);
})();
