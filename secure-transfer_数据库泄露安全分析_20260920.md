# 数据库泄露场景下的文件解密风险分析

> 日期：2026-09-20
> 触发问题：用户问「存在数据库，别人破解数据库后能解密出文件吗」

## 一句话结论

光拿到数据库，解不出文件；唯一薄弱点是用户口令。口令强则数据库泄露也安全，口令弱则全盘失守。

## 三层加密链路（每层都是强加密）

文件明文
  → AES-256-GCM（256位随机 fileKey 加密）→ .bin 密文

fileKey
  → 每个接收方用其 RSA-2048 公钥 OAEP(SHA-256) 封装 → file_keys.wrapped_key

RSA 私钥
  → 用「登录口令派生 KEK（PBKDF2, 310000 次迭代, SHA-256）」AES-256-GCM 加密
  → users.private_key_wrapped（+ kek_salt, kek_iv）

口令
  → Argon2id 哈希 → users.password_hash

## 数据库里的实际内容与可解性

| 字段 | 内容 | 直接可解？ |
|------|------|-----------|
| password_hash | Argon2id (m=65536, t=3) | 否（单向哈希） |
| private_key_wrapped | 口令派生 KEK 加密的私钥 | 否（需口令） |
| public_key | RSA 公钥 | 公开无害 |
| file_keys.wrapped_key | RSA-OAEP 封装的 fileKey | 否（需私钥） |
| files.iv | 文件 IV | 公开无害 |
| .bin | AES-256-GCM 密文 | 否（需 fileKey） |

## 攻击者唯一可行路径

破解口令 → 派生 KEK → 解封私钥 → 解封 fileKey → 解密 .bin

每一环强加密，所以唯一入口是「口令」。

## 薄弱点（需修复）

1. Argon2id t=3 偏低（argon2-cffi 默认值），建议 t≥10。
2. 无口令强度策略，后端仅校验 ≥8 位。
3. 根治方案：KMS 密钥托管，把私钥解锁从口令抽离。

## 加固建议（按性价比）

1. 强制强口令（≥12位 + 大小写 + 数字 + 符号）——改一处代码
2. Argon2id t=10 —— 登录慢 0.2~0.5s，暴力破解贵 3 倍
3. KMS 密钥托管 —— 大团队正解，工作量大
