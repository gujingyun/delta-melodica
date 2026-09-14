# 安卓 v0.6.0 官网发布记录

发布日期：2026-09-14。用户确认真机试奏正常并授权正式发布。

- [官网首页](https://aiygzn.top/melodica/)首屏及底部下载区各有一个「下载 Android 版」入口。
- [安卓下载页](https://aiygzn.top/melodica/android.html)包含安装、旧预览包迁移、更新说明和校验值。
- [正式 APK](https://aiygzn.top/melodica/downloads/delta-melodica-android-v0.6.0.apk)：版本 0.6.0／6，Android 8.0+，67,932 字节。
- APK SHA-256：`c08a157e1e72f276961dfdfaf66c86859a50c8e474804de75dc039989c9fbb39`。
- 证书 SHA-256：`fbb496e1dfe34cbaefe4e07fc6ab82480ca1b52807c5d86ac7fa49aa1231154c`，Android APK v2 签名验证通过。
- [安卓独立版本清单](https://aiygzn.top/melodica/android-version.json)与[权限和数据说明](https://aiygzn.top/melodica/android-data.html)均已公开。

公开 HTTPS 回读全部 9 个发布文件，与本地清单逐一核对 SHA-256 一致。APK 返回 `application/vnd.android.package-archive`；实际从首页进入安卓下载页，触发浏览器下载后再次核对文件名和 SHA-256 通过。

首页在 320／390／768／1440 像素宽度通过布局、两个安卓入口、既有 Windows 下载、键盘访问和视频回归。公开网站再检查手机与桌面截图和实际下载。

Windows 仍为 v0.14，下载入口正确跳转到原 EXE；Windows 版本清单和公开曲库的字节内容未改变。统计与账号健康接口正常，私有后台及账号曲库仍要求登录。Nginx 配置检查通过，仅平滑重载，没有重启账号或统计服务。

旧调试预览包与正式包签名不同，请先同步曲库或保存原始曲谱，再卸载预览包并安装正式包；原本未备份的数据不能直接通过覆盖安装迁移。后续正式更新继续使用同一签名。
