"""Private first-user pilot: managed Supabase auth/data and Stripe TEST checkout.
No local password database, card handling, or in-memory billing/credit counters.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookies import SimpleCookie

COOKIE = 'aiscart_pilot'
OFFER = {'id':'pilot_checks','name':"AI’sCart pilot — 10 screenshot checks",'amount':500,'currency':'usd','credits':10,
         'billing':'one_time','renewal':'None','expiry':'No expiry in this pilot','testOnly':True,
         'pricingNote':'Sample sandbox price, not an approved public offer.'}

class PilotError(Exception):
    def __init__(self,status,code,message): self.status,self.code,self.message=status,code,message


def config():
    return {k:os.environ.get(k,'').strip() for k in ('SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','PILOT_ORIGIN','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','PILOT_ALLOWED_EMAILS')}


def request(method,url,headers,body=None,form=False):
    raw=urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(url,method=method,data=raw,headers={**headers,'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            raw=r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        # Provider bodies may contain secrets or personal details; never pass them through.
        if e.code==409:raise PilotError(409,'conflict','This record changed or is already being processed. Refresh before retrying.')
        if e.code in (400,401,403): raise PilotError(401,'provider_rejected','The request could not be verified. Check your sign-in or account confirmation.')
        raise PilotError(503,'provider_unavailable','The account or payment service is temporarily unavailable.')
    except (OSError,ValueError): raise PilotError(503,'provider_unavailable','The account or payment service could not be reached.')


def required(*keys):
    c=config()
    if not all(c[k] for k in keys): raise PilotError(503,'setup_required','The pilot services are not connected yet. See pilot setup status.')
    return c


def sb(path,method='GET',body=None,token=None,privileged=False,prefer=None):
    c=required('SUPABASE_URL','SUPABASE_ANON_KEY')
    key=required('SUPABASE_SERVICE_ROLE_KEY')['SUPABASE_SERVICE_ROLE_KEY'] if privileged else c['SUPABASE_ANON_KEY']
    headers={'apikey':key,'Authorization':'Bearer '+(key if privileged else token or key)}
    if prefer:headers['Prefer']=prefer
    # REST responses may intentionally be empty (DELETE/upsert).
    return request(method,c['SUPABASE_URL'].rstrip('/')+path,headers,body)


def rpc(name,body): return sb('/rest/v1/rpc/'+name,'POST',body,privileged=True)

def stripe(path,body=None,idempotency=None):
    key=required('STRIPE_SECRET_KEY')['STRIPE_SECRET_KEY']
    if not key.startswith('sk_test_'):raise PilotError(503,'sandbox_only','This pilot only accepts a Stripe test secret key. Live payments are disabled.')
    headers={'Authorization':'Bearer '+key,'Stripe-Version':'2025-02-24.acacia'}
    if idempotency:headers['Idempotency-Key']=idempotency
    return request('POST' if body is not None else 'GET','https://api.stripe.com/v1'+path,headers,body,form=body is not None)


def allowed_email(email):
    allowed={e.strip().lower() for e in required('PILOT_ALLOWED_EMAILS')['PILOT_ALLOWED_EMAILS'].split(',') if e.strip()}
    if str(email).strip().lower() not in allowed:raise PilotError(403,'invite_required','This private pilot is limited to invited accounts.')


def session_cookie(session,clear=False):
    value='' if clear else base64.urlsafe_b64encode(json.dumps({'access_token':session['access_token'],'refresh_token':session.get('refresh_token','')},separators=(',',':')).encode()).decode()
    # Secure is mandatory on the deployed app; local loopback tests can use HTTP.
    secure='' if config()['PILOT_ORIGIN'].startswith('http://127.0.0.1:') else '; Secure'
    return f'{COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={0 if clear else 604800}'+secure


def identity(headers):
    try:
        cookie=SimpleCookie();cookie.load(headers.get('cookie',''))
        session=json.loads(base64.urlsafe_b64decode(cookie[COOKIE].value))
        token=session['access_token']
    except (ValueError,KeyError,TypeError):raise PilotError(401,'sign_in_required','Sign in to use your account.')
    updated=None
    try:user=sb('/auth/v1/user',token=token)
    except PilotError as e:
        if e.status!=401 or not session.get('refresh_token'):raise
        session=sb('/auth/v1/token?grant_type=refresh_token','POST',{'refresh_token':session['refresh_token']})
        token=session['access_token'];user=sb('/auth/v1/user',token=token);updated=session_cookie(session)
    try:uuid.UUID(user['id'])
    except (KeyError,ValueError):raise PilotError(401,'invalid_identity','The account identity could not be verified.')
    allowed_email(user.get('email'))
    return user,token,updated


def verify_origin(headers):
    origin=required('PILOT_ORIGIN')['PILOT_ORIGIN'].rstrip('/')
    if headers.get('origin','').rstrip('/')!=origin:raise PilotError(403,'origin_mismatch','Open the pilot from its configured address and try again.')


def valid_id(value):
    try:return str(uuid.UUID(str(value)))
    except (TypeError,ValueError):raise PilotError(400,'invalid_request','A valid request identifier is required.')


def handle(method,action,headers,raw):
    headers={k.lower():v for k,v in headers.items()}
    response_headers={'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
    def response(code,obj):return code,response_headers,json.dumps(obj).encode()
    try:
        if len(raw)>4400000:raise PilotError(413,'too_large','The request is too large.')
        if action=='status' and method=='GET':
            c=config();account_keys=('SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','PILOT_ORIGIN','PILOT_ALLOWED_EMAILS')
            return response(200,{'testOnly':True,'offer':OFFER,'accountsConfigured':all(c[k] for k in account_keys),
                'checkoutConfigured':all(c[k] for k in account_keys) and c['STRIPE_SECRET_KEY'].startswith('sk_test_') and bool(c['STRIPE_WEBHOOK_SECRET']),
                'checkoutSetupChecks':{'accountSettingsPresent':all(c[k] for k in account_keys),'stripeTestKeyFormat':c['STRIPE_SECRET_KEY'].startswith('sk_test_') and len(c['STRIPE_SECRET_KEY'])>12,'webhookSecretFormat':c['STRIPE_WEBHOOK_SECRET'].startswith('whsec_') and len(c['STRIPE_WEBHOOK_SECRET'])>12},
                'missing':[k for k,v in c.items() if not v]})
        if action=='webhook' and method=='POST':return response(200,webhook(headers,raw))
        allowed={'signup':{'POST'},'login':{'POST'},'logout':{'POST'},'session':{'GET'},'inventory':{'GET','PUT'},'history':{'GET','DELETE'},'checkout':{'POST'},'analyze':{'POST'},'ad':{'POST'}}
        if action not in allowed or method not in allowed[action]:raise PilotError(405,'method_not_allowed','That action or method is not supported.')
        if method!='GET':verify_origin(headers)
        try:body=json.loads(raw or b'{}')
        except ValueError:raise PilotError(400,'bad_request','Send a JSON object.')
        if not isinstance(body,dict):raise PilotError(400,'bad_request','Send a JSON object.')
        if action in ('signup','login'):
            required('SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','PILOT_ORIGIN','PILOT_ALLOWED_EMAILS')
            email=body.get('email','');password=body.get('password','')
            if not isinstance(email,str) or not isinstance(password,str) or '@' not in email or len(email)>254 or not 12<=len(password)<=128:
                raise PilotError(400,'invalid_credentials','Use a valid email and a password of 12–128 characters.')
            allowed_email(email)
            path='/auth/v1/signup' if action=='signup' else '/auth/v1/token?grant_type=password'
            data=sb(path,'POST',{'email':email.strip(),'password':password})
            if not data.get('access_token'):return response(200,{'confirmationRequired':True,'message':'Check your email to confirm the account, then sign in.'})
            # GoTrue is authoritative for identity; never accept a caller-supplied user id.
            response_headers['Set-Cookie']=session_cookie(data)
            return response(200,{'signedIn':True})
        if action=='logout':
            try:
                user,token,_=identity(headers);sb('/auth/v1/logout','POST',{},token=token)
            except PilotError:pass
            response_headers['Set-Cookie']=session_cookie({},clear=True)
            return response(200,{'signedOut':True})
        user,token,new_cookie=identity(headers);uid=user['id']
        if new_cookie:response_headers['Set-Cookie']=new_cookie
        if action=='session':
            # First authenticated session provisions a zero-credit account without manual SQL.
            sb('/rest/v1/pilot_accounts?on_conflict=user_id','POST',{'user_id':uid},privileged=True,prefer='resolution=ignore-duplicates,return=minimal')
            rpc('pilot_reclaim_stale',{'p_user':uid})
            rows=sb('/rest/v1/pilot_accounts?user_id=eq.'+uid+'&select=credits',token=token)
            return response(200,{'user':{'id':uid,'email':user.get('email')},'credits':rows[0]['credits'] if rows else 0,'testOnly':True})
        if action=='inventory':
            if method=='GET':
                rows=sb('/rest/v1/pilot_inventory?user_id=eq.'+uid+'&select=tools,revision',token=token)
                return response(200,rows[0] if rows else {'tools':[],'revision':0})
            tools=body.get('tools');revision=body.get('revision')
            if not isinstance(tools,list) or len(tools)>30 or any(not isinstance(t,str) or not t.strip() or len(t)>60 for t in tools) or type(revision)!=int or revision<0:
                raise PilotError(400,'invalid_inventory','Use up to 30 tool names and the current inventory revision.')
            return response(200,rpc('pilot_set_inventory',{'p_user':uid,'p_tools':list(dict.fromkeys(t.strip() for t in tools)),'p_revision':revision}))
        if action=='history':
            if method=='DELETE':
                record=valid_id(body.get('id'))
                sb('/rest/v1/pilot_checks?id=eq.'+record+'&user_id=eq.'+uid,'DELETE',token=token,prefer='return=representation')
                return response(200,{'deleted':True})
            return response(200,{'checks':sb('/rest/v1/pilot_checks?user_id=eq.'+uid+'&select=id,question,result,created_at&order=created_at.desc&limit=30',token=token)})
        if action=='checkout':return response(200,checkout(uid,valid_id(body.get('requestId'))))
        if action=='ad':
            from .web import _decode_image, _rate_limited
            from .ad import extract_ad
            from .meta import client_from_env
            if _rate_limited(headers):raise PilotError(429,'rate_limited','Too many requests; try again later.')
            try:image,mime=_decode_image(body.get('image'))
            except ValueError as e:raise PilotError(400,'invalid_image',str(e))
            client=client_from_env()
            if client is None:raise PilotError(503,'model_not_configured','Advertisement extraction is not configured.')
            return response(200,extract_ad(image,mime,client))
        if action=='analyze':return response(200,run_check(uid,body))
    except PilotError as e:return response(e.status,{'error':{'code':e.code,'message':e.message}})
    except Exception:
        # Unexpected provider failures must fail closed without leaking provider credentials.
        return response(503,{'error':{'code':'pilot_unavailable','message':'The pilot could not complete this request. No payment success is implied; check your account before retrying.'}})


def checkout(uid,request_id):
    c=required('PILOT_ORIGIN','STRIPE_WEBHOOK_SECRET','SUPABASE_SERVICE_ROLE_KEY')
    origin=c['PILOT_ORIGIN'].rstrip('/')
    data=stripe('/checkout/sessions',{'mode':'payment','payment_method_types[0]':'card','client_reference_id':uid,
        'line_items[0][price_data][currency]':OFFER['currency'],'line_items[0][price_data][unit_amount]':OFFER['amount'],
        'line_items[0][price_data][product_data][name]':OFFER['name'],'line_items[0][quantity]':1,
        'success_url':origin+'/pilot.html?checkout=success','cancel_url':origin+'/pilot.html?checkout=cancel'},
        idempotency='pilot:'+uid+':'+request_id)
    if data.get('livemode') is not False or not str(data.get('url','')).startswith('https://checkout.stripe.com/'):
        raise PilotError(503,'invalid_checkout','Stripe did not return a valid sandbox checkout.')
    order={'session_id':data['id'],'user_id':uid,'request_id':request_id,'amount':OFFER['amount'],'currency':OFFER['currency'],'credits':OFFER['credits']}
    sb('/rest/v1/pilot_orders?on_conflict=session_id','POST',order,privileged=True,prefer='resolution=ignore-duplicates,return=representation')
    return {'url':data['url'],'testOnly':True}


def webhook(headers,raw):
    c=required('STRIPE_WEBHOOK_SECRET','STRIPE_SECRET_KEY','SUPABASE_SERVICE_ROLE_KEY')
    if not c['STRIPE_SECRET_KEY'].startswith('sk_test_'):raise PilotError(503,'sandbox_only','Live payments are disabled.')
    try:
        pieces=headers.get('stripe-signature','').split(',');stamp=int(next(v[2:] for v in pieces if v.startswith('t=')))
        signatures=[v[3:] for v in pieces if v.startswith('v1=')]
        if abs(time.time()-stamp)>300:raise ValueError()
        expected=hmac.new(c['STRIPE_WEBHOOK_SECRET'].encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected,s) for s in signatures):raise ValueError()
        event=json.loads(raw)
    except (ValueError,StopIteration):raise PilotError(400,'invalid_signature','Webhook signature verification failed.')
    if event.get('livemode') is not False:raise PilotError(400,'sandbox_only','Only sandbox events are accepted.')
    if event.get('type') not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):return {'received':True,'ignored':True}
    sid=event.get('data',{}).get('object',{}).get('id','')
    if not isinstance(sid,str) or not sid.startswith('cs_test_'):raise PilotError(400,'invalid_session','Invalid sandbox session.')
    canonical=stripe('/checkout/sessions/'+urllib.parse.quote(sid,safe=''))
    if canonical.get('payment_status')!='paid':return {'received':True,'fulfilled':False}
    if canonical.get('livemode') is not False or canonical.get('mode')!='payment':raise PilotError(400,'sandbox_only','Only paid sandbox check packs are supported.')
    if type(canonical.get('amount_total')) is not int or not isinstance(canonical.get('currency'),str):raise PilotError(400,'invalid_payment','The payment total or currency is missing.')
    uid=valid_id(canonical.get('client_reference_id'))
    result=rpc('pilot_fulfill_order',{'p_session':sid,'p_user':uid,'p_amount':canonical.get('amount_total'),'p_currency':canonical.get('currency')})
    return {'received':True,**result}


def run_check(uid,body):
    from .web import _decode_image
    from .analyze import analyze,settings_from_env,StepError
    from .meta import client_from_env
    request_id=valid_id(body.get('requestId'))
    question=body.get('question','Should I complete this purchase?')
    if not isinstance(question,str) or not question.strip() or len(question)>500:raise PilotError(400,'invalid_question','Use a question of 1–500 characters.')
    try:image,mime=_decode_image(body.get('image'))
    except ValueError as e:raise PilotError(400,'invalid_image',str(e))
    client=client_from_env()
    if client is None:raise PilotError(503,'model_not_configured','Screenshot analysis is not configured yet.')
    fingerprint=hashlib.sha256(image+b'\x00'+question.encode()).hexdigest()
    # A new request for an already-completed screenshot/question needs explicit consent.
    # Replaying the SAME request ID remains idempotent and never consumes a second credit.
    if not body.get('confirmRepeat'):
        # Do not block an idempotent retry even if another matching check was completed later.
        same_request=sb('/rest/v1/pilot_usage?id=eq.'+request_id+'&user_id=eq.'+uid+'&select=id&limit=1',privileged=True)
        recent=[] if same_request else sb('/rest/v1/pilot_usage?user_id=eq.'+uid+'&fingerprint=eq.'+fingerprint+'&status=eq.completed&select=id,created_at&order=created_at.desc&limit=1',privileged=True)
        if recent and recent[0]['id']!=request_id:
            from datetime import datetime,timezone,timedelta
            try:
                checked=datetime.fromisoformat(recent[0]['created_at'].replace('Z','+00:00'))
                if datetime.now(timezone.utc)-checked<timedelta(hours=24):
                    raise PilotError(409,'repeat_confirmation_required','This screenshot and question were checked in the last 24 hours. Run again and use another credit?')
            except (ValueError,TypeError):pass
    reservation=rpc('pilot_reserve_check',{'p_user':uid,'p_request':request_id,'p_fingerprint':fingerprint})
    if reservation['status']=='completed' and reservation.get('result'):return reservation['result']
    if reservation['status']=='no_credits':raise PilotError(402,'no_credits','Add a sandbox check pack first.')
    if reservation['status']!='reserved_new':raise PilotError(409,'check_in_progress','This request is already running or was released. Check history before starting a new one.')
    try:
        result=analyze(image,mime,question,client,settings_from_env(),'auto')
        rpc('pilot_complete_check',{'p_user':uid,'p_request':request_id,'p_question':question,'p_result':result})
        return result
    except Exception:
        # Database transaction releases at most once and only if still reserved.
        try:rpc('pilot_release_check',{'p_user':uid,'p_request':request_id})
        except Exception:pass
        raise PilotError(503,'check_failed','The check did not complete. Refresh your account/history before retrying; failed reservations are released when reachable.')
