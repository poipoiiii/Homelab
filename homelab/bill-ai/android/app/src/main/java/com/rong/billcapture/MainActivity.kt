package com.rong.billcapture

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import kotlin.math.roundToInt

class MainActivity : Activity() {

    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var smsSwitch: Switch
    private lateinit var notificationSwitch: Switch
    private lateinit var allAppsSwitch: Switch
    private lateinit var statusView: TextView
    private lateinit var logsView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        render()
        FlushReceiver.schedule(this)
        Uploader.flushAsync(this) { runOnUiThread { render() } }
        ensureSmsPermission()
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    // ---------------------------------------------------------------- 界面

    private fun buildContent(): View {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(color(R.color.canvas))
            fitsSystemWindows = true
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(28), dp(20), dp(40))
        }
        scroll.addView(root)

        root.addView(TextView(this).apply {
            text = "记账采集"
            textSize = 28f
            typeface = Typeface.SERIF
            setTextColor(color(R.color.ink))
        })
        root.addView(TextView(this).apply {
            text = "把银行短信和支付通知上报到「Rong的账单」，先进待入账队列，确认后才写进流水。"
            textSize = 13f
            setTextColor(color(R.color.muted))
            setLineSpacing(dp(4).toFloat(), 1f)
            layoutParams = margins(top = 6, bottom = 16)
        })

        // 服务器与凭证
        val serverCard = card()
        serverCard.addView(label("服务器地址（Tailscale 内网入口）"))
        serverInput = input("https://xxx.ts.net:8451", uri = true)
        serverCard.addView(serverInput)
        serverCard.addView(label("上报凭证 · 服务端 .env 里的 INGEST_TOKEN"))
        tokenInput = input("与服务端 INGEST_TOKEN 一致", uri = false)
        tokenInput.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        serverCard.addView(tokenInput)

        val saveButton = button("保存并测试连接", primary = true)
        saveButton.setOnClickListener { saveAndTest() }
        serverCard.addView(saveButton)

        val openButton = button("打开待入账页面")
        openButton.setOnClickListener { openInbox() }
        serverCard.addView(openButton)
        root.addView(serverCard)

        // 采集开关
        val switchCard = card()
        smsSwitch = switchRow("采集短信", Prefs.smsEnabled(this))
        notificationSwitch = switchRow("采集通知", Prefs.notificationEnabled(this))
        allAppsSwitch = switchRow("监听所有应用的通知", Prefs.allApps(this))
        switchCard.addView(smsSwitch)
        switchCard.addView(notificationSwitch)
        switchCard.addView(allAppsSwitch)
        switchCard.addView(TextView(this).apply {
            text = "默认只监听微信、支付宝、云闪付和常见银行 App，避免把无关推送发到服务器。"
            textSize = 12f
            setTextColor(color(R.color.muted))
            layoutParams = margins(top = 6)
        })

        val listenerButton = button("打开通知使用权设置")
        listenerButton.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        switchCard.addView(listenerButton)

        val flushButton = button("立即补发队列")
        flushButton.setOnClickListener {
            statusView.text = "正在补发…"
            Uploader.flushAsync(this) { summary -> runOnUiThread { statusView.text = summary; renderLogs() } }
        }
        switchCard.addView(flushButton)
        root.addView(switchCard)

        // 状态
        val statusCard = card()
        statusCard.addView(label("当前状态"))
        statusView = TextView(this).apply {
            textSize = 13.5f
            setTextColor(color(R.color.body))
            setLineSpacing(dp(5).toFloat(), 1f)
        }
        statusCard.addView(statusView)
        root.addView(statusCard)

        // 日志
        val logCard = card()
        logCard.addView(label("最近采集与发送"))
        logsView = TextView(this).apply {
            textSize = 11f
            typeface = Typeface.MONOSPACE
            setTextColor(color(R.color.body))
            setTextIsSelectable(true)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            background = GradientDrawable().apply {
                cornerRadius = dp(8).toFloat()
                setColor(color(R.color.canvas))
                setStroke(dp(1), color(R.color.hairline))
            }
            layoutParams = margins(top = 8)
        }
        logCard.addView(logsView)
        root.addView(logCard)

        smsSwitch.setOnCheckedChangeListener { _, _ -> savePrefs() }
        notificationSwitch.setOnCheckedChangeListener { _, _ -> savePrefs() }
        allAppsSwitch.setOnCheckedChangeListener { _, _ -> savePrefs() }

        return scroll
    }

    private fun render() {
        if (!serverInput.hasFocus()) serverInput.setText(Prefs.serverUrl(this))
        if (!tokenInput.hasFocus()) tokenInput.setText(Prefs.token(this))

        setSwitchSilently(smsSwitch, Prefs.smsEnabled(this))
        setSwitchSilently(notificationSwitch, Prefs.notificationEnabled(this))
        setSwitchSilently(allAppsSwitch, Prefs.allApps(this))

        val smsGranted = checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED
        val listenerReady = notificationAccessGranted()
        statusView.text = buildString {
            append("短信权限：").append(if (smsGranted) "已授予" else "未授予")
            append("　　通知使用权：").append(if (listenerReady) "已开启" else "未开启")
            append("\n待补发：").append(Outbox.pending(this@MainActivity)).append(" 条")
            append("\nHyperOS 必做：设置 → 应用设置 → 记账采集，打开「自启动」，省电策略选「无限制」，并在最近任务里锁定。")
        }
        renderLogs()
    }

    private fun renderLogs() {
        logsView.text = Logs.tail(this, 14)
    }

    // ---------------------------------------------------------------- 行为

    private fun savePrefs() {
        Prefs.save(
            this,
            serverInput.text.toString(),
            tokenInput.text.toString(),
            smsSwitch.isChecked,
            notificationSwitch.isChecked,
            allAppsSwitch.isChecked,
        )
    }

    private fun saveAndTest() {
        savePrefs()
        statusView.text = "正在测试连接…"
        val appContext = applicationContext
        Thread {
            val ping = Uploader.ping(appContext)
            val flush = Uploader.flush(appContext)
            runOnUiThread {
                statusView.text = "$ping\n$flush"
                renderLogs()
            }
        }.start()
    }

    private fun openInbox() {
        savePrefs()
        val server = Prefs.serverUrl(this)
        if (server.isEmpty()) {
            Toast.makeText(this, "先填服务器地址", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$server/inbox")))
    }

    private fun ensureSmsPermission() {
        if (!Prefs.smsEnabled(this)) return
        val missing = arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS)
            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) return
        requestPermissions(missing.toTypedArray(), REQUEST_SMS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_SMS) render()
    }

    private fun notificationAccessGranted(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: return false
        return enabled.split(":").any { it.contains(packageName) }
    }

    // ---------------------------------------------------------------- 小工具

    private fun setSwitchSilently(node: Switch, checked: Boolean) {
        node.setOnCheckedChangeListener(null)
        node.isChecked = checked
        node.setOnCheckedChangeListener { _, _ -> savePrefs() }
    }

    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(16), dp(14), dp(16), dp(16))
        background = GradientDrawable().apply {
            cornerRadius = dp(12).toFloat()
            setColor(color(R.color.surface_soft))
            setStroke(dp(1), color(R.color.hairline))
        }
        layoutParams = margins(bottom = 14)
    }

    private fun label(value: String): TextView = TextView(this).apply {
        text = value
        textSize = 12f
        setTextColor(color(R.color.muted))
        layoutParams = margins(top = 8)
    }

    private fun input(hintText: String, uri: Boolean): EditText = EditText(this).apply {
        hint = hintText
        textSize = 15f
        setSingleLine(true)
        inputType = if (uri) {
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        } else {
            InputType.TYPE_CLASS_TEXT
        }
        setTextColor(color(R.color.ink))
        backgroundTintList = ColorStateList.valueOf(color(R.color.primary))
        layoutParams = margins(top = 4)
    }

    private fun switchRow(title: String, initial: Boolean): Switch = Switch(this).apply {
        text = title
        textSize = 15f
        setTextColor(color(R.color.ink))
        isChecked = initial
        setPadding(0, dp(8), 0, dp(8))
    }

    private fun button(title: String, primary: Boolean = false): Button = Button(this).apply {
        text = title
        textSize = 14f
        isAllCaps = false
        setTextColor(if (primary) Color.WHITE else color(R.color.ink))
        backgroundTintList = ColorStateList.valueOf(
            if (primary) color(R.color.primary_strong) else color(R.color.canvas)
        )
        layoutParams = margins(top = 10)
    }

    private fun margins(top: Int = 0, bottom: Int = 0): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply {
            topMargin = dp(top)
            this.bottomMargin = dp(bottom)
        }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

    private fun color(id: Int): Int = getColor(id)

    companion object {
        private const val REQUEST_SMS = 1001
    }
}
