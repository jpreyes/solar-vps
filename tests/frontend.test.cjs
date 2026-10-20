const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const test=require('node:test'),assert=require('node:assert/strict');
const root=path.join(__dirname,'../static');
function requestWith(fetch){const context={fetch,URL,location:{origin:'http://localhost:8088'},AbortController,setTimeout,clearTimeout};vm.runInNewContext(fs.readFileSync(path.join(root,'http.js'),'utf8')+';this.request=solarRequest;',context);return context.request}
test('HTML errors produce a readable error, never Unexpected token',async()=>{
 const request=requestWith(async()=>({status:500,ok:false,redirected:false,text:async()=>'<!doctype html><html>Error</html>'}));
 await assert.rejects(request('/api/refresh'),/respuesta inesperada \(HTTP 500\)/);
});
test('API database errors preserve the actionable message',async()=>{
 const request=requestWith(async()=>({status:503,ok:false,redirected:false,text:async()=>JSON.stringify({error:'La base de datos no está disponible.'})}));
 await assert.rejects(request('/api/status'),/base de datos/);
});
test('Login redirects are identified before parsing HTML',async()=>{
 const request=requestWith(async()=>({status:200,ok:true,redirected:true,url:'http://localhost:8088/local/login'}));
 await assert.rejects(request('/api/refresh'),/sesión terminó/);
});
test('Offline server has a connection message',async()=>{
 const request=requestWith(async()=>{throw new TypeError('Failed to fetch')});
 await assert.rejects(request('/api/status'),/servidor de la aplicación/);
});
test('Successful JSON is returned',async()=>{
 const request=requestWith(async()=>({status:200,ok:true,redirected:false,text:async()=>' {"cached":true} '}));
 assert.equal((await request('/api/refresh')).cached,true);
});
const context={Date};vm.runInNewContext(fs.readFileSync(path.join(root,'chart-time.js'),'utf8')+';this.time=solarTime;',context);
test('Quick ranges use the requested interval',()=>{const now=+new Date('2026-10-20T15:30:00-03:00');for(const [range,hours] of [['1h',1],['6h',6],['24h',24],['7d',168]]){const [start,end]=context.time.range(range,now);assert.equal(end,now);assert.equal(end-start,hours*3600000)}});
test('Today and yesterday use calendar boundaries',()=>{const now=+new Date(2026,9,20,15,30);assert.equal(context.time.range('today',now)[0],+new Date(2026,9,20));const previous=context.time.range('yesterday',now);assert.equal(previous[0],+new Date(2026,9,19));assert.equal(previous[1],+new Date(2026,9,20))});
test('Zoom retains the center and navigation retains the span',()=>{const zoom=context.time.zoom(0,3600000,.5);assert.equal(zoom[1]-zoom[0],1800000);assert.equal((zoom[1]+zoom[0])/2,1800000);const shifted=context.time.shift(0,3600000,-1);assert.equal(shifted[0],-3600000);assert.equal(shifted[1],0)});
const energyContext={Date};vm.runInNewContext(fs.readFileSync(path.join(root,'energy.js'),'utf8')+';this.state=energyState;',energyContext);
test('Energy diagram detects charging, discharging and unknown data',()=>{
 const time='2026-10-20T12:00:00Z',now=+new Date(time);
 assert.equal(energyContext.state({chargingCurrent:21,dischargingCurrent:0},time,now).battery,'charging');
 assert.equal(energyContext.state({batteryChargingPower:0,batteryDischargingPower:500},time,now).battery,'discharging');
 assert.equal(energyContext.state({},time,now).battery,'unknown');
 assert.equal(energyContext.state({},time,now).solar,null);
});
test('Old readings and conflicting battery directions do not imply a live flow',()=>{
 const time='2026-10-20T12:00:00Z',now=+new Date(time);
 assert.equal(energyContext.state({chargingCurrent:21},time,now+660000).fresh,false);
 assert.equal(energyContext.state({chargingCurrent:21,dischargingCurrent:4},time,now).battery,'uncertain');
 assert.equal(energyContext.state({pvInputPower1:0,pvInputPower2:1360},time,now).solar,1360);
});
