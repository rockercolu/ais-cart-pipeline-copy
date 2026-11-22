'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let setup=null,account=null,revision=0,inventory=[],history=[];
let pendingCheck=null,checkoutRequest=null,renderRun=0,sessionRun=0;
async function api(action,method='GET',body){
 const response=await fetch('/api/pilot?action='+action,{method,headers:{'Content-Type':'application/json'},credentials:'same-origin',...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();if(!response.ok)throw Object.assign(new Error(data.error?.message||'The request could not be completed.'),{status:response.status});return data;
}
function message(text){$('message').textContent=text;$('message').hidden=false;}
function offer(){const item=setup.offer;$('offerName').textContent=item.name;$('offerCredits').textContent=item.credits;$('offerAmount').textContent=new Intl.NumberFormat('en-US',{style:'currency',currency:item.currency}).format(item.amount/100);}
function showAccount(){
 $('signinCard').hidden=!!account;$('accountCard').hidden=!account;$('workbench').hidden=!account;$('historyCard').hidden=!account;
 $('checkout').disabled=!account||!setup.checkoutConfigured;
 $('checkout').textContent=!setup.checkoutConfigured?'Payment setup pending':account?'Open Stripe sandbox checkout':'Sign in to test checkout';
 $('checkoutHint').textContent=!setup.checkoutConfigured?'The sample offer is ready for review. Payment services still need connecting.':account?'Test payments only. Never enter a real card in a sandbox checkout.':'Sign in first so test credits reach your account.';
 if(account){$('who').textContent=account.user.email||'Signed in';$('credits').textContent=account.credits;$('analyze').disabled=account.credits<1;}
}
async function refresh(){
 const run=sessionRun;
 try{const session=await api('session');const saved=await api('inventory');const recent=await api('history');
  if(run!==sessionRun)return;
  account=session;inventory=saved.tools;revision=saved.revision;$('tools').value=inventory.join('\n');history=recent.checks;renderHistory();}
 catch(error){if(run!==sessionRun)return;if(error.status!==401)message(error.message);account=null;}
 showAccount();
}
async function authenticate(action){
 const password=$('password').value;
 if(!$('authForm').reportValidity())return;
 $('login').disabled=$('signup').disabled=true;
 try{const data=await api(action,'POST',{email:$('email').value,password});$('password').value='';message(data.confirmationRequired?data.message:'You’re signed in. Your sandbox balance starts at zero.');if(!data.confirmationRequired)await refresh();}
 catch(error){message(error.message);}finally{$('login').disabled=$('signup').disabled=!setup.accountsConfigured;}
}
$('authForm').onsubmit=event=>{event.preventDefault();authenticate('login');};$('signup').onclick=()=>authenticate('signup');
$('logout').onclick=async()=>{sessionRun++;try{await api('logout','POST',{});account=null;history=[];renderRun++;$('history').textContent='';$('answer').textContent='';$('tools').value='';$('preview').hidden=true;$('screenshot').value='';pendingCheck=null;showAccount();message('Signed out.');}catch(error){message(error.message);}};
$('saveTools').onclick=async()=>{try{const tools=[...new Set($('tools').value.split('\n').map(x=>x.trim()).filter(Boolean))];const saved=await api('inventory','PUT',{tools,revision});inventory=saved.tools;revision=saved.revision;message('Tools saved to your account.');}catch(error){message(error.message+' Refresh account to load the latest saved inventory.');}};
$('importTools').onclick=()=>{try{$('tools').value=JSON.parse(localStorage.getItem('aiscart-owned-tools')||'[]').filter(x=>typeof x==='string').join('\n');message('Tools copied into the form. Press Save tools to add them to this account.');}catch{message('No readable inventory was found in this browser.');}};
$('checkout').onclick=async()=>{
 $('checkout').disabled=true;checkoutRequest=checkoutRequest||crypto.randomUUID();
 try{const data=await api('checkout','POST',{requestId:checkoutRequest});const target=new URL(data.url);if(target.protocol!=='https:'||target.hostname!=='checkout.stripe.com')throw new Error('Unexpected checkout address.');location.assign(target.href);}
 catch(error){message(error.message);showAccount();}
};
$('refresh').onclick=refresh;
function render(result){
 const run=++renderRun;
 const v=result.verdict;
 $('answer').innerHTML=`<p class="decision">${esc({TRIAL:'TEST',REJECT:"DON’T BUY"}[v.decision]||v.decision)}</p><h2>${esc(v.headline)}</h2><p><strong>Due today:</strong> ${esc(result.facts?.total_due_now?.value||'Not shown')}</p>
 <ul>${(v.check_before_buying||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><div id="ownedOptions"></div><details><summary>View evidence</summary><pre id="facts"></pre></details>`;
 $('facts').textContent=JSON.stringify({facts:result.facts,checks:result.checks,verdict_checks:result.verdict_checks},null,2);
 fetch('/api/recommend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pipeline:result,ownedTools:inventory})}).then(r=>r.json()).then(data=>{
  const box=$('ownedOptions');if(!box||run!==renderRun)return;
  box.textContent=data.ownedRecommendation?`You already have ${data.ownedRecommendation.toolName}.`:data.recommendation?`Related tool: ${data.recommendation.toolName}. See the existing tester for the full editorial comparison.`:'No tool in our editorial library matches this purchase.';
 }).catch(()=>{});
}
function renderHistory(){
 $('history').innerHTML=history.length?history.map((item,i)=>`<article class="historyItem"><strong>${esc(item.result.verdict?.decision)} · ${esc(item.question)}</strong><p class="hint">${esc(new Date(item.created_at).toLocaleString())}</p><button class="secondary" data-open="${i}">Open result</button><button class="secondary" data-delete="${i}">Delete saved check</button></article>`).join(''):'<p>No saved checks yet. A completed check appears here automatically.</p>';
 document.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>{render(history[Number(button.dataset.open)].result);$('answer').scrollIntoView({block:'start'});});
 document.querySelectorAll('[data-delete]').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this saved check? Credits are not changed.'))return;try{await api('history','DELETE',{id:history[Number(button.dataset.delete)].id});await refresh();}catch(error){message(error.message);}});
}
const upload=$('screenshot'),dropzone=$('dropzone');
function uploadChanged(){
 pendingCheck=null;$('answer').textContent='';renderRun++;
 const file=upload.files[0];
 if(!file){$('preview').hidden=true;$('preview').removeAttribute('src');return;}
 if(!['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)||file.size>3000000){
  upload.value='';$('preview').hidden=true;$('preview').removeAttribute('src');
  message('Choose a PNG, JPG, WebP or GIF screenshot under 3 MB.');return;
 }
 const reader=new FileReader();
 reader.onload=()=>{if(upload.files[0]===file){$('preview').src=reader.result;$('preview').hidden=false;}};
 reader.readAsDataURL(file);
}
upload.addEventListener('change',uploadChanged);
['dragenter','dragover'].forEach(type=>dropzone.addEventListener(type,event=>{
 event.preventDefault();if(upload.disabled)return;
 if(event.dataTransfer)event.dataTransfer.dropEffect='copy';
 dropzone.classList.add('dragover');
}));
['dragleave','drop'].forEach(type=>dropzone.addEventListener(type,event=>{
 event.preventDefault();dropzone.classList.remove('dragover');
}));
dropzone.addEventListener('drop',event=>{
 if(upload.disabled||!event.dataTransfer)return;
 const file=[...event.dataTransfer.files].find(f=>f.type.startsWith('image/'));
 if(!file){message('Drop an image screenshot, not another file type.');return;}
 if(!['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)||file.size>3000000){
  message('Choose a PNG, JPG, WebP or GIF screenshot under 3 MB.');return;
 }
 const transfer=new DataTransfer();transfer.items.add(file);upload.files=transfer.files;
 uploadChanged();
});
$('question').oninput=()=>{pendingCheck=null;};
$('checkForm').onsubmit=async event=>{
 event.preventDefault();const file=$('screenshot').files[0];if(!file||!account)return;
 if(file.size>3000000){message('Choose a screenshot under 3 MB for this pilot.');return;}
 pendingCheck=pendingCheck||crypto.randomUUID();const requestId=pendingCheck,sessionAtStart=sessionRun;
 $('analyze').disabled=true;$('screenshot').disabled=true;$('question').disabled=true;$('working').hidden=false;
 try{
  const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
  const result=await api('analyze','POST',{requestId,image,question:$('question').value});if(sessionAtStart!==sessionRun)return;pendingCheck=null;render(result);await refresh();
 }catch(error){message(error.message);await refresh();}
 finally{$('working').hidden=true;$('screenshot').disabled=false;$('question').disabled=false;$('analyze').disabled=!account||account.credits<1;}
};
(async()=>{
 try{setup=await api('status');offer();$('email').disabled=$('password').disabled=$('login').disabled=$('signup').disabled=!setup.accountsConfigured;
  $('notice').textContent=setup.accountsConfigured?'Private pilot: sandbox payments only. Credits and saved checks are tied to your account.':'The first-user pilot is built for review. Account and payment services have not been connected, so sign-up, sign-in and checkout are unavailable here.';
  if(setup.accountsConfigured)await refresh();else showAccount();
  if(new URLSearchParams(location.search).get('checkout'))message('Returned from checkout. Refresh your account to see credits confirmed by the payment service; this return URL does not prove payment.');
 }catch(error){$('notice').textContent='Pilot setup could not be checked. '+error.message;}
})();
