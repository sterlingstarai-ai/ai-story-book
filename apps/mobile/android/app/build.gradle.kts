import java.util.Properties

val keyProperties = Properties()
val keyPropertiesFile = rootProject.file("key.properties")
if (keyPropertiesFile.exists()) {
    keyProperties.load(keyPropertiesFile.inputStream())
}

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.storybook.ai_story_book"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        // flutter_local_notifications 18.x 요구사항
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.storybook.ai_story_book"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            if (keyPropertiesFile.exists()) {
                val storePath = keyProperties.getProperty("storeFile")
                if (!storePath.isNullOrBlank()) {
                    storeFile = file(storePath)
                }
                storePassword = keyProperties.getProperty("storePassword")
                keyAlias = keyProperties.getProperty("keyAlias")
                keyPassword = keyProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (keyPropertiesFile.exists()) {
                signingConfigs.getByName("release")
            } else {
                // L18: fail-closed. release 태스크인데 key.properties가 없으면 debug 서명으로
                // 조용히 폴백하지 않고 빌드를 실패시킨다(androiddebugkey로 서명된 '릴리스'
                // 산출물 유통 방지). debug 빌드/flutter run은 release 태스크가 아니므로 통과.
                val isReleaseBuild = gradle.startParameter.taskNames.any {
                    it.contains("Release", ignoreCase = true)
                }
                if (isReleaseBuild) {
                    throw GradleException(
                        "release 빌드에는 android/key.properties가 필요합니다. debug 서명 폴백 금지."
                    )
                }
                // release 태스크가 아니면 release 변형은 서명하지 않고 null(debug 산출물 무관).
                null
            }
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    // flutter_local_notifications 18.x core library desugaring
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
