# 安卓安装使用教程上线记录

2026-09-14，按用户要求部署手机版安装使用教程。

- 观看入口：[安卓下载页的安装使用教程](https://aiygzn.top/melodica/android.html#tutorial)。从首页「下载 Android 版」进入，首屏可点击「观看安装使用教程」。
- 兼容链接：[MP4 直接播放](https://aiygzn.top/melodica/videos/android-install-20260914.mp4)。
- 完整时长 119.66 秒，保留原始 1608×1080 画面、60 帧和 AAC 原声。H.264 网页副本开启 faststart，大小从 258,055,416 字节降至 67,845,859 字节，原始素材不改动。
- MP4 SHA-256：`9e01e306e333a07b1b4c34698cd23b0fa6a3e30c56c03233aa7223771736c693`。
- HLS 清单包含 30 个约 4 秒分片；清单 SHA-256：`79bdef4026469ef16290fa5dc243e3259584f3fa11c1f6ef62b5a2b1cc694a7b`。首次点击才加载，不自动播放；复用本站 hls.js 与原生 HLS 支持。

MP4 与 HLS 全片音视频解码检查通过。35 个部署文件经公开 HTTPS 完整回读，SHA-256 均与本地一致；MP4、清单、TS 及封面 MIME 正确，尾部 Range 请求返回 206 且内容一致，缺失分片返回 404。

本机及线上 Chrome 的原生 HLS 和 hls.js 播放、103 秒定位、按需分片与失败重试检查通过。MP4 兼容链接实际打开视频后完成解码、103 秒定位及进入／退出全屏。320／390 像素窄屏无横向溢出，[桌面截图](android-tutorial-desktop.png)和[手机宽度截图](android-tutorial-mobile.png)已检查。详细浏览器结果保存在本机忽略目录 `work/android-tutorial-20260914/`，浏览器宽度检查不等同于手机真机验证。

发布先取得服务器发布锁并核对线上基线，备份原安卓页及样式，再上传媒体并原子切换页面。备份位于 `/var/backups/delta-melodica/android-tutorial-2f06mvh9`，沿用现有视频配置，无需重载或重启服务。首页、Windows 与 Android 版本清单、正式 APK、旧视频清单、曲库和账号脚本均保持原哈希；统计与账号健康接口正常。

页面、封面、播放清单和文档通过纯官网分支提交推送；MP4 与 TS 大文件不提交 Git。安卓本地发行模板同步教程及播放器资源，后续暂存包包含完整依赖。
