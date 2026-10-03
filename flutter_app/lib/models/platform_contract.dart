/// Platform-neutral capability contract shared by desktop and future mobile shells.
enum AppPlatform {
  windows,
  macos,
  linux,
  android,
  ios,
  webDesktop,
  unsupportedNative,
}

class PlatformCapabilities {
  const PlatformCapabilities({
    required this.platform,
    required this.runtimeKind,
    required this.status,
    required this.desktopEngineSupported,
    required this.nativeInferenceReady,
    required this.capabilities,
    required this.artifactTypes,
  });

  final AppPlatform platform;
  final String runtimeKind;
  final String status;
  final bool desktopEngineSupported;
  final bool nativeInferenceReady;
  final Set<String> capabilities;
  final List<String> artifactTypes;

  bool supports(String capability) => capabilities.contains(capability);

  bool get requiresNativeRuntime =>
      platform == AppPlatform.android || platform == AppPlatform.ios;

  bool get canStartMonitoring => desktopEngineSupported || nativeInferenceReady;

  String get unavailableReason => requiresNativeRuntime
      ? '此行動平台尚未提供原生推論 runtime，無法啟動監測。'
      : '此平台尚未提供可用的監測 runtime。';

  static const windows = PlatformCapabilities(
    platform: AppPlatform.windows,
    runtimeKind: 'python_desktop',
    status: 'available',
    desktopEngineSupported: true,
    nativeInferenceReady: true,
    capabilities: {'camera', 'ble', 'overlay', 'tauri_shell'},
    artifactTypes: ['nsis'],
  );

  static const macos = PlatformCapabilities(
    platform: AppPlatform.macos,
    runtimeKind: 'python_desktop',
    status: 'available',
    desktopEngineSupported: true,
    nativeInferenceReady: true,
    capabilities: {'camera', 'ble', 'overlay', 'tauri_shell'},
    artifactTypes: ['app', 'dmg'],
  );

  static const linux = PlatformCapabilities(
    platform: AppPlatform.linux,
    runtimeKind: 'python_desktop',
    status: 'available',
    desktopEngineSupported: true,
    nativeInferenceReady: true,
    capabilities: {'camera', 'tauri_shell'},
    artifactTypes: ['appimage', 'deb'],
  );

  static const android = PlatformCapabilities(
    platform: AppPlatform.android,
    runtimeKind: 'native_mobile',
    status: 'planned',
    desktopEngineSupported: false,
    nativeInferenceReady: false,
    capabilities: {},
    artifactTypes: ['apk', 'aab'],
  );

  static const ios = PlatformCapabilities(
    platform: AppPlatform.ios,
    runtimeKind: 'native_mobile',
    status: 'planned',
    desktopEngineSupported: false,
    nativeInferenceReady: false,
    capabilities: {},
    artifactTypes: ['ipa', 'archive'],
  );

  static const webDesktop = PlatformCapabilities(
    platform: AppPlatform.webDesktop,
    runtimeKind: 'tauri_web',
    status: 'available',
    desktopEngineSupported: true,
    nativeInferenceReady: false,
    capabilities: {'camera', 'tauri_shell'},
    artifactTypes: [],
  );

  static const unsupportedNative = PlatformCapabilities(
    platform: AppPlatform.unsupportedNative,
    runtimeKind: 'unknown',
    status: 'unsupported',
    desktopEngineSupported: false,
    nativeInferenceReady: false,
    capabilities: {},
    artifactTypes: [],
  );

  static PlatformCapabilities forPlatform(AppPlatform platform) {
    switch (platform) {
      case AppPlatform.windows:
        return windows;
      case AppPlatform.macos:
        return macos;
      case AppPlatform.linux:
        return linux;
      case AppPlatform.android:
        return android;
      case AppPlatform.ios:
        return ios;
      case AppPlatform.webDesktop:
        return webDesktop;
      case AppPlatform.unsupportedNative:
        return unsupportedNative;
    }
  }
}

PlatformCapabilities currentPlatformCapabilities({
  required bool isWeb,
  required bool isAndroid,
  required bool isIos,
  required bool isWindows,
  required bool isMacos,
  required bool isLinux,
}) {
  if (isWeb) return PlatformCapabilities.webDesktop;
  if (isAndroid) return PlatformCapabilities.android;
  if (isIos) return PlatformCapabilities.ios;
  if (isWindows) return PlatformCapabilities.windows;
  if (isMacos) return PlatformCapabilities.macos;
  if (isLinux) return PlatformCapabilities.linux;
  return PlatformCapabilities.unsupportedNative;
}

class UnsupportedPlatformRuntimeError extends UnsupportedError {
  UnsupportedPlatformRuntimeError(this.capabilities)
      : super(capabilities.unavailableReason);

  final PlatformCapabilities capabilities;
}
