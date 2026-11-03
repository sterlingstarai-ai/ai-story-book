import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../services/book_scoped_cache_manager.dart';

/// Book-owned media writes use a scoped store. Historic shared-cache entries
/// are read only and cannot certify complete local per-book erasure.
class ScopedBookImage extends ConsumerWidget {
  const ScopedBookImage({
    super.key,
    required this.bookId,
    required this.imageUrl,
    required this.placeholder,
    required this.error,
    this.fit,
    this.width,
    this.height,
  });

  final String bookId;
  final String imageUrl;
  final Widget placeholder;
  final Widget error;
  final BoxFit? fit;
  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(bookMediaBlockedProvider(bookId))) return placeholder;
    final scope = ref.watch(bookMediaStoreProvider);
    return scope.when(
      loading: () => placeholder,
      error: (_, __) => error,
      data: (media) => CachedNetworkImage(
        imageUrl: imageUrl,
        fit: fit,
        width: width,
        height: height,
        cacheManager: BookScopedCacheManager(
          store: media.store,
          bookId: bookId,
          fileExtension: 'img',
        ),
        placeholder: (_, __) => placeholder,
        errorWidget: (_, __, ___) => error,
      ),
    );
  }
}
