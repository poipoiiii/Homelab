plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}

// 构建产物落到 .cache，不污染源码目录；可用 BILL_CAPTURE_BUILD 覆盖
val outputDir = System.getenv("BILL_CAPTURE_BUILD") ?: "build"

allprojects {
    layout.buildDirectory.set(rootProject.file(outputDir).resolve(project.name))
}
