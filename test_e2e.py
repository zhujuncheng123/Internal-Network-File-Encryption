"""端到端集成测试：模拟浏览器 Web Crypto 流程，验证后端完整功能。

覆盖：注册(RSA密钥对)、登录、上传(AES-GCM加密+RSA封装)、共享、下载解密、
审计日志、文件过期、删除/撤销。
"""
import base64
import json
import os
import urllib.request
import urllib.error
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = "http://127.0.0.1:8443"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


class Client:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token = None
        # RSA 密钥对
        self.priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pub = self.priv.public_key()
        self.pub_b64 = b64(self.pub.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.priv_der = self.priv.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())

    # ---- 用口令封装/解封私钥（模拟浏览器 PBKDF2 + AES-GCM）----
    def _derive_kek(self, salt):
        # 简化：用 SHA-256 派生 32 字节密钥（测试专用，生产用 PBKDF2）
        import hashlib
        return hashlib.pbkdf2_hmac('sha256', self.password.encode(), salt, 310000, 32)

    def wrap_private_key(self):
        salt = os.urandom(16)
        iv = os.urandom(12)
        kek = self._derive_kek(salt)
        wrapped = AESGCM(kek).encrypt(iv, self.priv_der, None)
        return b64(wrapped), b64(salt), b64(iv)

    # ---- 文件加密 ----
    def encrypt_file(self, data: bytes):
        filekey = AESGCM.generate_key(bit_length=256)
        iv = os.urandom(12)
        cipher = AESGCM(filekey).encrypt(iv, data, None)
        return cipher, filekey, iv

    def wrap_filekey_rsa(self, filekey: bytes, pub_b64: str):
        pub = serialization.load_der_public_key(b64d(pub_b64))
        return pub.encrypt(filekey, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))

    def unwrap_filekey_rsa(self, wrapped: bytes):
        return self.priv.decrypt(wrapped, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))

    # ---- HTTP ----
    def _req(self, method, path, data=None, headers=None, form=None):
        url = BASE + path
        h = headers or {}
        body = None
        if self.token:
            h['Authorization'] = 'Bearer ' + self.token
        if form is not None:
            boundary = uuid.uuid4().hex
            parts = []
            for k, v in form.items():
                if isinstance(v, tuple):  # (filename, bytes)
                    fn, content = v
                    parts.append(
                        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\n"
                        f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
                else:
                    parts.append(
                        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            h['Content-Type'] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            body = json.dumps(data).encode()
            h['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except Exception:
                return e.code, {}

    def register(self):
        wrapped, salt, iv = self.wrap_private_key()
        return self._req('POST', '/api/auth/register', form={
            'username': self.username, 'password': self.password,
            'public_key': self.pub_b64, 'private_key_wrapped': wrapped,
            'kek_salt': salt, 'kek_iv': iv,
        })

    def login(self):
        code, data = self._req('POST', '/api/auth/login', form={
            'username': self.username, 'password': self.password})
        if code == 200:
            self.token = data['access_token']
        return code, data

    def upload(self, filename, data, expires_at=""):
        cipher, filekey, iv = self.encrypt_file(data)
        wrapped = self.wrap_filekey_rsa(filekey, self.pub_b64)
        code, resp = self._req('POST', '/api/files/upload', form={
            'file': (filename, cipher),
            'filename': filename,
            'iv': b64(iv),
            'wrapped_key': b64(wrapped),
            'original_size': str(len(data)),
            'expires_at': expires_at,
        })
        return code, resp, filekey, iv, cipher

    def list_files(self):
        return self._req('GET', '/api/files')

    def share(self, file_id, target_uid, filekey, target_pub_b64):
        wrapped = self.wrap_filekey_rsa(filekey, target_pub_b64)
        return self._req('POST', '/api/files/share', data={
            'file_id': file_id, 'target_user_id': target_uid, 'wrapped_key': b64(wrapped)})

    def download(self, file_id):
        url = BASE + f'/api/files/{file_id}/download'
        h = {'Authorization': 'Bearer ' + self.token}
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b''


def main():
    alice = Client("alice", "alice-pass-123")
    bob = Client("bob", "bob-pass-123")

    print("=== 1. 注册 alice/bob ===")
    print("alice:", alice.register())
    print("bob:", bob.register())

    print("=== 2. 登录 ===")
    print("alice:", alice.login()[0], "bob:", bob.login()[0])

    print("=== 3. alice 上传加密文件 ===")
    plaintext = "这是一份机密文件内容 - secret payload".encode() * 100
    code, resp, filekey, iv, cipher = alice.upload("机密计划.txt", plaintext)
    file_id = resp['id']
    print("upload code:", code, "file_id:", file_id)
    assert code == 200

    print("=== 4. alice 文件列表 ===")
    code, files = alice.list_files()
    print("alice files:", [(f['filename'], f['is_owner']) for f in files])
    assert any(f['id'] == file_id and f['is_owner'] for f in files)

    print("=== 5. bob 看不到 alice 的文件 ===")
    code, files = bob.list_files()
    assert not any(f['id'] == file_id for f in files), "bob 不应看到未共享的文件"
    print("bob files 数量:", len(files), "（正确为空）")

    print("=== 6. alice 共享给 bob ===")
    # 获取 bob 的 uid 和公钥
    code, search = alice._req('GET', '/api/users/search?q=bob')
    bob_uid = search[0]['id']
    bob_pub = search[0]['public_key']
    code, resp = alice.share(file_id, bob_uid, filekey, bob_pub)
    print("share:", code, resp)
    assert code == 200

    print("=== 7. bob 现在能看到并下载解密 ===")
    code, files = bob.list_files()
    assert any(f['id'] == file_id and not f['is_owner'] for f in files)
    print("bob 可见:", [(f['filename'], f['is_owner']) for f in files])

    code, cipher_downloaded = bob.download(file_id)
    assert code == 200
    # bob 用私钥解封 filekey 再解密
    meta_code, meta = bob._req('GET', f'/api/files/{file_id}/meta')
    assert meta_code == 200
    bob_filekey = bob.unwrap_filekey_rsa(b64d(meta['wrapped_key']))
    decrypted = AESGCM(bob_filekey).decrypt(b64d(meta['iv']), cipher_downloaded, None)
    assert decrypted == plaintext, "解密结果不匹配！"
    print("bob 解密成功，内容一致 ✓")

    print("=== 8. 审计日志 ===")
    code, audit = alice._req('GET', '/api/files/audit')
    actions = [a['action'] for a in audit]
    print("动作记录:", actions)
    assert 'upload' in actions and 'share' in actions and 'download' in actions

    print("=== 9. 撤销 bob 访问 ===")
    code, resp = alice._req('POST', '/api/files/revoke', data={
        'file_id': file_id, 'target_user_id': bob_uid})
    print("revoke:", code, resp)
    code, files = bob.list_files()
    assert not any(f['id'] == file_id for f in files)
    print("bob 访问已撤销 ✓")

    print("=== 10. 文件过期 ===")
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    code, resp, fk2, iv2, c2 = alice.upload("过期文件.txt", b"expired data", expires_at=past)
    exp_id = resp['id']
    code, _ = alice.download(exp_id)
    print("过期文件下载 code:", code, "（应为 410）")
    assert code == 410

    print("=== 11. 删除文件 ===")
    code, resp = alice._req('DELETE', f'/api/files/{file_id}')
    print("delete:", code, resp)
    assert code == 200 and resp.get('deleted') is True
    code, files = alice.list_files()
    assert not any(f['id'] == file_id for f in files)

    print("\n✅ 全部集成测试通过")


if __name__ == "__main__":
    main()
