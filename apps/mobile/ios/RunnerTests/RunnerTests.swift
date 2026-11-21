import Flutter
import UIKit
import XCTest
import Security
@testable import Runner

class RunnerTests: XCTestCase {

  func testExistingCredentialsMoveInPlaceWithoutChangingTheirValues() throws {
    let service = "security-regression-" + UUID().uuidString
    let base: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: service]
    defer { SecItemDelete(base as CFDictionary) }
    for account in DeviceSecurity.credentialAccounts {
      var item = base
      item[kSecAttrAccount] = account
      item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlocked
      item[kSecValueData] = Data(("synthetic-" + account).utf8)
      XCTAssertEqual(SecItemAdd(item as CFDictionary, nil), errSecSuccess)
    }
    for _ in 0..<2 {
      XCTAssertEqual(DeviceSecurity.protectCredentials(service: service), errSecSuccess)
      for account in DeviceSecurity.credentialAccounts {
        var query = base
        query[kSecAttrAccount] = account
        query[kSecReturnData] = true
        query[kSecReturnAttributes] = true
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        let item = try XCTUnwrap(result as? [CFString: Any])
        XCTAssertEqual(item[kSecAttrAccessible] as? String, kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        XCTAssertEqual(item[kSecValueData] as? Data, Data(("synthetic-" + account).utf8))
      }
    }
  }

  func testMissingCredentialsDoNotCreateOrDeleteAnAccount() {
    let service = "security-empty-" + UUID().uuidString
    XCTAssertEqual(DeviceSecurity.protectCredentials(service: service), errSecSuccess)
    let query: [CFString: Any] = [kSecClass: kSecClassGenericPassword, kSecAttrService: service]
    XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, nil), errSecItemNotFound)
  }

  func testClipboardClearPreservesANewerCopy() {
    let security = DeviceSecurity()
    let token = security.copyRecoveryCode("ASB-R1-" + String(repeating: "A", count: 43))
    XCTAssertTrue(UIPasteboard.general.hasStrings)
    UIPasteboard.general.string = "new unrelated text"
    security.clearRecoveryCode(token)
    XCTAssertEqual(UIPasteboard.general.string, "new unrelated text")
    UIPasteboard.general.items = []
  }

  func testClipboardOldHandleCannotClearNewCodeAndExpiryClearsOwnedItem() {
    let security = DeviceSecurity()
    let first = security.copyRecoveryCode("ASB-R1-" + String(repeating: "A", count: 43))
    _ = security.copyRecoveryCode("ASB-R1-" + String(repeating: "B", count: 43), lifetime: 0.2)
    security.clearRecoveryCode(first)
    XCTAssertEqual(UIPasteboard.general.string, "ASB-R1-" + String(repeating: "B", count: 43))
    let expired = expectation(description: "Native clipboard expiry")
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
      XCTAssertFalse(UIPasteboard.general.hasStrings)
      expired.fulfill()
    }
    wait(for: [expired], timeout: 3)
  }

}
