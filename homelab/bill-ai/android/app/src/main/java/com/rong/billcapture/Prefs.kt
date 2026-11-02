package com.rong.billcapture

import android.content.Context

/** 本地配置：服务器地址、上报凭证与采集开关。 */
object Prefs {
    private const val FILE = "capture"
    private const val KEY_SERVER = "server_url"
    private const val KEY_TOKEN = "ingest_token"
    private const val KEY_SMS = "capture_sms"
    private const val KEY_NOTIFICATION = "capture_notification"
    private const val KEY_ALL_APPS = "capture_all_apps"

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun serverUrl(context: Context): String = prefs(context).getString(KEY_SERVER, "").orEmpty().trim()

    fun token(context: Context): String = prefs(context).getString(KEY_TOKEN, "").orEmpty().trim()

    fun smsEnabled(context: Context): Boolean = prefs(context).getBoolean(KEY_SMS, true)

    fun notificationEnabled(context: Context): Boolean = prefs(context).getBoolean(KEY_NOTIFICATION, true)

    fun allApps(context: Context): Boolean = prefs(context).getBoolean(KEY_ALL_APPS, false)

    fun save(
        context: Context,
        serverUrl: String,
        token: String,
        sms: Boolean,
        notification: Boolean,
        allApps: Boolean,
    ) {
        prefs(context).edit()
            .putString(KEY_SERVER, serverUrl.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .putBoolean(KEY_SMS, sms)
            .putBoolean(KEY_NOTIFICATION, notification)
            .putBoolean(KEY_ALL_APPS, allApps)
            .apply()
    }
}
