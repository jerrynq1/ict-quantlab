from datetime import datetime
from typing import Protocol
from app.domain.market_data import CandleM1
class CTraderTransport(Protocol):
 async def list_accounts(self,access_token: str)->list[dict]: ...
 async def authorize_account(self,account_id: int,access_token: str)->None: ...
 async def list_symbols(self,account_id: int)->list[dict]: ...
 async def fetch_m1(self,account_id: int,symbol_id: int,start_utc: datetime,end_utc: datetime)->list[CandleM1]: ...
class CTraderTransportNotImplemented(RuntimeError): pass
class CTraderOpenApiTransport:
 """Protobuf transport boundary; don't report Connected before account auth and symbol discovery."""
 async def list_accounts(self,access_token): raise CTraderTransportNotImplemented('Protobuf account discovery is not wired yet.')
 async def authorize_account(self,account_id,access_token): raise CTraderTransportNotImplemented('Account authorization is not wired yet.')
 async def list_symbols(self,account_id): raise CTraderTransportNotImplemented('Dynamic symbol discovery is not wired yet.')
 async def fetch_m1(self,account_id,symbol_id,start_utc,end_utc): raise CTraderTransportNotImplemented('M1 trendbar retrieval is not wired yet.')
