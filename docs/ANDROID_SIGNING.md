# Android 업로드 서명키

2026-09-06에 이 프로젝트용 업로드 서명키를 로컬에 준비했습니다. 기존 `key.properties`와 서명 디렉터리가 없는 것을 확인한 뒤 생성했으며, Play Console 등록이나 앱 게시를 실행하지 않았습니다.

| 파일 | 저장소 기준 상대 경로 | 권한 |
|---|---|---|
| 비공개 키 저장소 | `apps/mobile/android/.signing/upload-key.jks` | 0600 |
| 저장소/키 암호 설정 | `apps/mobile/android/key.properties` | 0600 |
| 공개 인증서 | `apps/mobile/android/.signing/upload-certificate.pem` | 0600 |

`.signing` 디렉터리는 0700이며 모든 파일은 Git에서 제외했습니다. 개인키와 암호는 문서·작업 로그·프로세스 명령줄에 출력하지 않았습니다. 생성 도구는 기존 자료가 있으면 덮어쓰기를 거절합니다. 실제로 재실행이 거절되고 기존 파일이 그대로인 것을 확인했습니다. 별도의 합성 JAR 파일에 실제 개인키로 서명한 뒤 서명 검증까지 통과했고 시험 파일은 삭제했습니다.

인증서 SHA-256 지문:

```text
d81cf96b86b8c7fe8365c3553eb80c802464de7fc1e8869a1b8e2bbffdbb20f3
```

키는 RSA 4096비트, SHA256withRSA 서명, 10,000일 유효기간을 사용합니다. 인증서 이름 `AI Story Book Upload`는 로컬 서명 용도 표시이며 사업자 신원 인증이 아닙니다.

## 반드시 별도로 보관할 자료

위의 **`upload-key.jks`와 `key.properties`를 함께**, 이 체크아웃과 다른 암호화 저장소에 백업해야 합니다. 공개 인증서만 보관해서는 개인키와 암호를 복구할 수 없습니다. 현재 외부 암호화 보관소를 지정하거나 백업하지 않았습니다. 비공개 파일을 Git·이메일·공유 링크·일반 출시 증빙에 넣지 않습니다.

Play Console에서 기존 앱의 업로드 인증서가 이미 등록되어 있다면 이 새 인증서를 자동 대체하지 않습니다. 기존 앱 등록 상태와 업로드 키 등록/변경 절차를 확인해야 합니다. 이번에 생성한 키만으로 Play App Signing 등록이나 기존 배포본과의 업데이트 호환성이 입증되지는 않습니다.

## 재사용과 새 환경

현재 환경은 `android/key.properties`가 절대 경로로 키를 참조하므로 Gradle 릴리스 서명 구성을 그대로 사용합니다. 다른 환경에서는 복원한 키의 실제 경로를 해당 환경의 비공개 `key.properties`에 지정합니다. 기존 키가 필요한 환경에서 새 키를 생성해 대체하지 않습니다.

새 프로젝트 환경에서 기존 자료가 없고 새 업로드 키가 필요한 경우에만 다음 도구를 사용할 수 있습니다.

```bash
# macOS의 JDK가 시스템에 등록되어 있지 않으면 Android Studio 번들 JDK를 지정합니다.
JAVA_HOME='/Applications/Android Studio.app/Contents/jbr/Contents/Home' \
  python3 scripts/prepare_android_signing.py
```

이 도구는 키와 암호 설정만 준비합니다. 실제 운영 HTTPS API, Play Console 앱 설정, 최종 릴리스 빌드와 업로드 검증은 [RELEASE_PREPARATION.md](RELEASE_PREPARATION.md)에서 이어갑니다.
