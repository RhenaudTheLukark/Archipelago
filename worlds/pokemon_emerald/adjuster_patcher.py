import math
import os
import zlib

from PIL.Image import new as PIL_new
from Utils import open_image_secure
from .data import data
from .adjuster_constants import *

address_label_to_resource_path_list = { }
sprite_pack_data = { }
resource_address_to_insert_to = 0x00
current_rom = None

data_addresses = DATA_ADDRESSES_MOCK_AP

####################
## Main Functions ##
####################

def get_patch_from_sprite_pack(_sprite_pack_path):
    # Builds a patch from a given sprite pack to apply to the ROM
    global sprite_pack_data, resource_address_to_insert_to
    # Build patch data, fetch end of file
    sprite_pack_data = { 'length': 16777216, 'data': [] }
    resource_address_to_insert_to = ((data_addresses['sEmpty6'] >> 12) + 1) << 12 # Should be E3D000

    # Handle existing Trainer & Pokemon folders
    add_sprite_pack_object_collection(_sprite_pack_path, TRAINER_FOLDERS, TRAINER_SPRITES, TRAINER_PALETTES, False)
    add_sprite_pack_object_collection(_sprite_pack_path, POKEMON_FOLDERS, POKEMON_SPRITES, POKEMON_PALETTES, True)
    return sprite_pack_data

#########################
## Patch Data Building ##
#########################

def add_sprite_pack_object_collection(_sprite_pack_path, _folders_list, _sprites_list, _palette_lists, _is_pokemon):
    # Adds data from all pokemon or all trainers to the patch if a folder including their name can be found
    for object_name in _folders_list:
        object_folder_path = os.path.join(_sprite_pack_path, object_name)
        if not os.path.exists(object_folder_path):
            continue
        if _is_pokemon:
            # The Egg Pokemon sprite has an extra sprite for its hatching animation
            _sprites_list = EGG_SPRITES if object_name == 'Egg' else POKEMON_SPRITES
            _palette_lists = EGG_PALETTES if object_name == 'Egg' else POKEMON_PALETTES
        found_sprites = { }
        for resource_name in os.listdir(object_folder_path):
            if resource_name == 'data.txt' and _is_pokemon and object_name != 'Egg' and (not object_name.startswith('Unown ') or object_name == 'Unown A'):
                add_pokemon_data(object_name, os.path.join(object_folder_path, resource_name))
            if not resource_name.endswith('.png'):
                continue
            # Only handle sprites which are awaited for the current object
            matching_sprite_name = next(filter(lambda f: resource_name.startswith(f), _sprites_list), None)
            if not matching_sprite_name:
                continue
            sprite_file_name_data = resource_name[:-4].split('-')[1:]
            extra_sprite_data = sprite_file_name_data or None
            sprite_path = os.path.join(object_folder_path, resource_name)
            if found_sprites.get(matching_sprite_name):
                continue
            found_sprites[matching_sprite_name] = resource_name
            add_sprite(_is_pokemon, object_name, matching_sprite_name, extra_sprite_data, sprite_path)
        for palette, palette_extraction_priority_queue in _palette_lists.items():
            # Generate palettes if sprites exist
            found_sprite = False
            for resource_name in palette_extraction_priority_queue:
                if resource_name in found_sprites:
                    sprite_path = os.path.join(object_folder_path, found_sprites.get(resource_name))
                    found_sprite = True
                    add_palette(_is_pokemon, object_name, palette, sprite_path)
                    break
            if not found_sprite:
                # Try to find raw sprites if they have not been recorded yet
                for resource_name in palette_extraction_priority_queue:
                    sprite_path = os.path.join(object_folder_path, resource_name + '.png')
                    if os.path.exists(sprite_path):
                        add_palette(_is_pokemon, object_name, palette, sprite_path)
                        break

def add_sprite(_is_pokemon, _object_name, _sprite_name, _extra_data, _path):
    # Adds a sprite to the patch
    sprite_key = ('pokemon_' if _is_pokemon else 'trainer_') + _sprite_name
    data_address, is_raw = get_address_from_address_collection(_object_name, sprite_key, _sprite_name)

    if _is_pokemon and _sprite_name == 'icon' and _extra_data:
        # Pokemon palette indexed icon: Switch the palette to use if it's forced within the file's name
        palette_index = int(_extra_data[0])
        icon_index_address, _ = get_address_from_address_collection(_object_name, sprite_key + '_index', _sprite_name)
        add_data_to_patch({ 'address': icon_index_address, 'length': 1, 'data': palette_index.to_bytes(1, 'little')})

    if is_complex_sprite(sprite_key):
        data_address = replace_complex_sprite(data_address, sprite_key, _object_name, _extra_data)

    if sprite_key != 'trainer_battle_back':
        if is_raw:
            add_raw_resource(False, sprite_key, data_address, _path)
        else:
            add_resource(False, sprite_key, data_address, _path)
    else:
        # In case of Trainer battle back sprite, rerun this function to fill in the ball throwing animation table
        address_bytes = resource_address_to_insert_to.to_bytes(3, 'little')
        add_data_to_patch({ 'address': data_address, 'length': 3, 'data': address_bytes })
        add_sprite(_is_pokemon, _object_name, _sprite_name + '_throw', _extra_data, _path)

def add_palette(_is_pokemon, _object_name, _palette_name, _path):
    # Adds a palette to the patch
    palette_key = ('pokemon' if _is_pokemon else 'trainer') + '_' + _palette_name
    if _object_name.startswith('Unown '):
        _object_name = 'Unown A'
    data_address, is_raw = get_address_from_address_collection(_object_name, palette_key, _palette_name)
    if is_raw:
        add_raw_resource(True, palette_key, data_address, _path)
    else:
        add_resource(True, palette_key, data_address, _path)

def add_resource(_is_palette, _key, _data_address, _path):
    # Adds a resource (sprite or palette) to the patch and replaces its given pointer
    global resource_address_to_insert_to
    address_bytes = resource_address_to_insert_to.to_bytes(3, 'little')
    add_data_to_patch({ 'address': _data_address, 'length': 3, 'data': address_bytes })

    data_length = add_raw_resource(_is_palette, _key, resource_address_to_insert_to, _path)
    resource_address_to_insert_to = resource_address_to_insert_to + data_length
    if resource_address_to_insert_to > 0xFFFFFF:
        # Out of bounds: Too much data to add
        raise Exception('Too much data to add to the ROM! Please remove some resources.')

def add_raw_resource(_is_palette, _key, _data_address, _path):
    # Adds a raw resource to the patch at the given address
    needs_compression = OBJECT_NEEDS_COMPRESSION.get(_key, False)
    if _is_palette:
        resource_data = handle_sprite_to_palette(_path, needs_compression)
    else:
        resource_data = handle_sprite_to_gba_sprite(_path, needs_compression)
    add_data_to_patch({ 'address': _data_address, 'length': len(resource_data), 'data': resource_data })
    return len(resource_data)

def add_pokemon_data(_pokemon_name, _data_path):
    # Adds a given pokemon data and move pool to the patch
    with open(_data_path) as data_file:
        new_pokemon_data = destringify_pokemon_data(_pokemon_name, data_file.read())
    old_pokemon_data = get_pokemon_data(_pokemon_name)

    # Replace the pokemon data as a whole
    pokemon_data = merge_pokemon_data(old_pokemon_data, new_pokemon_data, True)
    pokemon_data_bytes = encode_pokemon_data(pokemon_data)
    data_address_stats, _ = get_address_from_address_collection(_pokemon_name, 'pokemon_stats', 'stats')
    add_data_to_patch({ 'address': data_address_stats, 'length': 28, 'data': pokemon_data_bytes })

    if 'move_pool' in new_pokemon_data:
        # Add a new move pool table and replace the pointer to it
        pokemon_move_pool_bytes = encode_move_pool(pokemon_data['move_pool'])
        global resource_address_to_insert_to
        # Move pool data MUST be isolated in its own 16 byte blocks, or reading it WILL cause garbage code execution
        resource_address_to_insert_to = (((resource_address_to_insert_to - 1) >> 4) + 1) << 4
        new_resource_address_bytes = resource_address_to_insert_to.to_bytes(3, 'little')
        data_pointer_move_pool, _ = get_address_from_address_collection(_pokemon_name, 'pokemon_move_pool', 'move_pool')
        add_data_to_patch({ 'address': data_pointer_move_pool, 'length': 3, 'data': new_resource_address_bytes })
        add_data_to_patch({ 'address': resource_address_to_insert_to, 'length': len(pokemon_move_pool_bytes), 'data': pokemon_move_pool_bytes })
        resource_address_to_insert_to += (((len(pokemon_move_pool_bytes) - 1) >> 4) + 1) << 4
        if resource_address_to_insert_to > 0xFFFFFF:
            # Out of bounds: Too much data to add
            raise Exception('Too much data to add to the ROM! Please remove some resources.')

def add_data_to_patch(_data):
    # Adds the given data to the patch
    index = 0
    # Order entries by ascending starting address
    for existing_data in sprite_pack_data['data']:
        if existing_data['address'] < _data['address']:
            index = index + 1
        elif existing_data['address'] == _data['address']:
            # Do not duplicate values
            return
        else:
            break
    sprite_pack_data['data'].insert(index, _data)

#############################
## Complex Sprite Handling ##
#############################

def replace_complex_sprite(_data_address, _sprite_key, _object_name, _extra_data):
    # Replaces a complex sprite's sprite data and update its other fields if needed
    sprite_size_data = None
    if _sprite_key == 'trainer_battle_back_throw':
        # Trainer back sprites need further pointer seeking
        info_object_address = _data_address
        _data_address = int.from_bytes(bytes(current_rom[_data_address + 12:_data_address + 15]), 'little')
    elif is_overworld_sprite(_sprite_key):
        # Trainer overworld sprites need two objects to delve into
        info_object_address = int.from_bytes(bytes(current_rom[_data_address:_data_address + 3]), 'little')
        _data_address = get_overworld_sprite_data(info_object_address, 'sprites_ptr')
        if _extra_data:
            # If size given, extract it and check if it is supported
            sprite_size_data = handle_overworld_custom_size(_extra_data)

    sprite_requirements = get_sprite_requirements(_sprite_key, _object_name)
    temp_address = resource_address_to_insert_to
    if not sprite_requirements:
        raise Exception('Could not find sprite data for the sprite with key {} of object {}.'.format(_sprite_key, _object_name))

    sprite_width = sprite_size_data.get('width') if sprite_size_data else sprite_requirements.get('width', 0)
    sprite_height = sprite_size_data.get('height') if sprite_size_data else sprite_requirements.get('height', 0)
    sprite_palette_size = sprite_requirements.get('palette_size', 16)
    bits_per_pixel = get_bits_per_pixel_from_palette_size(sprite_palette_size)
    if is_overworld_sprite(_sprite_key) and not sprite_size_data:
        sprite_width = get_overworld_sprite_data(info_object_address, 'sprite_width')
        sprite_height = get_overworld_sprite_data(info_object_address, 'sprite_height')
    sprite_size = round(sprite_width * sprite_height * bits_per_pixel / 8)

    # Build a new complex sprite table and insert it
    output_data = bytearray(0)
    for i in range(0, sprite_requirements.get('frames')):
        output_data.extend(temp_address.to_bytes(3, 'little'))
        output_data.extend(b'\x08')
        output_data.extend(sprite_size.to_bytes(2, 'little'))
        output_data.extend(b'\x00\x00')
        temp_address += sprite_size
    add_data_to_patch({'address': _data_address, 'length': len(output_data), 'data': bytes(output_data)})

    if is_overworld_sprite(_sprite_key) and sprite_size_data:
        # If custom size given, update overworld sprite data
        for current_overworld_info_object_pointer in get_overworld_sprite_addresses(_object_name, _sprite_key[8:]):
            current_overworld_info_object = int.from_bytes(bytes(current_rom[current_overworld_info_object_pointer:current_overworld_info_object_pointer + 3]), 'little')
            set_overworld_sprite_data(current_overworld_info_object, 'sprite_length', sprite_size)
            set_overworld_sprite_data(current_overworld_info_object, 'sprite_width', sprite_width)
            set_overworld_sprite_data(current_overworld_info_object, 'sprite_height', sprite_height)
            set_overworld_sprite_data(current_overworld_info_object, 'size_draw_ptr', data_addresses[sprite_size_data.get('data')])

    return _data_address

def extract_complex_sprite(_overworld_struct_address, _sprite_key, _object_name, _palette_sprite_name):
    # Extracts a complex sprite from the ROM as a Pillow sprite ready to be saved
    start_sprite_pointer = get_overworld_sprite_data(_overworld_struct_address, 'sprites_ptr')
    sprite_width = get_overworld_sprite_data(_overworld_struct_address, 'sprite_width')
    sprite_height = get_overworld_sprite_data(_overworld_struct_address, 'sprite_height')
    sprite_requirements = get_sprite_requirements(_sprite_key, _object_name)
    if not sprite_requirements:
        return
    sprites_pixel_data = []
    sprite_palette = None
    extra_sprite_name = ''
    for i in range(sprite_requirements['frames']):
        # Considers each frame as a sprite, then adds all of the frames' pixel data together
        start_sprite_address = int.from_bytes(bytes(current_rom[start_sprite_pointer:start_sprite_pointer + 3]), 'little')
        sprite, current_extra_sprite_name = extract_sprite(start_sprite_address, _sprite_key, _object_name, _palette_sprite_name, (sprite_width, sprite_height))
        sprites_pixel_data += sprite.getdata()
        if i == 0:
            sprite_palette = sprite.getpalette()
            extra_sprite_name = current_extra_sprite_name
        start_sprite_pointer += 8

    final_image = PIL_new('P', (sprite_width, sprite_height * sprite_requirements['frames']))
    final_image.putdata(sprites_pixel_data)
    final_image.putpalette(sprite_palette)
    return final_image, extra_sprite_name

#####################
## Data Extraction ##
#####################

def extract_palette_from_file(_path):
    # Extracts a palette from an existing sprite file
    sprite_image = open_image_secure(_path)
    sprite_palette = sprite_image.getpalette() or []
    sprite_palette_colors = []
    for i in range(round(len(sprite_palette) / 3)):
        index = i * 3
        color = (int(sprite_palette[index]) << 16) + (int(sprite_palette[index+1]) << 8) + int(sprite_palette[index+2])
        sprite_palette_colors.append(hex(color)[2:].zfill(6))
    return sprite_palette_colors

def extract_sprites(_object_name, _output_path):
    # Extracts all sprites from a given object from the ROM into the given output folder
    def handle_sprite_extraction(_sprite_name):
        reference_sprite_name = SPRITE_PIXEL_REFERENCE.get(_sprite_name, _sprite_name)
        sprite_key = ('pokemon' if is_pokemon else 'trainer') + '_' + reference_sprite_name
        data_address, is_raw = get_address_from_address_collection(_object_name, sprite_key, reference_sprite_name)
        if not is_raw:
            data_address = int.from_bytes(bytes(current_rom[data_address:data_address + 3]), 'little')

        if is_complex_sprite(sprite_key):
            sprite_object, extra_sprite_name = extract_complex_sprite(data_address, sprite_key, _object_name, reference_sprite_name)
        else:
            sprite_object, extra_sprite_name = extract_sprite(data_address, sprite_key, _object_name, _sprite_name)
        full_path = os.path.join(_output_path, _sprite_name + extra_sprite_name + '.png')
        sprite_object.save(full_path)

    is_pokemon = not _object_name in TRAINER_FOLDERS
    extracted_sprites = []

    # Extract all sprites awaited for the given object
    sprite_list = EGG_SPRITES if _object_name == 'Egg' else POKEMON_SPRITES if is_pokemon else TRAINER_SPRITES
    for sprite_name in sprite_list:
        handle_sprite_extraction(sprite_name)
        extracted_sprites.append(sprite_name)

    # If any extra sprite is awaited for depicting palettes, extract them as well
    palette_lists = EGG_PALETTES if _object_name == 'Egg' else POKEMON_PALETTES if is_pokemon else TRAINER_PALETTES
    palette_sprites = [palette_lists[palette_list] for palette_list in palette_lists]
    palette_sprites = filter(lambda s: s, [sprite if not sprite in extracted_sprites else None for sprite in flatten_2d(palette_sprites)])
    for sprite_name in palette_sprites:
        handle_sprite_extraction(sprite_name)

def extract_sprite(_data_address, _sprite_key, _object_name, _palette_sprite_name, _preset_size = 0):
    # Extracts a given sprite from the ROM as a Pillow sprite ready to be saved
    extra_sprite_name = ''

    needs_compression = OBJECT_NEEDS_COMPRESSION.get(_sprite_key, False)
    sprite_requirements = get_sprite_requirements(_sprite_key, _object_name)
    sprite_palette_size = sprite_requirements.get('palette_size', 16)
    bits_per_pixel = get_bits_per_pixel_from_palette_size(sprite_palette_size)
    # Retrieve the sprite's size
    if _preset_size:
        sprite_width = _preset_size[0]
        sprite_height = _preset_size[1]
    else:
        sprite_width = sprite_requirements['width']
        sprite_height = sprite_requirements['height'] * sprite_requirements['frames']

    # Extract the sprite's pixel data
    sprite_size = round(sprite_width * sprite_height * bits_per_pixel / 8)
    end_address = _data_address + sprite_size + ((4 + math.ceil(sprite_size / 8)) if needs_compression else 0)
    sprite_pixel_data = current_rom[_data_address:end_address]
    if needs_compression:
        sprite_pixel_data = truncate_lz_compressed_data(sprite_pixel_data, sprite_size)
        sprite_pixel_data = decompress_lz_data(sprite_pixel_data)
    sprite_pixel_data = decompress_sprite(sprite_pixel_data, bits_per_pixel)
    sprite_pixel_data = dechunk_sprite(sprite_pixel_data, sprite_width, sprite_height)
    if sprite_requirements.get('palette_per_frame', False):
        sprite_pixel_data = spread_palettes_to_sprite_frames(sprite_pixel_data, sprite_width, sprite_height, sprite_requirements.get('palettes', 1))

    # Extract the sprite's palette(s)
    if _palette_sprite_name == 'icon':
        # Retrieve the icon's palette index and add it at the end of the file's name
        icon_index_address, _ = get_address_from_address_collection(_object_name, _sprite_key + '_index', _object_name)
        icon_index = int(current_rom[icon_index_address])
        sprite_palette = bytes(VALID_ICON_PALETTES[icon_index])
        extra_sprite_name = '-{}'.format(int(icon_index))
    elif _palette_sprite_name == 'footprint':
        sprite_palette = bytes(VALID_FOOTPRINT_PALETTE)
    else:
        sprite_palette = extract_palette(_object_name, _palette_sprite_name, _sprite_key.startswith('pokemon_'))

    # Assemble the sprite
    extracted_image = PIL_new('P', (sprite_width, sprite_height))
    extracted_image.putdata(sprite_pixel_data)
    extracted_image.putpalette(sprite_palette)
    return extracted_image, extra_sprite_name

def extract_palette(_object_name, _sprite_name, _is_pokemon):
    # Extracts a palette as a list of RGB colors with values between 0 and 255
    palette_lists = EGG_PALETTES if _object_name == 'Egg' else POKEMON_PALETTES if _is_pokemon else TRAINER_PALETTES
    palette_name = next(filter(lambda palette_list: palette_list if _sprite_name in palette_lists[palette_list] else None, palette_lists), None)
    palette_key = ('pokemon_' if _is_pokemon else 'trainer_') + palette_name
    sprite_key = ('pokemon_' if _is_pokemon else 'trainer_') + _sprite_name

    sprite_requirements = get_sprite_requirements(sprite_key, _object_name)
    palette_size = sprite_requirements.get('palette_size', 16) * sprite_requirements.get('palettes', 1) * 2
    data_address, is_raw = get_address_from_address_collection(_object_name, palette_key, palette_name)
    if not is_raw:
        data_address = int.from_bytes(bytes(current_rom[data_address:data_address + 3]), 'little')

    needs_compression = OBJECT_NEEDS_COMPRESSION.get(palette_key, False)
    end_address = data_address + palette_size + ((4 + math.ceil(palette_size / 8)) if needs_compression else 0)
    palette_data = current_rom[data_address:end_address]
    if needs_compression:
        # If the data is compressed, decompress it first
        palette_data = truncate_lz_compressed_data(palette_data, palette_size)
        palette_data = decompress_lz_data(palette_data)

    palette = []
    for i in range(round(palette_size / 2)):
        palette_five_bits_color = int.from_bytes(palette_data[i*2:i*2+2], 'little')
        for _ in range(3):
            palette.append(five_to_eight_bits_palette(palette_five_bits_color % 32))
            palette_five_bits_color >>= 5
    return palette

#####################
## Data Conversion ##
#####################

def handle_sprite_to_gba_sprite(_sprite_path, _needs_compression):
    # Transforms indexed/grayscale PNG sprites into GBA sprites
    sprite_image = open_image_secure(_sprite_path)
    sprite_palette_size = round(len(sprite_image.getpalette()) / 3)
    bits_per_pixel = get_bits_per_pixel_from_palette_size(sprite_palette_size)

    # Chunk the data then compress it
    sprite_data = compress_sprite(chunk_sprite(bytes(sprite_image.getdata()), sprite_image.width, sprite_image.height), bits_per_pixel)
    if _needs_compression:
        # Compresses sprite if needed
        sprite_data = compress_lz_data(sprite_data)
    return bytes(sprite_data)

def handle_sprite_to_palette(_sprite_path, _needs_compression):
    # Transforms indexed/grayscale PNG sprites into GBA palettes
    sprite_image = open_image_secure(_sprite_path)
    palette_data = sprite_image.getpalette()
    palette_size = round(len(palette_data) / 3)

    # Transforms normal palette data into a GBA palette (8 bit colors to 5 bit colors)
    palette = [0 for _ in range(palette_size * 2)]
    for i in range(palette_size):
        palette_color_eight_bits = palette_data[i*3:(i+1)*3]
        palette_color_five_bits = 0
        for j in range(2, -1, -1):
            color_five_bits = eight_to_five_bits_palette(palette_color_eight_bits[j])
            palette_color_five_bits |= color_five_bits
            if j > 0:
                palette_color_five_bits <<= 5
        palette[i*2] = palette_color_five_bits & 0xFF
        palette[i*2+1] = palette_color_five_bits >> 8

    if _needs_compression:
        # Compresses palette if needed
        palette = compress_lz_data(bytes(palette))
    return bytes(palette)

###################
## Data Checking ##
###################

def validate_sprite_pack(_sprite_pack_path):
    # Validates an entire sprite pack to see if it can be applied to the given ROM
    errors = ''
    has_error = False
    def add_error(_error, _is_error = False):
        nonlocal errors, has_error
        if _error:
            has_error = has_error or _is_error
            errors += ('\n' if errors else '') + _error

    add_error(*validate_object_collection(_sprite_pack_path, TRAINER_FOLDERS, TRAINER_SPRITES, TRAINER_PALETTES))
    add_error(*validate_object_collection(_sprite_pack_path, POKEMON_FOLDERS, POKEMON_SPRITES, POKEMON_PALETTES))

    if not sprite_pack_folder_list:
        add_error('Error: The current sprite pack contains no resource to apply.', True)

    return errors, has_error

sprite_pack_folder_list = []
def validate_object_collection(_sprite_pack_path, _folders_list, _sprites_list, _palette_lists):
    # Validates all pokemon or all trainers if a folder including their name can be found
    global sprite_pack_folder_list
    sprite_pack_folder_list = []

    errors = ''
    has_error = False
    def add_error(_error, _is_error = False, _processed = False):
        nonlocal errors, has_error
        if _error:
            has_error = has_error or _is_error
            errors += ('\n' if errors else '') + ('' if _processed else 'Error: ' if _is_error else 'Warning: ') + _error

    def add_to_folder_list(_folder):
        global sprite_pack_folder_list
        if not _folder in sprite_pack_folder_list:
            sprite_pack_folder_list.append(_folder)

    is_pokemon = _folders_list == POKEMON_FOLDERS
    for object_name in _folders_list:
        object_folder_path = os.path.join(_sprite_pack_path, object_name)
        if not os.path.exists(object_folder_path):
            continue
        if is_pokemon:
            # The Egg Pokemon sprite has an extra sprite for its hatching animation
            _sprites_list = EGG_SPRITES if object_name == 'Egg' else POKEMON_SPRITES
            _palette_lists = EGG_PALETTES if object_name == 'Egg' else POKEMON_PALETTES
        found_sprites = { }
        for resource_name in os.listdir(object_folder_path):
            if resource_name == 'data.txt' and is_pokemon and object_name != 'Egg' and (not object_name.startswith('Unown ') or object_name == 'Unown A'):
                # Text file that holds the Pokemon's modified data
                with open(os.path.join(object_folder_path, resource_name)) as pokemon_data_file:
                    add_error(*validate_pokemon_data_string(object_name, pokemon_data_file.read()), True)
                    add_to_folder_list(object_name)
                    continue
            if not resource_name.endswith('.png'):
                add_error('File {} in folder {}: Not a recognized file and should be removed.'.format(resource_name, object_name))
                continue
            # Only handle sprites which are awaited for the current object
            matching_sprite_name = next(filter(lambda f: resource_name.startswith(f), _sprites_list), None)
            if not matching_sprite_name:
                # Allow sprites depicting an awaited palette
                if not next(filter(lambda palette_list: resource_name[:-4] in _palette_lists[palette_list], _palette_lists), None):
                    add_error('File {} in folder {}: Cannot be linked to a valid internal sprite or palette.'.format(resource_name, object_name))
                    continue
                matching_sprite_name = resource_name[:-4]
            sprite_file_name_data = resource_name[:-4].split('-')[1:]
            extra_sprite_data = sprite_file_name_data or None
            sprite_path = os.path.join(object_folder_path, resource_name)
            if found_sprites.get(matching_sprite_name):
                add_error('File {} in folder {}: Duplicate internal sprite entry with sprite {}.'.format(resource_name, object_name, found_sprites.get(matching_sprite_name)), True)
                continue
            found_sprites[matching_sprite_name] = resource_name
            add_to_folder_list(object_name)
            add_error(*validate_sprite(object_name, matching_sprite_name, extra_sprite_data, sprite_path), True)
    return errors, has_error

def validate_sprite(_object_name, _sprite_name, _extra_data, _path):
    # Validates a given sprite using metrics registered in the sprite requirements table
    errors = ''
    has_error = False
    def add_error(_error, _is_error = False):
        nonlocal errors, has_error
        if _error:
            has_error = has_error or _is_error
            errors += ('\n' if errors else '') + ('Error: ' if _is_error else 'Warning: ') + _error

    is_pokemon = _object_name in POKEMON_FOLDERS
    sprite_key = ('pokemon_' if is_pokemon else 'trainer_') + _sprite_name
    sprite_requirements = get_sprite_requirements(sprite_key, _object_name)

    try:
        sprite_image = open_image_secure(_path)
    except:
        add_error('File {} in folder {}: The sprite is not a valid PNG file.'.format(_sprite_name, _object_name), True)
        return errors, has_error

    # Palette checks
    if not sprite_image.palette:
        add_error('File {} in folder {}: The sprite is not an indexed PNG file.'.format(_sprite_name, _object_name), True)
    elif sprite_image.mode != 'P':
        add_error('File {} in folder {}: The sprite is not a valid indexed PNG file. Colors should be RGB, with no transparency.'.format(_sprite_name, _object_name), True)
    else:
        sprite_palette_colors = sprite_image.getpalette()
        sprite_palette_model = sprite_requirements.get('palette', None)
        sprite_palette_required_size = sprite_requirements.get('palette_size', 0) * sprite_requirements.get('palettes', 1)
        if sprite_palette_required_size > 0 and round(len(sprite_palette_colors) / 3) != sprite_palette_required_size:
            add_error('File {} in folder {}: The sprite\'s palette has {} colors but should have {}.'.format(_sprite_name, _object_name, round(len(sprite_palette_colors) / 3), sprite_palette_required_size), True)
        elif sprite_palette_model:
            matching_palette_model = True
            if is_pokemon and _sprite_name == 'icon':
                # Icons can have several palettes, one must be chosen
                if _extra_data:
                    # Icon palette ID is given in the icon's file name
                    palette_index = int(_extra_data[0])
                    if palette_index < 0 or palette_index > 2:
                        matching_palette_model = False
                        add_error('File {} in folder {}: Icons only have 3 palettes, but you tried using palette #{}.'.format(_sprite_name, _object_name, palette_index + 1), True)
                else:
                    # Icon palette ID must be retrieved from the ROM
                    icon_index_address, _ = get_address_from_address_collection(_object_name, sprite_key + '_index', _object_name)
                    palette_index = int.from_bytes(bytes(current_rom[icon_index_address]), 'little')
                if matching_palette_model:
                    sprite_palette_model = sprite_palette_model[palette_index]
            if matching_palette_model and not is_palette_valid(sprite_palette_colors, sprite_palette_model):
                add_error('File {} in folder {}: The sprite\'s palette does not contain the required colors.'.format(_sprite_name, _object_name), True)

    # Size checks
    sprite_valid_dimensions = []
    if is_overworld_sprite(sprite_key) and _extra_data:
        # If a custom frame size is given for overworld sprites, check that it is valid
        allowed_sizes = ['{}x{}'.format(size['width'], size['height']) for size in VALID_OVERWORLD_SPRITE_SIZES]
        if not _extra_data[0] in allowed_sizes:
            add_error('File {} in folder {}: Invalid custom size {}. The expected sizes are: {}.'.format(_sprite_name, _object_name, _extra_data[0], allowed_sizes), True)
            sprite_valid_dimensions.append({ 'width': 0, 'height': 0 })
        else:
            sizes = _extra_data[0].split('x')
            sprite_valid_dimensions.append({ 'width': int(sizes[0]), 'height': int(sizes[1]) * sprite_requirements.get('frames', 1) })
    else:
        sprite_valid_dimensions.append({ 'width': sprite_requirements.get('width', 0), 'height': sprite_requirements.get('height', 0) * sprite_requirements.get('frames', 0) })
    if sprite_valid_dimensions[0]['width'] > 0 and sprite_valid_dimensions[0]['height'] > 0:
        # Check that the sprite has the awaited size
        if not next(filter(lambda size: size['width'] == sprite_image.width and size['height'] == sprite_image.height, sprite_valid_dimensions), None):
            allowed_sizes = ['{}x{}'.format(size['width'], size['height']) for size in sprite_valid_dimensions]
            current_size = '{}x{}'.format(sprite_image.width, sprite_image.height)
            add_error('File {} in folder {}: Invalid size {}. The expected size{}: {}.'.format(_sprite_name, _object_name, current_size, ' is' if len(allowed_sizes) == 1 else 's are', allowed_sizes[0] if len(allowed_sizes) == 1 else allowed_sizes), True)

    return errors, has_error

def is_palette_valid(_palette, _palette_model):
    # Compares a given palette to its model and checks if it is valid or not
    for i in range(min(len(_palette), len(_palette_model))):
        if _palette_model[i] != -1 and _palette[i] != _palette_model[i]:
            return False
    return True

def validate_pokemon_data_string(_pokemon_name, _data_string):
    # Validates given Pokemon data, making sure that all fields are valid
    errors = ''
    has_error = False
    def add_error(_error, _is_error = False, _processed = False):
        nonlocal errors, has_error
        if _error:
            has_error = has_error or _is_error
            errors += ('\n' if errors else '') + ('' if _processed else 'Error: ' if _is_error else 'Warning: ') + _error

    if _pokemon_name.startswith('Unown '):
        _pokemon_name = 'Unown A'

    # If the given data is a string, extracts its data first
    if type(_data_string) is str:
        try:
            data_dict = destringify_pokemon_data(_pokemon_name, _data_string, True)
        except Exception as e:
            if hasattr(e, 'message'):
                return e.message, True
            else:
                return str(e), True
    else:
        data_dict = _data_string

    for field_name in data_dict:
        field_value = data_dict[field_name]
        if field_name in [ 'hp', 'atk', 'def', 'spatk', 'spdef', 'spd' ]:
            # Data must be a number between 1 and 255
            try:
                field_number_value = int(field_value)
                if field_number_value < 1 or field_number_value > 255:
                    add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
            except Exception:
                add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
        elif field_name in [ 'type1', 'type2' ]:
            # Data must be a number corresponding to a valid type
            try:
                if not field_value.capitalize() in POKEMON_TYPES:
                    field_number_value = int(field_value)
                    if field_number_value < 0 or field_number_value >= len(POKEMON_TYPES):
                        add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
            except Exception:
                add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
        elif field_name in [ 'ability1', 'ability2' ]:
            # Data must be a number corresponding to a valid ability
            try:
                if not field_value.upper() in POKEMON_ABILITIES:
                    field_number_value = int(field_value)
                    if field_number_value < 0 or field_number_value >= len(POKEMON_ABILITIES):
                        add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
            except Exception:
                add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
        elif field_name == 'gender_ratio':
            # Data must be a number corresponding to a valid gender ratio
            try:
                if not field_value in list(POKEMON_GENDER_RATIOS.values()):
                    field_number_value = int(field_value)
                    if not field_number_value in list(POKEMON_GENDER_RATIOS.keys()):
                        add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
            except Exception:
                add_error('{}\'s {} value is invalid: \'{}\'.'.format(_pokemon_name, field_name, field_value), True)
        elif field_name == 'dex':
            # Data must either be a 0 (allowed) or a 1 (forbidden)
            if not field_value in [ 0, 1, '0', '1', 'True', 'False' ]:
                add_error('{}\'s forbid_flip value is invalid: \'{}\'.'.format(_pokemon_name, field_value), True)
        elif field_name == 'move_pool':
            # Data must be a valid move pool table string
            if len(field_value) < 4:
                add_error('{}\'s move pool is empty.'.format(_pokemon_name), True)
            else:
                add_error(*validate_move_pool_string(_pokemon_name, field_value.replace(', ', '\n')[2:-2]), True)
    return errors, has_error

def validate_ability(_ability):
    # Validates a given ability
    return _ability.upper() in POKEMON_ABILITIES

def validate_move_pool_string(_pokemon_name, _move_pool):
    # Validates a move pool given as a string
    errors = ''
    has_error = False
    def add_error(_error, _is_error = False):
        nonlocal errors, has_error
        if _error:
            has_error = has_error or _is_error
            errors += ('\n' if errors else '') + ('Error: ' if _is_error else 'Warning: ') + _error

    if not _move_pool:
        add_error('{}\'s move pool is empty.'.format(_pokemon_name), True)

    move_lines =_move_pool.split('\n')
    for i in range(len(move_lines)):
        move_line = move_lines[i]
        if not move_line:
            continue
        move_info = move_line.split(':', 1)
        if len(move_info) != 2:
            add_error('{}\'s move #{} is malformed: \'{}\''.format(_pokemon_name, i + 1, move_line), True)
            continue
        move_name = move_info[0].strip()
        if not move_name.upper() in POKEMON_MOVES:
            add_error('{}\'s move #{} \'{}\' is unknown.'.format(_pokemon_name, i + 1, move_name), True)
        move_level = move_info[1].strip()
        try:
            move_level_value = int(move_level)
            move_level_valid = 1 <= move_level_value <= 100
        except Exception:
            move_level_valid = False
        if not move_level_valid:
            add_error('{}\'s move #{}\'s ({}) level \'{}\' is invalid.'.format(_pokemon_name, i + 1, move_name, move_level), True)
    return errors, has_error

####################
## LZ Compression ##
####################

def truncate_lz_compressed_data(_data, _data_size):
    # Given data, truncates it so that the output contains only LZ-compressed data and nothing more
    data_length = len(_data)
    shift = 4
    while True:
        control_byte = int(_data[shift])
        shift += 1
        for i in range(8):
            if shift >= data_length:
                return _data
            is_compressed = control_byte & 0x80
            control_byte <<= 1
            if not is_compressed:
                _data_size -= 1
                shift += 1
            else:
                diff = 3 + (int(_data[shift]) >> 4)
                shift += 2
                _data_size -= diff
            if _data_size <= 0:
                return _data[:shift]

def compress_lz_data(_src:bytes, _min_distance = 2):
    # Performs an LZ compression of the given data
    src_size = len(_src)

    worst_case_dest_size = 4 + src_size + math.ceil((src_size + 7) / 8)
    worst_case_dest_size = ((worst_case_dest_size >> 2) + 1) << 2

    dest = [0 for _ in range(worst_case_dest_size)]
    dest[0] = 0x10
    dest[1] = src_size & 0xFF
    dest[2] = (src_size >> 8) & 0xFF
    dest[3] = (src_size >> 16) & 0xFF

    src_pos = 0
    dest_pos = 4

    while True:
        flags_index = dest_pos
        dest_pos += 1

        for i in range(8):
            best_block_distance = 0
            best_block_size = -3
            block_distance = _min_distance

            # Smaller lookback for better speed and less compression
            while block_distance <= src_pos and block_distance <= 0x40:
                block_start = src_pos - block_distance
                block_size = 0

                while block_size < 18 and src_pos + block_size < src_size and _src[block_start + block_size] == _src[src_pos + block_size]:
                    block_size += 1

                if block_size > best_block_size:
                    best_block_distance = block_distance
                    best_block_size = block_size
                    if block_size == 18:
                        break

                block_distance += 1

            if best_block_size >= 3:
                dest[flags_index] |= 0x80 >> i
                src_pos += best_block_size
                best_block_size -= 3
                best_block_distance -= 1
                dest[dest_pos:dest_pos+2] = [(best_block_size << 4) | ((best_block_distance >> 8) & 0xF), best_block_distance & 0xFF]
                dest_pos += 2
            else:
                dest[dest_pos] = _src[src_pos]
                src_pos += 1
                dest_pos += 1

            if src_pos >= src_size:
                # Pad to multiple of 4 bytes
                dest_pos = ((dest_pos >> 2) + 1) << 2
                return bytes(dest[:dest_pos])

def decompress_lz_data(_src:bytes):
    # Performs an LZ decompression of the given data
    src_size = len(_src)
    if src_size < 4:
        raise Exception('Fatal error while decompressing LZ file: size of file is {}'.format(src_size))

    dest_size = int.from_bytes(bytes(_src[1:4]), 'little')
    dest = [0 for _ in range(dest_size)]

    src_pos = 4
    dest_pos = 0
    compressed_byte_count = 0

    while True:
        if src_pos >= src_size:
            raise Exception('Fatal error while decompressing LZ file: {}/{}'.format(src_pos, src_size))

        # A control byte exists to give info about the 8 following data points
        # Each bit tells whether the next data point is compressed (1) or raw (0) data
        control_byte = int(_src[src_pos])
        src_pos += 1

        for i in range(8):
            if control_byte & 0x80:
                # Compressed data: references data previously added to the output file and the number of repetitions
                if src_pos + 1 >= src_size:
                    raise Exception('Fatal error while decompressing LZ file: {}/{}'.format(src_pos, src_size))

                compressed_byte_count += 1
                block = int.from_bytes(bytes(_src[src_pos:src_pos+2]), 'big')
                block_size = (block >> 12) + 3
                block_distance = (block & 0xFFF) + 1

                src_pos += 2

                block_pos = dest_pos - block_distance
                if dest_pos + block_size > dest_size:
                    block_size = dest_size - dest_pos
                    print('LZ decompression: Destination buffer overflow.')

                if block_pos < 0:
                    raise Exception('Fatal error while decompressing LZ file: Distance is {} ({} - {}).'.format(block_pos, dest_pos, block_distance))

                for j in range(block_size):
                    dest[dest_pos] = dest[block_pos + j]
                    dest_pos += 1
            else:
                # Raw data: copies the byte as-is to the output
                if src_pos >= src_size or dest_pos >= dest_size:
                    raise Exception('Fatal error while decompressing LZ file: {}/{} and {}/{}.'.format(src_pos, src_size, dest_pos, dest_size))
                dest[dest_pos] = _src[src_pos]
                dest_pos += 1
                src_pos += 1

            if dest_pos == dest_size:
                return bytes(dest)

            control_byte <<= 1

###########################
## Sprite Transformation ##
###########################

def compress_sprite(_src, _bits_per_pixel):
    # Returns sprite data with each pixel taking as little space as possible
    # Useful for turning Pillow sprite data into GBA sprite data
    if _bits_per_pixel == 8:
        return _src

    pixels_per_bytes = round(8 / _bits_per_pixel)
    dest = []
    for src_bytes in [_src[i:i+pixels_per_bytes] for i in range(0, len(_src), pixels_per_bytes)]:
        dest_byte = 0
        bits = 0
        for src_byte in src_bytes:
            dest_byte |= src_byte << bits
            bits += _bits_per_pixel
        dest.append(dest_byte)
    return bytes(dest)

def decompress_sprite(_src, _bits_per_pixel):
    # Returns sprite data with each pixel taking one full byte of space
    # Useful for turning GBA sprite data into Pillow sprite data
    if _bits_per_pixel == 8:
        return _src

    pixels_per_bytes = round(8 / _bits_per_pixel)
    data_per_pixel = int(math.pow(2, _bits_per_pixel)) - 1

    dest = []
    for byte in _src:
        for _ in range(pixels_per_bytes):
            pixel = byte & data_per_pixel
            byte >>= _bits_per_pixel
            dest.append(pixel)
    return bytes(dest)

def chunk_sprite(_src, _width, _height):
    # Sprites stored in ROMs are bundled in 8x8 pixel chunks
    # This function applies this behavior, turning simple sprites into chunked pixel data
    # Only allows for sprites having both dimensions as a multiple of 8 for speed's sake
    if _width % 8 or _height % 8:
        raise Exception('Sprites must have both of their dimensions as multiples of 8 to be chunkable!')

    src_size = _width * _height
    dest = [0 for _ in range(src_size)]

    blocks_per_line = math.ceil(_width / 8)
    block_x_shift = 64
    block_y_shift = block_x_shift * blocks_per_line
    src_shift = 0
    while src_shift < src_size:
        block_x = math.floor((src_shift % _width) / 8)
        temp_src_shift = math.floor(src_shift / _width)
        y = temp_src_shift % 8
        block_y = math.floor(temp_src_shift / 8)
        dest_pos = (block_y * block_y_shift) + (block_x * block_x_shift) + (y * 8)
        dest[dest_pos:dest_pos+8] = [int(byte) for byte in _src[src_shift:src_shift+8]]
        src_shift += 8
    return bytes(dest)

def dechunk_sprite(_src, _width, _height):
    # Sprites stored in ROMs are bundled in 8x8 pixel chunks
    # This function reverts this behavior, returning raw, non-chunked pixel data
    # Only allows for sprites having both dimensions as a multiple of 8 for speed's sake
    if _width % 8 or _height % 8:
        raise Exception('Sprites must have both of their dimensions as multiples of 8 to be chunkable!')

    src_size = _width * _height
    dest = [0 for _ in range(src_size)]

    src_shift = 0
    block_x = 0
    block_y = 0
    while src_shift < src_size:
        for y in range(min(_height - (block_y * 8), 8)):
            dest_pos = (block_y * 8 + y) * _width + block_x * 8
            dest[dest_pos:dest_pos+8] = [int(byte) for byte in _src[src_shift:src_shift+8]]
            src_shift += 8
        block_x += 1
        if block_x * 8 >= _width:
            block_x = 0
            block_y += 1
    return bytes(dest)

def spread_palettes_to_sprite_frames(_src, _width, _height, _frames):
    # Adds values to the pixels in the sheet to match values in an extended palette
    # Assumes all palettes have exactly 16 colors
    _src = bytearray(_src)
    src_size = _width * _height
    data_size_per_frame = round(src_size / _frames)
    for frame in range(1, _frames):
        shift = frame * data_size_per_frame
        for pixel in range(data_size_per_frame):
            _src[shift + pixel] |= frame << 4
    return bytes(_src)

###############################
## Pokemon Data Manipulation ##
###############################

def get_pokemon_data(_pokemon_name, _data_type = None):
    # Gets a given field or all data from a given pokemon
    if _pokemon_name.startswith('Unown '):
        _pokemon_name = 'Unown A'
    data_container_name = 'move_pool' if _data_type == 'move_pool' else 'stats'
    data_key = 'pokemon_' + data_container_name
    data_address, _ = get_address_from_address_collection(_pokemon_name, data_key, data_container_name)
    if _data_type == 'move_pool':
        # Move pools are given as pointers, so seek their value
        data_address = int.from_bytes(bytes(current_rom[data_address:data_address+3]), 'little')
    end_address = data_address + (100 if _data_type == 'move_pool' else 28)
    data = current_rom[data_address:end_address]
    if _data_type == 'move_pool':
        return decode_move_pool(data)
    if not _data_type:
        return get_all_pokemon_data(_pokemon_name, data)
    return data[_data_type]

def get_all_pokemon_data(_pokemon_name, _data):
    # Gets all the data from a given pokemon
    if _pokemon_name.startswith('Unown '):
        _pokemon_name = 'Unown A'
    result = {}
    for field in POKEMON_DATA_INFO:
        field_info = POKEMON_DATA_INFO[field]
        data_address = field_info['shift']
        end_address = data_address + field_info['size']
        result[field] = int.from_bytes(bytes(_data[data_address:end_address]), 'little')
    result['move_pool'] = get_pokemon_data(_pokemon_name, 'move_pool')
    return result

def encode_pokemon_data(_data: dict[str,int]):
    # Encodes pokemon data into data to add to the ROM
    output = bytearray(28)
    for field_name in _data:
        if field_name == 'move_pool':
            continue
        shift = POKEMON_DATA_INFO[field_name]['shift']
        size = POKEMON_DATA_INFO[field_name]['size']
        output[shift:shift+size] = _data[field_name].to_bytes(size, 'little')
    return bytes(output)

def stringify_pokemon_data(_data):
    # Transforms a pokemon's data into a string
    result = ''
    for field_name in _data:
        field_value = _data[field_name]
        if field_name in [ 'type1', 'type2' ]:
            field_value = POKEMON_TYPES[field_value]
        elif field_name in [ 'ability1', 'ability2' ]:
            field_value = POKEMON_ABILITIES[field_value].title()
        elif field_name == 'gender_ratio':
            field_value = POKEMON_GENDER_RATIOS[field_value]
        elif field_name == 'dex':
            # The dex value is stored as a boolean named 'forbid_flip' for clarity
            field_value = 'True' if field_value & 0x80 else 'False'
            field_name = 'forbid_flip'
        elif field_name == 'move_pool':
            field_value = '[ ' + stringify_move_pool(field_value).replace('\n', ', ') + ' ]'
        result += '{}: {}\n'.format(field_name, field_value)
    return result[:-1]

def destringify_pokemon_data(_pokemon_name, _data_string, _safe_mode = False):
    # Transforms a pokemon's data given as a string into a dictionary holding said pokemon's data
    if _pokemon_name.startswith('Unown '):
        _pokemon_name = 'Unown A'
    result = {}
    for field_line in _data_string.split('\n'):
        field_info = field_line.split(':', 1)
        field_name = field_info[0].strip()
        field_value = field_info[1].strip()
        if field_name in [ 'hp', 'atk', 'def', 'spatk', 'spdef', 'spd' ]:
            field_value = field_value if _safe_mode else int(field_value)
        elif field_name in [ 'type1', 'type2' ]:
            field_value = field_value if _safe_mode else POKEMON_TYPES.index(field_value)
        elif field_name in [ 'ability1', 'ability2' ]:
            field_value = field_value if _safe_mode else POKEMON_ABILITIES.index(field_value.upper())
        elif field_name == 'gender_ratio':
            field_value = field_value if _safe_mode else REVERSE_POKEMON_GENDER_RATIOS[field_value]
        elif field_name in [ 'dex', 'forbid_flip' ]:
            # The dex value is stored as a boolean named 'forbid_flip' for clarity
            field_value = field_value if _safe_mode else (1 if field_value in [ 1, '1', 'True' ] else 0)
            field_name = 'dex'
        elif field_name == 'move_pool':
            if not _safe_mode:
                move_pool_errors, has_move_pool_error = validate_move_pool_string(_pokemon_name, field_value[2:-2].replace(', ', '\n'))
                if has_move_pool_error:
                    raise Exception('Bad move pool: {}'.format(move_pool_errors))
                field_value = destringify_move_pool(field_value[2:-2].replace(', ', '\n'))
        result[field_name] = field_value
    return result

def merge_pokemon_data(_old_data, _new_data, _is_dex_simple = False):
    # Merges two pokemon data objects
    merged_data = _old_data
    for field_name in _new_data:
        if _is_dex_simple and field_name == 'dex':
            merged_data[field_name] = (_new_data[field_name] << 7) + (_old_data[field_name] & 0x7F)
        else:
            merged_data[field_name] = _new_data[field_name]
    return merged_data

def keep_different_pokemon_data(_old_data, _new_data):
    # Returns only different fields between the two pokemon data objects given
    different_data = { k: v for k, v in _new_data.items() if not k in list(_old_data.keys()) or (v != _old_data[k] and k != 'move_pool') }
    if 'move_pool' in list(_new_data.keys()) and 'move_pool' in list(_old_data.keys()) and not are_move_pools_equal(_new_data['move_pool'], _old_data['move_pool']):
        different_data['move_pool'] = _new_data['move_pool']
    return different_data

def stringify_move_pool(_move_pool):
    # Transforms a pokemon's move pool a string
    result = ''
    for move_info in _move_pool:
        result += '{}: {}\n'.format(move_info['move'], move_info['level'])
    return result[:-1]

def destringify_move_pool(_move_pool_string):
    # Transforms a pokemon's move pool given as a string into a list of dictionaries holding said move pool data
    result = []
    for move_line in _move_pool_string.split('\n'):
        if not move_line:
            continue
        move_info = move_line.split(':', 1)
        move_name = move_info[0].strip()
        move_level = int(move_info[1].strip())
        result.append({ 'move': move_name, 'level': move_level })
    return result

def decode_move_pool(_data):
    # Decodes move pool data from a list of bytes into a list of moves
    result = []
    data_size = round(len(_data) / 2)
    for i in range(data_size):
        move_data = int.from_bytes(bytes(_data[i*2:(i+1)*2]), 'little')
        if move_data == 0xFFFF:
            break
        move_id = move_data & 0x1FF
        move_level = move_data >> 9
        result.append({ 'move': POKEMON_MOVES[move_id - 1].title(), 'level': move_level })
    return result

def encode_move_pool(_move_pool):
    # Encodes move pool data from a list of moves into a list of bytes
    result = bytearray()
    for move_data in _move_pool:
        move_id = POKEMON_MOVES.index(move_data['move'].upper()) + 1
        move_level = move_data['level']
        move_data = (move_level << 9) + move_id
        result += move_data.to_bytes(2, 'little')
    # Surround the table by FFFF as the move pool functions looks for the beginning and end of the table
    return bytes(result + b'\xff\xff')

def are_move_pools_equal(_move_pool_1, _move_pool_2):
    # Compares two move pool objects
    if len(_move_pool_1) != len(_move_pool_2):
        return False
    for i in range(len(_move_pool_1)):
        move_data_1 = _move_pool_1[i]
        move_data_2 = _move_pool_2[i]
        if move_data_1['move'] != move_data_2['move'] or move_data_1['level'] != move_data_2['level']:
            return False
    return True

#######################
## Utility Functions ##
#######################

def get_bits_per_pixel_from_palette_size(_palette_size):
    # Returns how many bits are needed to store a pixel for a palette of a given size
    if _palette_size <= 2:   return 1
    if _palette_size <= 16:  return 4
    if _palette_size <= 256: return 8
    raise Exception('A sprite with a palette with more than 256 colors cannot be handled by the ROM.')

def get_address_from_address_collection(_object_name, _resource_key, _resource_name):
    # Returns a known address from the ROM's address collection
    if _resource_key.startswith('pokemon_'):
        # Fetches internal Pokemon ID then resource address
        pokemon_id = POKEMON_NAME_TO_ID[_object_name]
        pokemon_internal_id = POKEMON_ID_TO_INTERNAL_ID.get(pokemon_id, pokemon_id)
        result = INTERNAL_ID_TO_OBJECT_ADDRESS[_resource_key](data_addresses, pokemon_internal_id)
    else:
        # Fetches named Trainer resource address
        named_key = _object_name.lower() + '_' + _resource_name
        result = INTERNAL_ID_TO_OBJECT_ADDRESS[named_key](data_addresses)

    if type(result) is int:
        return result, False
    return result

def get_overworld_sprite_addresses(_object_name, _resource_name):
    named_key = _object_name.lower() + '_' + _resource_name
    return OVERWORLD_SPRITE_ADDRESSES[named_key](data_addresses)

def handle_overworld_custom_size(_extra_data):
    # Checks if the custom size passed for a given overworld sprite sheet is valid
    sizes = _extra_data[0].split('x')
    if len(sizes) != 2:
        raise Exception('An overworld sprite\'s custom size must be in the format <width>x<height>, with <width> and <height> as numbers.')
    sprite_width = int(sizes[0])
    sprite_height = int(sizes[1])
    valid_sprite_size = next(filter(lambda f: f['width'] == sprite_width and f['height'] == sprite_height, VALID_OVERWORLD_SPRITE_SIZES), None)
    if not valid_sprite_size:
        raise Exception('Overworld sprites cannot have a custom size of {}x{}'.format(sizes[0], sizes[1]))
    return valid_sprite_size

def get_overworld_sprite_data(_data_address, _key):
    # Returns the value of given data from an overworld sprite data object
    value_data = OVERWORLD_SPRITE_OBJECT_INFO.get(_key, None)
    if not value_data:
        raise Exception('Could not get the value {} from an overworld sprite\'s data.'.format(_key))
    starting_address = _data_address + value_data.get('shift')
    end_address = starting_address + value_data.get('size')
    return int.from_bytes(bytes(current_rom[starting_address:end_address]), 'little')

def set_overworld_sprite_data(_data_address, _key, _value:int):
    # Sets the value of given data from an overworld sprite data object
    value_data = OVERWORLD_SPRITE_OBJECT_INFO.get(_key, None)
    if not value_data:
        raise Exception('Could not set the value {} from an overworld sprite\'s data.'.format(_key))
    starting_address = _data_address + value_data.get('shift')
    size = value_data.get('size')
    add_data_to_patch({ 'address': starting_address, 'length': size, 'data': _value.to_bytes(size, 'little')})

def get_sprite_requirements(_sprite_key, _object_name):
    # Returns the requirements of a given sprite for a given pokemon or trainer
    if _object_name.startswith('Unown '):
        _object_name = 'Unown A'

    sprite_name = _sprite_key[8:]
    reference_sprite_name = SPRITE_PIXEL_REFERENCE.get(sprite_name, sprite_name)
    reference_sprite_key = _sprite_key[:8] + reference_sprite_name
    _sprite_key = _sprite_key[:8] + sprite_name

    reqs = SPRITES_REQUIREMENTS.get(_sprite_key, {})
    reference_reqs = SPRITES_REQUIREMENTS.get(reference_sprite_key, {})
    reqs_exceptions_list = SPRITES_REQUIREMENTS_EXCEPTIONS.get(_object_name, {})
    reqs_exceptions = reqs_exceptions_list.get(_sprite_key, {})
    reference_reqs_exceptions = reqs_exceptions_list.get(reference_sprite_key, {})
    return reference_reqs | reference_reqs_exceptions | reqs | reqs_exceptions

def is_complex_sprite(_sprite_key):
    # Checks if a sprite is a complex sprite
    return _sprite_key in COMPLEX_SPRITES_LIST

def is_overworld_sprite(_sprite_key:str):
    # Checks if a sprite is an overworld sprite
    return _sprite_key.startswith('trainer_') and not 'battle' in _sprite_key

def handle_address_collection(_rom, _forced_is_ap = None):
    # Picks and stores the right address collection for the given ROM
    is_ap = _forced_is_ap if _forced_is_ap != None else zlib.crc32(_rom) != ORIGINAL_EMERALD_CRC32

    global data_addresses
    if is_ap:
        data_addresses = DATA_ADDRESSES_MOCK_AP
    else:
        data_addresses = DATA_ADDRESSES_ORIGINAL

    global current_rom
    current_rom = _rom
    return is_ap

def five_to_eight_bits_palette(value):
    # Transforms a 5-bit long palette color into an 8-bit long palette color
    return (value << 3) + math.floor(value / 31 * 7)

def eight_to_five_bits_palette(value):
    # Transforms a 8-bit long palette color into an 5-bit long palette color
    return value >> 3

def flatten_2d(input_list):
   # Flattens a list containing lists into a single unidimensional list
   result = []
   for sublist in input_list:
      for item in sublist:
        result.append(item)
   return result