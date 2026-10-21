/* Sidebar navigation: one view at a time, remembered in the URL hash. */
(function(){
  const views=[...document.querySelectorAll('.view')],links=[...document.querySelectorAll('nav.side a')];
  function show(name){
    if(!views.some(v=>v.dataset.view===name))name='ahora';
    views.forEach(v=>v.classList.toggle('on',v.dataset.view===name));
    links.forEach(a=>{a.classList.toggle('on',a.dataset.view===name);a.toggleAttribute('aria-current',a.dataset.view===name)});
    // Canvases measure their width when drawn: redraw after the view becomes visible.
    requestAnimationFrame(()=>{try{if(name==='datos'&&typeof draw==='function')draw();if(typeof drawPanels==='function')drawPanels()}catch(e){}});
  }
  window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
  show(location.hash.slice(1)||'ahora');
  const toggle=document.getElementById('alertsToggle'),box=document.getElementById('alerts');
  toggle.addEventListener('click',()=>{const open=box.dataset.open!=='1';box.dataset.open=open?'1':'0';box.hidden=!open||!box.children.length;toggle.setAttribute('aria-expanded',String(open))});
})();
