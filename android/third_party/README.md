# 安卓附加依赖

- jsoup 1.23.2：公开 HTML 解析，MIT 许可证，见 [jsoup-LICENSE.txt](jsoup-LICENSE.txt)。只解析下载的文字，不执行网页脚本。
- desugar_jdk_libs_nio 2.1.5：Android Gradle 的 Java API 兼容库，GPLv2 + Classpath Exception；项目及许可证见 [Google desugar_jdk_libs](https://github.com/google/desugar_jdk_libs)。随兼容库制品提供版权文件。
- JUnit、org.json 仅用于本机测试，不随应用打包。

接口参考：[jsoup 字符串解析](https://jsoup.org/cookbook/input/parse-document-from-string)、[Android AudioTrack](https://developer.android.com/reference/android/media/AudioTrack)。
