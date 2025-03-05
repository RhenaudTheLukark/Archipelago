from typing import Dict, Set

from .data import data

ITEM_GROUPS: Dict[str, Set[str]] = {}

for item in data.items.values():
    for tag in item.tags:
        if tag not in ITEM_GROUPS:
            ITEM_GROUPS[tag] = set()
        ITEM_GROUPS[tag].add(item.name)