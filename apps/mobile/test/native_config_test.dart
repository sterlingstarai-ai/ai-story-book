// 네이티브 설정 정적 가드 (W6: H27·H28·M33·L19).
//
// flutter test는 iOS/Android 네이티브 런타임(canOpenURL·백그라운드 오디오·리소스 지역화)을
// 실행할 수 없으므로, Info.plist/xcconfig/pbxproj/AndroidManifest/strings.xml/Dart 상수를
// 정적 분석해 회귀를 잠근다. 실기기 스모크는 별도(이 가드로 대체 불가, FIXLOG에 명시).
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final infoPlist = File('ios/Runner/Info.plist');
  final androidManifest = File('android/app/src/main/AndroidManifest.xml');

  // ─────────────────── H27: 카카오 공유 iOS 스킴 선언 ───────────────────
  group('H27 kakao iOS schemes', () {
    test('Info.plist가 LSApplicationQueriesSchemes(kakaolink·kakaotalk)를 선언한다', () {
      final text = infoPlist.readAsStringSync();
      expect(text.contains('LSApplicationQueriesSchemes'), isTrue);
      expect(text.contains('kakaolink'), isTrue,
          reason: 'isKakaoTalkSharingAvailable의 kakaolink 판정에 필수');
      expect(text.contains('kakaotalk'), isTrue);
    });

    test('Info.plist가 kakao URL 스킴을 CFBundleURLTypes에 등록한다', () {
      final text = infoPlist.readAsStringSync();
      expect(text.contains('CFBundleURLTypes'), isTrue);
      // G28: 하드코딩 금지 — xcconfig/CI 빌드변수로 주입.
      expect(text.contains(r'kakao$(KAKAO_NATIVE_APP_KEY)'), isTrue);
    });

    test('KAKAO_NATIVE_APP_KEY 빌드변수가 xcconfig에 선언된다', () {
      final debug = File('ios/Flutter/Debug.xcconfig').readAsStringSync();
      final release = File('ios/Flutter/Release.xcconfig').readAsStringSync();
      expect(debug.contains('KAKAO_NATIVE_APP_KEY'), isTrue);
      expect(release.contains('KAKAO_NATIVE_APP_KEY'), isTrue);
    });
  });

  // ─────────────────── H28: 백그라운드 오디오(G27=방식 a) ───────────────────
  group('H28 background audio', () {
    test('Info.plist UIBackgroundModes에 audio가 있다', () {
      final text = infoPlist.readAsStringSync();
      expect(text.contains('UIBackgroundModes'), isTrue);
      final idx = text.indexOf('UIBackgroundModes');
      // UIBackgroundModes 배열 안에 audio 문자열이 뒤따르는지 근접 검증.
      expect(text.substring(idx).contains('audio'), isTrue);
    });

    test('audio_session이 직접 의존성으로 선언된다', () {
      final pubspec = File('pubspec.yaml').readAsStringSync();
      expect(RegExp(r'^\s+audio_session:', multiLine: true).hasMatch(pubspec),
          isTrue,
          reason: 'AVAudioSession playback 카테고리 구성을 위해 직접 의존 필요');
    });
  });

  // ─────────────────── M33: 앱 표시명·권한 문자열 en/ja 지역화 ───────────────────
  group('M33 native localization', () {
    test('AndroidManifest label이 문자열 리소스를 참조한다', () {
      final text = androidManifest.readAsStringSync();
      final m = RegExp(r'android:label="([^"]*)"').firstMatch(text);
      expect(m, isNotNull);
      expect(m!.group(1)!.startsWith('@string/'), isTrue,
          reason: '하드코딩 라벨(AI 동화책) 대신 @string/app_name');
    });

    test('Android app_name이 ko/en/ja 3개 값에 존재한다', () {
      for (final path in [
        'android/app/src/main/res/values/strings.xml',
        'android/app/src/main/res/values-en/strings.xml',
        'android/app/src/main/res/values-ja/strings.xml',
      ]) {
        final f = File(path);
        expect(f.existsSync(), isTrue, reason: '$path 없음');
        expect(f.readAsStringSync().contains('name="app_name"'), isTrue,
            reason: '$path에 app_name 없음');
      }
    });

    test('iOS InfoPlist.strings ko/en/ja가 표시명·권한 4종 키를 담는다', () {
      const usageKeys = [
        'CFBundleDisplayName',
        'NSCameraUsageDescription',
        'NSPhotoLibraryUsageDescription',
        'NSMicrophoneUsageDescription',
        'NSSpeechRecognitionUsageDescription',
      ];
      for (final locale in ['ko', 'en', 'ja']) {
        final f = File('ios/Runner/$locale.lproj/InfoPlist.strings');
        expect(f.existsSync(), isTrue, reason: '$locale.lproj/InfoPlist.strings 없음');
        final text = f.readAsStringSync();
        for (final key in usageKeys) {
          expect(text.contains(key), isTrue, reason: '$locale에 $key 없음');
        }
      }
    });

    test('pbxproj가 InfoPlist.strings를 리소스로 참조한다 (#13)', () {
      // 파일과 knownRegions만 있고 프로젝트에 미참조면 어떤 빌드에도 번들되지 않아
      // en/ja 지역화가 코드 상태로는 절대 발효하지 않는다(가드가 false-green이었음).
      final text = File('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();
      expect(text.contains('InfoPlist.strings'), isTrue,
          reason: 'InfoPlist.strings가 pbxproj에 등록돼야 함');
      expect(text.contains('PBXVariantGroup'), isTrue);
      // variant group에 3개 로케일이 자식으로 등록됐는지.
      final vg = RegExp(
        r'isa = PBXVariantGroup;\s*children = \(([^)]*)\);\s*name = InfoPlist\.strings;',
        multiLine: true,
      ).firstMatch(text);
      expect(vg, isNotNull, reason: 'InfoPlist.strings variant group이 있어야 함');
      for (final locale in ['ko', 'en', 'ja']) {
        expect(vg!.group(1)!.contains('/* $locale */'), isTrue,
            reason: 'variant group에 $locale 누락');
      }
      // Resources 빌드 페이즈에 포함돼야 실제로 번들된다.
      expect(text.contains('InfoPlist.strings in Resources'), isTrue);
    });

    test('pbxproj knownRegions에 ko·ja가 등록된다', () {
      final text = File('ios/Runner.xcodeproj/project.pbxproj').readAsStringSync();
      final m = RegExp(r'knownRegions = \(([^)]*)\)').firstMatch(text);
      expect(m, isNotNull);
      final regions = m!.group(1)!;
      expect(regions.contains('ko'), isTrue);
      expect(regions.contains('ja'), isTrue);
    });
  });

  // ─────────────────── L21: 카카오 딥링크 수신 제외 (G28=결정 B) ───────────────────
  group('L21 kakao deep-link excluded', () {
    test('FeedTemplate에 execution params가 없다 — 웹 공유만(딥오픈 1차 제외)', () {
      final kakao =
          File('lib/services/kakao_share_service.dart').readAsStringSync();
      expect(kakao.contains('ExecutionParams'), isFalse,
          reason: 'G28: 카카오 딥링크 수신 1차 제외 — 미배선 execution params 데드 의도 제거');
    });
  });

  // ─────────────────── L19: placeholder 도메인 제거 + 정본 통일 ───────────────────
  group('L19 domain consistency', () {
    test('Info.plist에 example.com placeholder가 없다', () {
      expect(infoPlist.readAsStringSync().contains('example.com'), isFalse);
    });

    test('방침·약관·공유 도메인이 정본(aistorybook.com)으로 통일된다', () {
      final settings =
          File('lib/screens/settings_screen.dart').readAsStringSync();
      final kakao =
          File('lib/services/kakao_share_service.dart').readAsStringSync();

      String hostOf(String src, String constName) {
        final m = RegExp("$constName\\s*=\\s*'([^']*)'").firstMatch(src);
        if (m != null) return Uri.parse(m.group(1)!).host;
        // defaultValue 형태(String.fromEnvironment) 대응
        final m2 = RegExp("defaultValue:\\s*'(https://[^']*)'").firstMatch(src);
        return m2 != null ? Uri.parse(m2.group(1)!).host : '';
      }

      final privacyHost = hostOf(settings, '_privacyPolicyUrl');
      final shareHost = hostOf(kakao, '_webBaseUrl');
      expect(privacyHost, 'aistorybook.com');
      expect(shareHost, 'aistorybook.com',
          reason: '공유 딥링크 호스트가 정본과 달라 404 재발 방지');
    });
  });
}
