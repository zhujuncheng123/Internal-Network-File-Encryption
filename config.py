"""应用配置。所有敏感项优先从环境变量读取，内网部署时写入 .env 或 systemd 环境。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 服务 ---
    host: str = "0.0.0.0"
    port: int = 443

    # --- 安全核心（生产必须覆盖，禁止使用默认值） ---
    # JWT 签名密钥：openssl rand -hex 32
    jwt_secret: str = "CHANGE_ME_openssl_rand_hex_32"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720  # 12 小时

    # 服务端落盘加密主密钥(KEK)。E2EE 模式下文件已是密文，此项用于加密元数据与兜底。
    # 生产用环境变量注入；留空则启动时自动生成并提示持久化。
    master_key: str = ""

    # --- 存储 ---
    data_dir: Path = BASE_DIR / "data"       # 密文文件存放目录
    db_path: Path = BASE_DIR / "data" / "app.db"
    max_upload_mb: int = 2048                # 单文件上限

    # --- 文件类型白名单（防投毒） ---
    # E2EE 下服务端只能看到密文，此处按扩展名做第二道防线；真实类型检测在前端（加密前）。
    # 逗号分隔；默认排除可执行/脚本/宏/旧版二进制 Office 等高风险格式。
    # 注意：docm/xlsm/pptm（宏）、doc/xls/ppt（旧二进制）、svg（可嵌脚本）默认不开放。
    allowed_extensions: str = (
        "jpg,jpeg,png,gif,webp,bmp,"
        "pdf,docx,xlsx,pptx,txt,csv,md,"
        "zip,"
        "mp3,wav,mp4,mov"
    )

    @property
    def allowed_ext_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    # --- 管理员（免审上传） ---
    # 逗号分隔的管理员用户名；这些用户可上传任意类型文件（含脚本/可执行），由管理员本人背书安全性。
    # 普通用户仍受 allowed_extensions 白名单限制。
    admin_usernames: str = ""

    @property
    def admin_usernames_set(self) -> set[str]:
        return {u.strip() for u in self.admin_usernames.split(",") if u.strip()}

    # --- 到期物理清理 ---
    # 后台定时任务扫描并物理删除已过期文件（删密文 + 元数据 + 访问密钥），防止磁盘/数据库无限增长。
    purge_interval_seconds: int = 60       # 扫描间隔（秒）
    purge_enabled: bool = True              # 是否启用后台自动清理

    # --- TLS（内网自签证书路径；不提供则回退 HTTP，仅供开发） ---
    cert_file: str = ""
    key_file: str = ""

    # --- HTTP -> HTTPS 自动跳转 ---
    http_redirect_enabled: bool = True
    http_port: int = 80


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
