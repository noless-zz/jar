"""AI test model comparison: the run-file format, and missing models listed instead of pulled."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from worker import evaluate as E


class Compare(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(E.parse_models("2"), (2, []))
        self.assertEqual(E.parse_models("1 a:9b b:27b/nothink"), (1, [("a:9b", True), ("b:27b", False)]))
        self.assertEqual(E.parse_models("a:9b"), (1, [("a:9b", True)]))

    def test_compare_writes_a_grid_and_lists_missing_models(self):
        tmp = Path(tempfile.mkdtemp())
        cfg = SimpleNamespace(data_dir=tmp, ollama_url="http://x", llm_model="a:9b", think=True)
        fake = {"passed": 3, "total": 4, "per_case": {"x": "1/1", "y": "0/1"},
                "results": [{"case": "x", "seconds": 5}, {"case": "rating: r", "seconds": 1}]}
        with mock.patch.object(E, "pulled", return_value={"a:9b"}), \
                mock.patch.object(E, "replace", side_effect=lambda c, **kw: SimpleNamespace(**{**vars(c), **kw})), \
                mock.patch.object(E, "run", return_value=fake) as run:
            out = E.compare(cfg, [("a:9b", True), ("a:9b", False), ("big:70b", True)])
        self.assertEqual(run.call_count, 2)
        self.assertIn("ollama pull big:70b", out["rows"][2]["missing"])
        md = (tmp / "eval" / "compare.md").read_text(encoding="utf-8")
        self.assertIn("| a:9b/nothink | 3/4 | 5 |", md)
        self.assertIn("| y | 0/1 | 0/1 |", md)


if __name__ == "__main__":
    unittest.main()


def test_reply_language_problem():
    from worker.evaluate import reply_language_problem
    assert reply_language_problem("לקנות חלב", "הוספתי משימה לקנות חלב.") is None
    assert reply_language_problem("לקנות חלב", "I've added a task to buy milk for you.")
    assert reply_language_problem("buy milk", "I've added a task to buy milk for you.") is None
    assert reply_language_problem("לשלוח מייל ל-John", "הוספתי משימה לשלוח מייל ל-John Smith") is None
