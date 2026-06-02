"""
Item taxonomy and categorization.
"""


def get_item_category(item_id: str) -> str:
    """
    Returns the category for an item based on its ID structure.
    """
    item_id = item_id.upper()

    if any(
        weapon in item_id
        for weapon in [
            "MAIN",
            "2H",
            "BOW",
            "STAFF",
            "SWORD",
            "AXE",
            "MACE",
            "HAMMER",
            "SPEAR",
            "DAGGER",
            "KNIFE",
        ]
    ):
        return "weapon"
    if any(armor in item_id for armor in ["ARMOR", "HEAD", "SHOES"]):
        return "armor"
    if any(accessory in item_id for accessory in ["BAG", "CAPE", "MOUNT"]):
        return "accessory"
    if any(consumable in item_id for consumable in ["POTION", "MEAL"]):
        return "consumable"
    if any(
        resource in item_id
        for resource in [
            "WOOD",
            "ROCK",
            "ORE",
            "HIDE",
            "FIBER",
            "PLANKS",
            "STONEBLOCK",
            "METALBAR",
            "LEATHER",
            "CLOTH",
        ]
    ):
        return "resource"
    if "TRASH" in item_id:
        return "trash"

    return "unknown"
