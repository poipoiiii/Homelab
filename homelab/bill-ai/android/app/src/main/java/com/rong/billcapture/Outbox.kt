package com.rong.billcapture

import android.content.Context
import org.json.JSONObject
import java.io.File

/** 发送失败的原文暂存在这里，下次采集或定时任务时补发。 */
object Outbox {
    private const val FILE = "outbox.jsonl"
    private val lock = Any()

    private fun file(context: Context) = File(context.filesDir, FILE)

    private fun readAll(context: Context): List<JSONObject> {
        val target = file(context)
        if (!target.exists()) return emptyList()
        return target.readLines()
            .filter { it.isNotBlank() }
            .mapNotNull { line -> runCatching { JSONObject(line) }.getOrNull() }
    }

    private fun writeAll(context: Context, items: List<JSONObject>) {
        val target = file(context)
        if (items.isEmpty()) {
            target.delete()
            return
        }
        target.writeText(items.joinToString("\n") { it.toString() } + "\n")
    }

    fun add(context: Context, payload: JSONObject): Int = synchronized(lock) {
        file(context).appendText(payload.toString() + "\n")
        readAll(context).size
    }

    fun pending(context: Context): Int = synchronized(lock) { readAll(context).size }

    fun takeAll(context: Context): List<JSONObject> = synchronized(lock) { readAll(context) }

    fun write(context: Context, items: List<JSONObject>) = synchronized(lock) { writeAll(context, items) }
}
