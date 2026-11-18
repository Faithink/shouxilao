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

  /* ---- 添加到主屏幕:提醒条 + 图示指引(只在手机浏览器里、还没添加时出现) ---- */
  (()=>{
    const ua=navigator.userAgent, isAnd=/Android/.test(ua), isIOS=/iPhone|iPad|iPod/.test(ua)||(!isAnd&&navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
    const inApp=/MicroMessenger|\bQQ\/|DingTalk|AlipayClient|Weibo/i.test(ua);
    const standalone=()=>navigator.standalone===true||(window.matchMedia&&matchMedia("(display-mode: standalone)").matches);
    const KEY="shouxi-a2hs-off";
    const css=`.a2bar{display:flex;align-items:center;gap:10px;padding:9px 14px;background:#1f2430;color:#f9f8f4;font:13px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif}.a2bar span{flex:1}.a2bar button{border:0;border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}.a2bar .go{background:#f0c36a;color:#1f2430;font-weight:600}.a2bar .x{background:transparent;color:#b9bcc6;padding:6px 4px}
.a2mask{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:flex-end;justify-content:center}.a2box{background:var(--card,#fff);color:var(--ink,#1f2430);width:min(560px,100%);max-height:92vh;overflow:auto;border-radius:16px 16px 0 0;padding:18px 16px 22px;font:14px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif}@media(min-width:700px){.a2mask{align-items:center}.a2box{border-radius:16px}}
.a2box h3{margin:0 0 4px;font-size:17px}.a2box .sub{color:var(--mute,#7e8493);font-size:12.5px;margin:0 0 12px}.a2steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.a2s{border:1px solid var(--line,#e5e2d8);border-radius:12px;padding:8px 6px 10px;text-align:center}.a2s svg{width:100%;height:auto;display:block}.a2s b{display:block;font-size:12.5px;margin-top:6px}.a2s em{display:block;font-style:normal;font-size:11.5px;color:var(--mute,#7e8493);line-height:1.45;margin-top:2px}
.a2tip{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--seg,#f1efe7);font-size:12.5px;line-height:1.65}.a2tip b{color:var(--ink,#1f2430)}.a2box .ok{margin-top:14px;width:100%;border:0;border-radius:10px;padding:11px;background:var(--accent,#9a7b2f);color:#fff;font:inherit;font-weight:600;cursor:pointer}`;
    const st=document.createElement("style"); st.textContent=css;
    const F='font-family="system-ui,-apple-system,PingFang SC,sans-serif"', HL='#e8890c';
    const phone=(inner)=>`<svg viewBox="0 0 150 120" xmlns="http://www.w3.org/2000/svg" role="img">${'<rect x="2" y="2" width="146" height="116" rx="12" fill="#f4f2ea" stroke="#cfcbbd"/>'}${inner}</svg>`;
    const ios=[
      phone(`<rect x="12" y="14" width="126" height="56" rx="6" fill="#fff" stroke="#e1ddd0"/><rect x="20" y="24" width="60" height="6" rx="3" fill="#e1ddd0"/><rect x="20" y="36" width="92" height="5" rx="2.5" fill="#ece9de"/><rect x="20" y="46" width="80" height="5" rx="2.5" fill="#ece9de"/><rect x="2" y="84" width="146" height="34" rx="0" fill="#e9e6da"/><g stroke="#8d8a7d" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 98l-5 5 5 5"/><path d="M42 98l5 5-5 5"/><path d="M104 104h-4v10h14v-10h-4"/><path d="M107 108v-9M103 103l4-4 4 4" /><rect x="124" y="97" width="12" height="12" rx="2"/></g><circle cx="75" cy="103" r="14" fill="none" stroke="${HL}" stroke-width="2.5"/><g stroke="${HL}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M68 104v7h14v-7"/><path d="M75 109v-12M71 101l4-4 4 4"/></g>`),
      phone(`<rect x="8" y="8" width="134" height="104" rx="10" fill="#fff" stroke="#e1ddd0"/><g ${F} font-size="9" fill="#555"><rect x="16" y="18" width="118" height="18" rx="4" fill="#f4f2ea"/><text x="24" y="30">拷贝</text><rect x="16" y="42" width="118" height="18" rx="4" fill="#f4f2ea"/><text x="24" y="54">加入书签</text><rect x="16" y="66" width="118" height="20" rx="4" fill="#fff3dc" stroke="${HL}" stroke-width="2"/><text x="24" y="80" fill="#222" font-weight="700">添加到主屏幕</text><rect x="112" y="70" width="14" height="12" rx="3" fill="none" stroke="#222" stroke-width="1.5"/><path d="M119 72v8M115 76h8" stroke="#222" stroke-width="1.5"/><rect x="16" y="90" width="118" height="16" rx="4" fill="#f4f2ea"/><text x="24" y="101">查找页面</text></g>`),
      phone(`<rect x="8" y="8" width="134" height="104" rx="10" fill="#fff" stroke="#e1ddd0"/><g ${F} font-size="9" fill="#555"><text x="16" y="24">取消</text><text x="46" y="24" font-weight="700" fill="#222">添加到主屏幕</text><rect x="104" y="12" width="32" height="16" rx="8" fill="none" stroke="${HL}" stroke-width="2.5"/><text x="111" y="24" fill="${HL}" font-weight="700">添加</text></g><rect x="18" y="40" width="30" height="30" rx="8" fill="#9a7b2f"/><text x="24" y="60" ${F} font-size="12" fill="#fff" font-weight="700">息</text><text x="58" y="52" ${F} font-size="10" fill="#222" font-weight="700">收息佬</text><text x="58" y="66" ${F} font-size="8" fill="#999">shouxilao.app</text><rect x="18" y="82" width="114" height="5" rx="2.5" fill="#ece9de"/><rect x="18" y="92" width="86" height="5" rx="2.5" fill="#ece9de"/>`)
    ];
    const and=[
      phone(`<rect x="2" y="2" width="146" height="22" rx="12" fill="#e9e6da"/><rect x="12" y="8" width="96" height="10" rx="5" fill="#fff"/><g fill="#6b685c"><circle cx="134" cy="7" r="2"/><circle cx="134" cy="13" r="2"/><circle cx="134" cy="19" r="2"/></g><circle cx="134" cy="13" r="12" fill="none" stroke="${HL}" stroke-width="2.5"/><rect x="12" y="36" width="126" height="70" rx="6" fill="#fff" stroke="#e1ddd0"/><rect x="20" y="46" width="60" height="6" rx="3" fill="#e1ddd0"/><rect x="20" y="58" width="92" height="5" rx="2.5" fill="#ece9de"/>`),
      phone(`<rect x="30" y="8" width="112" height="104" rx="8" fill="#fff" stroke="#e1ddd0"/><g ${F} font-size="9" fill="#555"><text x="38" y="26">新建标签页</text><text x="38" y="44">历史记录</text><rect x="34" y="52" width="104" height="22" rx="4" fill="#fff3dc" stroke="${HL}" stroke-width="2"/><text x="38" y="67" fill="#222" font-weight="700">添加到主屏幕</text><text x="38" y="92">分享…</text></g>`),
      phone(`<rect x="16" y="28" width="118" height="68" rx="10" fill="#fff" stroke="#e1ddd0"/><g ${F} font-size="9" fill="#555"><text x="24" y="46" font-weight="700" fill="#222">添加到主屏幕</text><text x="24" y="62">收息佬</text><text x="82" y="86" fill="#777">取消</text><rect x="102" y="74" width="26" height="16" rx="8" fill="none" stroke="${HL}" stroke-width="2.5"/><text x="107" y="86" fill="${HL}" font-weight="700">添加</text></g>`)
    ];
    const capI=[["点「分享」","Safari 底部中间，方框带向上箭头"],["选「添加到主屏幕」","在弹出的列表里往下滑找"],["点右上角「添加」","桌面上就有「收息佬」图标了"]];
    const capA=[["点右上角「⋮」","Chrome 地址栏右边"],["选「添加到主屏幕」","部分手机叫「安装应用」"],["点「添加」","桌面上就有图标了"]];
    const show=()=>{
      if(document.querySelector(".a2mask")) return;
      const useI=isIOS||!isAnd, S=useI?ios:and, C=useI?capI:capA;
      const m=document.createElement("div"); m.className="a2mask";
      m.innerHTML=`<div class="a2box"><h3>添加到主屏幕</h3><p class="sub">${isIOS||!isAnd?"iPhone / iPad（Safari）":"安卓（Chrome）"}，三步完成，之后像 App 一样从桌面图标打开</p>
      <div class="a2steps">${S.map((s,i)=>`<div class="a2s">${s}<b>${i+1}. ${C[i][0]}</b><em>${C[i][1]}</em></div>`).join("")}</div>
      ${inApp?`<div class="a2tip"><b>你现在在微信 / QQ 等 App 里打开的，这里不能添加。</b>请点右上角「···」，选「在浏览器中打开」（iPhone 选 Safari），再按上面的步骤操作。</div>`:""}
      <div class="a2tip"><b>一定要先添加，再从桌面图标里打开并录入持仓。</b>在浏览器里录的数据，和桌面图标里的数据是分开的，不会自动带过去。${useI?"<br>如果在 iOS 26 的 Safari 里找不到「分享」，点右下角「⋯」，再找「分享」。":""}</div>
      <button class="ok" type="button">知道了</button></div>`;
      m.onclick=e=>{if(e.target===m||e.target.classList.contains("ok")) m.remove()};
      document.body.appendChild(m);
    };
    window.showA2HS=show;
    addEventListener("DOMContentLoaded",()=>{
      document.head.appendChild(st);
      if(!(isIOS||isAnd)||standalone()) return;
      let off=false; try{off=localStorage.getItem(KEY)==="1"}catch(e){}
      if(off) return;
      const b=document.createElement("div"); b.className="a2bar";
      b.innerHTML=`<span>${inApp?"请先在浏览器中打开，再":"建议"}<b>添加到主屏幕</b>，像 App 一样用，数据也更稳</span><button class="go" type="button">怎么添加</button><button class="x" type="button" aria-label="不再提示">✕</button>`;
      b.querySelector(".go").onclick=show;
      b.querySelector(".x").onclick=()=>{try{localStorage.setItem(KEY,"1")}catch(e){} b.remove()};
      document.body.prepend(b);
    });
  })();
  if("serviceWorker" in navigator) addEventListener("load",()=>navigator.serviceWorker.register(base+"sw.js").catch(()=>{}));
})();
