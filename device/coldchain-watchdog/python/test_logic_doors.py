"""A single knob turn resolves the doors-open warning (no acknowledge step)."""
import json
import unittest
from pathlib import Path

from logic import KNOB_ACK_STEPS, Watchdog

DATA = Path(__file__).parent / "data"


class DoorsKnobTest(unittest.TestCase):
    def test_one_turn_resolves_doors(self):
        wd = Watchdog(json.loads((DATA / "medicines.json").read_text()),
                      json.loads((DATA / "clinics.json").read_text()))
        wd.handle("doors_open")
        outcome = wd.knob_turn(KNOB_ACK_STEPS)
        self.assertFalse(wd.doors_open())
        self.assertEqual([name for name, _ in outcome.stubs], ["report_alarm_resolved"])
        data = outcome.stubs[0][1]
        self.assertTrue(data["doors"])
        self.assertIsNone(data["alarm_kind"])
        self.assertEqual(data["resolved_by"], "knob")


if __name__ == "__main__":
    unittest.main()
