"""Small same-origin mobile page; no CDN, analytics, or cached trading data."""

HTML = '''<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101015"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icon.svg"><link rel="apple-touch-icon" href="/icon-180.png">
<link rel="stylesheet" href="/app.css"><title>對沖小幫手</title></head><body>
<main><header><div><strong>對沖小幫手</strong><small id="stageLabel">手機控制</small></div>
<div class="header-actions"><span id="health" class="health" role="status" aria-live="polite">尚未連線</span><button id="connect" class="subtle">連線</button></div></header>
<section id="installCard" class="install-card" hidden><div class="row"><h2>下次直接從手機桌面開啟</h2><button id="installDismiss" class="subtle" aria-label="稍後加入桌面">×</button></div>
<p id="installHint">建議先加入桌面，再從圖示開啟並完成配對。</p><button id="install" class="subtle">加入手機桌面</button></section>
<section id="pairing" hidden><h2>第一次配對</h2><p>在電腦的「手機連線」取得配對碼。配對後會記住這支手機。</p>
<label>裝置名稱<input id="deviceName" maxlength="32" value="我的手機" autocomplete="off"></label>
<label>配對碼<input id="pairCode" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="one-time-code"></label>
<button id="pair" class="primary">配對並連線</button></section>
<p id="healthDetail" class="muted" hidden></p>
<nav class="workspace-tabs" aria-label="手機頁面"><button id="tradeTab" aria-selected="true">交易操作</button><button id="newsTab" aria-selected="false">消息</button></nav>
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
<section class="progress"><h2>帳號進度</h2><img id="ruler" alt="帳號進度，與電腦使用相同進度尺" width="340" height="186"><p id="rulerNote" class="muted"></p></section>
<details id="more"><summary>其他交易操作</summary><div class="grid">
<button data-action="fill_internal" data-control>填入場內</button><button data-action="fill_external" data-control>填入場外</button>
<button data-action="view_sl_tp" data-control>查看止盈／損</button><button data-action="sync" data-control>同步場外 SL／TP</button>
<label>場內進場點位<input data-field="internal_entry_price" inputmode="decimal" autocomplete="off" data-control></label></div>
<div id="options" class="options"></div></details>
<p id="operation" class="muted" aria-live="polite"></p></section>
<button id="installHelp" class="text-button">加入手機桌面說明</button>
<section id="newsSection" hidden><div class="news-heading"><h2>消息</h2><div class="news-actions">
<button id="pushBell" aria-label="手機通知設定：未啟用" aria-expanded="false" aria-controls="notificationSettings"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg></button>
<button id="newsRefresh" class="subtle" data-control>重整</button></div>
<div id="notificationSettings" role="group" aria-label="手機通知設定" hidden><div class="notification-title">手機通知 <span id="pushStatus">未啟用</span></div>
<p class="muted">提醒突發重大消息、公布前十分鐘及公布當下。電腦程式須保持開啟。</p>
<button id="pushEnable" class="subtle">啟用通知</button><button id="pushDisable" class="subtle" hidden>關閉通知</button>
<button id="pushTest" class="subtle" hidden>測試通知</button><p id="pushHint" class="muted" aria-live="polite"></p></div></div>
<p id="nextEvent" class="news-countdown">尚未取得事件</p>
<nav class="news-subtabs" role="tablist" aria-label="消息類別"><button id="newsUpcomingTab" role="tab" aria-selected="true" aria-controls="newsUpcoming">即將發生</button><button id="newsPublishedTab" role="tab" aria-selected="false" aria-controls="newsPublished">已公布／新聞</button></nav>
<div id="newsUpcoming" role="tabpanel" aria-labelledby="newsUpcomingTab"></div><div id="newsPublished" role="tabpanel" aria-labelledby="newsPublishedTab" hidden></div></section>
<button id="stop" hidden>停止本次操作</button>
</main>
<button id="backTop" aria-label="回到消息頂端" title="回到頂端" hidden>↑</button>
<dialog id="confirmation"><h2 id="confirmTitle"></h2><p id="confirmText"></p><div id="confirmChecks"></div><div id="confirmButtons" class="buttons"></div></dialog>
<dialog id="result"><h2 id="resultTitle">操作結果</h2><p id="resultText"></p><button id="resultClose">確定</button></dialog>
<script src="/app.js" defer></script></body></html>'''

CSS = '''*{box-sizing:border-box}body{margin:0;background:#09090c;color:#e9e7ef;font:14px system-ui,-apple-system,"Microsoft JhengHei",sans-serif;line-height:1.5}main{width:min(100%,460px);margin:auto;padding:16px 16px max(24px,env(safe-area-inset-bottom))}header,.row{display:flex;align-items:center;gap:10px}header{justify-content:space-between;border-bottom:1px solid #2c2c35;padding:0 0 12px;margin-bottom:12px}header strong{font-size:17px}small{color:#a8a1bc;font-size:11px;margin-left:9px}section{margin:14px 0}h2{font-size:14px;font-weight:600;margin:12px 0}p{margin:8px 0}button,input,select{font:inherit;color:inherit;border:1px solid #383743;background:#1c1b23;border-radius:9px;min-height:42px;padding:9px 11px}button{cursor:pointer}button:disabled,input:disabled,select:disabled{opacity:.5;cursor:default}input,select{width:100%;min-width:0}input::placeholder{color:#99929f;opacity:.82}label{display:block;color:#b9b3c5;font-size:12px}label input,label select{font-size:14px;margin-top:5px;color:#f1eff8}.grid,.selects{display:grid;grid-template-columns:1fr 1fr;gap:12px}.selects{grid-template-columns:1.25fr 1fr}.lots{display:flex;justify-content:space-around;text-align:center;padding:18px 0}.lots span{display:block;color:#a8a2b5;font-size:11px}.lots strong{display:block;font-size:25px;font-weight:400;margin-top:3px}.primary{background:#7150dc;border-color:#8b6be9}.row>button{flex:1}.row>h2{flex:1}.subtle{min-height:34px;padding:5px 10px;font-size:12px;flex:none!important}.health{padding:8px 12px;border:1px solid #30333a;border-radius:8px;color:#b8c8bc;font-size:12px}.health.bad{color:#edbb99;border-color:#624733}.muted{font-size:11px;color:#a39cad}.input-wrap{position:relative;display:block}.input-wrap input{padding-right:25px}.warning{position:absolute;right:5px;top:7px;background:#ed526e;border:0;border-radius:50%;min-height:16px;width:16px;height:16px;padding:0;font-size:11px;line-height:16px;color:white}.progress{margin:25px 0 12px}.progress h2{text-align:center;margin-bottom:4px}.progress img{width:100%;height:auto;display:block}details{border-top:1px solid #2c2c35;margin-top:15px;padding-top:12px}summary{cursor:pointer;font-size:12px;color:#c0b8ce;padding:3px 0 10px}#more .grid{padding-top:8px}.options{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}.options label{display:flex;align-items:center;gap:5px}.options input{width:16px;height:16px;min-height:16px;margin:0;accent-color:#eee}#newsSection{margin-top:22px}article{font-size:12px;border-bottom:1px solid #29262f;padding:10px 0}article small{display:block;margin:0 0 4px;color:#a59ab8}dialog{background:#111116;color:#eee;border:1px solid #44404f;border-radius:12px;padding:18px;width:min(92vw,430px);max-height:85dvh;overflow:auto}dialog::backdrop{background:#0009}dialog h2{margin-top:0}dialog p{white-space:pre-wrap;font-size:13px;overflow-wrap:anywhere}.buttons{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.buttons button{flex:1;min-width:90px}dialog label{display:flex;gap:8px;margin:10px 0}dialog input[type=checkbox]{width:18px;min-height:18px}#stop{width:100%;border-color:#a35b60;color:#ffc4cb}#pairing label{margin-bottom:12px}[hidden]{display:none!important}:focus-visible{outline:2px solid #ad91ff;outline-offset:3px}@media(max-width:340px){main{padding:10px}.grid{gap:8px}button{padding:8px}header strong{font-size:15px}}'''

JS = r'''"use strict";
const $=id=>document.getElementById(id);
let socket=null,state=null,revision=0,lease="",seen=0,rtt=0,reconnectTimer=null,connectionAttempt=0,retryDelay=1000,connecting=false,dirty={},draftTimer=null,draftInFlight=null,pending=new Map(),working=false,lastDialog="",newsSignature="",rulerSignature="";
let installPrompt=null;
const standalone=()=>matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
const temporaryHost=()=>location.hostname.endsWith('.trycloudflare.com');
function installCard(){
 let dismissed=false;try{dismissed=localStorage.getItem('installDismissed')==='1';}catch(error){}
 $('installCard').hidden=standalone()||dismissed;
 $('installHelp').hidden=standalone();
 $('installHint').textContent=temporaryHost()?'目前是臨時網址，重開電腦連線後可能失效。固定入口設定好後，再加入桌面。':'建議先加入桌面，再從圖示開啟並配對，之後可直接連線。';
 $('install').textContent=installPrompt?'加入手機桌面':'查看加入方式';
}
async function installApp(){
 if(temporaryHost()){localNotice('目前是臨時網址，重開連線後可能失效。請先在電腦設定固定入口，再加入手機桌面。','先設定固定入口');return;}
 if(installPrompt){const prompt=installPrompt;installPrompt=null;try{await prompt.prompt();await prompt.userChoice;installCard();return;}catch(error){installCard();}}
 const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
 localNotice(ios?'在 Safari 開啟此頁，按「分享」→「加入主畫面」。\n之後從桌面圖示開啟並完成一次配對。':'開啟瀏覽器選單，選「安裝應用程式」或「加入主畫面」。\n之後從桌面圖示開啟並完成一次配對。','加入手機桌面');
}
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;installCard();});
window.addEventListener('appinstalled',()=>{installPrompt=null;installCard();});
$('install').onclick=installApp;$('installHelp').onclick=installApp;
$('installDismiss').onclick=()=>{try{localStorage.setItem('installDismissed','1');}catch(error){}$('installCard').hidden=true;};
let pushConfig=null,pushRegistration=null,pushChecking=false;
const workerReady=('serviceWorker' in navigator&&window.isSecureContext)?navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(()=>navigator.serviceWorker.ready):Promise.resolve(null);
workerReady.catch(()=>{});
function pushSupport(){const ios=/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);return window.isSecureContext&&'PushManager' in window&&'Notification' in window&&(!ios||standalone());}
function pushDisplay(enabled,hint=''){$('pushStatus').textContent=enabled?'已啟用':'未啟用';$('pushEnable').hidden=enabled;$('pushDisable').hidden=!enabled;$('pushTest').hidden=!enabled;$('pushHint').textContent=hint;$('pushBell').classList.toggle('enabled',enabled);$('pushBell').setAttribute('aria-label','手機通知設定：'+(enabled?'已啟用':'未啟用'));}
async function pushRequest(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!response.ok)throw new Error(await response.text());return response.json();}
async function preparePush(){if(pushChecking)return;pushChecking=true;try{
 if(!pushSupport()){pushDisplay(false,'iPhone 請先加入主畫面，再從圖示開啟以啟用通知。');return;}
 pushConfig=await pushRequest('/api/notifications');pushRegistration=await workerReady;
 const sub=pushRegistration&&await pushRegistration.pushManager.getSubscription();
 pushDisplay(!!(pushConfig.enabled&&sub&&Notification.permission==='granted'),Notification.permission==='denied'?'通知已被系統封鎖，請到手機設定開啟。':'');
 }catch(error){pushDisplay(false,error.message);}finally{pushChecking=false;}}
$('pushEnable').onclick=async()=>{if(!pushSupport()){pushDisplay(false,'請先加入手機主畫面，再從圖示開啟。');return;}
 const button=$('pushEnable');button.disabled=true;
 try{const permission=await Notification.requestPermission();if(permission!=='granted')throw new Error('尚未允許通知，可稍後再開啟。');
 if(!pushConfig)pushConfig=await pushRequest('/api/notifications');pushRegistration=await workerReady;if(!pushRegistration)throw new Error('通知元件尚未就緒，請重新整理。');
 const key=Uint8Array.from(atob(pushConfig.publicKey.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
 let sub=await pushRegistration.pushManager.getSubscription();
 if(sub&&JSON.stringify(Array.from(new Uint8Array(sub.options.applicationServerKey||[])))!==JSON.stringify(Array.from(key))){await sub.unsubscribe();sub=null;}
 if(!sub)sub=await pushRegistration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
 await pushRequest('/api/notifications',{subscription:sub.toJSON()});pushDisplay(true,'已開啟；可按「測試通知」確認手機是否收到。');
 }catch(error){pushDisplay(false,error.message);}finally{button.disabled=false;}};
$('pushDisable').onclick=async()=>{const button=$('pushDisable');button.disabled=true;try{await pushRequest('/api/notifications',{subscription:null});if(pushRegistration){const sub=await pushRegistration.pushManager.getSubscription();if(sub)await sub.unsubscribe();}pushDisplay(false);}catch(error){$('pushHint').textContent=error.message;}finally{button.disabled=false;}};
let pushTestUntil=0,pushTestSending=false;
function testCooldown(){const seconds=Math.max(0,Math.ceil((pushTestUntil-Date.now())/1000));$('pushTest').disabled=pushTestSending||seconds>0;$('pushTest').textContent=pushTestSending?'發送中…':seconds?'測試通知（'+seconds+'秒）':'測試通知';}
$('pushTest').onclick=async()=>{if(pushTestSending||Date.now()<pushTestUntil)return;pushTestSending=true;testCooldown();try{const result=await pushRequest('/api/notifications/test',{});pushTestUntil=Date.now()+(result.cooldown||10)*1000;$('pushHint').textContent=result.queued===false?'請等按鈕倒數結束後再測試。':'已送出測試請求；手機顯示時間依系統與網路而定。';}catch(error){$('pushHint').textContent=error.message;}finally{pushTestSending=false;testCooldown();}};
installCard();
const optionNames={auto_entry:"自動進場",auto_sync:"同步 SL／TP","rule:C2":"來回打","rule:B6":"最小交易日目標","rule:E14":"固定場內止盈"};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function localNotice(message,title="提醒"){ $("resultTitle").textContent=title;$("resultText").textContent=message;if(!$("result").open)$("result").showModal(); }
function connected(){return socket&&socket.readyState===WebSocket.OPEN&&Date.now()-seen<4000;}
function disable(){document.querySelectorAll("[data-control],.warning").forEach(e=>e.disabled=true);}
function selectOptions(element,values,current){const signature=JSON.stringify(values);if(element.dataset.items!==signature){element.replaceChildren(...values.map(value=>{const o=node("option",value);o.value=value;return o;}));element.dataset.items=signature;}element.value=current||"";}
function result(operation){if(!operation)return;if(operation.status==="running"){$("operation").textContent="電腦正在執行，請稍候…";$("stop").hidden=false;return;}
 $("stop").hidden=true;const key=operation.id+":"+operation.status;$("operation").textContent=operation.result.message||"請核對操作結果。";
 if(sessionStorage.getItem("shownOperation")!==key){sessionStorage.setItem("shownOperation",key);if(operation.status!=="completed"&&operation.result.popup_required!==false)localNotice(operation.result.message||"請核對操作結果。",operation.result.title||"操作結果");}}
function send(action,args={}){return new Promise((resolve,reject)=>{if(!connected()){reject(new Error("連線已中斷，本次未送出。"));return;}
 const id=crypto.randomUUID();const timer=setTimeout(()=>{pending.delete(id);reject(new Error("尚未收到回覆，請重連查詢結果；不要重複進場。"));},8000);
 pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({type:"command",id,action,args,revision,lease}));});}
async function flush(){clearTimeout(draftTimer);if(draftInFlight){await draftInFlight;return flush();}if(!Object.keys(dirty).length)return;const outgoing={...dirty};dirty={};
 draftInFlight=send("draft",outgoing);try{await draftInFlight;$("draftStatus").textContent="已同步輸入；按更新或填入兩邊套用。";}
 catch(error){$("draftStatus").textContent="輸入尚未確認同步，請核對電腦最新值。";throw error;}
 finally{draftInFlight=null;}if(Object.keys(dirty).length)return flush();}
async function action(name,args={}){if(working)return;working=true;disable();try{await flush();await send(name,args);}catch(error){localNotice(error.message);}finally{working=false;if(state)render(state);}}
function drawRuler(value,version){const el=$("ruler");el.hidden=!value;
 if(!value){$("rulerNote").textContent="等待電腦讀取帳號進度";return;}
 if(version&&version!==rulerSignature){rulerSignature=version;el.src="/api/ruler.png?v="+version;}
 $("rulerNote").textContent="";}
const newsOpen=new Set();
function showNews(items){const now=Date.now();const upcoming=items.filter(e=>e.scheduled&&new Date(e.when)>now).sort((a,b)=>new Date(a.when)-new Date(b.when));
 const published=items.filter(e=>new Date(e.when)<=now).sort((a,b)=>new Date(b.when)-new Date(a.when));
 const identities=new Set(items.map(item=>JSON.stringify([item.when,item.source,item.original||item.title])));for(const key of newsOpen)if(!identities.has(key))newsOpen.delete(key);
 for(const [id,rows] of [["newsUpcoming",upcoming],["newsPublished",published]]){$(id).replaceChildren(...rows.map(item=>{
 const article=node('article');article.style.setProperty('--news-color',/^#[0-9a-f]{6}$/i.test(item.color||'')?item.color:'#aaa5b7');
 const detail=node('details'),summary=node('summary'),identity=JSON.stringify([item.when,item.source,item.original||item.title]);detail.open=newsOpen.has(identity);detail.ontoggle=()=>{if(detail.open)newsOpen.add(identity);else newsOpen.delete(identity);};
 const date=new Date(item.when),time=node('div',undefined,'news-time'),content=node('div',undefined,'news-content');
 time.append(node('small',date.toLocaleDateString('zh-TW',{month:'2-digit',day:'2-digit'})),node('small',date.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit',hour12:false})),node('small',date>now?'即將發生':'已公布'));content.append(node('span',item.category||'相關消息','news-category'));summary.append(time,content);
 const title=node('div',undefined,'news-title');if(Array.isArray(item.parts)){for(const [text,emphasis] of item.parts)title.append(node('span',text,emphasis?'news-keyword':undefined));}else title.textContent=item.title;content.append(title);
 const values=item.values||{},figures=node('div',undefined,'news-figures');for(const [key,label] of [['actual','公布值'],['forecast','預期'],['previous','前值']]){if(typeof values[key]==='string'&&values[key]){const field=node('div');field.append(node('span',label),node('strong',values[key]));figures.append(field);}}if(figures.childElementCount)content.append(figures);
 if(item.scheduled&&new Date(item.when)<=now&&!values.actual)content.append(node('p','來源尚未提供公布值','muted'));content.append(node('small',item.source));
 const body=node('div',undefined,'news-detail');body.append(node('p',item.details||'來源未提供更多內容'));if(item.original&&item.original!==item.title)body.append(node('p','原文：'+item.original,'muted'));
 detail.append(summary,body);article.append(detail);return article;
 }));if(!rows.length)$(id).append(node('p',id==='newsUpcoming'?'目前沒有載入近期排程':'目前沒有載入相關事件','muted'));}}
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
 drawRuler(s.ruler,s.ruler_revision);refreshNews();
 showDialog(s.dialog);health();}
function health(){const online=connected();const text=!online?(connecting?"正在連線…":!$("pairing").hidden?"首次使用或配對已失效，請輸入配對碼":"連線中斷，正在重新連線…"):state?state.health:"正在取得電腦狀態";const bad=!online||rtt>1000||!state||state.health!=="正常";$("health").textContent=!online?(connecting?"連線中":"未連線"):!bad?"正常":state&&state.busy?"操作中":"需留意";$("health").title=text;$("health").classList.toggle("bad",bad);$("healthDetail").textContent=text+(online&&rtt>1000?" · 連線稍慢":"");$("healthDetail").hidden=!bad;if(!online)disable();
 refreshNews();updateCountdown();}
function updateCountdown(){if(!state)return;const next=state.news.filter(e=>e.scheduled&&new Date(e.when)>Date.now()).sort((a,b)=>new Date(a.when)-new Date(b.when))[0];if(next){const seconds=Math.max(0,Math.ceil((new Date(next.when)-Date.now())/1000)),hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);const text='再過 '+(hours?hours+' 小時 ':'')+(hours||minutes?minutes+' 分 ':'')+seconds%60+' 秒 · '+next.title;$('nextEvent').textContent=text;$('nextEvent').title=text;}else $('nextEvent').textContent=state.news_error||'目前沒有可用的即將公布排程';}
setInterval(()=>{updateCountdown();testCooldown();},1000);
function refreshNews(){if(!state)return;const key=JSON.stringify(state.news)+':'+state.news.filter(item=>new Date(item.when)<=Date.now()).length;if(key!==newsSignature){newsSignature=key;showNews(state.news);}}
function retryConnection(){if(reconnectTimer||!$("pairing").hidden||document.hidden)return;health();
 reconnectTimer=setTimeout(()=>{reconnectTimer=null;connect();},retryDelay);retryDelay=Math.min(10000,retryDelay*2);}
async function connect(){const attempt=++connectionAttempt;clearTimeout(reconnectTimer);reconnectTimer=null;connecting=true;
 if(socket){socket.onclose=null;socket.onmessage=null;socket.close();socket=null;}disable();$("connect").textContent="重新連線";seen=0;health();
 const abort=new AbortController();const timeout=setTimeout(()=>abort.abort(),8000);
 try{const session=await fetch("/api/session",{credentials:"same-origin",cache:"no-store",signal:abort.signal});if(attempt!==connectionAttempt)return;
 if(session.status===401){$("pairing").hidden=false;connecting=false;health();return;}if(!session.ok)throw new Error("連線失敗");}
 catch(error){if(attempt===connectionAttempt){connecting=false;retryConnection();}return;}finally{clearTimeout(timeout);}
 $("pairing").hidden=true;preparePush();const current=new WebSocket(location.origin.replace(/^http/,"ws")+"/ws");socket=current;
 const handshake=setTimeout(()=>{if(socket===current&&!connected())current.close();},8000);
 current.onmessage=event=>{if(socket!==current)return;clearTimeout(handshake);connecting=false;retryDelay=1000;seen=Date.now();const message=JSON.parse(event.data);if(message.type==="state"){revision=message.revision;lease=message.lease;$("pairing").hidden=true;render(message.state);result(message.operation);}
 else if(message.type==="result"){const p=pending.get(message.operation.id);if(p){clearTimeout(p.timer);pending.delete(message.operation.id);p.resolve(message);}result(message.operation);}
 else if(message.type==="ack"||message.type==="rejected"){const p=pending.get(message.id);if(p){clearTimeout(p.timer);pending.delete(message.id);message.type==="ack"?p.resolve(message):p.reject(new Error(message.message));}}
 else if(message.type==="pong"){rtt=Date.now()-message.echo;}health();};
 current.onclose=()=>{clearTimeout(handshake);if(socket!==current)return;socket=null;connecting=false;seen=0;dirty={};clearTimeout(draftTimer);for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error("連線中斷，重連後先查詢結果；不會自動重送。"));}pending.clear();health();retryConnection();};current.onerror=()=>current.close();}
$("pair").onclick=async()=>{const b=$("pair");b.disabled=true;try{const response=await fetch("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:$("pairCode").value,name:$("deviceName").value}),credentials:"same-origin"});if(!response.ok)throw new Error(await response.text());$("pairCode").value="";connect();}catch(e){localNotice(e.message);}finally{b.disabled=false;}};
$("connect").onclick=connect;$("update").onclick=()=>action("update");$("fill").onclick=()=>action("fill_both");$("profile").onchange=()=>action("profile",{value:$("profile").value});$("stage").onchange=()=>action("stage",{value:$("stage").value});$("direction").onchange=()=>action("direction",{value:$("direction").value});
document.querySelectorAll("[data-field]").forEach(e=>{e.oninput=()=>{dirty[e.dataset.field]=e.value;$("draftStatus").textContent="正在同步輸入…";clearTimeout(draftTimer);draftTimer=setTimeout(()=>flush().catch(error=>localNotice(error.message)),200);};e.onkeydown=event=>{if(event.key==="Enter")action("update");};});
document.querySelectorAll("[data-action]").forEach(b=>b.onclick=()=>action(b.dataset.action));document.querySelectorAll("[data-warning]").forEach(b=>b.onclick=()=>action("warning",{key:b.dataset.warning}));$("newsRefresh").onclick=()=>action("refresh_news");$("stop").onclick=()=>send("stop").catch(e=>localNotice(e.message));
$("resultClose").onclick=()=>$("result").close();$("confirmation").addEventListener("cancel",event=>event.preventDefault());
function updateBackTop(){$('backTop').hidden=$('newsSection').hidden||window.scrollY<240;}
function workspace(news){$("trade").hidden=news;$("newsSection").hidden=!news;$("tradeTab").setAttribute("aria-selected",String(!news));$("newsTab").setAttribute("aria-selected",String(news));updateBackTop();}
$("tradeTab").onclick=()=>workspace(false);$("newsTab").onclick=()=>workspace(true);
function newsWorkspace(published){$('newsUpcoming').hidden=published;$('newsPublished').hidden=!published;$('newsUpcomingTab').setAttribute('aria-selected',String(!published));$('newsPublishedTab').setAttribute('aria-selected',String(published));updateBackTop();}
$('newsUpcomingTab').onclick=()=>newsWorkspace(false);$('newsPublishedTab').onclick=()=>newsWorkspace(true);
$('pushBell').onclick=()=>{const open=$('notificationSettings').hidden;$('notificationSettings').hidden=!open;$('pushBell').setAttribute('aria-expanded',String(open));};
document.addEventListener('click',event=>{if(!$('notificationSettings').contains(event.target)&&!$('pushBell').contains(event.target)){$('notificationSettings').hidden=true;$('pushBell').setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('notificationSettings').hidden=true;$('pushBell').setAttribute('aria-expanded','false');}});
window.addEventListener('scroll',updateBackTop,{passive:true});
$('backTop').onclick=()=>window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
if(location.hash==='#news')workspace(true);
if('serviceWorker' in navigator)navigator.serviceWorker.addEventListener('message',event=>{if(event.data&&event.data.type==='open-news')workspace(true);});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!connected())connect();});window.addEventListener("online",()=>{if(!connected())connect();});window.addEventListener("pageshow",e=>{if(e.persisted&&!connected())connect();});
setInterval(()=>{health();if(connected())socket.send(JSON.stringify({type:"ping",echo:Date.now()}));else if(socket&&!connecting){socket.close();}else if(!connecting)retryConnection();},1500);disable();connect();
'''

ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect width="192" height="192" rx="42" fill="#7150dc"/><path d="M45 70h100m-25-25 25 25-25 25M147 122H47m25-25-25 25 25 25" stroke="white" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'

# Match the desktop's transparent, white-check indicators.
CSS += '''.options input[type=checkbox],#confirmChecks input[type=checkbox]{appearance:none;position:relative;flex-shrink:0;border:1px solid #77717f;border-radius:3px;background:transparent;padding:0;min-height:16px;width:16px;height:16px}.options input[type=checkbox]:checked::after,#confirmChecks input[type=checkbox]:checked::after{content:"";position:absolute;left:3px;top:3px;width:8px;height:4px;border-left:2px solid white;border-bottom:2px solid white;transform:rotate(-45deg)}'''

CSS += '.workspace-tabs{display:flex;gap:24px;border-bottom:1px solid #34303d;margin-top:18px}.workspace-tabs button{border:0;border-radius:0;background:transparent;color:#aaa2b7;padding:10px 4px;min-height:42px}.workspace-tabs button[aria-selected=true]{color:#fff;border-bottom:2px solid #a68be8}#newsSection h3{font-size:12px;color:#c1afd9;border-left:2px solid #9b80dc;padding-left:8px;margin-top:22px}article details{margin-top:5px;padding-top:4px}article details p{font-size:12px;color:#beb5cc}article details summary{padding-bottom:2px}'
CSS += '''
.news-heading{position:relative;display:flex;align-items:center;justify-content:space-between;gap:10px}
.news-actions{display:flex;align-items:center;gap:8px}.news-heading h2{margin:6px 0}
#pushBell{position:relative;min-height:30px;width:30px;padding:5px;background:transparent;border:0;color:#aaa2b7}
#pushBell svg{vertical-align:middle}#pushBell.enabled::after{content:"";position:absolute;right:4px;top:4px;width:5px;height:5px;background:#82c69e;border-radius:50%}
#pushBell[aria-expanded=true]{border-color:#a58bdc;background:#282330}
#notificationSettings{position:absolute;right:0;top:calc(100% + 8px);width:min(290px,calc(100vw - 40px));z-index:20;padding:14px;background:#15131b;border:1px solid #443b52;border-radius:10px;box-shadow:0 10px 30px #0007}
.notification-title{display:flex;justify-content:space-between;font-size:13px}#pushStatus{color:#a9a0ba;font-size:11px}
.news-countdown{background:#17141e;border:1px solid #38313f;border-radius:8px;padding:10px 12px;margin:14px 0 16px;font-size:12px;color:#c9bed9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.news-subtabs{display:flex;gap:22px;border-bottom:1px solid #34303d}.news-subtabs button{background:transparent;border:0;border-radius:0;color:#aaa2b7;padding:7px 0 10px;min-height:36px;font-size:12px}
.news-subtabs button[aria-selected=true]{color:#f2edf9;border-bottom:2px solid #aa91ee}
#newsUpcoming,#newsPublished{padding-top:14px}article{border:0;border-left:2px solid var(--news-color,#aaa5b7);padding:0;margin:0 0 8px;-webkit-user-select:none;user-select:none}
article details{padding:0;margin:0;border:0}article summary{position:relative;display:grid;grid-template-columns:52px minmax(0,1fr);gap:8px;list-style:none;padding:5px 22px 5px 8px;color:#ece8f3}
.news-time small{display:block;white-space:nowrap;margin-bottom:2px}.news-content{min-width:0}.news-content>small{display:block;margin-top:5px}
article summary::-webkit-details-marker{display:none}article summary::after{content:"";position:absolute;right:10px;top:33px;width:5px;height:5px;border-right:1px solid #a49aae;border-bottom:1px solid #a49aae;transform:rotate(45deg)}
article details[open] summary::after{transform:rotate(225deg)}article small{margin-bottom:3px;font-size:11px;color:#aaa1b8}
.news-category,.news-keyword{color:var(--news-color,#aaa5b7)}.news-category{font-size:11px}.news-title{margin-top:4px;font-size:12px;font-weight:400}
.news-figures{display:flex;gap:12px;margin-top:8px}.news-figures>div{flex:1;min-width:0;border-left:1px solid #37313f;padding-left:10px}.news-figures>div:first-child{border:0;padding-left:0}
.news-figures span{display:block;font-size:11px;color:#aaa1b8}.news-figures strong{display:block;font-size:14px;font-weight:400;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.news-detail{margin:0 10px 0 68px;padding:5px 0 8px;overflow-wrap:anywhere}.news-detail p{margin:4px 0}
@media(pointer:coarse){#pushBell{width:44px;min-height:44px}.news-subtabs button{min-height:44px}}
'''

CSS += '''html{color-scheme:dark;scrollbar-width:thin;scrollbar-color:#514b5a #09090c}body{overflow-wrap:anywhere}.selects{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.row>#update{flex:0 0 74px;min-height:36px;font-size:12px;padding:6px 10px}.row>#fill{flex:1;min-height:44px}.install-card{background:#131218;border:1px solid #34303d;border-radius:10px;padding:12px}.install-card h2{font-size:12px;margin:0}.install-card p{font-size:12px;color:#b8b0c3}.text-button{display:block;margin:12px 0 0;padding:0;min-height:30px;background:transparent;border:0;color:#aaa1b9;font-size:11px}::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:#09090c}::-webkit-scrollbar-thumb{background:#514b5a;border-radius:6px}'''

CSS += '''header{flex-wrap:wrap}.header-actions{display:flex;align-items:center;gap:8px}.health{display:inline-flex;align-items:center;gap:5px;min-height:32px;padding:4px 8px;font-size:11px;white-space:nowrap}.health::before{content:"";width:6px;height:6px;border-radius:50%;background:#69c68c;flex:none}.health.bad::before{background:#e4ac70}.header-actions #connect{min-height:32px;font-size:11px}.row>#update{min-height:44px;align-self:stretch}#backTop{position:fixed;right:max(16px,env(safe-area-inset-right));bottom:max(16px,env(safe-area-inset-bottom));width:42px;height:42px;padding:0;background:#24202e;border:1px solid #78688f;border-radius:50%;font-size:23px;line-height:1;box-shadow:0 3px 12px #0008;z-index:3}#healthDetail{margin:8px 0}'''


def _icon_png(size):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    QSvgRenderer(ICON.encode('utf-8')).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)

ASSETS = {
    "/": ("text/html; charset=utf-8", HTML),
    "/app.css": ("text/css; charset=utf-8", CSS),
    "/app.js": ("text/javascript; charset=utf-8", JS),
    "/icon.svg": ("image/svg+xml", ICON),
    "/icon-180.png": ("image/png", _icon_png(180)),
    "/icon-192.png": ("image/png", _icon_png(192)),
    "/icon-512.png": ("image/png", _icon_png(512)),
    # No fetch handler/cache, credentials or pending trading command in this worker.
    "/sw.js": ("text/javascript; charset=utf-8", '''self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('push',event=>{let data={};try{data=event.data.json();if(!data||typeof data!=='object')data={};}catch(error){}
const stale=typeof data.expires==='number'&&data.expires*1000<Date.now();
event.waitUntil(self.registration.showNotification(String(data.title||'對沖小幫手').slice(0,80),{
body:stale?'較早的提醒，請開啟消息查看最新狀況。':String(data.body||'有新的消息，請開啟查看。').slice(0,300),
icon:'/icon-192.png',badge:'/icon-192.png',tag:String(data.tag||'helper-news').slice(0,80),data:{page:'news'}}));});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil((async()=>{
const pages=await clients.matchAll({type:'window',includeUncontrolled:true});
const page=pages.find(p=>new URL(p.url).origin===self.location.origin);
if(page){await page.focus();page.postMessage({type:'open-news'});}else await clients.openWindow('/#news');})());});'''),
    "/manifest.webmanifest": ("application/manifest+json", '{"id":"/","name":"對沖小幫手","short_name":"對沖小幫手","start_url":"/","scope":"/","display":"standalone","background_color":"#09090c","theme_color":"#101015","icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"},{"src":"/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any"}]}'),
}
