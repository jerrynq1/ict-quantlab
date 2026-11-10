from datetime import datetime,timezone,timedelta
import httpx
from fastapi import HTTPException
from app.settings import settings
from app.security import decrypt_secret,encrypt_secret
from app.storage.database import get_credentials,save_credentials,save_tokens

def public_config():
 row=get_credentials()
 if not row: return dict(configured=False,client_id=None,secret_saved=False,redirect_uri=None,environment=None,oauth_status='not_configured',token_expiry=None)
 return dict(configured=True,client_id=row['client_id'],secret_saved=bool(row['encrypted_client_secret']),redirect_uri=row['redirect_uri'],environment=row['environment'],oauth_status=row['oauth_status'],token_expiry=row['token_expires_at'])

def save_config(client_id,client_secret,redirect_uri,environment):
 old=get_credentials()
 if client_secret.strip(): encrypted=encrypt_secret(client_secret.strip())
 elif old and old['encrypted_client_secret'] and old['client_id']==client_id.strip(): encrypted=old['encrypted_client_secret']
 elif old and old['client_id']!=client_id.strip(): raise HTTPException(422,'Client ID changed; enter the matching new Client Secret.')
 else: raise HTTPException(422,'Client Secret is required for the first save.')
 save_credentials(client_id.strip(),encrypted,redirect_uri.strip(),environment)

def private_credentials():
 row=get_credentials()
 if not row: raise HTTPException(409,'Save cTrader credentials first.')
 return row['client_id'],decrypt_secret(row['encrypted_client_secret']),row['redirect_uri'],row['environment']

async def exchange_code(code):
 client_id,client_secret,redirect_uri,_=private_credentials()
 params=dict(grant_type='authorization_code',code=code,redirect_uri=redirect_uri,client_id=client_id,client_secret=client_secret)
 async with httpx.AsyncClient(timeout=20) as client: response=await client.get(settings.ctrader_token_url,params=params)
 if response.is_error: raise HTTPException(502,'cTrader token exchange failed; check app credentials and redirect URI.')
 body=response.json()
 if body.get('errorCode') or not body.get('accessToken') or not body.get('refreshToken'): raise HTTPException(502,'cTrader did not return valid access/refresh tokens.')
 expires=int(body.get('expiresIn',0))
 if expires<=0: raise HTTPException(502,'Invalid token expiry returned by cTrader.')
 expiry=(datetime.now(timezone.utc)+timedelta(seconds=expires)).isoformat()
 save_tokens(encrypt_secret(body['accessToken']),encrypt_secret(body['refreshToken']),expiry,'oauth_tokens_saved_account_pending')

async def refresh_token():
 row=get_credentials()
 if not row or not row['encrypted_refresh_token']: raise HTTPException(409,'Authorize cTrader first.')
 client_id,client_secret,_,_=private_credentials()
 refresh=decrypt_secret(row['encrypted_refresh_token'])
 params=dict(grant_type='refresh_token',refresh_token=refresh,client_id=client_id,client_secret=client_secret)
 async with httpx.AsyncClient(timeout=20) as client: response=await client.post(settings.ctrader_token_url,params=params)
 if response.is_error: raise HTTPException(502,'cTrader token refresh failed.')
 body=response.json()
 if body.get('errorCode') or not body.get('accessToken') or not body.get('refreshToken'): raise HTTPException(502,'Invalid token refresh response.')
 expires=int(body.get('expiresIn',0))
 if expires<=0: raise HTTPException(502,'Invalid token expiry returned by cTrader.')
 expiry=(datetime.now(timezone.utc)+timedelta(seconds=expires)).isoformat()
 save_tokens(encrypt_secret(body['accessToken']),encrypt_secret(body['refreshToken']),expiry,'oauth_tokens_saved_account_pending')
