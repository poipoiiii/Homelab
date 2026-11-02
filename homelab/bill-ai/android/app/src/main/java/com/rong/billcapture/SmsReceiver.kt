package com.rong.billcapture

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/** 银行/支付短信入口。只做本地预过滤，解析全部交给服务端。 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        if (!Prefs.smsEnabled(context)) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (messages.isEmpty()) return

        val sender = messages.first().displayOriginatingAddress.orEmpty()
        val body = messages.joinToString("") { it.displayMessageBody.orEmpty() }
        if (body.isBlank()) return
        if (!CapturedFilter.isTransactionText(body)) return

        val appContext = context.applicationContext
        val pending = goAsync()
        Thread {
            try {
                Uploader.submit(appContext, "sms", sender, body)
            } finally {
                pending.finish()
            }
        }.start()
    }
}
