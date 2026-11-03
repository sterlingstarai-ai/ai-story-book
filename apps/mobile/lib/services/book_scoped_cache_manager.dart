import 'dart:async';
import 'dart:io' as io;
import 'dart:typed_data';

import 'package:file/file.dart' as platform_file;
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';

import 'book_media_store.dart';

typedef BookMediaDownload =
    Future<void> Function(
      Uri url,
      io.File destination,
      Map<String, String> headers,
    );

/// CacheManager bridge for one book and one media format. All disk writes go
/// through BookMediaStore, whose deletion marker blocks late publication.
class BookScopedCacheManager implements BaseCacheManager {
  BookScopedCacheManager({
    required this.store,
    required this.bookId,
    required this.fileExtension,
    BookMediaDownload? download,
    this.legacyReadOnly,
  }) : _download = download ?? _downloadToFile {
    if (!RegExp(r'^[a-z0-9]{1,8}$').hasMatch(fileExtension)) {
      throw ArgumentError('Invalid media extension');
    }
  }

  final BookMediaStore store;
  final String bookId;
  final String fileExtension;
  final BookMediaDownload _download;
  /// Existing shared-cache files can be read, but new writes never use it.
  final BaseCacheManager? legacyReadOnly;
  final Map<String, Future<FileInfo>> _inFlight = {};
  static const _fileSystem = LocalFileSystem();
  static const _maxBytes = 32 * 1024 * 1024;

  FileInfo _info(io.File file, FileSource source, String url) => FileInfo(
    _fileSystem.file(file.path),
    source,
    DateTime.now().add(const Duration(days: 365)),
    url,
  );

  Future<FileInfo?> _legacyFile(String key) async {
    final legacy = legacyReadOnly;
    if (legacy == null || !await store.canRead(bookId)) return null;
    FileInfo? cached;
    try {
      cached = await legacy.getFileFromCache(key);
      if (cached == null || !await cached.file.exists()) return null;
    } catch (_) {
      return null;
    }
    return await store.canRead(bookId) ? cached : null;
  }

  Future<FileInfo> _load(
    String url, {
    required String identity,
    Map<String, String>? headers,
    bool force = false,
  }) async {
    if (!force) {
      final cached = await store.lookup(
        bookId,
        identity,
        extension: fileExtension,
      );
      if (cached != null) return _info(cached, FileSource.Cache, url);
      final legacy = await _legacyFile(identity);
      if (legacy != null) return legacy;
    }
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !const {'http', 'https'}.contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      throw ArgumentError('Invalid media URL');
    }
    final active = _inFlight[identity];
    if (active != null) return active;
    final operation = store
        .write(
          bookId,
          identity,
          extension: fileExtension,
          download: (temporary) =>
              _download(uri, temporary, headers ?? const {}),
        )
        .then((file) => _info(file, FileSource.Online, url));
    _inFlight[identity] = operation;
    try {
      return await operation;
    } finally {
      if (identical(_inFlight[identity], operation)) _inFlight.remove(identity);
    }
  }

  @override
  Future<platform_file.File> getSingleFile(
    String url, {
    String? key,
    Map<String, String>? headers,
  }) async => (await _load(url, identity: key ?? url, headers: headers)).file;

  @override
  Stream<FileInfo> getFile(
    String url, {
    String? key,
    Map<String, String>? headers,
  }) async* {
    yield await _load(url, identity: key ?? url, headers: headers);
  }

  @override
  Stream<FileResponse> getFileStream(
    String url, {
    String? key,
    Map<String, String>? headers,
    bool withProgress = false,
  }) async* {
    yield await _load(url, identity: key ?? url, headers: headers);
  }

  @override
  Future<FileInfo> downloadFile(
    String url, {
    String? key,
    Map<String, String>? authHeaders,
    bool force = false,
  }) => _load(url, identity: key ?? url, headers: authHeaders, force: force);

  @override
  Future<FileInfo?> getFileFromCache(
    String key, {
    bool ignoreMemCache = false,
  }) async {
    final cached = await store.lookup(bookId, key, extension: fileExtension);
    if (cached != null) return _info(cached, FileSource.Cache, '');
    return await _legacyFile(key);
  }

  @override
  Future<FileInfo?> getFileFromMemory(String key) async => null;

  @override
  Future<platform_file.File> putFile(
    String url,
    Uint8List fileBytes, {
    String? key,
    String? eTag,
    Duration maxAge = const Duration(days: 30),
    String fileExtension = 'file',
  }) => putFileStream(url, Stream.value(fileBytes), key: key);

  @override
  Future<platform_file.File> putFileStream(
    String url,
    Stream<List<int>> source, {
    String? key,
    String? eTag,
    Duration maxAge = const Duration(days: 30),
    String fileExtension = 'file',
  }) async {
    final file = await store.write(
      bookId,
      key ?? url,
      extension: this.fileExtension,
      download: (temporary) => _writeStream(temporary, source),
    );
    return _fileSystem.file(file.path);
  }

  @override
  Future<void> removeFile(String key) =>
      store.remove(bookId, key, extension: fileExtension);

  @override
  Future<void> emptyCache() async =>
      throw UnsupportedError('Whole-cache deletion is not supported');

  @override
  Future<void> dispose() async {}

  static Future<void> _writeStream(
    io.File destination,
    Stream<List<int>> source,
  ) async {
    final sink = destination.openWrite();
    var count = 0;
    try {
      await for (final chunk in source.timeout(const Duration(seconds: 30))) {
        count += chunk.length;
        if (count > _maxBytes) throw StateError('Media is too large');
        sink.add(chunk);
      }
      await sink.flush();
    } finally {
      await sink.close();
    }
  }

  static Future<void> _downloadToFile(
    Uri uri,
    io.File destination,
    Map<String, String> headers,
  ) async {
    final client = io.HttpClient()
      ..connectionTimeout = const Duration(seconds: 15);
    final deadline = Timer(const Duration(minutes: 2), () => client.close(force: true));
    try {
      final request = await client
          .getUrl(uri)
          .timeout(const Duration(seconds: 20));
      request.followRedirects = false;
      headers.forEach(request.headers.set);
      final response = await request.close().timeout(
        const Duration(seconds: 30),
      );
      if (response.statusCode != 200) {
        throw HttpExceptionWithStatus(
          response.statusCode,
          'Media request failed',
        );
      }
      if (response.contentLength > _maxBytes) {
        throw StateError('Media is too large');
      }
      await _writeStream(destination, response);
    } finally {
      deadline.cancel();
      client.close(force: true);
    }
  }
}
