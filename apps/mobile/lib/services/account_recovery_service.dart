import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import '../core/api_error.dart';
import 'parental_control_service.dart';
import 'local_media_cleanup.dart';
import 'user_service.dart';

class AccountDeletionUnconfirmed implements Exception {
  const AccountDeletionUnconfirmed();
}

/// Coordinates server rotation with durable device storage. Raw credentials never
/// leave this boundary for display, clipboard, preferences, or telemetry.
class AccountRecoveryService {
  AccountRecoveryService({
    required this.userService,
    required this.preferences,
    required this.clientForKey,
    required this.purgeLocalMedia,
  });

  final UserService userService;
  final SharedPreferences preferences;
  final ApiClient Function(String key) clientForKey;
  final Future<void> Function() purgeLocalMedia;

  Future<void> initialize() async {
    if (preferences.getBool(UserService.deletionCommittedKey) == true) {
      try {
        await purgeLocalMedia();
        await userService.completeAccountDeletion();
      } catch (_) {
        throw const AccountDeletionUnconfirmed();
      }
    }
    if (preferences.getBool(localMediaCleanupPendingKey) == true) {
      await purgeLocalMedia();
    }
    if (userService.deletionRequested) {
      try {
        await userService.resumeKeyForDeletion();
        await deleteAccount();
      } catch (_) {
        throw const AccountDeletionUnconfirmed();
      }
    }
    final pending = await userService.pendingRecoveryKey();
    if (pending == null) return;
    // A 401 may race a previous timed-out request. Retain the staged key and
    // offer recovery retry instead of creating/reopening an unrelated account.
    await clientForKey(pending).validateAccountSession();
    await userService.activatePendingRecoveryKey();
    await _restoreConsent(clientForKey(pending));
  }

  /// Persist the user's confirmed intent before sending the destructive request.
  /// A lost response keeps the same credential for reconciliation on next launch.
  Future<bool> deleteAccount({ApiClient? client}) async {
    await userService.markDeletionRequested();
    if (preferences.getBool(UserService.deletionCommittedKey) == true) {
      await purgeLocalMedia();
      await userService.completeAccountDeletion();
      return true;
    }
    final api = client ?? clientForKey(userService.getUserKey());
    var purgePending = false;
    try {
      try {
        await api.deleteMyData();
      } on StoragePurgePending {
        purgePending = true;
      } on DioException catch (error) {
        final apiError = error.error is ApiError
            ? error.error as ApiError
            : ApiError.fromDioException(error);
        if (apiError.code != 'ACCOUNT_DELETED') rethrow;
        purgePending =
            apiError.details is Map &&
            apiError.details['purge_retry_pending'] == true;
      }
      if (!await preferences.setBool(UserService.deletionCommittedKey, true)) {
        throw const UserKeyUnavailable();
      }
      await purgeLocalMedia();
      await userService.completeAccountDeletion();
      return purgePending;
    } finally {
      if (client == null) api.close();
    }
  }

  Future<void> validateCurrentSession() async {
    final key = userService.getUserKey();
    if (!key.startsWith('asb_device_')) return;
    try {
      await clientForKey(key).validateAccountSession();
    } on DioException catch (error) {
      if (error.response?.statusCode == 401 ||
          error.response?.statusCode == 403) {
        throw const UserKeyUnavailable();
      }
      // Offline startup may show already saved books; fresh authenticated
      // requests still fail closed and cannot mutate a revoked account.
    }
  }

  Future<String?> recover(String recoveryCode) async {
    final hadPending = await userService.pendingRecoveryKey() != null;
    final key = await userService.prepareRecoveryKey();
    final client = clientForKey(key);
    String? replacementCode;
    try {
      replacementCode = await client.recoverAccount(
        recoveryCode: recoveryCode.trim(),
        newUserKey: key,
      );
    } catch (error) {
      try {
        // A lost response must not strand a successfully rotated account.
        await client.validateAccountSession();
      } catch (_) {
        final status = error is DioException
            ? error.response?.statusCode
            : null;
        if (!hadPending && status != null && status >= 400 && status < 500) {
          // First attempt explicitly rejected before any ambiguous retry.
          await userService.discardPendingRecoveryKey();
        }
        rethrow;
      }
    }
    await userService.activatePendingRecoveryKey();
    await _restoreConsent(client);
    if (replacementCode == null) {
      try {
        replacementCode = await client.createAccountRecoveryCode();
      } catch (_) {
        // The account is safely installed; settings will retain a backup reminder.
      }
    }
    return replacementCode;
  }

  Future<void> _restoreConsent(ApiClient client) async {
    try {
      final consent = await client.getConsent();
      final granted =
          consent['granted'] == true &&
          consent['privacy'] == true &&
          consent['data_processing'] == true &&
          consent['revoked'] != true;
      await preferences.setBool(
        ParentalControlService.consentGrantedKey,
        granted,
      );
    } catch (_) {
      // Require the existing consent flow if its status cannot be established.
    }
  }
}
