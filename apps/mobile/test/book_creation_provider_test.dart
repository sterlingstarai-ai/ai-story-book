import 'dart:convert';
import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:dio/dio.dart';

import 'package:ai_story_book/models/models.dart';
import 'package:ai_story_book/models/generation_options.dart';
import 'package:ai_story_book/providers/providers.dart';
import 'package:ai_story_book/services/api_client.dart';

// H18: 생성 재시도(타임아웃 후 재탭) 시 같은 멱등키를 재사용해 서버가 dedup → 이중차감 방지.
class _SpyApiClient extends ApiClient {
  _SpyApiClient()
    : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  final List<String?> keys = <String?>[];
  int calls = 0;

  @override
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    calls++;
    keys.add(idempotencyKey);
    if (calls == 1) {
      throw Exception('timeout');
    }
    return CreateBookResponse(jobId: 'job-1', status: 'queued');
  }
}

class _TransportApi extends ApiClient {
  _TransportApi(this.failures)
    : super(baseUrl: 'http://test', userKey: 'u', enableLogging: false);

  final List<DioException> failures;
  final keys = <String?>[];
  void Function()? beforeFailure;

  @override
  Future<GenerationOptions> getGenerationOptions() async =>
      const GenerationOptions([BookStyle.watercolor]);

  @override
  Future<List<JobStatus>> getActiveBookGenerations() async => [];

  @override
  Future<CreateBookResponse> createBook(
    BookSpec spec, {
    String? idempotencyKey,
  }) async {
    keys.add(idempotencyKey);
    if (keys.length <= failures.length) {
      beforeFailure?.call();
      throw failures[keys.length - 1];
    }
    return CreateBookResponse(jobId: 'accepted-job', status: 'queued');
  }
}

DioException _transportFailure(DioExceptionType type, {int? status}) {
  final options = RequestOptions(path: '/v1/books');
  return DioException(
    requestOptions: options,
    type: type,
    response: status == null
        ? null
        : Response(requestOptions: options, statusCode: status),
  );
}

void main() {
  final spec = BookSpec(
    topic: '친구를 돕는 이야기',
    targetAge: '7-9',
    style: 'watercolor',
  );

  test(
    'a closed HTTP response reconciles the accepted request over real TCP',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      final keys = <String?>[];
      final bodies = <String>[];
      final accepted = <String>{};
      server.listen((request) async {
        if (request.method != 'POST' || request.uri.path != '/v1/books') {
          request.response.statusCode = 404;
          await request.response.close();
          return;
        }
        final key = request.headers.value('x-idempotency-key');
        keys.add(key);
        bodies.add(await utf8.decoder.bind(request).join());
        expect(request.headers.value('x-user-key'), 'synthetic-owner');
        expect(request.headers.value('x-profile-id'), 'synthetic-profile');
        accepted.add(key!);
        if (keys.length == 1) {
          final socket = await request.response.detachSocket(
            writeHeaders: false,
          );
          socket.destroy();
          return;
        }
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({'job_id': 'same-job', 'status': 'queued'}),
        );
        await request.response.close();
      });
      final api = ApiClient(
        baseUrl: 'http://127.0.0.1:${server.port}',
        userKey: 'synthetic-owner',
        profileId: 'synthetic-profile',
        enableLogging: false,
      );
      addTearDown(api.close);
      final container = ProviderContainer(
        overrides: [
          apiClientProvider.overrideWithValue(api),
          generationOptionsProvider.overrideWith(
            (ref) async => const GenerationOptions([BookStyle.watercolor]),
          ),
          activeBookGenerationsProvider.overrideWith((ref) async => []),
        ],
      );
      addTearDown(container.dispose);
      expect(
        await container.read(bookCreationProvider.notifier).createBook(spec),
        'same-job',
      );
      expect(keys, hasLength(2));
      expect(accepted, hasLength(1));
      expect(bodies.toSet(), hasLength(1));
    },
  );

  for (final type in [
    DioExceptionType.connectionTimeout,
    DioExceptionType.sendTimeout,
    DioExceptionType.receiveTimeout,
    DioExceptionType.connectionError,
  ]) {
    test(
      'reconciles a lost $type response once with the original key',
      () async {
        final api = _TransportApi([_transportFailure(type)]);
        addTearDown(api.close);
        final container = ProviderContainer(
          overrides: [apiClientProvider.overrideWithValue(api)],
        );
        addTearDown(container.dispose);
        final id = await container
            .read(bookCreationProvider.notifier)
            .createBook(spec);
        expect(id, 'accepted-job');
        expect(api.keys, hasLength(2));
        expect(api.keys.first, isNotNull);
        expect(api.keys.last, api.keys.first);
        expect(container.read(currentJobProvider)?.jobId, 'accepted-job');
      },
    );
  }

  test(
    'a second lost response stops and a manual retry retains the key',
    () async {
      final api = _TransportApi([
        _transportFailure(DioExceptionType.receiveTimeout),
        _transportFailure(DioExceptionType.connectionError),
      ]);
      addTearDown(api.close);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(container.dispose);
      final notifier = container.read(bookCreationProvider.notifier);
      await expectLater(
        notifier.createBook(spec),
        throwsA(isA<DioException>()),
      );
      expect(api.keys, hasLength(2));
      expect(await notifier.createBook(spec), 'accepted-job');
      expect(api.keys, hasLength(3));
      expect(api.keys.toSet(), hasLength(1));
    },
  );

  for (final type in [
    DioExceptionType.cancel,
    DioExceptionType.badCertificate,
    DioExceptionType.unknown,
  ]) {
    test('does not replay $type', () async {
      final api = _TransportApi([_transportFailure(type)]);
      addTearDown(api.close);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(container.dispose);
      await expectLater(
        container.read(bookCreationProvider.notifier).createBook(spec),
        throwsA(isA<DioException>()),
      );
      expect(api.keys, hasLength(1));
    });
  }

  for (final status in [400, 401, 402, 403, 429, 500, 503]) {
    test('does not replay an explicit HTTP $status refusal', () async {
      final api = _TransportApi([
        _transportFailure(DioExceptionType.badResponse, status: status),
      ]);
      addTearDown(api.close);
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(api)],
      );
      addTearDown(container.dispose);
      await expectLater(
        container.read(bookCreationProvider.notifier).createBook(spec),
        throwsA(isA<DioException>()),
      );
      expect(api.keys, hasLength(1));
    });
  }

  test(
    'does not reconcile after the account or profile client changes',
    () async {
      final first = _TransportApi([
        _transportFailure(DioExceptionType.receiveTimeout),
      ]);
      final next = _TransportApi([]);
      addTearDown(first.close);
      addTearDown(next.close);
      final selectedClient = StateProvider<ApiClient>((ref) => first);
      final container = ProviderContainer(
        overrides: [
          apiClientProvider.overrideWith((ref) => ref.watch(selectedClient)),
        ],
      );
      addTearDown(container.dispose);
      first.beforeFailure = () =>
          container.read(selectedClient.notifier).state = next;
      await expectLater(
        container.read(bookCreationProvider.notifier).createBook(spec),
        throwsA(isA<DioException>()),
      );
      expect(first.keys, hasLength(1));
      expect(next.keys, isEmpty);
    },
  );

  test(
    'createBook reuses idempotency key across retries, new after success',
    () async {
      final spy = _SpyApiClient();
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(spy)],
      );
      addTearDown(container.dispose);

      final spec = BookSpec(topic: 't', targetAge: '5-7', style: 'watercolor');
      final notifier = container.read(bookCreationProvider.notifier);

      // 1차 실패(타임아웃).
      await expectLater(notifier.createBook(spec), throwsException);
      // 2차 재시도 → 같은 spec이면 같은 키 재사용.
      final jobId = await notifier.createBook(spec);

      expect(jobId, 'job-1');
      expect(spy.keys.length, 2);
      expect(spy.keys[0], isNotNull);
      expect(spy.keys[0], spy.keys[1]); // 재시도 동일 키

      // 성공 후 새 생성은 새 키.
      await notifier.createBook(spec);
      expect(spy.keys.length, 3);
      expect(spy.keys[2], isNot(spy.keys[1]));
    },
  );
}
