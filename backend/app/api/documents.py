# -*- coding: utf-8 -*-
"""文档路由。见 docs/ARCHITECTURE.md §5「文档」。

  POST /api/projects/{id}/documents  multipart(file, kind)  拖拽上传,解析入库
  GET  /api/projects/{id}/documents
  GET  /api/documents/{docId}
  DELETE /api/documents/{docId}
"""
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import storage
from ..core import config as C
from ..core import deps
from ..db import database as db
from ..services import parsing

router = APIRouter(prefix="/api", tags=["documents"])

# 允许上传的扩展名白名单(与 services.parsing 的解析能力一致)
ALLOWED_EXTS = (".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml",
                ".xlsx", ".xlsm", ".docx", ".pdf")

_READ_CHUNK = 64 * 1024


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _summary(d, with_text=False):
    out = {"id": d["id"], "projectId": d.get("project_id"),
           "kind": d.get("kind", ""), "filename": d.get("filename", ""),
           "ext": d.get("ext", ""), "size": d.get("size", 0),
           "status": d.get("status", ""), "summary": d.get("summary", ""),
           "tags": d.get("tags", ""), "uploadedBy": d.get("uploaded_by", ""),
           "createdAt": d.get("created_at", ""),
           "parsedLength": len(d.get("parsed_text") or "")}
    if with_text:
        out["parsedText"] = d.get("parsed_text") or ""
    return out


@router.post("/projects/{pid}/documents")
async def upload_document(pid: int, file: UploadFile = File(...),
                          kind: str = Form("other"),
                          user=Depends(deps.get_current_user)):
    p = deps.get_project(pid, user, write=True)
    if kind not in db.DOC_KINDS:
        raise HTTPException(400, "非法文档类型:%s" % kind)
    # 「需求清单」是需求基准,每个项目只允许一份;要替换须先删除已有的。
    if kind == "requirement" and db.list_documents(project_id=pid, kind="requirement"):
        raise HTTPException(409, "需求清单只允许上传一份,请先删除已有的需求清单再上传")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "不支持的文件类型:%s(允许:%s)"
                            % (ext or "(无扩展名)", "、".join(ALLOWED_EXTS)))
    # 分块读取并即时校验,超限立即中止,避免把超大文件整体读入内存。
    max_bytes = C.MAX_UPLOAD_MB * 1024 * 1024
    buf = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, "文件超过 %d MB 上限" % C.MAX_UPLOAD_MB)
    data = bytes(buf)
    if not data:
        raise HTTPException(400, "文件内容为空")
    os.makedirs(os.path.join(storage.project_dir(p["slug"], create=True), "uploads"),
                exist_ok=True)
    stored, ext = storage.save_upload(p["slug"], file.filename, data)
    parsed = parsing.parse_file(stored)
    doc = db.add_document(p["id"], kind, file.filename or "", stored, ext, len(data),
                          parsed_text=parsed, uploaded_by=str(user["id"]))
    return _result(_summary(doc), "文档已上传")


@router.get("/projects/{pid}/documents")
def list_documents(pid: int, kind: str = "", user=Depends(deps.get_current_user)):
    deps.get_project(pid, user)
    if kind and kind not in db.DOC_KINDS:
        raise HTTPException(400, "非法文档类型:%s" % kind)
    docs = db.list_documents(project_id=pid, kind=kind or None)
    return _result([_summary(d) for d in docs])


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, user=Depends(deps.get_current_user)):
    d = db.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    deps.get_project(d.get("project_id"), user)
    return _result(_summary(d, with_text=True))


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user=Depends(deps.get_current_user)):
    d = db.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    deps.get_project(d.get("project_id"), user, write=True)
    db.delete_document(doc_id)
    return _result(None, "文档已删除")
