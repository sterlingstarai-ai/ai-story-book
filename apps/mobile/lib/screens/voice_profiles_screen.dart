import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../utils/constants.dart';

class VoiceProfilesScreen extends ConsumerStatefulWidget {
  const VoiceProfilesScreen({super.key});

  @override
  ConsumerState<VoiceProfilesScreen> createState() =>
      _VoiceProfilesScreenState();
}

class _VoiceProfilesScreenState extends ConsumerState<VoiceProfilesScreen> {
  bool _isLoading = true;
  bool _isSubmitting = false;
  String? _errorMessage;
  List<Map<String, dynamic>> _profiles = const [];

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
      final data = await api.getVoiceProfiles();
      final raw = data['profiles'];
      final profiles = <Map<String, dynamic>>[];
      if (raw is List) {
        for (final item in raw) {
          if (item is Map) {
            profiles.add(Map<String, dynamic>.from(item));
          }
        }
      }

      if (!mounted) {
        return;
      }
      setState(() {
        _profiles = profiles;
        _errorMessage = null;
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = AppLocalizations.of(context).voiceProfilesLoadError;
        _isLoading = false;
      });
    }
  }

  Future<Map<String, dynamic>?> _showProfileDialog({
    Map<String, dynamic>? initial,
  }) async {
    final l = AppLocalizations.of(context);
    final formKey = GlobalKey<FormState>();
    final labelController = TextEditingController(
      text: initial?['label']?.toString() ?? '',
    );
    final relationshipController = TextEditingController(
      text: initial?['relationship']?.toString() ?? '',
    );
    final sampleUrlController = TextEditingController(
      text: initial?['sample_audio_url']?.toString() ?? '',
    );
    var consented = initial?['consented'] == true;
    var active = initial?['active'] != false;
    var isUploadingSample = false;

    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: Text(initial == null
                  ? l.voiceProfilesAddTitle
                  : l.voiceProfilesEditTitle),
              content: Form(
                key: formKey,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextFormField(
                        controller: labelController,
                        maxLength: 40,
                        decoration: InputDecoration(
                          labelText: l.voiceProfilesLabelFieldLabel,
                          hintText: l.voiceProfilesLabelFieldHint,
                        ),
                        validator: (value) {
                          final text = value?.trim() ?? '';
                          if (text.isEmpty) {
                            return l.voiceProfilesLabelRequired;
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      TextFormField(
                        controller: relationshipController,
                        maxLength: 30,
                        decoration: InputDecoration(
                          labelText: l.voiceProfilesRelationshipFieldLabel,
                          hintText: l.voiceProfilesRelationshipFieldHint,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      TextFormField(
                        controller: sampleUrlController,
                        maxLength: 500,
                        decoration: InputDecoration(
                          labelText: l.voiceProfilesSampleUrlFieldLabel,
                          hintText: 'https://...',
                        ),
                        validator: (value) {
                          final text = value?.trim() ?? '';
                          if (text.isEmpty) {
                            return l.voiceProfilesSampleUrlRequired;
                          }
                          final uri = Uri.tryParse(text);
                          if (uri == null ||
                              !uri.hasScheme ||
                              !uri.hasAuthority) {
                            return l.voiceProfilesSampleUrlInvalid;
                          }
                          return null;
                        },
                      ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: OutlinedButton.icon(
                          onPressed: isUploadingSample
                              ? null
                              : () async {
                                  final picked =
                                      await FilePicker.platform.pickFiles(
                                    type: FileType.custom,
                                    allowMultiple: false,
                                    allowedExtensions: const [
                                      'm4a',
                                      'mp3',
                                      'wav',
                                      'aac',
                                      'ogg',
                                      'webm',
                                    ],
                                  );
                                  if (picked == null ||
                                      picked.files.isEmpty ||
                                      picked.files.first.path == null) {
                                    return;
                                  }

                                  setDialogState(
                                      () => isUploadingSample = true);
                                  try {
                                    final file = File(picked.files.first.path!);
                                    final uploaded = await ref
                                        .read(apiClientProvider)
                                        .uploadVoiceSample(
                                          file,
                                          fileName: picked.files.first.name,
                                        );
                                    final url = uploaded['sample_audio_url']
                                        ?.toString();
                                    if (url != null && url.isNotEmpty) {
                                      sampleUrlController.text = url;
                                    }
                                    if (mounted) {
                                      ScaffoldMessenger.of(this.context)
                                          .showSnackBar(
                                        SnackBar(
                                          content: Text(l
                                              .voiceProfilesSampleUploadSuccess),
                                        ),
                                      );
                                    }
                                  } catch (_) {
                                    if (mounted) {
                                      ScaffoldMessenger.of(this.context)
                                          .showSnackBar(
                                        SnackBar(
                                          content: Text(
                                              l.voiceProfilesSampleUploadError),
                                        ),
                                      );
                                    }
                                  } finally {
                                    if (mounted) {
                                      setDialogState(
                                          () => isUploadingSample = false);
                                    }
                                  }
                                },
                          icon: isUploadingSample
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.upload_file),
                          label: Text(
                            isUploadingSample
                                ? l.voiceProfilesUploading
                                : l.voiceProfilesUploadAudioButton,
                          ),
                        ),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(l.voiceProfilesConsentToggle),
                        value: consented,
                        onChanged: (value) {
                          setDialogState(() => consented = value);
                        },
                      ),
                      if (initial != null)
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(l.voiceProfilesActiveToggle),
                          value: active,
                          onChanged: (value) {
                            setDialogState(() => active = value);
                          },
                        ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: Text(l.voiceProfilesCancel),
                ),
                FilledButton(
                  onPressed: () {
                    if (!formKey.currentState!.validate()) {
                      return;
                    }
                    Navigator.pop(
                      context,
                      {
                        'label': labelController.text.trim(),
                        'relationship': relationshipController.text.trim(),
                        'sample_audio_url': sampleUrlController.text.trim(),
                        'consented': consented,
                        'active': active,
                      },
                    );
                  },
                  child: Text(initial == null
                      ? l.voiceProfilesAdd
                      : l.voiceProfilesSave),
                ),
              ],
            );
          },
        );
      },
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      labelController.dispose();
      relationshipController.dispose();
      sampleUrlController.dispose();
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
      await api.createVoiceProfile(
        label: draft['label'].toString(),
        relationship: _normalizeNullableText(draft['relationship']),
        sampleAudioUrl: draft['sample_audio_url'].toString(),
        consented: draft['consented'] == true,
      );
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content:
                Text(AppLocalizations.of(context).voiceProfilesCreateError)),
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
      await api.updateVoiceProfile(
        profile['id'].toString(),
        label: draft['label'].toString(),
        relationship: _normalizeNullableText(draft['relationship']),
        sampleAudioUrl: draft['sample_audio_url'].toString(),
        consented: draft['consented'] == true,
        active: draft['active'] == true,
      );
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context).voiceProfilesEditError)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _revokeConsent(String profileId) async {
    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.revokeVoiceProfileConsent(profileId);
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content:
                Text(AppLocalizations.of(context).voiceProfilesRevokeError)),
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
            title: Text(l.voiceProfilesDeleteTitle),
            content: Text(l.voiceProfilesDeleteConfirm),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(l.voiceProfilesCancel),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                style: FilledButton.styleFrom(backgroundColor: AppColors.error),
                child: Text(l.voiceProfilesDelete),
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
      await api.deleteVoiceProfile(profileId);
      await _load(showLoading: false);
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content:
                Text(AppLocalizations.of(context).voiceProfilesDeleteError)),
      );
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  String? _normalizeNullableText(dynamic value) {
    final text = value?.toString().trim() ?? '';
    if (text.isEmpty) {
      return null;
    }
    return text;
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l.voiceProfilesTitle),
        actions: [
          IconButton(
            onPressed: _isSubmitting ? null : _createProfile,
            icon: const Icon(Icons.add),
            tooltip: l.voiceProfilesAddTooltip,
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
                        Center(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                                horizontal: AppSpacing.lg),
                            child: Text(
                              l.voiceProfilesEmpty,
                              textAlign: TextAlign.center,
                              style: AppTextStyles.bodySmall,
                            ),
                          ),
                        ),
                      ],
                    )
                  : ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(AppSpacing.md),
                      itemBuilder: (context, index) {
                        final profile = _profiles[index];
                        final label = profile['label']?.toString() ??
                            l.voiceProfilesUnnamed;
                        final relationship =
                            profile['relationship']?.toString() ?? '-';
                        final consented = profile['consented'] == true;
                        final active = profile['active'] == true;
                        final profileId = profile['id'].toString();

                        return Container(
                          padding: const EdgeInsets.all(AppSpacing.md),
                          decoration: BoxDecoration(
                            color: AppColors.surface,
                            borderRadius: BorderRadius.circular(AppRadius.md),
                            border: Border.all(color: AppColors.divider),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      label,
                                      style: AppTextStyles.heading3,
                                    ),
                                  ),
                                  PopupMenuButton<String>(
                                    tooltip: l.voiceProfilesMenuTooltip,
                                    onSelected: (value) {
                                      if (value == 'edit') {
                                        _editProfile(profile);
                                        return;
                                      }
                                      if (value == 'revoke') {
                                        _revokeConsent(profileId);
                                        return;
                                      }
                                      if (value == 'delete') {
                                        _deleteProfile(profileId);
                                      }
                                    },
                                    itemBuilder: (context) => [
                                      PopupMenuItem(
                                        value: 'edit',
                                        child: Text(l.voiceProfilesMenuEdit),
                                      ),
                                      PopupMenuItem(
                                        value: 'revoke',
                                        child: Text(l.voiceProfilesMenuRevoke),
                                      ),
                                      PopupMenuItem(
                                        value: 'delete',
                                        child: Text(l.voiceProfilesMenuDelete),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                              const SizedBox(height: AppSpacing.xs),
                              Text(
                                  l.voiceProfilesRelationshipPrefix(
                                      relationship),
                                  style: AppTextStyles.bodySmall),
                              const SizedBox(height: AppSpacing.xs),
                              Row(
                                children: [
                                  _StateChip(
                                    text: consented
                                        ? l.voiceProfilesConsentDone
                                        : l.voiceProfilesConsentNeeded,
                                    ok: consented,
                                  ),
                                  const SizedBox(width: AppSpacing.sm),
                                  _StateChip(
                                    text: active
                                        ? l.voiceProfilesActive
                                        : l.voiceProfilesInactive,
                                    ok: active,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        );
                      },
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: AppSpacing.sm),
                      itemCount: _profiles.length,
                    ),
            ),
      bottomNavigationBar: _errorMessage == null
          ? null
          : SafeArea(
              child: Container(
                color: AppColors.error.withValues(alpha: 0.08),
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Text(
                  _errorMessage!,
                  style:
                      AppTextStyles.bodySmall.copyWith(color: AppColors.error),
                ),
              ),
            ),
    );
  }
}

class _StateChip extends StatelessWidget {
  const _StateChip({
    required this.text,
    required this.ok,
  });

  final String text;
  final bool ok;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: ok ? AppColors.successLight : AppColors.blackOverlayLight,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: AppTextStyles.caption.copyWith(
          color: AppColors.textPrimary,
        ),
      ),
    );
  }
}
