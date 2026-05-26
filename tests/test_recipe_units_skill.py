#!/usr/bin/env python3
"""
Schema + fixture validator for the recipe-units skill.

Migrated from homelab/bin/tests/ in phase 1 of homelab#225 — tests
live next to the code they validate. The recipe-units SKILL.md lives
in this repo at owui/recipe-units/SKILL.md; this test pins its
contract.

What it pins:
  - Frontmatter is well-formed YAML with required keys (name,
    description, tags, scope).
  - The Pantry staples section exists and contains a non-empty
    bulleted list with the canonical items.
  - The Recipe-unit -> grocery-unit translation table exists and
    covers the canonical recipe-units (tsp, tbsp, cup, lb, oz).
  - Each fixture's pantry_skipped items are all present in the
    canonical pantry list (worked examples can't drift from rules
    silently).

Does NOT exercise the LLM-driven path — that would need OWUI in the
loop. Run with:
    python3 tests/test_recipe_units_skill.py
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "ERROR: PyYAML not installed. Try: apt install python3-yaml OR pip install pyyaml\n"
    )
    sys.exit(2)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SKILL_FILE = REPO_ROOT / "owui" / "recipe-units" / "SKILL.md"
FIXTURE_DIR = HERE / "fixtures" / "recipe_units"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Raise on malformed."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with '---' frontmatter delimiter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter is unterminated")
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5 :]
    return fm, body


def _extract_pantry_list(body: str) -> list[str]:
    """Find the 'Pantry staples' section and return its bulleted items."""
    m = re.search(r"## Pantry staples[^\n]*\n(.*?)(?=\n## |\Z)", body, re.S)
    if not m:
        raise ValueError("SKILL.md missing 'Pantry staples' section header")
    section = m.group(1)
    items = []
    for line in section.split("\n"):
        m2 = re.match(r"-\s+([^*\n]+?)(?:\s+\(.*\))?$", line.strip())
        if m2:
            items.append(m2.group(1).strip().lower())
    return items


def _extract_translation_units(body: str) -> set[str]:
    """Return the set of unit-keywords mentioned in the translation table."""
    m = re.search(
        r"## Recipe-unit → grocery-unit translation\n(.*?)(?=\n## |\Z)", body, re.S
    )
    if not m:
        raise ValueError("SKILL.md missing 'Recipe-unit → grocery-unit translation' section")
    section = m.group(1).lower()
    found = set()
    for unit in ("tsp", "tbsp", "cup", "lb", "oz", "can", "jar", "box", "package"):
        if unit in section:
            found.add(unit)
    return found


class TestSkillStructure(unittest.TestCase):
    """Skill file is well-formed."""

    def setUp(self):
        if not SKILL_FILE.exists():
            self.fail(f"SKILL.md not found at {SKILL_FILE}")
        self.text = SKILL_FILE.read_text(encoding="utf-8")
        self.frontmatter, self.body = _split_frontmatter(self.text)

    def test_frontmatter_has_required_keys(self):
        for key in ("name", "description", "tags", "scope"):
            self.assertIn(key, self.frontmatter, f"frontmatter missing {key}")
        self.assertIsInstance(self.frontmatter["tags"], list)
        self.assertGreater(len(self.frontmatter["tags"]), 0)
        self.assertIn(self.frontmatter["scope"], ("task", "always"))

    def test_pantry_list_present_and_nonempty(self):
        pantry = _extract_pantry_list(self.body)
        self.assertGreater(len(pantry), 5, "pantry list is suspiciously short")
        for must_have in ("salt", "black pepper", "baking soda", "olive oil"):
            self.assertTrue(
                any(must_have in p for p in pantry),
                f"pantry list missing canonical item '{must_have}'",
            )

    def test_pantry_list_has_no_duplicates(self):
        pantry = _extract_pantry_list(self.body)
        self.assertEqual(
            len(pantry), len(set(pantry)),
            f"pantry list has duplicates: {[p for p in pantry if pantry.count(p) > 1]}",
        )

    def test_translation_covers_common_units(self):
        units = _extract_translation_units(self.body)
        for required in ("tsp", "tbsp", "cup", "lb", "oz"):
            self.assertIn(required, units, f"translation table missing unit '{required}'")


class TestFixturesAlignWithSkill(unittest.TestCase):
    """Each fixture's pantry_skipped is consistent with the skill's pantry list."""

    def setUp(self):
        if not SKILL_FILE.exists():
            self.fail(f"SKILL.md not found at {SKILL_FILE}")
        text = SKILL_FILE.read_text(encoding="utf-8")
        _, body = _split_frontmatter(text)
        self.pantry = _extract_pantry_list(body)

    def _pantry_covers(self, item: str) -> bool:
        item = item.lower()
        return any(item in p or p in item for p in self.pantry)

    def test_fixtures_directory_has_three_recipes(self):
        if not FIXTURE_DIR.exists():
            self.fail(f"no fixture dir at {FIXTURE_DIR}")
        fixtures = sorted(FIXTURE_DIR.glob("*.yaml"))
        self.assertGreaterEqual(
            len(fixtures), 3,
            "expected at least 3 worked-example fixtures (baked, savory, one-pot)",
        )

    def test_every_pantry_skipped_is_actually_in_pantry_list(self):
        if not FIXTURE_DIR.exists():
            self.fail(f"no fixture dir at {FIXTURE_DIR}")
        for fixture_path in sorted(FIXTURE_DIR.glob("*.yaml")):
            with self.subTest(fixture=fixture_path.name):
                fx = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
                skipped = fx.get("expected_cart", {}).get("pantry_skipped", [])
                for item in skipped:
                    self.assertTrue(
                        self._pantry_covers(item),
                        f"fixture says '{item}' is pantry but SKILL.md's pantry list doesn't cover it",
                    )

    def test_fixtures_have_nonzero_expected_item_count(self):
        if not FIXTURE_DIR.exists():
            self.fail(f"no fixture dir at {FIXTURE_DIR}")
        for fixture_path in sorted(FIXTURE_DIR.glob("*.yaml")):
            with self.subTest(fixture=fixture_path.name):
                fx = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
                count = fx.get("expected_cart", {}).get("expected_item_count", 0)
                self.assertGreater(count, 0, "expected_item_count must be > 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
