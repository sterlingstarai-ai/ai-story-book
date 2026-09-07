import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../l10n/app_localizations.dart';
import '../providers/active_child_profile.dart';

/// Keep account scope visible where parents start a new book or choose a hero.
class ActiveChildButton extends ConsumerWidget {
  const ActiveChildButton({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(activeChildProfileProvider).valueOrNull;
    final l = AppLocalizations.of(context);
    return TextButton.icon(
      style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
      onPressed: () async {
        await Navigator.pushNamed(context, '/profiles');
        if (context.mounted) ref.invalidate(activeChildProfileProvider);
      },
      icon: const Icon(Icons.child_care_outlined),
      label: Text(
        profile == null ? l.profilesTitle : l.activeChildLabel(profile.name),
      ),
    );
  }
}
