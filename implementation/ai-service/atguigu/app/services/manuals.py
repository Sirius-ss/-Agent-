import hashlib
import json
import re
import unicodedata
from io import BytesIO

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import text

MODELS={"W-DEMO","A-DEMO"}
def normalize(value):
    return unicodedata.normalize("NFKC",value).strip().lower()

def parse_manual(model, name, data):
    if model not in MODELS or "DEMO" not in name:
        raise ValueError("需要 DEMO 文件名与适用型号")
    chunks=[]
    for page_no,page in enumerate(PdfReader(BytesIO(data)).pages,1):
        page_text=unicodedata.normalize("NFKC",page.extract_text() or "").strip()
        if not page_text:
            continue
        if f"型号:{model}" not in page_text or "DEMO" not in page_text:
            raise ValueError(f"第 {page_no} 页型号不符")
        parts=re.split(r"(?:^|\n)章节:",page_text)
        if len(parts)<2:
            raise ValueError(f"第 {page_no} 页缺少章节")
        for ordinal,part in enumerate(parts[1:],1):
            lines=[s.strip() for s in part.splitlines() if s.strip()]
            fields=dict(line.split(":",1) for line in lines[1:] if ":" in line)
            tags=list(dict.fromkeys(normalize(t) for t in fields.get("症状","").split("|") if normalize(t)))
            if not tags or not fields.get("说明") or not re.fullmatch(r"[A-Z]+[0-9]+",fields.get("故障码","")):
                raise ValueError(f"第 {page_no} 页第 {ordinal} 条缺少故障码、标签或说明")
            steps=[s.strip() for s in fields.get("用户自查","").split("|") if s.strip()]
            digest=hashlib.sha256(f"{model}/{name}/{page_no}/{ordinal}/{part}".encode()).hexdigest()[:32]
            chunks.append(dict(id="kb_"+digest,model_code=model,file_name=name,page_no=page_no,section=lines[0],
                ordinal=ordinal,fault_code=fields["故障码"],content=fields["说明"],symptom_tags=tags,user_steps=steps))
    if not chunks:
        raise ValueError("文档没有可用条目")
    return chunks

async def ingest(session,model,name,data):
    try:
        chunks=parse_manual(model,name,data)
    except Exception as exc:
        raise HTTPException(422,detail=f"DEMO 文档解析失败：{exc}") from exc
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),{"key":model+name})
    await session.execute(text("DELETE FROM knowledge_chunks WHERE model_code=:m AND file_name=:n"),{"m":model,"n":name})
    for item in chunks:
        await session.execute(text("""INSERT INTO knowledge_chunks(id,created_at,model_code,file_name,page_no,section,ordinal,fault_code,content,symptom_tags,user_steps)
          VALUES(:id,now(),:model_code,:file_name,:page_no,:section,:ordinal,:fault_code,:content,CAST(:tags AS jsonb),CAST(:steps AS jsonb))"""),
          dict(**item,tags=json.dumps(item["symptom_tags"]),steps=json.dumps(item["user_steps"])))
    await session.commit()
    return len(chunks)

def fault_code(query):
    found=re.search(r"(?<![a-z0-9])[a-z]+\d+(?![a-z0-9])",normalize(query))
    return found[0].upper() if found else None

async def retrieve(session,model,query):
    code=fault_code(query)
    sql="SELECT id,model_code,file_name,page_no,section,ordinal,fault_code,content,symptom_tags,user_steps FROM knowledge_chunks WHERE model_code=:m"
    if code:
        sql+=" AND fault_code=:c"
    rows=(await session.execute(text(sql+" ORDER BY page_no,ordinal,id"),{"m":model,"c":code})).mappings()
    scored=[]
    for row in rows:
        score=1 if code else sum(t in normalize(query) for t in row.symptom_tags)
        if score:
            scored.append((score,dict(row)))
    scored.sort(key=lambda pair:-pair[0])
    if not scored:
        return []
    return [r for score,r in scored[:3] if score==scored[0][0]]
