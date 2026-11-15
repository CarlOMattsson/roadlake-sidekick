package com.roadlake.sidekick.share

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SharedContentTest {
    private fun share(text: String?, subject: String? = null, type: String? = "text/plain", action: String? = SharedContent.ACTION_SEND) =
        SharedContent.parse(action, type, subject, text)

    @Test
    fun aBrowserShareTakesThePageTitleAndKeepsTheAddress() {
        val shared = share("https://example.org/article?id=7", subject = "How the harbour was built")!!
        assertEquals("How the harbour was built", shared.title)
        assertEquals("https://example.org/article?id=7", shared.text)
        assertEquals("https://example.org/article?id=7", shared.link)
    }

    @Test
    fun aBareAddressWithoutASubjectIsTitledByItsHost() {
        val shared = share("https://www.example.org/a/b")!!
        assertEquals("example.org", shared.title)
        assertEquals("https://www.example.org/a/b", shared.link)
    }

    @Test
    fun aTextWithAnAddressInItIsTitledByItsFirstLineWithoutTheAddress() {
        val shared = share("Read this one later https://example.org/post, it is good\nSecond line")!!
        assertEquals("Read this one later , it is good", shared.title)
        assertEquals("https://example.org/post", shared.link)
        assertEquals("Read this one later https://example.org/post, it is good\nSecond line", shared.text)
    }

    @Test
    fun punctuationAfterTheAddressIsNotPartOfIt() {
        assertEquals("https://example.org/x", share("See (https://example.org/x).")!!.link)
        assertEquals("https://example.org/x", share("https://example.org/x!")!!.link)
    }

    @Test
    fun onlyWebAddressesAreOfferedAsLinks() {
        assertNull(share("javascript:alert(1) and ftp://example.org/file")!!.link)
        assertNull(share("http://")!!.link)
    }

    @Test
    fun plainTextWithoutAnAddressHasNoLinkAndAShortTitle() {
        val shared = share("  Buy a birthday present for Mum  ")!!
        assertEquals("Buy a birthday present for Mum", shared.title)
        assertEquals("Buy a birthday present for Mum", shared.text)
        assertNull(shared.link)
    }

    @Test
    fun aLongFirstLineIsCutAtAWordWithAnEllipsis() {
        val shared = share("word ".repeat(60))!!
        assertTrue(shared.title.length <= 100)
        assertTrue(shared.title.endsWith("word…"))
    }

    @Test
    fun aSubjectAloneIsEnough() {
        val shared = share(null, subject = "Meeting notes")!!
        assertEquals("Meeting notes", shared.title)
        assertEquals("", shared.text)
    }

    @Test
    fun aSubjectIsOneLineAndAtMostTwoHundredCharacters() {
        val shared = share("text", subject = "Line one\n  line two " + "x".repeat(300))!!
        assertFalse(shared.title.contains('\n'))
        assertEquals(SharedContent.MAX_SUBJECT, shared.title.length)
    }

    @Test
    fun theTextIsCutWithoutSplittingAnEmoji() {
        val shared = share("a" + "😀".repeat(SharedContent.MAX_TEXT))!!
        assertTrue(shared.text.length <= SharedContent.MAX_TEXT)
        assertFalse(Character.isHighSurrogate(shared.text.last()))
    }

    @Test
    fun anythingThatIsNotATextShareIsRefused() {
        assertNull(share("hello", action = "android.intent.action.VIEW"))
        assertNull(share("hello", action = null))
        assertNull(share("hello", type = "image/png"))
        assertNull(share("hello", type = null))
        assertNull(share(null))
        assertNull(share("   ", subject = "  "))
    }

    @Test
    fun theTextTypeMayCarryParametersAndAnyCase() {
        assertEquals("hello", share("hello", type = "Text/Plain; charset=utf-8")!!.text)
    }
}
