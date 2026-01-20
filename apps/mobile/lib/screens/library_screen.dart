import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';
import 'home_screen.dart';

/// 서재 화면
class LibraryScreen extends ConsumerWidget {
  const LibraryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final libraryAsync = ref.watch(libraryProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        elevation: 0,
        title: const Text('내 서재', style: AppTextStyles.heading2),
        centerTitle: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: AppColors.textPrimary),
            onPressed: () => ref.read(libraryProvider.notifier).refresh(),
          ),
        ],
      ),
      body: libraryAsync.when(
        data: (books) {
          if (books.isEmpty) {
            return EmptyState(
              icon: Icons.auto_stories_outlined,
              title: '아직 만든 책이 없어요',
              subtitle: '첫 번째 동화책을 만들어보세요!',
              buttonText: '새 책 만들기',
              onButtonPressed: () => Navigator.pushNamed(context, '/create'),
            );
          }

          return RefreshIndicator(
            onRefresh: () => ref.read(libraryProvider.notifier).refresh(),
            child: GridView.builder(
              padding: const EdgeInsets.all(AppSpacing.lg),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: AppSpacing.md,
                crossAxisSpacing: AppSpacing.md,
                childAspectRatio: 0.65,
              ),
              itemCount: books.length,
              itemBuilder: (context, index) {
                final book = books[index];
                return BookCard(
                  title: book.title,
                  imageUrl: book.coverImageUrl,
                  subtitle: _formatDate(book.createdAt),
                  onTap: () => Navigator.pushNamed(
                    context,
                    '/viewer',
                    arguments: book.id,
                  ),
                );
              },
            ),
          );
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => EmptyState(
          icon: Icons.error_outline,
          title: '책을 불러올 수 없어요',
          subtitle: error.toString(),
          buttonText: '다시 시도',
          onButtonPressed: () => ref.invalidate(libraryProvider),
        ),
      ),
      bottomNavigationBar: const _LibraryBottomNavBar(),
    );
  }

  String _formatDate(DateTime date) {
    final now = DateTime.now();
    final diff = now.difference(date);

    if (diff.inDays == 0) {
      return '오늘';
    } else if (diff.inDays == 1) {
      return '어제';
    } else if (diff.inDays < 7) {
      return '${diff.inDays}일 전';
    } else {
      return '${date.month}월 ${date.day}일';
    }
  }
}

class _LibraryBottomNavBar extends StatelessWidget {
  const _LibraryBottomNavBar();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.05),
            blurRadius: 10,
            offset: const Offset(0, -4),
          ),
        ],
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _NavItem(
                icon: Icons.home_rounded,
                label: '홈',
                isSelected: false,
                onTap: () => Navigator.pushReplacementNamed(context, '/'),
              ),
              _NavItem(
                icon: Icons.add_circle_rounded,
                label: '만들기',
                isSelected: false,
                onTap: () => Navigator.pushNamed(context, '/create'),
              ),
              _NavItem(
                icon: Icons.auto_stories_rounded,
                label: '서재',
                isSelected: true,
                onTap: () {},
              ),
              _NavItem(
                icon: Icons.people_rounded,
                label: '캐릭터',
                isSelected: false,
                onTap: () => Navigator.pushReplacementNamed(context, '/characters'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  const _NavItem({
    required this.icon,
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = isSelected ? AppColors.primary : AppColors.textHint;

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: color, size: 24),
            const SizedBox(height: AppSpacing.xs),
            Text(
              label,
              style: TextStyle(
                fontSize: 12,
                color: color,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
