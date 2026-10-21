/* Alerts, daily energy balance and battery-strategy study. */
const MONTHS=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
const PANEL_COLORS={pv:'#e0a93b',load:'#237c7b',grid:'#5b8fd6',expected:'#8a6a1e',current:'#9aa9b0',best:'#237c7b',winter:'#c46b4a'};
let dailyRows=[],strategyData=null;
function el(tag,attrs={},...children){const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='class')e.className=v;else if(k==='style')e.style.cssText=v;else e.setAttribute(k,v)}e.append(...children.filter(c=>c!==null&&c!==undefined));return e}
function fmt(v,digits=1){return v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('es-CL',{maximumFractionDigits:digits})}
function canvasContext(id,height){const canvas=document.getElementById(id),rect=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;canvas.width=rect.width*ratio;canvas.height=height*ratio;const c=canvas.getContext('2d');c.scale(ratio,ratio);c.font='11px system-ui';return [c,rect.width]}

async function updateAlerts(){
  const box=document.getElementById('alerts');
  const r=await solarRequest('/api/insights');
  const items=r.alerts.map(a=>el('div',{class:'alert '+a.level},el('b',{},a.level==='warning'?'⚠ ':'ℹ '),a.text,a.last?el('span',{class:'small muted'},' · último: '+new Date(a.last).toLocaleString('es-CL',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})):null));
  box.replaceChildren(...items);box.hidden=!items.length;
  const t=r.thresholds||{},facts=[];
  if(t.to_grid_soc!==null&&t.to_grid_soc!==undefined)facts.push(['Pasa a red al',fmt(t.to_grid_soc,0)+' %']);
  if(t.to_battery_soc!==null&&t.to_battery_soc!==undefined)facts.push(['Vuelve a batería al',fmt(t.to_battery_soc,0)+' %']);
  if(r.capacity_kwh)facts.push(['Capacidad medida',fmt(r.capacity_kwh)+' kWh']);
  if(r.days_since_full_charge!==null&&r.days_since_full_charge!==undefined)facts.push(['Última carga al 100 %','hace '+r.days_since_full_charge+' días']);
  document.getElementById('thresholds').replaceChildren(...facts.map(([k,v])=>el('div',{},el('span',{},k),el('b',{},v))));
}

async function updateDaily(){
  const days=Number(document.getElementById('dailyRange').value),end=new Date(),start=new Date(end.getTime()-days*86400000);
  const r=await solarRequest('/api/daily?'+new URLSearchParams({start:start.toISOString(),end:end.toISOString()}));
  dailyRows=r.days;drawDaily();
  const sum=k=>dailyRows.reduce((a,d)=>a+(d[k]||0),0),load=sum('load_kwh'),grid=sum('grid_kwh');
  const full=dailyRows.filter(d=>d.covered_hours>=20);
  document.getElementById('dailyTotals').replaceChildren(...[
    ['Solar',fmt(sum('pv_kwh'))+' kWh'],['Consumo',fmt(load)+' kWh'],['Red importada',fmt(grid)+' kWh'],
    ['Autosuficiencia',load>0?fmt(100*Math.max(0,1-grid/load),0)+' %':'—'],
    ['Consumo medio',full.length?fmt(full.reduce((a,d)=>a+d.load_kwh*24/d.covered_hours,0)/full.length)+' kWh/día':'—'],
    ['Batería entregó',fmt(sum('battery_out_kwh'))+' kWh']].map(([k,v])=>el('div',{},el('span',{},k),el('b',{},v))));
}
function drawDaily(){
  if(!document.getElementById('dailyChart'))return;
  const [c,w]=canvasContext('dailyChart',260),left=46,right=w-12,top=14,bottom=222,rows=dailyRows;
  if(!rows.length){c.fillStyle='#6b8078';c.fillText('Sin días con datos todavía.',left,120);return}
  const max=Math.max(1,...rows.flatMap(d=>[d.pv_kwh,d.load_kwh,d.grid_kwh,d.pv_expected_kwh||0]))*1.1,y=v=>bottom-v/max*(bottom-top);
  for(let i=0;i<=4;i++){const v=max*i/4;c.strokeStyle='#e5ece6';c.beginPath();c.moveTo(left,y(v));c.lineTo(right,y(v));c.stroke();c.fillStyle='#6b8078';c.textAlign='right';c.fillText(fmt(v,0),left-6,y(v)+4)}
  const slot=(right-left)/rows.length,bar=Math.max(1,Math.min(14,slot/4));
  rows.forEach((d,i)=>{
    const x0=left+i*slot+slot/2-bar*1.5;
    [['pv_kwh',PANEL_COLORS.pv],['load_kwh',PANEL_COLORS.load],['grid_kwh',PANEL_COLORS.grid]].forEach(([k,color],j)=>{c.fillStyle=color;c.globalAlpha=d.covered_hours<20?.45:1;c.fillRect(x0+j*bar,y(d[k]||0),bar-1,bottom-y(d[k]||0))});
    c.globalAlpha=1;
    if(d.pv_expected_kwh!==null&&d.covered_hours>=20){c.strokeStyle=PANEL_COLORS.expected;c.lineWidth=2;c.beginPath();c.moveTo(x0-2,y(d.pv_expected_kwh));c.lineTo(x0+bar*3+1,y(d.pv_expected_kwh));c.stroke();c.lineWidth=1}
    const every=Math.ceil(rows.length/Math.max(2,Math.floor((right-left)/48)));
    if(i%every===0){c.fillStyle='#6b8078';c.textAlign='center';const [yy,mm,dd]=d.date.split('-');c.fillText(dd+' '+MONTHS[+mm-1],left+i*slot+slot/2,bottom+16)}
  });
  c.fillStyle='#6b8078';c.textAlign='left';c.fillText('kWh',4,top+4);
}

function adviceFor(day,loadKwh){
  if(day.wind_max_kmh>=50||day.precipitation_mm>=25)return ['warn','Temporal probable (viento '+day.wind_max_kmh+' km/h, '+fmt(day.precipitation_mm)+' mm). Si te preocupan cortes de luz, sube temporalmente el mínimo a 40–50 % para guardar reserva.'];
  if(day.hours<20)return ['', 'Resto del día: ~'+fmt(day.pv_kwh,0)+' kWh solares.'];
  if(day.pv_kwh>=loadKwh*1.6)return ['good','Sol suficiente para cubrir el consumo y llenar la batería.'];
  if(day.pv_kwh>=loadKwh*0.8)return ['','Sol justo: la batería se recargará parcialmente.'];
  return ['low','Día escaso: la batería casi no se recargará; la red cubrirá la noche.'];
}
async function updateStrategy(){
  const r=await solarRequest('/api/strategy'),s=r.study;strategyData=s;
  const loadKwh=s.ready?s.load_daily_kwh[String(new Date().getMonth()+1)]:14;
  document.getElementById('forecast').replaceChildren(...(r.forecast.length?r.forecast:[]).map(d=>{const [tone,text]=adviceFor(d,loadKwh);const date=new Date(d.date+'T12:00:00');return el('div',{class:'day '+tone},el('span',{},date.toLocaleDateString('es-CL',{weekday:'short',day:'numeric',month:'short'})),el('b',{},fmt(d.pv_kwh,0)+' kWh'),el('small',{},'nubes '+fmt(d.cloud_cover,0)+' % · viento '+fmt(d.wind_max_kmh,0)+' km/h'),el('p',{},text))}));
  if(!r.forecast.length)document.getElementById('forecast').textContent='El pronóstico aparecerá tras la próxima descarga meteorológica.';
  if(!s.ready){document.getElementById('strategySummary').textContent=s.reason;return}
  const results=s.results,best=results.find(x=>x.name===s.best),current=results.find(x=>x.name.includes('(actual)'));
  const seasonal=results.find(x=>x.name.includes('40/50 invierno'));
  const parts=['Simulación hora a hora con '+fmt(s.years,0)+' años de radiación de Valdivia sobre el plano de tus paneles, '+fmt(s.system.pv_kwp)+' kWp limitado a '+fmt(s.system.ac_limit_kw)+' kW, batería de '+fmt(s.system.capacity_kwh)+' kWh y tu consumo '+(s.load_measured_months.length?'medido':'estimado')+'.'];
  parts.push('Menor costo: '+best.name+' ('+fmt(best.grid_kwh_year,0)+' kWh/año de red).');
  if(current&&current.name!==best.name)parts.push('Tu configuración actual ('+current.name.replace(' (actual)','')+') usaría '+fmt(current.grid_kwh_year-best.grid_kwh_year,0)+' kWh/año más de red (≈ $'+fmt(current.cost_clp_year-best.cost_clp_year,0)+').');
  if(seasonal)parts.push('Subir a 40/50 en invierno cuesta ≈ $'+fmt(seasonal.cost_clp_year-best.cost_clp_year,0)+'/año: no ahorra, compra reserva ante cortes.');
  document.getElementById('strategySummary').textContent=parts.join(' ');
  document.getElementById('strategyBadge').textContent='Recomendado: '+best.name;
  document.querySelector('#strategyTable tbody').replaceChildren(...results.map(x=>el('tr',{class:x.name===s.best?'best':x===current?'current':''},el('td',{},x.name),el('td',{},fmt(x.grid_kwh_year,0)),el('td',{},fmt(x.self_sufficiency*100,0)+' %'),el('td',{},fmt(x.cycles_year,0)),el('td',{},fmt(x.transfers_year,0)),el('td',{},'$'+fmt(x.cost_clp_year,0)))));
  document.getElementById('strategyNote').textContent='* Costo = red × $'+fmt(s.tariff_clp_kwh,0)+'/kWh + desgaste de batería × $'+fmt(s.wear_clp_kwh,0)+'/kWh entregado (ajustables en .env). Supuestos: sin exportación a la red ni carga de batería desde la red; en modo red la casa usa la red y el sol solo carga la batería (comportamiento medido). Consumo medido en '+(s.load_measured_months.map(m=>MONTHS[m-1]).join(', ')||'ningún mes aún')+'; los demás meses se extrapolan (+'+'invierno). Recalcula sola cada hora y mejora a medida que se acumulan datos.';
  drawPanels();
}
function drawMonthly(){
  const s=strategyData;if(!s||!s.ready||!document.getElementById('monthlyGrid'))return;
  const best=s.results.find(x=>x.name===s.best),current=s.results.find(x=>x.name.includes('(actual)')),winter=s.results.find(x=>x.name.includes('40/50 invierno'));
  const sets=[[current,PANEL_COLORS.current],[best,PANEL_COLORS.best],[winter,PANEL_COLORS.winter]].filter(([x])=>x&&!(x===current&&x.name===s.best));
  const [c,w]=canvasContext('monthlyGrid',200),left=46,right=w-12,top=24,bottom=176;
  const max=Math.max(1,...sets.flatMap(([x])=>Object.values(x.grid_kwh_month)))*1.1,y=v=>bottom-v/max*(bottom-top),slot=(right-left)/12,bar=Math.min(14,slot/(sets.length+1));
  for(let i=0;i<=3;i++){const v=max*i/3;c.strokeStyle='#e5ece6';c.beginPath();c.moveTo(left,y(v));c.lineTo(right,y(v));c.stroke();c.fillStyle='#6b8078';c.textAlign='right';c.fillText(fmt(v,0),left-6,y(v)+4)}
  for(let m=1;m<=12;m++){sets.forEach(([x,color],j)=>{const v=x.grid_kwh_month[m]||0;c.fillStyle=color;c.fillRect(left+(m-1)*slot+slot/2-bar*sets.length/2+j*bar,y(v),bar-1,bottom-y(v))});c.fillStyle='#6b8078';c.textAlign='center';c.fillText(MONTHS[m-1],left+(m-.5)*slot,bottom+15)}
  c.textAlign='left';let lx=left;for(const [x,color] of sets){c.fillStyle=color;c.fillRect(lx,6,10,10);c.fillStyle='#4a6470';c.fillText(x.name,lx+14,15);lx+=c.measureText(x.name).width+34}
}
function drawPanels(){drawDaily();drawMonthly()}
document.getElementById('dailyRange').addEventListener('change',()=>run(updateDaily));
