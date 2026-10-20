/* API responses can be JSON, a login redirect, a proxy HTML error, or offline. */
async function solarRequest(path, options={}) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),60000);
  try {
    let response;
    try {response=await fetch(new URL(path,location.origin),{...options,signal:controller.signal,headers:{Accept:'application/json',...(options.headers||{})}})}
    catch(error){throw new Error(error.name==='AbortError'?'La consulta tardó demasiado. Puedes volver a intentarlo.':'No se pudo conectar con el servidor de la aplicación. Comprueba que esté funcionando.')}
    if(response.redirected && new URL(response.url).pathname.startsWith('/local/'))throw new Error('La sesión terminó. Vuelve a ingresar al panel.');
    const text=await response.text();
    let data;
    try{data=JSON.parse(text)}catch{throw new Error(response.status===401?'La sesión terminó. Vuelve a ingresar al panel.':'El servidor devolvió una respuesta inesperada (HTTP '+response.status+'). Recarga el panel o vuelve a intentarlo.')}
    if(!response.ok)throw new Error(data.error||'No se pudo completar la consulta (HTTP '+response.status+').');
    return data;
  }finally{clearTimeout(timer)}
}
