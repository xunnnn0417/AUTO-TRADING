"""Small same-origin mobile page; no CDN, analytics, or cached trading data."""

HTML = '''<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101015"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icon.svg">
<link rel="stylesheet" href="/app.css"><title>對沖小幫手</title></head><body>
<main><header><div><strong>對沖小幫手</strong><small id="stageLabel">手機控制</small></div>
<button id="connect" class="subtle">連線</button></header>
<section id="pairing" hidden><h2>第一次配對</h2><p>在電腦的「手機連線」取得配對碼。配對後會記住這支手機。</p>
<label>裝置名稱<input id="deviceName" maxlength="32" value="我的手機" autocomplete="off"></label>
<label>配對碼<input id="pairCode" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="one-time-code"></label>
<button id="pair" class="primary">配對並連線</button></section>
<div id="health" class="health" role="status">尚未連線</div>
<section id="trade"><div class="selects"><label>方案<select id="profile" data-control></select></label>
<label>階段<select id="stage" data-control></select></label></div>
<div class="lots"><div><span id="internalPlatform">場內手數</span><strong id="internalLot">—</strong></div>
<div><span id="externalPlatform">場外手數</span><strong id="externalLot">—</strong></div></div>
<div class="grid"><label>場內方向<select id="direction" data-control><option value="BUY">買入</option><option value="SELL">賣出</option></select></label>
<label>預期 SL<span class="input-wrap"><input data-field="expected_sl_combined" inputmode="decimal" autocomplete="off" data-control><button class="warning" data-warning="expected_sl_combined" hidden aria-label="查看預期止損提醒">!</button></span></label>
<label>場內餘額<span class="input-wrap"><input data-field="internal_balance" inputmode="decimal" autocomplete="off" data-control><button class="warning" data-warning="internal_balance" hidden aria-label="查看場內餘額提醒">!</button></span></label>
<label>每日獲利／虧損<input data-field="daily_pnl" inputmode="decimal" autocomplete="off" data-control></label></div>
<p id="draftStatus" class="muted" aria-live="polite">數值以電腦回報為準</p>
<div class="row"><button id="update" data-control>更新</button><button id="fill" class="primary" data-control>⇆ 填入兩邊</button></div>
<section class="progress"><h2>帳號進度</h2><svg id="ruler" viewBox="0 0 340 115" role="img" aria-label="帳號進度"></svg><p id="rulerNote" class="muted"></p></section>
<details id="more"><summary>其他交易操作</summary><div class="grid">
<button data-action="fill_internal" data-control>填入場內</button><button data-action="fill_external" data-control>填入場外</button>
<button data-action="view_sl_tp" data-control>查看止盈／損</button><button data-action="sync" data-control>同步場外 SL／TP</button>
<label>場內進場點位<input data-field="internal_entry_price" inputmode="decimal" autocomplete="off" data-control></label></div>
<div id="options" class="options"></div></details></section>
<section id="newsSection"><div class="row"><h2>消息</h2><button id="newsRefresh" class="subtle" data-control>重新整理</button></div>
<p id="nextEvent" class="muted">尚未取得事件</p><details><summary>查看消息</summary><div id="news"></div></details></section>
<p id="operation" class="muted" aria-live="polite"></p><button id="stop" hidden>停止本次操作</button>
</main>
<dialog id="confirmation"><h2 id="confirmTitle"></h2><p id="confirmText"></p><div id="confirmChecks"></div><div id="confirmButtons" class="buttons"></div></dialog>
<dialog id="result"><h2 id="resultTitle">操作結果</h2><p id="resultText"></p><button id="resultClose">確定</button></dialog>
<script src="/app.js" defer></script></body></html>'''

CSS = '''*{box-sizing:border-box}body{margin:0;background:#09090c;color:#e9e7ef;font:14px system-ui,-apple-system,"Microsoft JhengHei",sans-serif;line-height:1.5}main{width:min(100%,460px);margin:auto;padding:16px 16px max(24px,env(safe-area-inset-bottom))}header,.row{display:flex;align-items:center;gap:10px}header{justify-content:space-between;border-bottom:1px solid #2c2c35;padding:0 0 12px;margin-bottom:12px}header strong{font-size:17px}small{color:#a8a1bc;font-size:11px;margin-left:9px}section{margin:14px 0}h2{font-size:14px;font-weight:600;margin:12px 0}p{margin:8px 0}button,input,select{font:inherit;color:inherit;border:1px solid #383743;background:#1c1b23;border-radius:9px;min-height:42px;padding:9px 11px}button{cursor:pointer}button:disabled,input:disabled,select:disabled{opacity:.5;cursor:default}input,select{width:100%;min-width:0}input::placeholder{color:#99929f;opacity:.82}label{display:block;color:#b9b3c5;font-size:12px}label input,label select{font-size:14px;margin-top:5px;color:#f1eff8}.grid,.selects{display:grid;grid-template-columns:1fr 1fr;gap:12px}.selects{grid-template-columns:1.25fr 1fr}.lots{display:flex;justify-content:space-around;text-align:center;padding:18px 0}.lots span{display:block;color:#a8a2b5;font-size:11px}.lots strong{display:block;font-size:25px;font-weight:400;margin-top:3px}.primary{background:#7150dc;border-color:#8b6be9}.row>button{flex:1}.row>h2{flex:1}.subtle{min-height:34px;padding:5px 10px;font-size:12px;flex:none!important}.health{padding:8px 12px;border:1px solid #30333a;border-radius:8px;color:#b8c8bc;font-size:12px}.health.bad{color:#edbb99;border-color:#624733}.muted{font-size:11px;color:#a39cad}.input-wrap{position:relative;display:block}.input-wrap input{padding-right:25px}.warning{position:absolute;right:5px;top:7px;background:#ed526e;border:0;border-radius:50%;min-height:16px;width:16px;height:16px;padding:0;font-size:11px;line-height:16px;color:white}.progress{margin:25px 0 12px}.progress h2{text-align:center;margin-bottom:4px}.progress svg{width:100%;display:block}details{border-top:1px solid #2c2c35;margin-top:15px;padding-top:12px}summary{cursor:pointer;font-size:12px;color:#c0b8ce;padding:3px 0 10px}#more .grid{padding-top:8px}.options{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}.options label{display:flex;align-items:center;gap:5px}.options input{width:16px;height:16px;min-height:16px;margin:0;accent-color:#eee}#newsSection{margin-top:22px}article{font-size:12px;border-bottom:1px solid #29262f;padding:10px 0}article small{display:block;margin:0 0 4px;color:#a59ab8}dialog{background:#111116;color:#eee;border:1px solid #44404f;border-radius:12px;padding:18px;width:min(92vw,430px);max-height:85dvh;overflow:auto}dialog::backdrop{background:#0009}dialog h2{margin-top:0}dialog p{white-space:pre-wrap;font-size:13px;overflow-wrap:anywhere}.buttons{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.buttons button{flex:1;min-width:90px}dialog label{display:flex;gap:8px;margin:10px 0}dialog input[type=checkbox]{width:18px;min-height:18px}#stop{width:100%;border-color:#a35b60;color:#ffc4cb}#pairing label{margin-bottom:12px}[hidden]{display:none!important}:focus-visible{outline:2px solid #ad91ff;outline-offset:3px}@media(max-width:340px){main{padding:10px}.grid{gap:8px}button{padding:8px}header strong{font-size:15px}}'''

JS = r'''"use strict";
const $=id=>document.getElementById(id);
let socket=null,state=null,revision=0,lease="",seen=0,rtt=0,dirty={},draftTimer=null,draftInFlight=null,pending=new Map(),working=false,lastDialog="",newsSignature="",rulerSignature="";
const optionNames={auto_entry:"自動進場",auto_sync:"同步 SL／TP","rule:C2":"來回打","rule:B6":"最小交易日目標","rule:E14":"固定場內止盈"};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function localNotice(message,title="提醒"){ $("resultTitle").textContent=title;$("resultText").textContent=message;if(!$("result").open)$("result").showModal(); }
function connected(){return socket&&socket.readyState===WebSocket.OPEN&&Date.now()-seen<4000;}
function disable(){document.querySelectorAll("[data-control],.warning").forEach(e=>e.disabled=true);}
function selectOptions(element,values,current){const signature=JSON.stringify(values);if(element.dataset.items!==signature){element.replaceChildren(...values.map(value=>{const o=node("option",value);o.value=value;return o;}));element.dataset.items=signature;}element.value=current||"";}
function result(operation){if(!operation)return;if(operation.status==="running"){$("operation").textContent="電腦正在執行，請稍候…";$("stop").hidden=false;return;}
 $("stop").hidden=true;const key=operation.id+":"+operation.status;$("operation").textContent=operation.result.message||"請核對操作結果。";
 if(sessionStorage.getItem("shownOperation")!==key){sessionStorage.setItem("shownOperation",key);if(operation.result.popup_required!==false)localNotice(operation.result.message||"請核對操作結果。",operation.result.title||"操作結果");}}
function send(action,args={}){return new Promise((resolve,reject)=>{if(!connected()){reject(new Error("連線已中斷，本次未送出。"));return;}
 const id=crypto.randomUUID();const timer=setTimeout(()=>{pending.delete(id);reject(new Error("尚未收到回覆，請重連查詢結果；不要重複進場。"));},8000);
 pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({type:"command",id,action,args,revision,lease}));});}
async function flush(){clearTimeout(draftTimer);if(draftInFlight){await draftInFlight;return flush();}if(!Object.keys(dirty).length)return;const outgoing={...dirty};dirty={};
 draftInFlight=send("draft",outgoing);try{await draftInFlight;$("draftStatus").textContent="已同步輸入；按更新或填入兩邊套用。";}
 catch(error){$("draftStatus").textContent="輸入尚未確認同步，請核對電腦最新值。";throw error;}
 finally{draftInFlight=null;}if(Object.keys(dirty).length)return flush();}
async function action(name,args={}){if(working)return;working=true;disable();try{await flush();await send(name,args);}catch(error){localNotice(error.message);}finally{working=false;if(state)render(state);}}
function svg(tag,attrs,text){const e=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function drawRuler(value){const signature=JSON.stringify(value);if(signature===rulerSignature)return;rulerSignature=signature;const el=$("ruler");el.replaceChildren();
 el.hidden=!value;if(!value){$("rulerNote").textContent="等待電腦讀取帳號進度";return;}const markers=value.markers.filter(m=>!["當前餘額","帳號初始餘額"].includes(m[0]));const nums=markers.map(m=>Number(m[1]));const low=Math.min(...nums),high=Math.max(...nums);const pos=n=>24+292*Math.max(0,Math.min(1,(Number(n)-low)/(high-low||1)));
 el.append(svg("line",{x1:24,y1:57,x2:316,y2:57,stroke:"#8b8298","stroke-width":2}));markers.forEach((m,i)=>{const x=pos(m[1]);el.append(svg("circle",{cx:x,cy:57,r:3,fill:"#bdb2cb"}));const labelX=24+292*i/Math.max(1,markers.length-1),anchor=i===0?"start":i===markers.length-1?"end":"middle";el.append(svg("text",{x:labelX,y:15,"text-anchor":anchor,fill:"#b9afc8","font-size":9},m[0]));el.append(svg("text",{x:labelX,y:29,"text-anchor":anchor,fill:"#e2dce9","font-size":9},Number(m[1]).toLocaleString(undefined,{maximumFractionDigits:2})));});
 el.append(svg("circle",{cx:pos(value.balance),cy:57,r:5,fill:"#9770ff",stroke:"#ded0ff"}));const initial=value.markers.find(m=>m[0]==="帳號初始餘額");const labels=[["初始餘額",initial?initial[1]:"—"],["當前餘額",value.balance]];if(initial&&Number(value.balance)<Number(initial[1]))labels.reverse();labels.forEach((m,i)=>{el.append(svg("text",{x:i?255:85,y:87,"text-anchor":"middle",fill:"#b9afc8","font-size":10},m[0]));el.append(svg("text",{x:i?255:85,y:103,"text-anchor":"middle",fill:"#eee","font-size":11},Number(m[1]).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})));});
 $("rulerNote").textContent="場外止損："+value.win_hint+"　場外止盈："+value.loss_hint;}
function showDialog(d){if(!d){if($("confirmation").open)$("confirmation").close();lastDialog="";return;}const signature=JSON.stringify(d);if(signature===lastDialog)return;lastDialog=signature;
 $("confirmTitle").textContent=d.title;$("confirmText").textContent=d.text+(d.desktop_required?"\n這項確認需要在電腦完成。":"");
 $("confirmChecks").replaceChildren(...d.checks.map(check=>{const l=node("label");const input=node("input");input.type="checkbox";input.checked=check.checked;input.disabled=!check.enabled;input.dataset.check=check.id;l.append(input,node("span",check.text));return l;}));
 $("confirmButtons").replaceChildren(...d.buttons.map(button=>{const b=node("button",button.text);b.disabled=!button.enabled;b.onclick=async()=>{const checks={};$("confirmChecks").querySelectorAll("input").forEach(c=>checks[c.dataset.check]=c.checked);$("confirmButtons").querySelectorAll("button").forEach(x=>x.disabled=true);try{await send("dialog",{dialog:d.id,button:button.id,checks});}catch(e){localNotice(e.message);}lastDialog="";};return b;}));
 if(!$("confirmation").open)$("confirmation").showModal();}
function render(s){state=s;const ready=connected()&&!working;$("stageLabel").textContent=s.stage||"尚未讀取階段";selectOptions($("profile"),s.profiles,s.profile);$("profile").disabled=!ready||!s.available;selectOptions($("stage"),s.stages,s.stage);$("stage").disabled=!ready||!s.stage_enabled;
 $("direction").value=s.direction||"BUY";$("direction").disabled=!ready||!s.direction_enabled;
 for(const [key,p]of Object.entries(s.parameters)){const e=document.querySelector('[data-field="'+key+'"]');if(!e)continue;if(!(key in dirty))e.value=p.raw;e.placeholder=p.value||"";e.disabled=!ready||!p.enabled;}
 if(!Object.keys(dirty).length&&!Object.values(s.parameters).some(p=>p.raw))$("draftStatus").textContent="已與電腦同步";
 for(const role of ["internal","external"]){$(role+"Platform").textContent=(role==="internal"?"場內手數":"場外手數")+" · "+s.platforms[role];const raw=Number(s.values[role+"_lot"]);$(role+"Lot").textContent=Number.isFinite(raw)?raw.toFixed(2):"—";}
 for(const [key,active]of Object.entries(s.warnings)){const b=document.querySelector('[data-warning="'+key+'"]');b.hidden=!active;b.disabled=!ready||!s.available;}
 $("fill").disabled=!ready||!s.actions.fill_both;$("update").disabled=!ready||!s.actions.update;$("newsRefresh").disabled=!ready||!s.available;
 document.querySelectorAll("[data-action]").forEach(b=>b.disabled=!ready||!s.actions[b.dataset.action]);
 for(const [key,option]of Object.entries(s.options)){let input=document.querySelector('[data-option="'+key+'"]');if(!input){const label=node("label");input=node("input");input.type="checkbox";input.dataset.option=key;input.onchange=()=>action("option",{key,checked:input.checked});label.append(input,node("span",optionNames[key]||key));$("options").append(label);}input.checked=option.checked;input.disabled=!ready||!option.enabled;}
 drawRuler(s.ruler);const newsKey=JSON.stringify(s.news);if(newsKey!==newsSignature){newsSignature=newsKey;$("news").replaceChildren(...s.news.slice().sort((a,b)=>new Date(b.when)-new Date(a.when)).slice(0,60).map(item=>{const article=node("article");article.append(node("small",(item.scheduled?"排程 · ":"已公布 · ")+new Date(item.when).toLocaleString()+" · "+item.source),node("div",item.title));return article;}));}
 showDialog(s.dialog);health();}
function health(){const online=connected();const text=!online?"連線中斷，請重連後確認結果":state?state.health:"正在取得電腦狀態";$("health").textContent=text+(online&&rtt>1000?" · 連線稍慢":"");$("health").classList.toggle("bad",!online||rtt>1000||(state&&state.health==="無法操作"));if(!online)disable();
 if(state){const next=state.news.filter(e=>e.scheduled&&new Date(e.when)>new Date()).sort((a,b)=>new Date(a.when)-new Date(b.when))[0];if(next){const minutes=Math.ceil((new Date(next.when)-Date.now())/60000);$("nextEvent").textContent="還有 "+Math.floor(minutes/1440)+"天 "+Math.floor(minutes%1440/60)+"時 "+minutes%60+"分 · "+next.title;}else $("nextEvent").textContent=state.news_error||"目前沒有可用的即將公布排程";}}
async function connect(){if(socket){socket.onclose=null;socket.close();}disable();$("connect").textContent="重新連線";seen=0;
 try{const session=await fetch("/api/session",{credentials:"same-origin",cache:"no-store"});if(session.status===401){$("pairing").hidden=false;$("health").textContent="尚未配對";return;}if(!session.ok)throw new Error("連線失敗");}catch(error){$("health").textContent="電腦尚未連上，請確認程式與連線入口。";return;}
 $("pairing").hidden=true;socket=new WebSocket(location.origin.replace(/^http/,"ws")+"/ws");
 socket.onmessage=event=>{seen=Date.now();const message=JSON.parse(event.data);if(message.type==="state"){revision=message.revision;lease=message.lease;$("pairing").hidden=true;render(message.state);result(message.operation);}
 else if(message.type==="result"){const p=pending.get(message.operation.id);if(p){clearTimeout(p.timer);pending.delete(message.operation.id);p.resolve(message);}result(message.operation);}
 else if(message.type==="ack"||message.type==="rejected"){const p=pending.get(message.id);if(p){clearTimeout(p.timer);pending.delete(message.id);message.type==="ack"?p.resolve(message):p.reject(new Error(message.message));}}
 else if(message.type==="pong"){rtt=Date.now()-message.echo;}health();};
 socket.onclose=()=>{seen=0;dirty={};clearTimeout(draftTimer);for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error("連線中斷，重連後先查詢結果；不會自動重送。"));}pending.clear();health();};socket.onerror=()=>{health();};}
$("pair").onclick=async()=>{const b=$("pair");b.disabled=true;try{const response=await fetch("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:$("pairCode").value,name:$("deviceName").value}),credentials:"same-origin"});if(!response.ok)throw new Error(await response.text());$("pairCode").value="";connect();}catch(e){localNotice(e.message);}finally{b.disabled=false;}};
$("connect").onclick=connect;$("update").onclick=()=>action("update");$("fill").onclick=()=>action("fill_both");$("profile").onchange=()=>action("profile",{value:$("profile").value});$("stage").onchange=()=>action("stage",{value:$("stage").value});$("direction").onchange=()=>action("direction",{value:$("direction").value});
document.querySelectorAll("[data-field]").forEach(e=>{e.oninput=()=>{dirty[e.dataset.field]=e.value;$("draftStatus").textContent="正在同步輸入…";clearTimeout(draftTimer);draftTimer=setTimeout(()=>flush().catch(error=>localNotice(error.message)),200);};e.onkeydown=event=>{if(event.key==="Enter")action("update");};});
document.querySelectorAll("[data-action]").forEach(b=>b.onclick=()=>action(b.dataset.action));document.querySelectorAll("[data-warning]").forEach(b=>b.onclick=()=>action("warning",{key:b.dataset.warning}));$("newsRefresh").onclick=()=>action("refresh_news");$("stop").onclick=()=>send("stop").catch(e=>localNotice(e.message));
$("resultClose").onclick=()=>$("result").close();$("confirmation").addEventListener("cancel",event=>event.preventDefault());
setInterval(()=>{health();if(connected())socket.send(JSON.stringify({type:"ping",echo:Date.now()}));},1500);disable();connect();
'''

ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="42" fill="#7150dc"/><path d="M45 70h100m-25-25 25 25-25 25M147 122H47m25-25-25 25 25 25" stroke="white" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'

# Match the desktop's transparent, white-check indicators.
CSS += '''.options input[type=checkbox],#confirmChecks input[type=checkbox]{appearance:none;position:relative;flex-shrink:0;border:1px solid #77717f;border-radius:3px;background:transparent;padding:0;min-height:16px;width:16px;height:16px}.options input[type=checkbox]:checked::after,#confirmChecks input[type=checkbox]:checked::after{content:"";position:absolute;left:3px;top:3px;width:8px;height:4px;border-left:2px solid white;border-bottom:2px solid white;transform:rotate(-45deg)}'''

ASSETS = {
    "/": ("text/html; charset=utf-8", HTML),
    "/app.css": ("text/css; charset=utf-8", CSS),
    "/app.js": ("text/javascript; charset=utf-8", JS),
    "/icon.svg": ("image/svg+xml", ICON),
    "/manifest.webmanifest": ("application/manifest+json", '{"name":"對沖小幫手","short_name":"對沖小幫手","start_url":"/","display":"standalone","background_color":"#09090c","theme_color":"#101015","icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any"}]}'),
}
