# 三角洲口风琴 · 安卓预览版

安卓端独立工程，面向 Android 8.0 及以上。通过用户开启的无障碍服务发送触摸手势，无需 Root。当前为功能原型，不能将模拟器结果当作三角洲手游兼容性结论。

## 使用

1. 安装 APK，打开「三角洲口风琴」，阅读权限说明并进入系统无障碍设置，手动开启「三角洲口风琴 · 演奏服务」。
2. 选择内置《小星星》，或导入 `.mid`／`.midi`、UTF-8 文本简谱，也可直接输入简谱保存。MIDI 可选择自动旋律、指定音轨或全部音轨高声部。
3. 设置速度和移调，点击「显示悬浮控制条」。进入三角洲手游的口风琴演奏画面。
4. 点悬浮窗「校准」，依次点 1、2、3、4、5、6、7、高音 1 的中心。校准层只记录位置，不会将这些点击传给游戏。校准同时绑定当前应用、屏幕尺寸和旋转方向。
5. 将悬浮窗拖到不遮挡音键的位置。点「播放」，倒计时 3 秒后演奏；「暂停」保留位置，「继续」从该处续播，「停止」回到曲首。
6. 收起悬浮窗会停止演奏，可返回主界面恢复。彻底退出演奏服务可点主界面「停止并关闭演奏服务」，或在系统无障碍设置中关闭。

先在「本地测试键盘」完成一次八键校准和播放，可以检查触摸是否生效；进入真实游戏后需重新校准。更换分辨率、屏幕方向、游戏键位或变音开关后也应重新校准。

## 音高和时序范围

- 默认中央 1 = MIDI 60（C4），需按游戏实际音高校正。
- 低八度、高八度、升半音键默认关闭；只有游戏存在对应的**按住变音**按钮才开启并校准。当前不支持点击切换式变音。
- 关闭八度键时，超出八键音域的音按八度折回。未启用升半音键且曲谱含半音时，开始前会提示修正，避免静默改变旋律。
- 简谱支持 `1 2 3:2 0 +1 -5 #4`；冒号后为拍数，支持 `:1/2`，文本文件默认 100 BPM。
- MIDI 支持 PPQ 时间格式的 0／1 型、跨轨速度表、打击乐过滤与高声部整理；不支持 SMPTE、类型 2、踏板还原和完整多声部。它是安卓第一版实现，尚未完整移植桌面版的钢琴连奏、片段编排和线上曲库。
- 调速和移调在主界面设置，应用后回到曲首。悬浮窗提供播放、暂停、继续、停止、校准和收起。
- 曲谱最长 30 分钟、最多 30000 音符，MIDI 文件最大 10 MB。导入保存本地副本，不修改原文件。

## 输入保护与本机数据

手势只在校准的目标应用处于前台、屏幕解锁且尺寸和方向一致时开始。切出、锁屏、旋转或系统取消手势会暂停。音符按不超过 60 毫秒的片段连续长按，暂停或停止后在当前短段回调时释放；系统调度可能增加延迟，不能承诺固定上限。接口拒绝或回调超时会关闭服务，由系统清理该服务的触摸序列。

窗口包名仅用于前台确认。不读取窗口文字、不截图、无网络权限，不进行游戏进程读取或修改。曲库和校准保存在应用私有目录；卸载会移除。测试键盘校准不会用于游戏窗口，返回主界面也不会触发测试音键。

## 构建与验证

使用 Android Studio 自带的 JDK 21，安装 Android SDK Platform 34 与 Build Tools 36.0.0。设置 `JAVA_HOME` 和 `ANDROID_HOME`，或在本目录不入库的 `local.properties` 中指定 `sdk.dir`。

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug lintDebug
```

项目固定 Gradle 9.2.1 和 Android Gradle Plugin 9.0.1。Java 源码采用 UTF-8；Gradle 进程采用 `file.encoding=COMPAT`，使 Windows 中文路径的测试进程参数文件与系统编码一致。APK 位于 `app\build\outputs\apk\debug\app-debug.apk`，为本地测试签名的预览包。

10 项核心测试覆盖简谱时值、休止与非法输入、八度折回和半音检查、旋律整理、跨轨速度表、连续 MIDI 状态、打击乐过滤、暂停续播和倒计时取消。

## 平台接口依据

- [Android 无障碍手势接口](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#dispatchGesture(android.accessibilityservice.GestureDescription,android.accessibilityservice.AccessibilityService.GestureResultCallback,android.os.Handler))
- [连续长按手势](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription#continueStroke(android.graphics.Path,long,long,boolean))
- [无障碍悬浮窗](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_ACCESSIBILITY_OVERLAY)

真机待验证：手游是否接受该类手势、音键和变音规则、长音听感、密集音符稳定性，以及不同手机系统的后台行为。
