from calendar import monthrange
from datetime import date, datetime, timezone, timedelta
from uuid import uuid4
from typing import Annotated, Literal
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import text
from sqlalchemy.orm import Session

from ecommerce_service.common.auth import Principal, require_roles
from ecommerce_service.database import get_db

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]
Owner = Annotated[Principal, Depends(require_roles("user"))]
JOIN = """ FROM appliances a JOIN order_items i ON i.id=a.order_item_id
 JOIN orders o ON o.id=i.order_id JOIN appliance_models m ON m.product_id=i.product_id """
DEVICE = "a.device_id,m.model_code,m.display_name,a.serial_no,o.id AS order_id"
TICKETS = """SELECT t.ticket_id,t.description,t.created_at,t.status,jsonb_build_object(
 'device_id',a.device_id,'model_code',m.model_code,'display_name',m.display_name,'serial_no',a.serial_no) AS device""" + JOIN + " JOIN repair_tickets t ON t.device_id=a.device_id WHERE o.user_id=:uid"


def ok(data, code="OK"):
    return {"success": True, "code": code, "message": "", "data": data}


def row(db, sql, **params):
    return db.execute(text(sql), params).mappings().first()


def fail(status, code):
    raise HTTPException(status, detail=code)


def device(db, uid, did, lock=False):
    sql = "SELECT " + DEVICE + ",a.signed_on,m.warranty_months" + JOIN + " WHERE o.user_id=:uid AND a.device_id=:did"
    return row(db, sql + (" FOR UPDATE OF a" if lock else ""), uid=uid, did=did) or fail(404, "NOT_FOUND")


def warranty(signed, months, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    end = None
    if not signed or signed > today:
        status = "UNVERIFIED"
        notice = "签收日期缺失，保修资格待人工核验" if not signed else "签收日期需人工核验"
    else:
        y, m = divmod(signed.year * 12 + signed.month - 1 + months, 12)
        end = date(y, m + 1, min(signed.day, monthrange(y, m + 1)[1]))
        status = "IN_WARRANTY" if today < end else "EXPIRED"
        notice = "整机在保，具体维修资格待核验" if today < end else "已过保，维修费用待人工确认"
    return dict(status=status, signed_on=signed and signed.isoformat(), months=months,
                exclusive_end=end and end.isoformat(), notice=notice)


@router.get("/devices")
def devices(db: DB, user: Owner, model_code: str | None = None):
    sql = "SELECT " + DEVICE + JOIN + " WHERE o.user_id=:uid"
    if model_code:
        sql += " AND m.model_code=:model"
    return ok(db.execute(text(sql+" ORDER BY a.device_id"), dict(uid=user.user_id, model=model_code)).mappings().all())


@router.get("/devices/{did}/warranty")
def coverage(did: str, db: DB, user: Owner):
    d = device(db, user.user_id, did)
    return ok(dict(device_id=did, **warranty(d.signed_on, d.warranty_months)))


class Draft(BaseModel):
    device_id: str
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    replaces_preview_id: str | None = None


class Confirmation(BaseModel):
    confirmed: Literal[True]


def preview_row(db, uid, pid, lock=False):
    return row(db, "SELECT *,expires_at<=now() AS expired FROM repair_previews WHERE user_id=:uid AND preview_id=:pid" +
               (" FOR UPDATE" if lock else ""), uid=uid, pid=pid) or fail(404, "NOT_FOUND")


@router.post("/repair-previews")
def preview(body: Draft, db: DB, user: Owner):
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    uid = user.user_id
    ids = {body.device_id}
    pid = body.replaces_preview_id
    if pid:
        ids.add(preview_row(db, uid, pid).device_id)
    locked = {did: device(db, uid, did, True) for did in sorted(ids)}
    d = locked[body.device_id]
    if pid:
        old = preview_row(db, uid, pid, True)
        submitted = row(db, TICKETS+" AND t.preview_id=:pid", uid=uid, pid=pid)
        if submitted:
            fail(409, {"code":"ALREADY_SUBMITTED","ticket_id":submitted.ticket_id})
        if old.expired or old.invalidated_at:
            fail(409, "PREVIEW_STALE")
    existing = row(db, TICKETS+" AND a.device_id=:did", uid=uid, did=d.device_id)
    if existing:
        return ok(existing, "EXISTING_TICKET")
    w = warranty(d.signed_on, d.warranty_months)
    new_id = "PV_"+uuid4().hex
    expires = row(db, """INSERT INTO repair_previews(preview_id,user_id,device_id,description,warranty_snapshot,expires_at)
        VALUES(:pid,:uid,:did,:descr,CAST(:snap AS jsonb),now()+interval '15 minutes') RETURNING expires_at""",
        pid=new_id, uid=uid, did=d.device_id, descr=body.description, snap=json.dumps(w)).expires_at
    if pid:
        db.execute(text("UPDATE repair_previews SET invalidated_at=now() WHERE preview_id=:pid"), {"pid":pid})
    db.commit()
    return JSONResponse(status_code=201, content=jsonable_encoder(ok(dict(preview_id=new_id,device=dict(d),
                        description=body.description,warranty=w,notice=w["notice"],expires_at=expires))))


@router.get("/repair-previews/{pid}")
def read_preview(pid: str, db: DB, user: Owner):
    p = preview_row(db, user.user_id, pid)
    d = device(db, user.user_id, p.device_id)
    w = warranty(d.signed_on, d.warranty_months)
    if (p.expired or p.invalidated_at or w != p.warranty_snapshot
            or row(db, TICKETS+" AND a.device_id=:did", uid=user.user_id, did=d.device_id)):
        fail(409, "PREVIEW_STALE")
    return ok(dict(preview_id=pid, device=dict(d), description=p.description,
                   warranty=w, notice=w["notice"], expires_at=p.expires_at))


@router.post("/repair-previews/{pid}/confirm")
def confirm(pid: str, body: Confirmation, db: DB, user: Owner):
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    uid = user.user_id
    d = device(db, uid, preview_row(db,uid,pid).device_id, True)
    p = preview_row(db, uid, pid, True)
    existing = row(db, TICKETS+" AND t.preview_id=:pid", uid=uid, pid=pid)
    if existing:
        return ok(existing, "REPLAY")
    if p.expired or p.invalidated_at or p.warranty_snapshot != warranty(d.signed_on,d.warranty_months):
        fail(409, "PREVIEW_STALE")
    existing = row(db, TICKETS+" AND a.device_id=:did", uid=uid, did=d.device_id)
    if existing:
        return ok(existing, "EXISTING_TICKET")
    db.execute(text("""INSERT INTO repair_tickets(ticket_id,preview_id,device_id,description,status)
                       VALUES(:tid,:pid,:did,:descr,'PENDING')"""),
               dict(tid="RT_"+uuid4().hex,pid=pid,did=d.device_id,descr=p.description))
    ticket = row(db,TICKETS+" AND t.preview_id=:pid",uid=uid,pid=pid)
    db.commit()
    return JSONResponse(status_code=201,content=jsonable_encoder(ok(ticket,"CREATED")))


@router.delete("/repair-previews/{pid}",status_code=204)
def revoke(pid: str, db: DB, user: Owner):
    p = preview_row(db,user.user_id,pid,True)
    if row(db,TICKETS+" AND t.preview_id=:pid",uid=user.user_id,pid=pid):
        fail(409,"ALREADY_SUBMITTED")
    db.execute(text("UPDATE repair_previews SET invalidated_at=COALESCE(invalidated_at,now()) WHERE preview_id=:pid"),dict(pid=p.preview_id))
    db.commit()


@router.get("/repair-tickets")
def tickets(db: DB, user: Owner, device_id: str | None = None):
    sql = TICKETS
    if device_id:
        device(db,user.user_id,device_id)
        sql += " AND a.device_id=:did"
    return ok(db.execute(text(sql+" ORDER BY t.created_at DESC,t.ticket_id DESC"),dict(uid=user.user_id,did=device_id)).mappings().all())


@router.get("/repair-tickets/{tid}")
def ticket(tid: str, db: DB, user: Owner):
    return ok(row(db,TICKETS+" AND t.ticket_id=:tid",uid=user.user_id,tid=tid) or fail(404,"NOT_FOUND"))
