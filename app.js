var V=[],U=[],F=[],busy=false,totalCount=0,sid=null,resultsIndex=0;
var API_BASE=window.location.hostname.endsWith('vercel.app')?'':(window.location.hostname==='strongshuai.github.io'?'https://proxy-checker-nu.vercel.app':window.location.origin);
var isRemote=window.location.hostname.endsWith('vercel.app')||window.location.hostname==='strongshuai.github.io';
var proxyInput=document.getElementById("proxyInput");
var checkBtn=document.getElementById("checkBtn");
var stopBtn=document.getElementById("stopBtn");
var prog=document.getElementById("progress");
var progBar=document.getElementById("progressBar");
var validList=document.getElementById("validList");
var failList=document.getElementById("failList");
var vCount=document.getElementById("vCount");
var fCount=document.getElementById("fCount");
var sTotal=document.getElementById("sTotal");
var sValid=document.getElementById("sValid");
var sUnstable=document.getElementById("sUnstable");
var sInvalid=document.getElementById("sInvalid");
var sRate=document.getElementById("sRate");
var sCfBypass=document.getElementById("sCfBypass");
var sRegReady=document.getElementById("sRegReady");
var statusText=document.getElementById("statusText");
var proxyCountBadge=document.getElementById("proxyCountBadge");

// ============================================================
// [1] Real-time proxy count in textarea
// ============================================================
function updateProxyCount(){
  var lines=parseLines(proxyInput.value);
  var n=lines.length;
  proxyCountBadge.textContent=n+' 个代理';
}
proxyInput.addEventListener('input',updateProxyCount);
updateProxyCount();

// Textarea drag-to-resize
(function(){
  var handle=proxyInput.parentElement;
  var startY,startH;
  handle.addEventListener('mousedown',function(e){
    // Only trigger on the bottom 8px of the handle area
    var rect=handle.getBoundingClientRect();
    if(e.clientY<rect.bottom-8)return;
    e.preventDefault();
    startY=e.clientY;
    startH=proxyInput.offsetHeight;
    document.addEventListener('mousemove',onMove);
    document.addEventListener('mouseup',onUp);
    document.body.style.cursor='ns-resize';
    document.body.style.userSelect='none';
  });
  function onMove(ev){
    var h=startH+(ev.clientY-startY);
    if(h<80)h=80;if(h>600)h=600;
    proxyInput.style.height=h+'px';
  }
  function onUp(){
    document.removeEventListener('mousemove',onMove);
    document.removeEventListener('mouseup',onUp);
    document.body.style.cursor='';
    document.body.style.userSelect='';
  }
})();

function copyText(text){
  var ta=document.createElement("textarea");
  ta.value=text;
  ta.style.cssText="position:fixed;left:-9999px;top:-9999px";
  document.body.appendChild(ta);
  ta.select();
  try{document.execCommand("copy");toast("已复制")}catch(e){toast("复制失败")}
  document.body.removeChild(ta);
}
function toast(m){var t=document.getElementById("toast");t.textContent=m;t.classList.add("show");setTimeout(function(){t.classList.remove("show")},2500)}
function esc(s){var d=document.createElement("div");d.textContent=s;return d.innerHTML}
function parseLines(t){return t.split("\n").map(function(l){return l.trim()}).filter(function(l){return l.length>0 && !l.startsWith("#")})}
function dedup(){
  var lines=parseLines(proxyInput.value);
  var seen={};var unique=[];
  lines.forEach(function(l){var k=l.toLowerCase();if(!seen[k]){seen[k]=true;unique.push(l)}});
  proxyInput.value=unique.join("\n");
  updateProxyCount();
  toast("去重: "+lines.length+" -> "+unique.length+" 个");
}
function post(url,data,cb){
  var fullUrl=API_BASE+url;
  var xhr=new XMLHttpRequest();xhr.open("POST",fullUrl,true);
  xhr.setRequestHeader("Content-Type","application/json");
  xhr.onload=function(){try{cb(null,JSON.parse(xhr.responseText))}catch(e){cb("解析失败")}};
  xhr.onerror=function(){cb("网络错误")};
  xhr.send(JSON.stringify(data));
}

// Check capabilities on load
function checkCapabilities(){
  post("/api/capabilities",{},function(err,res){
    if(err) return;
    var badge=document.getElementById("capBadge");
    if(res && res.deep_check){
      badge.className="cap-badge cap-ok";
      badge.innerHTML="&#9989; Deep Check可用";
    }else{
      badge.className="cap-badge cap-no";
      badge.innerHTML="&#9888; Deep Check不可用";
    }
    badge.style.display="inline-flex";
  });
}

// GitHub Pages: show backend config panel
if(isRemote && !window.location.hostname.endsWith('vercel.app')){
  document.getElementById("backendConfig").style.display="block";
  var saved=localStorage.getItem("proxy_checker_backend");
  if(saved){
    API_BASE=saved.replace(/\/$/,"");
    document.getElementById("backendUrl").value=API_BASE;
    checkCapabilities();
  }
}

function connectBackend(){
  var url=document.getElementById("backendUrl").value.trim().replace(/\/$/,"");
  if(!url){toast("请输入后端地址");return}
  API_BASE=url;
  localStorage.setItem("proxy_checker_backend",url);
  document.getElementById("connStatus").textContent="连接中...";
  document.getElementById("connStatus").style.color="#eab308";
  post("/api/capabilities",{},function(err,res){
    if(err){
      document.getElementById("connStatus").textContent="连接失败";
      document.getElementById("connStatus").style.color="#ef4444";
      toast("无法连接到后端: "+err);
      return;
    }
    document.getElementById("connStatus").textContent="已连接 ✓";
    document.getElementById("connStatus").style.color="#22c55e";
    toast("后端连接成功");
    checkCapabilities();
  });
}

checkCapabilities();

var roundsSelect=document.getElementById("roundsSelect");
var sRounds=document.getElementById("sRounds");

function updateStatLabels(){
  var r=parseInt(roundsSelect.value)||2;
  sRounds.textContent=r+"轮";
  document.querySelector('#sValid').closest('.stat').querySelector('.stat-label').textContent='稳定('+r+'/'+r+')';
  document.querySelector('#sUnstable').closest('.stat').querySelector('.stat-label').textContent='不稳定('+(r-1>0?r-1:1)+'/'+r+')';
}
roundsSelect.addEventListener('change',updateStatLabels);
updateStatLabels();

function startCheck(){
  if(busy) return;
  var lines=parseLines(proxyInput.value);
  if(!lines.length){toast("请输入至少一个代理");return}
  var rounds=parseInt(roundsSelect.value)||2;
  sRounds.textContent=rounds+"轮";
  updateStatLabels();

  // Filter based on detect mode
  var toCheck=lines;
  var skippedCount=0;
  if(detectMode==='skip'&&getCheckedCount()>0){
    toCheck=lines.filter(function(p){return !isChecked(p)});
    skippedCount=lines.length-toCheck.length;
  }
  if(toCheck.length===0){
    toast("所有代理均已检测过，请切换到'强制检测全部'模式或清空检测记录");
    return;
  }

  busy=true; V=[]; U=[]; F=[]; totalCount=toCheck.length; resultsIndex=0;
  checkBtn.disabled=true;
  document.getElementById('stopBtn').style.display="inline-flex";
  prog.style.display="block";
  progBar.style.width="0%";
  validList.innerHTML=""; failList.innerHTML="";
  if(skippedCount>0){
    statusText.textContent="跳过 "+skippedCount+" 个已检测代理，正在提交 "+toCheck.length+" 个...";
  }else{
    statusText.textContent="正在提交...";
  }
  post("/api/start",{proxies:toCheck,rounds:rounds},function(err,res){
    if(err){toast(err);finishCheck(false);return}
    sid=res.session_id; totalCount=res.total;
    statusText.textContent="正在检测 0/"+totalCount;
    poll();
  });
}
function poll(){
  if(!busy||!sid) return;
  post("/api/status",{session_id:sid, since:resultsIndex},function(err,res){
    if(err){setTimeout(poll,1000);return}
    if(res.new&&res.new.length>0){
      res.new.forEach(function(r){
        if(r.valid){V.push(r);appendItem(validList,r,"valid")}
        else if(r.unstable){U.push(r);appendItem(validList,r,"unstable")}
        else{F.push(r);appendItem(failList,r,"invalid")}
      });
      resultsIndex+=res.new.length;
      var pct=Math.round(res.total_done/totalCount*100);
      progBar.style.width=pct+"%";
      statusText.textContent="已检测 "+res.total_done+"/"+totalCount+" ("+pct+"%)";
      updateStats();
      saveResults();
    }
    if(res.finished){
      // Mark all detected proxies as checked
      var allDetected=V.concat(U).concat(F);
      markCheckedBatch(allDetected.map(function(r){return r.original||r.proxy}));
      saveCheckedLocal();
      syncCheckedToServer();
      finishCheck(false);
      toast("检测完成: "+V.length+" 稳定, "+U.length+" 不稳定, "+F.length+" 失效");
      statusText.textContent="检测完成";
    }else{setTimeout(poll,500)}
  });
}
function stopCheck(){
  if(!sid)return;
  post("/api/stop",{session_id:sid},function(){});
  finishCheck(true); toast("已停止");
}
function finishCheck(stopped){
  busy=false;sid=null;
  checkBtn.disabled=false;
  document.getElementById('stopBtn').style.display="none";
  prog.style.display="none";
  statusText.textContent=stopped?"已停止":"检测完成";
  saveResults();
  updateSkipBadge();
}

function appendItem(list,r,type){
  if(list.querySelector(".empty"))list.innerHTML="";
  list.insertAdjacentHTML("beforeend",itemHTML(r,type));
}
function itemHTML(r,type){
  var lat=r.latency?r.latency+"ms":"-";
  var spd=r.latency?(r.latency<1000?"speed-fast":r.latency<3000?"speed-mid":"speed-slow"):"";
  var err=r.error||(r.valid?"HTTP "+r.status_code:"HTTP "+(r.status_code||"N/A"));

  // Grade badge
  var gradeColors={'A':'#22c55e','B':'#10b981','C':'#eab308','D':'#f97316','F':'#ef4444'};
  var gradeLabels={'A':'最优','B':'良好','C':'可用','D':'仅首页','F':'失效'};
  var g=r.grade||'F';
  var gradeTag='<span class="tag" style="background:rgba(0,0,0,.3);color:'+(gradeColors[g]||'#888')+';font-weight:700">等级'+g+'</span>';

  // IP tag
  var ipTag=r.ip?'<span class="tag tag-ip">IP: '+esc(r.ip)+'</span>':'';
  // IP type tag
  var ipTypeTag='';
  if(r.ip_type==='datacenter') ipTypeTag='<span class="tag tag-dc">机房</span>';
  else if(r.ip_type==='residential') ipTypeTag='<span class="tag tag-res">住宅</span>';
  else ipTypeTag='<span class="tag" style="background:rgba(255,255,255,.06);color:#666">IP未知</span>';

  // CF bypass tag
  var cfTag='';
  if(r.cf_bypass) cfTag='<span class="tag tag-cf">&#9989; CF绕过</span>';
  else if(r.cf_challenge) cfTag='<span class="tag tag-cf-fail">&#10060; CF拦截('+esc(r.cf_challenge_type||'?')+')</span>';
  else cfTag='<span class="tag" style="background:rgba(255,255,255,.06);color:#666">CF未通过</span>';

  // API tag
  var apiTag='';
  if(r.api_reachable===true) apiTag='<span class="tag tag-ok">API可达</span>';
  else if(r.api_reachable===false) apiTag='<span class="tag tag-fail">API不可达</span>';
  else apiTag='<span class="tag" style="background:rgba(255,255,255,.06);color:#666">API未检测</span>';

  // Registration tag
  var regTag='';
  if(r.registration_ready) regTag='<span class="tag tag-reg">&#9989; 可注册</span>';
  else if(r.registration_detail) regTag='<span class="tag tag-reg-fail">&#10060; 注册受限</span>';
  else regTag='<span class="tag" style="background:rgba(255,255,255,.06);color:#666">注册未检测</span>';

  // Check count tag
  var chkTag='';
  if(r.checks_total!==undefined){
    var pct=(r.checks_passed||0)+"/"+r.checks_total;
    chkTag=r.valid?'<span class="tag tag-ok">'+pct+'</span>':
           r.unstable?'<span class="tag tag-unstable">'+pct+'</span>':
           '<span class="tag tag-fail">'+pct+'</span>';
  }

  // Badge
  var badge=r.valid?'<span class="tag tag-ok">'+gradeLabels[g]+'</span>':
            r.unstable?'<span class="tag tag-unstable">不稳定</span>':
            '<span class="tag tag-fail">'+gradeLabels[g]+'</span>';

  // Detail panel (expandable)
  var detailId='detail_'+Math.random().toString(36).substr(2,8);
  var detailHTML='';
  if(r.checks_detail && Object.keys(r.checks_detail).length>0){
    var d=r.checks_detail;
    var rows='';
    if(d.chat) rows+='<div class="detail-row"><span class="detail-key">首页:</span><span>'+(d.chat.status||'-')+(d.chat.cf_detected?' <span style="color:#ef4444">CF:'+esc(d.chat.cf_type||'detected')+'</span>':'')+'</span></div>';
    if(d.signup) rows+='<div class="detail-row"><span class="detail-key">注册页:</span><span>'+(d.signup.status||'-')+' '+(d.signup.accessible?'<span style="color:#22c55e">可访问</span>':'<span style="color:#ef4444">'+esc(d.signup.detail||'不可达')+'</span>')+'</span></div>';
    if(d.api) rows+='<div class="detail-row"><span class="detail-key">API:</span><span>'+(d.api.status||'-')+'</span></div>';
    if(d.ip_info) rows+='<div class="detail-row"><span class="detail-key">IP信息:</span><span>'+esc(d.ip_info.org||'')+' ('+esc(d.ip_info.country||'')+')</span></div>';
    if(r.cf_indicators && r.cf_indicators.length>0) rows+='<div class="detail-row"><span class="detail-key">CF特征:</span><span style="color:#ef4444">'+esc(r.cf_indicators.join(', '))+'</span></div>';
    detailHTML='<div class="detail-panel" id="'+detailId+'">'+rows+'</div>';
  }

  return '<div class="proxy-item '+type+'" data-lat="'+(r.latency||99999)+'" data-err="'+(r.error?"y":"n")+'" data-stable="'+(r.valid?"y":r.unstable?"u":"n")+'" data-cf="'+(r.cf_bypass?"y":"n")+'" data-reg="'+(r.registration_ready?"y":"n")+'" data-cf-challenge="'+(r.cf_challenge_type||"")+'" data-grade="'+g+'" onclick="toggleDetail(\''+detailId+'\')">'+ 
    '<div style="flex:1;min-width:0">'+
    '<div class="proxy-addr">'+esc(r.proxy)+'</div>'+
    '<div class="proxy-meta">'+gradeTag+chkTag+cfTag+regTag+ipTag+ipTypeTag+apiTag+
    '<span style="color:#555">'+err+'</span></div>'+
    detailHTML+
    '</div>'+
    '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0">'+
    (r.latency?'<span class="tag tag-lat"><span class="speed-dot '+spd+'"></span>'+lat+'</span>':'')+
    badge+
    '<button class="copy-btn" onclick="event.stopPropagation();clip(this)" data-p="'+esc(r.proxy)+'">复制</button>'+
    '</div></div>';
}

function toggleDetail(id){
  var el=document.getElementById(id);
  if(el) el.classList.toggle("show");
}

function updateStats(){
  var total=V.length+U.length+F.length;
  sTotal.textContent=total;
  sValid.textContent=V.length;
  sUnstable.textContent=U.length;
  sInvalid.textContent=F.length;
  sRate.textContent=total>0?Math.round(V.length/total*100)+"%":"0%";
  vCount.textContent=V.length+U.length;
  fCount.textContent=F.length;

  // Count CF bypass and registration ready
  var allR=V.concat(U).concat(F);
  var cfCount=allR.filter(function(r){return r.cf_bypass}).length;
  var regCount=allR.filter(function(r){return r.registration_ready}).length;
  sCfBypass.textContent=cfCount;
  sRegReady.textContent=regCount;
}
function clip(el){copyText(el.dataset.p)}
function copyValidProxies(){
  var all=V.concat(U);
  copyText(all.map(function(r){return r.proxy}).join("\n"));
  toast("已复制 "+all.length+" 个可用代理");
}
function copyFailedProxies(){copyText(F.map(function(r){return r.proxy}).join("\n"));toast("已复制 "+F.length+" 个失效代理")}
function clearValid(){
  V=[];U=[];validList.innerHTML='<div class="empty">等待检测...</div>';
  updateStats();saveResults();toast('已清空有效代理');
}
function clearFailed(){
  F=[];failList.innerHTML='<div class="empty">等待检测...</div>';
  updateStats();saveResults();toast('已清空失效代理');
}
function clearAll(){
  if(busy)stopCheck();
  proxyInput.value="";V=[];U=[];F=[];totalCount=0;sid=null;
  try{localStorage.removeItem(RESULTS_KEY)}catch(e){}
  validList.innerHTML='<div class="empty">等待检测...</div>';
  failList.innerHTML='<div class="empty">等待检测...</div>';
  vCount.textContent="0";fCount.textContent="0";
  sTotal.textContent="0";sValid.textContent="0";sUnstable.textContent="0";sInvalid.textContent="0";
  sCfBypass.textContent="0";sRegReady.textContent="0";
  sRate.textContent="0%";statusText.textContent="";
  updateProxyCount();
}

// [3] Export as TXT — one proxy per line
function exportResults(){
  var all=V.concat(U).concat(F);
  if(!all.length){toast("没有可导出的结果");return}
  var lines=all.map(function(r){return r.proxy}).join("\n");
  var b=new Blob([lines],{type:'text/plain'});
  var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='proxy-results-'+Date.now()+'.txt';a.click();
  toast('已导出 '+all.length+' 个代理');
}

function loadDemo(){
  proxyInput.value="# 示例(支持自动识别协议)\n127.0.0.1:7890\n192.168.1.1:1080\n# 也支持带前缀\nhttp://user:pass@proxy.example.com:8080\nhttps://proxy.example.com:8443\nsocks4://your-proxy:1080\nsocks5://your-proxy:1080\nsocks5h://your-proxy:1080";
  updateProxyCount();
  toast('已加载示例');
}

// Tab switching
function switchTab(tab){
  document.querySelectorAll('.result-tab').forEach(function(t){t.classList.remove('active')});
  document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.remove('active')});
  if(tab==='valid'){
    document.getElementById('tabBtnValid').classList.add('active');
    document.getElementById('tabValid').classList.add('active');
  }else if(tab==='invalid'){
    document.getElementById('tabBtnInvalid').classList.add('active');
    document.getElementById('tabInvalid').classList.add('active');
  }else if(tab==='repo'){
    document.getElementById('tabBtnRepo').classList.add('active');
    document.getElementById('tabRepo').classList.add('active');
    renderRepo();
  }
}

// Filter buttons
document.querySelectorAll('.fbtn').forEach(function(btn){
  btn.addEventListener('click',function(){
    var bar=btn.closest('.filter-bar');
    bar.querySelectorAll('.fbtn').forEach(function(b){b.classList.remove('active')});
    btn.classList.add('active');
    var f=btn.dataset.f;
    var listId=bar.id==='vFilters'?'validList':'failList';
    document.querySelectorAll('#'+listId+' .proxy-item').forEach(function(item){
      var lat=parseInt(item.dataset.lat);
      var err=item.dataset.err;
      var stb=item.dataset.stable;
      var cf=item.dataset.cf;
      var reg=item.dataset.reg;
      var cfChal=item.dataset.cfChallenge;
      var show=true;
      if(listId==='validList'){
        if(f==='stable')show=stb==='y';
        else if(f==='unstable')show=stb==='u';
        else if(f==='cf_bypass')show=cf==='y';
        else if(f==='reg_ready')show=reg==='y';
        else if(f==='fast')show=lat<1000;
        else if(f==='mid')show=lat>=1000&&lat<3000;
        else if(f==='slow')show=lat>=3000;
        else show=stb==='y'||stb==='u';
      }else{
        if(f==='timeout')show=err==='y'&&item.textContent.indexOf('\u8d85\u65f6')>-1;
        else if(f==='cf_block')show=cfChal.length>0&&cf!=='y';
        else if(f==='conn')show=err==='y'&&item.textContent.indexOf('\u8d85\u65f6')===-1&&cfChal.length===0;
        else if(f==='other')show=err==='n'&&cfChal.length===0;
        else show=true;
      }
      item.style.display=show?'flex':'none';
    });
  });
});
document.addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();if(busy)stopCheck();else startCheck()}});

// ============================================================
// [4] Grade dropdown — add proxies to repo by grade
// ============================================================
function toggleGradeMenu(){
  var dd=document.getElementById('gradeDropdown');
  dd.classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.grade-dropdown'))document.getElementById('gradeDropdown').classList.remove('open');
});

function addToRepoByGrade(grade){
  document.getElementById('gradeDropdown').classList.remove('open');
  var all=V.concat(U);
  var filtered;
  if(grade==='ALL'){
    filtered=all;
  }else{
    filtered=all.filter(function(r){return (r.grade||'F')===grade});
  }
  if(!filtered.length){toast('没有等级 '+grade+' 的代理');return}
  var proxies=filtered.map(function(r){
    return {proxy:r.proxy,grade:r.grade||'F',latency:r.latency,ip:r.ip,ip_type:r.ip_type,cf_bypass:r.cf_bypass,api_reachable:r.api_reachable,registration_ready:r.registration_ready,added:Date.now()};
  });
  var repo=loadRepo();
  var existingSet={};
  repo.forEach(function(p){existingSet[p.proxy]=true});
  var added=0;
  proxies.forEach(function(p){
    if(!existingSet[p.proxy]){repo.push(p);existingSet[p.proxy]=true;added++}
  });
  saveRepo(repo);
  renderRepo();
  if(added>0) toast('已添加 '+added+' 个等级'+(grade==='ALL'?'全部':grade)+'代理到仓库');
  else toast('仓库中已存在这些代理');
}

// ============================================================
// [5] 我的仓库 — localStorage persistence
// ============================================================
var REPO_KEY='proxy_checker_repo';
var USER_TOKEN_KEY='proxy_checker_token';
var REPO_SYNCED_KEY='proxy_checker_synced';

function getUserToken(){
  var t=localStorage.getItem(USER_TOKEN_KEY);
  if(!t){t='user_'+Math.random().toString(36).substr(2,12);localStorage.setItem(USER_TOKEN_KEY,t)}
  return t;
}

function syncRepoToServer(){
  var repo=loadRepo();
  var token=getUserToken();
  post('/api/repo/save',{repo:repo,token:token},function(err,res){
    if(!err&&res.ok){localStorage.setItem(REPO_SYNCED_KEY,JSON.stringify({count:res.count,time:Date.now()}))}
  });
}

function loadRepoFromServer(callback){
  var token=getUserToken();
  function tryLoadJson(t,cb){
    var xhr=new XMLHttpRequest();
    xhr.open('GET',API_BASE+'/api/repo/'+t+'.json',true);
    xhr.onload=function(){
      if(xhr.status===200){
        try{
          var data=JSON.parse(xhr.responseText);
          if(Array.isArray(data)&&data.length>0){cb(data.length,data);return}
        }catch(e){}
        // Fallback to txt
        tryLoadTxt(t,cb);
      }else{tryLoadTxt(t,cb)}
    };
    xhr.onerror=function(){tryLoadTxt(t,cb)};
    xhr.send();
  }
  function tryLoadTxt(t,cb){
    var xhr=new XMLHttpRequest();
    xhr.open('GET',API_BASE+'/api/repo/'+t+'.txt',true);
    xhr.onload=function(){
      if(xhr.status===200){
        var text=xhr.responseText.trim();
        if(!text){cb(0);return}
        var lines=text.split('\n').filter(function(l){return l.trim()});
        var repo=lines.map(function(p){return {proxy:p,grade:'?',latency:null,ip:null,ip_type:null,cf_bypass:false,api_reachable:false,registration_ready:false,added:Date.now()}});
        cb(repo.length,repo);
      }else{cb(0)}
    };
    xhr.onerror=function(){cb(0)};
    xhr.send();
  }
  tryLoadJson(token,function(count,repo){
    if(count>0){
      saveRepo(repo);
      renderRepo();
      if(callback)callback(count);
    }else{
      tryLoadJson('default',function(count2,repo2){
        if(count2>0){
          saveRepo(repo2);
          syncRepoToServer();
          renderRepo();
          if(callback)callback(count2);
        }else{
          if(callback)callback(0);
        }
      });
    }
  });
}
var RESULTS_KEY='proxy_checker_results';
var CHECKED_KEY='proxy_checker_checked';
var detectMode=localStorage.getItem('proxy_checker_detect_mode')||'skip'; // 'skip' or 'force'
var checkedProxies=new Set();
var checkedSyncTimer=null;

function loadCheckedLocal(){
  try{
    var arr=JSON.parse(localStorage.getItem(CHECKED_KEY))||[];
    checkedProxies=new Set(arr);
  }catch(e){checkedProxies=new Set()}
}
function saveCheckedLocal(){
  try{localStorage.setItem(CHECKED_KEY,JSON.stringify([...checkedProxies]))}catch(e){}
}
function syncCheckedToServer(){
  clearTimeout(checkedSyncTimer);
  checkedSyncTimer=setTimeout(function(){
    var token=getUserToken();
    var arr=[...checkedProxies];
    // Limit to 50000 to avoid huge payloads
    if(arr.length>50000) arr=arr.slice(-50000);
    post('/api/checked/save',{proxies:arr,token:token},function(){});
  },1500);
}
function loadCheckedFromServer(callback){
  var token=getUserToken();
  var xhr=new XMLHttpRequest();
  xhr.open('GET',API_BASE+'/api/checked/'+token+'.txt',true);
  xhr.onload=function(){
    if(xhr.status===200){
      var lines=xhr.responseText.split('\n').filter(function(l){return l.trim()});
      lines.forEach(function(l){checkedProxies.add(l.trim())});
      saveCheckedLocal();
      if(callback)callback(lines.length);
    }else{if(callback)callback(0)}
  };
  xhr.onerror=function(){if(callback)callback(0)};
  xhr.send();
}
function markChecked(proxy){checkedProxies.add(proxy)}
function markCheckedBatch(proxies){proxies.forEach(function(p){checkedProxies.add(p)})}
function isChecked(proxy){return checkedProxies.has(proxy)}
function getCheckedCount(){return checkedProxies.size}

function setDetectMode(mode){
  detectMode=mode;
  localStorage.setItem('proxy_checker_detect_mode',mode);
  document.getElementById('detectDropdown').classList.remove('open');
  var label=document.getElementById('detectBtnLabel');
  if(mode==='skip'){label.textContent='跳过已检测'}
  else{label.textContent='强制检测全部'}
  updateSkipBadge();
}
function toggleDetectMenu(){
  document.getElementById('detectDropdown').classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.detect-dropdown'))document.getElementById('detectDropdown').classList.remove('open');
});
function updateSkipBadge(){
  var badge=document.getElementById('skipBadge');
  var count=getCheckedCount();
  if(detectMode==='skip'&&count>0){
    badge.style.display='inline';
    badge.textContent=count+'个已检测';
  }else{
    badge.style.display='none';
  }
}
function clearCheckedHistory(){
  if(!getCheckedCount()){toast('检测记录为空');return}
  if(!confirm('确定清空检测记录？清空后所有代理将被重新检测。'))return;
  checkedProxies.clear();
  saveCheckedLocal();
  syncCheckedToServer();
  updateSkipBadge();
  toast('检测记录已清空');
}

// Initialize detect mode UI
(function(){
  var label=document.getElementById('detectBtnLabel');
  if(detectMode==='force'){label.textContent='强制检测全部'}
  else{label.textContent='跳过已检测'}
})();

function saveResults(){
  try{localStorage.setItem(RESULTS_KEY,JSON.stringify({valid:V,unstable:U,invalid:F}))}catch(e){}
}
function loadSavedResults(){
  try{var d=JSON.parse(localStorage.getItem(RESULTS_KEY));if(d){V=d.valid||[];U=d.unstable||[];F=d.invalid||[];return true}}catch(e){}
  return false;
}

function loadRepo(){
  try{return JSON.parse(localStorage.getItem(REPO_KEY))||[]}catch(e){return[]}
}
function saveRepo(repo){
  localStorage.setItem(REPO_KEY,JSON.stringify(repo));
  clearTimeout(saveRepo._timer);
  saveRepo._timer=setTimeout(syncRepoToServer,1000);
}

function renderRepo(){
  var repo=loadRepo();
  var list=document.getElementById('repoList');
  var cnt=document.getElementById('repoCount');
  cnt.textContent=repo.length;
  if(!repo.length){
    list.innerHTML='<div class="empty">仓库为空，检测完成后可将代理添加到仓库</div>';
    return;
  }
  var html='';
  repo.forEach(function(p,i){
    var gradeColors={'A':'#22c55e','B':'#10b981','C':'#eab308','D':'#f97316','F':'#ef4444'};
    var gradeLabels={'A':'最优','B':'良好','C':'可用','D':'仅首页','F':'失效'};
    var g=p.grade||'F';
    var lat=p.latency?p.latency+'ms':'-';
    var spd=p.latency?(p.latency<1000?"speed-fast":p.latency<3000?"speed-mid":"speed-slow"):"";
    html+='<div class="proxy-item valid" data-lat="'+(p.latency||99999)+'">'+
      '<div style="flex:1;min-width:0">'+
      '<div class="proxy-addr">'+esc(p.proxy)+'</div>'+
      '<div class="proxy-meta">'+
      '<span class="tag" style="background:rgba(0,0,0,.3);color:'+(gradeColors[g]||'#888')+';font-weight:700">等级'+g+'</span>'+
      (p.ip_type==='datacenter'?'<span class="tag tag-dc">机房</span>':p.ip_type==='residential'?'<span class="tag tag-res">住宅</span>':'')+
      (p.cf_bypass?'<span class="tag tag-cf">CF绕过</span>':'')+
      (p.registration_ready?'<span class="tag tag-reg">可注册</span>':'')+
      '</div></div>'+
      '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0">'+
      (p.latency?'<span class="tag tag-lat"><span class="speed-dot '+spd+'"></span>'+lat+'</span>':'')+
      '<span class="tag tag-ok">'+(gradeLabels[g]||'')+'</span>'+
      '<button class="copy-btn" style="opacity:0.6" onclick="event.stopPropagation();clip(this)" data-p="'+esc(p.proxy)+'">复制</button>'+
      '<button class="copy-btn" style="opacity:0.6;color:#ef4444" onclick="event.stopPropagation();removeFromRepo('+i+')">删除</button>'+
      '</div></div>';
  });
  list.innerHTML=html;
  list.style.maxHeight='300px';
  list.style.overflowY='auto';
}

function removeFromRepo(idx){
  var repo=loadRepo();
  repo.splice(idx,1);
  saveRepo(repo);
  renderRepo();
  toast('已从仓库移除');
}

function exportRepo(){
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空');return}
  var lines=repo.map(function(p){return p.proxy}).join("\n");
  var b=new Blob([lines],{type:'text/plain'});
  var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='proxy-repo-'+Date.now()+'.txt';a.click();
  toast('已导出 '+repo.length+' 个代理');
}

function copyRepo(){
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空');return}
  copyText(repo.map(function(p){return p.proxy}).join("\n"));
  toast("已复制 "+repo.length+" 个代理");
}

function restoreRepoFromCloud(){
  var local=loadRepo();
  if(local.length>0 && !confirm('清空本地仓库并从云端恢复？'))return;
  localStorage.removeItem('repo_manually_cleared');
  loadRepoFromServer(function(count){
    if(count>0) toast('已从云端恢复 '+count+' 个代理');
    else toast('云端没有仓库数据');
  });
}

function toggleRepoIO(){
  document.getElementById('repoIODropdown').classList.toggle('open');
}
function toggleRepoCloud(){
  document.getElementById('repoCloudDropdown').classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('#repoIODropdown'))document.getElementById('repoIODropdown').classList.remove('open');
  if(!e.target.closest('#repoCloudDropdown'))document.getElementById('repoCloudDropdown').classList.remove('open');
});
function saveRepoToCloud(){
  document.getElementById('repoCloudDropdown').classList.remove('open');
  localStorage.removeItem('repo_manually_cleared');
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空，无需保存');return}
  var token=getUserToken();
  post('/api/repo/save',{repo:repo,token:token},function(err,res){
    if(err){toast('保存失败: '+err);return}
    if(res.ok){
      localStorage.setItem(REPO_SYNCED_KEY,JSON.stringify({count:res.count,time:Date.now()}));
      toast('已保存 '+res.count+' 个代理到云端');
    }
  });
}

function clearRepo(){
  if(!loadRepo().length){toast('仓库已经是空的');return}
  if(!confirm('确定清空本地仓库？\n注意：云端数据不会被删除，可随时通过「恢复云端数据」恢复。'))return;
  localStorage.removeItem(REPO_KEY);
  localStorage.setItem('repo_manually_cleared','1');
  renderRepo();
  toast('本地仓库已清空（云端数据保留）');
}

function importRepoTxt(input){
  localStorage.removeItem('repo_manually_cleared');
  var file=input.files[0];
  if(!file)return;
  var reader=new FileReader();
  reader.onload=function(e){
    var text=e.target.result;
    var lines=text.split("\n").map(function(l){return l.trim()}).filter(function(l){return l.length>0&&!l.startsWith("#")});
    if(!lines.length){toast("文件中没有有效的代理");return}
    var repo=loadRepo();
    var existingSet={};
    repo.forEach(function(p){existingSet[p.proxy]=true});
    var added=0;
    lines.forEach(function(proxy){
      if(!existingSet[proxy]){
        repo.push({proxy:proxy,grade:"?",latency:null,ip:null,ip_type:null,cf_bypass:false,api_reachable:false,registration_ready:false,added:Date.now()});
        existingSet[proxy]=true;
        added++;
      }
    });
    saveRepo(repo);
    renderRepo();
    toast("已导入 "+added+" 个代理到仓库"+(added<lines.length?"（跳过 "+(lines.length-added)+" 个重复）":""));
  };
  reader.readAsText(file);
  input.value="";
}

// Initial render
renderRepo();
// Load checked proxies from server
loadCheckedLocal();
updateSkipBadge();
loadCheckedFromServer(function(count){
  if(count>0){updateSkipBadge();toast('从服务器恢复 '+count+' 条检测记录')}
});
// If repo is empty, try loading from server (skip if user manually cleared)
var repoClearedManually=localStorage.getItem('repo_manually_cleared');
if(!repoClearedManually && !loadRepo().length){
  loadRepoFromServer(function(count){
    if(count>0){toast('从服务器恢复 '+count+' 个仓库代理')}
  });
}
// Restore saved detection results
if(loadSavedResults()){
  var all=V.concat(U).concat(F);
  if(all.length>0){
    V.forEach(function(r){appendItem(validList,r,"valid")});
    U.forEach(function(r){appendItem(validList,r,"unstable")});
    F.forEach(function(r){appendItem(failList,r,"invalid")});
    updateStats();
    statusText.textContent="已恢复 "+all.length+" 条历史结果";
  }
}

// Get repo link — sync to server and show URL
// Get repo link — sync to server and show URL
function getRepoLink(){
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空');return}
  var proxies=repo.map(function(p){return p.proxy});
  // Fixed: use static token so link never changes
  var token='myrepo';
  var btn=event.target;
  btn.textContent='同步中...';
  btn.disabled=true;
  post('/api/repo/save',{proxies:proxies,token:token},function(err,res){
    btn.innerHTML='&#128279; 获取仓库链接';
    btn.disabled=false;
    if(err||res.error){toast('同步失败: '+(err||res.error));return}
    var url=API_BASE+res.url;
    copyText(url);
    toast('链接已复制 ('+res.count+'个代理)');
    var overlay=document.createElement('div');
    overlay.className='modal-overlay show';
    overlay.onclick=function(e){if(e.target===overlay)overlay.remove()};
    var html='<div class="modal-box" style="max-width:500px">';
    html+='<div class="modal-icon" style="background:linear-gradient(135deg,rgba(96,165,250,.15),rgba(96,165,250,.05));border-color:rgba(96,165,250,.2)">&#128279;</div>';
    html+='<h3>仓库链接</h3>';
    html+='<p style="margin-bottom:16px">在其他程序的代理框中粘贴此链接即可拉取：</p>';
    html+='<input id="repoLinkInput" readonly value="'+url+'" style="width:100%;padding:12px 14px;background:#0d0d1a;border:1px solid rgba(255,255,255,.1);border-radius:10px;color:#e0e0e0;font-family:monospace;font-size:12px;margin-bottom:20px">';
    html+='<div style="display:flex;gap:10px;justify-content:center">';
    html+='<button class="btn btn-ghost" onclick="navigator.clipboard.writeText(document.getElementById(\'repoLinkInput\').value);toast(\'已复制\')">复制链接</button>';
    html+='<button class="btn btn-primary" onclick="this.closest(\'.modal-overlay\').remove()">关闭</button>';
    html+='</div></div>';
    overlay.innerHTML=html;
    document.body.appendChild(overlay);
    document.getElementById('repoLinkInput').select();
  });
}

// ============================================================
// Fetch free proxies from external sources
// ============================================================
var fetchSources=[];
var fetchMenu=document.getElementById('fetchMenu');
var fetchDropdown=document.getElementById('fetchDropdown');

function initFetchMenu(){
  post('/api/capabilities',{},function(err,res){
    if(err||!res)return;
    if(!res.fetch_proxies)return;
    fetchSources=res.proxy_sources||[];
    if(!fetchSources.length)return;
    var html='';
    fetchSources.forEach(function(s){
      html+='<div class="fetch-menu-item" onclick="doFetchProxies(\''+esc(s.id)+'\')">'+esc(s.name)+'</div>';
    });
    fetchMenu.innerHTML=html;
    document.getElementById('fetchBtn').style.display='inline-flex';
  });
}
initFetchMenu();

function toggleFetchMenu(){
  fetchDropdown.classList.toggle('open');
}
document.addEventListener('click',function(e){
  if(!e.target.closest('.fetch-dropdown'))fetchDropdown.classList.remove('open');
});

function doFetchProxies(sourceId){
  fetchDropdown.classList.remove('open');
  var btn=document.getElementById('fetchBtn');
  var origText=btn.innerHTML;
  btn.innerHTML='&#8987; 拉取中...';
  btn.disabled=true;
  statusText.textContent='正在从 '+sourceId+' 拉取代理...';
  post('/api/fetch-proxies',{source:sourceId,limit:500},function(err,res){
    btn.innerHTML=origText;
    btn.disabled=false;
    if(err){
      toast('拉取失败: '+err);
      statusText.textContent='';
      return;
    }
    if(res.error){
      toast('拉取失败: '+res.error);
      statusText.textContent='';
      return;
    }
    var proxyLines=res.proxies.map(function(p){return p.proxy});
    var existing=proxyInput.value.trim();
    if(existing){
      proxyInput.value=existing+'\n'+proxyLines.join('\n');
    }else{
      proxyInput.value=proxyLines.join('\n');
    }
    updateProxyCount();
    toast('已从 '+res.source+' 拉取 '+res.count+' 个代理');
    statusText.textContent='已追加 '+res.count+' 个代理';
  });
}
