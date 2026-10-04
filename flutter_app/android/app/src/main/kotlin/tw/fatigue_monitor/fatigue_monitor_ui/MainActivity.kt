package tw.fatigue_monitor.fatigue_monitor_ui

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import tw.fatigue_monitor.mobile_runtime.MobileRuntimePlugin

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        if (!flutterEngine.plugins.has(MobileRuntimePlugin::class.java)) {
            flutterEngine.plugins.add(MobileRuntimePlugin())
        }
    }
}
