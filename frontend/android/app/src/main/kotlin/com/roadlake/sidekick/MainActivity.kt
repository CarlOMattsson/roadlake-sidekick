package com.roadlake.sidekick

import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.WebView
import android.widget.Button
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.getcapacitor.BridgeActivity
import com.roadlake.sidekick.companion.SidekickNativePlugin
import com.roadlake.sidekick.push.PushChannels
import com.roadlake.sidekick.widget.WidgetLocale
import com.roadlake.sidekick.widget.WidgetLocaleStore

class MainActivity : BridgeActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Local plugins are registered before the bridge is created.
        registerPlugin(SidekickNativePlugin::class.java)
        super.onCreate(savedInstanceState)
        PushChannels.create(this)
    }

    // BridgeActivity.onCreate ends in load(), which creates the bridge and loads the page. An installed WebView older than
    // the page's build target (WebViewRequirement) would draw a blank screen, so the explanation replaces it. The bridge
    // stays null, which BridgeActivity's lifecycle handles.
    override fun load() {
        val verdict = WebViewRequirement.check(this)
        if (verdict is WebViewRequirement.Verdict.TooOld) {
            showWebViewTooOld(verdict.major)
            return
        }
        super.load()
    }

    private fun showWebViewTooOld(installedMajor: Int) {
        setContentView(R.layout.webview_too_old)
        // The app's language is its own setting (Swedish by default), not the system's.
        val texts = WidgetLocale.localized(this, WidgetLocaleStore(this).get())
        findViewById<TextView>(R.id.webview_too_old_title).text = texts.getString(R.string.webview_too_old_title)
        findViewById<TextView>(R.id.webview_too_old_body).text =
            texts.getString(R.string.webview_too_old_body, WebViewRequirement.MIN_CHROMIUM_MAJOR, installedMajor)
        // The way out of this screen: the store page of the WebView provider (Chrome on phones that use it), else the stock WebView.
        findViewById<Button>(R.id.webview_too_old_update).apply {
            text = texts.getString(R.string.webview_too_old_update)
            setOnClickListener {
                val installed = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    WebView.getCurrentWebViewPackage()?.packageName
                } else {
                    null
                }
                SystemLinks.openStore(this@MainActivity, SystemLinks.webViewPackage(installed))
            }
        }
        // Edge-to-edge: keep the text out from under the system bars.
        val root = findViewById<View>(R.id.webview_too_old_root)
        val padding = root.paddingLeft
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(padding + bars.left, padding + bars.top, padding + bars.right, padding + bars.bottom)
            insets
        }
        SystemBarStyle.apply(this, resources.configuration)
    }

    // uiMode is in the manifest's configChanges, so a theme change reaches here instead of recreating the activity.
    // Capacitor's plugins ran in super (SystemBars re-applies its stale style); the right contrast is set after it.
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        SystemBarStyle.apply(this, newConfig)
    }

    override fun onResume() {
        super.onResume()
        SidekickRuntime.get(this).foreground.set(this)
    }

    override fun onPause() {
        SidekickRuntime.get(this).foreground.clear(this)
        super.onPause()
    }
}
