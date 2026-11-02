"""余额候选链路的单元测试：金额/尾号解析、去重、确认回写、驳回与超期清理。

全部用标准库 unittest，不依赖 FastAPI；临时库放在项目 .cache 下，不写 C 盘。
运行：在 homelab/bill-ai 目录执行 python tests/test_balance.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import balance, store  # noqa: E402

SMS = "您尾号1234的储蓄卡10月29日21:10余额人民币12,345.67元"
TS = 1761743400


class ParseBalanceTest(unittest.TestCase):
    def test_amount_with_thousands_separator(self):
        candidate = balance.parse_balance(SMS, "sms", "95588", TS)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.balance, "12345.67")
        self.assertEqual(candidate.card_tail, "1234")
        self.assertEqual(candidate.source, "sms")
        self.assertEqual(candidate.currency, "CNY")
        self.assertEqual(candidate.observed_at, balance.iso_time(TS))

    def test_available_balance_with_symbol_and_short_decimals(self):
        text = "您账户可用余额 ¥1,234.5 元，尾号 8888"
        candidate = balance.parse_balance(text, "sms", "95599", TS)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.balance, "1234.50")
        self.assertEqual(candidate.card_tail, "8888")

    def test_masked_card_tail(self):
        text = "信用卡****5678余额人民币200.00元"
        candidate = balance.parse_balance(text, "sms", "95566", TS)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.card_tail, "5678")
        self.assertEqual(candidate.balance, "200.00")

    def test_card_tail_words(self):
        candidate = balance.parse_balance("卡号后四位 4321 账户余额 88.00 元", "sms", "95533", TS)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.card_tail, "4321")

    def test_missing_tail_is_ignored(self):
        self.assertIsNone(balance.parse_balance("您账户余额人民币12,345.67元", "sms", "95588", TS))

    def test_missing_keyword_is_ignored(self):
        self.assertIsNone(balance.parse_balance("尾号1234消费100.00元", "sms", "95588", TS))

    def test_marketing_sender_is_ignored(self):
        text = "尾号1234余额人民币12,345.67元"
        self.assertIsNone(balance.parse_balance(text, "sms", "10690001", TS))

    def test_notification_source(self):
        candidate = balance.parse_balance(SMS, "notification", "com.example.bank", TS)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.source, "notification")

    def test_dedup_key_window(self):
        first = balance.dedup_key("1234", "12.00", TS)
        same_window = balance.dedup_key("1234", "12.00", TS + 60)
        next_window = balance.dedup_key("1234", "12.00", TS + balance.DEDUP_WINDOW_SECONDS)
        self.assertEqual(first, same_window)
        self.assertNotEqual(first, next_window)


class BalanceStoreTest(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / ".cache"
        cache.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="balance-test-", dir=str(cache))
        store.DB_PATH = os.path.join(self.tmp, "bill.db")
        store.init_db()
        self.account_id = store.create_account("招行储蓄卡", "0")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, text: str = SMS, ts: int = TS, sender: str = "95588"):
        candidate = balance.parse_balance(text, "sms", sender, ts)
        self.assertIsNotNone(candidate)
        return store.add_balance_candidate(candidate, sender=sender, raw_text=text)

    def test_duplicate_ingest_is_idempotent(self):
        first_id, created = self._add()
        self.assertTrue(created)

        second_id, created_again = self._add()
        self.assertFalse(created_again)
        self.assertEqual(first_id, second_id)
        self.assertEqual(store.list_balance_candidates()["pending_count"], 1)

        # 原文不同但卡号尾号 + 金额 + 5 分钟窗口相同，也只算一条
        _, created_same_window = self._add(
            "尾号1234的卡余额12,345.67元", ts=TS + 30,
        )
        self.assertFalse(created_same_window)
        self.assertEqual(store.list_balance_candidates()["pending_count"], 1)

    def test_candidate_list_fields(self):
        self._add()
        page = store.list_balance_candidates()
        self.assertEqual(len(page["items"]), 1)
        item = page["items"][0]
        self.assertEqual(item["card_tail"], "1234")
        self.assertEqual(item["balance"], "12345.67")
        self.assertEqual(item["status"], "pending")
        self.assertIsNone(item["account_id"])
        self.assertIsNone(item["current_balance"])
        self.assertFalse(item["anomaly"])
        self.assertLessEqual(len(item["raw_excerpt"]), store.RAW_EXCERPT_CHARS + 1)

    def test_raw_excerpt_masks_long_card_number(self):
        self._add("卡号6225880212341234，尾号1234余额人民币12,345.67元")
        item = store.list_balance_candidates()["items"][0]
        self.assertNotIn("6225880212341234", item["raw_excerpt"])
        self.assertIn("1234", item["raw_excerpt"])

    def test_confirm_writes_back_balance_and_freshness(self):
        snapshot_id, _ = self._add()
        result = store.confirm_balance_candidates([snapshot_id], self.account_id)
        self.assertEqual(result["items"][0]["status"], "confirmed")
        self.assertEqual(result["pending_count"], 0)

        account = store.list_accounts()[0]
        self.assertEqual(account["balance"], "12345.67")
        self.assertEqual(account["balance_source"], "sms")
        self.assertEqual(account["balance_updated_at"], balance.iso_time(TS))

        # 确认后记下尾号映射，下一条同尾号短信能自动匹配账户
        _, created = self._add("尾号1234余额人民币100.00元", ts=TS + 3600)
        self.assertTrue(created)
        latest = store.list_balance_candidates()["items"][0]
        self.assertEqual(latest["account_id"], self.account_id)

    def test_stale_confirm_does_not_override_newer_balance(self):
        newer, _ = self._add("尾号1234余额人民币200.00元", ts=TS + 7200)
        store.confirm_balance_candidates([newer], self.account_id)
        older, _ = self._add("尾号1234余额人民币100.00元", ts=TS + 3600)
        store.confirm_balance_candidates([older], self.account_id)

        account = store.list_accounts()[0]
        self.assertEqual(account["balance"], "200.00")
        self.assertEqual(account["balance_updated_at"], balance.iso_time(TS + 7200))

    def test_confirm_without_account_is_skipped(self):
        snapshot_id, _ = self._add()
        result = store.confirm_balance_candidates([snapshot_id])
        self.assertEqual(result["items"][0]["status"], "skipped")
        self.assertEqual(store.pending_balance_count(), 1)

    def test_reject_keeps_balance(self):
        snapshot_id, _ = self._add()
        result = store.reject_balance_candidates([snapshot_id])
        self.assertEqual(result["items"][0]["status"], "rejected")
        self.assertEqual(store.pending_balance_count(), 0)
        self.assertEqual(store.list_accounts()[0]["balance"], "0.00")

    def test_expire_old_pending(self):
        snapshot_id, _ = self._add()
        con = store.connect()
        try:
            con.execute(
                "UPDATE account_balance_snapshots SET created_at = ? WHERE id = ?",
                (int(time.time()) - 8 * 86400, snapshot_id),
            )
            con.commit()
        finally:
            con.close()

        self.assertEqual(store.expire_balance_candidates(7), 1)
        self.assertEqual(store.pending_balance_count(), 0)
        expired = store.list_balance_candidates(status="rejected")["items"][0]
        self.assertEqual(expired["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
