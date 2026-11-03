/* 在线演示版的"假后端":把页面对 /api/* 的请求改成读静态 JSON,没有服务器也能跑。
   持仓只存在访问者自己的浏览器(localStorage);刷新数据、添加/移出股票等需要后端的功能提示去下载桌面版。 */
(()=>{
  const base=location.pathname.replace(/[^/]*$/,""), real=window.fetch.bind(window), KEY="shouxi-demo-holdings";
  const J=(o,s=200)=>new Response(JSON.stringify(o),{status:s,headers:{"Content-Type":"application/json"}});
  const loadH=async()=>{try{const v=localStorage.getItem(KEY); if(v) return JSON.parse(v)}catch(e){} return (await real(base+"demo/holdings.json")).json()};
  window.fetch=async(u,o={})=>{
    u=String((u&&u.url)||u); const m=(o.method||"GET").toUpperCase(), p=u.split("?")[0];
    if(p==="/changelog.md") return real(base+"changelog.md");
    if(!p.startsWith("/api/")) return real(u,o);
    if(p==="/api/pool") return real(base+"demo/pool.json");
    if(p.startsWith("/api/stock/")) return real(base+"demo/stocks/"+p.split("/").pop()+".json");
    if(p==="/api/holdings"){
      if(m==="PUT"){try{localStorage.setItem(KEY,o.body)}catch(e){} return J({ok:true})}
      return J(await loadH());
    }
    if(p==="/api/status") return J({running:false});
    if(p==="/api/version") return real(base+"demo/version.json");
    if(p==="/api/update"){const v=await (await real(base+"demo/version.json")).json(); return J({newer:false,current:v.version})}
    if(p==="/api/access") return J({enabled:false,urls:[],port:0});
    if(p==="/api/missing") return J([]);
    const msg="在线演示版是只读的，这个功能请下载桌面版使用";
    try{notice(msg)}catch(e){}
    return J({error:msg},403);
  };
  addEventListener("DOMContentLoaded",async()=>{
    let up="";try{up=(await (await real(base+"demo/version.json")).json()).updated||""}catch(e){}
    const b=document.createElement("div");
    b.setAttribute("style","background:#1f2430;color:#f9f8f4;font:13px/1.6 system-ui,-apple-system,'PingFang SC',sans-serif;padding:8px 16px;text-align:center");
    b.innerHTML=`在线演示 · 数据截至 ${up} · 只读，持仓是虚构的示例，你的改动只保存在这个浏览器里 · <a style="color:#f0c36a" href="https://github.com/Faithink/shouxilao" target="_blank" rel="noopener">下载桌面版 / 源码</a>`;
    document.body.prepend(b);
  });
})();
