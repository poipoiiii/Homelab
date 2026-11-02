package com.rong.billcapture

import android.content.Context
import android.os.Build
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 上报：原文进队列后立刻尝试发送，失败留待下次补发。 */
object Uploader {
    private const val TIMEOUT = 10_000

    private fun labelOf(source: String) = if (source == "sms") "短信" else "通知"

    fun submit(context: Context, source: String, sender: String, text: String) {
        val payload = JSONObject().apply {
            put("source", source)
            put("sender", sender.take(64))
            put("text", text.take(2000))
            put("ts", System.currentTimeMillis() / 1000)
            put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
        }
        val pending = Outbox.add(context, payload)
        Logs.append(context, "采集${labelOf(source)}：${text.replace("\n", " ").take(28)}（队列 $pending）")
        flushAsync(context)
    }

    fun flushAsync(context: Context, onDone: ((String) -> Unit)? = null) {
        val appContext = context.applicationContext
        Thread {
            val summary = flush(appContext)
            onDone?.invoke(summary)
        }.start()
    }

    @Synchronized
    fun flush(context: Context): String {
        val server = Prefs.serverUrl(context).trimEnd('/')
        val token = Prefs.token(context)
        if (server.isEmpty() || token.isEmpty()) return "未配置服务器或凭证"

        val queued = Outbox.takeAll(context)
        if (queued.isEmpty()) return "队列为空"

        val remaining = mutableListOf<JSONObject>()
        var sent = 0
        var firstError = ""
        for (payload in queued) {
            if (firstError.isNotEmpty()) {
                remaining.add(payload)
                continue
            }
            val error = post("$server/api/ingest", token, payload.toString())
            if (error == null) {
                sent += 1
            } else {
                firstError = error
                remaining.add(payload)
            }
        }
        Outbox.write(context, remaining)

        val summary = when {
            sent == 0 -> "发送失败：$firstError"
            remaining.isEmpty() -> "已上报 $sent 条"
            else -> "已上报 $sent 条，剩 ${remaining.size} 条待补发"
        }
        Logs.append(context, summary)
        return summary
    }

    fun ping(context: Context): String {
        val server = Prefs.serverUrl(context).trimEnd('/')
        val token = Prefs.token(context)
        if (server.isEmpty() || token.isEmpty()) return "先填服务器地址和上报凭证"

        var connection: HttpURLConnection? = null
        return try {
            connection = (URL("$server/api/ingest/ping").openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = TIMEOUT
                readTimeout = TIMEOUT
                setRequestProperty("X-Ingest-Token", token)
            }
            val code = connection.responseCode
            if (code !in 200..299) {
                val detail = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                "连接失败：HTTP $code ${detail.take(120)}"
            } else {
                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val pending = runCatching { JSONObject(body).optInt("pending", -1) }.getOrDefault(-1)
                "连接成功 · 服务端待确认 $pending 条"
            }
        } catch (error: Exception) {
            "连接失败：${error.message ?: error.javaClass.simpleName}"
        } finally {
            connection?.disconnect()
        }
    }

    private fun post(url: String, token: String, body: String): String? {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = TIMEOUT
                readTimeout = TIMEOUT
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("X-Ingest-Token", token)
            }
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            if (code in 200..299) {
                null
            } else {
                val detail = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                "HTTP $code ${detail.take(160)}".trim()
            }
        } catch (error: Exception) {
            error.message ?: error.javaClass.simpleName
        } finally {
            connection?.disconnect()
        }
    }
}
