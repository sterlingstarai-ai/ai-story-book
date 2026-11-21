import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';
import '../widgets/age_gate_dialog.dart';

class ProfilesScreen extends ConsumerStatefulWidget {
  const ProfilesScreen({super.key});

  @override
  ConsumerState<ProfilesScreen> createState() => _ProfilesScreenState();
}

class _ProfilesScreenState extends ConsumerState<ProfilesScreen> {
  static const List<String> _ageBandValues = ['3-5', '5-7', '7-9', 'adult'];

  static String _ageBandLabel(AppLocalizations l, String? value) {
    switch (value) {
      case '3-5':
        return l.profilesAgeBand35;
      case '5-7':
        return l.profilesAgeBand57;
      case '7-9':
        return l.profilesAgeBand79;
      case 'adult':
        return l.profilesAgeBandAdult;
    }
    return value ?? '-';
  }

  // 생년월을 입력하면 연령대를 실제 나이에서 파생(부모 임의선택 제거). 서버가 권위적으로
  // 재파생하지만, 클라에서도 같은 규칙으로 미리보기·잠금한다(반열린 구간).
  static List<int> _birthYearOptions() {
    final now = DateTime.now().year;
    return [for (var y = now; y >= now - 12; y--) y];
  }

  static String _deriveAgeBand(int year, int month) {
    final now = DateTime.now();
    final months = (now.year - year) * 12 + (now.month - month);
    final age = months ~/ 12;
    if (age < 5) return '3-5';
    if (age < 7) return '5-7';
    return '7-9';
  }

  bool _isLoading = true;
  bool _isSubmitting = false;
  String? _errorMessage;
  List<Map<String, dynamic>> _profiles = const [];
  String? _activeProfileId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool showLoading = true}) async {
    if (showLoading) {
      setState(() => _isLoading = true);
    }
    try {
      final api = ref.read(apiClientProvider);
      final data = await api.getProfiles();
      final profiles = _asProfileList(data['profiles']);
      final userService = ref.read(userServiceProvider);
      var activeProfileId = userService.getActiveProfileId();
      final exists =
          profiles.any((p) => p['id']?.toString() == activeProfileId);
      if (!exists) {
        Map<String, dynamic>? fallback;
        for (final profile in profiles) {
          if (profile['is_default'] == true) {
            fallback = profile;
            break;
          }
        }
        fallback ??= profiles.isNotEmpty ? profiles.first : null;
        final fallbackId = fallback?['id']?.toString();
        await userService.setActiveProfileId(fallbackId);
        activeProfileId = fallbackId;
        ref.invalidate(apiClientProvider);
      }
      if (!mounted) {
        return;
      }
      setState(() {
        _profiles = profiles;
        _activeProfileId = activeProfileId;
        _errorMessage = null;
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = AppLocalizations.of(context).profilesLoadError;
        _isLoading = false;
      });
    }
  }

  List<Map<String, dynamic>> _asProfileList(dynamic value) {
    if (value is List) {
      return value
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }
    return <Map<String, dynamic>>[];
  }

  Future<Map<String, dynamic>?> _showProfileDialog({
    Map<String, dynamic>? initial,
  }) async {
    final l = AppLocalizations.of(context);
    final formKey = GlobalKey<FormState>();
    var name = initial?['name']?.toString() ?? '';
    var selectedAgeBand = initial?['age_band']?.toString() ?? '5-7';
    int? selectedBirthYear = (initial?['birth_year'] as num?)?.toInt();
    int? selectedBirthMonth = (initial?['birth_month'] as num?)?.toInt();
    var isDefault = initial?['is_default'] == true;

    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              scrollable: true,
              title: Text(initial == null
                  ? l.profilesDialogAddTitle
                  : l.profilesDialogEditTitle),
              content: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    TextFormField(
                      initialValue: name,
                      onChanged: (value) => name = value,
                      maxLength: 40,
                      decoration: InputDecoration(
                        labelText: l.profilesNameLabel,
                        hintText: l.profilesNameHint,
                      ),
                      validator: (value) {
                        final text = value?.trim() ?? '';
                        if (text.isEmpty) {
                          return l.profilesNameRequired;
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    // 출생연월(선택) — 입력하면 연령대를 실제 나이에서 자동 파생.
                    Builder(builder: (context) {
                      final fields = [
                        DropdownButtonFormField<int>(
                          initialValue: selectedBirthYear,
                          isExpanded: true,
                          decoration: InputDecoration(
                            labelText: l.profilesBirthYearLabel,
                          ),
                          items: _birthYearOptions()
                              .map((y) => DropdownMenuItem<int>(
                                    value: y,
                                    child: Text(l.profilesYearOption(y)),
                                  ))
                              .toList(),
                          onChanged: (value) {
                            setDialogState(() {
                              selectedBirthYear = value;
                              if (selectedBirthYear != null &&
                                  selectedBirthMonth != null) {
                                selectedAgeBand = _deriveAgeBand(
                                    selectedBirthYear!, selectedBirthMonth!);
                              }
                            });
                          },
                        ),
                        DropdownButtonFormField<int>(
                          initialValue: selectedBirthMonth,
                          isExpanded: true,
                          decoration: InputDecoration(
                              labelText: l.profilesBirthMonthLabel),
                          items: [for (var m = 1; m <= 12; m++) m]
                              .map((m) => DropdownMenuItem<int>(
                                    value: m,
                                    child: Text(l.profilesMonthOption(m)),
                                  ))
                              .toList(),
                          onChanged: (value) {
                            setDialogState(() {
                              selectedBirthMonth = value;
                              if (selectedBirthYear != null &&
                                  selectedBirthMonth != null) {
                                selectedAgeBand = _deriveAgeBand(
                                    selectedBirthYear!, selectedBirthMonth!);
                              }
                            });
                          },
                        )
                      ];
                      if (MediaQuery.sizeOf(context).width < 488 ||
                          MediaQuery.textScalerOf(context).scale(14) > 18) {
                        return Column(children: [
                          fields[0],
                          const SizedBox(height: AppSpacing.md),
                          fields[1]
                        ]);
                      }
                      return Row(children: [
                        Expanded(child: fields[0]),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(child: fields[1])
                      ]);
                    }),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      (selectedBirthYear != null && selectedBirthMonth != null)
                          ? l.profilesAgeBandAuto(selectedAgeBand)
                          : l.profilesBirthHint,
                      style: AppTextStyles.caption.copyWith(
                          color: AppPalette.of(context).textSecondary),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    DropdownButtonFormField<String>(
                      key: ValueKey(selectedAgeBand),
                      isExpanded: true,
                      initialValue: selectedAgeBand,
                      decoration: InputDecoration(
                        labelText: l.profilesAgeBandLabel,
                      ),
                      items: _ageBandValues
                          .map(
                            (option) => DropdownMenuItem<String>(
                              value: option,
                              child: Text(_ageBandLabel(l, option)),
                            ),
                          )
                          .toList(),
                      // 생년월이 둘 다 있으면 자동 파생값으로 잠금(부모 임의선택 방지).
                      onChanged: (selectedBirthYear != null &&
                              selectedBirthMonth != null)
                          ? null
                          : (value) {
                              if (value == null) {
                                return;
                              }
                              setDialogState(() => selectedAgeBand = value);
                            },
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(l.profilesSetAsDefaultSwitch),
                      value: isDefault,
                      onChanged: (value) {
                        setDialogState(() => isDefault = value);
                      },
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(l.profilesCancel),
                ),
                TextButton(
                  onPressed: () {
                    if (!formKey.currentState!.validate()) {
                      return;
                    }
                    Navigator.pop(
                      context,
                      {
                        'name': name.trim(),
                        'age_band': selectedAgeBand,
                        'birth_year': selectedBirthYear,
                        'birth_month': selectedBirthMonth,
                        'is_default': isDefault,
                      },
                    );
                  },
                  child: Text(initial == null
                      ? l.profilesAddAction
                      : l.profilesSaveAction),
                ),
              ],
            );
          },
        );
      },
    );
    return result;
  }

  Future<void> _createProfile() async {
    final draft = await _showProfileDialog();
    if (draft == null || !mounted) {
      return;
    }
    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.createProfile(
        name: draft['name'].toString(),
        ageBand: draft['age_band'].toString(),
        birthYear: (draft['birth_year'] as num?)?.toInt(),
        birthMonth: (draft['birth_month'] as num?)?.toInt(),
        isDefault: draft['is_default'] == true,
      );
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).profilesCreateFailed)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _editProfile(Map<String, dynamic> profile) async {
    final draft = await _showProfileDialog(initial: profile);
    if (draft == null || !mounted) {
      return;
    }

    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.updateProfile(
        profile['id'].toString(),
        name: draft['name'].toString(),
        ageBand: draft['age_band'].toString(),
        birthYear: (draft['birth_year'] as num?)?.toInt(),
        birthMonth: (draft['birth_month'] as num?)?.toInt(),
        isDefault: draft['is_default'] == true,
      );
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).profilesEditFailed)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _setDefaultProfile(String profileId) async {
    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.updateProfile(profileId, isDefault: true);
      await _setActiveProfile(profileId, syncServerDefault: false);
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content:
                Text(AppLocalizations.of(context).profilesSetDefaultFailed)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _deleteProfile(String profileId) async {
    final l = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(l.profilesDeleteTitle),
            content: Text(l.profilesDeleteConfirm),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.profilesCancel),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(l.profilesDeleteAction),
              ),
            ],
          ),
        ) ??
        false;
    if (!confirmed || !mounted) {
      return;
    }

    if (!await showAgeGateDialog(context, ref) || !mounted) return;

    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.deleteProfile(profileId);
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).profilesDeleteFailed)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _activateProfile(String profileId) async {
    if (_isSubmitting) return;
    setState(() => _isSubmitting = true);
    try {
      await _setActiveProfile(profileId);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content:
                  Text(AppLocalizations.of(context).profilesSetDefaultFailed)),
        );
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  Future<void> _setActiveProfile(
    String profileId, {
    bool syncServerDefault = true,
  }) async {
    final normalized = profileId.trim();
    if (normalized.isEmpty) {
      return;
    }
    final userService = ref.read(userServiceProvider);
    await userService.setActiveProfileId(normalized);
    ref.invalidate(apiClientProvider);
    if (syncServerDefault) {
      final api = ref.read(apiClientProvider);
      await api.updateProfile(normalized, isDefault: true);
    }
    ref.invalidate(libraryProvider);
    ref.invalidate(libraryBrowseProvider);
    ref.invalidate(homeStreakProvider);
    // 읽기성장·또래비교·주간추이는 프로필 단위 데이터 → 전환 시 무효화(이전 아이 데이터 잔류 방지).
    ref.invalidate(growthReportProvider);
    ref.invalidate(peerComparisonProvider);
    ref.invalidate(weeklyReadingTrendProvider);
    if (!mounted) {
      return;
    }
    setState(() {
      _activeProfileId = normalized;
      if (syncServerDefault) {
        _profiles = _profiles.map((profile) => {
          ...profile,
          'is_default': profile['id']?.toString() == normalized,
        }).toList();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l.profilesTitle),
        actions: [
          IconButton(
            onPressed: _isSubmitting || _isLoading || _errorMessage != null
                ? null
                : _createProfile,
            icon: const Icon(Icons.add),
            tooltip: l.profilesAddTooltip,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: () => _load(showLoading: false),
              child: _profiles.isEmpty
                  ? ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        const SizedBox(height: 120),
                        Icon(
                          Icons.child_care_outlined,
                          size: 72,
                          color: AppPalette.of(context).textHint,
                        ),
                        const SizedBox(height: AppSpacing.md),
                        Padding(
                          padding: const EdgeInsets.symmetric(
                              horizontal: AppSpacing.lg),
                          child: Text(
                            _errorMessage ?? l.profilesEmpty,
                            textAlign: TextAlign.center,
                            style: AppTextStyles.body,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.lg),
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.lg,
                          ),
                          child: ElevatedButton(
                            style: ElevatedButton.styleFrom(
                                minimumSize: const Size(64, 64)),
                            onPressed: _isSubmitting
                                ? null
                                : _errorMessage != null
                                    ? _load
                                    : _createProfile,
                            child: Text(_errorMessage != null
                                ? l.retry
                                : l.profilesCreateFirst),
                          ),
                        ),
                      ],
                    )
                  : ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      itemCount: _profiles.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final profile = _profiles[index];
                        final profileId = profile['id']?.toString() ?? '';
                        final isDefault = profile['is_default'] == true;
                        final isActive = _activeProfileId == profileId;

                        return ListTile(
                          minVerticalPadding: AppSpacing.md,
                          selected: isActive,
                          selectedTileColor:
                              AppPalette.of(context).primaryLight,
                          onTap: _isSubmitting || profileId.isEmpty
                              ? null
                              : () => _activateProfile(profileId),
                          leading: CircleAvatar(
                            child: Text(
                              (profile['name']?.toString().isNotEmpty ?? false)
                                  ? profile['name'].toString().characters.first
                                  : '?',
                            ),
                          ),
                          title: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(profile['name']?.toString() ?? '-'),
                              const SizedBox(height: AppSpacing.xs),
                              Wrap(
                                spacing: AppSpacing.xs,
                                runSpacing: AppSpacing.xs,
                                children: [
                                  if (isDefault)
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 8,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color:
                                            AppPalette.of(context).primaryLight,
                                        borderRadius:
                                            BorderRadius.circular(999),
                                      ),
                                      child: Text(
                                        l.profilesDefaultBadge,
                                        style: AppTextStyles.caption,
                                      ),
                                    ),
                                  if (isActive) ...[
                                    const SizedBox(width: AppSpacing.xs),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 8,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: AppColors.successLight,
                                        borderRadius:
                                            BorderRadius.circular(999),
                                      ),
                                      child: Text(
                                        l.profilesActiveBadge,
                                        style: AppTextStyles.caption,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ],
                          ),
                          subtitle: Text(
                            l.profilesAgeBandValue(_ageBandLabel(
                                l, profile['age_band']?.toString())),
                          ),
                          trailing: PopupMenuButton<String>(
                            enabled: !_isSubmitting,
                            tooltip: l.profilesMenuEdit,
                            style: IconButton.styleFrom(
                              minimumSize: const Size(64, 64),
                            ),
                            onSelected: (value) {
                              switch (value) {
                                case 'activate':
                                  _activateProfile(profileId);
                                  break;
                                case 'default':
                                  _setDefaultProfile(profileId);
                                  break;
                                case 'edit':
                                  _editProfile(profile);
                                  break;
                                case 'delete':
                                  _deleteProfile(profileId);
                                  break;
                              }
                            },
                            itemBuilder: (context) => [
                              if (!isActive)
                                PopupMenuItem<String>(
                                  value: 'activate',
                                  child: Text(l.profilesMenuActivate),
                                ),
                              if (!isDefault)
                                PopupMenuItem<String>(
                                  value: 'default',
                                  child: Text(l.profilesMenuSetDefault),
                                ),
                              PopupMenuItem<String>(
                                value: 'edit',
                                child: Text(l.profilesMenuEdit),
                              ),
                              PopupMenuItem<String>(
                                value: 'delete',
                                child: Text(l.profilesDeleteAction),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
    );
  }
}
