package com.rong.billcapture

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock

/** 每 30 分钟补发一次队列，避免短信来时正好没网导致长期积压。 */
class FlushReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Uploader.flushAsync(context.applicationContext)
    }

    companion object {
        private const val INTERVAL = 30 * 60 * 1000L

        fun schedule(context: Context) {
            val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val intent = Intent(context, FlushReceiver::class.java)
            val pending = PendingIntent.getBroadcast(
                context,
                0,
                intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            alarm.setInexactRepeating(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + INTERVAL,
                INTERVAL,
                pending,
            )
        }
    }
}
