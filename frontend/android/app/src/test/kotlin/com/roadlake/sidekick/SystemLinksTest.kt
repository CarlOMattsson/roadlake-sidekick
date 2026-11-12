package com.roadlake.sidekick

import org.junit.Assert.assertEquals
import org.junit.Test

class SystemLinksTest {
    @Test
    fun theStoreAddressesAreBuiltFromThePackageName() {
        assertEquals("market://details?id=io.heckel.ntfy", SystemLinks.marketUri(SystemLinks.NTFY_PACKAGE))
        assertEquals(
            "https://play.google.com/store/apps/details?id=com.google.android.webview",
            SystemLinks.playWebUri(SystemLinks.DEFAULT_WEBVIEW_PACKAGE),
        )
    }

    @Test
    fun theInstalledWebViewProviderIsUpdatedWhenItsNameIsWellFormed() {
        assertEquals("com.android.chrome", SystemLinks.webViewPackage("com.android.chrome"))
    }

    @Test
    fun aMissingOrOddProviderFallsBackToTheStockWebView() {
        assertEquals(SystemLinks.DEFAULT_WEBVIEW_PACKAGE, SystemLinks.webViewPackage(null))
        assertEquals(SystemLinks.DEFAULT_WEBVIEW_PACKAGE, SystemLinks.webViewPackage(""))
        assertEquals(SystemLinks.DEFAULT_WEBVIEW_PACKAGE, SystemLinks.webViewPackage("nodots"))
        assertEquals(SystemLinks.DEFAULT_WEBVIEW_PACKAGE, SystemLinks.webViewPackage("a.b&x=1"))
    }
}
