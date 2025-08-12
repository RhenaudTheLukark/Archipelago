from typing import TYPE_CHECKING, Dict
from BaseClasses import Item, ItemClassification
from .data import data
from .groups import item_groups
from .options import ShuffleRunningShoes

if TYPE_CHECKING:
    from . import PokemonFRLGWorld


class PokemonFRLGItem(Item):
    game: str = "Pokemon FireRed and LeafGreen"

    def __init__(self, name: str, classification: ItemClassification, code: int | None, player: int) -> None:
        super().__init__(name, classification, code, player)


def create_item_name_to_id_map() -> Dict[str, int]:
    """
    Creates a map from item names to their AP item ID (code)
    """
    name_to_id_map: Dict[str, int] = {}
    for item_id, item_data in data.items.items():
        name_to_id_map[item_data.name] = item_id

    return name_to_id_map


def get_item_classification(item_id: int) -> ItemClassification:
    """
    Returns the item classification for a given AP item id (code)
    """
    return data.items[item_id].classification


def add_starting_items(world: "PokemonFRLGWorld") -> None:
    start_inventory = world.options.start_inventory.value.copy()
    if not world.options.shuffle_berry_pouch:
        start_inventory["Berry Pouch"] = 1
        world.multiworld.push_precollected(world.create_item("Berry Pouch"))
    if not world.options.shuffle_tm_case:
        start_inventory["TM Case"] = 1
        world.multiworld.push_precollected(world.create_item("TM Case"))
    if not world.options.shuffle_ledge_jump:
        start_inventory["Ledge Jump"] = 1
        world.multiworld.push_precollected(world.create_item("Ledge Jump"))
    if world.options.shuffle_running_shoes == ShuffleRunningShoes.option_start_with:
        start_inventory["Running Shoes"] = 1
        world.multiworld.push_precollected(world.create_item("Running Shoes"))

def get_random_item(world: "PokemonFRLGWorld", item_classification: ItemClassification = None) -> str:
    if item_classification is None:
        item_classification = ItemClassification.useful if world.random.random() < 0.20 else ItemClassification.filler
    items = [item for item in data.items.values()
             if item.classification == item_classification and item.name not in item_groups["Unique Items"]]
    return world.random.choice(items).name
