package com.roadlake.sidekick.widget

import android.content.Context
import android.content.res.Configuration
import java.util.Locale

/**
 * The language of the widget's texts. The app's language is its own setting (Swedish by default, never the system
 * language), so the page tells the widget with `setLocale` and the widget draws its strings in that language.
 */
internal object WidgetLocale {
    const val DEFAULT = "sv"
    private val SUPPORTED = setOf("sv", "en")

    /** The tag if it is one the app has texts for, else null. */
    fun parse(tag: String?): String? = tag?.takeIf { it in SUPPORTED }

    /** What to draw in: the saved tag, or Swedish when nothing (valid) is saved. */
    fun resolve(saved: String?): String = parse(saved) ?: DEFAULT

    /** [context] with its resources in the language of [tag], for `getString` and the date format. */
    fun localized(context: Context, tag: String): Context {
        val configuration = Configuration(context.resources.configuration)
        configuration.setLocale(Locale.forLanguageTag(tag))
        return context.createConfigurationContext(configuration)
    }
}

/** The saved tag in a small preferences file of its own. Not a secret; it is not part of the pairing. */
internal class WidgetLocaleStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun get(): String = WidgetLocale.resolve(prefs.getString(KEY, null))

    fun set(tag: String) {
        prefs.edit().putString(KEY, tag).apply()
    }

    private companion object {
        const val FILE = "sidekick_widget"
        const val KEY = "locale"
    }
}
