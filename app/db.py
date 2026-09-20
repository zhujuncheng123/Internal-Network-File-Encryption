"""SQLite 持久化：用户(RSA密钥对)、文件、访问密钥(file_keys)、审计日志。"""
import sqlite3
import threading
from datetime import datetime, timezone

from config import settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    public_key TEXT NOT NULL,           -- base64(SPKI)  RSA 公钥
    private_key_wrapped TEXT NOT NULL,  -- base64(AES-GCM加密的PKCS8私钥)
    kek_salt TEXT NOT NULL,             -- base64(PBKDF2盐)
    kek_iv TEXT NOT NULL,               -- base64(私钥封装AES-GCM IV)
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,          -- 磁盘密文文件名
    size INTEGER NOT NULL,              -- 密文字节数
    original_size INTEGER NOT NULL,
    iv TEXT NOT NULL,                   -- 文件内容 AES-GCM IV (base64)
    created_at TEXT NOT NULL,
    expires_at TEXT,                    -- 可选 ISO 过期时间
    FOREIGN KEY (owner_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS file_keys (
    file_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    wrapped_key TEXT NOT NULL,          -- RSA-OAEP 加密的 fileKey (base64)
    created_at TEXT NOT NULL,
    PRIMARY KEY (file_id, user_id),
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,               -- register/login/upload/download/share/revoke/delete/remove_access
    file_id TEXT,
    filename TEXT,
    target TEXT,
    ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_keys_user ON file_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL;")
        _local.conn.execute("PRAGMA foreign_keys=ON;")
    return _local.conn


def init_db() -> None:
    conn = _conn()
    conn.executescript(SCHEMA)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return _conn().execute(sql, params).fetchone()


def fetch_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return _conn().execute(sql, params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    conn = _conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def purge_expired() -> tuple[int, list[str]]:
    """物理删除所有已过期文件：密文文件 + files 元数据 + file_keys 访问密钥。

    同时为每个被删除的文件写入 audit_log 留痕（action='expire'，username=owner，
    ip='system'），保证到期自动删除也有迹可查。
    返回 (删除数量, 被删除的 stored_name 列表)。调用方据此清理磁盘文件。
    """
    conn = _conn()
    now = now_iso()
    rows = conn.execute(
        "SELECT f.id, f.stored_name, f.filename, f.owner_id, u.username AS owner_name "
        "FROM files f LEFT JOIN users u ON u.id = f.owner_id "
        "WHERE f.expires_at IS NOT NULL AND f.expires_at <= ?",
        (now,),
    ).fetchall()
    if not rows:
        return 0, []
    ids = [r["id"] for r in rows]
    stored_names = [r["stored_name"] for r in rows]
    marks = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM file_keys WHERE file_id IN ({marks})", ids)
    conn.execute(f"DELETE FROM files WHERE id IN ({marks})", ids)
    # 留痕：到期自动删除也写审计（系统动作，非用户触发）
    for r in rows:
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, file_id, filename, target, ip, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (r["owner_id"], r["owner_name"] or "unknown", "expire",
             r["id"], r["filename"], "到期自动清理", "system", now),
        )
    conn.commit()
    return len(ids), stored_names
