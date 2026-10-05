package com.wlukaz.loseitsync

import android.content.Context

/** Thin wrapper over SharedPreferences for the user's sync configuration and last result. */
class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("loseit_sync", Context.MODE_PRIVATE)

    var scriptUrl: String
        get() = prefs.getString("script_url", "")!!
        set(v) = prefs.edit().putString("script_url", v.trim()).apply()

    var token: String
        get() = prefs.getString("token", "")!!
        set(v) = prefs.edit().putString("token", v.trim()).apply()

    /** Health Connect data origin to keep; blank means every app's records. */
    var sourcePackage: String
        get() = prefs.getString("source_package", LOSEIT_PACKAGE)!!
        set(v) = prefs.edit().putString("source_package", v.trim()).apply()

    var backfillDays: Int
        get() = prefs.getInt("backfill_days", 30)
        set(v) = prefs.edit().putInt("backfill_days", v).apply()

    var lastStatus: String
        get() = prefs.getString("last_status", "Never synced")!!
        set(v) = prefs.edit().putString("last_status", v).apply()

    val isConfigured: Boolean
        get() = scriptUrl.startsWith("https://") && token.isNotEmpty()

    companion object {
        const val LOSEIT_PACKAGE = "com.fitnow.loseit"
    }
}
