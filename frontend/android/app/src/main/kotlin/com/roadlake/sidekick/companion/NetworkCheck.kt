package com.roadlake.sidekick.companion

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * Whether the phone has a network that can reach the internet at all ([UrlConnectionTransport.hasNetwork]). Only "no
 * network" is decided here: a network the system has not validated (a captive portal, a VPN, a server on the local
 * network) is still tried, with the transport's normal timeouts. A phone that cannot answer the question is treated as
 * online, so a check that fails never blocks a request.
 */
fun networkCheck(context: Context): () -> Boolean {
    val app = context.applicationContext
    return check@{
        try {
            val manager = app.getSystemService(ConnectivityManager::class.java) ?: return@check true
            val network = manager.activeNetwork ?: return@check false
            val capabilities = manager.getNetworkCapabilities(network) ?: return@check false
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        } catch (_: SecurityException) {
            true
        }
    }
}
