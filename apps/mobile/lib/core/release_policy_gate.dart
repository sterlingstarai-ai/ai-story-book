/// Constant evaluation rejects a release build with missing public documents.
/// Debug builds can read bundled documents without public hosting.
class ReleasePolicyGate {
  const ReleasePolicyGate({
    this.release = const bool.fromEnvironment('dart.vm.product'),
    this.privacy = const String.fromEnvironment('PRIVACY_POLICY_URL'),
    this.terms = const String.fromEnvironment('TERMS_OF_SERVICE_URL'),
  }) : assert(
         !release || privacy != '',
         'Release requires PRIVACY_POLICY_URL.',
       ),
       assert(
         !release || terms != '',
         'Release requires TERMS_OF_SERVICE_URL.',
       );

  final bool release;
  final String privacy;
  final String terms;
}

const releasePolicyGate = ReleasePolicyGate();
