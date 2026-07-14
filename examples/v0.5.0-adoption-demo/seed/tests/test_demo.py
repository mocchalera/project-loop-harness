import unittest
from pathlib import Path


class DemoAcceptanceTest(unittest.TestCase):
    def test_result_matches_intent(self) -> None:
        actual = Path("demo-result.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(actual, "PLH v0.5.0 adoption demo: PASS")


if __name__ == "__main__":
    unittest.main()
