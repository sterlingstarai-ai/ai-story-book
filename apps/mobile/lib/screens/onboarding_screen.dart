import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

typedef _Slide = ({IconData icon, String title, String subtitle});

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final PageController _controller = PageController();
  int _page = 0;

  static const _icons = [
    Icons.auto_stories,
    Icons.face_retouching_natural,
    Icons.local_fire_department,
    Icons.card_giftcard,
  ];

  List<_Slide> _slides(AppLocalizations l) => [
        (
          icon: _icons[0],
          title: l.onboardingSlide1Title,
          subtitle: l.onboardingSlide1Subtitle,
        ),
        (
          icon: _icons[1],
          title: l.onboardingSlide2Title,
          subtitle: l.onboardingSlide2Subtitle,
        ),
        (
          icon: _icons[2],
          title: l.onboardingSlide3Title,
          subtitle: l.onboardingSlide3Subtitle,
        ),
        (
          icon: _icons[3],
          title: l.onboardingSlide4Title,
          subtitle: l.onboardingSlide4Subtitle,
        ),
      ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    final prefs = ref.read(sharedPreferencesProvider);
    final parental = ref.read(parentalControlServiceProvider);
    await parental.setOnboardingDone(prefs, true);

    if (!mounted) {
      return;
    }
    Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final slides = _slides(l);
    final isLast = _page == slides.length - 1;

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _finish,
                child: Text(l.onboardingSkip),
              ),
            ),
            Expanded(
              child: PageView.builder(
                controller: _controller,
                onPageChanged: (index) => setState(() => _page = index),
                itemCount: slides.length,
                itemBuilder: (context, index) {
                  final slide = slides[index];
                  // R4: iOS 최대 접근성 글자 크기(AX5)에서 이 Column이 고정 높이를
                  // 넘겨 'BOTTOM OVERFLOWED BY 82 PIXELS'가 났다(release 빌드에서는
                  // 배너 없이 조용히 잘린다). 스크롤 가능 구조로 바꾸되, 공간이
                  // 남을 때의 세로 중앙 정렬은 minHeight로 유지한다.
                  return LayoutBuilder(
                    builder: (context, constraints) {
                      return SingleChildScrollView(
                        padding: const EdgeInsets.all(AppSpacing.xl),
                        child: ConstrainedBox(
                          constraints: BoxConstraints(
                            minHeight: constraints.maxHeight - AppSpacing.xl * 2,
                          ),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                slide.icon,
                                size: 120,
                                color: AppColors.primary,
                              ),
                              const SizedBox(height: AppSpacing.xl),
                              Text(
                                slide.title,
                                style: AppTextStyles.heading1,
                                textAlign: TextAlign.center,
                              ),
                              const SizedBox(height: AppSpacing.md),
                              Text(
                                slide.subtitle,
                                style: AppTextStyles.bodySmall,
                                textAlign: TextAlign.center,
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  );
                },
              ),
            ),
            // 페이지 위치를 스크린리더가 읽도록 의미 라벨 부여(점들은 장식적).
            Semantics(
              label: l.onboardingPageIndicator(_page + 1, slides.length),
              container: true,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(
                  slides.length,
                  (index) => AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    width: _page == index ? 20 : 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: _page == index
                          ? AppColors.primary
                          : AppColors.divider,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: SizedBox(
                width: double.infinity,
                height: 64,
                child: ElevatedButton(
                  onPressed: () {
                    if (isLast) {
                      _finish();
                      return;
                    }
                    _controller.nextPage(
                      duration: const Duration(milliseconds: 250),
                      curve: Curves.easeInOut,
                    );
                  },
                  child: Text(isLast ? l.onboardingStart : l.onboardingNext),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
          ],
        ),
      ),
    );
  }
}
