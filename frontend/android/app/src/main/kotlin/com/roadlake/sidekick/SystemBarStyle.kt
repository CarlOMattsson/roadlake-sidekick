package com.roadlake.sidekick

import android.app.Activity
import android.content.res.Configuration
import androidx.core.view.WindowCompat

/**
 * The contrast of the status and navigation bar icons. The page draws under the bars (edge-to-edge), so the icons must be
 * dark on a light page and light on a dark one. Capacitor's SystemBars sets them at start from the theme, but when the
 * theme changes while the app is open it re-applies the style it last resolved, not the new theme, so the icons stayed
 * dark on the dark page. [MainActivity.onConfigurationChanged] therefore sets them again from the new configuration.
 */
internal object SystemBarStyle {
    /** True when the page is light, so the bar icons are dark ("light bars" in the Android sense). */
    fun lightBars(uiMode: Int): Boolean = (uiMode and Configuration.UI_MODE_NIGHT_MASK) != Configuration.UI_MODE_NIGHT_YES

    fun apply(activity: Activity, configuration: Configuration) {
        val window = activity.window
        val controller = WindowCompat.getInsetsController(window, window.decorView)
        val light = lightBars(configuration.uiMode)
        controller.isAppearanceLightStatusBars = light
        controller.isAppearanceLightNavigationBars = light
    }
}
