function energyNumber(value){return value===null||value===undefined||value===''||typeof value==='boolean'||!Number.isFinite(Number(value))?null:Number(value)}
function energyState(data,observedAt,now=Date.now()){
  const solarValues=['pvInputPower1','pvInputPower2','pvInputPower3','pvInputPower4'].map(key=>energyNumber(data[key])).filter(value=>value!==null);
  const solar=solarValues.length?solarValues.reduce((a,b)=>a+b,0):null;
  const charge=energyNumber(data.batteryChargingPower),discharge=energyNumber(data.batteryDischargingPower),chargeA=energyNumber(data.chargingCurrent),dischargeA=energyNumber(data.dischargingCurrent);
  const charging=(charge||0)>0||(chargeA||0)>0,discharging=(discharge||0)>0||(dischargeA||0)>0;
  const known=[charge,discharge,chargeA,dischargeA].some(value=>value!==null);
  const battery=!known?'unknown':charging&&discharging?'uncertain':charging?'charging':discharging?'discharging':'idle';
  const timestamp=observedAt?+new Date(observedAt):NaN,age=now-timestamp;
  // gridPowerInputActiveTotal mirrors the AC output in battery mode (B); only line mode (L) imports.
  const mode=data.workMode==='L'||data.workMode==='B'?data.workMode:energyNumber(data.statusGrid)===1?'L':energyNumber(data.statusGrid)===0?'B':null;
  const gridField=energyNumber(data.gridPowerInputActiveTotal);
  const grid=mode==='L'?gridField:mode==='B'?0:null;
  return {solar,charge,discharge,chargeA,dischargeA,battery,mode,grid,
    load:energyNumber(data.acOutputActivePowerTotal),soc:energyNumber(data.batteryCapacity),
    fresh:Number.isFinite(timestamp)&&age>=-300000&&age<=600000};
}
function updateEnergy(data,observedAt){
  const state=energyState(data,observedAt),format=value=>value===null?'—':value.toLocaleString('es-CL',{maximumFractionDigits:1});
  const put=(id,text)=>{const element=document.getElementById(id);if(element)element.textContent=text};
  put('diagramSolar',format(state.solar)+' W');put('diagramLoad',format(state.load)+' W');put('diagramGrid',format(state.grid)+' W');put('diagramBattery',format(state.soc)+' %');
  const batteryText=state.battery==='charging'?'Cargando · '+format(state.charge)+' W · '+format(state.chargeA)+' A':state.battery==='discharging'?'Descargando · '+format(state.discharge)+' W · '+format(state.dischargeA)+' A':state.battery==='uncertain'?'Carga/descarga simultánea':state.battery==='unknown'?'Sin lectura':'En espera · '+format(energyNumber(data.batteryVoltage))+' V';
  put('diagramBatteryDetail',batteryText);
  const level=document.getElementById('batteryLevel');if(level&&state.soc!==null){const height=53*Math.max(0,Math.min(100,state.soc))/100;level.setAttribute('height',String(height));level.setAttribute('y',String(75-height))}
  const flows={solar:state.solar>0,load:state.load>0,grid:state.grid>0,battery:state.battery==='charging'||state.battery==='discharging'};
  for(const [name,active] of Object.entries(flows)){const path=document.getElementById('flow-'+name);if(path){path.classList.toggle('energized',Boolean(active&&state.fresh));path.classList.toggle('reversed',name==='battery'&&state.battery==='discharging')}}
  put('flowFreshness',(state.fresh?'● Estado reciente':'○ Lectura guardada · animación en pausa')+(state.mode?' · '+(state.mode==='L'?'Modo red':'Modo batería'):''));
  const sentences=[];
  if(state.solar!==null)sentences.push('Solar: '+format(state.solar)+' W');
  if(state.load!==null)sentences.push('Consumo: '+format(state.load)+' W');
  if(state.battery==='charging')sentences.push('La batería está recibiendo carga');
  if(state.battery==='discharging')sentences.push('La batería está entregando energía');
  if(state.mode==='L')sentences.push('Modo red: la casa se alimenta de la red'+(state.solar>0?' y el sol solo carga la batería':''));
  if(state.mode==='B')sentences.push('Modo batería: la red no aporta');
  if(state.grid<0)sentences.push('La red reporta potencia negativa; sentido sin confirmar');
  if(state.battery==='uncertain')sentences.push('El sentido de la batería requiere confirmar la lectura');
  put('energySummary',(state.fresh?'':'Última lectura disponible. ')+(sentences.length?sentences.join(' · '):'Conecta tu equipo para ver los flujos.'));
}
function weatherDescription(code){
  if(code===null||code===undefined)return 'Sin dato';
  if(code===0)return 'Despejado';if(code<=3)return ['Despejado','Mayormente despejado','Parcialmente nublado','Cubierto'][code];
  if([45,48].includes(code))return 'Niebla';if(code>=51&&code<=57)return 'Llovizna';if(code>=61&&code<=67)return 'Lluvia';
  if(code>=71&&code<=77)return 'Nieve';if(code>=80&&code<=82)return 'Chubascos';if(code>=95)return 'Tormenta';return 'Condiciones variables';
}
async function updateWeather(){
  try{
    const result=await solarRequest('/api/weather'),latest=result.latest;
    if(!latest){document.getElementById('weatherStatus').textContent='Descargando y archivando meteorología…';return}
    const data=latest.payload,format=v=>energyNumber(v)===null?'—':Number(v).toLocaleString('es-CL',{maximumFractionDigits:1});
    document.querySelector('.weather-card').dataset.sky=data.weather_code===0?'clear':data.weather_code>=51?'rain':'cloudy';
    document.getElementById('weatherTemp').textContent=format(data.temperature_2m)+'°';
    document.getElementById('weatherDescription').textContent=weatherDescription(data.weather_code);
    document.getElementById('weatherRadiation').textContent=format(data.shortwave_radiation);
    const gti=document.getElementById('weatherGti');if(gti)gti.textContent=format(data.global_tilted_irradiance)+' W/m²';
    document.getElementById('weatherCloud').textContent=format(data.cloud_cover)+' %';
    document.getElementById('weatherRain').textContent=format(data.precipitation)+' mm';
    document.getElementById('weatherShowers').textContent=format(data.showers)+' mm';
    document.getElementById('weatherWind').textContent=format(data.wind_speed_10m)+' km/h';
    document.getElementById('weatherStatus').textContent='Modelo horario · '+new Date(latest.observed_at).toLocaleString('es-CL',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})+' · '+result.hours_archived+' horas archivadas';
  }catch(error){document.getElementById('weatherStatus').textContent='Meteorología temporalmente no disponible. Se conservan los registros guardados.'}
}
