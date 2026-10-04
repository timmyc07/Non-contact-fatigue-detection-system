package tw.fatigue_monitor.mobile_runtime

import android.content.Context
import android.content.SharedPreferences
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Phase 3 channel boundary for the future Android inference runtime.
 *
 * Camera capture, permission requests, and model inference intentionally stay
 * unavailable until Phase 4 supplies a real on-device implementation.
 */
class MobileRuntimePlugin : FlutterPlugin, MethodChannel.MethodCallHandler,
    EventChannel.StreamHandler {
    companion object {
        const val METHOD_CHANNEL = "tw.fatigue_monitor/mobile_runtime"
        const val EVENT_CHANNEL = "tw.fatigue_monitor/mobile_runtime/events"

        private const val RUNTIME_UNAVAILABLE = "runtime_unavailable"
        private const val PREFS_NAME = "fatigue_monitor_mobile_runtime"
    }

    private lateinit var context: Context
    private lateinit var preferences: SharedPreferences
    private var methodChannel: MethodChannel? = null
    private var eventChannel: EventChannel? = null
    private var eventSink: EventChannel.EventSink? = null
    private var foregroundState = "terminated"

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        context = binding.applicationContext
        preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        methodChannel = MethodChannel(binding.binaryMessenger, METHOD_CHANNEL).also {
            it.setMethodCallHandler(this)
        }
        eventChannel = EventChannel(binding.binaryMessenger, EVENT_CHANNEL).also {
            it.setStreamHandler(this)
        }
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        methodChannel?.setMethodCallHandler(null)
        eventChannel?.setStreamHandler(null)
        methodChannel = null
        eventChannel = null
        eventSink = null
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "getPermissionState" -> result.success("unknown")
            "requestPermission", "startCamera", "loadModel" -> unavailable(result)
            "stopCamera", "unloadModel" -> result.success(null)
            "getModelState" -> result.success("unloaded")
            "getForegroundState" -> result.success(foregroundState)
            "setForegroundState" -> {
                val state = call.argument<String>("state")
                if (state.isNullOrBlank()) {
                    result.error("invalid_argument", "Missing foreground state.", null)
                } else {
                    foregroundState = state
                    eventSink?.success(
                        mapOf("type" to "foreground", "state" to foregroundState),
                    )
                    result.success(null)
                }
            }
            "readLocal" -> result.success(preferences.getString(call.argument("key"), null))
            "writeLocal" -> {
                val key = call.argument<String>("key")
                val value = call.argument<String>("value")
                if (key.isNullOrEmpty() || value == null) {
                    result.error("invalid_argument", "Missing local storage key/value.", null)
                } else {
                    preferences.edit().putString(key, value).apply()
                    result.success(null)
                }
            }
            "deleteLocal" -> {
                val key = call.argument<String>("key")
                if (key.isNullOrEmpty()) {
                    result.error("invalid_argument", "Missing local storage key.", null)
                } else {
                    preferences.edit().remove(key).apply()
                    result.success(null)
                }
            }
            "dispose" -> {
                eventSink = null
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    private fun unavailable(result: MethodChannel.Result) {
        result.error(
            RUNTIME_UNAVAILABLE,
            "Native mobile inference runtime is not available in Phase 3.",
            mapOf("phase" to 3),
        )
    }
}
