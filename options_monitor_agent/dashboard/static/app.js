let ivChart=null,pcrChart=null,historyChart=null;
const API="";

document.addEventListener("DOMContentLoaded",()=>{refreshData();setInterval(refreshData,60000)});

async function fetchJSON(u){try{const r=await fetch(u);if(r.redirected||r.status===401||r.status===403){window.location.href='/login';return{status:'error'};}return await r.json()}catch(e){return{status:"error"}}}

async function refreshData(){
    document.getElementById("last-update").textContent="Last: "+new Date().toLocaleTimeString();
    const[lat,alt,unu,sta,bt]=await Promise.all([fetchJSON("/api/latest"),fetchJSON("/api/alerts?hours=24"),fetchJSON("/api/unusual?days=7"),fetchJSON("/api/stats"),fetchJSON("/api/backtest")]);
    if(lat.status==="ok"){updateTable(lat.data);updateCharts(lat.data);updateSelect(lat.data)}
    if(alt.status==="ok")updateAlerts(alt.data);
    if(unu.status==="ok")updateUnusual(unu.data);
    if(sta.status==="ok")document.getElementById("snapshots-count").textContent=(sta.data.total_snapshots||0).toLocaleString();
    if(bt.status==="ok")updateBacktest(bt.data);
}

function updateTable(data){
    const tb=document.getElementById("tickers-body");
    if(!data||!data.length){tb.innerHTML='<tr><td colspan="8" class="loading">No data. Run a cycle.</td></tr>';return}
    document.getElementById("tickers-count").textContent=data.length;
    tb.innerHTML=data.map(d=>{
        const p=d.pcr_volume||0,pc=p>1.2?"badge-bearish":p<0.8?"badge-bullish":"badge-neutral",pe=p>1.2?"🐻":p<0.8?"🐂":"😐";
        const sc=d.sentiment?.includes("BEAR")?"badge-bearish":d.sentiment?.includes("BULL")?"badge-bullish":"badge-neutral";
        return`<tr onclick="selectTicker('${d.ticker}')" style="cursor:pointer"><td><b>${d.ticker}</b></td><td>${(d.price||0).toLocaleString("en-US",{minimumFractionDigits:2})}</td><td><span class="badge ${pc}">${p.toFixed(2)} ${pe}</span></td><td>${(d.call_iv||0).toFixed(1)}%</td><td>${(d.put_iv||0).toFixed(1)}%</td><td>${(d.iv_skew||0).toFixed(1)}%</td><td><span class="badge ${sc}">${d.sentiment||"-"}</span></td><td class="alert-time">${d.timestamp?new Date(d.timestamp).toLocaleString():"-"}</td></tr>`
    }).join("")
}

function updateCharts(data){
    if(!data||!data.length)return;
    const t=data.map(d=>d.ticker),ci=data.map(d=>d.call_iv||0),pi=data.map(d=>d.put_iv||0),pc=data.map(d=>d.pcr_volume||0);
    const ctx1=document.getElementById("iv-chart").getContext("2d");
    if(ivChart)ivChart.destroy();
    ivChart=new Chart(ctx1,{type:"bar",data:{labels:t,datasets:[{label:"Call IV%",data:ci,backgroundColor:"rgba(16,185,129,0.7)",borderRadius:6},{label:"Put IV%",data:pi,backgroundColor:"rgba(239,68,68,0.7)",borderRadius:6}]},options:{responsive:true,plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}},y:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}}}}});
    const ctx2=document.getElementById("pcr-chart").getContext("2d");
    if(pcrChart)pcrChart.destroy();
    pcrChart=new Chart(ctx2,{type:"bar",data:{labels:t,datasets:[{label:"P/C Ratio",data:pc,backgroundColor:pc.map(p=>p>1.2?"rgba(239,68,68,0.7)":p<0.8?"rgba(16,185,129,0.7)":"rgba(245,158,11,0.7)"),borderRadius:6}]},options:{responsive:true,plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}},y:{ticks:{color:"#94a3b8"},grid:{color:"rgba(45,55,72,0.5)"}}}}});
    const avg=pc.reduce((a,b)=>a+b,0)/pc.length;
    const se=document.getElementById("sentiment-value"),pe=document.getElementById("pcr-value");
    pe.textContent=avg.toFixed(3);
    if(avg>1.2){se.textContent="🐻 BEARISH";se.style.color="#ef4444"}else if(avg<0.8){se.textContent="🐂 BULLISH";se.style.color="#10b981"}else{se.textContent="😐 NEUTRAL";se.style.color="#f59e0b"}
}

function updateAlerts(alerts){
    const c=document.getElementById("alerts-container");document.getElementById("alerts-count").textContent=alerts.length;
    if(!alerts.length){c.innerHTML='<p class="loading">No alerts ✅</p>';return}
    c.innerHTML=alerts.slice(0,20).map(a=>{const i=a.severity==="high"?"🔴":"🟡";return`<div class="alert-item alert-${a.severity||"medium"}">${i} <span class="alert-ticker">[${a.ticker}]</span> ${a.message}<div class="alert-time">${a.type} · ${new Date(a.timestamp).toLocaleString()}</div></div>`}).join("")
}

function updateUnusual(acts){
    const c=document.getElementById("unusual-container");
    if(!acts.length){c.innerHTML='<p class="loading">No unusual activity</p>';return}
    c.innerHTML=acts.slice(0,15).map(u=>`<div class="alert-item alert-medium">${u.type==="CALL"?"📗":"📕"} <span class="alert-ticker">${u.ticker}</span> ${u.type}
$${u.strike?.toFixed(2)} | Vol:${(u.volume||0).toLocaleString()} OI:${(u.oi||0).toLocaleString()} <b>Vol/OI:${u.vol_oi_ratio}x</b> IV:${u.iv}%<div class="alert-time">Exp:${u.expiration} · ${new Date(u.timestamp).toLocaleString()}</div></div>`).join("")
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

function updateSelect(data){const s=document.getElementById("ticker-select"),v=s.value;s.innerHTML='<option value="">Select...</option>';data.forEach(d=>{const o=document.createElement("option");o.value=d.ticker;o.textContent=d.ticker;if(d.ticker===v)o.selected=true;s.appendChild(o)})}

function selectTicker(t){document.getElementById("ticker-select").value=t;loadTickerHistory()}

async function loadTickerHistory(){
    const t=document.getElementById("ticker-select").value;if(!t)return;
    const r=await fetchJSON(`/api/history/${t}?days=30`);if(r.status!=="ok"||!r.data.length)return;
    const d=r.data,l=d.map(x=>new Date(x.timestamp).toLocaleString()),p=d.map(x=>x.price),ci=d.map(x=>x.call_iv),pi=d.map(x=>x.put_iv);
    const ctx=document.getElementById("history-chart").getContext("2d");
    if(historyChart)historyChart.destroy();
    historyChart=new Chart(ctx,{type:"line",data:{labels:l,datasets:[{label:t+" Price",data:p,borderColor:"#06b6d4",yAxisID:"y1",tension:.3,fill:false},{label:"Call IV%",data:ci,borderColor:"#10b981",borderDash:[5,5],yAxisID:"y2",tension:.3},{label:"Put IV%",data:pi,borderColor:"#ef4444",borderDash:[5,5],yAxisID:"y2",tension:.3}]},options:{responsive:true,interaction:{intersect:false,mode:"index"},plugins:{legend:{labels:{color:"#94a3b8"}}},scales:{x:{ticks:{color:"#94a3b8",maxTicksLimit:12},grid:{color:"rgba(45,55,72,0.3)"}},y1:{position:"left",ticks:{color:"#06b6d4"},grid:{color:"rgba(45,55,72,0.3)"},title:{display:true,text:"Price ($)",color:"#06b6d4"}},y2:{position:"right",ticks:{color:"#10b981"},grid:{display:false},title:{display:true,text:"IV (%)",color:"#10b981"}}}}})
}
async function runCycle(){
    const b=document.getElementById("btn-run-cycle");
    b.disabled=true;b.textContent="Running...";
    try{
        await fetch("/api/run-cycle",{method:"POST"});
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
    msgs.innerHTML+=`<div class="chat-msg user">${q.replace(/</g,"&lt;")}</div>`;inp.value="";
    const lid="l"+Date.now();msgs.innerHTML+=`<div class="chat-msg bot" id="${lid}">🤔 Thinking...</div>`;msgs.scrollTop=msgs.scrollHeight;
    try{const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q})});const d=await r.json();document.getElementById(lid).textContent=d.status==="ok"?d.response:"❌ Error"}catch(e){document.getElementById(lid).textContent="❌ Connection error"}
    msgs.scrollTop=msgs.scrollHeight
}

function showNotif(msg,type="info"){
    const c={info:"#3b82f6",success:"#10b981",error:"#ef4444"}[type]||"#3b82f6";
    const n=document.createElement("div");
    n.style.cssText=`position:fixed;top:20px;right:20px;padding:14px 24px;background:${c};color:white;border-radius:10px;font-weight:600;z-index:10000;box-shadow:0 4px 12px rgba(0,0,0,0.3)`;
    n.textContent=msg;document.body.appendChild(n);
    setTimeout(()=>{n.style.opacity="0";n.style.transition="opacity 0.3s";setTimeout(()=>n.remove(),300)},3000)
}
