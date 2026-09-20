# 文件类型白名单（防投毒）交付记录

> 日期：2026-09-20
> 需求：防止有人上传带毒文件（"投毒"），限制文件类型。

## 用户决策

- 限制方式：**白名单**（只允许指定安全类型，最安全）
- 是否防改名投毒：**要，上传前检测真实类型**（推荐）

## 核心约束（E2EE 架构）

端到端加密下，服务端拿到的是 AES 密文，看不到文件内容，只能按扩展名判断。
扩展名可伪造（病毒.exe 改名 报表.pdf），所以防投毒必须在浏览器加密前读文件头魔数。

## 实现：前后端两层防线

### 前端（加密前，真实类型检测）

`static/index.html` 新增：
- `ALLOWED_EXT`：与服务端一致的白名单（19 种）。
- `sniffType(file)`：读前 64 字节，双列表判断：
  - **危险魔数黑名单**（无论扩展名，一律拒绝）：
    - MZ → Windows EXE/DLL
    - \x7fELF → Linux ELF
    - FE ED FA CE / CE FA ED FE / CF FA ED FE → Mach-O
    - CA FE BA BE → Java class
    - #! → shebang 脚本
    - D0 CF 11 E0 A1 B1 1A E1 → OLE2 旧版 Office（宏风险）
    - {\rtf → RTF
    - @echo/rem/reg/powershell/cmd/wscript/cscript/mshta → 批处理/脚本
  - **白名单魔数**：png/jpg/gif/bmp/webp/pdf/mp3/wav/mp4/7z/zip（zip 容器再通过 [Content_Types].xml 区分 docx/xlsx/pptx）
- `validateFileType(file)`：
  1. 扩展名不在白名单 → 拒绝
  2. 命中危险魔数 → 拒绝
  3. 命中白名单魔数但类型与扩展名不符 → 拒绝
  4. 无法识别 → 仅纯文本 txt/csv/md 放行，其余保守拒绝

### 后端（第二道防线，扩展名白名单）

`config.py` 新增 `allowed_extensions` 配置（19 种，逗号分隔）+ `allowed_ext_set` 属性。
`app/main.py` 新增 `_validate_ext()`，在 upload 接口入口校验扩展名，非法返回 415。

## 默认白名单（19 种）

jpg jpeg png gif webp bmp pdf docx xlsx pptx txt csv md zip 7z mp3 wav mp4 mov

默认排除的高风险类型：exe/dll/msi/bat/cmd/ps1/sh/elf/mach-o/jar/class/scr/vbs/js/html/svg/
doc/xls/ppt（旧二进制，宏风险）/docm/xlsm/pptm（宏）/rtf 等。

## 验证结果

后端冒烟测试：
- 上传 .exe → 415 "不允许的文件类型：.exe" ✅
- 上传 .pdf → 200 ✅

前端逻辑（node 模拟 10 场景全通过）：
- exe 改名 .pdf → 拒绝（危险 EXE）✅
- elf 改名 .txt → 拒绝 ✅
- OLE2 改名 .pdf → 拒绝 ✅
- shebang 改名 .pdf → 拒绝 ✅
- exe 改名 .mp4/.zip → 拒绝 ✅
- 真 pdf/txt/csv/png → 通过 ✅

## 修改文件

- config.py：+allowed_extensions 配置
- app/main.py：+_validate_ext()，upload 入口调用
- static/index.html：+类型检测全套逻辑，btnUpload 入口调用 validateFileType

## 说明与后续可选项

1. 白名单可按需调整：改 config.py 的 allowed_extensions 和前端 ALLOWED_EXT 两处（保持同步）。
2. 服务端只做扩展名校验（E2EE 看不了内容），真实类型检测在前端；恶意用户可绕过前端直调 API，
   但此时服务端扩展名白名单仍会拦截非白名单扩展名（拦不住"改名后内容也是白名单扩展"的场景，
   因为密文无法嗅探——这是 E2EE 的固有边界，要更强需在解密侧加沙箱）。
3. 更彻底方案：文件解密后不落地、用沙箱/杀毒引擎扫描，但会破坏端到端加密模型，需权衡。
