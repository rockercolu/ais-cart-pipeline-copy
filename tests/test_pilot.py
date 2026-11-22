"""Pilot contract/security tests with isolated provider doubles; no remote accounts or charges.
SQL functions/RLS are independently exercised in test_pilot_sql.js against PGlite Postgres.
"""
import hashlib,hmac,json,os,sys,time,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from aiscart import pilot
from urllib.parse import urlparse,parse_qs

OWNER='11111111-1111-4111-8111-111111111111';OTHER='22222222-2222-4222-8222-222222222222'
ENV={'SUPABASE_URL':'https://supabase.example.test','SUPABASE_ANON_KEY':'anon-test','SUPABASE_SERVICE_ROLE_KEY':'service-test',
     'PILOT_ORIGIN':'https://pilot.example.test','PILOT_ALLOWED_EMAILS':'owner@example.test,other@example.test',
     'STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture','MOCK':'1'}
class Providers:
 def __init__(self):
  self.calls=[];self.users={OWNER:'owner@example.test',OTHER:'other@example.test'};self.balances={};self.inventory={};self.history={};self.orders={};self.usage={};self.sessions={};self.keys={};self.accounts=set()
 def __call__(self,method,url,headers,body=None,form=False):
  self.calls.append((method,url,body));path=urlparse(url).path;q=parse_qs(urlparse(url).query)
  if url.startswith(ENV['SUPABASE_URL']):
   auth=headers['Authorization'].removeprefix('Bearer ');uid={'token-owner':OWNER,'token-other':OTHER}.get(auth)
   if path in ('/auth/v1/signup','/auth/v1/token'):
    if body.get('refresh_token'):return {'access_token':'token-owner','refresh_token':'refresh-owner'}
    key='owner' if body.get('email')=='owner@example.test' else 'other';return {'access_token':'token-'+key,'refresh_token':'refresh-'+key}
   if path=='/auth/v1/user':
    if not uid:raise pilot.PilotError(401,'expired','Expired')
    return {'id':uid,'email':self.users[uid]}
   if path=='/auth/v1/logout':return {}
   if path.startswith('/rest/v1/rpc/'):
    assert auth=='service-test','Privileged functions require service credential'
    name=path.rsplit('/',1)[-1];u=body.get('p_user');rid=body.get('p_request')
    if name=='pilot_reclaim_stale':return 0
    if name=='pilot_set_inventory':
     current=self.inventory.get(u,{'tools':[],'revision':0})
     if current['revision']!=body['p_revision']:raise pilot.PilotError(409,'conflict','Inventory changed')
     self.inventory[u]={'tools':body['p_tools'],'revision':current['revision']+1};return self.inventory[u]
    if name=='pilot_fulfill_order':
     order=self.orders[body['p_session']]
     if order['user_id']!=u or order['amount']!=body['p_amount'] or order['currency']!=body['p_currency']:raise pilot.PilotError(409,'conflict','Payment mismatch')
     if order.get('fulfilled'):return {'already_fulfilled':True}
     order['fulfilled']=True;self.balances[u]=self.balances.get(u,0)+order['credits'];return {'credits_added':order['credits']}
    if name=='pilot_reserve_check':
     old=self.usage.get(rid)
     if old:
      if old['user']!=u or old['fingerprint']!=body['p_fingerprint']:raise pilot.PilotError(409,'conflict','Payload changed')
      return {'status':old['status'],'result':self.history.get(rid,{}).get('result')}
     if self.balances.get(u,0)<1:return {'status':'no_credits'}
     self.balances[u]-=1;self.usage[rid]={'user':u,'status':'reserved','fingerprint':body['p_fingerprint'],'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())};return {'status':'reserved_new'}
    if name=='pilot_release_check':
     row=self.usage[rid]
     if row['status']=='reserved':row['status']='released';self.balances[u]+=1
     return None
    if name=='pilot_complete_check':
     row=self.usage[rid];assert row['user']==u and row['status']=='reserved';row['status']='completed'
     self.history[rid]={'id':rid,'user_id':u,'question':body['p_question'],'result':body['p_result'],'created_at':'2026-11-19T00:00:00Z'};return None
   if path=='/rest/v1/pilot_orders':
    assert auth=='service-test';self.orders.setdefault(body['session_id'],dict(body));return [self.orders[body['session_id']]]
   if path=='/rest/v1/pilot_accounts':
    if method=='POST':
     assert auth=='service-test' and q.get('on_conflict')==['user_id'] and 'resolution=ignore-duplicates' in headers.get('Prefer','')
     self.accounts.add(body['user_id']);return None
    return [{'credits':self.balances.get(uid,0)}] if uid in self.accounts or uid in self.balances else []
   if path=='/rest/v1/pilot_usage':
    assert auth=='service-test','Usage is only readable with the service credential'
    one=lambda k:q[k][0].split('.',1)[1]
    rows=[{'id':k,'created_at':v['created_at']} for k,v in self.usage.items() if v['user']==one('user_id') and v['fingerprint']==one('fingerprint')
          and v['status']==one('status') and k!=one('id') and v['created_at']>=one('created_at')]
    return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:1]
   if path=='/rest/v1/pilot_inventory':return [self.inventory[uid]] if uid in self.inventory else []
   if path=='/rest/v1/pilot_checks':
    rows=[v for v in self.history.values() if v['user_id']==uid and (not q.get('id') or 'eq.'+v['id'] in q['id'])]
    if method=='DELETE':
     for row in rows:self.history.pop(row['id'])
    return rows
  if url.startswith('https://api.stripe.com/v1/checkout/sessions'):
   assert headers['Authorization']=='Bearer sk_test_fixture'
   if method=='POST':
    idem=headers['Idempotency-Key']
    if idem in self.keys:return self.sessions[self.keys[idem]]
    assert body['line_items[0][price_data][unit_amount]']==500
    assert body['mode']=='payment';sid='cs_test_'+str(len(self.sessions)+1);self.keys[idem]=sid
    self.sessions[sid]={'id':sid,'url':'https://checkout.stripe.com/c/pay/'+sid,'livemode':False,'mode':'payment','payment_status':'unpaid',
      'amount_total':500,'currency':'usd','client_reference_id':body['client_reference_id']};return self.sessions[sid]
   return self.sessions[path.rsplit('/',1)[-1]]
  raise AssertionError('Unexpected provider route: '+url)

def cookie(token='token-owner'):return pilot.session_cookie({'access_token':token,'refresh_token':'refresh-owner'}).split(';')[0]

def call(action,method='GET',body=None,who=True,origin=True,extra=None):
 headers={'Origin':ENV['PILOT_ORIGIN']} if origin else {}
 if who:headers['Cookie']=cookie('token-other' if who=='other' else 'token-owner')
 if extra:headers.update(extra)
 status,h,raw=pilot.handle(method,action,headers,json.dumps(body).encode() if body is not None else b'')
 return status,h,json.loads(raw)

passed=0
def check(name,condition):
 global passed
 assert condition,name;passed+=1;print('PASS',name)

def event(provider,sid,valid=True,age=0,live=False):
 raw=json.dumps({'type':'checkout.session.completed','livemode':live,'data':{'object':{'id':sid}}}).encode();stamp=int(time.time())-age
 signature=hmac.new(ENV['STRIPE_WEBHOOK_SECRET'].encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
 code,_,body=pilot.handle('POST','webhook',{'Stripe-Signature':f't={stamp},v1={signature if valid else "bad"}'},raw)
 return code,json.loads(body)

with patch.dict(os.environ,ENV,clear=True):
 provider=Providers()
 with patch.object(pilot,'request',provider):
  status,_,data=call('status',who=False);check('Status exposes no keys and labels test-only',status==200 and data['testOnly'] and 'service-test' not in json.dumps(data))
  check('Unauthenticated account is rejected',call('history',who=False)[0]==401)
  before=len(provider.calls);check('Cross-origin sign-in rejected before provider call',call('login','POST',{'email':'owner@example.test','password':'long-test-password'},who=False,extra={'Origin':'https://attacker.example'})[0]==403 and len(provider.calls)==before)
  check('Uninvited signup rejected',call('signup','POST',{'email':'uninvited@example.test','password':'long-test-password'},who=False)[0]==403)
  status,headers,data=call('signup','POST',{'email':'owner@example.test','password':'long-test-password'},who=False)
  check('Signup returns HttpOnly Secure cookie and no token JSON',status==200 and 'HttpOnly' in headers['Set-Cookie'] and 'Secure' in headers['Set-Cookie'] and 'token-owner' not in json.dumps(data))
  check('Account row does not exist before the first session',OWNER not in provider.accounts)
  check('Starting balance is zero',call('session')[2]['credits']==0)
  check('First session creates the account row automatically, with the service credential',OWNER in provider.accounts)
  call('session');check('Later sessions leave the existing account row alone',provider.accounts=={OWNER} and call('session')[2]['credits']==0)
  check('No credits blocks model request',call('analyze','POST',{'requestId':str(uuid.uuid4()),'image':'iVBORw==','question':'Should I buy?'})[0]==402)
  check('Save inventory uses authenticated identity',call('inventory','PUT',{'tools':['Canva','ElevenLabs'],'revision':0,'userId':OTHER})[2]['tools']==['Canva','ElevenLabs'] and OWNER in provider.inventory and OTHER not in provider.inventory)
  check('Stale inventory update conflicts',call('inventory','PUT',{'tools':['Wrong'],'revision':0})[0]==409)
  check('Another session retrieves persisted inventory',call('inventory')[2]['revision']==1)
  checkout_id=str(uuid.uuid4());status,_,data=call('checkout','POST',{'requestId':checkout_id,'amount':1,'credits':999})
  sid=next(iter(provider.sessions));check('Checkout uses server offer and grants no credits',status==200 and provider.balances.get(OWNER,0)==0)
  call('checkout','POST',{'requestId':checkout_id});check('Checkout request id is idempotent',len(provider.sessions)==1)
  check('Unpaid event grants no credits',event(provider,sid)[1].get('fulfilled') is False and provider.balances.get(OWNER,0)==0)
  provider.sessions[sid]['payment_status']='paid'
  check('Forged webhook rejected',event(provider,sid,valid=False)[0]==400 and provider.balances.get(OWNER,0)==0)
  check('Expired webhook rejected',event(provider,sid,age=301)[0]==400)
  check('Live webhook rejected',event(provider,sid,live=True)[0]==400)
  provider.sessions[sid]['amount_total']=501
  check('Wrong amount cannot grant credits',event(provider,sid)[0]==409 and provider.balances.get(OWNER,0)==0)
  provider.sessions[sid]['amount_total']=500
  check('Verified paid sandbox event grants pack',event(provider,sid)[0]==200 and provider.balances[OWNER]==10)
  event(provider,sid);check('Duplicate event cannot grant twice',provider.balances[OWNER]==10)
  with patch.dict(os.environ,{'STRIPE_SECRET_KEY':'sk_live_forbidden'}):check('Live Stripe key refused',call('checkout','POST',{'requestId':str(uuid.uuid4())})[0]==503)
  import base64
  image=base64.b64encode((Path(__file__).resolve().parent.parent/'eval/samples/checkout_03_cart.png').read_bytes()).decode()
  rid=str(uuid.uuid4());body={'requestId':rid,'image':image,'question':'Should I complete this purchase?'}
  status,_,data=call('analyze','POST',body)
  check('Full check saves result and spends one credit',status==200 and data['verdict']['decision']=='BUY' and provider.balances[OWNER]==9 and rid in provider.history)
  call('analyze','POST',body);check('Retry returns same result without spending twice',provider.balances[OWNER]==9)
  check('Same request id cannot refer to a different question',call('analyze','POST',{**body,'question':'Different question'})[0]==409 and provider.balances[OWNER]==9)
  check('Other account cannot read saved history',call('history',who='other')[2]['checks']==[])
  call('history','DELETE',{'id':rid},who='other');check('Other account cannot delete saved check',rid in provider.history)
  again=str(uuid.uuid4());status,_,data=call('analyze','POST',{**body,'requestId':again})
  check('Same screenshot and question again asks first, spends nothing and points to the saved check',
        status==409 and data['error']['code']=='duplicate_check' and data['error']['previousId']==rid and data['error']['checkedAt'] and provider.balances[OWNER]==9 and again not in provider.usage)
  status,_,data=call('analyze','POST',{**body,'requestId':again,'confirmDuplicate':True})
  check('Confirming the duplicate runs it and spends one credit',status==200 and provider.balances[OWNER]==8 and again in provider.history)
  status,_,data=call('analyze','POST',{**body,'requestId':str(uuid.uuid4()),'question':'Is the renewal price shown?'})
  check('The same screenshot with a different question is not a duplicate',status==200 and provider.balances[OWNER]==7)
  call('analyze','POST',body);check('Retrying the original request still returns its saved result for free',provider.balances[OWNER]==7)
  check('Duplicate errors still hide provider details',data and 'service-test' not in json.dumps(call('analyze','POST',{**body,'requestId':str(uuid.uuid4())})[2]))
  with patch('aiscart.analyze.analyze',side_effect=RuntimeError('fake provider failure')):
   check('Failed analysis releases credit',call('analyze','POST',{**body,'requestId':str(uuid.uuid4()),'confirmDuplicate':True})[0]==503 and provider.balances[OWNER]==7)
  call('history','DELETE',{'id':rid});check('Owner can delete own saved check',rid not in provider.history and provider.balances[OWNER]==7)
  status,headers,_=call('logout','POST',{});check('Logout clears session cookie',status==200 and 'Max-Age=0' in headers['Set-Cookie'])
  status,headers,_=call('session',extra={'Cookie':cookie('expired-token')});check('Expired session refreshes server-side',status==200 and 'Set-Cookie' in headers)
with patch.dict(os.environ,{},clear=True):
 status,_,data=call('status',who=False);check('Unconfigured deployment fails closed',status==200 and not data['accountsConfigured'] and not data['checkoutConfigured'])
print(f'{passed} pilot contract checks passed; provider doubles only, no real payments.')
