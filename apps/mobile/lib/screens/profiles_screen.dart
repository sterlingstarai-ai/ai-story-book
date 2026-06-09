import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/providers.dart';
import '../utils/constants.dart';

class ProfilesScreen extends ConsumerStatefulWidget {
  const ProfilesScreen({super.key});

  @override
  ConsumerState<ProfilesScreen> createState() => _ProfilesScreenState();
}

class _ProfilesScreenState extends ConsumerState<ProfilesScreen> {
  static const List<Map<String, String>> _ageBandOptions = [
    {'value': '3-5', 'label': '3-5세'},
    {'value': '5-7', 'label': '5-7세'},
    {'value': '7-9', 'label': '7-9세'},
    {'value': 'adult', 'label': '성인'},
  ];

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
        _errorMessage = '프로필 정보를 불러오지 못했어요.';
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
    final formKey = GlobalKey<FormState>();
    final nameController = TextEditingController(
      text: initial?['name']?.toString() ?? '',
    );
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
              title: Text(initial == null ? '프로필 추가' : '프로필 수정'),
              content: SingleChildScrollView(
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextFormField(
                        controller: nameController,
                        maxLength: 40,
                        decoration: const InputDecoration(
                          labelText: '이름',
                          hintText: '예: 민지',
                        ),
                        validator: (value) {
                          final text = value?.trim() ?? '';
                          if (text.isEmpty) {
                            return '이름을 입력해주세요.';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      // 출생연월(선택) — 입력하면 연령대를 실제 나이에서 자동 파생.
                      Row(
                        children: [
                          Expanded(
                            child: DropdownButtonFormField<int>(
                              initialValue: selectedBirthYear,
                              isExpanded: true,
                              decoration: const InputDecoration(
                                labelText: '출생연도(선택)',
                              ),
                              items: _birthYearOptions()
                                  .map((y) => DropdownMenuItem<int>(
                                        value: y,
                                        child: Text('$y년'),
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
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          Expanded(
                            child: DropdownButtonFormField<int>(
                              initialValue: selectedBirthMonth,
                              isExpanded: true,
                              decoration: const InputDecoration(labelText: '월'),
                              items: [for (var m = 1; m <= 12; m++) m]
                                  .map((m) => DropdownMenuItem<int>(
                                        value: m,
                                        child: Text('$m월'),
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
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        (selectedBirthYear != null &&
                                selectedBirthMonth != null)
                            ? '연령대 자동: $selectedAgeBand세'
                            : '출생연월을 입력하면 연령대가 자동 설정돼요(선택).',
                        style: const TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      DropdownButtonFormField<String>(
                        initialValue: selectedAgeBand,
                        decoration: const InputDecoration(
                          labelText: '연령대',
                        ),
                        items: _ageBandOptions
                            .map(
                              (option) => DropdownMenuItem<String>(
                                value: option['value'],
                                child:
                                    Text(option['label'] ?? option['value']!),
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
                        title: const Text('기본 프로필로 설정'),
                        value: isDefault,
                        onChanged: (value) {
                          setDialogState(() => isDefault = value);
                        },
                      ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('취소'),
                ),
                TextButton(
                  onPressed: () {
                    if (!formKey.currentState!.validate()) {
                      return;
                    }
                    Navigator.pop(
                      context,
                      {
                        'name': nameController.text.trim(),
                        'age_band': selectedAgeBand,
                        'birth_year': selectedBirthYear,
                        'birth_month': selectedBirthMonth,
                        'is_default': isDefault,
                      },
                    );
                  },
                  child: Text(initial == null ? '추가' : '저장'),
                ),
              ],
            );
          },
        );
      },
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {
      nameController.dispose();
    });
    return result;
  }

  Future<void> _createProfile() async {
    final draft = await _showProfileDialog();
    if (draft == null) {
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
        const SnackBar(content: Text('프로필 생성에 실패했어요. 잠시 후 다시 시도해주세요.')),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _editProfile(Map<String, dynamic> profile) async {
    final draft = await _showProfileDialog(initial: profile);
    if (draft == null) {
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
        const SnackBar(content: Text('프로필 수정에 실패했어요.')),
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
        const SnackBar(content: Text('기본 프로필 설정에 실패했어요.')),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _deleteProfile(String profileId) async {
    final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('프로필 삭제'),
            content: const Text('이 프로필을 삭제할까요?'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('취소'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('삭제'),
              ),
            ],
          ),
        ) ??
        false;
    if (!confirmed) {
      return;
    }

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
        const SnackBar(content: Text('프로필 삭제에 실패했어요.')),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  String _ageLabel(String? value) {
    for (final option in _ageBandOptions) {
      if (option['value'] == value) {
        return option['label'] ?? value ?? '-';
      }
    }
    return value ?? '-';
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
    setState(() => _activeProfileId = normalized);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('아이 프로필'),
        actions: [
          IconButton(
            onPressed: _isSubmitting ? null : _createProfile,
            icon: const Icon(Icons.add),
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
                        const Icon(
                          Icons.child_care_outlined,
                          size: 72,
                          color: AppColors.textHint,
                        ),
                        const SizedBox(height: AppSpacing.md),
                        const Center(
                          child: Text(
                            '등록된 프로필이 없어요',
                            style: AppTextStyles.body,
                          ),
                        ),
                        if (_errorMessage != null) ...[
                          const SizedBox(height: AppSpacing.sm),
                          Center(
                            child: Text(
                              _errorMessage!,
                              style: AppTextStyles.caption
                                  .copyWith(color: AppColors.error),
                            ),
                          ),
                        ],
                        const SizedBox(height: AppSpacing.lg),
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppSpacing.lg,
                          ),
                          child: ElevatedButton(
                            onPressed: _isSubmitting ? null : _createProfile,
                            child: const Text('첫 프로필 만들기'),
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
                          onTap: _isSubmitting || profileId.isEmpty
                              ? null
                              : () => _setActiveProfile(profileId),
                          leading: CircleAvatar(
                            child: Text(
                              (profile['name']?.toString().isNotEmpty ?? false)
                                  ? profile['name'].toString()[0]
                                  : '?',
                            ),
                          ),
                          title: Row(
                            children: [
                              Expanded(
                                child: Text(profile['name']?.toString() ?? '-'),
                              ),
                              if (isDefault)
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 2,
                                  ),
                                  decoration: BoxDecoration(
                                    color: AppColors.primaryLight,
                                    borderRadius: BorderRadius.circular(999),
                                  ),
                                  child: const Text(
                                    '기본',
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
                                    borderRadius: BorderRadius.circular(999),
                                  ),
                                  child: const Text(
                                    '현재',
                                    style: AppTextStyles.caption,
                                  ),
                                ),
                              ],
                            ],
                          ),
                          subtitle: Text(
                            '연령대: ${_ageLabel(profile['age_band']?.toString())}',
                          ),
                          trailing: PopupMenuButton<String>(
                            onSelected: (value) {
                              switch (value) {
                                case 'activate':
                                  _setActiveProfile(profileId);
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
                                const PopupMenuItem<String>(
                                  value: 'activate',
                                  child: Text('현재 프로필로 사용'),
                                ),
                              if (!isDefault)
                                const PopupMenuItem<String>(
                                  value: 'default',
                                  child: Text('기본 프로필로 설정'),
                                ),
                              const PopupMenuItem<String>(
                                value: 'edit',
                                child: Text('수정'),
                              ),
                              const PopupMenuItem<String>(
                                value: 'delete',
                                child: Text('삭제'),
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
