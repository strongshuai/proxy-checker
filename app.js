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
var sApiReachable=document.getElementById("sApiReachable");
var statusText=document.getElementById("statusText");
var proxyCountBadge=document.getElementById("proxyCountBadge");
var TARGET_PROFILE_KEY='proxy_checker_target_profile';
var ACTIVE_SESSION_KEY='proxy_checker_active_session';
var AUTH_TOKEN_KEY='proxy_checker_auth_token';
var authRequired=false;
var authenticated=false;
var autoModeAvailable=false;
var autoStatusTimer=null;
var autoStatusCache=null;
var autoResultsIndex=0;
var autoSessionId='';
var autoRunResultKeys={};
var autoStopRequestedSession='';
var autoStopRepoPromptSession='';
var appSettings={
  check_rounds:2,
  max_check_rounds:3,
  max_concurrent:30,
  max_concurrent_limit:200,
  timeout:12,
  detect_timeout:8,
  auth_session_days:7,
  run_log_limit:100,
  timezone:'UTC',
  timezone_options:[{id:'UTC',name:'UTC'}],
  password_configurable:true
};
var targetProfiles=[
  {id:'generic',name:'常规代理检测',has_api:false,has_signup:false,has_cf_detection:false},
  {id:'openai',name:'OpenAI 检测',has_api:true,has_signup:false,has_cf_detection:true},
  {id:'grok',name:'Grok 检测',has_api:true,has_signup:false,has_cf_detection:true},
  {id:'gemini',name:'Gemini 检测',has_api:true,has_signup:false,has_cf_detection:false},
  {id:'claude',name:'Claude 检测',has_api:true,has_signup:false,has_cf_detection:true}
];
var currentTargetProfile=localStorage.getItem(TARGET_PROFILE_KEY)||'generic';

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
function attr(s){return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
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
  var authToken=localStorage.getItem(AUTH_TOKEN_KEY);
  if(authToken)xhr.setRequestHeader("Authorization","Bearer "+authToken);
  xhr.onload=function(){
    var res=null;
    try{res=JSON.parse(xhr.responseText||"{}")}catch(e){cb("解析失败");return}
    if(xhr.status===401){
      if(url!=='/api/auth/login')localStorage.removeItem(AUTH_TOKEN_KEY);
      authenticated=false;
      if(url!=='/api/auth/login'&&(!API_BASE||API_BASE===window.location.origin)){
        location.replace('/login.html');
        return;
      }
      showAuthOverlay();
      cb(res.error||"请先输入登录密码",res);
      return;
    }
    cb(null,res);
  };
  xhr.onerror=function(){cb("网络错误")};
  xhr.send(JSON.stringify(data));
}

function showAuthOverlay(){
  var overlay=document.getElementById('authOverlay');
  if(!overlay)return;
  overlay.classList.add('show');
  overlay.style.display='flex';
  setTimeout(function(){
    var input=document.getElementById('authPassword');
    if(input)input.focus();
  },50);
}

function hideAuthOverlay(){
  var overlay=document.getElementById('authOverlay');
  if(!overlay)return;
  overlay.classList.remove('show');
  overlay.style.display='none';
}

function requireAuthenticatedUI(){
  if(authRequired&&!authenticated){
    showAuthOverlay();
    toast('请输入登录密码');
    return false;
  }
  return true;
}

function checkAuthStatus(){
  post('/api/auth/status',{},function(err,res){
    if(err||!res){
      authRequired=true;
      authenticated=false;
      showAuthOverlay();
      return;
    }
    authRequired=!!res.auth_required;
    authenticated=!!res.authenticated||!authRequired;
    if(authRequired&&!authenticated)showAuthOverlay();
    else hideAuthOverlay();
  });
}

function loginWithPassword(){
  var input=document.getElementById('authPassword');
  var msg=document.getElementById('authMessage');
  var btn=document.getElementById('authLoginBtn');
  var password=input?input.value:'';
  if(!password){
    if(msg)msg.textContent='请输入密码';
    return;
  }
  if(btn){btn.disabled=true;btn.textContent='登录中...'}
  post('/api/auth/login',{password:password},function(err,res){
    if(btn){btn.disabled=false;btn.textContent='登录'}
    if(err||!res||!res.ok){
      if(msg)msg.textContent=err||'登录失败';
      return;
    }
    if(res.token)localStorage.setItem(AUTH_TOKEN_KEY,res.token);
    authenticated=true;
    authRequired=!!res.auth_required;
    if(input)input.value='';
    if(msg)msg.textContent='';
    hideAuthOverlay();
    toast('已登录');
    checkCapabilities();
  });
}

function logoutAuth(){
  post('/api/auth/logout',{},function(){});
  localStorage.removeItem(AUTH_TOKEN_KEY);
  authenticated=false;
  showAuthOverlay();
  toast('已退出');
}

// Check capabilities on load
function checkCapabilities(){
  post("/api/capabilities",{},function(err,res){
    if(err) return;
    authRequired=!!res.auth_required;
    authenticated=!!res.authenticated||!authRequired;
    if(authRequired&&!authenticated)showAuthOverlay();
    if(res && Array.isArray(res.target_profiles) && res.target_profiles.length){
      targetProfiles=res.target_profiles;
      renderTargetProfileMenu();
      updateTargetProfileUI();
    }
    autoModeAvailable=!!(res&&res.auto_mode);
    if(res&&res.settings)applyAppSettings(res.settings);
    updateAutoAvailability(res&&res.auto_mode_hint);
    if(autoModeAvailable&&authenticated)loadAutoStatus();
    var badge=document.getElementById("capBadge");
    if(res && res.deep_check){
      badge.className="cap-badge cap-ok";
      badge.innerHTML="&#9989; Deep Check可用";
      badge.title="Deep Check 已可用：会用真实浏览器再测一次，速度慢一点，但更接近真实访问目标服务的结果。";
    }else{
      badge.className="cap-badge cap-no";
      badge.innerHTML="&#9888; Deep Check不可用";
      badge.title="Deep Check 是用真实浏览器复测代理的慢速检查；当前服务器没装这套组件，所以这里只能做普通检测。";
    }
    badge.style.display="inline-flex";
  });
}

function getTargetProfileInfo(id){
  for(var i=0;i<targetProfiles.length;i++){
    if(targetProfiles[i].id===id)return targetProfiles[i];
  }
  return targetProfiles[0];
}

function renderTargetProfileMenu(){
  var menu=document.getElementById('targetProfileMenu');
  if(!menu)return;
  var html='';
  targetProfiles.forEach(function(profile){
    var active=profile.id===currentTargetProfile?' <span style="color:#22c55e;margin-left:auto">✓</span>':'';
    html+='<div class="fetch-menu-item" onclick="setTargetProfile(\''+esc(profile.id)+'\')">&#127919; '+esc(profile.name)+active+'</div>';
  });
  menu.innerHTML=html;
}

function updateTargetProfileUI(){
  var profile=getTargetProfileInfo(currentTargetProfile);
  var btn=document.getElementById('targetProfileBtn');
  if(btn)btn.innerHTML='&#127919; '+esc(profile.name)+' &#9660;';
  var serviceBtn=document.getElementById('filterServiceBtn');
  var apiBtn=document.getElementById('filterApiBtn');
  if(serviceBtn)serviceBtn.textContent=profile.has_cf_detection?'CF绕过':'服务可达';
  if(apiBtn)apiBtn.textContent=profile.has_api?'API域名可达':'出口IP';
  updateStatLabels();
}

function setTargetProfile(id){
  currentTargetProfile=getTargetProfileInfo(id).id;
  localStorage.setItem(TARGET_PROFILE_KEY,currentTargetProfile);
  document.getElementById('targetProfileDropdown').classList.remove('open');
  renderTargetProfileMenu();
  updateTargetProfileUI();
}

function toggleTargetProfileMenu(){
  document.getElementById('targetProfileDropdown').classList.toggle('open');
}

document.addEventListener('click',function(e){
  var dd=document.getElementById('targetProfileDropdown');
  if(dd&&!e.target.closest('#targetProfileDropdown'))dd.classList.remove('open');
});

// GitHub Pages: show backend config panel
if(isRemote && !window.location.hostname.endsWith('vercel.app')){
  document.getElementById("backendConfig").style.display="block";
  var saved=localStorage.getItem("proxy_checker_backend");
  if(saved){
    API_BASE=saved.replace(/\/$/,"");
    document.getElementById("backendUrl").value=API_BASE;
    checkCapabilities();
    checkAuthStatus();
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
    checkAuthStatus();
  });
}

checkCapabilities();
checkAuthStatus();

var roundsSelect=document.getElementById("roundsSelect");
var concurrentInput=document.getElementById("concurrentInput");
var sRounds=document.getElementById("sRounds");
var CONCURRENT_KEY='proxy_checker_max_concurrent';
var ROUNDS_KEY='proxy_checker_rounds';

function normalizeConcurrent(value){
  var n=parseInt(value);
  if(!n||n<1)n=appSettings.max_concurrent||30;
  var limit=appSettings.max_concurrent_limit||200;
  if(n>limit)n=limit;
  return n;
}

function normalizeRounds(value){
  var n=parseInt(value);
  if(!n||n<1)n=appSettings.check_rounds||2;
  var max=appSettings.max_check_rounds||3;
  if(n>max)n=max;
  return n;
}

function renderRoundsSelect(maxRounds,selected){
  if(!roundsSelect)return;
  maxRounds=normalizeRounds(maxRounds||3);
  selected=normalizeRounds(selected||appSettings.check_rounds||2);
  var labels={1:'1轮(快速)',2:'2轮(推荐)',3:'3轮(严格)'};
  var html='';
  for(var i=1;i<=maxRounds;i++){
    html+='<option value="'+i+'" '+(i===selected?'selected':'')+'>'+(labels[i]||i+'轮')+'</option>';
  }
  roundsSelect.innerHTML=html;
  roundsSelect.value=String(selected);
}

function applyAppSettings(settings){
  if(!settings)return;
  appSettings=Object.assign({},appSettings,settings);
  var savedRounds=localStorage.getItem(ROUNDS_KEY);
  var rounds=normalizeRounds(savedRounds||appSettings.check_rounds);
  renderRoundsSelect(appSettings.max_check_rounds,rounds);
  if(concurrentInput){
    var savedConcurrent=localStorage.getItem(CONCURRENT_KEY);
    concurrentInput.max=String(appSettings.max_concurrent_limit||200);
    concurrentInput.value=String(normalizeConcurrent(savedConcurrent||appSettings.max_concurrent));
  }
  updateStatLabels();
}

function getConcurrentValue(){
  var n=normalizeConcurrent(concurrentInput?concurrentInput.value:30);
  if(concurrentInput)concurrentInput.value=String(n);
  localStorage.setItem(CONCURRENT_KEY,String(n));
  return n;
}

function getRoundsValue(){
  var n=normalizeRounds(roundsSelect?roundsSelect.value:appSettings.check_rounds);
  if(roundsSelect)roundsSelect.value=String(n);
  localStorage.setItem(ROUNDS_KEY,String(n));
  return n;
}

if(concurrentInput){
  concurrentInput.value=String(normalizeConcurrent(localStorage.getItem(CONCURRENT_KEY)||concurrentInput.value));
  concurrentInput.addEventListener('change',getConcurrentValue);
  concurrentInput.addEventListener('blur',getConcurrentValue);
}
renderRoundsSelect(appSettings.max_check_rounds,localStorage.getItem(ROUNDS_KEY)||appSettings.check_rounds);

function updateStatLabels(){
  if(!roundsSelect)return;
  var r=getRoundsValue();
  sRounds.textContent=r+"轮";
  document.querySelector('#sValid').closest('.stat').querySelector('.stat-label').textContent='稳定('+r+'/'+r+')';
  document.querySelector('#sUnstable').closest('.stat').querySelector('.stat-label').textContent='不稳定('+(r-1>0?r-1:1)+'/'+r+')';
  var profile=getTargetProfileInfo(currentTargetProfile);
  document.querySelector('#sCfBypass').closest('.stat').querySelector('.stat-label').textContent=profile.has_cf_detection?'CF绕过':'服务可达';
  document.querySelector('#sApiReachable').closest('.stat').querySelector('.stat-label').textContent=profile.has_api?'API域名':'出口IP';
}
roundsSelect.addEventListener('change',updateStatLabels);
updateStatLabels();
renderTargetProfileMenu();
updateTargetProfileUI();

function startCheck(options){
  options=options||{};
  if(!requireAuthenticatedUI())return;
  if(busy) return;
  if(!options.skipAutoCheck&&autoModeAvailable){
    post('/api/auto/status',{token:getUserToken()},function(err,res){
      if(!err&&res&&res.state&&res.state.running){
        renderAutoStatus(res);
        toast('自动任务正在执行，请先打开自动模式并停止自动任务');
        return;
      }
      var nextOptions=Object.assign({},options,{skipAutoCheck:true});
      startCheck(nextOptions);
    });
    return;
  }
  var lines=parseLines(proxyInput.value);
  if(!lines.length){toast("请输入至少一个代理");return}
  var rounds=getRoundsValue();
  var maxConcurrent=getConcurrentValue();
  sRounds.textContent=rounds+"轮";
  updateStatLabels();

  // Filter based on detect mode
  var toCheck=lines;
  var skippedCount=0;
  if(!options.force&&detectMode==='skip'&&getCheckedCount()>0){
    toCheck=lines.filter(function(p){return !isChecked(p)});
    skippedCount=lines.length-toCheck.length;
  }
  if(toCheck.length===0){
    toast("所有代理均已检测过，请切换到'强制检测全部'模式或清空检测记录");
    return;
  }

  clearActiveSession();
  busy=true; V=[]; U=[]; F=[]; totalCount=toCheck.length; resultsIndex=0;
  saveResults();
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
  var targetProfile=options.targetProfile||currentTargetProfile;
  post("/api/start",{proxies:toCheck,rounds:rounds,target_profile:targetProfile,max_concurrent:maxConcurrent,token:getUserToken()},function(err,res){
    if(err){toast(err);finishCheck(false);return}
    if(res&&res.auto_running){toast(res.error||'自动任务正在执行，请先停止自动任务');finishCheck(false);return}
    if(res&&res.error){toast(res.error);finishCheck(false);return}
    sid=res.session_id; totalCount=res.total;
    currentTargetProfile=res.target_profile||targetProfile;
    if(res.max_concurrent&&concurrentInput){
      concurrentInput.value=String(res.max_concurrent);
      localStorage.setItem(CONCURRENT_KEY,String(res.max_concurrent));
    }
    localStorage.setItem(TARGET_PROFILE_KEY,currentTargetProfile);
    saveActiveSession();
    statusText.textContent="正在检测 0/"+totalCount+"，并发 "+getConcurrentValue();
    poll();
  });
}

function saveActiveSession(){
  if(!sid||!busy)return;
  localStorage.setItem(ACTIVE_SESSION_KEY,JSON.stringify({
    session_id:sid,
    target_profile:currentTargetProfile,
    rounds:getRoundsValue(),
    max_concurrent:getConcurrentValue(),
    total:totalCount,
    input:proxyInput.value,
    results_index:resultsIndex,
    created:Date.now()
  }));
}

function clearActiveSession(){
  localStorage.removeItem(ACTIVE_SESSION_KEY);
}

function expireActiveSession(message){
  clearActiveSession();
  busy=false;sid=null;
  checkBtn.disabled=false;
  document.getElementById('stopBtn').style.display="none";
  prog.style.display="none";
  statusText.textContent=message;
  toast(message);
  updateSkipBadge();
}

function poll(){
  if(!busy||!sid) return;
  post("/api/status",{session_id:sid, since:resultsIndex},function(err,res){
    if(err){setTimeout(poll,1000);return}
    if(res.error){
      expireActiveSession("检测任务已过期，可重新开始");
      return;
    }
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
      saveActiveSession();
    }
    if(res.finished){
      // Mark all detected proxies as checked
      var allDetected=V.concat(U).concat(F);
      markCheckedBatch(allDetected.map(function(r){return r.original||r.proxy}));
      saveCheckedLocal();
      syncCheckedToServer();
      clearActiveSession();
      finishCheck(false);
      toast("检测完成: "+V.length+" 稳定, "+U.length+" 不稳定, "+F.length+" 失效");
      statusText.textContent="检测完成";
    }else{setTimeout(poll,500)}
  });
}
function stopCheck(){
  if(!sid)return;
  post("/api/stop",{session_id:sid},function(){});
  clearActiveSession();
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

function getResultByProxy(proxy){
  var key=proxyKeyValue(proxy);
  var all=V.concat(U);
  for(var i=0;i<all.length;i++){
    if(resultKey(all[i])===key)return all[i];
  }
  return null;
}

function proxyKeyValue(proxy){
  return String(proxy||'').trim().toLowerCase().replace(/^[a-z0-9+.-]+:\/\//,'');
}

function resultKey(r){
  return proxyKeyValue((r&&r.original)||((r&&r.proxy)||''));
}

function removeResultByKey(key){
  V=V.filter(function(r){return resultKey(r)!==key});
  U=U.filter(function(r){return resultKey(r)!==key});
  F=F.filter(function(r){return resultKey(r)!==key});
}

function renderResultLists(){
  validList.innerHTML='';
  failList.innerHTML='';
  V.forEach(function(r){appendItem(validList,r,'valid')});
  U.forEach(function(r){appendItem(validList,r,'unstable')});
  F.forEach(function(r){appendItem(failList,r,'invalid')});
  if(!V.length&&!U.length)validList.innerHTML='<div class="empty">等待检测...</div>';
  if(!F.length)failList.innerHTML='<div class="empty">等待检测...</div>';
  applyActiveResultFilters();
}

function applyActiveResultFilters(){
  var activeValid=document.querySelector('#vFilters .fbtn.active');
  var activeInvalid=document.querySelector('#fFilters .fbtn.active');
  if(activeValid)activeValid.click();
  if(activeInvalid)activeInvalid.click();
}

function upsertResult(r){
  if(!r)return false;
  var key=resultKey(r);
  if(!key)return false;
  removeResultByKey(key);
  if(r.valid)V.push(r);
  else if(r.unstable)U.push(r);
  else F.push(r);
  return true;
}

function getResultCountry(r){
  var country=r.country;
  if(!country&&r.checks_detail&&r.checks_detail.ip_info)country=r.checks_detail.ip_info.country;
  return country?String(country).toUpperCase():'';
}

function getResultErrorText(r){
  if(r.error)return r.error;
  if(!r.valid&&r.status_code&&r.status_code!==200)return 'HTTP '+r.status_code;
  return '';
}

function getRecommendedUseLabel(use){
  var map={
    web_api:'网页+API',
    web:'网页可用',
    api:'API可用',
    generic:'基础代理',
    unstable:'不稳定',
    invalid:'失效'
  };
  return map[use]||'待判断';
}

function getRecommendedUseTitle(use){
  var map={
    web_api:'网页和 API 域名都测通了，优先拿来做目标服务相关访问。',
    web:'目标网页能打开，但 API 域名不一定通，适合网页访问。',
    api:'API 域名能连上，适合程序请求；不代表账号、Key 或额度可用。',
    generic:'基础代理能连通并能拿到出口 IP，适合先收进池子再按目标复测。',
    unstable:'有成功记录但不稳定，可能受网络波动、代理限速或目标封锁影响。',
    invalid:'这次检测没体现可用价值，通常是连接失败、超时或目标不可达。'
  };
  return map[use]||'还没有足够信息判断这条代理更适合怎么用。';
}

function getGradeTitle(grade){
  var map={
    A:'等级 A：网页和 API 都稳定可达，整体最值得优先使用。',
    B:'等级 B：目标网页或 API 至少一项稳定可达，有实际用途。',
    C:'等级 C：基础代理可用，但目标专项能力一般。',
    D:'等级 D：有成功记录但多轮不稳定，建议复测后再用。',
    F:'等级 F：基础连接或目标检测失败，不建议使用。',
    '?':'等级未知：这条记录来自导入或旧数据，还没有完整检测结果。'
  };
  return map[grade]||map['?'];
}

function getFinalBadgeTitle(grade,state){
  if(state==='valid')return '最终结论：这条代理对当前检测模式有实际用途。'+getGradeTitle(grade);
  if(state==='unstable')return '最终结论：有成功但不够稳定，建议复测后再用。'+getGradeTitle(grade);
  return '最终结论：这条代理当前不建议使用。'+getGradeTitle(grade);
}

function getIpTypeTitle(type){
  if(type==='datacenter')return '机房 IP，通常来自云服务器或数据中心，速度可能好，但更容易被风控。';
  if(type==='residential')return '住宅 IP，通常更像普通家庭宽带，可能更容易通过风控，但稳定性不保证。';
  return '查到了出口 IP，但暂时无法判断它是机房、住宅还是其它类型。';
}

function tagTitle(kind,value){
  var text={
    target:'检测模式：'+(value||'当前模式')+'。结果只代表当前服务器跑这个模式时的网络可达性。',
    service_ok:'目标首页或网页入口能通过这个代理打开，说明网页访问路径可用。',
    service_fail:'目标首页或网页入口没通过这个代理打通；API 可能仍单独可用。',
    ip:'目标网站看到的是这个出口 IP，不一定等于你填写的代理服务器 IP。',
    country:'出口 IP 查询到的国家或地区，结果依赖第三方 IP 数据库。',
    cf_ok:'目标网页没有被 Cloudflare 挑战页卡住，网页访问更接近真实可用。',
    cf_fail:'访问目标网页时撞上 Cloudflare 挑战或拦截页，浏览器里可能需要额外验证。',
    cf_unknown:'这个模式会看 CF，但本次没有确认成功绕过 Cloudflare。',
    api_ok:'目标 API 域名能连上。401/403 也算域名可达，不代表账号、Key 或额度可用。',
    api_fail:'目标 API 域名没连通，可能是代理、DNS、TLS 或目标侧拦截导致。',
    api_unknown:'当前检测模式没有拿到 API 结果，不能据此判断 API 是否可用。',
    checks:'多轮检测通过数/总轮数，数字越接近满分越稳定。',
    latency:'通过这个代理完成检测请求的大致耗时，越低越快，但只代表本次检测。',
    error:'后端返回的失败原因或 HTTP 状态，仅用于排查，不一定代表代理完全不可用。'
  };
  return text[kind]||'这个标签是当前检测结果的一项摘要。';
}

function tagHTML(className,content,title,style){
  var cls='tag'+(className?' '+className:'');
  var attrs='class="'+attr(cls)+'"';
  if(style)attrs+=' style="'+attr(style)+'"';
  if(title)attrs+=' title="'+attr(title)+'"';
  return '<span '+attrs+'>'+content+'</span>';
}

function itemHTML(r,type){
  var lat=r.latency?r.latency+"ms":"-";
  var spd=r.latency?(r.latency<1000?"speed-fast":r.latency<3000?"speed-mid":"speed-slow"):"";
  var err=getResultErrorText(r);
  var errTag=err?'<span style="color:#555" title="'+attr(tagTitle('error'))+'">'+esc(err)+'</span>':'';
  var profileId=r.target_profile||currentTargetProfile;
  var profileInfo=getTargetProfileInfo(profileId);
  var hasCfDetection=!!profileInfo.has_cf_detection||!!r.cf_challenge;
  var targetTag=r.target_name?tagHTML('',esc(r.target_name),tagTitle('target',r.target_name),'background:rgba(255,255,255,.06);color:#aaa'):'';
  var useTag=r.recommended_use?tagHTML('tag-ok',esc(getRecommendedUseLabel(r.recommended_use)),getRecommendedUseTitle(r.recommended_use)):'';
  var serviceTag='';
  if(r.service_reachable===true) serviceTag=tagHTML('tag-ok','服务可达',tagTitle('service_ok'));
  else if(r.service_reachable===false) serviceTag=tagHTML('tag-fail','服务不可达',tagTitle('service_fail'));

  // Grade badge
  var gradeColors={'A':'#22c55e','B':'#10b981','C':'#eab308','D':'#f97316','F':'#ef4444'};
  var gradeLabels={'A':'最优','B':'目标可用','C':'基础可用','D':'不稳定','F':'失效'};
  var g=r.grade||'F';
  var gradeTag=tagHTML('','等级'+esc(g),getGradeTitle(g),'background:rgba(0,0,0,.3);color:'+(gradeColors[g]||'#888')+';font-weight:700');

  // IP tag
  var ipTag=r.ip?tagHTML('tag-ip','IP: '+esc(r.ip),tagTitle('ip')):'';
  var country=getResultCountry(r);
  var countryTag=country?tagHTML('tag-country','国家: '+esc(country),tagTitle('country')):'';
  // IP type tag
  var ipTypeTag='';
  if(r.ip_type==='datacenter') ipTypeTag=tagHTML('tag-dc','机房',getIpTypeTitle(r.ip_type));
  else if(r.ip_type==='residential') ipTypeTag=tagHTML('tag-res','住宅',getIpTypeTitle(r.ip_type));
  else if(r.ip) ipTypeTag=tagHTML('','类型未知',getIpTypeTitle(r.ip_type),'background:rgba(255,255,255,.06);color:#666');

  // CF bypass tag
  var cfTag='';
  if(hasCfDetection){
    if(r.cf_bypass) cfTag=tagHTML('tag-cf','&#9989; CF绕过',tagTitle('cf_ok'));
    else if(r.cf_challenge) cfTag=tagHTML('tag-cf-fail','&#10060; CF拦截('+esc(r.cf_challenge_type||'?')+')',tagTitle('cf_fail'));
    else cfTag=tagHTML('','CF未通过',tagTitle('cf_unknown'),'background:rgba(255,255,255,.06);color:#666');
  }

  // API tag
  var apiTag='';
  if(r.api_reachable===true) apiTag=tagHTML('tag-ok','API域名可达',tagTitle('api_ok'));
  else if(r.api_reachable===false) apiTag=tagHTML('tag-fail','API域名不可达',tagTitle('api_fail'));
  else if(profileInfo.has_api) apiTag=tagHTML('','API未检测',tagTitle('api_unknown'),'background:rgba(255,255,255,.06);color:#666');

  // Check count tag
  var chkTag='';
  if(r.checks_total!==undefined){
    var pct=(r.checks_passed||0)+"/"+r.checks_total;
    chkTag=r.valid?tagHTML('tag-ok',esc(pct),tagTitle('checks')):
           r.unstable?tagHTML('tag-unstable',esc(pct),tagTitle('checks')):
           tagHTML('tag-fail',esc(pct),tagTitle('checks'));
  }

  // Badge
  var badge=r.valid?tagHTML('tag-ok',esc(gradeLabels[g]||''),getFinalBadgeTitle(g,'valid')):
            r.unstable?tagHTML('tag-unstable','不稳定',getFinalBadgeTitle(g,'unstable')):
            tagHTML('tag-fail',esc(gradeLabels[g]||''),getFinalBadgeTitle(g,'invalid'));
  var repoBtn=type==='invalid'?'':'<button class="copy-btn" onclick="event.stopPropagation();addSingleResultToRepo(this)" data-p="'+esc(r.proxy)+'">添加到仓库</button>';

  // Detail panel (expandable)
  var detailId='detail_'+Math.random().toString(36).substr(2,8);
  var detailHTML='';
  if(r.checks_detail && Object.keys(r.checks_detail).length>0){
    var d=r.checks_detail;
    var rows='';
    if(d.service) rows+='<div class="detail-row"><span class="detail-key">服务:</span><span>'+(d.service.status||'-')+' '+(d.service.reachable?'<span style="color:#22c55e">可达</span>':'<span style="color:#ef4444">不可达</span>')+(d.service.cf_detected?' <span style="color:#ef4444">CF:'+esc(d.service.cf_type||'detected')+'</span>':'')+'</span></div>';
    else if(d.chat) rows+='<div class="detail-row"><span class="detail-key">首页:</span><span>'+(d.chat.status||'-')+(d.chat.cf_detected?' <span style="color:#ef4444">CF:'+esc(d.chat.cf_type||'detected')+'</span>':'')+'</span></div>';
    if(d.api) rows+='<div class="detail-row"><span class="detail-key">API域名:</span><span>'+(d.api.status||'-')+' '+(d.api.reachable?'<span style="color:#22c55e">可达</span>':'<span style="color:#ef4444">不可达</span>')+'</span></div>';
    if(d.ip_info) rows+='<div class="detail-row"><span class="detail-key">IP信息:</span><span>'+esc(d.ip_info.org||'')+' ('+esc(d.ip_info.country||'')+')</span></div>';
    if(r.cf_indicators && r.cf_indicators.length>0) rows+='<div class="detail-row"><span class="detail-key">CF特征:</span><span style="color:#ef4444">'+esc(r.cf_indicators.join(', '))+'</span></div>';
    detailHTML='<div class="detail-panel" id="'+detailId+'">'+rows+'</div>';
  }

  return '<div class="proxy-item '+type+'" data-lat="'+(r.latency||99999)+'" data-err="'+(err?"y":"n")+'" data-stable="'+(r.valid?"y":r.unstable?"u":"n")+'" data-service="'+(r.service_reachable?"y":"n")+'" data-api="'+(r.api_reachable===true?"y":"n")+'" data-ip="'+(r.ip?"y":"n")+'" data-cf="'+(r.cf_bypass?"y":"n")+'" data-cf-challenge="'+(r.cf_challenge_type||"")+'" data-grade="'+g+'" data-ip-type="'+(r.ip_type||"")+'" data-country="'+(country?"y":"n")+'" onclick="toggleDetail(\''+detailId+'\')">'+
    '<div style="flex:1;min-width:0">'+
    '<div class="proxy-addr">'+esc(r.proxy)+'</div>'+
    '<div class="proxy-meta">'+targetTag+gradeTag+useTag+chkTag+serviceTag+cfTag+ipTag+countryTag+ipTypeTag+apiTag+errTag+'</div>'+
    detailHTML+
    '</div>'+
    '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0">'+
    (r.latency?tagHTML('tag-lat','<span class="speed-dot '+spd+'"></span>'+esc(lat),tagTitle('latency')):'')+
    badge+
    repoBtn+
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

  var allR=V.concat(U).concat(F);
  var profile=getTargetProfileInfo(currentTargetProfile);
  if(profile.has_cf_detection){
    sCfBypass.textContent=allR.filter(function(r){return r.cf_bypass}).length;
  }else{
    sCfBypass.textContent=allR.filter(function(r){return r.service_reachable}).length;
  }
  sApiReachable.textContent=profile.has_api?
    allR.filter(function(r){return r.api_reachable===true}).length:
    allR.filter(function(r){return r.ip}).length;
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
  sCfBypass.textContent="0";sApiReachable.textContent="0";
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
    if(bar.id==='repoFilters'){
      filterRepoList(f);
      return;
    }
    var listId=bar.id==='vFilters'?'validList':'failList';
    document.querySelectorAll('#'+listId+' .proxy-item').forEach(function(item){
      var lat=parseInt(item.dataset.lat);
      var err=item.dataset.err;
      var stb=item.dataset.stable;
      var cf=item.dataset.cf;
      var service=item.dataset.service;
      var api=item.dataset.api;
      var ip=item.dataset.ip;
      var cfChal=item.dataset.cfChallenge;
      var show=true;
      if(listId==='validList'){
        if(f==='stable')show=stb==='y';
        else if(f==='unstable')show=stb==='u';
        else if(f==='cf_bypass')show=getTargetProfileInfo(currentTargetProfile).has_cf_detection?cf==='y':service==='y';
        else if(f==='api_or_ip')show=getTargetProfileInfo(currentTargetProfile).has_api?api==='y':ip==='y';
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

function filterRepoList(f){
  document.querySelectorAll('#repoList .proxy-item').forEach(function(item){
    var show=true;
    if(f==='grade_a')show=item.dataset.grade==='A';
    else if(f==='grade_b')show=item.dataset.grade==='B';
    else if(f==='grade_c')show=item.dataset.grade==='C';
    else if(f==='grade_d')show=item.dataset.grade==='D';
    else if(f==='service')show=item.dataset.service==='y';
    else if(f==='api')show=item.dataset.api==='y';
    else if(f==='cf')show=item.dataset.cf==='y';
    else if(f==='dc')show=item.dataset.ipType==='datacenter';
    else if(f==='res')show=item.dataset.ipType==='residential';
    else if(f==='country')show=item.dataset.country==='y';
    item.style.display=show?'flex':'none';
  });
}

function applyRepoFilter(){
  var active=document.querySelector('#repoFilters .fbtn.active');
  filterRepoList(active?active.dataset.f:'all');
}

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
  var changed=addRepoItems(filtered.map(resultToRepoItem));
  if(changed.added>0||changed.updated>0){
    toast('已同步仓库: 新增 '+changed.added+' 个，更新 '+changed.updated+' 个');
  }else{
    toast('仓库中已存在这些代理');
  }
}

// ============================================================
// [5] 我的仓库 — localStorage persistence
// ============================================================
var REPO_KEY='proxy_checker_repo';
var USER_TOKEN_KEY='proxy_checker_token';
var REPO_SYNCED_KEY='proxy_checker_synced';
var repoCache=null;
var userTokenCache=null;

function compactRepoItem(p){
  var item={proxy:String(p.proxy||'')};
  if(!item.proxy)return null;
  item.grade=p.grade||'?';
  if(p.latency!==undefined&&p.latency!==null)item.latency=p.latency;
  if(p.ip)item.ip=p.ip;
  if(p.country)item.country=String(p.country).toUpperCase();
  if(p.ip_type)item.ip_type=p.ip_type;
  if(p.service_reachable===true)item.service_reachable=true;
  if(p.api_reachable===true)item.api_reachable=true;
  if(p.cf_bypass)item.cf_bypass=true;
  if(p.recommended_use)item.recommended_use=p.recommended_use;
  if(p.target_profile)item.target_profile=p.target_profile;
  if(p.target_name)item.target_name=p.target_name;
  item.added=p.added||Date.now();
  item.updated=p.updated||item.added;
  return item;
}

function compactRepo(repo){
  var out=[];
  var seen={};
  (repo||[]).forEach(function(p){
    var item=compactRepoItem(p||{});
    if(!item||seen[item.proxy])return;
    seen[item.proxy]=true;
    out.push(item);
  });
  return out;
}

function getUserToken(){
  if(userTokenCache)return userTokenCache;
  var t='';
  try{t=localStorage.getItem(USER_TOKEN_KEY)||''}catch(e){}
  if(!t){
    t='user_'+Math.random().toString(36).substr(2,12);
    try{localStorage.setItem(USER_TOKEN_KEY,t)}catch(e){}
  }
  userTokenCache=t;
  return t;
}

// ============================================================
// Auto mode — backend scheduler controls
// ============================================================
function updateAutoAvailability(hint){
  var btn=document.getElementById('autoModeBtn');
  var badge=document.getElementById('autoStatusBadge');
  if(!btn||!badge)return;
  if(autoModeAvailable){
    btn.disabled=false;
    btn.title='后台按计划自动拉取、检测并更新仓库';
    badge.title='自动模式状态';
  }else{
    btn.disabled=true;
    btn.title=hint||'当前部署不支持后台自动模式';
    badge.className='auto-status-badge error';
    badge.textContent='自动不可用';
    badge.title=hint||'当前部署不支持后台自动模式';
  }
}

function formatAutoTime(ts,timezone){
  if(!ts)return '-';
  var d=new Date(Number(ts)*1000);
  if(isNaN(d.getTime()))return '-';
  var tz=timezone||appSettings.timezone||'UTC';
  try{
    return new Intl.DateTimeFormat('zh-CN',{
      timeZone:tz,
      year:'numeric',
      month:'2-digit',
      day:'2-digit',
      hour:'2-digit',
      minute:'2-digit',
      second:'2-digit',
      hour12:false
    }).format(d).replace(/\//g,'-');
  }catch(e){
    var pad=function(n){return n<10?'0'+n:String(n)};
    return d.getUTCFullYear()+'-'+pad(d.getUTCMonth()+1)+'-'+pad(d.getUTCDate())+' '+pad(d.getUTCHours())+':'+pad(d.getUTCMinutes());
  }
}

function getAutoTimezone(data){
  return (data&&data.config&&data.config.timezone)||appSettings.timezone||'UTC';
}

function getAutoProgressPercent(data){
  var state=(data&&data.state)||{};
  var total=Number(state.total||0);
  var done=Number(state.done||0);
  if(!state.running||total<=0)return 0;
  return Math.max(0,Math.min(100,Math.round(done/total*100)));
}

function autoStatusText(data){
  var state=(data&&data.state)||{};
  var config=(data&&data.config)||{};
  if(!autoModeAvailable)return '自动不可用';
  if(state.running){
    if(state.stage==='fetching')return '自动拉取中';
    if(state.stage==='loading_repo')return '自动合并中';
    if(state.stage==='stopping')return '自动停止中 '+(state.done||0)+'/'+(state.total||0);
    return '自动检测中 '+(state.done||0)+'/'+(state.total||0);
  }
  if(!config.enabled)return '自动未开启';
  if(state.status==='failed')return '自动上次失败';
  if(state.status==='interrupted')return '自动曾中断';
  if(state.status==='stopped')return '自动已停止';
  return '等待下次 '+formatAutoTime(state.next_run_at,getAutoTimezone(data));
}

function renderAutoStatus(data){
  if(!data)return;
  autoStatusCache=data;
  var badge=document.getElementById('autoStatusBadge');
  if(badge){
    var state=data.state||{};
    var config=data.config||{};
    var progress=getAutoProgressPercent(data);
    badge.textContent=autoStatusText(data);
    badge.style.setProperty('--auto-progress',progress+'%');
    badge.className='auto-status-badge';
    if(state.running)badge.classList.add('running');
    else if(config.enabled&&state.status!=='failed'&&state.status!=='interrupted')badge.classList.add('waiting');
    else if(state.status==='failed'||state.status==='interrupted')badge.classList.add('error');
    badge.title='进度: '+progress+'%，已拉取 '+(state.source_count||0)+'，仓库 '+(state.repo_count||0)+'，跳过 '+(state.skipped||0)+'，计划时区: '+getAutoTimezone(data);
  }
  var stopBtn=document.getElementById('autoStopBtn');
  if(stopBtn)stopBtn.disabled=!(data.state&&data.state.running);
  renderAutoProgress(data);
  if(data.state&&data.state.running)startAutoPolling(data.state.stage==='stopping'?1000:2500);
  else startAutoPolling(10000);
}

function processAutoRealtimeResults(data){
  if(!data)return;
  var state=data.state||{};
  var sessionId=state.session_id||autoSessionId;
  if(state.session_id&&state.session_id!==autoSessionId){
    autoSessionId=state.session_id;
    autoResultsIndex=0;
    autoRunResultKeys={};
    autoStopRepoPromptSession='';
  }
  var incoming=Array.isArray(data.new)?data.new:[];
  var changed=false;
  if(incoming.length){
    incoming.forEach(function(result){
      var key=resultKey(result);
      if(!key)return;
      autoRunResultKeys[key]=true;
      changed=upsertResult(result)||changed;
    });
    markCheckedBatch(incoming.map(function(r){return r.original||r.proxy}).filter(Boolean));
    saveCheckedLocal();
    syncCheckedToServer();
  }
  if(typeof data.results_index==='number')autoResultsIndex=data.results_index;
  if(changed){
    renderResultLists();
    updateStats();
    saveResults();
  }
  if(!state.running&&state.status==='stopped'){
    maybePromptAutoStoppedRepo(sessionId||autoStopRequestedSession);
  }
}

function getCurrentAutoRepoCandidates(){
  var all=V.concat(U);
  return all.filter(function(result){
    return !!autoRunResultKeys[resultKey(result)];
  });
}

function maybePromptAutoStoppedRepo(sessionId){
  var promptKey=sessionId||autoStopRequestedSession;
  if(!autoStopRequestedSession||!promptKey||autoStopRepoPromptSession===promptKey)return;
  autoStopRepoPromptSession=promptKey;
  autoStopRequestedSession='';
  var candidates=getCurrentAutoRepoCandidates();
  if(!candidates.length){
    toast('自动任务已停止，暂无可入库的有效结果');
    return;
  }
  if(!confirm('自动任务已停止，已检测到 '+candidates.length+' 条有效/不稳定代理。是否写入我的仓库并同步云端？'))return;
  var changed=addRepoItems(candidates.map(resultToRepoItem));
  toast('已写入仓库: 新增 '+changed.added+' 个，更新 '+changed.updated+' 个');
}

function startAutoPolling(delay){
  if(!autoModeAvailable||!authenticated)return;
  clearTimeout(autoStatusTimer);
  autoStatusTimer=setTimeout(loadAutoStatus,delay||5000);
}

function loadAutoStatus(callback){
  if(!autoModeAvailable||!authenticated){
    if(callback)callback(null);
    return;
  }
  post('/api/auto/status',{token:getUserToken(),since:autoResultsIndex,session_id:autoSessionId},function(err,res){
    if(!err&&res){
      processAutoRealtimeResults(res);
      renderAutoStatus(res);
      if(callback)callback(res);
    }else if(callback)callback(null);
  });
}

function autoProfileOptions(selected){
  return targetProfiles.map(function(profile){
    return '<option value="'+esc(profile.id)+'" '+(profile.id===selected?'selected':'')+'>'+esc(profile.name)+'</option>';
  }).join('');
}

function timezoneOptions(selected){
  var options=appSettings.timezone_options||[{id:'UTC',name:'UTC'}];
  selected=selected||appSettings.timezone||'UTC';
  return options.map(function(item){
    return '<option value="'+esc(item.id)+'" '+(item.id===selected?'selected':'')+'>'+esc(item.name||item.id)+' · '+esc(item.id)+'</option>';
  }).join('');
}

function renderAutoProgress(data){
  var box=document.getElementById('autoProgress');
  if(!box||!data)return;
  var state=data.state||{};
  var config=data.config||{};
  var tz=getAutoTimezone(data);
  var stageMap={
    starting:'准备启动',
    fetching:'拉取免费代理',
    loading_repo:'合并仓库代理',
    detecting:'批量检测',
    updating_repo:'更新仓库',
    stopping:'正在停止',
    completed:'已完成',
    stopped:'已停止',
    failed:'失败',
    interrupted:'已中断',
    idle:'等待中',
    disabled:'未开启'
  };
  var html='';
  html+='<div>状态: '+esc(autoStatusText(data))+'</div>';
  html+='<div>阶段: '+esc(stageMap[state.stage]||state.stage||'-')+'</div>';
  html+='<div>计划时区: '+esc(tz)+'</div>';
  html+='<div>当前时间: '+esc((data.server_time&&data.server_time.text)||formatAutoTime((data.server_time&&data.server_time.timestamp),tz))+'</div>';
  if(data.server_time&&data.server_time.server_text&&data.server_time.server_text!==data.server_time.text)html+='<div>服务器本地: '+esc(data.server_time.server_text)+' '+esc(data.server_time.server_timezone||'')+'</div>';
  if(config.enabled)html+='<div>下次执行: '+esc(state.next_run_text||formatAutoTime(state.next_run_at,tz))+'</div>';
  if(state.running){
    html+='<div>进度: '+(state.done||0)+'/'+(state.total||0)+'，有效 '+(state.valid_count||0)+'，不稳定 '+(state.unstable_count||0)+'，失效 '+(state.invalid_count||0)+'</div>';
    html+='<div>已拉取 '+(state.source_count||0)+'，仓库 '+(state.repo_count||0)+'，去重后 '+(state.input_count||0)+'，跳过已检测 '+(state.skipped||0)+'</div>';
  }
  if(state.last_summary){
    var s=state.last_summary;
    html+='<div>上次: '+esc(s.status||'-')+'，检测 '+(s.done||0)+'/'+(s.total||0)+'，入库 +'+(s.repo_added||0)+'，更新 '+(s.repo_updated||0)+'，删除 '+(s.repo_removed||0)+'</div>';
    if(s.error)html+='<div style="color:#ef4444">错误: '+esc(s.error)+'</div>';
  }
  if(Array.isArray(state.history)&&state.history.length){
    html+='<div class="auto-history">';
    state.history.slice(-5).reverse().forEach(function(item){
      html+='<div>'+esc(formatAutoTime(item.finished_at,item.timezone||tz))+' · '+esc(item.status||'-')+' · '+(item.done||0)+'/'+(item.total||0)+' · 有效 '+(item.valid_count||0)+'</div>';
    });
    html+='</div>';
  }
  box.innerHTML=html;
}

function openAutoSettings(){
  if(!requireAuthenticatedUI())return;
  if(!autoModeAvailable){
    toast('当前部署不支持后台自动模式');
    return;
  }
  post('/api/auto/get',{token:getUserToken(),since:autoResultsIndex,session_id:autoSessionId},function(err,res){
    if(err||res.error){
      toast(err||res.error||'读取自动模式失败');
      return;
    }
    processAutoRealtimeResults(res);
    renderAutoStatus(res);
    showAutoModal(res);
  });
}

function showAutoModal(data){
  var config=(data&&data.config)||{};
  var state=(data&&data.state)||{};
  var overlay=document.createElement('div');
  overlay.className='modal-overlay show';
  overlay.onclick=function(e){if(e.target===overlay)overlay.remove()};
  var html='<div class="modal-box" style="max-width:640px;text-align:left">';
  html+='<div class="modal-icon" style="background:linear-gradient(135deg,rgba(34,197,94,.15),rgba(34,197,94,.05));border-color:rgba(34,197,94,.22)">⏱️</div>';
  html+='<h3 style="text-align:center">自动模式</h3>';
  html+='<div class="auto-progress" id="autoProgress"></div>';
  html+='<div class="settings-note">启用后台自动检测：保存后服务器会按时间规则自动跑，不需要浏览器一直打开。立即运行：不等下次计划时间，马上跑一轮；是否启用定时由上面的勾选决定。</div>';
  html+='<div class="auto-form">';
  html+='<div class="auto-field full"><label><input id="autoEnabled" type="checkbox" '+(config.enabled?'checked':'')+' style="width:auto;height:auto;margin-right:8px">启用后台自动检测</label></div>';
  html+='<div class="auto-field"><label>时间规则</label><select id="autoScheduleType" onchange="updateAutoScheduleFields()"><option value="interval" '+(config.schedule_type==='interval'?'selected':'')+'>每隔 N 小时</option><option value="daily" '+(config.schedule_type==='daily'?'selected':'')+'>每天固定时间</option></select></div>';
  html+='<div class="auto-field" id="autoIntervalField"><label>间隔小时</label><input id="autoIntervalHours" type="number" min="0.01" max="720" step="0.25" value="'+esc(config.interval_hours||6)+'"></div>';
  html+='<div class="auto-field" id="autoDailyField"><label>固定时间（计划时区）</label><input id="autoDailyTime" type="time" value="'+esc(config.daily_time||'03:00')+'"></div>';
  html+='<div class="auto-field"><label>计划时区</label><select id="autoTimezone">'+timezoneOptions(config.timezone||appSettings.timezone)+'</select></div>';
  html+='<div class="auto-field"><label>检测模式</label><select id="autoTargetProfile">'+autoProfileOptions(config.target_profile||currentTargetProfile)+'</select></div>';
  html+='<div class="auto-field"><label>检测范围</label><select id="autoDetectMode"><option value="skip">只检测新代理</option><option value="force">强制检测全部</option></select></div>';
  html+='<div class="auto-field full"><label>入库策略</label><select id="autoRepoPolicy"><option value="stable_only">只入库稳定可用(A/B/C)，复测失败旧代理会删除</option><option value="include_unstable">包含不稳定(A/B/C/D)，复测失败旧代理会删除</option><option value="archive_all">所有结果都留档，失效代理也保留</option></select></div>';
  html+='<div class="auto-field full"><div class="settings-note">本轮自动检测使用全局设置：'+esc(getRoundsValue())+' 轮，并发 '+esc(getConcurrentValue())+'。要修改请打开“设置”。</div></div>';
  html+='</div>';
  html+='<div class="auto-inline" style="justify-content:center;margin-top:12px">';
  html+='<button class="btn btn-primary" onclick="saveAutoSettings()">保存设置</button>';
  html+='<button class="btn btn-ghost" onclick="runAutoNow()">立即运行</button>';
  html+='<button class="btn btn-danger" id="autoStopBtn" onclick="stopAutoNow()" '+(state.running?'':'disabled')+'>停止自动任务</button>';
  html+='<button class="btn btn-ghost" onclick="this.closest(\'.modal-overlay\').remove()">关闭</button>';
  html+='</div></div>';
  overlay.innerHTML=html;
  document.body.appendChild(overlay);
  document.getElementById('autoDetectMode').value=config.detect_mode||'skip';
  document.getElementById('autoRepoPolicy').value=config.repo_update_policy||'stable_only';
  updateAutoScheduleFields();
  renderAutoProgress(data);
}

function updateAutoScheduleFields(){
  var type=document.getElementById('autoScheduleType');
  var interval=document.getElementById('autoIntervalField');
  var daily=document.getElementById('autoDailyField');
  if(!type||!interval||!daily)return;
  interval.style.display=type.value==='interval'?'flex':'none';
  daily.style.display=type.value==='daily'?'flex':'none';
}

function readAutoConfigFromModal(){
  return {
    enabled:!!document.getElementById('autoEnabled').checked,
    schedule_type:document.getElementById('autoScheduleType').value,
    interval_hours:parseFloat(document.getElementById('autoIntervalHours').value)||6,
    daily_time:document.getElementById('autoDailyTime').value||'03:00',
    timezone:document.getElementById('autoTimezone').value||appSettings.timezone||'UTC',
    target_profile:document.getElementById('autoTargetProfile').value,
    rounds:getRoundsValue(),
    max_concurrent:getConcurrentValue(),
    detect_mode:document.getElementById('autoDetectMode').value,
    repo_update_policy:document.getElementById('autoRepoPolicy').value
  };
}

function saveAutoSettings(){
  var config=readAutoConfigFromModal();
  post('/api/auto/save',{token:getUserToken(),config:config},function(err,res){
    if(err||res.error){toast('保存失败: '+(err||res.error));return}
    renderAutoStatus(res);
    toast('自动模式设置已保存');
  });
}

function runAutoNow(){
  var config=readAutoConfigFromModal();
  post('/api/auto/save',{token:getUserToken(),config:config},function(saveErr,saveRes){
    if(saveErr||saveRes.error){toast('保存失败: '+(saveErr||saveRes.error));return}
    post('/api/auto/run-now',{token:getUserToken()},function(err,res){
      if(err||res.error){toast(err||res.error||'启动失败');if(res)renderAutoStatus(res);return}
      autoResultsIndex=0;
      autoSessionId=(res.state&&res.state.session_id)||'';
      autoRunResultKeys={};
      autoStopRequestedSession='';
      autoStopRepoPromptSession='';
      renderAutoStatus(res);
      toast(res.started?'自动任务已启动':'自动任务已在运行');
    });
  });
}

function stopAutoNow(){
  var state=(autoStatusCache&&autoStatusCache.state)||{};
  autoStopRequestedSession=state.session_id||autoSessionId||('auto_stop_'+Date.now());
  post('/api/auto/stop',{token:getUserToken(),since:autoResultsIndex,session_id:autoSessionId},function(err,res){
    if(err){toast(err);return}
    processAutoRealtimeResults(res);
    renderAutoStatus(res);
    toast(res.stopped?'已请求停止自动任务':'当前没有自动任务');
  });
}

// ============================================================
// Global settings and run logs
// ============================================================
function openAppSettings(){
  if(!requireAuthenticatedUI())return;
  post('/api/settings/get',{},function(err,res){
    if(err||res.error){toast(err||res.error||'读取设置失败');return}
    if(res.settings)applyAppSettings(res.settings);
    showSettingsModal(res.settings||appSettings);
  });
}

function settingsRoundsOptions(selected){
  var max=appSettings.max_check_rounds||3;
  selected=normalizeRounds(selected||appSettings.check_rounds||2);
  var html='';
  for(var i=1;i<=max;i++){
    html+='<option value="'+i+'" '+(i===selected?'selected':'')+'>'+i+'轮'+(i===2?'（推荐）':'')+'</option>';
  }
  return html;
}

function showSettingsModal(settings){
  settings=Object.assign({},appSettings,settings||{});
  var overlay=document.createElement('div');
  overlay.className='modal-overlay show';
  overlay.onclick=function(e){if(e.target===overlay)overlay.remove()};
  var html='<div class="modal-box" style="max-width:720px;text-align:left">';
  html+='<div class="modal-icon" style="background:linear-gradient(135deg,rgba(124,92,252,.16),rgba(124,92,252,.05));border-color:rgba(124,92,252,.22)">⚙️</div>';
  html+='<h3 style="text-align:center">设置</h3>';
  html+='<div class="settings-note">这里保存的是服务运行参数。轮次默认最多 3 轮，轮次越高越慢；并发越高越快，但服务器和代理源压力也越大。</div>';
  html+='<div class="auto-form">';
  html+='<div class="auto-field"><label>检测轮次</label><select id="settingsRounds">'+settingsRoundsOptions(settings.check_rounds)+'</select></div>';
  html+='<div class="auto-field"><label>默认并发</label><input id="settingsConcurrent" type="number" min="1" max="'+esc(settings.max_concurrent_limit||200)+'" step="1" value="'+esc(settings.max_concurrent||30)+'"></div>';
  html+='<div class="auto-field"><label>并发上限</label><input id="settingsConcurrentLimit" type="number" min="1" max="1000" step="1" value="'+esc(settings.max_concurrent_limit||200)+'"></div>';
  html+='<div class="auto-field"><label>请求超时（秒）</label><input id="settingsTimeout" type="number" min="3" max="120" step="1" value="'+esc(settings.timeout||12)+'"></div>';
  html+='<div class="auto-field"><label>协议识别超时（秒）</label><input id="settingsDetectTimeout" type="number" min="3" max="120" step="1" value="'+esc(settings.detect_timeout||8)+'"></div>';
  html+='<div class="auto-field"><label>登录有效天数</label><input id="settingsSessionDays" type="number" min="1" max="365" step="1" value="'+esc(settings.auth_session_days||7)+'"></div>';
  html+='<div class="auto-field"><label>日志保留条数</label><input id="settingsLogLimit" type="number" min="20" max="1000" step="10" value="'+esc(settings.run_log_limit||100)+'"></div>';
  html+='<div class="auto-field full"><label>默认时区</label><select id="settingsTimezone">'+timezoneOptions(settings.timezone||appSettings.timezone)+'</select></div>';
  html+='<div class="auto-field full"><label>新登录密码</label><input id="settingsPassword" type="password" autocomplete="new-password" placeholder="'+(settings.password_configurable?'留空表示不修改':'当前由环境变量控制，页面不能永久修改')+'" '+(settings.password_configurable?'':'disabled')+'></div>';
  html+='<div class="auto-field full"><label>确认新密码</label><input id="settingsPasswordConfirm" type="password" autocomplete="new-password" placeholder="再次输入新密码" '+(settings.password_configurable?'':'disabled')+'></div>';
  html+='</div>';
  html+='<div class="auto-inline" style="justify-content:center;margin-top:12px">';
  html+='<button class="btn btn-primary" onclick="saveAppSettings()">保存设置</button>';
  html+='<button class="btn btn-ghost" onclick="this.closest(\'.modal-overlay\').remove()">关闭</button>';
  html+='</div></div>';
  overlay.innerHTML=html;
  document.body.appendChild(overlay);
}

function readSettingsFromModal(){
  var password=document.getElementById('settingsPassword').value;
  var confirm=document.getElementById('settingsPasswordConfirm').value;
  if(password||confirm){
    if(password!==confirm){
      toast('两次输入的新密码不一致');
      return null;
    }
    if(password.length<4){
      toast('新密码至少 4 位');
      return null;
    }
  }
  return {
    check_rounds:parseInt(document.getElementById('settingsRounds').value)||2,
    max_check_rounds:3,
    max_concurrent:parseInt(document.getElementById('settingsConcurrent').value)||30,
    max_concurrent_limit:parseInt(document.getElementById('settingsConcurrentLimit').value)||200,
    timeout:parseInt(document.getElementById('settingsTimeout').value)||12,
    detect_timeout:parseInt(document.getElementById('settingsDetectTimeout').value)||8,
    auth_session_days:parseInt(document.getElementById('settingsSessionDays').value)||7,
    run_log_limit:parseInt(document.getElementById('settingsLogLimit').value)||100,
    timezone:document.getElementById('settingsTimezone').value||'UTC',
    auth_password:password||''
  };
}

function saveAppSettings(){
  var settings=readSettingsFromModal();
  if(!settings)return;
  post('/api/settings/save',{settings:settings},function(err,res){
    if(err||res.error){toast(err||res.error||'保存设置失败');return}
    if(res.token)localStorage.setItem(AUTH_TOKEN_KEY,res.token);
    applyAppSettings(res.settings||settings);
    if(autoStatusCache)renderAutoStatus(autoStatusCache);
    toast(res.password_changed?'设置已保存，登录密码已更新':'设置已保存');
  });
}

function openRunLogs(){
  if(!requireAuthenticatedUI())return;
  post('/api/logs/list',{token:getUserToken()},function(err,res){
    if(err||res.error){toast(err||res.error||'读取检测日志失败');return}
    showRunLogsModal(res.logs||[]);
  });
}

function logStatusLabel(status){
  var map={running:'运行中',completed:'已完成',stopped:'已停止',failed:'失败',interrupted:'已中断'};
  return map[status]||status||'-';
}

function showRunLogsModal(logs){
  var overlay=document.createElement('div');
  overlay.className='modal-overlay show';
  overlay.onclick=function(e){if(e.target===overlay)overlay.remove()};
  var html='<div class="modal-box" style="max-width:820px;text-align:left">';
  html+='<div class="modal-icon" style="background:linear-gradient(135deg,rgba(96,165,250,.16),rgba(96,165,250,.05));border-color:rgba(96,165,250,.22)">📋</div>';
  html+='<h3 style="text-align:center">检测日志</h3>';
  html+='<div class="settings-note">记录手动检测和自动任务的开始时间、结束时间、模式、轮次、并发、数量和结果摘要。</div>';
  html+='<div class="log-list" id="runLogList">';
  if(!logs.length){
    html+='<div class="empty">还没有检测日志</div>';
  }else{
    logs.forEach(function(item){
      var title=(item.type==='auto'?'⏱️ 自动任务':'▶ 手动检测')+' · '+logStatusLabel(item.status);
      html+='<div class="log-item">';
      html+='<div class="log-title"><span>'+esc(title)+'</span><span>'+esc(item.started_text||formatAutoTime(item.started_at,item.timezone||appSettings.timezone))+'</span></div>';
      html+='<div>结束: '+esc(item.finished_text||formatAutoTime(item.finished_at,item.timezone||appSettings.timezone))+' · 耗时: '+esc(item.duration_seconds!==undefined?item.duration_seconds+'秒':'-')+'</div>';
      html+='<div class="log-meta">';
      html+='<span class="log-pill">'+esc(item.target_name||item.target_profile||'常规代理检测')+'</span>';
      html+='<span class="log-pill">'+esc(item.rounds||'-')+'轮</span>';
      html+='<span class="log-pill">并发 '+esc(item.max_concurrent||'-')+'</span>';
      if(item.schedule_type)html+='<span class="log-pill">'+esc(item.schedule_type==='daily'?'每天固定':'间隔执行')+'</span>';
      if(item.timezone)html+='<span class="log-pill">'+esc(item.timezone)+'</span>';
      html+='<span class="log-pill">检测 '+esc(item.done||0)+'/'+esc(item.total||0)+'</span>';
      html+='<span class="log-pill">有效 '+esc(item.valid_count||0)+'</span>';
      html+='<span class="log-pill">不稳定 '+esc(item.unstable_count||0)+'</span>';
      html+='<span class="log-pill">失效 '+esc(item.invalid_count||0)+'</span>';
      if(item.repo_added!==undefined)html+='<span class="log-pill">入库 +'+esc(item.repo_added||0)+'</span>';
      if(item.repo_removed!==undefined)html+='<span class="log-pill">删除 '+esc(item.repo_removed||0)+'</span>';
      html+='</div>';
      if(item.error)html+='<div style="color:#ef4444;margin-top:4px">错误: '+esc(item.error)+'</div>';
      html+='</div>';
    });
  }
  html+='</div>';
  html+='<div class="auto-inline" style="justify-content:center;margin-top:12px">';
  html+='<button class="btn btn-danger" onclick="clearRunLogs()">清空日志</button>';
  html+='<button class="btn btn-ghost" onclick="openRunLogs();this.closest(\'.modal-overlay\').remove()">刷新</button>';
  html+='<button class="btn btn-ghost" onclick="this.closest(\'.modal-overlay\').remove()">关闭</button>';
  html+='</div></div>';
  overlay.innerHTML=html;
  document.body.appendChild(overlay);
}

function clearRunLogs(){
  if(!confirm('确定清空检测日志？'))return;
  post('/api/logs/clear',{token:getUserToken()},function(err,res){
    if(err||res.error){toast(err||res.error||'清空失败');return}
    var modal=document.querySelector('.modal-overlay.show');
    if(modal)modal.remove();
    showRunLogsModal(res.logs||[]);
    toast('检测日志已清空');
  });
}

function syncRepoToServer(repoOverride){
  if(!requireAuthenticatedUI())return;
  var repo=compactRepo(repoOverride||loadRepo());
  var token=getUserToken();
  post('/api/repo/save',{repo:repo,token:token},function(err,res){
    if(!err&&res.ok){
      try{localStorage.setItem(REPO_SYNCED_KEY,JSON.stringify({count:res.count,time:Date.now()}))}catch(e){}
    }
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
        var repo=lines.map(function(p){return {proxy:p,grade:'?',latency:null,ip:null,country:null,ip_type:null,service_reachable:null,api_reachable:null,cf_bypass:false,recommended_use:'generic',target_profile:'generic',target_name:'常规代理检测',added:Date.now()}});
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

function restoreActiveSession(){
  var raw=localStorage.getItem(ACTIVE_SESSION_KEY);
  if(!raw)return false;
  var active;
  try{active=JSON.parse(raw)}catch(e){clearActiveSession();return false}
  if(!active||!active.session_id){clearActiveSession();return false}
  sid=active.session_id;
  currentTargetProfile=active.target_profile||currentTargetProfile;
  localStorage.setItem(TARGET_PROFILE_KEY,currentTargetProfile);
  if(active.input&&parseLines(proxyInput.value).length===0){
    proxyInput.value=active.input;
    updateProxyCount();
  }
  if(active.rounds)roundsSelect.value=String(normalizeRounds(active.rounds));
  if(active.max_concurrent&&concurrentInput){
    concurrentInput.value=String(normalizeConcurrent(active.max_concurrent));
    localStorage.setItem(CONCURRENT_KEY,concurrentInput.value);
  }
  updateTargetProfileUI();
  busy=true;
  totalCount=active.total||V.length+U.length+F.length;
  resultsIndex=V.length+U.length+F.length;
  checkBtn.disabled=true;
  document.getElementById('stopBtn').style.display="inline-flex";
  prog.style.display="block";
  var pct=totalCount>0?Math.round(resultsIndex/totalCount*100):0;
  progBar.style.width=pct+"%";
  statusText.textContent="已恢复检测进度 "+resultsIndex+"/"+totalCount;
  poll();
  return true;
}

function loadRepo(){
  if(repoCache)return repoCache;
  try{
    repoCache=compactRepo(JSON.parse(localStorage.getItem(REPO_KEY))||[]);
    return repoCache;
  }catch(e){
    repoCache=[];
    return repoCache;
  }
}
function saveRepo(repo,options){
  options=options||{};
  repoCache=compactRepo(repo);
  var json=JSON.stringify(repoCache);
  var localSaved=false;
  try{
    localStorage.setItem(REPO_KEY,json);
    localSaved=true;
  }catch(e){
    try{
      localStorage.removeItem(RESULTS_KEY);
      localStorage.setItem(REPO_KEY,json);
      localSaved=true;
    }catch(e2){
      try{localStorage.removeItem(REPO_KEY)}catch(e3){}
      if(!saveRepo._quotaWarned){
        toast('仓库太大，本地缓存已跳过，仍会同步到云端');
        saveRepo._quotaWarned=true;
      }
    }
  }
  if(options.sync!==false){
    clearTimeout(saveRepo._timer);
    saveRepo._timer=setTimeout(function(){syncRepoToServer(repoCache)},1000);
  }
  return localSaved;
}

function resultToRepoItem(r){
  return {
    proxy:r.proxy,
    grade:r.grade||'F',
    latency:r.latency,
    ip:r.ip,
    country:getResultCountry(r),
    ip_type:r.ip_type,
    service_reachable:r.service_reachable,
    api_reachable:r.api_reachable,
    cf_bypass:r.cf_bypass,
    recommended_use:r.recommended_use,
    target_profile:r.target_profile||currentTargetProfile,
    target_name:r.target_name||getTargetProfileInfo(currentTargetProfile).name,
    added:Date.now(),
    updated:Date.now()
  };
}

function addRepoItems(items){
  if(!items.length)return {added:0,updated:0};
  try{localStorage.removeItem('repo_manually_cleared')}catch(e){}
  var repo=loadRepo();
  var indexByProxy={};
  repo.forEach(function(p,i){indexByProxy[p.proxy]=i});
  var added=0;
  var updated=0;
  items.forEach(function(item){
    var idx=indexByProxy[item.proxy];
    if(idx===undefined){
      repo.push(item);
      indexByProxy[item.proxy]=repo.length-1;
      added++;
    }else{
      item.added=repo[idx].added||item.added;
      repo[idx]=Object.assign({},repo[idx],item);
      updated++;
    }
  });
  saveRepo(repo);
  renderRepo();
  return {added:added,updated:updated};
}

function addSingleResultToRepo(button){
  var proxy=button.dataset.p;
  var result=getResultByProxy(proxy);
  if(!result){toast('这个代理不在有效列表里');return}
  var changed=addRepoItems([resultToRepoItem(result)]);
  if(changed.added>0)toast('已添加到仓库，稍后自动同步云端');
  else toast('仓库已更新，稍后自动同步云端');
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
  var displayRepo=repo.map(function(p,i){return {item:p,index:i}}).sort(function(a,b){
    return (b.item.updated||b.item.added||0)-(a.item.updated||a.item.added||0);
  });
  displayRepo.forEach(function(entry){
    var p=entry.item;
    var i=entry.index;
    var gradeColors={'A':'#22c55e','B':'#10b981','C':'#eab308','D':'#f97316','F':'#ef4444'};
    var gradeLabels={'A':'最优','B':'目标可用','C':'基础可用','D':'不稳定','F':'失效','?':'待判断'};
    var g=p.grade||'F';
    var lat=p.latency?p.latency+'ms':'-';
    var spd=p.latency?(p.latency<1000?"speed-fast":p.latency<3000?"speed-mid":"speed-slow"):"";
    var country=p.country?String(p.country).toUpperCase():'';
    html+='<div class="proxy-item valid" data-lat="'+(p.latency||99999)+'" data-grade="'+g+'" data-service="'+(p.service_reachable===true?"y":"n")+'" data-api="'+(p.api_reachable===true?"y":"n")+'" data-cf="'+(p.cf_bypass?"y":"n")+'" data-ip-type="'+(p.ip_type||"")+'" data-country="'+(country?"y":"n")+'">'+
      '<div style="flex:1;min-width:0">'+
      '<div class="proxy-addr">'+esc(p.proxy)+'</div>'+
      '<div class="proxy-meta">'+
      (p.target_name?tagHTML('',esc(p.target_name),tagTitle('target',p.target_name),'background:rgba(255,255,255,.06);color:#aaa'):'')+
      tagHTML('','等级'+esc(g),getGradeTitle(g),'background:rgba(0,0,0,.3);color:'+(gradeColors[g]||'#888')+';font-weight:700')+
      (p.recommended_use?tagHTML('tag-ok',esc(getRecommendedUseLabel(p.recommended_use)),getRecommendedUseTitle(p.recommended_use)):'')+
      (p.service_reachable===true?tagHTML('tag-ok','服务可达',tagTitle('service_ok')):'')+
      (p.api_reachable===true?tagHTML('tag-ok','API域名可达',tagTitle('api_ok')):'')+
      (country?tagHTML('tag-country','国家: '+esc(country),tagTitle('country')):'')+
      (p.ip_type==='datacenter'?tagHTML('tag-dc','机房',getIpTypeTitle(p.ip_type)):p.ip_type==='residential'?tagHTML('tag-res','住宅',getIpTypeTitle(p.ip_type)):'')+
      (p.cf_bypass?tagHTML('tag-cf','CF绕过',tagTitle('cf_ok')):'')+
      '</div></div>'+
      '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0">'+
      (p.latency?tagHTML('tag-lat','<span class="speed-dot '+spd+'"></span>'+esc(lat),tagTitle('latency')):'')+
      tagHTML('tag-ok',esc(gradeLabels[g]||''),getFinalBadgeTitle(g,g==='D'?'unstable':g==='F'?'invalid':'valid'))+
      '<button class="copy-btn" style="opacity:0.6" onclick="event.stopPropagation();clip(this)" data-p="'+esc(p.proxy)+'">复制</button>'+
      '<button class="copy-btn" style="opacity:0.6;color:#ef4444" onclick="event.stopPropagation();removeFromRepo('+i+')">删除</button>'+
      '</div></div>';
  });
  list.innerHTML=html;
  list.style.maxHeight='420px';
  list.style.overflowY='auto';
  applyRepoFilter();
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

function recheckRepo(){
  if(busy){toast('正在检测中，请先停止当前任务');return}
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空');return}
  var proxies=repo.map(function(p){return p.proxy}).filter(function(p){return p&&p.trim()});
  if(!proxies.length){toast('仓库没有可检测的代理');return}
  proxyInput.value=proxies.join("\n");
  updateProxyCount();
  switchTab('valid');
  startCheck({force:true});
}

function restoreRepoFromCloud(){
  if(!requireAuthenticatedUI())return;
  var local=loadRepo();
  if(local.length>0 && !confirm('清空本地仓库并从云端恢复？'))return;
  try{localStorage.removeItem('repo_manually_cleared')}catch(e){}
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
  if(!requireAuthenticatedUI())return;
  document.getElementById('repoCloudDropdown').classList.remove('open');
  try{localStorage.removeItem('repo_manually_cleared')}catch(e){}
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空，无需保存');return}
  var token=getUserToken();
  post('/api/repo/save',{repo:repo,token:token},function(err,res){
    if(err){toast('保存失败: '+err);return}
    if(res.ok){
      try{localStorage.setItem(REPO_SYNCED_KEY,JSON.stringify({count:res.count,time:Date.now()}))}catch(e){}
      toast('已保存 '+res.count+' 个代理到云端');
    }
  });
}

function clearRepo(){
  if(!loadRepo().length){toast('仓库已经是空的');return}
  if(!confirm('确定清空本地仓库？\n注意：云端数据不会被删除，可随时通过「恢复云端数据」恢复。'))return;
  repoCache=[];
  try{localStorage.removeItem(REPO_KEY)}catch(e){}
  try{localStorage.setItem('repo_manually_cleared','1')}catch(e){}
  renderRepo();
  toast('本地仓库已清空（云端数据保留）');
}

function importRepoTxt(input){
  try{localStorage.removeItem('repo_manually_cleared')}catch(e){}
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
        repo.push({proxy:proxy,grade:"?",latency:null,ip:null,country:null,ip_type:null,service_reachable:null,api_reachable:null,cf_bypass:false,recommended_use:'generic',target_profile:'generic',target_name:'常规代理检测',added:Date.now()});
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
restoreActiveSession();

// Get repo link — sync to server and show URL
function getRepoLink(button){
  if(!requireAuthenticatedUI())return;
  var repo=loadRepo();
  if(!repo.length){toast('仓库为空');return}
  var token=getUserToken();
  var btn=button||(typeof event!=='undefined'?event.target:null);
  if(btn){
    btn.innerHTML='&#128279; 同步中...';
    btn.disabled=true;
  }
  post('/api/repo/save',{repo:repo,token:token},function(err,res){
    if(btn){
      btn.innerHTML='&#128279; 获取仓库链接';
      btn.disabled=false;
    }
    if(err||res.error){toast('同步失败: '+(err||res.error));return}
    var url=API_BASE+'/api/repo/'+token+'.txt';
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
    var html='<div class="fetch-menu-item" onclick="doFetchProxies(\'all\')">&#9889; 一键拉取所有免费代理</div>';
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
  if(!requireAuthenticatedUI())return;
  fetchDropdown.classList.remove('open');
  var btn=document.getElementById('fetchBtn');
  var origText=btn.innerHTML;
  btn.innerHTML='&#8987; 拉取中...';
  btn.disabled=true;
  statusText.textContent='正在从 '+(sourceId==='all'?'所有免费代理源':sourceId)+' 拉取代理...';
  post('/api/fetch-proxies',{source:sourceId,limit:50000},function(err,res){
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
