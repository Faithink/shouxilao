/* 网页版的离线缓存:页面本体和图片先用缓存(后台更新),数据快照优先取最新、断网时用上一次的 */
const V="shouxi-pwa-1.8.0-202611210210";
self.addEventListener("install",e=>{self.skipWaiting()});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==V).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{
  const r=e.request; if(r.method!=="GET"||!r.url.startsWith(self.location.origin)) return;
  const isData=/\/data\//.test(r.url);
  e.respondWith((async()=>{
    const c=await caches.open(V);
    if(isData){
      try{const n=await fetch(r,{cache:"no-cache"}); if(n.ok) c.put(r,n.clone()); return n}catch(err){const h=await c.match(r); if(h) return h; throw err}
    }
    const h=await c.match(r,{ignoreSearch:true});
    const net=fetch(r).then(n=>{if(n.ok) c.put(r,n.clone()); return n}).catch(()=>h);
    return h||net;
  })());
});
