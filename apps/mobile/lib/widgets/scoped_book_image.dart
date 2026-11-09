import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/book_scoped_cache_manager.dart';

/// Book-owned media writes use a scoped store. Historic shared-cache entries
/// are read only and cannot certify complete local per-book erasure.
class ScopedBookImage extends ConsumerStatefulWidget {
  const ScopedBookImage({
    super.key,
    required this.bookId,
    required this.imageUrl,
    required this.placeholder,
    required this.error,
    this.onSignedUrlRejected,
    this.onRetrySignedUrl,
    this.fit,
    this.width,
    this.height,
  });

  final String bookId;
  final String imageUrl;
  final Widget placeholder;
  final Widget error;
  final VoidCallback? onSignedUrlRejected;
  final Future<void> Function()? onRetrySignedUrl;
  final BoxFit? fit;
  final double? width;
  final double? height;

  @override
  ConsumerState<ScopedBookImage> createState() => _ScopedBookImageState();
}

class _ScopedBookImageState extends ConsumerState<ScopedBookImage> {
  var _attempt = 0;
  var _retrying = false;

  bool _canRetry(BookScopedCacheManager manager) =>
      mounted &&
      manager.bookId == widget.bookId &&
      identical(
        ref.read(bookMediaStoreProvider).valueOrNull?.store,
        manager.store,
      ) &&
      !ref.read(bookMediaBlockedProvider(widget.bookId));

  Future<void> _retry(
    BookScopedCacheManager manager,
    String url,
    bool signedRejection,
  ) async {
    if (_retrying || widget.imageUrl != url || !_canRetry(manager)) return;
    setState(() => _retrying = true);
    try {
      if (signedRejection) {
        await widget.onRetrySignedUrl?.call();
      } else {
        // A failed decode may leave corrupt bytes in the scoped disk cache.
        await manager.removeFile(url);
      }
    } catch (_) {
      // The next image load will surface a continuing error. A change in
      // consent or ownership is enforced by the surrounding providers.
    } finally {
      if (mounted) {
        setState(() {
          _attempt++;
          _retrying = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scope = ref.watch(bookMediaStoreProvider);
    if (ref.watch(bookMediaBlockedProvider(widget.bookId)) || _retrying) {
      return widget.placeholder;
    }
    return scope.when(
      loading: () => widget.placeholder,
      error: (_, __) => widget.error,
      data: (media) {
        final manager = ref.watch(
          bookIllustrationCacheProvider((
            store: media.store,
            bookId: widget.bookId,
          )),
        );
        return CachedNetworkImage(
          key: ValueKey(_attempt),
          imageUrl: widget.imageUrl,
          fit: widget.fit,
          width: widget.width,
          height: widget.height,
          cacheManager: manager,
          placeholder: (_, __) => widget.placeholder,
          errorWidget: (context, url, failure) {
            final signedRejection =
                failure is HttpExceptionWithStatus &&
                const {401, 403, 404}.contains(failure.statusCode) &&
                (Uri.tryParse(url)?.query
                        .split('&')
                        .any((field) => field.startsWith('X-Amz-Signature=')) ??
                    false);
            final notify = widget.onSignedUrlRejected;
            if (notify != null && signedRejection) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (context.mounted &&
                    widget.imageUrl == url &&
                    _canRetry(manager)) {
                  notify();
                }
              });
            }
            if (widget.onRetrySignedUrl == null) return widget.error;
            return ColoredBox(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.broken_image, size: 40),
                      FilledButton.tonal(
                        style: FilledButton.styleFrom(
                          minimumSize: const Size(64, 64),
                        ),
                        onPressed: () =>
                            unawaited(_retry(manager, url, signedRejection)),
                        child: Text(
                          AppLocalizations.of(context).viewerRetryIllustration,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }
}
