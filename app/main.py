"""FastAPI 主应用。

安全模型（端到端加密 + 多接收方共享）：
- 每个用户一对 RSA-2048 密钥对：公钥明文存服务端；私钥用「登录口令派生 KEK」AES-GCM 加密后存服务端。
  登录后浏览器用口令解密私钥进内存（服务端永不接触明文私钥）。
- 文件内容：AES-256-GCM 加密，fileKey 随机生成。
- fileKey 分发：为每个有权访问的用户，用其 RSA 公钥 OAEP 封装一份 file_key（存入 file_keys 表）。
- 服务端只存密文 + 各用户独立封装的 fileKey，永不接触明文与明文 fileKey。
- 审计日志记录 register/login/upload/download/share/revoke/delete/remove_access。
"""
import base64
import ipaddress
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db, security
from config import settings

app = FastAPI(title="内网加密文件传输", version="0.2.0")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 统一过期时间格式：前端传 ISO；为兼容前端传「天数」外的简单场景，这里约定传 ISO 字符串。
EXPIRES_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _audit(user: dict, action: str, request: Request, file_id=None, filename=None, target=None):
    db.execute(
        "INSERT INTO audit_log (user_id, username, action, file_id, filename, target, ip, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (user["id"], user["username"], action, file_id, filename, target, _client_ip(request), db.now_iso()),
    )


def _validate_ext(filename: str) -> None:
    """扩展名白名单（服务端第二道防线）。E2EE 下服务端只能看扩展名，真实类型在前端检测。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_ext_set:
        raise HTTPException(415, f"不允许的文件类型：.{ext or '(无扩展名)'}")


def is_admin_user(user: dict) -> bool:
    return user["username"] in settings.admin_usernames_set


def _parse_expiry(raw: str | None) -> str | None:
    """解析 ISO 时间；无法解析返回 None（不设过期）。"""
    if not raw:
        return None
    for fmt in EXPIRES_FORMATS:
        try:
            return datetime.strptime(raw, fmt).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


# ---------- 认证依赖 ----------
def current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="未提供凭证")
    try:
        payload = security.decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="凭证无效或已过期")
    user = db.fetch_one("SELECT * FROM users WHERE username = ?", (payload["sub"],))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return dict(user)


def _purge_loop():
    """后台守护线程：定期扫描并物理删除已过期文件。"""
    while True:
        try:
            count, stored_names = db.purge_expired()
            for name in stored_names:
                (settings.data_dir / name).unlink(missing_ok=True)
            if count:
                print(f"[purge] 已物理删除 {count} 个过期文件", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[purge] 清理异常：{e}", flush=True)
        time.sleep(settings.purge_interval_seconds)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.purge_enabled:
        threading.Thread(target=_purge_loop, daemon=True, name="purge-expired").start()


# ---------- 认证接口 ----------
@app.post("/api/auth/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    public_key: str = Form(...),          # base64 SPKI
    private_key_wrapped: str = Form(...), # base64
    kek_salt: str = Form(...),            # base64
    kek_iv: str = Form(...),              # base64
):
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="口令至少 8 位")
    if db.fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    db.execute(
        "INSERT INTO users (username, password_hash, public_key, private_key_wrapped, "
        "kek_salt, kek_iv, created_at) VALUES (?,?,?,?,?,?,?)",
        (username, security.hash_password(password), public_key,
         private_key_wrapped, kek_salt, kek_iv, db.now_iso()),
    )
    # 注册也记录审计
    u = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    _audit(dict(u), "register", request)
    return {"ok": True, "id": u["id"]}


@app.post("/api/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not user or not security.verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或口令错误")
    token = security.create_access_token(user["username"], {"uid": user["id"]})
    _audit(dict(user), "login", request)
    return {"access_token": token, "token_type": "bearer", "username": username}


@app.get("/api/auth/me")
async def me(user: dict = Depends(current_user)):
    """返回当前用户私钥解密所需的材料（不返回私钥本身）。"""
    return {
        "username": user["username"],
        "id": user["id"],
        "is_admin": is_admin_user(user),
        "public_key": user["public_key"],
        "private_key_wrapped": user["private_key_wrapped"],
        "kek_salt": user["kek_salt"],
        "kek_iv": user["kek_iv"],
    }


@app.get("/api/users/search")
async def search_users(q: str = "", user: dict = Depends(current_user)):
    """按用户名前缀搜索（用于共享选人）；返回 id/username/public_key。"""
    rows = db.fetch_all(
        "SELECT id, username, public_key FROM users WHERE username LIKE ? AND id != ? ORDER BY username LIMIT 20",
        (f"%{q}%", user["id"]),
    )
    return [dict(r) for r in rows]


# ---------- 文件接口 ----------
class ShareBody(BaseModel):
    file_id: str
    target_user_id: int
    wrapped_key: str  # base64 RSA-OAEP 加密的 fileKey


class RevokeBody(BaseModel):
    file_id: str
    target_user_id: int


@app.get("/api/files")
async def list_files(user: dict = Depends(current_user)):
    """列出当前用户可访问的文件（自有 + 被共享）。已过期文件不再展示（后台会物理删除）。"""
    now = db.now_iso()
    rows = db.fetch_all(
        """
        SELECT f.id, f.filename, f.size, f.original_size, f.created_at, f.expires_at,
               f.owner_id, u.username AS owner_name,
               (f.owner_id = ?) AS is_owner
        FROM file_keys fk
        JOIN files f ON f.id = fk.file_id
        JOIN users u ON u.id = f.owner_id
        WHERE fk.user_id = ? AND (f.expires_at IS NULL OR f.expires_at > ?)
        ORDER BY f.created_at DESC
        """,
        (user["id"], user["id"], now),
    )
    result = []
    for r in rows:
        d = dict(r)
        d["is_owner"] = bool(d["is_owner"])
        result.append(d)
    return result


@app.get("/api/users/public_key/{user_id}")
async def get_public_key(user_id: int, user: dict = Depends(current_user)):
    """获取指定用户公钥（共享时封装 fileKey 用）。"""
    row = db.fetch_one("SELECT id, username, public_key FROM users WHERE id = ?", (user_id,))
    if not row:
        raise HTTPException(404, "用户不存在")
    return dict(row)


@app.get("/api/files/audit")
async def list_audit(
    user: dict = Depends(current_user),
    q: str = "",
    page: int = 1,
    page_size: int = 50,
):
    """审计日志：仅管理员可查看。支持按 IP/用户名/文件名/动作/目标搜索 + 分页。"""
    if not is_admin_user(user):
        raise HTTPException(403, "仅管理员可查看审计日志")
    page = max(1, page)
    page_size = max(1, min(200, page_size))

    q = q.strip()
    where, params = "", []
    if q:
        like = f"%{q}%"
        where = "WHERE username LIKE ? OR ip LIKE ? OR filename LIKE ? OR action LIKE ? OR target LIKE ?"
        params = [like, like, like, like, like]

    total = db.fetch_one(
        f"SELECT COUNT(*) AS c FROM audit_log {where}", params
    )["c"]
    rows = db.fetch_all(
        f"SELECT * FROM audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    )
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@app.post("/api/files/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    filename: str = Form(...),
    iv: str = Form(...),                 # 文件内容 AES-GCM IV (base64)
    wrapped_key: str = Form(...),        # 上传者自己 RSA-OAEP 封装的 fileKey (base64)
    original_size: int = Form(...),
    expires_at: str = Form(""),          # 可选 ISO 时间
    user: dict = Depends(current_user),
):
    if not is_admin_user(user):
        _validate_ext(filename)
    file_id = uuid.uuid4().hex
    stored_name = f"{file_id}.bin"
    dest = settings.data_dir / stored_name

    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "超出单文件大小限制")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, "写入失败")

    expiry = _parse_expiry(expires_at)
    db.execute(
        "INSERT INTO files (id, owner_id, filename, stored_name, size, original_size, "
        "iv, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (file_id, user["id"], filename, stored_name, size, original_size,
         iv, db.now_iso(), expiry),
    )
    # 上传者自己的 fileKey
    db.execute(
        "INSERT INTO file_keys (file_id, user_id, wrapped_key, created_at) VALUES (?,?,?,?)",
        (file_id, user["id"], wrapped_key, db.now_iso()),
    )
    _audit(user, "upload", request, file_id=file_id, filename=filename)
    return {"id": file_id, "size": size, "expires_at": expiry}


@app.get("/api/files/{file_id}/meta")
async def file_meta(file_id: str, user: dict = Depends(current_user)):
    row = db.fetch_one(
        """
        SELECT f.id, f.filename, f.size, f.original_size, f.iv, f.created_at, f.expires_at,
               f.owner_id, u.username AS owner_name,
               fk.wrapped_key
        FROM file_keys fk
        JOIN files f ON f.id = fk.file_id
        JOIN users u ON u.id = f.owner_id
        WHERE fk.file_id = ? AND fk.user_id = ?
        """,
        (file_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "文件不存在或无权访问")
    return dict(row)


@app.get("/api/files/{file_id}/accesses")
async def file_accesses(file_id: str, user: dict = Depends(current_user)):
    """列出可访问该文件的用户（仅 owner 可查看）。"""
    f = db.fetch_one("SELECT * FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    if not f:
        raise HTTPException(404, "文件不存在或无权查看")
    rows = db.fetch_all(
        """
        SELECT u.id, u.username, fk.created_at,
               (f.owner_id = u.id) AS is_owner
        FROM file_keys fk
        JOIN users u ON u.id = fk.user_id
        JOIN files f ON f.id = fk.file_id
        WHERE fk.file_id = ?
        ORDER BY is_owner DESC, u.username
        """,
        (file_id,),
    )
    return [dict(r) for r in rows]


@app.post("/api/files/share")
async def share_file(body: ShareBody, request: Request, user: dict = Depends(current_user)):
    f = db.fetch_one("SELECT * FROM files WHERE id = ? AND owner_id = ?", (body.file_id, user["id"]))
    if not f:
        raise HTTPException(404, "文件不存在或无权共享")
    target = db.fetch_one("SELECT * FROM users WHERE id = ?", (body.target_user_id,))
    if not target:
        raise HTTPException(404, "目标用户不存在")
    # 幂等：已存在则更新 wrapped_key（理论上同一 fileKey 相同，但允许重设）
    db.execute(
        "INSERT INTO file_keys (file_id, user_id, wrapped_key, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(file_id, user_id) DO UPDATE SET wrapped_key=excluded.wrapped_key",
        (body.file_id, body.target_user_id, body.wrapped_key, db.now_iso()),
    )
    _audit(user, "share", request, file_id=body.file_id, filename=f["filename"], target=target["username"])
    return {"ok": True}


@app.post("/api/files/revoke")
async def revoke_file(body: RevokeBody, request: Request, user: dict = Depends(current_user)):
    f = db.fetch_one("SELECT * FROM files WHERE id = ? AND owner_id = ?", (body.file_id, user["id"]))
    if not f:
        raise HTTPException(404, "文件不存在或无权操作")
    target = db.fetch_one("SELECT * FROM users WHERE id = ?", (body.target_user_id,))
    db.execute("DELETE FROM file_keys WHERE file_id = ? AND user_id = ? AND user_id != ?",
               (body.file_id, body.target_user_id, user["id"]))
    _audit(user, "revoke", request, file_id=body.file_id, filename=f["filename"],
           target=target["username"] if target else str(body.target_user_id))
    return {"ok": True}


@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str, request: Request, user: dict = Depends(current_user)):
    """删除文件：owner 可物理删除；非 owner 移除自己的访问权。"""
    f = db.fetch_one("SELECT * FROM files WHERE id = ?", (file_id,))
    if not f:
        raise HTTPException(404, "文件不存在")

    if f["owner_id"] == user["id"]:
        # 物理删除：删密文 + 元数据 + 所有 file_keys
        path = settings.data_dir / f["stored_name"]
        path.unlink(missing_ok=True)
        db.execute("DELETE FROM file_keys WHERE file_id = ?", (file_id,))
        db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        _audit(user, "delete", request, file_id=file_id, filename=f["filename"])
        return {"ok": True, "deleted": True}
    else:
        # 移除自己的访问权
        db.execute("DELETE FROM file_keys WHERE file_id = ? AND user_id = ?", (file_id, user["id"]))
        _audit(user, "remove_access", request, file_id=file_id, filename=f["filename"])
        return {"ok": True, "deleted": False}


@app.get("/api/files/{file_id}/download")
async def download(file_id: str, request: Request, user: dict = Depends(current_user)):
    row = db.fetch_one(
        "SELECT f.stored_name, f.filename, f.expires_at FROM files f "
        "JOIN file_keys fk ON fk.file_id = f.id "
        "WHERE f.id = ? AND fk.user_id = ?",
        (file_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "文件不存在或无权访问")
    # 过期检查
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp <= datetime.now(timezone.utc):
                raise HTTPException(410, "文件已过期")
        except ValueError:
            pass
    path = settings.data_dir / row["stored_name"]
    if not path.exists():
        raise HTTPException(404, "密文文件丢失")
    _audit(user, "download", request, file_id=file_id, filename=row["filename"])
    return FileResponse(path, filename=row["filename"], media_type="application/octet-stream")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# 静态前端（最后挂载）
app.mount("/", StaticFiles(directory=settings.data_dir.parent / "static", html=True), name="static")
