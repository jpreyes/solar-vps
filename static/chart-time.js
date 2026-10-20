const solarTime={
  range(name, now=Date.now()){
    const end=new Date(now),today=new Date(now);today.setHours(0,0,0,0);
    if(name==='today')return [+today,+end];
    if(name==='yesterday'){const start=new Date(today);start.setDate(start.getDate()-1);return [+start,+today]}
    if(name==='all')return [+new Date(2026,9,18),+end];
    const duration={'1h':3600000,'6h':21600000,'24h':86400000,'7d':604800000}[name];
    if(!duration)throw new Error('Periodo desconocido');
    return [now-duration,now];
  },
  zoom(start,end,factor){const center=(start+end)/2,half=Math.max(60000,(end-start)*factor)/2;return [center-half,center+half]},
  shift(start,end,direction){const offset=(end-start)*direction;return [start+offset,end+offset]},
  tickLabel(timestamp,span){const date=new Date(timestamp);return span<=86400000?date.toLocaleTimeString('es-CL',{hour:'2-digit',minute:'2-digit'}):date.toLocaleString('es-CL',{day:'2-digit',month:'short',...(span<4*86400000?{hour:'2-digit',minute:'2-digit'}:{})})}
};
