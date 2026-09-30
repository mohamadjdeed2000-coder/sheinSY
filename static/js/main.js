async function toggleFavorite(id,el){let r=await fetch('/favorite/'+id,{method:'POST'});let d=await r.json();if(el)el.innerText=d.favorite?'♥':'♡';}
if(location.pathname==='/admin'){setInterval(async()=>{try{let r=await fetch('/admin/api/new-orders');if(r.ok){let d=await r.json(),e=document.getElementById('newBadge');if(e)e.innerText=d.count+' new orders'}}catch(e){}},10000)}

function goBackOrHome(){ if(document.referrer && window.history.length>1){ window.history.back(); } else { window.location.href='/'; } }
