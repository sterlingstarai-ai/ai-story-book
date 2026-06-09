// flutter_driver 진입점 — 실기기/시뮬레이터에서 통합 테스트를 구동할 때 사용.
//   flutter drive \
//     --driver=test_driver/integration_test.dart \
//     --target=integration_test/app_flow_test.dart
//
// CI·로컬에서 에뮬레이터 없이 헤드리스로 돌릴 때는 driver 없이:
//   flutter test integration_test/
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver();
