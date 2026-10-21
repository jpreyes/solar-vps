const $=id=>document.getElementById(id);
const WEATHER_METRICS=[['global_tilted_irradiance','Irradiancia en paneles (GTI) · W/m²'],['shortwave_radiation','Radiación GHI estimada · W/m²'],['direct_radiation','Radiación directa estimada · W/m²'],['diffuse_radiation','Radiación difusa estimada · W/m²'],['temperature_2m','Temperatura Valdivia · °C'],['cloud_cover','Nubosidad Valdivia · %'],['precipitation','Precipitación total Valdivia · mm/hora'],['showers','Chubascos Valdivia · mm/hora'],['rain','Lluvia Valdivia · mm/hora'],['wind_speed_10m','Viento Valdivia · km/h'],['wind_direction_10m','Dirección del viento · °'],['relative_humidity_2m','Humedad relativa · %'],['surface_pressure','Presión atmosférica · hPa'],['direct_normal_irradiance','Irradiancia normal directa · W/m²']];
for(const [key,label] of WEATHER_METRICS){const option=document.createElement('option');option.value='weather:'+key;option.textContent=label;$('metric').append(option)}
let series={main:null,compare:null},activeRange='today',previousRange=null,drag=null,loadNumber=0,refreshing=false;
const COLORS={main:'#237c7b',band:'rgba(35,124,123,.16)',compare:'#c08a2e',grid:'#e5ece6',axis:'#6b8078'};
function themeColors(){const css=getComputedStyle(document.documentElement),v=n=>css.getPropertyValue(n).trim();if(v('--line')){COLORS.grid=v('--line');COLORS.axis=v('--muted');COLORS.main=v('--accent')}}
const localInput=d=>new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
function number(v){return v===null||v===undefined||v===''||typeof v==='boolean'?null:Number.isFinite(Number(v))?Number(v):null}
function display(v){const n=number(v);return n===null?'—':n.toLocaleString('es-CL',{maximumFractionDigits:1})}
function card(label,value,unit,sub,tone){
  const el=document.createElement('article');el.className='card'+(tone?' '+tone:'');
  const l=document.createElement('div');l.className='label';l.textContent=label;
  const v=document.createElement('div');v.className='value';v.textContent=display(value)+' ';
  const u=document.createElement('small');u.textContent=unit;v.append(u);
  const s=document.createElement('div');s.className='sub';s.textContent=sub;el.append(l,v,s);return el;
}
function showError(error){$('error').textContent=error.message;$('error').hidden=false}
async function run(fn){try{await fn();$('error').hidden=true}catch(error){showError(error)}}
function dates(){
  const start=+new Date($('start').value),end=+new Date($('end').value);
  if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end)throw new Error('Selecciona un rango de fechas válido.');
  return [start,end];
}
function setDates(start,end,name=null){
  start=Math.floor(start/60000)*60000;end=Math.max(start+60000,Math.floor(end/60000)*60000);
  $('start').value=localInput(new Date(start));$('end').value=localInput(new Date(end));activeRange=name;
  document.querySelectorAll('[data-range]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.range===name)));
}
function query(){const [start,end]=dates();return new URLSearchParams({start:new Date(start).toISOString(),end:new Date(end).toISOString()})}
function stringText(name,w,v){return name+' '+display(w)+' W'+(v!==null&&v!==undefined?' · '+display(v)+' V':'')}
async function status(){
  const s=await solarRequest('/api/status'),d=s.latest?.response?.data||{},x=s.derived||{};
  const pvDead=[['PV1',x.pv1_v,x.pv2_w],['PV2',x.pv2_v,x.pv1_w]].filter(([,v,other])=>(v??1)<20&&(other||0)>300).map(([n])=>n);
  const flow=(x.battery_charge_w||0)>0?'Cargando '+display(x.battery_charge_w)+' W':(x.battery_discharge_w||0)>0?'Descargando '+display(x.battery_discharge_w)+' W':'En reposo';
  $('cards').replaceChildren(
    card('Producción solar',x.pv_w,'W',stringText('PV1',x.pv1_w,x.pv1_v)+' · '+stringText('PV2',x.pv2_w,x.pv2_v)+(pvDead.length?' · ⚠ '+pvDead.join(', ')+' sin tensión':''),pvDead.length?'warn':''),
    card('Consumo',x.load_w,'W','Potencia activa de salida'),
    card('Estado de batería',x.soc,'%',x.battery_valid===false?'⚠ Lectura de batería no válida':'Tensión '+display(x.battery_v)+' V'),
    card('Flujo de batería',(x.battery_charge_w||0)-(x.battery_discharge_w||0),'W',flow+' · + carga / − descarga'),
    card('Importación de red',x.grid_import_w,'W',x.on_grid===true?'Modo red (L): la casa usa la red':x.on_grid===false?'Modo batería (B): sin consumo de red':'Modo desconocido',x.on_grid?'grid':''));
  const sideSoc=$('sideSoc');if(sideSoc){sideSoc.textContent=display(x.soc)+' %';$('sideMode').textContent=x.on_grid===true?'Red':x.on_grid===false?'Batería':'—'}
  renderStrings(x,s.pv_config||{max_v:500});
  const age=s.latest?Math.max(0,Math.round((Date.now()-new Date(s.latest.observed_at||s.latest.received_at))/60000)):null;
  updateEnergy(d,s.latest?.observed_at);
  $('status').textContent=s.latest?'Última lectura del equipo hace '+age+' min · '+new Date(s.latest.observed_at||s.latest.received_at).toLocaleString('es-CL'):'Pendiente de la primera lectura';
  $('event').textContent=s.event?(s.event.ok?'✓ ':'⚠ ')+s.event.detail+' · '+new Date(s.event.time).toLocaleString('es-CL'):'Sin intentos registrados';
  $('stats').textContent=s.stats.captures+' respuestas originales distintas archivadas'+(s.stats.since?' desde '+new Date(s.stats.since).toLocaleString('es-CL'):'');$('raw').textContent=JSON.stringify(d,null,2);
  const h=s.coverage;$('coverage').textContent=h?.measurements?h.measurements+' registros históricos · '+(h.first_time?new Date(h.first_time).toLocaleString('es-CL'):'fecha pendiente')+' — '+(h.last_time?new Date(h.last_time).toLocaleString('es-CL'):'fecha pendiente'):'Pendiente de la primera descarga histórica.';
  const collection=s.collection;
  if(collection){if(document.activeElement!==$('syncInterval'))$('syncInterval').value=String(collection.interval_seconds);$('syncInfo').textContent='Intervalo activo: '+collection.interval_seconds/60+' min.'+(collection.last_duration!==null?' Última descarga: '+collection.last_duration.toFixed(1)+' s, '+collection.last_pages+' páginas, '+(collection.last_added||0)+' registros nuevos.':' Sin descarga cronometrada todavía.')+(collection.last_error?' Error: '+collection.last_error:'')}
}
function renderStrings(x,cfg){
  const box=$('strings');if(!box)return;$('pvLimit').textContent=cfg.max_v;
  const max=cfg.max_v,pos=v=>Math.max(0,Math.min(100,v/max*100));
  const rows=[['PV1',x.pv1_v,x.pv1_w],['PV2',x.pv2_v,x.pv2_w]],notes=[];
  const sunny=rows.some(r=>(r[2]||0)>300);
  box.replaceChildren(...rows.map(([name,v,w])=>{
    const amps=v>20&&w!==null?w/v:null,dead=sunny&&(v??0)<20,high=(v??0)>=0.9*max;
    if(dead)notes.push(name+' sin tensión con sol');if(high)notes.push(name+' cerca del límite');
    const dot=document.createElement('i');dot.className='dot'+(dead?' off':high?' warn':'');dot.style.left=pos(v||0)+'%';
    const zone=document.createElement('i');zone.className='zone';zone.style.left=pos(cfg.mppt_min_v||90)+'%';zone.style.width=(pos(cfg.mppt_max_v||450)-pos(cfg.mppt_min_v||90))+'%';
    const mark=document.createElement('i');mark.className='mark';mark.style.left='calc('+pos(max)+'% - 2px)';
    const bar=document.createElement('div');bar.className='bar';bar.append(zone,mark,dot);
    const vals=document.createElement('div');vals.className='vals';
    vals.append(Object.assign(document.createElement('b'),{textContent:display(v)+' V'}),Object.assign(document.createElement('span'),{textContent:display(w)+' W · '+(amps===null?'—':amps.toFixed(1))+' A'}));
    const right=document.createElement('div');right.append(vals,bar);
    const label=Object.assign(document.createElement('span'),{className:'name',textContent:name});
    const row=document.createElement('div');row.className='row';row.append(label,right);return row}));
  const both=rows.every(r=>(r[1]||0)>150);
  if(both){const [a,b]=[rows[0][1],rows[1][1]];if(Math.abs(a-b)/Math.max(a,b)>0.15)notes.push('voltajes de los strings difieren más de 15 %')}
  $('stringsNote').textContent=notes.length?'⚠ '+notes.join(' · '):'Normal';
}
async function fetchSeries(metric,q){
  if(!metric)return null;
  if(metric.startsWith('weather:')){
    const key=metric.slice(8),s=await solarRequest('/api/weather/series?'+q);
    return {metric,bucket:3600,points:s.rows.map(r=>{const v=number(r.payload[key]);return [+new Date(r.observed_at),v,v,v]}).filter(p=>p[1]!==null),truncated:s.truncated};
  }
  q=new URLSearchParams(q);q.set('field',metric);
  const s=await solarRequest('/api/field?'+q);
  return {metric,bucket:s.bucket_seconds,points:s.points.map(p=>[+new Date(p[0]),p[1],p[2],p[3]])};
}
function labelOf(select,value){return [...$(select).options].find(o=>o.value===value)?.textContent||value}
async function load(){
  const requestNumber=++loadNumber,q=query(),range=dates();
  $('rangeLabel').textContent=range.map(t=>new Date(t).toLocaleString('es-CL',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})).join(' → ');
  $('apply').disabled=true;$('chartNote').textContent='Consultando el archivo…';
  try{
    const [main,compare]=await Promise.all([fetchSeries($('metric').value,q),fetchSeries($('compare').value,q)]);
    if(requestNumber!==loadNumber)return;
    series={main,compare};$('csv').href='/api/export.csv?'+q;$('jsonl').href='/api/export.jsonl?'+q;
    const bucket=main.bucket?' Promedios cada '+(main.bucket>=3600?main.bucket/3600+' h':main.bucket/60+' min')+' con banda mín–máx.':'';
    $('chartNote').textContent=main.points.length+' puntos en el periodo.'+bucket+(main.truncated?' Se muestran las primeras 5000 horas.':'');draw();
  }catch(error){if(requestNumber===loadNumber)$('chartNote').textContent='No se pudo actualizar el gráfico. Las lecturas anteriores siguen guardadas.';throw error}
  finally{if(requestNumber===loadNumber)$('apply').disabled=false}
}
function scale(points,bottom,top){
  const values=points.flatMap(p=>[p[2],p[3]]).filter(v=>v!==null);
  const min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):1;
  const padding=Math.max((max-min)*0.1,1),lo=min<0?min-padding:Math.max(0,min-padding),hi=Math.max(lo+1,max+padding);
  return {lo,hi,y:v=>bottom-(v-lo)/(hi-lo)*(bottom-top)};
}
function draw(){
  themeColors();
  const canvas=$('chart'),rect=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;
  canvas.width=rect.width*ratio;canvas.height=300*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);
  const compare=series.compare,w=rect.width,left=58,right=w-(compare?58:20),top=20,bottom=248,[first,last]=dates(),span=last-first,x=t=>left+(t-first)/span*(right-left);
  const main=series.main||{points:[],bucket:0};
  const inRange=s=>s.points.filter(p=>p[0]>=first&&p[0]<=last);
  const points=inRange(main),m=scale(points,bottom,top);c.font='11px system-ui';
  for(let i=0;i<5;i++){const value=m.lo+(m.hi-m.lo)*i/4;c.strokeStyle=COLORS.grid;c.beginPath();c.moveTo(left,m.y(value));c.lineTo(right,m.y(value));c.stroke();c.fillStyle=COLORS.axis;c.textAlign='right';c.fillText(display(value),left-8,m.y(value)+4)}
  const count=Math.max(2,Math.min(7,Math.floor((right-left)/115)));
  for(let i=0;i<=count;i++){const t=first+span*i/count;c.strokeStyle=COLORS.grid;c.beginPath();c.moveTo(x(t),top);c.lineTo(x(t),bottom);c.stroke();c.fillStyle=COLORS.axis;c.textAlign=i===0?'left':i===count?'right':'center';c.fillText(solarTime.tickLabel(t,span),x(t),bottom+25)}
  c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
  const gapOf=s=>Math.max(s.metric?.startsWith('weather:')?7200000:900000,(s.bucket||0)*2500);
  function segments(list,gap){const out=[];let current=[];for(const p of list){if(current.length&&p[0]-current[current.length-1][0]>gap){out.push(current);current=[]}current.push(p)}if(current.length)out.push(current);return out}
  if(main.bucket){c.fillStyle=COLORS.band;for(const seg of segments(points,gapOf(main))){c.beginPath();seg.forEach((p,i)=>i?c.lineTo(x(p[0]),m.y(p[3])):c.moveTo(x(p[0]),m.y(p[3])));for(let i=seg.length-1;i>=0;i--)c.lineTo(x(seg[i][0]),m.y(seg[i][2]));c.closePath();c.fill()}}
  function line(list,sc,color,gap){c.strokeStyle=color;c.lineWidth=2;for(const seg of segments(list,gap)){c.beginPath();seg.forEach((p,i)=>i?c.lineTo(x(p[0]),sc.y(p[1])):c.moveTo(x(p[0]),sc.y(p[1])));c.stroke();if(seg.length===1){c.fillStyle=color;c.beginPath();c.arc(x(seg[0][0]),sc.y(seg[0][1]),2.5,0,Math.PI*2);c.fill()}}}
  line(points,m,COLORS.main,gapOf(main));
  let cs=null;
  if(compare){const cp=inRange(compare);cs=scale(cp,bottom,top);line(cp,cs,COLORS.compare,gapOf(compare))}
  if(drag){c.fillStyle='rgba(53,121,90,.16)';c.fillRect(Math.min(drag.start,drag.end),top,Math.abs(drag.end-drag.start),bottom-top)}c.restore();
  if(cs){c.fillStyle=COLORS.compare;c.textAlign='left';for(let i=0;i<5;i++){const value=cs.lo+(cs.hi-cs.lo)*i/4;c.fillText(display(value),right+8,cs.y(value)+4)}}
  if(!points.length){c.fillStyle=COLORS.axis;c.textAlign='left';c.fillText('No hay datos de esta variable en el periodo.',left+8,130)}
  $('chartLegend').replaceChildren(...[[labelOf('metric',$('metric').value),COLORS.main],...(compare?[[labelOf('compare',compare.metric)+' (eje derecho)',COLORS.compare]]:[])].map(([text,color])=>{const s=document.createElement('span');s.className='key';s.style.setProperty('--key',color);s.textContent=text;return s}));
}
async function refresh(){
  if(document.hidden||refreshing)return;refreshing=true;$('refreshNow').disabled=true;$('refreshStatus').textContent='Solicitando una lectura al proveedor…';
  try{const data=await solarRequest('/api/refresh',{method:'POST'});await status();$('refreshStatus').textContent=data.busy?'Hay otra consulta en curso. Se muestran los últimos datos guardados.':data.cached?'Se muestra la lectura reciente guardada.':'Lectura actual guardada correctamente.'}
  catch(error){$('refreshStatus').textContent='La lectura actual no pudo actualizarse; el historial guardado sigue disponible.';throw error}
  finally{refreshing=false;$('refreshNow').disabled=false}
}
function changeRange(start,end,name=null){previousRange=dates();setDates(start,end,name);return load()}
document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>run(()=>changeRange(...solarTime.range(button.dataset.range),button.dataset.range))));
$('apply').addEventListener('click',()=>run(()=>changeRange(...dates())));
for(const id of ['start','end'])$(id).addEventListener('change',()=>{activeRange=null;document.querySelectorAll('[data-range]').forEach(button=>button.setAttribute('aria-pressed','false'))});
$('previous').addEventListener('click',()=>run(()=>changeRange(...solarTime.shift(...dates(),-1))));
$('next').addEventListener('click',()=>run(()=>changeRange(...solarTime.shift(...dates(),1))));
$('zoomIn').addEventListener('click',()=>run(()=>changeRange(...solarTime.zoom(...dates(),0.5))));
$('zoomOut').addEventListener('click',()=>run(()=>changeRange(...solarTime.zoom(...dates(),2))));
$('fitData').addEventListener('click',()=>run(async()=>{const points=series.main?.points||[];if(!points.length)throw new Error('No hay lecturas en este periodo para ajustar el eje.');const times=points.map(p=>p[0]),start=Math.min(...times),end=Math.max(...times),pad=Math.max(60000,(end-start)*.04);await changeRange(start-pad,end+pad)}));
$('refreshNow').addEventListener('click',()=>run(refresh));$('metric').addEventListener('change',()=>run(load));$('compare').addEventListener('change',()=>run(load));window.addEventListener('resize',()=>run(()=>{draw();drawPanels()}));
$('saveInterval').addEventListener('click',()=>run(async()=>{const button=$('saveInterval');button.disabled=true;try{await solarRequest('/api/collection/interval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seconds:Number($('syncInterval').value)})});await status()}finally{button.disabled=false}}));
const canvas=$('chart');
function plotWidth(){return canvas.getBoundingClientRect().width-(series.compare?116:78)}
function chartX(event){const rect=canvas.getBoundingClientRect();return Math.max(58,Math.min(58+plotWidth(),event.clientX-rect.left))}
function timeAt(px){const [start,end]=dates();return start+(px-58)/plotWidth()*(end-start)}
canvas.addEventListener('pointerdown',event=>{if(event.button!==0)return;drag={start:chartX(event),end:chartX(event)};canvas.setPointerCapture(event.pointerId)});
canvas.addEventListener('pointermove',event=>{if(drag){drag.end=chartX(event);draw();return}const points=series.main?.points||[];if(!points.length)return;const t=timeAt(chartX(event));const nearest=list=>list.reduce((a,b)=>Math.abs(a[0]-t)<Math.abs(b[0]-t)?a:b);const p=nearest(points);let text=new Date(p[0]).toLocaleString('es-CL')+' · '+labelOf('metric',series.main.metric)+': '+display(p[1])+(series.main.bucket&&p[2]!==p[3]?' (mín '+display(p[2])+', máx '+display(p[3])+')':'');if(series.compare?.points.length){const q=nearest(series.compare.points);text+=' · '+labelOf('compare',series.compare.metric)+': '+display(q[1])}$('pointReadout').textContent=text});
canvas.addEventListener('pointerup',()=>{if(!drag)return;const selected=drag;drag=null;if(Math.abs(selected.end-selected.start)<12){draw();return}run(()=>changeRange(timeAt(Math.min(selected.start,selected.end)),timeAt(Math.max(selected.start,selected.end))))});
canvas.addEventListener('pointercancel',()=>{drag=null;draw()});
canvas.addEventListener('dblclick',()=>{if(previousRange)run(()=>changeRange(...previousRange))});
setDates(...solarTime.range('today'),'today');
async function updatePanel(){const results=await Promise.allSettled([status(),load(),updateWeather(),updateAlerts(),updateDaily(),updateControl(),...(window.updateBattery?[window.updateBattery()]:[])]);const failure=results.find(result=>result.status==='rejected');if(failure)throw failure.reason}
run(async()=>{await updatePanel();await refresh()});
run(updateStrategy);
setInterval(()=>{if(!document.hidden)run(async()=>{if(activeRange&&activeRange!=='yesterday')setDates(...solarTime.range(activeRange),activeRange);await updatePanel();await refresh()})},60000);
setInterval(()=>{if(!document.hidden)run(updateStrategy)},3600000);
