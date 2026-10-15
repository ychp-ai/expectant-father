"""Regression tests for source-based review deadlines; no external requests."""

import contextlib
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import check_knowledge_base as checker


class ReviewDeadlineTests(unittest.TestCase):
    def check(self, codes="NHS-TEST-001", age=90, period="365 天", body="", source_age=0):
        today = date(2026, 10, 15)
        reviewed = (today - timedelta(days=age)).isoformat()
        source_reviewed = (today - timedelta(days=source_age)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / "references" / "README.md"
            references.parent.mkdir()
            (root / "README.md").write_text(
                "# 导航\n[正文](page.md)\n[来源](references/README.md)\n", encoding="utf-8"
            )
            (root / "page.md").write_text(
                f"# 正文\n{body}\n## 内容依据与复核\n- 采用来源：{codes}\n"
                f"- 最近复核：{reviewed}\n", encoding="utf-8"
            )
            metadata = f"- 复核周期：{period}\n" if period is not None else ""
            references.write_text(
                "# 来源\n### NHS-TEST-001：医学资料\n- 适用范围：通用知识\n"
                f"{metadata}- 最近复核：{source_reviewed}\n"
                "### HZ-TEST-001：地方事项\n- 适用范围：办事条件\n"
                "- 复核周期：90 天\n- 最近复核：2026-10-15\n"
                "## 已停用来源\n## 来源编号规则\n", encoding="utf-8"
            )
            # 导航也引用全部来源，避免未引用检查干扰本组日期用例。
            with (root / "README.md").open("a", encoding="utf-8") as stream:
                stream.write("NHS-TEST-001、HZ-TEST-001\n")
            output = io.StringIO()
            with patch.object(checker, "ROOT", root), patch.object(checker, "REFERENCES", references):
                with patch("sys.argv", ["check", "--today", today.isoformat()]):
                    with contextlib.redirect_stdout(output):
                        result = checker.main()
            return result, output.getvalue()

    def test_generic_hospital_reminders_do_not_shorten_medical_period(self):
        self.assertEqual(self.check(body="预约医院前核对医保卡，按医院建议就诊。", age=364)[0], 0)

    def test_medical_deadline_is_due_on_day_365(self):
        result, output = self.check(age=365)
        self.assertEqual(result, 1)
        self.assertIn("page.md: 已超过 365 天复核周期", output)

    def test_policy_deadline_does_not_depend_on_keywords(self):
        self.assertEqual(self.check(codes="HZ-TEST-001", age=89)[0], 0)
        result, output = self.check(codes="HZ-TEST-001", age=90)
        self.assertEqual(result, 1)
        self.assertIn("page.md: 已超过 90 天复核周期", output)

    def test_mixed_sources_use_shorter_period(self):
        result, output = self.check(codes="NHS-TEST-001、HZ-TEST-001")
        self.assertEqual(result, 1)
        self.assertIn("page.md: 已超过 90 天复核周期", output)

    def test_invalid_or_missing_period_fails(self):
        for period in (None, "30 天", "365 天\n- 复核周期：90 天"):
            with self.subTest(period=period):
                result, output = self.check(period=period)
                self.assertEqual(result, 1)
                self.assertIn("复核周期须唯一", output)

    def test_unknown_source_still_fails(self):
        result, output = self.check(codes="CN-UNKNOWN-001")
        self.assertEqual(result, 1)
        self.assertIn("来源编号 CN-UNKNOWN-001 未定义", output)

    def test_source_deadline_uses_registered_period(self):
        for days in (90, 365):
            with self.subTest(days=days):
                self.assertEqual(self.check(age=0, period=f"{days} 天", source_age=days - 1)[0], 0)
                result, output = self.check(age=0, period=f"{days} 天", source_age=days)
                self.assertEqual(result, 1)
                self.assertIn(f"来源编号 NHS-TEST-001: 已超过 {days} 天复核周期", output)

    def test_empty_source_list_fails(self):
        result, output = self.check(codes="")
        self.assertEqual(result, 1)
        self.assertIn("page.md: 缺少采用来源", output)

    def test_future_review_date_still_fails(self):
        result, output = self.check(age=-1)
        self.assertEqual(result, 1)
        self.assertIn("page.md: 最近复核日期晚于检查日期", output)


if __name__ == "__main__":
    unittest.main()
