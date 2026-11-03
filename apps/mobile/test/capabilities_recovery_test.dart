import 'dart:async';

import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _CapabilitiesApi extends ApiClient {
  _CapabilitiesApi({this.failures = 0, required this.audio})
    : super(baseUrl: 'http://127.0.0.1:1', userKey: 'synthetic');

  int failures;
  int requests = 0;
  final bool audio;

  @override
  Future<Map<String, dynamic>> getCapabilities() async {
    requests++;
    if (failures > 0) {
      failures--;
      throw StateError('synthetic network failure');
    }
    return {'audio_supported': audio, 'inpaint_supported': false};
  }
}

void main() {
  testWidgets('a transient failure stays closed and retries after delay', (
    tester,
  ) async {
    final api = _CapabilitiesApi(failures: 1, audio: true);
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(api)],
    );
    final subscription = container.listen(capabilitiesProvider, (_, __) {});
    addTearDown(() {
      subscription.close();
      container.dispose();
      api.close();
    });

    expect(
      (await container.read(capabilitiesProvider.future))['audio_supported'],
      false,
    );
    expect(api.requests, 1);
    await tester.pump(const Duration(seconds: 29));
    expect(api.requests, 1);
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(milliseconds: 1));
    expect(
      (await container.read(capabilitiesProvider.future))['audio_supported'],
      true,
    );
    expect(api.requests, 2);
  });

  testWidgets('changing the API client refreshes cached capabilities', (
    tester,
  ) async {
    final oldApi = _CapabilitiesApi(audio: false);
    final newApi = _CapabilitiesApi(audio: true);
    final apiChoice = StateProvider<ApiClient>((ref) => oldApi);
    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWith((ref) => ref.watch(apiChoice)),
      ],
    );
    final subscription = container.listen(capabilitiesProvider, (_, __) {});
    addTearDown(() {
      subscription.close();
      container.dispose();
      oldApi.close();
      newApi.close();
    });

    expect(
      (await container.read(capabilitiesProvider.future))['audio_supported'],
      false,
    );
    container.read(apiChoice.notifier).state = newApi;
    await tester.pump(const Duration(milliseconds: 1));
    expect(
      (await container.read(capabilitiesProvider.future))['audio_supported'],
      true,
    );
    expect(newApi.requests, 1);
    await tester.pump(const Duration(milliseconds: 1));
  });

  testWidgets(
    'disposing while a request is in flight does not schedule retries',
    (tester) async {
      final pending = Completer<Map<String, dynamic>>();
      final api = _PendingCapabilitiesApi(pending);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      container.read(capabilitiesProvider);
      container.dispose();
      pending.completeError(StateError('late synthetic failure'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 31));
      expect(tester.takeException(), isNull);
      api.close();
    },
  );
}

class _PendingCapabilitiesApi extends ApiClient {
  _PendingCapabilitiesApi(this.pending)
    : super(baseUrl: 'http://127.0.0.1:1', userKey: 'synthetic');
  final Completer<Map<String, dynamic>> pending;

  @override
  Future<Map<String, dynamic>> getCapabilities() => pending.future;
}
