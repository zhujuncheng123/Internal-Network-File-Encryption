"""认证与密码学工具：Argon2 口令哈希、JWT、RSA 密钥对与封装。"""
import base64
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from config import settings

_ph = PasswordHasher()


# ---------- 口令哈希 ----------
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ---------- RSA 密钥对（用于多接收方共享与文件密钥封装） ----------
def generate_rsa_keypair() -> tuple[str, bytes]:
    """返回 (public_key_b64_spki, private_key_pkcs8_der)。"""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    pub_b64 = pub.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    priv_der = priv.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    import base64
    return base64.b64encode(pub_b64).decode(), priv_der


def rsa_encrypt_filekey(public_key_b64: str, filekey: bytes) -> bytes:
    """用接收方公钥 RSA-OAEP(SHA-256) 封装 fileKey。"""
    import base64
    pub = serialization.load_der_public_key(base64.b64decode(public_key_b64))
    return pub.encrypt(filekey, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ))


def rsa_decrypt_filekey(private_key_der: bytes, wrapped: bytes) -> bytes:
    priv = serialization.load_der_private_key(private_key_der, password=None)
    return priv.decrypt(wrapped, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ))


# ---------- 企业密钥托管（恢复密钥对，私钥离线保管） ----------
RECOVERY_PRIVATE_KEY = "recovery_private_key_der"   # base64(PKCS8 DER)，离线导出给管理员
RECOVERY_PUBLIC_KEY = "recovery_public_key_spki"     # base64(SPKI)，存服务端用于封装


def generate_recovery_keypair() -> tuple[str, str]:
    """生成企业恢复密钥对。返回 (public_key_b64_spki, private_key_b64_pkcs8_der)。

    恢复私钥用于「忘记口令」时解封用户私钥；必须离线保管，绝不落盘于服务端。
    """
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    pub_b64 = _b64e(pub.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ))
    priv_b64 = _b64e(priv.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return pub_b64, priv_b64


def recovery_encrypt_aes_key(public_key_b64: str, aes_key: bytes) -> bytes:
    """用企业恢复公钥 RSA-OAEP 封装随机 AES 密钥。"""
    pub = serialization.load_der_public_key(base64.b64decode(public_key_b64))
    return pub.encrypt(aes_key, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ))


def recovery_decrypt_aes_key(private_key_der: bytes, wrapped: bytes) -> bytes:
    """用企业恢复私钥解封随机 AES 密钥（离线恢复工具用）。"""
    priv = serialization.load_der_private_key(private_key_der, password=None)
    return priv.decrypt(wrapped, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ))


def _b64e(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode()
