// Run on a dedicated Android test emulator. Provider fakes keep this free of
// external AI, accounts, purchases and user photos; native Flutter input remains.
import 'package:integration_test/integration_test.dart';
import '../test/account_recovery_test.dart' as recovery;
import '../test/viewer_reading_accessibility_test.dart' as reader;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  recovery.main();
  reader.main();
}
