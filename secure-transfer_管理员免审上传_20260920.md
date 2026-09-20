# 管理员免审上传（账号权限分级）交付记录

> 日期：2026-09-20
> 需求：管理员自己确定文件安全性后，把脚本/特殊类型文件传输给用户。

## 用户决策背景

脚本（.sh/.bat/.ps1/.py）在 E2EE 白名单体系下被一刀切拦截，
因为"正常脚本 vs 恶意脚本"在文件头层面无法区分。
用户提出：给管理员一个"免审上传"权限，由管理员本人背书文件安全性后再分发给用户。

## 关键约束（E2EE 固有）

管理员也看不到文件明文（端到端加密，服务端只存密文）。
所以"管理员确定安全性"= 管理员本人是可信来源（他此前已从别处确认文件安全），
而非"管理员打开文件看内容判断"。
正确形态：管理员可上传任意类型，再走现有「共享」功能分发给用户。

## 实现

### 后端

- `config.py` 新增 `admin_usernames: str`（逗号分隔）+ `admin_usernames_set` 属性。
- `app/main.py`：
  - 新增 `is_admin_user(user)` 辅助函数。
  - `/api/auth/me` 返回体新增 `is_admin` 字段。
  - 上传接口：`if not is_admin_user(user): _validate_ext(filename)` —— 管理员跳过扩展名白名单校验。

### 前端

- `static/index.html`：
  - 新增全局 `IS_ADMIN`（localStorage 持久化 `st_admin`，刷新不丢）。
  - 登录成功后从 `/api/auth/me` 读 `is_admin` 写入 IS_ADMIN。
  - 登出时清除。
  - 上传逻辑：`if (!IS_ADMIN) await validateFileType(pendingFile);` —— 管理员跳过前端类型检测。
  - UI：管理员登录后显示「管理员」标识 + 上传区黄色提示「管理员免审模式」。

### 配置

- `.env` 新增 `ADMIN_USERNAMES=admin`（现有 admin 账号即管理员）。
- 多管理员逗号分隔，如 `ADMIN_USERNAMES=admin,zhangsan`。

## 验证（真实 API 端到端）

- ① `/api/auth/me` 对管理员返回 `is_admin: True` ✅
- ② 管理员上传 `.sh` 脚本 → HTTP 200 成功 ✅
- ③ 普通用户(alice)上传 `.sh` 脚本 → HTTP 415 拒绝 ✅

## 修改文件

- config.py：+admin_usernames 字段与属性
- app/main.py：+is_admin_user、me 返回 is_admin、上传跳过白名单
- static/index.html：+IS_ADMIN 状态、登录写入、上传跳过、管理员 UI 提示
- .env：+ADMIN_USERNAMES=admin

## 注意事项

1. 管理员免审意味着：管理员账号被攻破 → 可上传任意恶意文件。
   管理员账号务必用强口令（当前 Argon2id t=3 偏低，上线前建议提到 t≥10）。
2. 服务端第二道防线对管理员"完全放开"（非仅扩展名），这是信任模型的明确选择。
3. 上传的文件仍会被 E2EE 加密，密文落盘；管理员"免审"只影响类型检查，不影响加密。
4. 建议后续配合「审计日志按角色限制」：管理员上传任意类型应留清晰审计记录（当前已有 upload 审计）。
