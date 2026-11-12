# R8 rules for the release build (minifyEnabled). Libraries ship consumer rules of their own (Capacitor, WorkManager,
# Glance, the UnifiedPush connector); the rules below name what this app reaches by reflection, so that they hold
# even if a library's own rules change. Classes named in AndroidManifest.xml are kept by AGP without a rule here.

# Capacitor bridge: the bridge finds plugins through the @CapacitorPlugin annotation and calls their methods by the
# name the page uses, so the plugin class, its @PluginMethod methods and the annotations must keep their names.
-keepattributes *Annotation*, InnerClasses, Signature, EnclosingMethod
-keep @com.getcapacitor.annotation.CapacitorPlugin public class * {
    @com.getcapacitor.PluginMethod public <methods>;
    @com.getcapacitor.annotation.PermissionCallback <methods>;
    @com.getcapacitor.annotation.ActivityCallback <methods>;
}
-keep public class * extends com.getcapacitor.Plugin { <init>(); }

# The page talks to the native side through Capacitor's WebView JavaScript interface.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# WorkManager restores workers (TodaySync, ReminderSync, PushSync) from their class name and builds them with the
# (Context, WorkerParameters) constructor.
-keep class * extends androidx.work.ListenableWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}

# Glance runs widget taps as ActionCallback classes it looks up by name and creates with the no-argument constructor.
-keep class * implements androidx.glance.appwidget.action.ActionCallback {
    public <init>();
}

# The UnifiedPush connector binds to the PushService declared in the manifest (SidekickPushService); the subclass is
# kept by the manifest rule, and its callbacks are overridden members the library calls by signature.
-keepclassmembers class * extends org.unifiedpush.android.connector.PushService {
    public <methods>;
}

# org.json comes from the Android framework (the org.json test dependency is for JVM tests only); nothing to keep.

# Readable stack traces from release crashes (the mapping file in the build output de-obfuscates them).
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
