let ivChart=null,pcrChart=null,historyChart=null;
const API="";
let _csrfToken="";
function _esc(s){const d=document.createElement('div');d.appendChild(document.createTextNode(s));return d.innerHTML;}

// Theme-aware chart colors
function _chartColors(){
    const s=getComputedStyle(document.documentElement);
    return {
        text: s.getPropertyValue('--text-muted').trim()||'#64748B',
        grid: s.getPropertyValue('--border').trim()||'#EDF2F7',
        green: '#22C55E',
        red: '#EF4444',
        yellow: '#F59E0B',
        primary: s.getPropertyValue('--primary-text').trim()||'#7C3AED',
        cyan: '#7C3AED'
    };
}

function _loadCsrf(){
    const meta=document.querySelector('meta[name="csrf-token"]');
    if(meta&&meta.content){_csrfToken=meta.content;return Promise.resolve()}
    return fetch("/api/csrf-token").then(r=>r.json()).then(d=>{_csrfToken=d.csrf_token||""}).catch(()=>{})
}

function _postHeaders(){return{"Content-Type":"application/json","X-CSRF-Token":_csrfToken}}

document.addEventListener("DOMContentLoaded",()=>{_loadCsrf().then?_loadCsrf().then(()=>{checkMarketAndRefresh();setInterval(refreshData,60000)}):(_loadCsrf(),checkMarketAndRefresh(),setInterval(refreshData,60000))});

async function checkMarketAndRefresh(){
    // Fire market-status and refreshData in parallel — don't block rendering
    const msPromise=fetchJSON("/api/market-status");
    refreshData();
    try{
        const ms=await msPromise;
        if(ms.status==="ok"&&ms.market){
            updateMarketBadge(ms.market);
            if(ms.market.should_refresh){
                showNotif("Updating data...","info");
                await fetch("/api/run-cycle",{method:"POST",headers:{"X-CSRF-Token":_csrfToken}});
                let pollCount=0;
                const pollId=setInterval(async()=>{
                    pollCount++;
                    try{
                        const st=await fetchJSON("/api/cycle-status");
                        if(st.status==="ok"&&st.cycle&&!st.cycle.running&&st.cycle.completed_at){
                            clearInterval(pollId);
                            refreshData();
                        }
                    }catch(e){clearInterval(pollId);}
                    if(pollCount>100){clearInterval(pollId);refreshData();}
                },3000);
            }
        }
    }catch(e){}
}

function updateMarketBadge(market){
    let badge=document.getElementById("market-status-badge");
    if(!badge){
        badge=document.createElement("span");
        badge.id="market-status-badge";
        badge.style.cssText="margin-left:12px;padding:4px 10px;border-radius:6px;font-size:0.8rem;font-weight:600;";
        const header=document.getElementById("last-update");
        if(header&&header.parentNode)header.parentNode.insertBefore(badge,header.nextSibling);
    }
    if(market.open){
        let parts=[];
        if(market.es_open)parts.push("ES");
        if(market.us_open)parts.push("US");
        badge.textContent="🟢 "+parts.join("+")+(" Open ("+market.now_cet+" CET)");
        badge.style.background="rgba(34,197,94,0.12)";badge.style.color="#22c55e";
    }else{
        badge.textContent="🔴 Markets Closed"+(market.now_cet?" ("+market.now_cet+" CET)":"");
        badge.style.background="rgba(239,68,68,0.12)";badge.style.color="#ef4444";
    }
    // Show last update time
    if(market.last_update){
        let lu=document.getElementById("data-freshness");
        if(!lu){
            lu=document.createElement("span");
            lu.id="data-freshness";
            lu.style.cssText="margin-left:12px;font-size:0.75rem;color:var(--text-muted,#64748B);";
            badge.parentNode.insertBefore(lu,badge.nextSibling);
        }
        lu.textContent="Data: "+new Date(market.last_update).toLocaleString();
    }
}

async function fetchJSON(u){try{const r=await fetch(u);if(r.redirected||r.status===401||r.status===403){window.location.href='/login';return{status:'error'};}return await r.json()}catch(e){return{status:"error"}}}

async function refreshData(){
    document.getElementById("last-update").textContent="Last: "+new Date().toLocaleTimeString();
    const[lat,alt,unu,sta,bt,wl,qq]=await Promise.all([fetchJSON("/api/latest"),fetchJSON("/api/alerts?hours=24"),fetchJSON("/api/unusual?days=7"),fetchJSON("/api/stats"),fetchJSON("/api/backtest"),fetchJSON("/api/watchlist"),fetchJSON("/api/watchlist-quotes")]);
    const watchlist=wl.status==="ok"?wl.watchlist:[];
    const quotes=qq.status==="ok"?qq.quotes:{};
    if(lat.status==="ok"){updateTable(lat.data,watchlist,quotes);updateCharts(lat.data,watchlist);updateSelect(lat.data,watchlist)}
    if(typeof populateSpikeTickerSelect==="function")populateSpikeTickerSelect(watchlist);
    if(alt.status==="ok")updateAlerts(alt.data);
    if(unu.status==="ok")updateUnusual(unu.data);
    if(sta.status==="ok")document.getElementById("snapshots-count").textContent=(sta.data.total_snapshots||0).toLocaleString();
    if(bt.status==="ok")updateBacktest(bt.data);
    // Load usage limits
    fetchJSON("/api/usage").then(u=>{
        if(u.status==="ok"){
            const b=document.getElementById("usage-badge");
            if(b){
                if(u.superuser){b.textContent="⭐ Superuser";b.style.color="#f59e0b";}
                else{b.textContent=`Queries: ${u.limits.ask_agent.remaining}/${u.limits.ask_agent.max} | Tickers: ${u.limits.watchlist.used}/${u.limits.watchlist.max}`;}
            }
        }
    });
}

function updateTable(data,watchlist,quotes){
    const tb=document.getElementById("tickers-body");
    const dataMap={};
    if(data)data.forEach(d=>{dataMap[d.ticker]=d});
    quotes=quotes||{};
    const allTickers=(watchlist&&watchlist.length)?watchlist:(data?data.map(d=>d.ticker):[]);
    if(!allTickers.length){tb.innerHTML='<tr><td colspan="9" class="loading">No data. Add tickers and run a cycle.</td></tr>';return}
    document.getElementById("tickers-count").textContent=allTickers.length;
    tb.innerHTML=allTickers.map(ticker=>{
        const d=dataMap[ticker];
        const delBtn=`<button onclick="event.stopPropagation();removeTicker('${ticker}',this)" title="Remove ${ticker}" class="btn-delete-ticker">✖</button>`;
        if(d){
            const p=d.pcr_volume||0,pc=p>1.2?"badge-bearish":p<0.8?"badge-bullish":"badge-neutral",pe=p>1.2?"🐻":p<0.8?"🐂":"😐";
            const price=d.price||quotes[ticker]||0;
            return`<tr onclick="selectTicker('${d.ticker}')" style="cursor:pointer"><td><b>${d.ticker}</b></td><td>${price.toLocaleString("en-US",{minimumFractionDigits:2})}</td><td><span class="badge ${pc}">${p.toFixed(2)} ${pe}</span></td><td>${(d.call_iv||0).toFixed(1)}%</td><td>${(d.put_iv||0).toFixed(1)}%</td><td>${(d.iv_skew||0).toFixed(1)}%</td><td>${delBtn}</td></tr>`;
        }
        const qp=quotes[ticker];
        const priceCell=qp?qp.toLocaleString("en-US",{minimumFractionDigits:2}):'<span style="color:var(--text-secondary)">-</span>';
        return`<tr onclick="selectTicker('${ticker}')" style="cursor:pointer"><td><b>${ticker}</b></td><td>${priceCell}</td><td colspan="3" style="color:var(--text-secondary);font-style:italic">Pending — run cycle for full data</td><td>${delBtn}</td></tr>`;
    }).join("")
}

function updateCharts(data,watchlist){
    const dataMap={};
    if(data)data.forEach(d=>{dataMap[d.ticker]=d});
    const allTickers=(watchlist&&watchlist.length)?watchlist:(data?data.map(d=>d.ticker):[]);
    if(!allTickers.length)return;
    const t=[],ci=[],pi=[],pc=[];
    allTickers.forEach(ticker=>{
        const d=dataMap[ticker];
        t.push(ticker);
        ci.push(d?d.call_iv||0:0);
        pi.push(d?d.put_iv||0:0);
        pc.push(d?d.pcr_volume||0:0);
    });
    const cc=_chartColors();
    const ctx1=document.getElementById("iv-chart").getContext("2d");
    if(ivChart)ivChart.destroy();
    ivChart=new Chart(ctx1,{type:"bar",data:{labels:t,datasets:[{label:"Call IV%",data:ci,backgroundColor:"rgba(34,197,94,0.7)",borderRadius:6},{label:"Put IV%",data:pi,backgroundColor:"rgba(239,68,68,0.7)",borderRadius:6}]},options:{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,plugins:{legend:{labels:{color:cc.text}}},scales:{x:{ticks:{color:cc.text,maxRotation:45,minRotation:0},grid:{color:cc.grid}},y:{ticks:{color:cc.text},grid:{color:cc.grid}}}}});
    const ctx2=document.getElementById("pcr-chart").getContext("2d");
    if(pcrChart)pcrChart.destroy();
    pcrChart=new Chart(ctx2,{type:"bar",data:{labels:t,datasets:[{label:"P/C Ratio",data:pc,backgroundColor:pc.map(p=>p>1.2?"rgba(239,68,68,0.7)":p<0.8?"rgba(34,197,94,0.7)":"rgba(245,158,11,0.7)"),borderRadius:6}]},options:{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,plugins:{legend:{labels:{color:cc.text}}},scales:{x:{ticks:{color:cc.text,maxRotation:45,minRotation:0},grid:{color:cc.grid}},y:{ticks:{color:cc.text},grid:{color:cc.grid}}}}});
    const validPc=pc.filter(p=>p>0);
    const avg=validPc.length?validPc.reduce((a,b)=>a+b,0)/validPc.length:0;
    const se=document.getElementById("sentiment-value"),pe=document.getElementById("pcr-value");
    pe.textContent=avg.toFixed(3);
    if(avg>1.2){se.textContent="🐻 BEARISH";se.style.color="#ef4444"}else if(avg<0.8){se.textContent="🐂 BULLISH";se.style.color="#22c55e"}else{se.textContent="😐 NEUTRAL";se.style.color="#f59e0b"}
}

function updateAlerts(alerts){
    const c=document.getElementById("alerts-container");document.getElementById("alerts-count").textContent=alerts.length;
    if(!alerts.length){c.innerHTML='<p class="loading">No alerts ✅</p>';return}
    c.innerHTML=alerts.slice(0,20).map(a=>{const i=a.severity==="high"?"\ud83d\udd34":"\ud83d\udfe1";const sev=_esc(a.severity||"medium");return`<div class="alert-item alert-${sev}">${i} <span class="alert-ticker">[${_esc(a.ticker)}]</span> ${_esc(a.message)}<div class="alert-time">${_esc(a.type)} \u00b7 ${new Date(a.timestamp).toLocaleString()}</div></div>`}).join("")
}

function updateUnusual(acts){
    const c=document.getElementById("unusual-container");
    if(!acts.length){c.innerHTML='<p class="loading">No unusual activity</p>';return}
    c.innerHTML=acts.slice(0,15).map(u=>`<div class="alert-item alert-medium">${u.type==="CALL"?"\ud83d\udcd7":"\ud83d\udcd5"} <span class="alert-ticker">${_esc(u.ticker)}</span> ${_esc(u.type)}
$${u.strike?.toFixed(2)} | Vol:${(u.volume||0).toLocaleString()} OI:${(u.oi||0).toLocaleString()} <b>Vol/OI:${_esc(String(u.vol_oi_ratio))}x</b> IV:${_esc(String(u.iv))}%<div class="alert-time">Exp:${_esc(u.expiration)} \u00b7 ${new Date(u.timestamp).toLocaleString()}</div></div>`).join("")
}

function updateBacktest(sigs){
    const c=document.getElementById("backtest-container");
    if(!sigs.length){c.innerHTML='<p class="loading">No signals yet.</p>';return}
    const ev=sigs.filter(s=>s.outcome==="CORRECT"||s.outcome==="INCORRECT"),co=ev.filter(s=>s.outcome==="CORRECT").length,ac=ev.length?((co/ev.length)*100).toFixed(1):"-";
    document.getElementById("accuracy-value").textContent=ev.length?ac+"%":"-";
    let h=`<div class="table-container"><table><thead><tr><th>Date</th><th>Ticker</th><th>Signal</th><th>Dir</th><th>Price</th><th>+1D</th><th>+3D</th><th>+7D</th><th>Result</th></tr></thead><tbody>`;
    sigs.slice(0,30).forEach(s=>{const oc=s.outcome==="CORRECT"?"badge-bullish":s.outcome==="INCORRECT"?"badge-bearish":"badge-neutral";const fp=p=>p?"$"+p.toFixed(2):"-";h+=`<tr><td class="alert-time">${new Date(s.timestamp).toLocaleDateString()}</td><td><b>${s.ticker}</b></td><td>${s.signal_type}</td><td>${s.direction==="BULLISH"?"🐂":"🐻"} ${s.direction}</td><td>${fp(s.price_at_signal)}</td><td>${fp(s.price_after_1d)}</td><td>${fp(s.price_after_3d)}</td><td>${fp(s.price_after_7d)}</td><td><span class="badge ${oc}">${s.outcome||"PENDING"}</span></td></tr>`});
    h+="</tbody></table></div>";c.innerHTML=h
}

function updateSelect(data,watchlist){
    const s=document.getElementById("ticker-select"),v=s.value;
    s.innerHTML='<option value="">Select...</option>';
    const allTickers=(watchlist&&watchlist.length)?watchlist:(data?data.map(d=>d.ticker):[]);
    allTickers.forEach(t=>{const o=document.createElement("option");o.value=t;o.textContent=t;if(t===v)o.selected=true;s.appendChild(o)})
}

function selectTicker(t){
    document.getElementById("ticker-select").value=t;
    loadTickerHistory();
    // Scroll to the history chart so user sees it
    const hc=document.getElementById("history-chart");
    if(hc)hc.scrollIntoView({behavior:"smooth",block:"center"});
    if(typeof showOptionsChain==="function")showOptionsChain(t);
}

async function loadTickerHistory(){
    const t=document.getElementById("ticker-select").value;if(!t)return;
    const r=await fetchJSON(`/api/history/${t}?days=30`);if(r.status!=="ok"||!r.data.length)return;
    const d=r.data,l=d.map(x=>{const s=Math.round((Date.now()-new Date(x.timestamp))/1e3);if(s<60)return s+"s ago";if(s<3600)return Math.round(s/60)+"min ago";if(s<86400)return Math.round(s/3600)+"h ago";return Math.round(s/86400)+"d ago";}),p=d.map(x=>x.price),ci=d.map(x=>x.call_iv),pi=d.map(x=>x.put_iv);
    // Calculate y-axis ranges with padding for flat data
    const pMin=Math.min(...p),pMax=Math.max(...p),pPad=pMax===pMin?Math.max(pMax*0.05,0.5):0;
    const ivAll=ci.concat(pi).filter(v=>v>0),ivMin=ivAll.length?Math.min(...ivAll):0,ivMax=ivAll.length?Math.max(...ivAll):100,ivPad=ivMax===ivMin?Math.max(ivMax*0.1,1):0;
    const ctx=document.getElementById("history-chart").getContext("2d");
    if(historyChart)historyChart.destroy();
    const hc=_chartColors();
    historyChart=new Chart(ctx,{type:"line",data:{labels:l,datasets:[{label:t+" Price",data:p,borderColor:hc.primary,yAxisID:"y1",tension:.3,fill:false,pointRadius:3,pointBackgroundColor:hc.primary},{label:"Call IV%",data:ci,borderColor:hc.green,borderDash:[5,5],yAxisID:"y2",tension:.3,pointRadius:3,pointBackgroundColor:hc.green},{label:"Put IV%",data:pi,borderColor:hc.red,borderDash:[5,5],yAxisID:"y2",tension:.3,pointRadius:3,pointBackgroundColor:hc.red}]},options:{responsive:true,interaction:{intersect:false,mode:"index"},plugins:{legend:{labels:{color:hc.text}},tooltip:{enabled:true}},scales:{x:{ticks:{color:hc.text,maxTicksLimit:12},grid:{color:hc.grid}},y1:{position:"left",min:pMin-pPad,max:pMax+pPad,ticks:{color:hc.primary},grid:{color:hc.grid},title:{display:true,text:"Price ($)",color:hc.primary}},y2:{position:"right",min:Math.max(0,ivMin-ivPad),max:ivMax+ivPad,ticks:{color:hc.green},grid:{display:false},title:{display:true,text:"IV (%)",color:hc.green}}}}})
}
async function runCycle(){
    const b=document.getElementById("btn-run-cycle");
    b.disabled=true;b.textContent="Running...";
    try{
        await fetch("/api/run-cycle",{method:"POST",headers:{"X-CSRF-Token":_csrfToken}});
        showNotif("Cycle started!","info");
        let pollInterval=setInterval(async()=>{
            try{
                const st=await fetchJSON("/api/cycle-status");
                if(st.status==="ok"&&st.cycle&&!st.cycle.running&&st.cycle.completed_at){
                    clearInterval(pollInterval);
                    b.disabled=false;b.textContent="Run Cycle";
                    if(st.cycle.error){showNotif("Cycle error: "+st.cycle.error,"error");}
                    else{showNotif("Cycle done!","success");refreshData();}
                }
            }catch(e){clearInterval(pollInterval);b.disabled=false;b.textContent="Run Cycle";}
        },3000);
        setTimeout(()=>{clearInterval(pollInterval);if(b.disabled){b.disabled=false;b.textContent="Run Cycle";}},300000);
    }catch(e){
        showNotif("Error starting cycle","error");
        b.disabled=false;b.textContent="Run Cycle";
    }
}

async function sendChat(){
    const inp=document.getElementById("chat-input"),q=inp.value.trim();if(!q)return;
    const msgs=document.getElementById("chat-messages");
    const userDiv=document.createElement('div');userDiv.className='chat-msg user';userDiv.textContent=q;msgs.appendChild(userDiv);inp.value="";
    const lid="l"+Date.now();const botDiv=document.createElement('div');botDiv.className='chat-msg bot';botDiv.id=lid;botDiv.textContent='\ud83e\udd14 Thinking...';msgs.appendChild(botDiv);msgs.scrollTop=msgs.scrollHeight;
    try{const r=await fetch("/api/ask",{method:"POST",headers:_postHeaders(),body:JSON.stringify({question:q})});const d=await r.json();document.getElementById(lid).textContent=d.status==="ok"?d.response:"❌ Error"}catch(e){document.getElementById(lid).textContent="❌ Connection error"}
    msgs.scrollTop=msgs.scrollHeight
}

function showNotif(msg,type="info"){
    const c={info:"#A78BFA",success:"#22C55E",error:"#EF4444"}[type]||"#A78BFA";
    const n=document.createElement("div");
    n.style.cssText=`position:fixed;top:20px;right:20px;padding:14px 24px;background:${c};color:white;border-radius:10px;font-weight:600;z-index:10000;box-shadow:0 4px 12px rgba(0,0,0,0.15);font-family:Inter,system-ui,sans-serif`;
    n.textContent=msg;document.body.appendChild(n);
    setTimeout(()=>{n.style.opacity="0";n.style.transition="opacity 0.3s";setTimeout(()=>n.remove(),300)},3000)
}

// ── Ticker autocomplete search ─────────────────────────────────────────────
let _searchTimeout=null;
function onTickerInput(e){
    const q=e.target.value.trim();
    const dd=document.getElementById("ticker-ac-dropdown");
    if(q.length<1){dd.style.display="none";return}
    clearTimeout(_searchTimeout);
    _searchTimeout=setTimeout(async()=>{
        try{
            const r=await fetchJSON(`/api/search-ticker?q=${encodeURIComponent(q)}`);
            if(r.status==="ok"&&r.results&&r.results.length){
                dd.innerHTML=r.results.map(s=>
                    `<div class="ac-item" onmousedown="pickTicker('${_esc(s.symbol)}')">`+
                    `<span class="ac-symbol">${_esc(s.symbol)}</span>`+
                    `<span class="ac-name">${_esc((s.name||"").substring(0,40))}</span>`+
                    `<span class="ac-price">$${_esc(String(s.price))}</span></div>`
                ).join("");
                dd.style.display="block";
            }else{
                dd.innerHTML='<div class="ac-item ac-empty">No results for "'+_esc(q)+'"</div>';
                dd.style.display="block";
            }
        }catch(ex){dd.style.display="none"}
    },400);
}
function pickTicker(symbol){
    document.getElementById("add-ticker-input").value=symbol;
    document.getElementById("ticker-ac-dropdown").style.display="none";
    addTicker();
}
function hideAcDropdown(){setTimeout(()=>{document.getElementById("ticker-ac-dropdown").style.display="none"},200)}

async function addTicker(){
    const inp=document.getElementById("add-ticker-input");
    const ticker=inp.value.trim().toUpperCase();
    if(!ticker){showNotif("Enter a ticker symbol","error");return}
    inp.disabled=true;
    try{
        const r=await fetch("/api/watchlist",{method:"POST",headers:_postHeaders(),body:JSON.stringify({ticker})});
        const d=await r.json();
        if(d.status==="ok"){
            inp.value="";
            const info=d.ticker_info||{};
            if(info.valid){
                showNotif(`${ticker} added ($${info.price})`,"success");
            }else if(d.message==="Already in watchlist"){
                showNotif(`${ticker} already in watchlist`,"info");
            }else{
                showNotif(`${ticker} added — run a cycle for full data`,"success");
            }
            refreshData();
        }else{
            showNotif(d.message||"Error adding ticker","error");
        }
    }catch(e){showNotif("Connection error","error")}
    inp.disabled=false;
    inp.focus();
}

async function removeTicker(ticker, btn){
    if (btn) {
        twoTapAction(btn, btn.textContent.trim(), function(){ _doRemoveTicker(ticker); });
        return;
    }
    _doRemoveTicker(ticker);
}
async function _doRemoveTicker(ticker){
    try{
        const r=await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`,{method:"DELETE",headers:{"X-CSRF-Token":_csrfToken}});
        const d=await r.json();
        if(d.status==="ok"){
            showNotif(`${ticker} removed`,"success");
            refreshData();
        }else{
            showNotif(d.message||"Error removing ticker","error");
        }
    }catch(e){showNotif("Connection error","error")}
}
