# 内网加密文件传输 —— 部署与使用说明

基于 FastAPI + 浏览器 Web Crypto 的**端到端加密**文件传输工具，支持多接收方共享、操作审计、文件有效期与删除、企业密钥托管（忘记口令可恢复）。

## 安全模型（v0.3）

| 能力 | 实现 |
|------|------|
| 端到端加密 | 文件内容 AES-256-GCM，fileKey 随机生成 |
| 多接收方共享 | 每用户一对 RSA-2048 密钥对，fileKey 用接收方公钥 OAEP 独立封装 |
| 私钥保护 | 私钥用「登录口令派生 KEK」AES-GCM 加密后存服务端，仅浏览器内存解密 |
| 认证 | Argon2id 口令哈希 + JWT |
| 审计 | register/login/upload/download/share/revoke/delete/remove_access/expire 全记录，仅管理员可查 |
| 生命周期 | 文件可设过期时间、可删除、可撤销访问；过期自动物理删除 |
| 密钥托管 | 企业恢复公钥再封接一份用户私钥，忘记口令可恢复（私钥离线保管） |
| 防投毒 | 扩展名白名单 + 真实类型魔数检测 + zip 递归扫描 |

**核心原则**：服务端永不接触明文与明文 fileKey；每个有权用户有自己独立封装的 fileKey。

## 目录结构

```
secure-transfer/
├── config.py           # JWT密钥、存储、TLS、大小限制、清理配置
├── run.py              # 启动入口（HTTPS 443 + HTTP 80 跳转）
├── test_e2e.py         # 端到端集成测试（可重复跑）
├── requirements.txt
├── app/
│   ├── main.py         # 路由：认证/上传/下载/共享/撤销/审计/过期/删除/恢复密钥
│   ├── db.py           # SQLite：users/files/file_keys/audit_log/system_config
│   └── security.py     # Argon2 + JWT + RSA 密钥对 + 恢复密钥
├── tools/
│   ├── gen_recovery_key.py  # 生成企业恢复密钥对（离线）
│   └── recover_user.py      # 忘记口令时离线恢复（管理员）
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
HOST=0.0.0.0
PORT=443
MAX_UPLOAD_MB=2048
ADMIN_USERNAMES=admin
EOF

.venv/bin/python run.py   # HTTPS 0.0.0.0:443，HTTP 0.0.0.0:80 自动跳转
```

浏览器访问 `https://<内网IP>`（或 `https://<内网IP>:443`）。

## 企业密钥托管（忘记口令恢复）

> 默认设计下「口令 = 私钥的唯一保护」，忘口令则名下文件永久无法解密。
> 密钥托管用「企业恢复密钥」额外封装一份私钥，使管理员可协助找回，且文件不丢。

### 1. 一次性初始化（管理员离线操作）

```bash
# 生成企业恢复密钥对（私钥离线保管，绝不进服务器/不进 git）
.venv/bin/python tools/gen_recovery_key.py --out ./recovery_keys

# 把公钥导入服务器（recovery_public.pem 的内容）
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, '.')
from app import db, security
pub = open('recovery_keys/recovery_public.pem').read().strip()
db.set_config(security.RECOVERY_PUBLIC_KEY, pub)
print('恢复公钥已导入')
EOF
```

> 或由管理员登录后调用 `POST /api/admin/recovery/config` 接口导入。

### 2. 用户忘记口令时（管理员离线操作）

```bash
.venv/bin/python tools/recover_user.py \
  --db data/app.db \
  --private-key recovery_keys/recovery_private.pem \
  --username 忘记口令的用户名 \
  --new-password '用户新设的口令'
```

完成后用户用新口令登录，名下文件全部可解密。

**⚠️ 安全红线**：`recovery_private.pem` 是企业恢复密钥的私钥，任何人拿到它 = 可解密全公司所有用户的私钥与文件。必须离线保管（打印/U盘/保险柜），绝不落盘于服务器或提交 git。

## 验证结果（test_e2e.py 全通过）

1. 注册（含 RSA 密钥对 + 恢复封装）✅
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
12. 企业密钥托管：忘口令后离线恢复，新口令可解出原私钥 ✅

## 上线前必做

1. **替换 JWT_SECRET** 默认值。
2. **启用正式 TLS**（当前为自签证书，正式环境换受信证书）。
3. **用户管理**：当前开放注册，内网建议改为邀请制或 LDAP/SSO 对接。
4. **备份**：`data/`（密文 + app.db）必须纳入备份，丢失则无法解密。
5. **审计日志清理策略**：审计记录会累积，建议加「保留 N 天」策略。
6. **多 worker**：当前单 worker，大团队高并发建议多 worker + 千兆/万兆内网。
7. **Argon2id 强度**：当前 t=3 偏低，建议提到 t≥10。

## 设计取舍（重要）

- **口令 = 私钥的唯一保护**（未启用托管时）：忘口令则私钥无法恢复 → 名下文件永久不可解密。启用「企业密钥托管」可解决（见上文）。
- **非对称封装**：fileKey 用 RSA-2048 封装，单文件开销固定（约 256 字节），适合中小文件；超大文件建议改「RSA 封装临时对称密钥 + 对称密钥加密 fileKey」的分层方案以降低开销。
