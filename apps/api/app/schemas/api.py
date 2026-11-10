from typing import Literal
from pydantic import BaseModel,Field
class LoginRequest(BaseModel):
 username: str=Field(min_length=1,max_length=100)
 password: str=Field(min_length=1,max_length=300)
class CredentialUpdate(BaseModel):
 client_id: str=Field(min_length=1,max_length=100)
 client_secret: str=Field(default="",max_length=500)
 redirect_uri: str=Field(min_length=8,max_length=500)
 environment: Literal['demo','live']='demo'
class ConfigStatus(BaseModel):
 configured: bool
 client_id: str|None=None
 secret_saved: bool
 redirect_uri: str|None=None
 environment: str|None=None
 oauth_status: str='not_configured'
 token_expiry: str|None=None
class ModuleInfo(BaseModel):
 id: str; name: str; group: str; phase: str
 status: Literal['spec_ready','in_development','ready','blocked']
 purpose: str
