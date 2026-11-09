import 'dart:async';

import 'package:ai_story_book/l10n/app_localizations.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/screens/settings_screen.dart';
import 'package:ai_story_book/widgets/narration_style_previews.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:ai_story_book/services/page_audio_playback.dart';
import 'package:ai_story_book/services/parental_control_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _SettingsApi extends ApiClient {
  _SettingsApi(
    this.supported, {
    this.styleSupported = false,
    this.previewProvider,
    this.audioProvider,
    this.narrationSupported,
    this.audioSupported = true,
    this.betaInvitationSupported = false,
  }) : super(baseUrl: 'http://localhost', userKey: 'test');
  final bool supported;
  final bool styleSupported;
  final String? previewProvider;
  final String? audioProvider;
  final bool? narrationSupported;
  final bool audioSupported;
  final bool betaInvitationSupported;
  int invitationRequests = 0;
  Future<String>? pendingInvitation;
  @override
  Future<Map<String, dynamic>> getSettings() async => {};
  @override
  Future<void> patchSettings(Map<String, dynamic> payload) async {}
  @override
  Future<Map<String, dynamic>> getCapabilities() async => {
    'audio_supported': audioSupported,
    if (narrationSupported != null) 'narration_supported': narrationSupported,
    'narration_voice_selection_supported': supported,
    'narration_style_selection_supported': styleSupported,
    if (previewProvider != null) 'narration_preview_provider': previewProvider,
    if (audioProvider != null) 'narration_audio_provider': audioProvider,
    'generation_invitation_supported': betaInvitationSupported,
  };

  @override
  Future<String> getGenerationInvitationId() async {
    invitationRequests++;
    return pendingInvitation ?? ('b' * 64);
  }
}

class _PreviewPlayer implements NarrationPreviewPlayer {
  final assets = <String>[];
  int starts = 0;
  int stops = 0;
  bool disposed = false;
  @override
  Future<void> setAsset(String asset) async {
    assets.add(asset);
  }

  @override
  Future<void> stop() async {
    stops++;
  }

  @override
  Future<void> play() async {
    starts++;
  }

  @override
  Future<void> dispose() async {
    disposed = true;
  }
}

class _DelayedPreviewPlayer extends _PreviewPlayer {
  final firstLoad = Completer<void>();
  String? loaded;
  @override
  Future<void> setAsset(String asset) async {
    assets.add(asset);
    if (assets.length == 1) await firstLoad.future;
    loaded = asset;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('beta invitation copies only after the parent check', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final api = _SettingsApi(false, betaInvitationSupported: true);
    final copied = <Object?>[];
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied.add(call.arguments);
      return null;
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(SystemChannels.platform, null),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final tile = find.text('베타 참여 ID 복사', skipOffstage: false);
    await tester.scrollUntilVisible(
      tile,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(tile);
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(api.invitationRequests, 0);
    expect(copied, isEmpty);
    Navigator.pop(tester.element(find.byType(AlertDialog)), false);
    await tester.pumpAndSettle();
    await prefs.setInt(
      ParentalControlService.ageGateSessionKey,
      DateTime.now().millisecondsSinceEpoch,
    );
    final invitation = Completer<String>();
    api.pendingInvitation = invitation.future;
    await tester.tap(tile);
    await tester.pumpAndSettle();
    expect(api.invitationRequests, 1);
    await tester.tap(tile);
    await tester.pumpAndSettle();
    expect(api.invitationRequests, 1);
    expect(copied, isEmpty);
    invitation.complete('b' * 64);
    await tester.pumpAndSettle();
    expect(copied, [
      {'text': 'b' * 64},
    ]);
    expect(find.text('베타 참여 ID를 복사했어요.'), findsOneWidget);
  });

  testWidgets(
    'narration settings are available without pronunciation support',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(
              _SettingsApi(
                true,
                styleSupported: true,
                audioSupported: false,
                narrationSupported: true,
              ),
            ),
          ],
          child: const MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: Locale('ko'),
            home: SettingsScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('이야기 성우 미리 듣기', skipOffstage: false),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('이야기 성우 미리 듣기', skipOffstage: false), findsOneWidget);
    },
  );

  testWidgets('narrator setting saves a voice on this device', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(_SettingsApi(true)),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final dropdown = find.byType(DropdownButtonFormField<String>);
    await tester.scrollUntilVisible(
      dropdown,
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('남성 느낌의 목소리').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장').first);
    await tester.pumpAndSettle();
    expect(prefs.getString(narrationVoicePreferenceKey), 'deep');
  });

  testWidgets('unsupported deployment does not advertise voice selection', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(_SettingsApi(false)),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(DropdownButtonFormField<String>), findsNothing);
  });

  testWidgets('voice selection remains usable on a narrow enlarged screen', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 480);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(_SettingsApi(true)),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('ko'),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(1.4)),
            child: child!,
          ),
          home: const SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final dropdown = find.byType(DropdownButtonFormField<String>);
    await tester.scrollUntilVisible(
      dropdown,
      180,
      scrollable: find.byType(Scrollable).first,
    );
    await Scrollable.ensureVisible(tester.element(dropdown), alignment: .5);
    await tester.pumpAndSettle();
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    expect(find.text('여성 느낌의 목소리'), findsOneWidget);
    expect(find.text('남성 느낌의 목소리'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('style previews and selection are available and saved', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(
            _SettingsApi(true, styleSupported: true),
          ),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final dropdown = find
        .byType(DropdownButtonFormField<String>, skipOffstage: false)
        .last;
    await tester.scrollUntilVisible(
      dropdown,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await Scrollable.ensureVisible(tester.element(dropdown), alignment: .5);
    await tester.pumpAndSettle();
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('구연동화').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장').first);
    await tester.pumpAndSettle();
    expect(prefs.getString(narrationStylePreferenceKey), 'animated');
    expect(find.text('이야기 성우 미리 듣기', skipOffstage: false), findsOneWidget);
  });
  test('style is included in the cache identity', () {
    final a = pageAudioCacheKey('book', 1, 'ko', 'text', style: 'natural');
    final b = pageAudioCacheKey('book', 1, 'ko', 'text', style: 'bedtime');
    expect(a, isNot(b));
    expect(narrationStyleOrDefault('unknown'), 'legacy');
  });

  testWidgets('Realtime offers three styles without older audio previews', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(
            _SettingsApi(
              true,
              styleSupported: true,
              audioProvider: 'openai_realtime',
            ),
          ),
          realtimeNarrationPreviewsProvider.overrideWith((ref) async => false),
          narrationPreviewPlayerFactoryProvider.overrideWithValue(
            () => throw StateError('Older audio must not play for Realtime'),
          ),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final pending = find.textContaining('미리 듣기를 준비 중이에요');
    await tester.scrollUntilVisible(
      pending,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(pending, findsOneWidget);
    expect(
      find.byKey(const ValueKey('narration-preview-animated')),
      findsNothing,
    );

    final dropdown = find.byType(DropdownButtonFormField<String>).last;
    await Scrollable.ensureVisible(tester.element(dropdown), alignment: .5);
    await tester.pumpAndSettle();
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    for (final label in ['이야기 성우', '구연동화', '잠자리']) {
      expect(find.text(label), findsWidgets);
    }
    await tester.tap(find.text('구연동화').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('저장').first);
    await tester.pumpAndSettle();
    expect(prefs.getString(narrationStylePreferenceKey), 'animated');
  });

  for (final voice in ['warm', 'deep']) {
    testWidgets('Realtime loads the three $voice preview assets', (
      tester,
    ) async {
      final player = _PreviewPlayer();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            capabilitiesProvider.overrideWith(
              (ref) async => {'narration_audio_provider': 'openai_realtime'},
            ),
            narrationPreviewPlayerFactoryProvider.overrideWithValue(
              () => player,
            ),
          ],
          child: MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: const Locale('ko'),
            home: Scaffold(body: NarrationStylePreviews(voice: voice)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      const styles = ['natural', 'animated', 'bedtime'];
      for (final style in styles) {
        await tester.tap(find.byKey(ValueKey('narration-preview-$style')));
        await tester.pumpAndSettle();
      }
      expect(player.assets, [
        for (final style in styles)
          'assets/audio/narration_preview_realtime_${voice}_$style.wav',
      ]);
    });
  }

  testWidgets('all three preview buttons call the offline player', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final player = _PreviewPlayer();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(
            _SettingsApi(true, styleSupported: true),
          ),
          narrationPreviewPlayerFactoryProvider.overrideWithValue(() => player),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    for (final label in ['이야기 성우 미리 듣기', '구연동화 미리 듣기', '잠자리 미리 듣기']) {
      final button = find.text(label, skipOffstage: false);
      await tester.scrollUntilVisible(
        button,
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await Scrollable.ensureVisible(tester.element(button), alignment: .5);
      await tester.pumpAndSettle();
      await tester.tap(button);
      await tester.pumpAndSettle();
    }
    expect(player.assets, [
      'assets/audio/narration_preview_natural.mp3',
      'assets/audio/narration_preview_animated.mp3',
      'assets/audio/narration_preview_bedtime.mp3',
    ]);
    expect(player.starts, 3);
    expect(player.stops, 3);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(player.disposed, isTrue);
  });

  testWidgets(
    'rapid preview selection plays the most recently selected sample',
    (tester) async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final player = _DelayedPreviewPlayer();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sharedPreferencesProvider.overrideWithValue(prefs),
            apiClientProvider.overrideWithValue(
              _SettingsApi(true, styleSupported: true),
            ),
            narrationPreviewPlayerFactoryProvider.overrideWithValue(
              () => player,
            ),
          ],
          child: const MaterialApp(
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            locale: Locale('ko'),
            home: SettingsScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final first = find.text('이야기 성우 미리 듣기', skipOffstage: false);
      await tester.scrollUntilVisible(
        first,
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await Scrollable.ensureVisible(tester.element(first), alignment: .3);
      await tester.pumpAndSettle();
      await tester.tap(first);
      await tester.pump();
      final second = find.text('구연동화 미리 듣기', skipOffstage: false);
      await Scrollable.ensureVisible(tester.element(second), alignment: .5);
      await tester.pump();
      await tester.tap(second);
      await tester.pump();
      player.firstLoad.complete();
      await tester.pumpAndSettle();
      expect(player.loaded, 'assets/audio/narration_preview_animated.mp3');
      expect(player.starts, 1);
    },
  );

  testWidgets('Google deployment plays its own approved style sample', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final player = _PreviewPlayer();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          apiClientProvider.overrideWithValue(
            _SettingsApi(
              true,
              styleSupported: true,
              previewProvider: 'google_gemini',
            ),
          ),
          narrationPreviewPlayerFactoryProvider.overrideWithValue(() => player),
        ],
        child: const MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: Locale('ko'),
          home: SettingsScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.text('구연동화 미리 듣기', skipOffstage: false);
    await tester.scrollUntilVisible(
      button,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await Scrollable.ensureVisible(tester.element(button), alignment: .5);
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(player.assets, [
      'assets/audio/narration_preview_google_animated.mp3',
    ]);
    final voiceDropdown = find
        .byType(DropdownButtonFormField<String>, skipOffstage: false)
        .first;
    await Scrollable.ensureVisible(
      tester.element(voiceDropdown),
      alignment: .5,
    );
    await tester.pumpAndSettle();
    await tester.tap(voiceDropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('남성 느낌의 목소리').last);
    await tester.pumpAndSettle();
    await Scrollable.ensureVisible(tester.element(button), alignment: .5);
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(
      player.assets.last,
      'assets/audio/narration_preview_google_male_animated.mp3',
    );
  });
}
