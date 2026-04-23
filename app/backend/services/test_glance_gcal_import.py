"""Unit tests for parse_glance_title."""

import unittest
from glance_gcal_import import parse_glance_title


class TestParseGlanceTitle(unittest.TestCase):

    def _parse(self, title):
        return parse_glance_title(title)

    # --- Zero-prefix (implicit steve event) ---

    def test_no_prefix_is_steve_event(self):
        r = self._parse("solo walk")
        self.assertEqual(r["member"], "steve")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "solo walk")
        self.assertTrue(r["valid"])

    # --- Single-char name prefix ---

    def test_s_prefix_steve_event(self):
        r = self._parse("s solo walk")
        self.assertEqual(r["member"], "steve")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "solo walk")
        self.assertTrue(r["valid"])

    def test_p_prefix_pgv_event(self):
        r = self._parse("p recital")
        self.assertEqual(r["member"], "pgv")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "recital")

    def test_y_prefix_york_event(self):
        r = self._parse("y HVAC service")
        self.assertEqual(r["member"], "york")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "HVAC service")

    # --- Single-char type prefix (t defaults name to steve) ---

    def test_t_prefix_defaults_to_steve_travel(self):
        r = self._parse("t dentist")
        self.assertEqual(r["member"], "steve")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "dentist")

    # --- Two-char prefixes ---

    def test_st_steve_travel(self):
        r = self._parse("st Azores")
        self.assertEqual(r["member"], "steve")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "Azores")

    def test_pt_pgv_travel(self):
        r = self._parse("pt Lisbon")
        self.assertEqual(r["member"], "pgv")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "Lisbon")

    def test_ot_ovinters_travel(self):
        r = self._parse("ot soccer camp")
        self.assertEqual(r["member"], "ovinters")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "soccer camp")

    def test_kt_kpv_travel(self):
        r = self._parse("kt Edinburgh")
        self.assertEqual(r["member"], "kpv")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "Edinburgh")

    # --- Edge cases ---

    def test_whitespace_stripped(self):
        r = self._parse("  st  Azores  ")
        self.assertEqual(r["member"], "steve")
        self.assertTrue(r["is_travel"])
        self.assertEqual(r["label"], "Azores")

    def test_empty_string_invalid(self):
        r = self._parse("")
        self.assertFalse(r["valid"])
        self.assertIsNotNone(r["error"])

    def test_york_travel_is_coerced_to_event(self):
        r = self._parse("yt something")
        self.assertEqual(r["member"], "york")
        self.assertFalse(r["is_travel"])  # york + travel → coerced to event
        self.assertEqual(r["label"], "something")
        self.assertTrue(r["valid"])

    def test_unrecognized_prefix_treated_as_title(self):
        # 'z' is not in VALID_META_CHARS → entire string is label, defaults to steve
        r = self._parse("z something")
        self.assertEqual(r["member"], "steve")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "z something")

    def test_prefix_without_space_treated_as_title(self):
        # 'st' followed by non-space → treat as title
        r = self._parse("stAzores")
        self.assertEqual(r["member"], "steve")
        self.assertFalse(r["is_travel"])
        self.assertEqual(r["label"], "stAzores")

    def test_multiple_spaces_between_meta_and_title(self):
        r = self._parse("s   solo walk")
        self.assertEqual(r["member"], "steve")
        self.assertEqual(r["label"], "solo walk")

    def test_title_with_no_space_after_single_valid_char(self):
        # 'pdentist' — no space after 'p' → full title
        r = self._parse("pdentist")
        self.assertEqual(r["label"], "pdentist")
        self.assertEqual(r["member"], "steve")


if __name__ == "__main__":
    unittest.main()
