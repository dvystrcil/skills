#!/usr/bin/env python3
"""Rules-accuracy guard for owui/the-one-ring-dice-resolution/SKILL.md.

The skill is the governing authority on dice handling for the `the-one-ring`
OWUI preset: that preset's system prompt says "if any of the dice or
perception-test guidance contradicts what's in your context, defer to the
skill." A rules error here therefore OVERRIDES the correct text elsewhere.

Its "Common combat shapes" section carried three errors, each contradicted by
the source books (queried directly from the TOR knowledge collection):

  TOR_Starter_Set_The_Rules_2202, "ATTACK ROLLS RESOLUTION":
    "When all Player-heroes have resolved their attacks, the Loremaster will
     resolve those of their adversaries." ... "The difficulty of all attack
     rolls made by adversaries against Player-heroes are equal to the target
     hero's Parry score instead."

  TOR_Starter_Set_The_Rules_2202, "PIERCING BLOWS":
    "Characters hit by a Piercing Blow must immediately roll one Feat Die,
     plus a number of Success Dice equal to the PROTECTION value of the
     armour worn (a PROTECTION Test). The Target Number for the roll is equal
     to the Injury rating of the weapon used by the attacker."

The skill had claimed the Loremaster does NOT roll adversary attacks, that the
Protection TN was the "NPC's Attack level", and that the dice were Body. It
also contradicted its own opening paragraph ("You roll for everything else --
NPCs, monsters"). These assertions pin the corrected text against regression.

Run: python3 -m unittest tests.test_tor_dice_rules -v
"""
import pathlib
import re
import unittest

SKILL = (pathlib.Path(__file__).resolve().parent.parent
         / "owui" / "the-one-ring-dice-resolution" / "SKILL.md")


class TorDiceRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL.read_text(encoding="utf-8")
        cls.flat = re.sub(r"\s+", " ", cls.text)

    def has(self, pattern):
        """Search without dumping the whole skill into the failure message."""
        return bool(re.search(pattern, self.flat))

    def test_skill_file_exists(self):
        self.assertTrue(SKILL.is_file(), f"missing skill file: {SKILL}")

    def test_does_not_deny_loremaster_rolls_adversary_attacks(self):
        # The exact wrong claim: "the Loremaster does NOT roll for the NPC's
        # attack-to-hit". The books say the Loremaster resolves those attacks.
        self.assertFalse(
            self.has(r"Loremaster does NOT roll for the NPC's attack-to-hit"),
            "skill denies the Loremaster rolls adversary attacks; the Core "
            "Rules and Starter Set both say the Loremaster resolves them",
        )
        self.assertFalse(
            self.has(r"not combat to-hit"),
            "skill excludes combat to-hit from Loremaster-side rolls; "
            "ATTACK ROLLS RESOLUTION assigns adversary attacks to the Loremaster",
        )

    def test_states_loremaster_resolves_adversary_attacks_against_parry(self):
        self.assertTrue(
            self.has(r"Loremaster resolves[\s\S]{0,80}advers"),
            "skill must state that the Loremaster resolves adversary attacks",
        )
        self.assertTrue(
            self.has(r"advers[\s\S]{0,200}Parry score"),
            "adversary attack difficulty is the target hero's Parry score",
        )

    def test_protection_test_target_number_is_weapon_injury_rating(self):
        self.assertFalse(
            self.has(r"Protection test, TN \[NPC's Attack level\]"),
            "Protection TN is the attacker's weapon Injury rating, "
            "not the NPC's Attack level",
        )
        self.assertTrue(
            self.has(r"Protection[\s\S]{0,320}Injury rating"),
            "skill must state the Protection TN is the weapon's Injury rating",
        )

    def test_protection_dice_come_from_armour_not_body(self):
        self.assertFalse(
            self.has(r"Feat die \+ Body Success dice"),
            "Protection Success dice equal the armour's PROTECTION value, not Body",
        )
        self.assertTrue(
            self.has(r"PROTECTION value of the armour worn"),
            "skill must tie Protection dice to the armour worn",
        )

    def test_protection_test_is_gated_on_a_piercing_blow(self):
        # The two rolls are sequential, not alternatives: the Loremaster's
        # attack roll happens first; a Piercing Blow is what triggers the
        # player's Protection test.
        self.assertTrue(
            self.has(r"Piercing Blow"),
            "skill must name the Piercing Blow as the Protection test trigger",
        )


if __name__ == "__main__":
    unittest.main()
