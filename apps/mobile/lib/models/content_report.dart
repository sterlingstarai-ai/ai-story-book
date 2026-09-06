enum ContentReportReason {
  harmfulContent('harmful_content'),
  sexualContent('sexual_content'),
  hateOrBullying('hate_or_bullying'),
  personalInformation('personal_information'),
  imageProblem('image_problem'),
  other('other');

  final String apiValue;
  const ContentReportReason(this.apiValue);
}

class ContentReportReceipt {
  final String reportId;
  final String status;

  const ContentReportReceipt({required this.reportId, required this.status});

  factory ContentReportReceipt.fromJson(Map<String, dynamic> data) {
    final id = data['report_id'];
    final status = data['status'];
    if (id is! String ||
        id.isEmpty ||
        status is! String ||
        !{'pending', 'in_review', 'resolved', 'dismissed'}.contains(status)) {
      throw const FormatException('Invalid content report receipt');
    }
    return ContentReportReceipt(reportId: id, status: status);
  }
}
