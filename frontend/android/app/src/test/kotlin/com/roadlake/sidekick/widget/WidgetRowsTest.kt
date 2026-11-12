package com.roadlake.sidekick.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WidgetRowsTest {
    // Fixed parts: padding 2 x 8 + header 48 + footer 20 + a 2 dp safety margin = 86 dp;
    // one row is 48 dp (a touch target); the notice line takes another 20 dp.
    private val chrome = 86f
    private val row = 48f

    @Test
    fun theConstantsAreTheMeasuredHeights() {
        assertEquals(row, ROW_HEIGHT.value)
        assertEquals(chrome, CHROME_HEIGHT.value)
        assertEquals(20f, FOOTER_HEIGHT.value)
        assertEquals("the footer with \"+N till\" is a touch target", 48f, MORE_FOOTER_HEIGHT.value)
    }

    @Test
    fun smallestSizeStillShowsOneRow() {
        assertEquals(1, rowsForHeight(0f, withNotice = false))
        assertEquals(1, rowsForHeight(110f, withNotice = false))
    }

    @Test
    fun rowsFollowTheHeightInWholeRows() {
        assertEquals(1, rowsForHeight(chrome + row - 0.1f, withNotice = false))
        assertEquals(1, rowsForHeight(chrome + row, withNotice = false))
        assertEquals(2, rowsForHeight(chrome + 2 * row, withNotice = false))
        assertEquals(4, rowsForHeight(chrome + 4 * row, withNotice = false))
        assertEquals(4, rowsForHeight(chrome + 5 * row - 0.1f, withNotice = false))
    }

    @Test
    fun aTallWidgetIsNotCappedAtSevenRows() {
        assertEquals(10, rowsForHeight(chrome + 10 * row, withNotice = false))
    }

    @Test
    fun theNoticeLineTakesRoomFromTheRows() {
        assertEquals(3, rowsForHeight(chrome + 3 * row + 20f, withNotice = true))
        assertEquals(2, rowsForHeight(chrome + 3 * row + 19f, withNotice = true))
    }

    // Heights in dp as the launcher reports them: the emulator's 4x2 widget is 184.4 dp tall and its 4x4 widget 384.8 dp;
    // 343 dp is a taller phone's 4x4. At 183 and 184.4 the third row must fit (it left a row of empty space before).
    @Test
    fun smallFourByTwoAndFourByFourWidgetsFillTheirHeight() {
        assertEquals(1, rowsForHeight(110f, withNotice = false))
        assertEquals(1, rowsForHeight(150f, withNotice = false))
        assertEquals(2, rowsForHeight(183f, withNotice = false))
        assertEquals(2, rowsForHeight(184.38f, withNotice = false))
        assertEquals(5, rowsForHeight(343f, withNotice = false))
        assertEquals(6, rowsForHeight(384.76f, withNotice = false))
    }

    // The rest of the height (up to a row short of the next declared layout) goes to the rows only when the tasks fill the
    // layout; with fewer tasks they keep their height instead of growing into a few tall rows.
    @Test
    fun theRowsShareTheRestOfTheHeightOnlyWhenTheTasksFillTheLayout() {
        assertTrue(stretchesRows(taskCount = 8, rowsThatFit = 8))
        assertTrue(stretchesRows(taskCount = 20, rowsThatFit = 8))
        assertTrue(!stretchesRows(taskCount = 7, rowsThatFit = 8))
        assertTrue(!stretchesRows(taskCount = 0, rowsThatFit = 1))
    }

    // Between two declared layouts the real height exceeds the layout drawn by less than a row, so the rows always end up
    // rows end up between one and two row heights tall when the layout has a single row, and never below one.
    @Test
    fun theHeightLeftOverByTheChosenLayoutIsLessThanOneRow() {
        for (actual in listOf(134f, 145.9f, 183f, 184.38f, 220f, 343f, 384.76f, 400f)) {
            val layout = sizedHeights().lastOrNull { it <= actual } ?: sizedHeights().first()
            val rows = rowsForHeight(layout, withNotice = false)
            val rest = actual - (CHROME_HEIGHT.value + rows * ROW_HEIGHT.value)
            assertTrue("at $actual dp: $rest dp left over", rest in 0f..ROW_HEIGHT.value)
        }
    }

    // The rows plus the footer never need more than the height: the last row is clear of the footer by the safety margin.
    @Test
    fun theDrawnRowsAndChromeNeverExceedTheHeight() {
        for (height in listOf(134f, 150f, 183f, 184.38f, 343f, 384.76f, 600f)) {
            val rows = rowsForHeight(height, withNotice = false)
            val used = (PADDING * 2 + HEADER_HEIGHT + FOOTER_HEIGHT).value + rows * ROW_HEIGHT.value
            assertTrue("at $height dp: $used dp used", used + SAFETY_MARGIN.value <= height)
        }
    }

    @Test
    fun aDeclaredLayoutExistsForEveryRowCountAndHoldsExactlyThatMany() {
        val heights = sizedHeights()
        assertEquals((1..12).toList(), heights.map { rowsForHeight(it, withNotice = false) })
        assertEquals("the smallest layout is the widget's minHeight: one row and the 48 dp footer", 162f, heights.first())
        assertTrue("RemoteViews takes at most 16 sized layouts", heights.size <= 16)
    }

    // The system shows the tallest declared layout that fits the real height (the smallest when none does).
    private fun rowsDrawnAt(actualDp: Float): Int {
        val layout = sizedHeights().lastOrNull { it <= actualDp } ?: sizedHeights().first()
        return rowsForHeight(layout, withNotice = false)
    }

    @Test
    fun theLayoutTheSystemPicksDrawsAsManyWholeRowsAsTheRealHeightHolds() {
        for (actual in listOf(100f, 110f, 150f, 183f, 184.38f, 343f, 384.76f, 400f, 528f, 900f)) {
            assertEquals("at $actual dp", minOf(rowsForHeight(actual, withNotice = false), 12), rowsDrawnAt(actual))
        }
        assertEquals(2, rowsDrawnAt(183f))
        assertEquals(5, rowsDrawnAt(343f))
        assertEquals(6, rowsDrawnAt(384.76f))
    }

    // widget_preview.xml (the picker's static preview) draws its header and rows at the heights of the widget; the header
    // and the rows are both ROW_HEIGHT, so every fixed height and width in the file must be that.
    @Test
    fun thePreviewLayoutUsesTheSameRowAndHeaderHeight() {
        assertEquals(HEADER_HEIGHT, ROW_HEIGHT)
        val xml = java.io.File("src/main/res/layout/widget_preview.xml").readText()
        val heights = Regex("""android:layout_height="(\d+)dp"""").findAll(xml).map { it.groupValues[1].toInt() }.toList()
        assertTrue("the header and its rows are declared", heights.size >= 4)
        heights.forEach { assertEquals(ROW_HEIGHT.value.toInt(), it) }
        val widths = Regex("""android:layout_width="(\d+)dp"""").findAll(xml).map { it.groupValues[1].toInt() }.filter { it != 0 }.toList()
        widths.forEach { assertEquals(ROW_HEIGHT.value.toInt(), it) }
    }

    // The tappable parts of the widget (refresh, the circle, the task, Undo, "+N till") are at least 48 dp square or tall.
    @Test
    fun theTouchTargetsAreAtLeast48dp() {
        assertEquals(48f, MIN_TOUCH_TARGET.value)
        assertTrue(HEADER_HEIGHT >= MIN_TOUCH_TARGET)
        assertTrue(ROW_HEIGHT >= MIN_TOUCH_TARGET)
        assertTrue(MORE_FOOTER_HEIGHT >= MIN_TOUCH_TARGET)
    }

    // "+N till" is a 48 dp target (ua-5): the footer is that tall when something is hidden, and the rows give way for it.
    @Test
    fun theFooterGrowsToATouchTargetOnlyWhenSomethingIsHidden() {
        // Room for 3 rows with the plain footer: all 3 tasks (and the total) fit, so the footer stays a plain line.
        val h = chrome + 3 * row
        assertEquals(3, layoutRows(h, withNotice = false, taskCount = 3, total = 3).rows)
        assertEquals(0, layoutRows(h, withNotice = false, taskCount = 3, total = 3).hidden)
        // The same height with a fourth task: 28 dp of the rows go to the footer, so 2 rows and "+2 till".
        val more = layoutRows(h, withNotice = false, taskCount = 4, total = 4)
        assertEquals(2, more.rows)
        assertEquals(2, more.hidden)
    }

    @Test
    fun theTotalCountsTasksThatWereNeverRead() {
        val layout = layoutRows(chrome + 3 * row, withNotice = false, taskCount = 3, total = 9)
        assertEquals(2, layout.rows)
        assertEquals(7, layout.hidden)
    }

    @Test
    fun aListThatFitsWithThePlainFooterNeverLosesARowToTheTallOne() {
        for (n in 1..12) {
            val h = chrome + n * row
            val layout = layoutRows(h, withNotice = false, taskCount = n, total = n)
            assertEquals("$n tasks at $h dp", n, layout.rows)
            assertEquals(0, layout.hidden)
        }
    }

    // Whatever is drawn fits: rows, header, padding, the notice line when shown and the footer that "+N till" needs.
    @Test
    fun theRowsAndTheTallFooterNeverExceedTheHeightOfADeclaredLayout() {
        for (h in sizedHeights()) {
            for (withNotice in listOf(false)) {
                val layout = layoutRows(h, withNotice, taskCount = 20, total = 30)
                val footer = if (layout.hidden > 0) MORE_FOOTER_HEIGHT.value else FOOTER_HEIGHT.value
                val used = PADDING.value * 2 + HEADER_HEIGHT.value + footer + layout.rows * ROW_HEIGHT.value
                assertTrue("at $h dp: ${layout.rows} rows use $used dp", used + SAFETY_MARGIN.value <= h)
            }
        }
    }

    @Test
    fun theSmallestLayoutHoldsOneRowAndTheTargetFooterWithoutClipping() {
        val h = sizedHeights().first()
        val layout = layoutRows(h, withNotice = false, taskCount = 5, total = 5)
        assertEquals(1, layout.rows)
        assertEquals(4, layout.hidden)
        assertTrue(PADDING.value * 2 + HEADER_HEIGHT.value + MORE_FOOTER_HEIGHT.value + row + SAFETY_MARGIN.value <= h)
    }
}

class WidgetLocaleTest {
    @Test
    fun swedishIsTheDefaultWhenNothingIsSaved() {
        assertEquals("sv", WidgetLocale.resolve(null))
        assertEquals("sv", WidgetLocale.DEFAULT)
    }

    @Test
    fun aSavedSupportedTagIsKept() {
        assertEquals("en", WidgetLocale.resolve("en"))
        assertEquals("sv", WidgetLocale.resolve("sv"))
    }

    @Test
    fun anUnknownSavedTagFallsBackToSwedish() {
        assertEquals("sv", WidgetLocale.resolve("de"))
        assertEquals("sv", WidgetLocale.resolve(""))
    }

    @Test
    fun onlySvAndEnAreAccepted() {
        assertEquals("en", WidgetLocale.parse("en"))
        assertNull(WidgetLocale.parse("EN"))
        assertNull(WidgetLocale.parse("sv-SE"))
        assertNull(WidgetLocale.parse(null))
    }
}
