import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../providers/providers.dart';
import '../services/api_client.dart';
import '../utils/constants.dart';
import '../widgets/common_widgets.dart';

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

  bool get _audioSupported => ref.read(capabilitiesProvider).maybeWhen(
        data: (value) => value['audio_supported'] == true,
        orElse: () => false,
      );

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
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _VoiceProfileDialog(initial: initial),
    );
  }

  Future<void> _createProfile() async {
    if (_isSubmitting || !_audioSupported) return;
    final draft = await _showProfileDialog();
    if (draft == null || !mounted || !_audioSupported) {
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
    if (_isSubmitting || !_audioSupported) return;
    final draft = await _showProfileDialog(initial: profile);
    if (draft == null || !mounted || !_audioSupported) {
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
    if (_isSubmitting) return;
    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.revokeVoiceProfileConsent(profileId);
      await _load(showLoading: false);
    } on StoragePurgePending {
      await _showPurgePending();
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
    if (_isSubmitting) return;
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
    if (!confirmed || !mounted) {
      return;
    }

    setState(() => _isSubmitting = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.deleteVoiceProfile(profileId);
      await _load(showLoading: false);
    } on StoragePurgePending {
      await _showPurgePending();
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

  Future<void> _showPurgePending() async {
    await _load(showLoading: false);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text(AppLocalizations.of(context).voiceDeletionPending)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final audioSupported = ref.watch(capabilitiesProvider).maybeWhen(
          data: (value) => value['audio_supported'] == true,
          orElse: () => false,
        );
    return Scaffold(
      appBar: AppBar(
        title:
            Text(audioSupported ? l.voiceProfilesTitle : l.settingsSavedVoices),
        actions: [
          if (audioSupported)
            IconButton(
              onPressed: _isSubmitting ? null : _createProfile,
              icon: const Icon(Icons.add),
              tooltip: l.voiceProfilesAddTooltip,
            ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _profiles.isEmpty
              ? EmptyState(
                  icon: _errorMessage != null
                      ? Icons.cloud_off_outlined
                      : Icons.record_voice_over_outlined,
                  title: _errorMessage ??
                      (audioSupported
                          ? l.voiceProfilesEmpty
                          : l.voiceProfilesUnavailable),
                  buttonText: _errorMessage != null
                      ? l.retry
                      : audioSupported
                          ? l.voiceProfilesAdd
                          : null,
                  onButtonPressed: _errorMessage != null
                      ? _load
                      : audioSupported && !_isSubmitting
                          ? _createProfile
                          : null,
                )
              : RefreshIndicator(
                  onRefresh: () => _load(showLoading: false),
                  child: ListView.separated(
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
                          color: AppPalette.of(context).surface,
                          borderRadius: BorderRadius.circular(AppRadius.md),
                          border:
                              Border.all(color: AppPalette.of(context).divider),
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
                                  enabled: !_isSubmitting,
                                  constraints:
                                      const BoxConstraints(minWidth: 200),
                                  tooltip: l.voiceProfilesMenuTooltip,
                                  onSelected: (value) {
                                    if (value == 'edit' && audioSupported) {
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
                                    if (audioSupported)
                                      PopupMenuItem(
                                        height: AppSizing.minTouchTarget,
                                        value: 'edit',
                                        child: Text(l.voiceProfilesMenuEdit),
                                      ),
                                    PopupMenuItem(
                                      height: AppSizing.minTouchTarget,
                                      value: 'revoke',
                                      child: Text(l.voiceProfilesMenuRevoke),
                                    ),
                                    PopupMenuItem(
                                      height: AppSizing.minTouchTarget,
                                      value: 'delete',
                                      child: Text(l.voiceProfilesMenuDelete),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                            const SizedBox(height: AppSpacing.xs),
                            Text(
                                l.voiceProfilesRelationshipPrefix(relationship),
                                style: AppTextStyles.bodySmall),
                            const SizedBox(height: AppSpacing.xs),
                            Wrap(
                              spacing: AppSpacing.sm,
                              runSpacing: AppSpacing.xs,
                              children: [
                                _StateChip(
                                  text: consented
                                      ? l.voiceProfilesConsentDone
                                      : l.voiceProfilesConsentNeeded,
                                  ok: consented,
                                ),
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
      bottomNavigationBar: _errorMessage == null || _profiles.isEmpty
          ? null
          : SafeArea(
              child: Container(
                color: AppColors.error.withValues(alpha: 0.08),
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(_errorMessage!, style: AppTextStyles.bodySmall),
                    TextButton.icon(
                      style:
                          TextButton.styleFrom(minimumSize: const Size(64, 64)),
                      onPressed: _load,
                      icon: const Icon(Icons.refresh),
                      label: Text(l.retry),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}

/// Dialog controllers belong to the route's widget lifecycle, including its
/// exit animation. Resolving showDialog does not mean its fields are unmounted.
class _VoiceProfileDialog extends ConsumerStatefulWidget {
  const _VoiceProfileDialog({this.initial});

  final Map<String, dynamic>? initial;

  @override
  ConsumerState<_VoiceProfileDialog> createState() =>
      _VoiceProfileDialogState();
}

class _VoiceProfileDialogState extends ConsumerState<_VoiceProfileDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _label;
  late final TextEditingController _relationship;
  late final TextEditingController _sampleUrl;
  late bool _consented;
  late bool _active;
  bool _uploading = false;
  bool _closing = false;
  String? _sampleError;

  @override
  void initState() {
    super.initState();
    _label =
        TextEditingController(text: widget.initial?['label']?.toString() ?? '');
    _relationship = TextEditingController(
        text: widget.initial?['relationship']?.toString() ?? '');
    _sampleUrl = TextEditingController(
        text: widget.initial?['sample_audio_url']?.toString() ?? '');
    _consented = widget.initial?['consented'] == true;
    _active = widget.initial?['active'] != false;
  }

  @override
  void dispose() {
    _label.dispose();
    _relationship.dispose();
    _sampleUrl.dispose();
    super.dispose();
  }

  Future<void> _uploadSample() async {
    if (_uploading || _closing) return;
    final l = AppLocalizations.of(context);
    final api = ref.read(apiClientProvider);
    setState(() {
      _uploading = true;
      _sampleError = null;
    });
    try {
      final picked = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowMultiple: false,
        allowedExtensions: const ['m4a', 'mp3', 'wav', 'aac', 'ogg', 'webm'],
      );
      if (!mounted ||
          picked == null ||
          picked.files.isEmpty ||
          picked.files.first.path == null) {
        return;
      }
      final uploaded = await api.uploadVoiceSample(
        File(picked.files.first.path!),
        fileName: picked.files.first.name,
      );
      if (!mounted) return;
      final url = uploaded['sample_audio_url']?.toString();
      if (url == null || url.isEmpty) {
        throw const FormatException('Missing uploaded sample URL');
      }
      setState(() => _sampleUrl.text = url);
    } catch (_) {
      if (mounted) {
        setState(() => _sampleError = l.voiceProfilesSampleUploadError);
      }
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  void _save() {
    if (_uploading || _closing) return;
    final l = AppLocalizations.of(context);
    final validForm = _formKey.currentState!.validate();
    final sample = _sampleUrl.text.trim();
    final uri = Uri.tryParse(sample);
    final sampleError = sample.isEmpty
        ? l.voiceProfilesSampleRequiredUpload
        : uri == null || !uri.hasScheme || !uri.hasAuthority
            ? l.voiceProfilesSampleUrlInvalid
            : null;
    setState(() => _sampleError = sampleError);
    if (!validForm || sampleError != null) return;
    _closing = true;
    Navigator.pop(context, {
      'label': _label.text.trim(),
      'relationship': _relationship.text.trim(),
      'sample_audio_url': sample,
      'consented': _consented,
      'active': _active,
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return AlertDialog(
      scrollable: true,
      title: Text(widget.initial == null
          ? l.voiceProfilesAddTitle
          : l.voiceProfilesEditTitle),
      content: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextFormField(
              controller: _label,
              maxLength: 40,
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(
                  labelText: l.voiceProfilesLabelFieldLabel,
                  hintText: l.voiceProfilesLabelFieldHint),
              validator: (value) => value == null || value.trim().isEmpty
                  ? l.voiceProfilesLabelRequired
                  : null,
            ),
            const SizedBox(height: AppSpacing.sm),
            TextFormField(
              controller: _relationship,
              maxLength: 30,
              decoration: InputDecoration(
                  labelText: l.voiceProfilesRelationshipFieldLabel,
                  hintText: l.voiceProfilesRelationshipFieldHint),
            ),
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 64)),
              onPressed: _uploading ? null : _uploadSample,
              icon: _uploading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.audio_file_outlined),
              label: Text(
                  _uploading
                      ? l.voiceProfilesUploading
                      : l.voiceProfilesUploadAudioButton,
                  textAlign: TextAlign.center),
            ),
            if (_sampleUrl.text.trim().isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(l.voiceProfilesSampleSelected,
                  style: AppTextStyles.bodySmall),
            ],
            if (_sampleError != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(_sampleError!,
                  style:
                      AppTextStyles.bodySmall.copyWith(color: AppColors.error)),
            ],
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              maintainState: true,
              title: Text(l.voiceProfilesSampleLinkOption,
                  style: AppTextStyles.bodySmall),
              children: [
                TextFormField(
                  controller: _sampleUrl,
                  maxLength: 4096,
                  keyboardType: TextInputType.url,
                  onChanged: (_) => setState(() => _sampleError = null),
                  decoration: InputDecoration(
                      labelText: l.voiceProfilesSampleUrlFieldLabel,
                      hintText: 'https://...',
                      counterText: ''),
                ),
              ],
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(l.voiceProfilesConsentToggle),
              value: _consented,
              onChanged: (value) => setState(() => _consented = value),
            ),
            if (widget.initial != null)
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(l.voiceProfilesActiveToggle),
                value: _active,
                onChanged: (value) => setState(() => _active = value),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(64, 64)),
          onPressed: () {
            if (!_closing) {
              _closing = true;
              Navigator.pop(context);
            }
          },
          child: Text(l.voiceProfilesCancel),
        ),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(64, 64)),
          onPressed: _uploading ? null : _save,
          child: Text(widget.initial == null
              ? l.voiceProfilesAdd
              : l.voiceProfilesSave),
        ),
      ],
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
        color: ok
            ? AppPalette.of(context).primaryLight
            : AppPalette.of(context).background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: AppTextStyles.caption.copyWith(
          color: AppPalette.of(context).textPrimary,
        ),
      ),
    );
  }
}
