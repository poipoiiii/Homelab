package com.rong.billcapture

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/** 支付宝/微信/银行 App 的支付通知。需要在系统设置里手动授予「通知使用权」。 */
class NotificationCapture : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val packageName = sbn?.packageName ?: return
        if (packageName == this.packageName) return
        if (!Prefs.notificationEnabled(this)) return
        if (!Prefs.allApps(this) && packageName !in CapturedFilter.PACKAGES) return
        if (sbn.isOngoing) return

        val extras = sbn.notification?.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val body = (
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
                ?: extras.getCharSequence(Notification.EXTRA_TEXT)
            )?.toString().orEmpty()
        val lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            ?.joinToString("\n").orEmpty()

        val text = listOf(title, body, lines).filter { it.isNotBlank() }.joinToString("\n")
        if (text.isBlank()) return
        if (!CapturedFilter.isTransactionText(text)) return

        Uploader.submit(applicationContext, "notification", packageName, text)
    }
}
