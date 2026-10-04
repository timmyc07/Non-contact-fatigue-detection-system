import Flutter
import Foundation

/// Phase 3 channel boundary for the future iOS inference runtime.
///
/// Camera capture, permission requests, and model inference intentionally stay
/// unavailable until Phase 5 supplies a real on-device implementation.
public final class MobileRuntimePlugin: NSObject, FlutterPlugin, FlutterStreamHandler {
    public static let methodChannelName = "tw.fatigue_monitor/mobile_runtime"
    public static let eventChannelName = "tw.fatigue_monitor/mobile_runtime/events"

    private static let runtimeUnavailable = "runtime_unavailable"
    private let preferences = UserDefaults.standard
    private var eventSink: FlutterEventSink?
    private var foregroundState = "terminated"

    public static func register(with registrar: FlutterPluginRegistrar) {
        let instance = MobileRuntimePlugin()
        let methodChannel = FlutterMethodChannel(
            name: methodChannelName,
            binaryMessenger: registrar.messenger(),
        )
        let eventChannel = FlutterEventChannel(
            name: eventChannelName,
            binaryMessenger: registrar.messenger(),
        )
        registrar.addMethodCallDelegate(instance, channel: methodChannel)
        eventChannel.setStreamHandler(instance)
    }

    public func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
        switch call.method {
        case "getPermissionState":
            result("unknown")
        case "requestPermission", "startCamera", "loadModel":
            unavailable(result)
        case "stopCamera", "unloadModel", "dispose":
            if call.method == "dispose" { eventSink = nil }
            result(nil)
        case "getModelState":
            result("unloaded")
        case "getForegroundState":
            result(foregroundState)
        case "setForegroundState":
            guard
                let arguments = call.arguments as? [String: Any],
                let state = arguments["state"] as? String,
                !state.isEmpty
            else {
                result(FlutterError(
                    code: "invalid_argument",
                    message: "Missing foreground state.",
                    details: nil,
                ))
                return
            }
            foregroundState = state
            eventSink?(["type": "foreground", "state": foregroundState])
            result(nil)
        case "readLocal":
            let key = (call.arguments as? [String: Any])?["key"] as? String
            result(key.flatMap { preferences.string(forKey: $0) })
        case "writeLocal":
            guard
                let arguments = call.arguments as? [String: Any],
                let key = arguments["key"] as? String,
                let value = arguments["value"] as? String,
                !key.isEmpty
            else {
                result(FlutterError(
                    code: "invalid_argument",
                    message: "Missing local storage key/value.",
                    details: nil,
                ))
                return
            }
            preferences.set(value, forKey: key)
            result(nil)
        case "deleteLocal":
            guard
                let key = (call.arguments as? [String: Any])?["key"] as? String,
                !key.isEmpty
            else {
                result(FlutterError(
                    code: "invalid_argument",
                    message: "Missing local storage key.",
                    details: nil,
                ))
                return
            }
            preferences.removeObject(forKey: key)
            result(nil)
        default:
            result(FlutterMethodNotImplemented)
        }
    }

    public func onListen(
        withArguments arguments: Any?,
        eventSink events: @escaping FlutterEventSink,
    ) -> FlutterError? {
        eventSink = events
        return nil
    }

    public func onCancel(withArguments arguments: Any?) -> FlutterError? {
        eventSink = nil
        return nil
    }

    private func unavailable(_ result: @escaping FlutterResult) {
        result(FlutterError(
            code: Self.runtimeUnavailable,
            message: "Native mobile inference runtime is not available in Phase 3.",
            details: ["phase": 3],
        ))
    }
}
