package com.roadlake.sidekick.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerUrlTest {
    private fun refused(raw: String, cleartext: Boolean = false) {
        val error = assertThrows(CompanionException::class.java) { ServerUrl.parse(raw, cleartext) }
        assertEquals("invalid_server_url", error.code)
    }

    @Test
    fun acceptsHttpsOriginsAndNormalisesThem() {
        assertEquals("https://sidekick.example", ServerUrl.parse("https://sidekick.example", false).origin)
        assertEquals("https://sidekick.example", ServerUrl.parse("  HTTPS://Sidekick.Example/  ", false).origin)
        assertEquals("https://sidekick.example:8443", ServerUrl.parse("https://sidekick.example:8443", false).origin)
        assertEquals("sidekick.example", ServerUrl.parse("https://sidekick.example", false).host)
    }

    @Test
    fun refusesCleartextToRealHostsInEveryBuild() {
        refused("http://sidekick.example")
        refused("http://sidekick.example", cleartext = true)
        refused("http://192.168.1.10:8101", cleartext = true)
    }

    @Test
    fun refusesCleartextToLocalHostsInTheReleaseBuild() {
        refused("http://10.0.2.2:8101")
        refused("http://localhost:8101")
    }

    @Test
    fun acceptsCleartextToLocalHostsInTheDebugBuild() {
        assertEquals("http://10.0.2.2:8101", ServerUrl.parse("http://10.0.2.2:8101", true).origin)
        assertEquals("http://localhost:8101", ServerUrl.parse("http://localhost:8101", true).origin)
        assertEquals("http://127.0.0.1:8101", ServerUrl.parse("http://127.0.0.1:8101", true).origin)
    }

    @Test
    fun refusesOtherSchemesAndMissingHosts() {
        refused("")
        refused("   ")
        refused("sidekick.example")
        refused("ftp://sidekick.example")
        refused("file:///etc/passwd")
        refused("javascript:alert(1)")
        refused("https://")
        refused("https:///companion")
    }

    @Test
    fun refusesCredentialsPathsQueriesAndFragments() {
        refused("https://user:pass@sidekick.example")
        refused("https://user@sidekick.example")
        refused("https://sidekick.example/app")
        refused("https://sidekick.example/?x=1")
        refused("https://sidekick.example#frag")
    }

    @Test
    fun refusesLookAlikeHostsThatParseToAnotherHost() {
        // "good.example" is the userinfo here, the real host is evil.example.
        refused("https://good.example@evil.example")
        refused("https://evil.example\\@good.example")
        refused("https://good.example:443@evil.example")
    }

    @Test
    fun refusesBadPortsAndOverlongInput() {
        refused("https://sidekick.example:0")
        refused("https://sidekick.example:99999")
        refused("https://" + "a".repeat(300) + ".example")
    }
}
