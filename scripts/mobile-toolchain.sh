#!/usr/bin/env bash
# Source from mobile scripts. Configure this process only; never run flutter config,
# install SDKs, accept licenses, or change the user's shell profile.
setup_mobile_toolchain() {
  local sdk_candidate java_candidate
  if [ -z "${ANDROID_HOME:-}" ] || [ ! -d "$ANDROID_HOME/platform-tools" ]; then
    for sdk_candidate in "${ANDROID_SDK_ROOT:-}" "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
      if [ -n "$sdk_candidate" ] && [ -x "$sdk_candidate/platform-tools/adb" ]; then
        export ANDROID_HOME="$sdk_candidate"
        break
      fi
    done
  fi
  if [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME/platform-tools" ]; then
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
  fi
  if [ -z "${JAVA_HOME:-}" ] || [ ! -x "$JAVA_HOME/bin/java" ]; then
    for java_candidate in "/Applications/Android Studio.app/Contents/jbr/Contents/Home" "/opt/android-studio/jbr" "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"; do
      if [ -x "$java_candidate/bin/java" ]; then
        export JAVA_HOME="$java_candidate"
        export PATH="$JAVA_HOME/bin:$PATH"
        break
      fi
    done
  fi
}
