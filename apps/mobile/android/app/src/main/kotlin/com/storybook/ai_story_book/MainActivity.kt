package com.storybook.ai_story_book

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PersistableBundle
import java.util.UUID

class MainActivity : FlutterActivity() {
    private val expiryHandler = Handler(Looper.getMainLooper())
    // Only a random clipboard label and deadline are retained, never the code.
    // Retry after focus returns or a process restart: Android cannot inspect
    // another app's clipboard while this activity is in the background.
    private val clipboardState get() = getSharedPreferences("recovery_clipboard_cleanup", Context.MODE_PRIVATE)
    private val clipboardToken get() = clipboardState.getString("token", null)

    private fun clearRecoveryCode(token: String) {
        if (clipboardToken != token) return
        clipboardState.edit().putLong("expires_at", 0).commit()
        val board = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        // Inspect only our label, never read another app's clipboard text.
        // null also means "read denied" (background/locked), so keep the handle.
        val description = board.primaryClipDescription ?: return
        if (description.label?.toString() == "asb-recovery:$token") {
            if (Build.VERSION.SDK_INT >= 28) board.clearPrimaryClip()
            else board.setPrimaryClip(ClipData.newPlainText("", ""))
        }
        clipboardState.edit().clear().commit()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "ai_story_book/security")
            .setMethodCallHandler { call, result ->
                try {
                    when (call.method) {
                        "copyRecoveryCode" -> {
                            val code = call.arguments as? String
                            if (code == null || !Regex("ASB-R1-[A-Za-z0-9_-]{43}").matches(code)) {
                                result.error("INVALID_CODE", "Invalid recovery code", null)
                            } else {
                                val token = UUID.randomUUID().toString()
                                val clip = ClipData.newPlainText("asb-recovery:$token", code)
                                clip.description.extras = PersistableBundle().apply {
                                    putBoolean("android.content.extra.IS_SENSITIVE", true)
                                }
                                val board = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                board.setPrimaryClip(clip)
                                if (!clipboardState.edit().putString("token", token)
                                        .putLong("expires_at", System.currentTimeMillis() + 60_000).commit()) {
                                    if (Build.VERSION.SDK_INT >= 28) board.clearPrimaryClip()
                                    else board.setPrimaryClip(ClipData.newPlainText("", ""))
                                    throw IllegalStateException("Clipboard cleanup state unavailable")
                                }
                                expiryHandler.postDelayed({ runCatching { clearRecoveryCode(token) } }, 60_000)
                                result.success(token)
                            }
                        }
                        "clearRecoveryCode" -> {
                            (call.arguments as? String)?.let { clearRecoveryCode(it) }
                            result.success(null)
                        }
                        else -> result.notImplemented()
                    }
                } catch (_: Exception) {
                    result.error("CLIPBOARD_UNAVAILABLE", "Secure copy unavailable", null)
                }
            }
        clipboardToken?.let { token ->
            val delay = (clipboardState.getLong("expires_at", 0) - System.currentTimeMillis()).coerceAtLeast(0)
            expiryHandler.postDelayed({ runCatching { clearRecoveryCode(token) } }, delay)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && System.currentTimeMillis() >= clipboardState.getLong("expires_at", 0)) {
            clipboardToken?.let { runCatching { clearRecoveryCode(it) } }
        }
    }

    override fun onDestroy() {
        clipboardToken?.let { runCatching { clearRecoveryCode(it) } }
        expiryHandler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }
}
