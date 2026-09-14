# 官网下载分平台统计

日期：2026-09-14。

Windows 沿用 `/melodica/api/download`，Android 下载按钮改为 `/melodica/api/download/android`。两者计数后分别跳转到既有 Windows v0.15.1 EXE 和 Android v0.6.0 APK。私有后台显示 Windows、Android 和下载总次数。

旧版 `downloads` 全部归入 Windows；创建时间和浏览次数保留。Android 从接入后累计，不补算此前静态 APK 下载。总次数等于两端之和。GET 入口请求会计数，重复请求重复累计；HEAD、直接下载静态文件和校验文件不计数。统计不代表下载完成数或独立用户数。

## 验证

- 在服务器 Python 3.6.8 的独立临时目录运行 `python3 -m unittest -v server.test_melodica_stats`，7 项通过。覆盖旧数据只读兼容、首次写入迁移、两端独立增长、HEAD 不计数、非法路径与请求方法、浏览量回归、新安装零值，以及 60 个混合并发请求计数无丢失。
- `node website/test_stats.cjs` 通过：320／390／768／1440 px 无横向溢出，两端及总数正确，刷新、旧接口兼容、失败后重试正常。本机 HTTP 模拟下载接口返回实际 302，浏览器下载文件名和内容核对通过。
- [桌面后台](stats-dashboard-desktop.png)和[手机后台](stats-dashboard-mobile.png)已人工检查，图片使用模拟统计数据。前端测试初版通过 Playwright 拦截重定向下载得到错误测试文件名，改为本机 HTTP 服务模拟 302 后通过；未因此修改生产下载协议。
- 线上部署和公开 HTTPS 校验将在发布完成后记录。
