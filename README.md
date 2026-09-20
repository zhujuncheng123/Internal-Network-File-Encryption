# 内网加密文件传输 —— 部署与使用说明

基于 FastAPI + 浏览器 Web Crypto 的**端到端加密**文件传输工具，支持多接收方共享、操作审计、文件有效期与删除。

## 安全模型（v0.2）

| 能力 | 实现 |
|------|------|
| 端到端加密 | 文件内容 AES-256-GCM，fileKey 随机生成 |
| 多接收方共享 | 每用户一对 RSA-2048 密钥对，fileKey 用接收方公钥 OAEP 独立封装 |
| 私钥保护 | 私钥用「登录口令派生 KEK」AES-GCM 加密后存服务端，仅浏览器内存解密 |
| 认证 | Argon2id 口令哈希 + JWT |
| 审计 | register/login/upload/download/share/revoke/delete/remove_access 全记录 |
| 生命周期 | 文件可设过期时间、可删除、可撤销访问 |

**核心原则**：服务端永不接触明文与明文 fileKey；每个有权用户有自己独立封装的 fileKey。

## 目录结构

```
secure-transfer/
├── config.py           # JWT密钥、存储、TLS、大小限制
├── run.py              # 启动入口
├── test_e2e.py         # 端到端集成测试（可重复跑）
├── requirements.txt
├── app/
│   ├── main.py         # 路由：认证/上传/下载/共享/撤销/审计/过期/删除
│   ├── db.py           # SQLite：users/files/file_keys/audit_log
│   └── security.py     # Argon2 + JWT + RSA 密钥对
└── static/index.html   # 前端（Web Crypto E2EE + UI）
```

## 部署

```bash
cd secure-transfer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 生产密钥 + TLS
openssl rand -hex 32                    # → 作为 JWT_SECRET
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout server.key -out server.crt -subj "/CN=内网IP或域名"

cat > .env <<EOF
JWT_SECRET=上面生成的hex
CERT_FILE=./server.crt
KEY_FILE=./server.key
MAX_UPLOAD_MB=2048
EOF

.venv/bin/python run.py   # 监听 0.0.0.0:8443
```

浏览器访问 `https://<内网IP>:8443`。

## 验证结果（test_e2e.py 全通过）

1. 注册（含 RSA 密钥对）✅
2. 登录 ✅
3. AES-GCM 加密上传 ✅
4. 文件列表（owner 视角）✅
5. 未共享用户不可见 ✅
6. 共享给他人 ✅
7. 接收方下载 + 私钥解封 fileKey + 解密，**内容与明文一致** ✅
8. 审计日志记录 upload/share/download ✅
9. 撤销访问 ✅
10. 过期文件返回 410 ✅
11. 删除文件 ✅

## 上线前必做

1. **替换 JWT_SECRET** 默认值。
2. **启用 TLS**，否则传输层裸奔。
3. **审计日志权限**：当前 `/api/files/audit` 返回全部记录，正式环境应限制为管理员角色。
4. **用户管理**：当前开放注册，内网建议改为邀请制或 LDAP/SSO 对接。
5. **备份**：`data/`（密文 + app.db）必须纳入备份，丢失则无法解密。
6. **过期清理**：过期文件仅在下达请求时拦截，未物理删除；可加定时任务清理过期密文。

## 设计取舍（重要）

- **口令 = 私钥的唯一保护**：用户忘记登录口令，其私钥无法恢复 → 名下文件永久不可解密。需提前设计口令重置与密钥托管（如企业级密钥托管/KMS）方案。
- **非对称封装**：fileKey 用 RSA-2048 封装，单文件开销固定（约 256 字节），适合中小文件；超大文件建议改「RSA 封装临时对称密钥 + 对称密钥加密 fileKey」的分层方案以降低开销。
