/* 网页版(PWA)的"静态后端":没有服务器,页面对 /api/* 的请求改成读每天更新的静态数据快照;
   持仓、设置只保存在用户自己的浏览器里(localStorage),不上传。添加个股、手动刷新这类需要后端的功能不提供。 */
(()=>{
  window.SHOUXI_STATIC=true; document.documentElement.classList.add("static");
  const base=location.pathname.replace(/[^/]*$/,""), real=window.fetch.bind(window), KEY="shouxi-holdings", BK="shouxi-bk-";
  const J=(o,s=200)=>new Response(JSON.stringify(o),{status:s,headers:{"Content-Type":"application/json"}});
  const EMPTY={settings:{},lots:[],sells:[],divs:[]};
  const lget=k=>{try{return localStorage.getItem(k)}catch(e){return null}}, lset=(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}};
  const loadH=()=>{const v=lget(KEY); if(v){try{return JSON.parse(v)}catch(e){}} return EMPTY};
  const keys=()=>{const r=[]; try{for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i); if(k&&k.startsWith(BK)) r.push(k)}}catch(e){} return r.sort()};
  const day=()=>{const d=new Date(), z=x=>String(x).padStart(2,"0"); return d.getFullYear()+z(d.getMonth()+1)+z(d.getDate())};
  const roll=txt=>{lset(BK+day(),txt); keys().slice(0,-7).forEach(k=>{try{localStorage.removeItem(k)}catch(e){}})};   // 每天一份,留最近 7 天
  const ver=()=>real(base+"data/version.json",{cache:"no-store"});
  window.fetch=async(u,o={})=>{
    u=String((u&&u.url)||u); const m=(o.method||"GET").toUpperCase(), p=u.split("?")[0];
    if(p==="/changelog.md") return real(base+"changelog.md");
    if(!p.startsWith("/api/")) return real(u,o);
    if(p==="/api/pool") return real(base+"data/pool.json",{cache:"no-cache"});
    if(p.startsWith("/api/stock/")) return real(base+"data/stocks/"+p.split("/").pop()+".json",{cache:"no-cache"});
    if(p==="/api/holdings"){
      if(m==="PUT"){const t=typeof o.body==="string"?o.body:""; try{JSON.parse(t)}catch(e){return J({error:"格式不对"},400)} lset(KEY,t); roll(t); return J({ok:true})}
      return J(loadH());
    }
    if(p==="/api/backups"){
      return J(keys().reverse().map(k=>{let d={};try{d=JSON.parse(lget(k))}catch(e){} const s=k.slice(BK.length);
        return {name:"holdings-"+s+".json",date:s.slice(0,4)+"-"+s.slice(4,6)+"-"+s.slice(6,8),size:(lget(k)||"").length,lots:(d.lots||[]).length,sells:(d.sells||[]).length,favorites:((d.settings||{}).favorites||[]).length}}));
    }
    if(p==="/api/backups/restore"&&m==="POST"){
      let name=""; try{name=JSON.parse(o.body).name}catch(e){} const s=(name.match(/^holdings-(\d{8})\.json$/)||[])[1]; const v=s&&lget(BK+s);
      if(!v) return J({error:"没有这份备份"},404); lset(KEY+".bak",lget(KEY)||""); lset(KEY,v); return J({ok:true});
    }
    if(p==="/api/status") return J({running:false,done:0,total:0,errors:{}});
    if(p==="/api/version") return ver();
    if(p==="/api/update"){const v=await (await ver()).json(); return J({newer:false,current:v.version})}
    if(p==="/api/access") return J({enabled:false,urls:[],port:0});
    if(p==="/api/missing") return J([]);
    console.warn("pwa: 不支持的接口",m,p); const msg="网页版不支持这个功能，请用电脑版或安卓版";
    try{notice(msg)}catch(e){}
    return J({error:msg},403);
  };
  if("serviceWorker" in navigator) addEventListener("load",()=>navigator.serviceWorker.register(base+"sw.js").catch(()=>{}));
})();
