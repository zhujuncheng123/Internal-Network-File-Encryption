# 审计日志权限限制 + 审计模态框补退出按钮 交付记录

> 日期：2026-09-20

## 用户提出的两个问题

1. **审计日志是不是只有管理员能看？** —— 现状：不是。后端 `/api/files/audit`
   代码注释写着"管理员视角暂简化为返回全部"，任何登录用户都能看全部审计日志，
   前端"审计日志"按钮也对所有人显示。
2. **审计日志缺少退出按钮。** —— 审计模态框是全屏遮罩，遮住了 header 上的"退出"
   按钮，且模态框里只有"关闭"按钮，所以打开审计日志后无法退出登录。

## 修复内容

### 后端 `app/main.py`

- `/api/files/audit` 增加权限校验：
  ```python
  if not is_admin_user(user):
      raise HTTPException(403, "仅管理员可查看审计日志")
  ```
  只有 `ADMIN_USERNAMES` 里的账号能看审计日志，其他用户返回 403。

### 前端 `static/index.html`

1. **审计按钮仅管理员可见**：`enterApp()` 与初始化段都改为
   `$('btnAudit').classList.toggle('hidden', !IS_ADMIN)`，非管理员看不到"审计日志"按钮。
2. **退出逻辑提取为 `doLogout()` 函数**（原先匿名函数），并额外关闭审计模态框。
3. **审计模态框补"退出登录"按钮**：在"关闭"按钮左边加
   `<button id="btnAuditLogout">退出登录</button>`，点击调用 `doLogout()`。

## 验证结果（真实 API 实测）

| 验证项 | 结果 |
|--------|------|
| 非管理员访问 `/api/files/audit` | ✅ 返回 403 `{"detail":"仅管理员可查看审计日志"}` |
| 管理员访问 `/api/files/audit` | ✅ 返回 200，正确返回审计记录列表 |
| 前端审计模态框含"退出登录"按钮 | ✅ `btnAuditLogout` 存在 |
| 前端审计按钮仅管理员可见 | ✅ 代码改为 toggle(!IS_ADMIN) |

## 修改文件

- app/main.py：`/api/files/audit` 加管理员校验
- static/index.html：doLogout 提取、审计按钮按 IS_ADMIN 显示、模态框加退出按钮

## 注意

- 管理员判断基于 `.env` 的 `ADMIN_USERNAMES`（逗号分隔，如 `admin,zhangsan`）。
- 改动后需重启服务生效（`.env` 变更尤其要重启）。
- 前端只是隐藏按钮；真正的安全边界在后端 403 校验（已实现），即使有人绕过前端
  直调 API 也会被拦截。
