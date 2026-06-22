import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/branch_story_screen.dart';
import 'package:ai_story_book/screens/consent_screen.dart';
import 'package:ai_story_book/screens/onboarding_screen.dart';
import 'package:ai_story_book/screens/pod_order_screen.dart';
import 'package:ai_story_book/screens/profiles_screen.dart';
import 'package:ai_story_book/screens/pronunciation_practice_screen.dart';
import 'package:ai_story_book/screens/settings_screen.dart';
import 'package:ai_story_book/screens/startup_gate_screen.dart';
import 'package:ai_story_book/screens/voice_profiles_screen.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/parental_control_service.dart';

Future<SharedPreferences> _createPrefs([
  Map<String, Object> values = const <String, Object>{},
]) async {
  SharedPreferences.setMockInitialValues(values);
  return SharedPreferences.getInstance();
}

Widget _buildHarness(
  Widget child, {
  required SharedPreferences prefs,
  List<Override> overrides = const [],
}) {
  return ProviderScope(
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      ...overrides,
    ],
    child: MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      initialRoute: '/__test__',
      onGenerateRoute: (settings) {
        switch (settings.name) {
          case '/__test__':
            return MaterialPageRoute<void>(
              builder: (_) => child,
            );
          case '/':
            return MaterialPageRoute<void>(
              builder: (_) =>
                  const Scaffold(body: Center(child: Text('home-marker'))),
            );
          case '/consent':
            return MaterialPageRoute<void>(
              builder: (_) => const ConsentScreen(),
            );
          case '/onboarding':
            return MaterialPageRoute<void>(
              builder: (_) => const OnboardingScreen(),
            );
          case '/profiles':
            return MaterialPageRoute<void>(
              builder: (_) => const ProfilesScreen(),
            );
          case '/voice-profiles':
            return MaterialPageRoute<void>(
              builder: (_) => const VoiceProfilesScreen(),
            );
          case '/parent-dashboard':
            return MaterialPageRoute<void>(
              builder: (_) =>
                  const Scaffold(body: Text('parent-dashboard-marker')),
            );
          case '/credits':
            return MaterialPageRoute<void>(
              builder: (_) => const Scaffold(body: Text('credits-marker')),
            );
        }
        return MaterialPageRoute<void>(
          builder: (_) => Scaffold(body: Text('route:${settings.name}')),
        );
      },
    ),
  );
}

class _InteractiveMockApiClient extends ApiClient {
  _InteractiveMockApiClient({
    Map<String, dynamic>? settingsPayload,
    List<Map<String, dynamic>>? profiles,
    List<Map<String, dynamic>>? voiceProfiles,
    Map<String, dynamic>? branchGraph,
    Map<String, dynamic>? pronunciationResult,
    Map<String, dynamic>? createdOrder,
    Map<String, dynamic>? orderDetail,
  })  : _settingsPayload = Map<String, dynamic>.from(
          settingsPayload ??
              {
                'language': 'ko',
                'dark_mode': false,
                'allow_kakao_share': true,
                'bedtime_notification_enabled': false,
                'bedtime_notification_hour': 21,
                'bedtime_notification_minute': 0,
                'sleep_mode_default_minutes': 20,
                'screen_time_enabled': false,
                'daily_limit_minutes': 60,
              },
        ),
        _profiles = List<Map<String, dynamic>>.from(profiles ?? const []),
        _voiceProfiles =
            List<Map<String, dynamic>>.from(voiceProfiles ?? const []),
        _branchGraph = Map<String, dynamic>.from(
          branchGraph ??
              {
                'nodes': [
                  {
                    'node_key': 'start',
                    'page_number': 1,
                    'text': '갈림길 앞에 선 토끼가 있었어요.',
                    'image_url': '',
                  },
                  {
                    'node_key': 'left_end',
                    'page_number': 2,
                    'text': '왼쪽 길에서 친구를 만났어요.',
                    'image_url': '',
                  },
                ],
                'edges': [
                  {
                    'from_node_key': 'start',
                    'to_node_key': 'left_end',
                    'option_text': '왼쪽 길로 간다',
                  },
                ],
              },
        ),
        _pronunciationResult = Map<String, dynamic>.from(
          pronunciationResult ??
              {
                'score': 91.5,
                'feedback': '발음이 또렷합니다.',
              },
        ),
        _createdOrder = Map<String, dynamic>.from(
          createdOrder ??
              {
                'order_id': 'pod-order-1',
                'status': 'created',
                'provider_order_id': 'pf-order-1',
                'total_price': 39000,
                'sync_source': 'local',
              },
        ),
        _orderDetail = Map<String, dynamic>.from(
          orderDetail ??
              {
                'order_id': 'pod-order-1',
                'status': 'processing',
                'provider_order_id': 'pf-order-1',
                'total_price': 39000,
                'sync_source': 'printful',
                'tracking_number': 'TRACK1234',
              },
        ),
        super(
          baseUrl: 'http://localhost',
          userKey: 'test-user',
          enableLogging: false,
        );

  final Map<String, dynamic> _settingsPayload;
  final List<Map<String, dynamic>> _profiles;
  final List<Map<String, dynamic>> _voiceProfiles;
  final Map<String, dynamic> _branchGraph;
  final Map<String, dynamic> _pronunciationResult;
  final Map<String, dynamic> _createdOrder;
  final Map<String, dynamic> _orderDetail;

  Map<String, dynamic>? lastPatchedSettings;
  bool deleteMyDataCalled = false;
  int _profileSeq = 1;
  int _voiceProfileSeq = 1;

  bool grantConsentCalled = false;

  @override
  Future<Map<String, dynamic>> getSettings() async =>
      Map<String, dynamic>.from(_settingsPayload);

  @override
  Future<Map<String, dynamic>> grantConsent({
    required bool privacy,
    required bool photos,
    required bool dataProcessing,
    String? consentVersion,
  }) async {
    grantConsentCalled = true;
    return {
      'granted': privacy && dataProcessing,
      'privacy': privacy,
      'photos': photos,
      'data_processing': dataProcessing,
      'consent_version': consentVersion ?? 'v1',
      'revoked': false,
    };
  }

  @override
  Future<void> patchSettings(Map<String, dynamic> payload) async {
    lastPatchedSettings = Map<String, dynamic>.from(payload);
    _settingsPayload
      ..clear()
      ..addAll(payload);
  }

  @override
  Future<void> deleteMyData() async {
    deleteMyDataCalled = true;
  }

  @override
  Future<Map<String, dynamic>> getProfiles() async => {
        'profiles': _profiles
            .map((profile) => Map<String, dynamic>.from(profile))
            .toList(growable: false),
      };

  @override
  Future<Map<String, dynamic>> createProfile({
    required String name,
    required String ageBand,
    int? birthYear,
    int? birthMonth,
    String? preferredTheme,
    bool? isDefault,
  }) async {
    final created = {
      'id': 'profile-${_profileSeq++}',
      'name': name,
      'age_band': ageBand,
      'birth_year': birthYear,
      'birth_month': birthMonth,
      'preferred_theme': preferredTheme,
      'is_default': (isDefault ?? false) || _profiles.isEmpty,
    };
    if (created['is_default'] == true) {
      for (final profile in _profiles) {
        profile['is_default'] = false;
      }
    }
    _profiles.add(created);
    return Map<String, dynamic>.from(created);
  }

  @override
  Future<Map<String, dynamic>> updateProfile(
    String profileId, {
    String? name,
    String? ageBand,
    int? birthYear,
    int? birthMonth,
    String? preferredTheme,
    String? avatarUrl,
    bool? isDefault,
  }) async {
    final profile = _profiles.firstWhere((item) => item['id'] == profileId);
    if (name != null) {
      profile['name'] = name;
    }
    if (ageBand != null) {
      profile['age_band'] = ageBand;
    }
    if (birthYear != null) {
      profile['birth_year'] = birthYear;
    }
    if (birthMonth != null) {
      profile['birth_month'] = birthMonth;
    }
    if (preferredTheme != null) {
      profile['preferred_theme'] = preferredTheme;
    }
    if (avatarUrl != null) {
      profile['avatar_url'] = avatarUrl;
    }
    if (isDefault != null) {
      if (isDefault) {
        for (final item in _profiles) {
          item['is_default'] = false;
        }
      }
      profile['is_default'] = isDefault;
    }
    return Map<String, dynamic>.from(profile);
  }

  @override
  Future<void> deleteProfile(String profileId) async {
    _profiles.removeWhere((item) => item['id'] == profileId);
  }

  @override
  Future<Map<String, dynamic>> getVoiceProfiles() async => {
        'profiles': _voiceProfiles
            .map((profile) => Map<String, dynamic>.from(profile))
            .toList(growable: false),
      };

  @override
  Future<Map<String, dynamic>> createVoiceProfile({
    required String label,
    required String sampleAudioUrl,
    String? relationship,
    String? providerVoiceId,
    required bool consented,
  }) async {
    final created = {
      'id': 'voice-${_voiceProfileSeq++}',
      'label': label,
      'relationship': relationship,
      'sample_audio_url': sampleAudioUrl,
      'provider_voice_id': providerVoiceId,
      'consented': consented,
      'active': true,
    };
    _voiceProfiles.add(created);
    return Map<String, dynamic>.from(created);
  }

  @override
  Future<Map<String, dynamic>> updateVoiceProfile(
    String profileId, {
    String? label,
    String? sampleAudioUrl,
    String? relationship,
    String? providerVoiceId,
    bool? consented,
    bool? active,
  }) async {
    final profile =
        _voiceProfiles.firstWhere((item) => item['id'] == profileId);
    if (label != null) {
      profile['label'] = label;
    }
    if (sampleAudioUrl != null) {
      profile['sample_audio_url'] = sampleAudioUrl;
    }
    if (relationship != null) {
      profile['relationship'] = relationship;
    }
    if (providerVoiceId != null) {
      profile['provider_voice_id'] = providerVoiceId;
    }
    if (consented != null) {
      profile['consented'] = consented;
    }
    if (active != null) {
      profile['active'] = active;
    }
    return Map<String, dynamic>.from(profile);
  }

  @override
  Future<Map<String, dynamic>> revokeVoiceProfileConsent(
      String profileId) async {
    final profile =
        _voiceProfiles.firstWhere((item) => item['id'] == profileId);
    profile['consented'] = false;
    profile['active'] = false;
    return Map<String, dynamic>.from(profile);
  }

  @override
  Future<void> deleteVoiceProfile(String profileId) async {
    _voiceProfiles.removeWhere((item) => item['id'] == profileId);
  }

  @override
  Future<Map<String, dynamic>> getBranchStoryGraph(String bookId) async =>
      Map<String, dynamic>.from(_branchGraph);

  @override
  Future<Map<String, dynamic>> chooseBranchStoryOption(
    String bookId, {
    required String currentNodeKey,
    String? optionText,
    String? toNodeKey,
  }) async {
    final edges =
        (_branchGraph['edges'] as List<dynamic>).cast<Map<String, dynamic>>();
    final nodes =
        (_branchGraph['nodes'] as List<dynamic>).cast<Map<String, dynamic>>();
    final matchedEdge = edges.firstWhere(
      (edge) =>
          edge['from_node_key'] == currentNodeKey &&
          (optionText == null || edge['option_text'] == optionText),
    );
    final nextNode = nodes.firstWhere(
      (node) => node['node_key'] == matchedEdge['to_node_key'],
    );
    final nextOptions = edges
        .where((edge) => edge['from_node_key'] == nextNode['node_key'])
        .map(Map<String, dynamic>.from)
        .toList(growable: false);
    return {
      'status': nextOptions.isEmpty ? 'end' : 'ok',
      'selected_option': matchedEdge['option_text'],
      'next_node': Map<String, dynamic>.from(nextNode),
      'next_options': nextOptions,
    };
  }

  @override
  Future<Map<String, dynamic>> evaluatePronunciation({
    required String bookId,
    required int pageNumber,
    required String transcript,
    required String expectedText,
    String? audioUrl,
  }) async {
    return Map<String, dynamic>.from(_pronunciationResult);
  }

  @override
  Future<Map<String, dynamic>> createPodOrder({
    required String bookId,
    required int quantity,
    required Map<String, dynamic> shippingAddress,
  }) async {
    return Map<String, dynamic>.from(_createdOrder)
      ..['quantity'] = quantity
      ..['shipping_address'] = Map<String, dynamic>.from(shippingAddress);
  }

  @override
  Future<Map<String, dynamic>> getPodOrder(String orderId) async =>
      Map<String, dynamic>.from(_orderDetail);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('P5 hardening widget flows', () {
    testWidgets('ConsentScreen requires all approvals before continuing',
        (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient();

      await tester.pumpWidget(_buildHarness(
        const ConsentScreen(),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      final continueButton = tester.widget<ElevatedButton>(
        find.widgetWithText(ElevatedButton, '동의하고 시작하기'),
      );
      expect(continueButton.onPressed, isNull);

      // 동의 항목은 스크롤 영역 안에 있어 화면 밖일 수 있으므로 보이게 한 뒤 탭
      // (고지 문구 길이에 무관하게 견고).
      for (final label in const [
        '개인정보 수집 및 이용에 동의 (필수)',
        '사진으로 우리 아이 주인공 만들기 (선택)',
        '데이터 처리 및 저장 정책에 동의 (필수)',
      ]) {
        final checkbox = find.text(label);
        await tester.ensureVisible(checkbox);
        await tester.tap(checkbox);
        await tester.pumpAndSettle();
      }

      await tester.tap(find.text('동의하고 시작하기'));
      await tester.pumpAndSettle();

      // 서버에 동의가 실제로 전송됐는지(게이트의 근거) + 로컬 플래그 + 라우팅
      expect(api.grantConsentCalled, isTrue);
      expect(
        prefs.getBool(ParentalControlService.consentGrantedKey),
        isTrue,
      );
      expect(find.byType(OnboardingScreen), findsOneWidget);
    });

    testWidgets('OnboardingScreen skip completes onboarding and routes home',
        (tester) async {
      final prefs = await _createPrefs();

      await tester.pumpWidget(_buildHarness(
        const OnboardingScreen(),
        prefs: prefs,
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text('건너뛰기'));
      await tester.pumpAndSettle();

      expect(
        prefs.getBool(ParentalControlService.onboardingDoneKey),
        isTrue,
      );
      expect(find.text('home-marker'), findsOneWidget);
    });

    testWidgets('StartupGateScreen routes to consent when consent is missing',
        (tester) async {
      final noConsentPrefs = await _createPrefs();
      await tester.pumpWidget(_buildHarness(
        const StartupGateScreen(),
        prefs: noConsentPrefs,
      ));
      await tester.pumpAndSettle();
      expect(find.byType(ConsentScreen), findsOneWidget);
    });

    testWidgets('StartupGateScreen routes to onboarding when consent exists',
        (tester) async {
      final consentOnlyPrefs = await _createPrefs({
        ParentalControlService.consentGrantedKey: true,
      });
      await tester.pumpWidget(_buildHarness(
        const StartupGateScreen(),
        prefs: consentOnlyPrefs,
      ));
      await tester.pumpAndSettle();
      expect(find.byType(OnboardingScreen), findsOneWidget);
    });

    testWidgets('SettingsScreen saves updated toggles through API contract',
        (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient();

      await tester.pumpWidget(_buildHarness(
        const SettingsScreen(),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('설정'), findsOneWidget);
      // 설정 항목이 늘어 카카오 토글이 lazy ListView 빌드 윈도우 밖일 수 있어 먼저 스크롤.
      final kakaoSwitch =
          find.widgetWithText(SwitchListTile, '카카오톡 카드 공유');
      final settingsList = find.byType(ListView).first;
      for (var i = 0; i < 20 && kakaoSwitch.evaluate().isEmpty; i++) {
        await tester.drag(settingsList, const Offset(0, -250));
        await tester.pumpAndSettle();
      }
      await tester.ensureVisible(kakaoSwitch);
      await tester.pumpAndSettle();
      await tester.tap(kakaoSwitch);
      await tester.pumpAndSettle();
      await tester.tap(find.text('저장'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(api.lastPatchedSettings?['allow_kakao_share'], isFalse);
      expect(find.text('설정이 저장되었습니다.'), findsOneWidget);
    });

    testWidgets(
        'ProfilesScreen creates a profile and persists active selection',
        (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient(profiles: const []);

      await tester.pumpWidget(_buildHarness(
        const ProfilesScreen(),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      expect(find.text('등록된 프로필이 없어요'), findsOneWidget);
      await tester.tap(find.text('첫 프로필 만들기'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField).first, '민지');
      await tester.tap(find.text('추가'));
      await tester.pumpAndSettle();

      expect(find.text('민지'), findsOneWidget);
      expect(prefs.getString('active_profile_id_v1'), isNotEmpty);
    });

    testWidgets('ProfilesScreen DOB 드롭다운이 연령대를 파생·노출한다', (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient(profiles: const []);

      await tester.pumpWidget(_buildHarness(
        const ProfilesScreen(),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.text('첫 프로필 만들기'));
      await tester.pumpAndSettle();

      // 출생연도=만 7~8세(→ 7-9), 월=6월 선택
      final birthYear = DateTime.now().year - 8;
      await tester.tap(find.byType(DropdownButtonFormField<int>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('$birthYear년').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<int>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('6월').last);
      await tester.pumpAndSettle();

      // 생년월 선택 시 연령대가 자동 파생되어 안내됨(부모 임의선택 제거)
      expect(find.textContaining('연령대 자동'), findsOneWidget);
      expect(find.textContaining('7-9'), findsWidgets);
    });

    testWidgets('VoiceProfilesScreen creates a profile through the dialog',
        (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient(voiceProfiles: const []);

      await tester.pumpWidget(_buildHarness(
        const VoiceProfilesScreen(),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byIcon(Icons.add));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, '이름/라벨'),
        '엄마 목소리',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '샘플 오디오 URL'),
        'https://example.com/sample.m4a',
      );
      await tester.tap(find.widgetWithText(SwitchListTile, '보호자 동의 완료'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, '추가'));
      await tester.pumpAndSettle();

      expect(find.text('엄마 목소리'), findsOneWidget);
      expect(find.text('동의 완료'), findsOneWidget);
    });

    testWidgets('BranchStoryScreen restores saved progress and can restart',
        (tester) async {
      final prefs = await _createPrefs({
        'branch_story_progress_book-1_v1': 'left_end',
      });
      final api = _InteractiveMockApiClient();

      await tester.pumpWidget(_buildHarness(
        const BranchStoryScreen(bookId: 'book-1'),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      expect(find.text('왼쪽 길에서 친구를 만났어요.'), findsOneWidget);
      expect(find.text('이전 진행 지점에서 이어서 읽고 있어요.'), findsOneWidget);
      await tester.tap(find.text('처음부터'));
      await tester.pumpAndSettle();

      expect(find.text('갈림길 앞에 선 토끼가 있었어요.'), findsOneWidget);
      expect(
        prefs.getString('branch_story_progress_book-1_v1'),
        'start',
      );
    });

    testWidgets(
        'PronunciationPracticeScreen renders scored feedback after submit',
        (tester) async {
      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient();

      await tester.pumpWidget(_buildHarness(
        const PronunciationPracticeScreen(
          bookId: 'book-1',
          pageNumber: 2,
          expectedText: '토끼가 걸어가요',
        ),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextField, '읽은 문장(텍스트 입력)'),
        '토끼가 걸어가요',
      );
      await tester.tap(find.text('발음 평가하기'));
      await tester.pumpAndSettle();

      expect(find.text('발음 점수: 91.5점'), findsOneWidget);
      expect(find.text('발음이 또렷합니다.'), findsOneWidget);
    });

    testWidgets('PodOrderScreen completes order flow and shows synced status',
        (tester) async {
      tester.view.physicalSize = const Size(1200, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final prefs = await _createPrefs();
      final api = _InteractiveMockApiClient();

      await tester.pumpWidget(_buildHarness(
        const PodOrderScreen(
          bookId: 'book-1',
          bookTitle: '테스트 동화',
        ),
        prefs: prefs,
        overrides: [apiClientProvider.overrideWithValue(api)],
      ));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.widgetWithText(TextFormField, '수령인 이름'),
        '홍길동',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '주소'),
        '서울시 강남구 테스트로 1',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '우편번호'),
        '06236',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '연락처'),
        '01012345678',
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('주문하기').first);
      await tester.pumpAndSettle();

      expect(find.text('주문번호: pod-order-1'), findsOneWidget);
      expect(find.text('상태: processing'), findsOneWidget);
      expect(find.text('동기화: printful'), findsOneWidget);
      expect(find.text('운송장: TRACK1234'), findsOneWidget);
    });
  });
}
