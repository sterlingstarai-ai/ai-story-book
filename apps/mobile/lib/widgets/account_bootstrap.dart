import 'package:flutter/material.dart';

import '../l10n/app_localizations.dart';
import '../utils/app_theme.dart';

/// 계정 접근에 실패해도 새 계정을 만들지 않고 같은 부트스트랩을 재시도한다.
class AccountBootstrap extends StatefulWidget {
  const AccountBootstrap({
    super.key,
    required this.initialize,
    required this.child,
    this.onRestore,
  });

  final Future<void> Function() initialize;
  final Widget child;
  final Future<bool> Function(BuildContext context)? onRestore;

  @override
  State<AccountBootstrap> createState() => _AccountBootstrapState();
}

class _AccountBootstrapState extends State<AccountBootstrap> {
  bool _loading = true;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    setState(() => _loading = true);
    try {
      await widget.initialize();
      if (mounted) setState(() => _ready = true);
    } catch (_) {
      // 오류 원문에 플랫폼 자격증명 정보가 포함될 수 있어 화면·로그에 노출하지 않는다.
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_ready) return widget.child;
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      theme: buildAppTheme(Brightness.light),
      darkTheme: buildAppTheme(Brightness.dark),
      home: Builder(builder: (context) {
        final l = AppLocalizations.of(context);
        return Scaffold(
          body: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: _loading
                    ? CircularProgressIndicator(
                        semanticsLabel: l.accountOpening)
                    : Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(l.accountUnavailableTitle,
                              style: Theme.of(context).textTheme.headlineSmall),
                          const SizedBox(height: 16),
                          Text(l.accountUnavailableMessage),
                          const SizedBox(height: 24),
                          FilledButton(
                            style: FilledButton.styleFrom(
                              minimumSize: const Size(160, 64),
                              backgroundColor: const Color(0xFF4F46E5),
                            ),
                            onPressed: _initialize,
                            child: Text(l.accountRetry),
                          ),
                          if (widget.onRestore != null) ...[
                            const SizedBox(height: 16),
                            TextButton(
                                onPressed: () async {
                                  final recovered =
                                      await widget.onRestore!(context);
                                  if (mounted && recovered) await _initialize();
                                },
                                child: Text(l.recoveryRestoreTitle)),
                          ],
                        ],
                      ),
              ),
            ),
          ),
        );
      }),
    );
  }
}
