package com.rong.billcapture

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 采集与发送日志，保留最近 120 行，方便在手机上排查漏单。 */
object Logs {
    private const val FILE = "capture.log"
    private const val MAX_LINES = 120
    private val stamp = SimpleDateFormat("MM-dd HH:mm:ss", Locale.CHINA)

    fun append(context: Context, message: String) {
        val target = File(context.filesDir, FILE)
        val entry = "${stamp.format(Date())}  $message"
        val lines = if (target.exists()) target.readLines().toMutableList() else mutableListOf()
        lines.add(entry)
        while (lines.size > MAX_LINES) lines.removeAt(0)
        target.writeText(lines.joinToString("\n") + "\n")
    }

    fun tail(context: Context, count: Int = 12): String {
        val target = File(context.filesDir, FILE)
        if (!target.exists()) return "还没有记录"
        return target.readLines().takeLast(count).joinToString("\n")
    }
}
