// L18: release 서명 fail-closed 가드.
//
// Gradle 서명 로직은 flutter test 밖(빌드 레벨)이라 실제 서명은 검증할 수 없으므로,
// build.gradle.kts를 정적 분석해 release 빌드가 key.properties 부재 시 debug 서명으로
// 조용히 폴백하지 않고(GradleException) 실패하는지 회귀를 잠근다.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final gradle = File('android/app/build.gradle.kts');

  test('build.gradle.kts가 존재한다', () {
    expect(gradle.existsSync(), isTrue);
  });

  test('release 빌드는 key.properties 부재 시 debug 서명으로 폴백하지 않는다', () {
    final text = gradle.readAsStringSync();
    expect(
      text.contains('signingConfigs.getByName("debug")'),
      isFalse,
      reason: 'release 서명이 debug 키로 조용히 폴백하면 안 됨(fail-open)',
    );
    expect(
      text.contains('GradleException'),
      isTrue,
      reason: 'key.properties 부재 시 release 빌드는 fail-closed로 실패해야 함',
    );
  });
}
