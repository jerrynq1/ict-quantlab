from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.security import require_auth
from app.db import db
import json

router=APIRouter(prefix="/research",tags=["research notes"])
class NoteBody(BaseModel):
    title:str=Field(min_length=1,max_length=160)
    body:str=Field(min_length=1,max_length=20000)
    tags:list[str]=Field(default_factory=list,max_length=20)

@router.get("/notes")
async def list_notes(_:str=Depends(require_auth)):
    with db() as conn: rows=conn.execute("SELECT * FROM research_notes ORDER BY id DESC LIMIT 200").fetchall()
    return {"notes":[{"id":r["id"],"created_at":r["created_at"],"title":r["title"],"body":r["body"],"tags":json.loads(r["tags"])} for r in rows]}

@router.post("/notes")
async def create_note(body:NoteBody,_:str=Depends(require_auth)):
    with db() as conn:
        cur=conn.execute("INSERT INTO research_notes(title,body,tags) VALUES(?,?,?)",(body.title,body.body,json.dumps(body.tags)))
        return {"id":cur.lastrowid,"created":True}

@router.delete("/notes/{note_id}")
async def delete_note(note_id:int,_:str=Depends(require_auth)):
    with db() as conn: cur=conn.execute("DELETE FROM research_notes WHERE id=?",(note_id,))
    if not cur.rowcount: raise HTTPException(status_code=404,detail="Note not found")
    return {"deleted":True}
