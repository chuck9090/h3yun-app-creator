# -*- coding: utf-8 -*-
"""全局资料库路由(所有登录用户共享)。

  模型:一份「资料」(名称唯一 + 描述),其下挂多份上传文档;
        夜间由 LLM 把该资料下的文档整理成《已有系统梳理》,回填到该资料(analysis)。
        项目按「资料名称」勾选参考(projects.ref_items),生成方案/ER 时并入 AI 输入。

  资料:
    GET    /api/library/items                     列表(含文档数/整理状态)
    POST   /api/library/items     {name,description}   新建(name 唯一,冲突 409)
    GET    /api/library/items/{id}                详情(描述 + 文档 + AI 整理内容)
    PATCH  /api/library/items/{id} {name?,description?}
    DELETE /api/library/items/{id}                删除(级联删文档)
  文档:
    POST   /api/library/items/{id}/documents  multipart(file)
    DELETE /api/library/documents/{docId}
  整理:
    POST   /api/library/items/{id}/analyze        手动触发整理(创建者/管理员)
"""
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import storage
from ..core import config as C
from ..core import deps
from ..db import database as db
from ..schemas import LibraryItemCreate, LibraryItemUpdate
from ..services import parsing
from ..services import library as library_service
from .documents import ALLOWED_EXTS

router = APIRouter(prefix="/api", tags=["library"])

_READ_CHUNK = 64 * 1024
_KIND = "existing_system"
_MAX_NAME = 64
_MAX_DESC = 1000


def _result(data=None, message=""):
    return {"ok": True, "data": data, "message": message}


def _item_view(it, with_analysis=False):
    docs = db.list_library_documents(it["id"])
    out = {"id": it["id"], "name": it.get("name", ""),
           "description": it.get("description", ""),
           "createdBy": it.get("created_by", 0),
           "createdAt": it.get("created_at", ""),
           "updatedAt": it.get("updated_at", ""),
           "docCount": len(docs),
           "analysisReady": bool((it.get("analysis") or "").strip()),
           "analysisAt": it.get("analysis_at", ""),
           "analysisError": it.get("analysis_error", ""),
           "docs": [_doc_view(d) for d in docs]}
    if with_analysis:
        out["analysis"] = it.get("analysis", "") or ""
    return out


def _doc_view(d):
    return {"id": d["id"], "libraryId": d.get("library_id"),
            "filename": d.get("filename", ""), "ext": d.get("ext", ""),
            "size": d.get("size", 0), "status": d.get("status", ""),
            "summary": d.get("summary", ""),
            "parsedLength": len(d.get("parsed_text") or ""),
            "createdAt": d.get("created_at", "")}


def _get_item(item_id):
    it = db.get_library_item(item_id)
    if not it:
        raise HTTPException(404, "资料不存在")
    return it


def _can_manage(it, user):
    return user["role"] == "admin" or int(it.get("created_by") or 0) == int(user["id"])


def _refresh_library_digest():
    """F3:资料增删改后立即重编译 library.md;失败仅忽略,不影响主流程。"""
    try:
        library_service.render_library_digest()
    except Exception:
        pass


@router.get("/library/items")
def list_items(user=Depends(deps.require_user)):
    return _result([_item_view(it) for it in db.list_library_items()])


@router.post("/library/items")
def create_item(body: LibraryItemCreate, user=Depends(deps.require_user)):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "资料名称不能为空")
    if len(name) > _MAX_NAME:
        raise HTTPException(400, "资料名称最长 %d 字" % _MAX_NAME)
    if len(body.description or "") > _MAX_DESC:
        raise HTTPException(400, "资料描述最长 %d 字" % _MAX_DESC)
    if db.get_library_item_by_name(name):
        raise HTTPException(409, "资料名称已存在,请换一个")
    it = db.create_library_item(name, body.description or "", created_by=user["id"])
    _refresh_library_digest()
    return _result(_item_view(it, with_analysis=True), "资料已创建")


@router.get("/library/items/{item_id}")
def get_item(item_id: int, user=Depends(deps.require_user)):
    return _result(_item_view(_get_item(item_id), with_analysis=True))


@router.patch("/library/items/{item_id}")
def update_item(item_id: int, body: LibraryItemUpdate, user=Depends(deps.require_user)):
    it = _get_item(item_id)
    if not _can_manage(it, user):
        raise HTTPException(403, "仅创建者或管理员可修改该资料")
    fields = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "资料名称不能为空")
        if len(name) > _MAX_NAME:
            raise HTTPException(400, "资料名称最长 %d 字" % _MAX_NAME)
        other = db.get_library_item_by_name(name)
        if other and other["id"] != item_id:
            raise HTTPException(409, "资料名称已存在,请换一个")
        fields["name"] = name
    if body.description is not None:
        if len(body.description) > _MAX_DESC:
            raise HTTPException(400, "资料描述最长 %d 字" % _MAX_DESC)
        fields["description"] = body.description
    if fields:
        it = db.update_library_item(item_id, **fields)
    _refresh_library_digest()
    return _result(_item_view(it, with_analysis=True), "资料已更新")


@router.delete("/library/items/{item_id}")
def delete_item(item_id: int, user=Depends(deps.require_user)):
    it = _get_item(item_id)
    if not _can_manage(it, user):
        raise HTTPException(403, "仅创建者或管理员可删除该资料")
    for d in db.list_library_documents(item_id):      # 清理上传原件
        p = d.get("stored_path")
        if p and os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass
    db.delete_library_item(item_id)
    _refresh_library_digest()
    return _result(None, "资料已删除")


@router.post("/library/items/{item_id}/documents")
async def upload_document(item_id: int, file: UploadFile = File(...),
                          user=Depends(deps.require_user)):
    it = _get_item(item_id)
    if not _can_manage(it, user):
        raise HTTPException(403, "仅创建者或管理员可为该资料上传文档")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "不支持的文件类型:%s(允许:%s)"
                            % (ext or "(无扩展名)", "、".join(ALLOWED_EXTS)))
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
    stored, ext = storage.save_library_upload(file.filename, data)
    parsed = parsing.parse_file(stored)
    doc = db.add_document(None, _KIND, file.filename or "", stored, ext, len(data),
                          parsed_text=parsed, uploaded_by=str(user["id"]), library_id=item_id)
    _refresh_library_digest()
    return _result(_doc_view(doc), "文档已上传,将在夜间整理")


@router.delete("/library/documents/{doc_id}")
def delete_document(doc_id: int, user=Depends(deps.require_user)):
    d = db.get_document(doc_id)
    if not d or d.get("library_id") is None:
        raise HTTPException(404, "文档不存在")
    it = db.get_library_item(d["library_id"])
    if not it or not _can_manage(it, user):
        raise HTTPException(403, "仅创建者或管理员可删除该文档")
    db.delete_document(doc_id)
    _refresh_library_digest()
    return _result(None, "文档已删除")


@router.post("/library/items/{item_id}/analyze")
def analyze_item(item_id: int, user=Depends(deps.require_user)):
    it = _get_item(item_id)
    if not _can_manage(it, user):
        raise HTTPException(403, "仅创建者或管理员可触发整理")
    from ..services import nightly
    res = nightly.analyze_library_item(item_id)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "整理失败")
    return _result(_item_view(res["item"], with_analysis=True),
                   "整理完成(provider=%s)" % res.get("provider"))
