from __future__ import annotations

from app.meta.patch_diff import PatchDiffEngine


def test_patch_diff_detects_buff() -> None:
    engine = PatchDiffEngine()
    old = {
        "S1": {
            "item_id": "T4_SWORD",
            "spell_name": "Slash",
            "damage": 100.0,
            "cooldown": 5.0,
            "energy_cost": 10.0,
            "coefficient": 0.5,
        }
    }
    new = {
        "S1": {
            "item_id": "T4_SWORD",
            "spell_name": "Slash",
            "damage": 120.0,
            "cooldown": 5.0,
            "energy_cost": 10.0,
            "coefficient": 0.5,
        }
    }
    df = engine.diff_spells(old, new)
    assert not df.empty
    scores = engine.generate_item_meta_scores(df)
    assert not scores.empty
    row = scores.iloc[0]
    assert row["item_id"] == "T4_SWORD"
    assert row["meta_score_impact"] > 0
