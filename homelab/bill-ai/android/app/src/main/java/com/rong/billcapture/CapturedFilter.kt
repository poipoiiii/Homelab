package com.rong.billcapture

/** 本地预过滤：明显不是交易的消息不往服务器发，减少原文外发。 */
object CapturedFilter {
    private val HINTS = listOf(
        "消费", "支付", "付款", "扣款", "入账", "到账", "转账", "退款",
        "取现", "取款", "缴费", "还款", "工资", "收款", "交易", "支出", "收入",
    )

    fun isTransactionText(text: String): Boolean = HINTS.any { text.contains(it) }

    /** 默认只监听这些应用的推送；「其他应用通知」开关打开后不再限制。 */
    val PACKAGES = setOf(
        "com.tencent.mm",
        "com.eg.android.AlipayGphone",
        "com.unionpay",
        "com.icbc",
        "com.chinamworld.main",
        "com.bankcomm.Bankcomm",
        "com.cmbchina.ccd.pluto.cmbActivity",
        "com.android.bankabc",
        "com.boc.bocsoft.mobile.bocmobile",
        "cmb.pb",
    )
}
