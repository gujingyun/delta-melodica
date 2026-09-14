# 安卓 v0.6.3 官网发布记录

2026-09-14 已发布至[安卓下载页](https://aiygzn.top/melodica/android.html)，官网下载从 v0.6.0 升级至 v0.6.3。

## 用户可见变化

- 悬浮控制条根据屏幕和字体大小自适应，播放时保留进度、暂停、停止与拖动，暂停后展开。
- 点击播放或继续，仅在控制条内显示「半音设为未选中」，3 秒后自动换回进度并演奏。移除半音状态选择、「开始演奏」「取消」按钮；准备期间不发送音键或变音手势。
- 正式签名包可覆盖升级并保留本地曲库、设置与校准。旧调试预览包仍需先备份再卸载迁移。

## 成品

| 项目 | 内容 |
| --- | --- |
| 下载文件 | `downloads/delta-melodica-android-v0.6.3.apk` |
| 包名 | `top.aiygzn.melodica` |
| 版本 | 0.6.3 / versionCode 9 |
| Android | minSdk 26 / targetSdk 34 |
| 大小 | 69,292 字节 |
| 源码 | `7ea4cd22e55ebd7bea4da9359a18b5243894fae6`，干净源码 Release 构建 |
| 官网准备提交 | `08f4ad1` |

APK SHA-256：

```text
59552ed90bbd01efc114598d06b116f093a1a8e873c96045cdd3d9f480093dd9
```

签名证书 SHA-256：

```text
fbb496e1dfe34cbaefe4e07fc6ab82480ca1b52807c5d86ac7fa49aa1231154c
```

本次发布使用已验证成品，未重新构建 APK。再次运行 `apksigner verify --print-certs` 与 `aapt dump badging` 核验签名和版本，公网浏览器下载文件与本地成品 SHA-256 相同。

## 部署与回退

发布前核对线上基线，持有 `/var/lock/delta-melodica-release.lock`。备份目录为 `/var/backups/delta-melodica/android-v063-bi16fqsl`，保存原安卓下载页、版本清单、Nginx 安卓配置、统计服务代码和部署前统计快照。

先上传 APK 和校验文件，新增 `/etc/nginx/default.d/delta-melodica-android.conf` 中 v0.6.3 APK 的精确下载规则，`nginx -t` 通过后平滑 reload。随后将统计服务安卓目标改为 v0.6.3 并重启，确认 HEAD 跳转后原子替换安卓下载页和版本清单。旧 v0.6.0 APK 保留。

共替换／新增六个生产文件。首页、Windows 版本清单与安装包、曲库索引、账号和后台页面、权限页、样式及教程播放器资源哈希保持一致；Nginx、统计与账号服务均为 active。发布期间有正常计数增长，实时统计文件没有被替换。

若需回退，在同一发布锁内从备份恢复安卓页面、清单、Nginx 配置和统计服务代码，通过 `nginx -t` 后 reload 并重启统计服务，再检查两端下载目标。不要将部署前统计快照覆盖实时数据；保留新旧版本安装包，以便已经取得链接的下载继续完成。

## 验收

- 发布前客户端：28 项单元测试、15 项完整触摸回归和小屏大字体布局检查通过，使用 Android 14 模拟器自建键盘；未进行手游真机测试。
- 发布前网站：`android/test_release_site.cjs` 验证两页、四档宽度（320／390／768／1440 px）、图片、站内链接、锚点、APK 大小及哈希，无页面脚本错误。
- 统计服务：Linux 隔离临时目录运行 `python3 -m unittest -v server.test_melodica_stats`，7 项通过，包含并发计数及 HEAD 不计数。
- 公网：下载页及版本清单逐字节回读一致；四档宽度无横向溢出，图片加载成功。APK 返回正确 MIME，SHA 文件正常。
- 浏览器实际点击一次下载，取得 `delta-melodica-android-v0.6.3.apk`，大小和 SHA-256 一致。验收期间 Android 计数 46 → 47，Windows 保持 224，总数 270 → 271；这是一次验收下载，并非新增用户数。
- Windows／Android 的 HEAD 下载探测均返回预期的 302 与 `no-store`。后台、统计及未登录私有曲库入口仍返回 401，健康检查返回 200。

原始发布日志、测试输出和公网验收结果保存于本机忽略目录 `work/android-release-v063-publish/`。

[手机官网下载页截图](android-v0.6.3-mobile.png) · [桌面官网下载页截图](android-v0.6.3-desktop.png) · [半音提示截图](../android/docs/half-toast-v063.png) · [提示消失后的演奏截图](../android/docs/half-text-playing-v063.png)
