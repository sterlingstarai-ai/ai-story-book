import Flutter
import UIKit
import UserNotifications
import Security

/// Credential operations stay on the platform side; no raw keys cross this channel.
final class DeviceSecurity {
  static let credentialService = "flutter_secure_storage_service"
  static let credentialAccounts = ["user_key", "pending_recovered_user_key_v1"]
  private var clipboardToken: String?
  private var clipboardChange: Int?

  static func protectCredentials(service: String = credentialService) -> OSStatus {
    for account in credentialAccounts {
      let query: [CFString: Any] = [
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: service,
        kSecAttrAccount: account,
        kSecAttrSynchronizable: false,
      ]
      // Never use the storage plugin's destructive delete/re-add fallback.
      let status = SecItemUpdate(query as CFDictionary, [
        kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        kSecAttrSynchronizable: false,
      ] as CFDictionary)
      if status != errSecSuccess && status != errSecItemNotFound { return status }
    }
    return errSecSuccess
  }

  func copyRecoveryCode(_ code: String, lifetime: TimeInterval = 60) -> String {
    let token = UUID().uuidString
    let board = UIPasteboard.general
    board.setItems([["public.utf8-plain-text": code]], options: [
      .localOnly: true,
      .expirationDate: Date(timeIntervalSinceNow: lifetime),
    ])
    clipboardToken = token
    clipboardChange = board.changeCount
    DispatchQueue.main.asyncAfter(deadline: .now() + lifetime) { [weak self] in
      self?.clearRecoveryCode(token)
    }
    return token
  }

  func clearRecoveryCode(_ token: String) {
    guard clipboardToken == token else { return }
    let board = UIPasteboard.general
    if clipboardChange == board.changeCount { board.items = [] }
    clipboardToken = nil
    clipboardChange = nil
  }
}

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private let deviceSecurity = DeviceSecurity()
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    // 로컬 알림(잠자리 리마인더) — 포그라운드 표시를 위해 delegate 설정
    if #available(iOS 10.0, *) {
      UNUserNotificationCenter.current().delegate = self
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    let channel = FlutterMethodChannel(
      name: "ai_story_book/security",
      binaryMessenger: engineBridge.applicationRegistrar.messenger()
    )
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else { return }
      switch call.method {
      case "protectDeviceCredentials":
        let status = DeviceSecurity.protectCredentials()
        if status == errSecSuccess {
          result(nil)
        } else {
          result(FlutterError(code: "KEYCHAIN_UNAVAILABLE", message: "Credential protection failed", details: nil))
        }
      case "copyRecoveryCode":
        guard let code = call.arguments as? String,
              code.range(of: "^ASB-R1-[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil else {
          result(FlutterError(code: "INVALID_CODE", message: "Invalid recovery code", details: nil))
          return
        }
        result(self.deviceSecurity.copyRecoveryCode(code))
      case "clearRecoveryCode":
        if let token = call.arguments as? String { self.deviceSecurity.clearRecoveryCode(token) }
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }
}
