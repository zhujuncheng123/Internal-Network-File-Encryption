# 压缩文件递归扫描（防投毒增强）交付记录

> 日期：2026-09-20
> 需求：压缩文件（zip）里藏 exe/脚本怎么办。

## 问题

此前白名单魔数检测只看文件自身头部，zip/7z 的头部是合法的「压缩包」标识，
所以「恶意.exe 压进 资料.zip 再上传」会绕过检测。

威胁清单：
- zip 里藏 exe/脚本（最常见）
- 压缩包炸弹（几 KB 解压出几百 GB）
- 嵌套压缩包（zip 套 zip 套 exe）
- 加密 zip（内容看不到，无法检查）

## 用户决策

「保留 zip，上传前解包递归检查（推荐，能拦 zip 里藏 exe）」

## 实现

### 依赖

引入 fflate（32KB，纯 JS，UMD，全局 `fflate` 对象）到 `static/fflate.min.js`。
`index.html` `<head>` 加 `<script src="fflate.min.js"></script>`。
来源：unpkg.com/fflate@0.8.2/umd/index.js（已本地化，不依赖 CDN）。

### 关键约束与取舍

- fflate 只支持 zip/gzip，**不支持 7z**。故将 7z 从白名单移除
  （`config.py` allowed_extensions 与前端 ALLOWED_EXT 两处同步）。
- 加密 zip：fflate 无法解，unzipSync 抛错 → 统一「无法解析（损坏或加密）→ 拦截」。
  如需传加密压缩包，需换用支持 AES 的库（如 node 侧 crypto 库），当前按保守拒绝处理。

### 前端逻辑（static/index.html）

- 重构 `sniffType(file)` → `sniffBytes(buf)`（纯字节魔数判断，普通文件与压缩包条目共用）。
- 新增 `scanZipData(data, prefix, depth)` 递归扫描：
  1. `fflate.unzipSync` 解包；解析失败 → 拦截（覆盖加密/损坏）
  2. 条目数 > MAX_ZIP_ENTRIES(1000) → 拦截
  3. 累计解压体积 > MAX_ZIP_TOTAL(512MB) → 拦截（防压缩炸弹）
  4. 嵌套深度 > MAX_ZIP_DEPTH(5) → 拦截
  5. 每个条目过 sniffBytes：命中危险魔数 → 拦截
  6. 条目本身是 zip 且非 docx/xlsx/pptx → 递归 scanZipData
  7. 条目扩展名不在白名单 → 拦截
  8. 跳过 __MACOSX/ 与 .DS_Store（macOS 元数据）
- `validateFileType`：ext==='zip' 时读整个文件走 scanZipData；其余走 sniffBytes。

### 后端

`config.py` 白名单移除 7z（现 18 种）。
后端仍是扩展名第二道防线（E2EE 看不到内容），递归检查只能在前端做。

## 验证（node + fflate 实测）

- zip 藏 exe → 拦截 ✅
- zip 藏正常文件(txt/pdf) → 通过 ✅
- zip 藏脚本(.sh shebang) → 拦截 ✅
- zip 藏不允许类型(.doc) → 拦截 ✅
- 嵌套 zip 藏 exe → 拦截（递归生效）✅
- zip 内正常 docx → 通过 ✅

## 修改文件

- static/fflate.min.js（新增，32KB）
- static/index.html：head 引脚本 + 类型检测重构（sniffBytes/scanZipData）
- config.py：白名单移除 7z
- app/main.py：无改动（扩展名白名单仍生效）

## 说明与边界

1. 递归检查在浏览器内存完成，解压 512MB 上限可防炸弹，但大文件上传前会占用内存，可按需调低。
2. 服务端仍只能看扩展名（E2EE 固有限制）；恶意用户绕过前端直调 API，服务端拦不住
   「zip 内藏 exe」这种（因为密文无法解包）——这是 E2EE 的固有边界。
3. 7z 已被移除；若后续需要 7z，需引入支持 7z 的 JS 库（如 lzma.js，体积大、纯 JS 慢），当前不建议。
4. 加密 zip 一律拒绝；需要时再评估 AES zip 支持。
