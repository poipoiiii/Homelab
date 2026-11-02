# bill-ai 余额候选接口

手机上报的短信 / 通知原文里如果带「余额 + 卡号尾号」，`/api/ingest` 会额外写一条 `pending` 的余额候选；人工确认后才回写账户余额。识别失败、缺金额或缺尾号只写服务端日志，不影响 `/api/ingest` 返回 2xx。

规则与阈值集中在 [app/balance.py](app/balance.py)：

- 关键词：`可用余额` / `账户余额` / `余额` / `剩余`
- 金额：支持千分位、`¥`、`元`；卡号只取后 4 位（`尾号1234`、`****1234`、`卡号后四位1234`）
- 来源过滤：`106` 开头的营销短信号码直接跳过
- 幂等：`raw_hash`（原文哈希）+ `dedup_key`（尾号或账户 + 金额 + 5 分钟窗口）唯一，客户端重发安全
- 超期：`pending` 超过 `BALANCE_PENDING_DAYS`（默认 7）天自动置 `rejected`

## 字段

`GET /api/overview?month=yyyy-MM` 的 `accounts[]` 新增两个字段，旧客户端可忽略：

```json
{
  "id": 1,
  "name": "招行储蓄卡",
  "balance": "12345.67",
  "balance_updated_at": "2026-10-29T21:10:00+08:00",
  "balance_source": "sms"
}
```

- `balance_updated_at`：余额最后一次被确认的时间（ISO8601 带时区），从未确认为 `null`
- `balance_source`：`manual` / `sms` / `notification` / `ocr`，未知为 `null`

`/api/overview` 顶层新增 `pending_balance_candidates`（整数，默认 0）。

## 列表

```http
GET /api/balances/candidates?status=pending&limit=50
Authorization: Bearer <token>
```

```json
{
  "items": [
    {
      "id": 12,
      "account_id": 1,
      "account_name": "招行储蓄卡",
      "card_tail": "1234",
      "balance": "12345.67",
      "currency": "CNY",
      "source": "sms",
      "observed_at": "2026-10-29T21:10:00+08:00",
      "created_at": "2026-10-29T21:10:05+08:00",
      "raw_excerpt": "您尾号1234的储蓄卡…余额人民币12,345.67元",
      "current_balance": "12000.00",
      "delta": "345.67",
      "anomaly": false,
      "status": "pending"
    }
  ],
  "pending_count": 1
}
```

- `raw_excerpt` 最多 80 字，8 位以上连续数字只保留后 4 位，接口不返回完整卡号
- `account_id` 为 `null` 表示还没匹配到账户，只认出了尾号
- `anomaly` 在偏差超过 `BALANCE_ANOMALY_RATIO`（默认 0.5，即 50%）时为 `true`

## 确认（支持批量）

```http
POST /api/balances/candidates/confirm
Authorization: Bearer <token>
Content-Type: application/json

{ "ids": [12, 13], "account_id": 1 }
```

- `account_id` 可选：只用于把「只有尾号」的候选指定到某个账户
- 成功后候选置 `confirmed`，并记住「发送方 + 尾号 → 账户」映射，后续同尾号短信自动匹配
- 同一账户一次确认多条时，只让 `observed_at` 最新的一条决定余额
- 回写通过调整账户期初余额完成，同时更新 `balance_updated_at` / `balance_source`

```json
{
  "items": [
    { "id": 12, "status": "confirmed", "account_id": 1, "balance": "12345.67" }
  ],
  "pending_count": 0
}
```

单条失败时 `status` 为 `missing`（记录不存在）/ `skipped`（未指定账户或账户不存在），并带 `error`。

## 驳回（支持批量）

```http
POST /api/balances/candidates/reject
Authorization: Bearer <token>
Content-Type: application/json

{ "ids": [12] }
```

返回结构与确认一致，`status` 为 `rejected`。

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `BALANCE_ANOMALY_RATIO` | `0.5` | 偏差超过该比例标记 anomaly |
| `BALANCE_PENDING_DAYS` | `7` | pending 超期自动驳回天数 |

## 自测

```bash
curl -X POST "$BASE/api/ingest" \
  -H "X-Ingest-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"sms","sender":"95588","text":"您尾号1234的储蓄卡10月29日21:10余额人民币12,345.67元","ts":1761743400,"device":"test"}'
```

连续发两次，第二次不会新增候选；确认后 `/api/overview` 的对应账户余额变为 `12345.67`。

单元测试：`python tests/test_balance.py`（在 `homelab/bill-ai` 目录执行）。
