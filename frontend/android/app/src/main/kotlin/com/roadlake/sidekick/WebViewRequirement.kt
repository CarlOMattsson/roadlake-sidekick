package com.roadlake.sidekick

import android.content.Context
import android.os.Build
import android.webkit.WebView

/**
 * The oldest WebView (Chromium) the app's page runs in. Android 7 (minSdk 24) says nothing about it: the WebView is a
 * separately updated app, and the page needs Chromium 123 for the native `light-dark()` of its CSS. The same number is
 * the build target in vite.mobile.config.ts and `minWebViewVersion` in capacitor.config.ts; WebViewRequirementTest keeps
 * the three equal. An older WebView would show a blank or unstyled page, so [MainActivity] shows an explanation instead.
 */
internal object WebViewRequirement {
    const val MIN_CHROMIUM_MAJOR = 123

    sealed interface Verdict {
        data class Supported(val major: Int) : Verdict

        data class TooOld(val major: Int) : Verdict

        /** No readable version. Not blocked: a check that cannot judge must not lock out a working WebView. */
        data object Unknown : Verdict
    }

    private val FIRST_NUMBER = Regex("""\d+""")
    private val USER_AGENT_CHROME = Regex("""Chrome/(\d+)""")

    /** The major version in a WebView package version name such as "124.0.6367.82", or null. */
    fun majorOfVersionName(versionName: String?): Int? = versionName?.let { FIRST_NUMBER.find(it)?.value?.toIntOrNull() }

    /** The major version in a WebView user agent ("... Chrome/124.0.0.0 Mobile ..."), or null. */
    fun majorOfUserAgent(userAgent: String?): Int? = userAgent?.let { USER_AGENT_CHROME.find(it)?.groupValues?.get(1)?.toIntOrNull() }

    fun verdict(major: Int?, minimum: Int = MIN_CHROMIUM_MAJOR): Verdict = when {
        major == null -> Verdict.Unknown
        major >= minimum -> Verdict.Supported(major)
        else -> Verdict.TooOld(major)
    }

    /** The installed WebView's verdict: the package version on Android 8+, else the user agent of a throwaway WebView. */
    fun check(context: Context): Verdict {
        val fromPackage =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                majorOfVersionName(WebView.getCurrentWebViewPackage()?.versionName)
            } else {
                null
            }
        val major = fromPackage
            ?: majorOfUserAgent(runCatching { WebView(context).settings.userAgentString }.getOrNull())
        return verdict(major)
    }
}
