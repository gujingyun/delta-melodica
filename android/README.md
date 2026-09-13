# 三角洲口风琴 · 安卓预览版

## 0.6 功能同步开发记录

曲谱处理层已同步桌面版的文字简谱规则、原谱保存与校验、钢琴连奏、精确音符编辑、选段时间轴和多片段编排。每首曲目的速度、移调、音轨、演奏方式和片段按游客／账号分别保存；退出账号后仍可查看原游客曲库，归属记录继续防止重复继承。

第一阶段运行 `testDebugUnitTest` 通过；其中 94 组自编谱与桌面解析器逐项对照音高、时值、连奏和原文位置，包含非法结构拒绝。基准由 `tools/generate_parity_fixtures.py` 生成。本阶段为处理层提交，手机界面将在后续阶段接入。

## 邮箱账号与云端曲库（开发预览）

主界面新增「账号 / 云端同步」。邮箱验证注册后自动继承本机游客曲谱并上传私有云端；已有账号登录后可按提示选择合并游客曲库。游客继续使用本地导入、公开曲库、校准和演奏，私有云同步需要登录。忘记密码可通过邮箱验证码重置，重置后旧会话全部失效。

账号与官网、Windows 共用后端；同步完整音符与音轨编号，可下载其他端的曲谱，导入入口也支持官网导出的曲谱 JSON。同步为主动合并，不同步删除、速度、移调、校准或片段设置。原游客文件保留备份，已归属条目隐藏于游客曲库；账号之间独立保存。会话使用 Android Keystore AES-GCM 加密，密码不落盘。

真实发信和线上账号 API 尚待部署。开发阶段安卓代码及 APK 遵守仓库的本地保留规则，不推送公开远程。

本阶段 `testDebugUnitTest assembleDebug assembleDebugAndroidTest lintDebug` 通过，26 项单元测试包含跨端曲谱固定 SHA-256 样例、时值／音轨／重复音、格式拒绝及本地云谱去重。Lint 无错误，保留已有 SDK／依赖版本等警告及界面文字国际化提示。

新增 `AccountChecks` 设备回归入口，覆盖真实 Keystore 加密、游客继承断网重试、账号隔离、下载和注册页面截图；使用隔离目录及假服务，不发送邮件、不更改无障碍授权。本机模拟器多次在图形初始化阶段失败，尚未执行此设备回归，不能将构建通过视为手机实测通过。

```powershell
.\gradlew.bat assembleDebug assembleDebugAndroidTest '-PtestRunner=top.aiygzn.melodica.AccountChecks'
adb -s 测试设备序列号 install -r .\app\build\outputs\apk\debug\app-debug.apk
adb -s 测试设备序列号 install -r .\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk
adb -s 测试设备序列号 shell am instrument -w top.aiygzn.melodica.test/top.aiygzn.melodica.AccountChecks
```

安卓端独立工程，面向 Android 8.0 及以上。通过用户开启的无障碍服务发送触摸手势，无需 Root。当前为功能原型，不能将模拟器结果当作三角洲手游兼容性结论。

## 使用

1. 安装 APK，打开「三角洲口风琴」，首次点击「开启无障碍服务」，阅读说明并前往系统设置，开启「三角洲口风琴 · 演奏服务」。返回应用后会自动刷新授权和连接状态。尚未开启时，点击「显示悬浮控制条」也会直接给出申请入口。
2. 选择内置《小星星》，或点击「线上曲库」搜索、分页浏览官网 MIDI，点选「下载并选用」后自动加入并选中本地曲目。也可导入 `.mid`／`.midi`、UTF-8 文本简谱，或直接输入简谱保存。MIDI 可选择自动旋律、指定音轨或全部音轨高声部。
3. 设置速度和移调，点击「显示悬浮控制条」。进入三角洲手游的口风琴演奏画面。
4. 点悬浮窗「校准」，依次点 **1、2、3、4、5、6、7、高音 1、半音、升调、自然音、降调** 的中心，共 12 处。校准层只记录位置，不会将这些点击传给游戏。校准同时绑定当前应用、屏幕尺寸和旋转方向。
5. 将悬浮窗拖到不遮挡这 12 个按钮的位置。点「播放」，按游戏当前状态选择半音「未选中」或「已选中」，倒计时中会预选首音的变音状态，3 秒后才按下音键。「暂停」保留位置；「继续」也需确认半音当前状态，再从该处续播；「停止」回到曲首。
6. **倒计时和演奏期间「收起」置灰禁用**；暂停或停止并完成触摸释放后恢复可用，曲目结束也会恢复。日常结束使用主界面「停止并隐藏悬浮窗」，停止归零并保留无障碍授权，下次直接点「显示悬浮控制条」。如需关闭授权，使用「管理无障碍授权」进入系统页面关闭服务。

从 v0.1 升级后保留曲库，但需要重新完成 12 点校准；已有 v0.2 及后续版本的曲库和 12 点校准可继续使用。可以先在「本地测试键盘」检查触摸和选中状态；进入真实游戏后需重新校准。更换分辨率、屏幕方向或游戏键位后也应重新校准。

## 无障碍授权

- v0.4 及更早版本的「停止并关闭演奏服务」会调用 `disableSelf()`，使系统开关也关闭。v0.5 的日常退出改为停止并隐藏，保持系统授权和待机服务，不自动演奏。已有授权时显示「管理无障碍授权」，不重复弹出申请说明。
- 授权开关和服务连接分别检查：已授权但系统尚未绑定时显示等待连接，不误报为未授权；返回应用时立即刷新，并继续检查连接状态。
- 首次开启无障碍必须由用户在系统页面确认，不能用普通运行时权限弹窗自动开启。已授权的正常停止无需重设；主动撤销、系统关闭或触摸接口严重故障导致服务关闭后，仍需重新开启。[Android 服务生命周期与 disableSelf 说明](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#disableSelf())。
- 继续使用已有的无障碍悬浮层，本次未增加权限。系统设置入口不可用时会提示手动路径，不因跳转异常退出应用。

## 线上曲库

- 沿用官网目录 `https://aiygzn.top/melodica/songs.json`，支持按曲名或作者搜索，每页 10 首，最多 500 首。目录读取与下载在后台进行，可随时返回主界面。
- 下载前后检查文件大小、目录提供的 SHA-256 和 MIDI 格式，全部通过后才保存本地曲谱。目录最大 1 MB，MIDI 最大 10 MB，仅接受 HTTPS，限制重定向次数和请求时长。
- 同一线上曲目使用固定本地标识，重新选用已下载曲目不会产生副本；下载后可以离线演奏、选音轨、调速和移调。线上目录不缓存，网络不可用时请直接从主界面选择已下载的本地曲目。
- 下载失败可重新点选重试，读取目录失败可点「刷新目录」。文件写入失败或取消不会把临时文件当作曲库条目；关闭页面后旧请求不会改变当前选曲。

## 音高和时序范围

- 默认中央 1 = MIDI 60（C4），需按游戏实际音高校正。
- 升调、自然音、降调是点击后保持选中的三选一音区；半音是独立开关，可以与任意音区组合。自然音只切回中央音区，不会取消半音。
- 沿用音高映射：升调高一个八度、降调低一个八度、半音升半音，超出总音域的音按八度折回。程序先松开音键，再依次点击需要改变的音区／半音按钮，最后按住音键；状态相同时不重复点击。
- 半音没有独立的「关闭」按钮，因此每次开始、续播都需要用户确认它的实际选中状态；程序随后明确点击所需音区。暂停、停止、切出或手势中断会作废内部状态记录，不会盲目尝试复位半音。手动调整游戏变音前请先暂停。
- v0.4 在倒计时、休止符及上一音符松键后提前切换变音，利用已有空隙；只有切换超过下一音符的开始时刻才暂缓乐谱计时，避免吞掉短音。先松开音键才切换，也不会提前按下下一音符。
- 变音按钮每次点击仍为 45 毫秒，点击间隔和结束等待缩短至 8 毫秒；需要同时改变音区和半音时，将两次先后点击放在同一手势批次，减少系统回调往返。实际耗时仍受系统调度影响。频繁变音且没有足够空隙的曲目仍可能长于曲谱显示时长，不能保证零停顿。
- 开始／继续前缓存音符指法，悬浮窗仅在文字和按钮状态改变时更新，减少演奏期间的重复计算与布局。
- 简谱支持 `1 2 3:2 0 +1 -5 #4`；冒号后为拍数，支持 `:1/2`，文本文件默认 100 BPM。
- MIDI 支持 PPQ 时间格式的 0／1 型、跨轨速度表、打击乐过滤与高声部整理；不支持 SMPTE、类型 2、踏板还原和完整多声部。尚未完整移植桌面版的钢琴连奏和片段编排。
- 调速和移调在主界面设置，应用后回到曲首。悬浮窗提供播放、暂停、继续、停止、校准和收起。
- 曲谱最长 30 分钟、最多 30000 音符，MIDI 文件最大 10 MB。导入保存本地副本，不修改原文件。

## 输入保护与本机数据

手势只在校准的目标应用处于前台、屏幕解锁且尺寸和方向一致时开始。切出、锁屏、旋转或系统取消手势会暂停。音符按不超过 60 毫秒的片段连续长按，暂停或停止后在当前短段回调时释放；系统调度可能增加延迟，不能承诺固定上限。接口拒绝或回调超时会关闭服务，由系统清理该服务的触摸序列。

为避免系统将静止的续接手势合并为空事件，长按在音键中心附近往返 1 个屏幕像素；校准时应点按钮中心，避免边缘。点击悬浮暂停按钮时，系统可能先取消当前手势，助手会保留暂停状态。

窗口包名仅用于前台确认。不读取窗口文字、不截图，不进行游戏进程读取或修改。游客本地演奏不上传曲谱；注册继承和主动云同步会上传可演奏曲谱副本，不上传设置或窗口信息。曲库和校准保存在应用私有目录；卸载会移除本机数据，云端曲库保留。测试键盘校准不会用于游戏窗口，返回主界面也不会触发测试音键。

## 构建与验证

使用 Android Studio 自带的 JDK 21，安装 Android SDK Platform 34 与 Build Tools 36.0.0。设置 `JAVA_HOME` 和 `ANDROID_HOME`，或在本目录不入库的 `local.properties` 中指定 `sdk.dir`。

```powershell
.\build.ps1 -JavaHome '你的 JDK 21 目录' -SdkRoot '你的 Android SDK 目录'
```

项目固定 Gradle 9.2.1 和 Android Gradle Plugin 9.0.1。Java 源码采用 UTF-8；Gradle 进程采用 `file.encoding=COMPAT`，使 Windows 中文路径的测试进程参数文件与系统编码一致。APK 位于 `app\build\outputs\apk\debug\app-debug.apk`，为本地测试签名的预览包。

构建脚本先执行 `clean testDebugUnitTest assembleDebug lintDebug`，成功后复制到仓库根目录 `dist\三角洲口风琴_安卓_v0.5预览版.apk`，并输出 SHA-256。使用完整清理构建，避免增量打包残留旧 dex。

26 项单元测试覆盖简谱、MIDI、旋律整理、音高映射、暂停续播、倒计时取消、变音状态、顺序点击批次、提前切换的时钟截止点，以及线上目录校验、搜索、HTTPS 地址、下载大小与哈希、取消、本地去重保存和云端交换格式。JSON 测试依赖只在本机测试运行，不打入 APK。

设备触摸回归需要专用 Android 10+ 测试设备或模拟器，先安装应用并开启本应用的无障碍服务：

```powershell
.\gradlew.bat assembleDebugAndroidTest
adb -s 你的测试设备序列号 install -r .\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk
adb -s 你的测试设备序列号 shell am instrument -w -r top.aiygzn.melodica.test/top.aiygzn.melodica.GestureSmokeTest
# 记录实际 DOWN／UP 时间，检查休止时不累积切换延迟、音符不提前及二倍速密集变音
adb -s 你的测试设备序列号 shell am instrument -w -r -e suite timing top.aiygzn.melodica.test/top.aiygzn.melodica.GestureSmokeTest
# 专用测试设备上的授权保留、重开应用、连接状态和按需申请验证
adb -s 你的测试设备序列号 shell am instrument -w -r -e suite permissions top.aiygzn.melodica.test/top.aiygzn.melodica.GestureSmokeTest
# 线上曲库验证，不要求开启无障碍演奏服务；会读取官网并验证当前目录中的 MIDI
adb -s 你的测试设备序列号 shell am instrument -w -r -e suite online top.aiygzn.melodica.test/top.aiygzn.melodica.GestureSmokeTest
```

此入口会打开应用自建测试键盘，临时校准并执行触摸，结束后恢复曲库选择和校准设置。它不会进入三角洲手游；只重连原本已开启的本应用无障碍服务。成功时输出各项「通过」和 `INSTRUMENTATION_CODE: -1`；仅 adb 返回码为 0 不能判断测试成功。普通 `uiautomator dump` 会暂时抑制其他无障碍服务，不应在演奏过程中用它验证状态。

15 项触摸设备回归包含真实 12 点校准、变音与播放生命周期、倒计时预选变音但不发音，以及倒计时／演奏时收起禁用、结束／暂停／停止后恢复、实际点击禁用按钮不收起。时序入口另有 2 项检查和 3 段计时记录。线上曲库另有 5 项设备验证，覆盖官网目录和 MIDI 下载、搜索分页、取消／下载／返回主界面、重复选用、加载期间关闭页面。测试入口会清理本次创建的测试下载，保存自建界面截图；正常演奏不截图。

授权入口有 5 项检查：停止隐藏保持系统开关、恢复悬浮窗及退出重开不重复申请、已授权但未连接的状态展示、管理授权的系统 Intent、撤销后按需申请。仅设备测试包临时操作专用设备设置并在结束时恢复；正式 APK 不包含测试入口，也不具备自动修改系统无障碍开关的能力。该入口的 Intent 拦截验证不代替各手机系统的设置页面实测。

![v0.5 已连接并保留授权](docs/permissions-connected-v05.png)

![v0.5 未授权时的申请入口](docs/permissions-needed-v05.png)

![安卓主界面与线上曲库入口](docs/main-v03.png)

![v0.2 设置与升级提示](docs/settings-v02.png)

![四个变音按钮纳入校准](docs/calibration-v02.png)

![播放前确认半音实际状态](docs/half-confirmation-v02.png)

![官网线上曲库](docs/online-catalog-v03.png)

![v0.4 播放期间禁用收起](docs/collapse-disabled-v04.png)

## 平台接口依据

- [Android 无障碍手势接口](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#dispatchGesture(android.accessibilityservice.GestureDescription,android.accessibilityservice.AccessibilityService.GestureResultCallback,android.os.Handler))
- [连续长按手势](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription#continueStroke(android.graphics.Path,long,long,boolean))
- [无障碍悬浮窗](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_ACCESSIBILITY_OVERLAY)

真机待验证：手游对按钮点击时长及切换间隔的响应、中央音高和八度映射、长音听感、密集音符稳定性，以及不同手机系统的后台行为。选中与互斥规则按用户提供的手游画面和说明实现。
