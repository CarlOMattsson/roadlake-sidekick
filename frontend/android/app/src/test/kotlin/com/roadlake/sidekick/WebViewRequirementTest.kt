package com.roadlake.sidekick

import com.roadlake.sidekick.WebViewRequirement.Verdict
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The minimum WebView: the version check, and that the build target and Capacitor's setting name the same number. */
class WebViewRequirementTest {
    private val min = WebViewRequirement.MIN_CHROMIUM_MAJOR

    @Test
    fun readsTheMajorVersionFromAPackageVersionName() {
        assertEquals(124, WebViewRequirement.majorOfVersionName("124.0.6367.82"))
        assertEquals(99, WebViewRequirement.majorOfVersionName("99"))
        assertEquals(123, WebViewRequirement.majorOfVersionName("v123.0 beta"))
        assertNull(WebViewRequirement.majorOfVersionName(null))
        assertNull(WebViewRequirement.majorOfVersionName(""))
        assertNull(WebViewRequirement.majorOfVersionName("unknown"))
    }

    @Test
    fun readsTheMajorVersionFromAUserAgent() {
        val agent =
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
                "Version/4.0 Chrome/122.0.6261.64 Mobile Safari/537.36"
        assertEquals(122, WebViewRequirement.majorOfUserAgent(agent))
        assertNull(WebViewRequirement.majorOfUserAgent("Mozilla/5.0 (Linux; Android 7.0)"))
        assertNull(WebViewRequirement.majorOfUserAgent(null))
    }

    @Test
    fun theMinimumItselfIsSupportedAndOneBelowIsTooOld() {
        assertEquals(Verdict.Supported(min), WebViewRequirement.verdict(min))
        assertEquals(Verdict.Supported(min + 30), WebViewRequirement.verdict(min + 30))
        assertEquals(Verdict.TooOld(min - 1), WebViewRequirement.verdict(min - 1))
        assertEquals(Verdict.TooOld(60), WebViewRequirement.verdict(60))
    }

    @Test
    fun anUnreadableVersionIsNotBlocked() {
        assertEquals(Verdict.Unknown, WebViewRequirement.verdict(null))
    }

    @Test
    fun theMinimumIsAnArgumentSoTheBoundaryIsTestedAnywhere() {
        assertEquals(Verdict.TooOld(9), WebViewRequirement.verdict(9, minimum = 10))
        assertEquals(Verdict.Supported(10), WebViewRequirement.verdict(10, minimum = 10))
    }

    // The tests run in frontend/android/app, so the web side is two folders up.
    private fun web(path: String): String = File("../../$path").readText()

    private fun chromeTargets(source: String, option: String): List<Int> = Regex("""\b$option:\s*(\[[^\]]*]|"[^"]*")""").findAll(source)
        .flatMap { Regex("""chrome(\d+)""").findAll(it.groupValues[1]) }
        .map { it.groupValues[1].toInt() }
        .toList()

    @Test
    fun theMobileBundleIsBuiltForExactlyTheMinimumChromium() {
        val vite = web("vite.mobile.config.ts")
        assertEquals("script target", listOf(min), chromeTargets(vite, "target"))
        assertEquals("css target", listOf(min), chromeTargets(vite, "cssTarget"))
    }

    @Test
    fun capacitorChecksTheSameMinimum() {
        val declared = Regex("""minWebViewVersion:\s*(\d+)""").find(web("capacitor.config.ts"))
        assertTrue("capacitor.config.ts sets android.minWebViewVersion", declared != null)
        assertEquals(min, declared!!.groupValues[1].toInt())
    }

    @Test
    fun theExplanationExistsInBothLanguagesAndNamesBothVersions() {
        val placeholders = Regex("%\\d[$]d")
        listOf("values", "values-en").forEach { dir ->
            val strings = File("src/main/res/$dir/strings.xml").readText()
            val body = Regex("""<string name="webview_too_old_body">([^<]*)</string>""").find(strings)
            assertTrue("$dir has the body", body != null)
            assertEquals(
                "$dir names required and installed version",
                listOf("%1\$d", "%2\$d"),
                placeholders.findAll(body!!.groupValues[1]).map {
                    it.value
                }.toList(),
            )
            assertTrue("$dir has the title", strings.contains("""name="webview_too_old_title""""))
        }
    }
}
