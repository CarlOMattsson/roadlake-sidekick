package com.roadlake.sidekick

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings

/**
 * The few places the app sends the owner outside itself: the system's notification settings for Sidekick and an app
 * store page (the ntfy app, a newer WebView). The addresses are built here from fixed parts and a package name that is
 * checked first, so nothing from the page or the server reaches an intent.
 */
internal object SystemLinks {
    /** The ntfy app (UnifiedPush distributor). F-Droid and Play use the same package name. */
    const val NTFY_PACKAGE = "io.heckel.ntfy"
    const val NTFY_FALLBACK_URI = "https://f-droid.org/packages/io.heckel.ntfy/"

    /** The WebView when the system names none (a phone with Chrome as its WebView names Chrome instead). */
    const val DEFAULT_WEBVIEW_PACKAGE = "com.google.android.webview"

    private val PACKAGE_NAME = Regex("""[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+""")

    fun marketUri(packageName: String): String = "market://details?id=$packageName"

    fun playWebUri(packageName: String): String = "https://play.google.com/store/apps/details?id=$packageName"

    /** The package of the WebView provider to update: the installed one when its name is well formed, else the stock WebView. */
    fun webViewPackage(installed: String?): String = installed?.takeIf { PACKAGE_NAME.matches(it) } ?: DEFAULT_WEBVIEW_PACKAGE

    /** The store page of [packageName]: the market app first, then [webUri] in a browser. False when neither could open. */
    fun openStore(context: Context, packageName: String, webUri: String = playWebUri(packageName)): Boolean {
        require(PACKAGE_NAME.matches(packageName)) { "bad package" }
        return start(context, view(marketUri(packageName))) || start(context, view(webUri))
    }

    /** Android's notification settings for this app (below Android 8, its app details page). */
    fun openNotificationSettings(context: Context): Boolean {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
        } else {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
        }
        return start(context, intent)
    }

    private fun view(uri: String): Intent = Intent(Intent.ACTION_VIEW, Uri.parse(uri))

    private fun start(context: Context, intent: Intent): Boolean {
        if (context !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }
}
