# 三角洲口风琴介绍页

## Windows 与 Android 下载统计

Windows 下载沿用 `api/download`，安卓下载页及发布模板改用 `api/download/android`，由统计服务计数后 302 跳转至对应安装包。部署时先更新 `server/melodica_stats.py` 并重启统计服务，确认两端 HEAD 跳转正确后再发布 `android.html` 与 `admin/index.html`；现有 Nginx `/melodica/api/` 代理已覆盖新入口，无需改配置。

后台显示浏览次数、下载总次数、Windows 和 Android 下载次数。接口新增 `downloads_windows`、`downloads_android`，保留 `downloads` 作为两端总计。原来只有 `downloads` 的数据自动归入 Windows，首次写入在原有文件锁内保存新字段，历史次数和创建时间保留。Android 从 2026-09-14 接入后累计，此前未统计的下载不回填。计数口径为 GET 下载入口请求次数，重复请求重复累计；HEAD、静态安装包和校验文件不计数，不表示下载完成或独立用户数。

升级版本时同步维护服务中的 Windows／Android 安装包目标，安卓独立版本清单仍指向静态 APK。统计回归在 Linux 运行 `python3 -m unittest -v server.test_melodica_stats`，使用临时目录和回环端口；后台浏览器回归运行 `npm --prefix website run test:stats`，支持 `PLAYWRIGHT_MODULE`，使用本机模拟数据验证两端显示、刷新、错误重试、四档宽度和重定向下载。截图为测试样例数据。已于 2026-09-14 上线，并通过真实公网 APK 下载和计数校验；详见[分平台统计记录](../docs/platform-download-stats.md)。

## Windows v0.15.1 发布

修复退出草稿保护、BOM 与旧版曲谱导入、损坏曲目删除及游客记录恢复提示。发布文件为 `updates-v0.15.1.html`、`assets/main-window-v0.15.1.png` 和 `downloads/delta-melodica-v0.15.1.exe`，同时切换首页、下载跳转和 `version.json`。沿用下方的备份、校验与发布顺序。

2026-09-14 已上线，公网回读及下载成品冒烟通过；详见 [Windows v0.15.1 发布记录](../docs/windows-v0.15.1-release.md)。

## Windows v0.15 发布

客户端支持原谱精确拍数、谱面预览与特殊时值编辑。对应 `updates-v0.15.html`、`assets/main-window-v0.15.png` 和 `downloads/delta-melodica-v0.15.exe`。先上传校验成品与资源，再切换下载跳转、首页和 `version.json`；保留安卓页面、账号资源和线上曲库。

## 安卓 v0.6.0 官网发布

安卓页 `android.html#tutorial` 提供手机版安装使用教程，首屏「观看安装使用教程」跳转至播放器。复用本站 `video-player.js` 和 hls.js，点击后加载视频，支持拖动、全屏及 MP4 兼容播放。素材为用户提供的 2026-09-14 手机实录，约 2 分钟；网页副本保留 1608×1080、60 帧及原声，开启 MP4 faststart，并拆成 30 个约 4 秒的 HLS 分片。

教程已于 2026-09-14 部署并通过公开 HTTPS 校验，详见[教程上线记录](../docs/android-install-tutorial-release.md)。

教程资源：`assets/android-install-20260914.jpg`、`videos/android-install-20260914.mp4`、`videos/android-install-20260914/index.m3u8` 和同目录 `segment-*.ts`。MP4 与 TS 不提交 Git，发布时必须一并上传。沿用已有 `/melodica/videos/` 配置，先校验媒体再切换安卓页，不需重载 Nginx。

2026-09-14 已正式上线：[官网首页](https://aiygzn.top/melodica/)、[安卓下载页](https://aiygzn.top/melodica/android.html)。用户确认真机试奏通过后发布，公开下载及签名校验通过；发布结果见 [上线记录](../docs/android-v0.6.0-release.md)。

首页首屏和底部下载区均提供「下载 Android 版」，进入 `android.html` 后下载正式签名 APK。安卓使用 `android-version.json` 独立版本清单，`android-data.html` 展示与 App 一致的权限和数据说明。

发行包为 `downloads/delta-melodica-android-v0.6.0.apk`，67,932 字节，SHA-256：`c08a157e1e72f276961dfdfaf66c86859a50c8e474804de75dc039989c9fbb39`。文件不提交 Git；只发布公开静态页面、截图、版本清单与 Nginx 下载配置。旧调试预览包应先保留曲谱再切换正式签名版本，网页含完整迁移说明。

部署时先备份首页和配置，再上传 APK／校验文件、安卓页面和资源，把 `nginx-android-download.conf` 放进已有 HTTPS server 的 include 目录并通过 `nginx -t`，平滑 reload 后最后切换首页。Windows 版本清单、下载统计跳转、曲库与账号数据保持原值。发布后通过 HTTPS 完整下载核对文件与 MIME，并复查两个首页入口。

本地首页回归：`test_homepage.cjs` 验证 320／390／768／1440 px、两个安卓入口、既有 Windows 下载、视频和导航；先设置 `PLAYWRIGHT_MODULE` 指向本机 Playwright，再设置 `HOMEPAGE_TEST_URL` 为本机预览地址。

## v0.14 正式发布

本次同步发布客户端、主页改版及 `updates-v0.14.html` 更新说明；主页使用 `assets/main-window-v0.14.png` 正式版本截图，去除待发布标记。以下保留本地预览与历史联调方式，正式验证结果见仓库「验证记录.md」。

正式成品为 `dist/三角洲口风琴_v0.14.exe`，下载文件为 `downloads/delta-melodica-v0.14.exe`。先上传并校验新 EXE 与静态资源，备份线上文件，再切换统计服务下载目标、首页与版本清单。保留旧版安装包；不得用仓库旧 songs.json 覆盖线上曲库或覆盖账号数据库。

主页使用与 Windows 客户端一致的炭黑、浅绿配色及音量柱标识，重新整理导航、下载入口、客户端展示、视频、功能卡片和使用指南。账号页同步基础配色。`assets/main-window-refresh.png` 为隔离数据环境中的真实客户端截图，页面标注为待发布设计；现有 `api/download`、视频资源、统计接口和 `version.json` 保持原有约定。

本地只看静态页面，在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m http.server 8768 --bind 127.0.0.1 --directory website
```

打开 `http://127.0.0.1:8768/`。该静态预览用于确认界面，不提供下载统计和账号 API。停止该终端即可关闭预览。不要把本地测试服务当成部署入口。

完整本机联调（临时数据库、假邮件，需 `server/requirements-test.txt` 中的依赖以及本机 Chrome）：

```powershell
.\.venv\Scripts\python.exe server/test_web_server.py
# 在另一终端执行以下命令。
npm --prefix website install
npm --prefix website run test:homepage
npm --prefix website run test:accounts
```

`test:homepage` 检查 320 / 390 / 768 / 1440 px 布局、图片加载、下载入口、锚点、键盘访问、视频延迟加载和错误重试，截图写入忽略的 `work/ui-refresh/`。`test:accounts` 验证本机假邮件及临时账号流程，未发送真实邮件。支持用 `PLAYWRIGHT_MODULE` 指定已有 Playwright 路径；主页测试地址仅允许本机回环地址。

本轮预览截图：[桌面主页](../docs/homepage-refresh-desktop.png)、[手机主页](../docs/homepage-refresh-mobile.png)。发布前仍需用户确认设计、安排正式资源及服务验证，本轮未操作线上服务器。

## 账号与私有曲库（开发预览）

`account/` 提供邮箱登录、注册验证码、密码重置、游客曲谱备份导入、注册继承、账号曲库同步及下载。通过独立 `/melodica/account-api/` 接口访问后端，静态站点不直接读取 SQLite。[线上账号页](https://aiygzn.top/melodica/account/)及阿里云 SMTP 已部署，配置见[后端说明](../server/README.md)。

网页身份使用 HttpOnly Cookie，本机曲谱使用 IndexedDB 并按账号隔离。游客曲谱仅保存在当前浏览器；清除网站数据会移除本机曲谱，请下载备份。注册只继承当前浏览器的曲谱，其他设备需在对应客户端合并。曲谱 JSON 导入有 2 MB 和 30000 音符限制，MIDI／文本简谱请通过客户端导入。

静态账号页需随 `account.js`、`account.css` 一同部署，Nginx 示例包含严格来源策略及专用 API 反代，不改变原统计服务。账号 API 不可用时明确提示服务暂不可用。线上主页已增加「账号 / 我的曲库」入口；公开下载仍为 v0.13，客户端账号功能使用预览版。

这是挂载在 `https://aiygzn.top/melodica/` 的静态介绍页。

- `index.html`：页面内容与下载入口。
- `styles.css`：深色产品视觉与响应式布局。
- `assets/main-window.png`：软件主界面预览图。
- `assets/display-mode-borderless.png`：游戏视频设置中的无边框窗口示意图。
- `assets/feature-intro-20260912.jpg`：功能介绍视频实录封面。
- `videos/feature-intro-20260912.mp4`：完整功能介绍视频的网页优化副本，1080p／60 帧，保留原声并开启 faststart；大文件不提交 Git。原始素材保留在 `D:\剪辑\9月12日(1)\9月12日(1).mp4`。
- `videos/feature-intro-20260912/index.m3u8`：HLS 点播清单，36 个约 4 秒的独立片段，分片文件 `segment-*.ts` 不提交 Git，发布时必须与清单一起上传。
- `video-player.js`、`vendor/`：按需加载的 HLS 播放器，固定使用本站托管的 hls.js 1.7.2，原生支持 HLS 的浏览器直接读取清单；依赖来源和许可见 `vendor/README.md`。
- `delta-melodica-nginx.conf`：现有 Nginx 站点的独立路径配置。
- `version.json`：客户端检查更新时读取的公开版本清单。
- `songs.json`：客户端读取的线上 MIDI 曲库目录，当前包含 5 首曲目；新增条目时，`url`、`size` 和 `sha256` 必须与 `songs/` 中的文件一致。
- `songs/`：线上曲库提供下载的 MIDI 文件目录。
- `downloads/`：本地部署暂存目录，已被 Git 忽略；发布时从 `dist/三角洲口风琴_v0.13.exe` 复制为 `delta-melodica-v0.13.exe`。
- `../server/melodica_stats.py`：记录官网浏览次数和下载入口点击次数。
- `admin/index.html`：私有统计页，由服务器 Basic Auth 保护，不在公开页面显示入口。

发布路径为 `/melodica/`，统计页为 `/melodica/admin/`，不会覆盖服务器现有首页。更新版本时同步替换服务器上的下载文件，更新页面中的版本号与说明，并修改 `version.json` 的 `version` 和 `notes`。新增线上曲目时同步上传 `songs.json` 和 `songs/` 中对应的 MIDI。

统计密码只保存在服务器的 Nginx 密码文件中，不提交到仓库；统计数据保存在服务器本地 `/var/lib/delta-melodica-stats/stats.json`，不记录访客身份或曲谱内容。

首页 `#demo` 提供 HLS 分片流媒体播放器、封面和 MP4 兼容链接，默认不预载视频、不自动播放，支持手机内联与全屏播放。视频录制于 v0.12，页面说明与当前软件下载版本分开维护。部署时先上传所有分片、清单、播放器、MP4 与封面，再更新样式和首页；检查 HLS MIME、缺失文件 404、实际分片请求和拖动定位，以及 MP4 的 HTTP Range 206。独立 `/melodica/videos/` 配置采用现有 MIME 映射，避免缺失分片回退成首页；首次添加配置后先通过 `nginx -t` 再平滑 reload，不停止其他服务，不改动下载统计入口。
