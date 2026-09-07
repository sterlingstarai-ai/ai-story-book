import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../l10n/app_localizations.dart';
import '../services/public_links.dart';
import '../utils/constants.dart';

enum LegalDocument { privacy, terms }

/// The same versioned source is rendered into the public HTML pages.
/// Reading the bundled full text never requires login, consent, or connectivity.
class LegalDocumentScreen extends ConsumerStatefulWidget {
  const LegalDocumentScreen({super.key, required this.document});

  final LegalDocument document;

  @override
  ConsumerState<LegalDocumentScreen> createState() =>
      _LegalDocumentScreenState();
}

class _LegalDocumentScreenState extends ConsumerState<LegalDocumentScreen> {
  late final Future<Map<String, dynamic>> _document = _load();

  Future<Map<String, dynamic>> _load() async =>
      jsonDecode(
            await rootBundle.loadString(
              'assets/legal/${widget.document.name}.ko.json',
            ),
          )
          as Map<String, dynamic>;

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final privacy = widget.document == LegalDocument.privacy;
    final links = ref.watch(publicLinksProvider);
    final url = privacy ? links.privacyPolicyUrl : links.termsOfServiceUrl;
    return Scaffold(
      appBar: AppBar(
        title: Text(
          privacy ? l.settingsPrivacyPolicy : l.settingsTermsOfService,
        ),
      ),
      body: SafeArea(
        child: FutureBuilder<Map<String, dynamic>>(
          future: _document,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return Center(child: Text(l.settingsPageOpenError));
            }
            final data = snapshot.data;
            if (data == null) {
              return const Center(child: CircularProgressIndicator());
            }
            final sections = (data['sections'] as List)
                .cast<Map<String, dynamic>>();
            return SelectionArea(
              child: ListView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                children: [
                  if (data['publication_status'] != 'approved')
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        child: Text(l.legalDraftNotice),
                      ),
                    ),
                  if (Localizations.localeOf(context).languageCode != 'ko')
                    Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.md),
                      child: Text(l.legalKoreanOriginal),
                    ),
                  Text(
                    data['title'] as String,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(data['version_label'] as String),
                  const SizedBox(height: AppSpacing.md),
                  Text(data['introduction'] as String),
                  for (final section in sections) ...[
                    const SizedBox(height: AppSpacing.lg),
                    Semantics(
                      header: true,
                      child: Text(
                        section['heading'] as String,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    for (final paragraph
                        in (section['paragraphs'] as List).cast<String>())
                      Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                        child: Text(paragraph),
                      ),
                  ],
                  if (PublicLinks.publicUri(url) != null)
                    OutlinedButton.icon(
                      onPressed: () async {
                        final opened = await links.open(url);
                        if (!context.mounted || opened) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(l.settingsPageOpenError)),
                        );
                      },
                      icon: const Icon(Icons.open_in_new),
                      label: Text(l.legalOpenWebsite),
                    ),
                  const SizedBox(height: AppSpacing.lg),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}
