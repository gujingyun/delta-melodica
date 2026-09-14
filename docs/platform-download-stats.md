# 官网下载分平台统计

日期：2026-09-14。

Windows 沿用 `/melodica/api/download`，Android 下载按钮改为 `/melodica/api/download/android`。两者计数后分别跳转到既有 Windows v0.15.1 EXE 和 Android v0.6.0 APK。私有后台显示 Windows、Android 和下载总次数。

旧版 `downloads` 全部归入 Windows；创建时间和浏览次数保留。Android 从接入后累计，不补算此前静态 APK 下载。总次数等于两端之和。GET 入口请求会计数，重复请求重复累计；HEAD、直接下载静态文件和校验文件不计数。统计不代表下载完成数或独立用户数。

## 验证

- 在服务器 Python 3.6.8 的独立临时目录运行 `python3 -m unittest -v server.test_melodica_stats`，7 项通过。覆盖旧数据只读兼容、首次写入迁移、两端独立增长、HEAD 不计数、非法路径与请求方法、浏览量回归、新安装零值，以及 60 个混合并发请求计数无丢失。
- `node website/test_stats.cjs` 通过：320／390／768／1440 px 无横向溢出，两端及总数正确，刷新、旧接口兼容、失败后重试正常。本机 HTTP 模拟下载接口返回实际 302，浏览器下载文件名和内容核对通过。
- [桌面后台](stats-dashboard-desktop.png)和[手机后台](stats-dashboard-mobile.png)已人工检查，图片使用模拟统计数据。前端测试初版通过 Playwright 拦截重定向下载得到错误测试文件名，改为本机 HTTP 服务模拟 302 后通过；未因此修改生产下载协议。
- 公网验收通过：两个下载入口 HEAD 均返回正确的 302 目标与 `no-store`；安卓页面 HTTPS 回读 SHA-256 与发布文件一致，APK MIME 正确。实际从线上安卓页面点击下载一次，文件名、67,932 字节和 SHA-256 `c08a157e1e72f276961dfdfaf66c86859a50c8e474804de75dc039989c9fbb39` 均正确。
- 2026-09-14 17:19:49（北京时间）验收读数：Windows 186 → 186，Android 0 → 1，总计 186 → 187；安卓的 1 次为本次验收下载。HEAD 和后台读取没有增加计数。浏览次数 288、原创建时间保留。
- 私有后台、统计接口（含查询参数）及账号曲库接口在未登录时均返回 401。验收脚本首次使用不存在的账号路径得到 404，核对既有接口后改为 `/account-api/library/songs`，401 验证通过。

## 部署与备份

- 已正式上线。使用已有全站发布文件锁，核对线上三个文件的基线 SHA-256 后发布；仅替换统计服务源码、私有后台页面与安卓下载页。先重启统计服务并检查健康及 HEAD，再最后切换安卓按钮，无需修改或重载 Nginx。
- 服务器备份目录：`/var/backups/delta-melodica/platform-stats-_ykypw45`，保存原服务、原页面、发布清单和文件锁内读取的统计快照。实时 `stats.json` 沿用原文件，未被备份覆盖或清零。
- 首页、Windows／Android 版本清单、两个安装包、曲库索引、账号页面和公共样式的发布前后哈希一致。Nginx、统计服务及账号服务均正常。
- 本机阶段代码提交 `e763ab5`；公开分支为 `codex/platform-download-stats`，功能提交 `a916a09` 已推送。仅同步本次功能文件与新增文档段落，未推送当前开发分支的其他本地历史。
- 本机发布脚本、限定文件清单、下载验收包及公网结果保存在已忽略的 `work/platform-download-stats/`。
