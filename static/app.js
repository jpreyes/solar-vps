const $=id=>document.getElementById(id);
for(const [key,label] of [['shortwave_radiation','Radiación GHI estimada · W/m²'],['direct_radiation','Radiación directa estimada · W/m²'],['diffuse_radiation','Radiación difusa estimada · W/m²'],['temperature_2m','Temperatura Valdivia · °C'],['cloud_cover','Nubosidad Valdivia · %'],['precipitation','Precipitación total Valdivia · mm/hora'],['showers','Chubascos Valdivia · mm/hora'],['rain','Lluvia Valdivia · mm/hora'],['wind_speed_10m','Viento Valdivia · km/h'],['wind_direction_10m','Dirección del viento · °'],['relative_humidity_2m','Humedad relativa · %'],['surface_pressure','Presión atmosférica · hPa'],['direct_normal_irradiance','Irradiancia normal directa · W/m²']]){const option=document.createElement('option');option.value='weather:'+key;option.textContent=label;$('metric').append(option)}
let rows=[],activeRange='today',previousRange=null,drag=null,loadNumber=0,refreshing=false;
const localInput=d=>new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
function number(v){return v===null||v===undefined||v===''||typeof v==='boolean'?null:Number.isFinite(Number(v))?Number(v):null}
function display(v){const n=number(v);return n===null?'—':n.toLocaleString('es-CL',{maximumFractionDigits:1})}
function card(label,value,unit,sub){
  const el=document.createElement('article');el.className='card';
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
function metricKey(){return $('metric').value.replace(/^weather:/,'')}
async function status(){
  const s=await solarRequest('/api/status'),d=s.latest?.response?.data||{},pv1=number(d.pvInputPower1),pv2=number(d.pvInputPower2);
  $('cards').replaceChildren(card('Producción solar',pv1===null&&pv2===null?null:(pv1||0)+(pv2||0),'W','PV1 '+display(pv1)+' W · PV2 '+display(pv2)+' W'),card('Consumo',d.acOutputActivePowerTotal,'W','Potencia activa de salida'),card('Estado de batería',d.batteryCapacity,'%','Tensión '+display(d.batteryVoltage)+' V'),card('Carga de batería',d.batteryChargingPower,'W','Corriente de carga '+display(d.chargingCurrent)+' A'),card('Entrada de red',d.gridPowerInputActiveTotal,'W','Tensión '+display(d.gridVoltageR)+' V'));
  const age=s.latest?Math.max(0,Math.round((Date.now()-new Date(s.latest.received_at))/60000)):null;
  updateEnergy(d,s.latest?.observed_at);
  $('status').textContent=s.latest?'Última consulta guardada hace '+age+' min · '+new Date(s.latest.received_at).toLocaleString('es-CL'):'Pendiente de la primera lectura';
  $('event').textContent=s.event?(s.event.ok?'✓ ':'⚠ ')+s.event.detail+' · '+new Date(s.event.time).toLocaleString('es-CL'):'Sin intentos registrados';
  $('stats').textContent=s.stats.captures+' respuestas originales archivadas'+(s.stats.since?' desde '+new Date(s.stats.since).toLocaleString('es-CL'):'');$('raw').textContent=JSON.stringify(d,null,2);
  const h=s.coverage;$('coverage').textContent=h?.measurements?h.measurements+' registros históricos · '+(h.first_time?new Date(h.first_time).toLocaleString('es-CL'):'fecha pendiente')+' — '+(h.last_time?new Date(h.last_time).toLocaleString('es-CL'):'fecha pendiente'):'Pendiente de la primera descarga histórica.';
  const collection=s.collection;
  if(collection){if(document.activeElement!==$('syncInterval'))$('syncInterval').value=String(collection.interval_seconds);$('syncInfo').textContent='Intervalo activo: '+collection.interval_seconds/60+' min.'+(collection.last_duration!==null?' Última descarga: '+collection.last_duration.toFixed(1)+' s, '+collection.last_pages+' páginas, '+(collection.last_added||0)+' registros nuevos.':' Sin descarga cronometrada todavía.')+(collection.last_error?' Error: '+collection.last_error:'')}
}
async function load(){
  const requestNumber=++loadNumber,q=query(),range=dates();
  $('rangeLabel').textContent=range.map(t=>new Date(t).toLocaleString('es-CL',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})).join(' → ');
  $('apply').disabled=true;$('chartNote').textContent='Consultando el archivo…';
  try{
    const endpoint=$('metric').value.startsWith('weather:')?'/api/weather/series':'/api/series';
    const s=await solarRequest(endpoint+'?'+q);if(requestNumber!==loadNumber)return;
    rows=s.rows;$('csv').href='/api/export.csv?'+q;$('jsonl').href='/api/export.jsonl?'+q;
    $('chartNote').textContent=rows.length+' lecturas en el periodo.'+(s.truncated?' Se muestran las primeras 5000; acota el rango. Las exportaciones incluyen todos los registros.':'');draw();
  }catch(error){if(requestNumber===loadNumber)$('chartNote').textContent='No se pudo actualizar el gráfico. Las lecturas anteriores siguen guardadas.';throw error}
  finally{if(requestNumber===loadNumber)$('apply').disabled=false}
}
function draw(){
  const canvas=$('chart'),rect=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;
  canvas.width=rect.width*ratio;canvas.height=300*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);
  const w=rect.width,left=58,right=w-20,top=20,bottom=248,key=metricKey(),[first,last]=dates(),span=last-first,x=t=>left+(t-first)/span*(right-left);
  const points=rows.map(r=>({t:+new Date(r.observed_at||r.received_at),v:number(r.payload[key])})).filter(p=>p.t>=first&&p.t<=last);
  const valid=points.filter(p=>p.v!==null),min=valid.length?Math.min(...valid.map(p=>p.v)):0,max=valid.length?Math.max(...valid.map(p=>p.v)):1;
  const padding=Math.max((max-min)*0.12,1),lo=min<0?min-padding:Math.max(0,min-padding),hi=Math.max(lo+1,max+padding),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);c.font='11px system-ui';
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4;c.strokeStyle='#e5ece6';c.beginPath();c.moveTo(left,y(value));c.lineTo(right,y(value));c.stroke();c.fillStyle='#6b8078';c.textAlign='right';c.fillText(display(value),left-8,y(value)+4)}
  const count=Math.max(2,Math.min(7,Math.floor((right-left)/115)));
  for(let i=0;i<=count;i++){const t=first+span*i/count;c.strokeStyle='#edf1ed';c.beginPath();c.moveTo(x(t),top);c.lineTo(x(t),bottom);c.stroke();c.fillStyle='#6b8078';c.textAlign=i===0?'left':i===count?'right':'center';c.fillText(solarTime.tickLabel(t,span),x(t),bottom+25)}
  c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();c.strokeStyle='#35795a';c.lineWidth=2;c.beginPath();let previous=null;
  const maxGap=$('metric').value.startsWith('weather:')?7200000:600000;
  for(const p of points){if(p.v===null){previous=null;continue}if(previous&&p.t-previous.t<maxGap)c.lineTo(x(p.t),y(p.v));else c.moveTo(x(p.t),y(p.v));previous=p}c.stroke();
  c.fillStyle='#35795a';for(const p of valid){c.beginPath();c.arc(x(p.t),y(p.v),2,0,Math.PI*2);c.fill()}
  if(drag){c.fillStyle='rgba(53,121,90,.16)';c.fillRect(Math.min(drag.start,drag.end),top,Math.abs(drag.end-drag.start),bottom-top)}c.restore();
  if(!valid.length){c.fillStyle='#6b8078';c.textAlign='left';c.fillText('No hay datos de esta variable en el periodo.',left+8,130)}
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
$('fitData').addEventListener('click',()=>run(async()=>{if(!rows.length)throw new Error('No hay lecturas en este periodo para ajustar el eje.');const times=rows.map(r=>+new Date(r.observed_at||r.received_at)),start=Math.min(...times),end=Math.max(...times),pad=Math.max(60000,(end-start)*.04);await changeRange(start-pad,end+pad)}));
$('refreshNow').addEventListener('click',()=>run(refresh));$('metric').addEventListener('change',()=>run(load));window.addEventListener('resize',()=>run(draw));
$('saveInterval').addEventListener('click',()=>run(async()=>{const button=$('saveInterval');button.disabled=true;try{await solarRequest('/api/collection/interval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seconds:Number($('syncInterval').value)})});await status()}finally{button.disabled=false}}));
const canvas=$('chart');
function chartX(event){const rect=canvas.getBoundingClientRect();return Math.max(58,Math.min(rect.width-20,event.clientX-rect.left))}
canvas.addEventListener('pointerdown',event=>{if(event.button!==0)return;drag={start:chartX(event),end:chartX(event)};canvas.setPointerCapture(event.pointerId)});
canvas.addEventListener('pointermove',event=>{if(drag){drag.end=chartX(event);draw();return}if(!rows.length)return;const [start,end]=dates(),width=canvas.getBoundingClientRect().width,t=start+(chartX(event)-58)/(width-78)*(end-start);const nearest=rows.reduce((a,b)=>Math.abs(+new Date(a.observed_at||a.received_at)-t)<Math.abs(+new Date(b.observed_at||b.received_at)-t)?a:b);$('pointReadout').textContent=new Date(nearest.observed_at||nearest.received_at).toLocaleString('es-CL')+' · '+$('metric').selectedOptions[0].textContent+': '+display(nearest.payload[metricKey()])});
canvas.addEventListener('pointerup',()=>{if(!drag)return;const selected=drag;drag=null;if(Math.abs(selected.end-selected.start)<12){draw();return}const [start,end]=dates(),width=canvas.getBoundingClientRect().width,t=x=>start+(x-58)/(width-78)*(end-start);run(()=>changeRange(t(Math.min(selected.start,selected.end)),t(Math.max(selected.start,selected.end))))});
canvas.addEventListener('pointercancel',()=>{drag=null;draw()});
canvas.addEventListener('dblclick',()=>{if(previousRange)run(()=>changeRange(...previousRange))});
setDates(...solarTime.range('today'),'today');
async function updatePanel(){const results=await Promise.allSettled([status(),load(),updateWeather()]);const failure=results.find(result=>result.status==='rejected');if(failure)throw failure.reason}
run(async()=>{await updatePanel();await refresh()});
setInterval(()=>{if(!document.hidden)run(async()=>{if(activeRange&&activeRange!=='yesterday')setDates(...solarTime.range(activeRange),activeRange);await updatePanel();await refresh()})},60000);
