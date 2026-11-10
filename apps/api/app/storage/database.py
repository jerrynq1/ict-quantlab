import sqlite3
from pathlib import Path
from contextlib import contextmanager
from app.settings import settings

SCHEMA="""
CREATE TABLE IF NOT EXISTS ctrader_credentials (
 id INTEGER PRIMARY KEY CHECK(id=1), client_id TEXT NOT NULL,
 encrypted_client_secret TEXT NOT NULL, redirect_uri TEXT NOT NULL,
 environment TEXT NOT NULL CHECK(environment IN ('demo','live')),
 encrypted_access_token TEXT, encrypted_refresh_token TEXT, token_expires_at TEXT,
 oauth_status TEXT NOT NULL DEFAULT 'not_authorized', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states (state TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);
"""
@contextmanager
def connect():
 path=Path(settings.database_path); path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(path,timeout=15); db.row_factory=sqlite3.Row
 try:
  db.execute("PRAGMA journal_mode=WAL"); yield db; db.commit()
 finally: db.close()
def initialize_database():
 with connect() as db: db.executescript(SCHEMA)
def get_credentials():
 with connect() as db: return db.execute("SELECT * FROM ctrader_credentials WHERE id=1").fetchone()
def save_credentials(client_id,encrypted_secret,redirect_uri,environment):
 from datetime import datetime,timezone
 now=datetime.now(timezone.utc).isoformat()
 with connect() as db:
  db.execute("""INSERT INTO ctrader_credentials(id,client_id,encrypted_client_secret,redirect_uri,environment,oauth_status,updated_at)
  VALUES(1,?,?,?,?, 'not_authorized',?) ON CONFLICT(id) DO UPDATE SET
  client_id=excluded.client_id, encrypted_client_secret=excluded.encrypted_client_secret,
  redirect_uri=excluded.redirect_uri, environment=excluded.environment,
  oauth_status=CASE WHEN ctrader_credentials.client_id!=excluded.client_id OR ctrader_credentials.environment!=excluded.environment OR ctrader_credentials.encrypted_client_secret!=excluded.encrypted_client_secret THEN 'not_authorized' ELSE ctrader_credentials.oauth_status END,
  encrypted_access_token=CASE WHEN ctrader_credentials.client_id!=excluded.client_id OR ctrader_credentials.environment!=excluded.environment OR ctrader_credentials.encrypted_client_secret!=excluded.encrypted_client_secret THEN NULL ELSE ctrader_credentials.encrypted_access_token END,
  encrypted_refresh_token=CASE WHEN ctrader_credentials.client_id!=excluded.client_id OR ctrader_credentials.environment!=excluded.environment OR ctrader_credentials.encrypted_client_secret!=excluded.encrypted_client_secret THEN NULL ELSE ctrader_credentials.encrypted_refresh_token END,
  token_expires_at=CASE WHEN ctrader_credentials.client_id!=excluded.client_id OR ctrader_credentials.environment!=excluded.environment OR ctrader_credentials.encrypted_client_secret!=excluded.encrypted_client_secret THEN NULL ELSE ctrader_credentials.token_expires_at END,
  updated_at=excluded.updated_at""",(client_id,encrypted_secret,redirect_uri,environment,now))
def save_tokens(access,refresh,expires_at,status):
 from datetime import datetime,timezone
 with connect() as db: db.execute("UPDATE ctrader_credentials SET encrypted_access_token=?,encrypted_refresh_token=?,token_expires_at=?,oauth_status=?,updated_at=? WHERE id=1",(access,refresh,expires_at,status,datetime.now(timezone.utc).isoformat()))
def delete_credentials():
 with connect() as db: db.execute("DELETE FROM ctrader_credentials WHERE id=1"); db.execute("DELETE FROM oauth_states")
def save_oauth_state(state,expires):
 with connect() as db:
  db.execute("DELETE FROM oauth_states WHERE expires_at < strftime('%s','now')")
  db.execute("INSERT INTO oauth_states(state,expires_at) VALUES(?,?)",(state,expires))
def consume_oauth_state(state,now):
 with connect() as db:
  row=db.execute("SELECT expires_at FROM oauth_states WHERE state=?",(state,)).fetchone()
  db.execute("DELETE FROM oauth_states WHERE state=?",(state,))
  return bool(row and int(row['expires_at'])>=now)
