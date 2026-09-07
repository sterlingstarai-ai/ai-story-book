import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/book_spec.dart';
import 'providers.dart';

class ActiveChildProfile {
  const ActiveChildProfile({
    required this.id,
    required this.name,
    required this.targetAge,
  });

  final String id;
  final String name;
  final TargetAge targetAge;
}

/// Defaults only: the parent can edit or clear them before creating a story.
/// Never borrow another child's data when the selected profile is unavailable.
final activeChildProfileProvider = FutureProvider<ActiveChildProfile?>((
  ref,
) async {
  final user = ref.watch(userServiceProvider);
  final profileId = user.getActiveProfileId();
  if (profileId == null) return null;
  final api = ref.watch(apiClientProvider);
  final response = await api.getProfiles();
  if (user.getActiveProfileId() != profileId) return null;
  final profiles = response['profiles'];
  if (profiles is! List) return null;
  for (final profile in profiles.whereType<Map>()) {
    if (profile['id'] != profileId) continue;
    final name = profile['name'];
    if (name is! String) return null;
    for (final age in TargetAge.values) {
      if (age != TargetAge.adult && age.value == profile['age_band']) {
        return ActiveChildProfile(
          id: profileId,
          name: name.trim(),
          targetAge: age,
        );
      }
    }
  }
  return null;
});
