document.getElementById('connect').addEventListener('submit',async e=>{
  e.preventDefault();
  const result=document.getElementById('result'),button=document.getElementById('submit');
  button.disabled=true;result.textContent='Conectando con isolar.tumcapp.com…';
  try{
    await solarRequest('/local/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value,serial:document.getElementById('serial').value})});
    document.getElementById('password').value='';
    result.textContent='Equipo conectado. Descarga histórica iniciada; abriendo el panel…';window.location.href='/';
  }catch(error){result.textContent=error.message;button.disabled=false;}
});
