package com.roadlake.sidekick.widget

import android.content.res.Configuration
import com.roadlake.sidekick.SystemBarStyle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The widget's declared size and picker texts, the app's pairing-link filter, and the bar contrast: plain files and bits. */
class WidgetResourcesTest {
    private fun file(path: String): String = File("src/main/$path").readText()

    private fun attr(xml: String, name: String): String = Regex("""android:$name="([^"]*)"""").find(xml)!!.groupValues[1]

    @Test
    fun theDefaultSizeIsFourByTwoCells() {
        val info = file("res/xml/today_widget_info.xml")
        assertEquals("4", attr(info, "targetCellWidth"))
        assertEquals("2", attr(info, "targetCellHeight"))
        // The launcher's cell formula: n cells are 70n - 30 dp. The height is the smallest layout: padding, header, one row, the 48 dp "+N till" footer.
        assertEquals("250dp", attr(info, "minWidth"))
        assertEquals("162dp", attr(info, "minHeight"))
        assertEquals("162dp", attr(info, "minResizeHeight"))
    }

    @Test
    fun thePickerPreviewShowsTheHeaderAndTwoRowsLikeTheDefaultSize() {
        val preview = file("res/layout/widget_preview.xml")
        assertEquals(1, Regex("@string/widget_preview_title").findAll(preview).count())
        assertEquals("two rows", 2, Regex("@string/widget_preview_task_\\d").findAll(preview).count())
        assertTrue(preview.contains("@string/widget_preview_task_2"))
        assertFalse(preview.contains("widget_preview_task_3"))
    }

    private fun translatableNames(path: String): Set<String> = Regex("""<(?:string|plurals) name="([^"]+)"([^>]*)>""").findAll(file(path))
        .filter { "translatable=\"false\"" !in it.groupValues[2] }
        .map { it.groupValues[1] }
        .toSet()

    @Test
    fun everyTranslatableStringHasAnEnglishTextAndTheOtherWayRound() {
        val swedish = translatableNames("res/values/strings.xml")
        val english = translatableNames("res/values-en/strings.xml")
        assertEquals(emptySet<String>(), swedish - english)
        assertEquals(emptySet<String>(), english - swedish)
    }

    @Test
    fun thePickerPreviewTextsFollowTheSystemLanguage() {
        val translatable = translatableNames("res/values-en/strings.xml")
        listOf("widget_preview_title", "widget_preview_task_1", "widget_preview_task_2", "widget_preview_overdue")
            .forEach { assertTrue("$it has an English text", it in translatable) }
    }

    @Test
    fun theExpiredNoticeAndTheTaskLabelExistInBothLanguagesWithoutUserData() {
        for (path in listOf("res/values/strings.xml", "res/values-en/strings.xml")) {
            assertTrue("widget_notice_expired in $path", "widget_notice_expired" in translatableNames(path))
            assertTrue("widget_open_task in $path", "widget_open_task" in translatableNames(path))
            val text = Regex("""<string name="widget_notice_expired">([^<]*)</string>""").find(file(path))!!.groupValues[1]
            assertFalse("the notice has no placeholder for task data", text.contains("%"))
        }
    }

    @Test
    fun everyNoticeHasAFooterText() {
        for (notice in com.roadlake.sidekick.today.TodayNotice.entries) {
            assertTrue(noticeTextRes(notice) != 0)
        }
        assertEquals(
            com.roadlake.sidekick.today.TodayNotice.entries.size,
            com.roadlake.sidekick.today.TodayNotice.entries.map {
                noticeTextRes(it)
            }.toSet().size,
        )
    }

    @Test
    fun theUnpairedWidgetHasAButtonText() {
        assertTrue("widget_pair_button" in translatableNames("res/values/strings.xml"))
        assertTrue("widget_pair_button" in translatableNames("res/values-en/strings.xml"))
    }

    @Test
    fun theActivityOpensOnAPairingLinkAndNothingElseIsBrowsable() {
        val manifest = file("AndroidManifest.xml")
        val filter = Regex(
            """<intent-filter>(?:(?!</intent-filter>).)*sidekick(?:(?!</intent-filter>).)*</intent-filter>""",
            RegexOption.DOT_MATCHES_ALL,
        )
            .findAll(manifest).toList()
        assertEquals(1, filter.size)
        val text = filter[0].value
        assertTrue(text.contains("""android:scheme="sidekick""""))
        assertTrue(text.contains("""android:host="pair""""))
        assertTrue(text.contains("android.intent.category.BROWSABLE"))
        assertTrue(text.contains("android.intent.action.VIEW"))
    }

    @Test
    fun thePairingLinkIsNotAnAppLinkBecauseEveryInstallationSignsItsOwnApp() {
        val manifest = file("AndroidManifest.xml")
        // The domain is the user's own and the app is signed with the user's own key, so no assetlinks.json can verify it.
        assertFalse(manifest.contains("autoVerify"))
        assertFalse(Regex("""android:scheme="https?"""").containsMatchIn(manifest))
        assertEquals(1, Regex("android.intent.action.VIEW").findAll(manifest).count())
    }

    private fun stringText(path: String, name: String): String =
        Regex("""<string name="$name">([^<]*)</string>""").find(file(path))!!.groupValues[1]

    @Test
    fun aPendingCheckOffIsSendingNotTheTaskStatusInProgress() {
        assertEquals("Skickas…", stringText("res/values/strings.xml", "widget_pending"))
        assertEquals("Sending…", stringText("res/values-en/strings.xml", "widget_pending"))
        assertEquals("Skickas: %1\$s", stringText("res/values/strings.xml", "widget_pending_description"))
        assertEquals("Sending: %1\$s", stringText("res/values-en/strings.xml", "widget_pending_description"))
    }

    @Test
    fun theUndoAndOfflineTextsExistInBothLanguages() {
        assertEquals("Klar · Ångra", stringText("res/values/strings.xml", "widget_done_undo"))
        assertEquals("Done · Undo", stringText("res/values-en/strings.xml", "widget_done_undo"))
        assertEquals("Ångra: %1\$s", stringText("res/values/strings.xml", "widget_undo_description"))
        assertEquals("Undo: %1\$s", stringText("res/values-en/strings.xml", "widget_undo_description"))
        assertEquals("Offline · synkad %1\$s", stringText("res/values/strings.xml", "widget_offline_synced"))
        assertEquals("Offline · synced %1\$s", stringText("res/values-en/strings.xml", "widget_offline_synced"))
    }

    @Test
    fun theLicenseCoinIsGoneFromTheWidgetAndItsResourcesWithIt() {
        for (path in listOf("res/values/strings.xml", "res/values-en/strings.xml")) {
            val names = translatableNames(path)
            assertFalse("widget_license_free in $path", "widget_license_free" in names)
            assertFalse("widget_license_expired in $path", "widget_license_expired" in names)
        }
        assertFalse(File("src/main/res/drawable/ic_widget_coin.xml").exists())
    }

    // The accent follows the app's primary pair (ui/tokens.css --sk-inverse-bg / --sk-inverse-fg), not a blue of its own.
    @Test
    fun theWidgetsPrimaryColoursAreTheAppsInkAndInversePair() {
        fun hex(argb: Long) = "#%06x".format(argb and 0xFFFFFF)
        val tokens = File("../../src/features/mcp-apps/ui/tokens.css").readText()
        // Light: the inverse background is the text colour (--sk-fg) and its text the page colour (--sk-bg).
        assertTrue(tokens.contains("--sk-fg: var(--color-text-primary, light-dark(${hex(PrimaryPair.LIGHT_BG)}, "))
        assertTrue(tokens.contains("--sk-bg: var(--color-background-primary, light-dark(${hex(PrimaryPair.LIGHT_FG)}, "))
        // Dark: #ededed with #1c1c1e text, the fixed fallback of the inverse pair.
        assertTrue(tokens.contains("light-dark(var(--sk-fg), ${hex(PrimaryPair.DARK_BG)})"))
        assertTrue(tokens.contains("light-dark(var(--sk-bg), ${hex(PrimaryPair.DARK_FG)})"))
    }

    @Test
    fun theReminderSummaryHasPluralPartsInBothLanguages() {
        for (path in listOf("res/values/strings.xml", "res/values-en/strings.xml")) {
            val names = translatableNames(path)
            assertTrue("reminder_today in $path", "reminder_today" in names)
            assertTrue("reminder_overdue in $path", "reminder_overdue" in names)
            assertFalse("the old two-number string is gone from $path", "reminder_summary" in names)
        }
    }

    @Test
    fun theTooOldScreenHasAnUpdateButtonAtLeast48dp() {
        val layout = file("res/layout/webview_too_old.xml")
        assertTrue(layout.contains("@+id/webview_too_old_update"))
        assertEquals("48dp", attr(layout.substringAfter("<Button"), "minHeight"))
        assertTrue("webview_too_old_update" in translatableNames("res/values/strings.xml"))
        assertTrue("webview_too_old_update" in translatableNames("res/values-en/strings.xml"))
    }
}

class SystemBarStyleTest {
    @Test
    fun aLightPageGetsDarkIconsAndADarkPageLightOnes() {
        assertTrue(SystemBarStyle.lightBars(Configuration.UI_MODE_NIGHT_NO))
        assertFalse(SystemBarStyle.lightBars(Configuration.UI_MODE_NIGHT_YES))
    }

    @Test
    fun onlyTheNightBitsDecideNotTheOtherUiModeBits() {
        val car = Configuration.UI_MODE_TYPE_CAR
        assertFalse(SystemBarStyle.lightBars(Configuration.UI_MODE_NIGHT_YES or car))
        assertTrue(SystemBarStyle.lightBars(Configuration.UI_MODE_NIGHT_NO or car))
        // Undefined night (no setting yet) counts as light, as Capacitor's own default does.
        assertTrue(SystemBarStyle.lightBars(0))
    }
}
