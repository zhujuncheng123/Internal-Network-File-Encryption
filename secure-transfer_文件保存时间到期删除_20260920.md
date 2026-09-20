# 文件保存时间 + 到期物理删除 交付记录

> 日期：2026-09-20
> 需求：文件设置保存时间，到期自动删除，防止数据库/磁盘容量爆掉。

## 需求本质

此前「有效期」功能只做到「到期拦截访问返回 410」，密文文件仍躺在磁盘、
数据库记录仍在 —— 容量照样会涨。本次把它升级为「到期物理删除」。

## 实现

### 后端

- `config.py` 新增：
  - `purge_interval_seconds: int = 60`（后台扫描间隔，秒）
  - `purge_enabled: bool = True`（是否启用自动清理）
- `app/db.py` 新增 `purge_expired()`：
  - 查 `expires_at IS NOT NULL AND expires_at <= now` 的文件
  - 删 file_keys + files 记录，返回 (数量, stored_name 列表)
- `app/main.py`：
  - 新增后台守护线程 `_purge_loop()`：每 `purge_interval_seconds` 秒调用
    purge_expired，并 unlink 对应密文文件，打印 `[purge]` 日志。
  - `_startup()` 中启动该线程（daemon）。
  - `GET /api/files` 列表 SQL 增加 `(f.expires_at IS NULL OR f.expires_at > now)`
    过滤，已过期文件不再展示（后台会随即物理删除）。

### 前端

- `static/index.html` 上传区改为「保存时间」下拉选择：
  - 永久保存 / 1 天 / 7 天(默认) / 30 天 / 90 天 / 自定义时间…
  - 选「自定义时间…」时显示 datetime-local 精确时间输入框。
- 新增 `computeExpiry()`：按天数算出 ISO 过期时间；自定义则读时间输入框。
- 上传后重置控件回默认 7 天。

## 关键设计说明

1. 后台线程是「兜底」：即使无人访问，到期文件也会被清理，真正防容量爆。
2. 列表过滤 + 物理删除双保险：列表立刻不显示过期文件，线程随后删密文。
3. 过期时间存的是 ISO 时间（UTC），比较用字符串 ISO 字典序（同格式可安全比较）。
4. 删除是物理的：密文文件 unlink + files 记录 + file_keys 记录全删。

## 验证（真实端到端）

- ✅ 上传 1 天后过期文件 → 密文落盘成功
- ✅ 手动把过期时间改为过去 → purge_expired 删除 1 条，密文 unlink 成功
- ✅ files / file_keys 表记录彻底删除（无残留）
- ✅ 上传「1 秒后过期」文件 → 后台线程自动清理（日志 `[purge] 已物理删除 1 个过期文件`）
- ✅ 恢复 60 秒间隔后服务正常

## 配置

.env 可选（不写则用默认值）：
```
PURGE_ENABLED=true
PURGE_INTERVAL_SECONDS=60
```

## 修改文件

- config.py：+purge_interval_seconds、+purge_enabled
- app/db.py：+purge_expired()
- app/main.py：+_purge_loop、startup 启动线程、列表过滤过期
- static/index.html：保存时间下拉控件 + computeExpiry

## 注意

- 清理线程每 60 秒跑一次，到期后最多 60 秒内被物理删除。
- 到期时间是「上传时刻 + 保存天数」，非「最后访问时间」。
- 若未来需要「按最后访问时间滑动过期」，需另加 last_access_at 字段。
