
import pandas as pd


class PatchDiffEngine:
    """
    Analyzes differences between two versions of spell/item data (e.g. between game updates)
    and generates a 'patch_impact' or 'meta_score' based on buffs and nerfs to:
    - spell coefficients
    - cooldowns
    - damage
    - energy costs
    """

    def __init__(self):
        # Weights for calculating impact
        self.weights = {
            "damage": 1.5,       # Increase in damage is highly impactful
            "cooldown": -2.0,    # Decrease in cooldown is highly impactful (hence negative weight for simple diff)
            "energy_cost": -0.5, # Decrease in energy cost is moderately impactful
            "coefficient": 1.5   # Increase in scaling is highly impactful
        }

    def compute_stat_diff(self, old_val: float, new_val: float, stat_type: str) -> float:
        """
        Computes the relative impact of a single stat change.
        Returns a positive value for a BUFF, negative for a NERF.
        """
        if old_val == 0:
            if new_val == 0:
                return 0.0
            return self.weights[stat_type] if new_val > 0 else -self.weights[stat_type]

        pct_change = (new_val - old_val) / abs(old_val)

        # Multiply by the weight.
        # Example: cooldown drops by 10% (-0.10). Weight is -2.0. Impact = (-0.10) * (-2.0) = +0.20 (Buff)
        return pct_change * self.weights.get(stat_type, 1.0)

    def diff_spells(self, old_patch: dict[str, dict], new_patch: dict[str, dict]) -> pd.DataFrame:
        """
        Compares two dictionaries of spell data and calculates the meta_score impact.
        
        Expected structure for patches:
        {
            "spell_id": {
                "item_id": "T4_MAIN_SWORD",
                "spell_name": "Heroic Strike",
                "damage": 150.0,
                "cooldown": 3.0,
                "energy_cost": 15.0,
                "coefficient": 0.8
            }
        }
        """
        impacts = []

        for spell_id, new_data in new_patch.items():
            if spell_id not in old_patch:
                # New spell added
                impacts.append({
                    "spell_id": spell_id,
                    "item_id": new_data.get("item_id", "UNKNOWN"),
                    "spell_name": new_data.get("spell_name", "UNKNOWN"),
                    "status": "NEW",
                    "damage_diff": 0,
                    "cooldown_diff": 0,
                    "energy_diff": 0,
                    "coeff_diff": 0,
                    "meta_score_impact": 1.0 # Base positive impact for new ability
                })
                continue

            old_data = old_patch[spell_id]

            d_dmg = self.compute_stat_diff(old_data.get('damage', 0), new_data.get('damage', 0), 'damage')
            d_cd = self.compute_stat_diff(old_data.get('cooldown', 0), new_data.get('cooldown', 0), 'cooldown')
            d_nrg = self.compute_stat_diff(old_data.get('energy_cost', 0), new_data.get('energy_cost', 0), 'energy_cost')
            d_coef = self.compute_stat_diff(old_data.get('coefficient', 0), new_data.get('coefficient', 0), 'coefficient')

            total_impact = d_dmg + d_cd + d_nrg + d_coef

            if total_impact != 0:
                impacts.append({
                    "spell_id": spell_id,
                    "item_id": new_data.get("item_id", "UNKNOWN"),
                    "spell_name": new_data.get("spell_name", "UNKNOWN"),
                    "status": "CHANGED",
                    "damage_diff": round(d_dmg, 4),
                    "cooldown_diff": round(d_cd, 4),
                    "energy_diff": round(d_nrg, 4),
                    "coeff_diff": round(d_coef, 4),
                    "meta_score_impact": round(total_impact, 4)
                })

        return pd.DataFrame(impacts)

    def generate_item_meta_scores(self, spell_diff_df: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregates spell impacts up to the item level to determine 
        which weapons/armors got the biggest buffs/nerfs overall.
        """
        if spell_diff_df.empty:
            return pd.DataFrame()

        # Group by item_id and sum the impacts
        item_impacts = spell_diff_df.groupby('item_id')['meta_score_impact'].sum().reset_index()
        item_impacts = item_impacts.sort_values(by='meta_score_impact', ascending=False)

        # Add a readable classification
        def classify(score):
            if score > 0.5: return "MASSIVE BUFF"
            if score > 0.1: return "BUFF"
            if score < -0.5: return "MASSIVE NERF"
            if score < -0.1: return "NERF"
            return "MINOR TWEAK"

        item_impacts['classification'] = item_impacts['meta_score_impact'].apply(classify)
        return item_impacts

# ==========================================================
# Example Usage / Test
# ==========================================================
if __name__ == "__main__":
    old_patch = {
        "SPELL_BROADSWORD_Q": {
            "item_id": "T4_MAIN_SWORD",
            "spell_name": "Heroic Strike",
            "damage": 100.0,
            "cooldown": 3.0,
            "energy_cost": 15.0,
            "coefficient": 0.8
        },
        "SPELL_BOW_E": {
            "item_id": "T4_2H_BOW",
            "spell_name": "Enchanted Quiver",
            "damage": 50.0,
            "cooldown": 20.0,
            "energy_cost": 30.0,
            "coefficient": 0.4
        }
    }

    new_patch = {
        "SPELL_BROADSWORD_Q": {
            "item_id": "T4_MAIN_SWORD",
            "spell_name": "Heroic Strike",
            "damage": 115.0,      # BUFF (damage up)
            "cooldown": 2.5,      # BUFF (cooldown down)
            "energy_cost": 15.0,
            "coefficient": 0.8
        },
        "SPELL_BOW_E": {
            "item_id": "T4_2H_BOW",
            "spell_name": "Enchanted Quiver",
            "damage": 45.0,       # NERF (damage down)
            "cooldown": 25.0,     # NERF (cooldown up)
            "energy_cost": 35.0,  # NERF (energy up)
            "coefficient": 0.35   # NERF (scaling down)
        }
    }

    engine = PatchDiffEngine()
    diffs = engine.diff_spells(old_patch, new_patch)
    print("--- SPELL DIFFS ---")
    print(diffs.to_string())

    print("\n--- ITEM META SCORES ---")
    item_scores = engine.generate_item_meta_scores(diffs)
    print(item_scores.to_string())
