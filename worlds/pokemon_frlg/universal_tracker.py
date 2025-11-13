from typing import TYPE_CHECKING, Dict

from .data import data, NATIONAL_ID_TO_SPECIES_ID, EncounterType, EventData

if TYPE_CHECKING:
    from . import PokemonFRLGWorld

def ut_set_options(world: "PokemonFRLGWorld") -> None:
    for key, value in world.ut_slot_data.items():
        try:
            getattr(world.options, key).value = value
        except AttributeError:
            pass

def ut_set_wild_pokemon(world: "PokemonFRLGWorld") -> None:
    game_version = world.options.game_version.current_key
    wild_encounters = world.ut_slot_data["wild_encounters"]

    for encounter_key, ids in wild_encounters.items():
        already_placed: Dict[int, int] = {}
        index = 0

        if encounter_key.startswith("LAND") or encounter_key.startswith("WATER"):
            encounter_type, map_id = encounter_key.split("_", 1)
        else:
            encounter_type, _, map_id = encounter_key.split("_", 2)

        map_data = world.modified_maps[map_id]
        encounters = (map_data.encounters[EncounterType.LAND] if encounter_type == "LAND" else
                      map_data.encounters[EncounterType.WATER] if encounter_type == "WATER" else
                      map_data.encounters[EncounterType.FISHING])
        slots = encounters.slots[game_version]
        if encounter_type == "OLD":
            slots = [e for i, e in enumerate(slots) if i < 2]
        elif encounter_type == "GOOD":
            slots = [e for i, e in enumerate(slots) if 2 <= i < 5]
        elif encounter_type == "SUPER":
            slots = [e for i, e in enumerate(slots) if i >= 5]

        for slot in slots:
            if slot.species_id in already_placed:
                slot.species_id = already_placed[slot.species_id]
            else:
                new_species_id = NATIONAL_ID_TO_SPECIES_ID[ids[index]]
                already_placed[slot.species_id] = new_species_id
                slot.species_id = new_species_id
                index += 1


def ut_set_legendary_pokemon(world: "PokemonFRLGWorld") -> None:
    for id, legendary_pokemon in world.modified_legendary_pokemon.items():
        if id not in world.modified_events or id not in world.ut_slot_data["static_encounters"]:
            continue

        species_id = NATIONAL_ID_TO_SPECIES_ID[world.ut_slot_data["static_encounters"][id]]
        item = world.modified_events[id].item

        if item.startswith("Static"):
            item = f"Static {world.modified_species[species_id].name}"
        else:
            item = world.modified_species[species_id].name

        new_event = EventData(
            world.modified_events[id].id,
            world.modified_events[id].name,
            item,
            world.modified_events[id].parent_region_id,
            world.modified_events[id].category
        )

        world.modified_events[id] = new_event


def ut_set_misc_pokemon(world: "PokemonFRLGWorld") -> None:
    for id, misc_pokemon in world.modified_misc_pokemon.items():
        if id not in world.modified_events or id not in world.ut_slot_data["static_encounters"]:
            continue

        species_id = NATIONAL_ID_TO_SPECIES_ID[world.ut_slot_data["static_encounters"][id]]
        item = world.modified_events[id].item

        if item.startswith("Static"):
            item = f"Static {world.modified_species[species_id].name}"
        else:
            item = world.modified_species[species_id].name

        new_event = EventData(
            world.modified_events[id].id,
            world.modified_events[id].name,
            item,
            world.modified_events[id].parent_region_id,
            world.modified_events[id].category
        )

        world.modified_events[id] = new_event

    for id, trade_pokemon in world.modified_trade_pokemon.items():
        if id not in world.modified_events or id not in world.ut_slot_data["static_encounters"]:
            continue

        species_id = NATIONAL_ID_TO_SPECIES_ID[world.ut_slot_data["static_encounters"][id]]
        item = world.modified_events[id].item

        if item.startswith("Static"):
            item = f"Static {world.modified_species[species_id].name}"
        else:
            item = world.modified_species[species_id].name

        new_event = EventData(
            world.modified_events[id].id,
            world.modified_events[id].name,
            item,
            world.modified_events[id].parent_region_id,
            world.modified_events[id].category
        )

        world.modified_events[id] = new_event


def ut_set_tm_hm_compatibility(world: "PokemonFRLGWorld") -> None:
    for species_id, species in world.modified_species.items():
        species.tm_hm_compatibility = world.ut_slot_data["tm_hm_compatibility"][species.name]


def ut_set_requested_trade_pokemon(world: "PokemonFRLGWorld") -> None:
    game_version = world.options.game_version.current_key

    for id, trade_pokemon in world.modified_trade_pokemon.items():
        species_id = world.ut_slot_data["requested_trade_pokemon"][id]
        trade_pokemon.requested_species_id[game_version] = species_id
        world.logic.required_trade_pokemon[data.events[id].name] = data.species[species_id].name


def ut_set_entrances(world: "PokemonFRLGWorld") -> None:
    deferred_entrances = (hasattr(world.multiworld, "enforce_deferred_connections")
                          and world.multiworld.enforce_deferred_connections in ("on", "default"))
    datastorage_key_prefix = "pokemon_frlg_{player}_"

    if "entrances" in world.ut_slot_data:
        for entrance_name, region_name in world.ut_slot_data["entrances"].items():
            entrance = world.get_entrance(entrance_name)
            region = world.get_region(region_name)
            entrance.connected_region.entrances.remove(entrance)
            if deferred_entrances:
                entrance.connected_region = None
                datastorage_key = datastorage_key_prefix + entrance_name
                world.found_entrances_datastorage_key.append(datastorage_key)
            else:
                entrance.connected_region = region
                region.entrances.append(entrance)


def ut_reconnect_found_entrances(world: "PokemonFRLGWorld", found_key: str) -> None:
    entrance_name = found_key.split("_")[-1]
    region_name = world.ut_slot_data["entrances"][entrance_name]
    entrance = world.get_entrance(entrance_name)
    region = world.get_region(region_name)
    entrance.connected_region = region
    region.entrances.append(entrance)
