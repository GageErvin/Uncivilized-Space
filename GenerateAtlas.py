# 1 export AllAssets.ora
# sudo apt update && sudo apt install -y python3-full python3-venv
# python3 -m venv venv
# 2 source venv/bin/activate
# 3 python3 GenerateAtlas.py

import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image


def get_representative_rgb(img: Image.Image) -> list[int]:
  """Computes the alpha-weighted average [R, G, B] of non-transparent pixels."""
  rgba = img.convert('RGBA')
  r_sum = g_sum = b_sum = alpha_sum = 0

  for r, g, b, a in rgba.getdata():
    # Ignore fully or mostly transparent pixels (anti-aliased edges/background)
    if a > 16:
      r_sum += r * a
      g_sum += g * a
      b_sum += b * a
      alpha_sum += a

  if alpha_sum == 0:
    return [128, 128, 128]

  return [
      round(r_sum / alpha_sum),
      round(g_sum / alpha_sum),
      round(b_sum / alpha_sum),
  ]


def normalize_key(name: str) -> str:
  """Normalizes asset/JSON names so 'Trading-Post' matches 'Trading Post'."""
  # Strip file extensions if any, lowercase, and unify separators
  base = os.path.splitext(os.path.basename(name))[0]
  return re.sub(r'[-_\s]+', ' ', base).strip().lower()


def load_relaxed_json(filepath: str):
  """Loads standard JSON as well as Unciv JSON containing //, /* */ comments or trailing commas."""
  with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

  # Remove /* ... */ and // ... comments while preserving strings
  pattern = re.compile(
      r'("(?:\\.|[^"\\])*")|(/\*[\s\S]*?\*/|//[^\r\n]*)',
      re.MULTILINE,
  )
  cleaned = pattern.sub(
      lambda m: m.group(1) if m.group(1) is not None else '', text
  )
  # Remove trailing commas before closing ] or }
  cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
  return json.loads(cleaned)


def update_json_rgb_values(
    jsons_dir: str,
    terrain_colors: dict[str, list[int]],
    improvement_colors: dict[str, list[int]],
):
  """Scans ./jsons for terrain and tile improvement definitions and updates their RGB field."""
  if not os.path.isdir(jsons_dir):
    print(f"Note: Directory '{jsons_dir}' not found. Skipping JSON RGB updates.")
    return

  if not terrain_colors and not improvement_colors:
    print('No terrain or improvement colors extracted to update in JSONs.')
    return

  print(f"Scanning '{jsons_dir}' to update Terrain and Tile Improvement RGB values...")

  for root_dir, _, files in os.walk(jsons_dir):
    for filename in files:
      if not filename.lower().endswith('.json'):
        continue

      filepath = os.path.join(root_dir, filename)
      lower_name = filename.lower()

      # Determine which color dictionary applies based on filename or structure
      is_terrain_file = 'terrain' in lower_name
      is_improvement_file = 'improvement' in lower_name

      try:
        data = load_relaxed_json(filepath)
      except Exception as e:
        print(f"  Warning: Could not parse '{filepath}': {e}")
        continue

      # Unciv terrain/improvement JSONs are top-level lists of dicts
      if not isinstance(data, list):
        continue

      modified = False
      updated_names = []

      for entry in data:
        if not isinstance(entry, dict) or 'name' not in entry:
          continue

        norm_entry_name = normalize_key(entry['name'])
        matched_rgb = None

        # Check specific file category first, otherwise check both
        if is_terrain_file and norm_entry_name in terrain_colors:
          matched_rgb = terrain_colors[norm_entry_name]
        elif is_improvement_file and norm_entry_name in improvement_colors:
          matched_rgb = improvement_colors[norm_entry_name]
        elif not is_terrain_file and not is_improvement_file:
          if norm_entry_name in terrain_colors:
            matched_rgb = terrain_colors[norm_entry_name]
          elif norm_entry_name in improvement_colors:
            matched_rgb = improvement_colors[norm_entry_name]

        if matched_rgb is not None:
          if entry.get('RGB') != matched_rgb:
            entry['RGB'] = matched_rgb
            modified = True
            updated_names.append(f"{entry['name']} -> {matched_rgb}")

      if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
          json.dump(data, f, indent='  ', ensure_ascii=False)
          f.write('\n')
        print(f'  Updated {filepath}:')
        for item_log in updated_names:
          print(f'    - {item_log}')


def pack_ora_to_atlas(
    ora_path='AllAssets.ora',
    output_image='game.png',
    output_atlas='game.atlas',
    jsons_dir='./jsons',
):
  if not os.path.exists(ora_path):
    print(f"Error: '{ora_path}' not found in the current directory.")
    print('Please export your GIMP project as an OpenRaster (.ora) file first.')
    return

  print(f"Reading layers from '{ora_path}'...")
  layers_meta = []
  terrain_colors: dict[str, list[int]] = {}
  improvement_colors: dict[str, list[int]] = {}

  # OpenRaster (.ora) files are ZIP archives containing stack.xml and layer images
  with zipfile.ZipFile(ora_path, 'r') as z:
    if 'stack.xml' not in z.namelist():
      print("Error: Invalid OpenRaster file (missing 'stack.xml').")
      return

    # Parse stack.xml to extract layers, names, and properties
    xml_content = z.read('stack.xml')
    root = ET.fromstring(xml_content)

    # Iterate through all layer elements in the XML tree (ignoring namespace prefixes)
    for elem in root.iter():
      if elem.tag.endswith('layer'):
        name = elem.attrib.get('name')
        src = elem.attrib.get('src')
        visibility = elem.attrib.get('visibility', 'visible')

        # Skip hidden layers
        if visibility.lower() == 'hidden':
          continue

        if not name or not src:
          continue

        # Skip helper background layers if present
        if name.lower().startswith('background'):
          continue

        try:
          # Extract the layer's PNG data directly from the zip archive
          img_data = z.read(src)
          img = Image.open(io.BytesIO(img_data)).convert('RGBA')

          # Default metadata state
          standalone_name = name
          atlas_names = [name]
          save_standalone = False
          fallback_icon = None

          # Normalize path without leading 'Images/' for accurate category matching
          norm_layer = (
              name[len('Images/') :] if name.startswith('Images/') else name
          )

          # 1. Process Terrains -> Map to Tiles/ with standard crop and standalone export
          if re.search(r'(?:^|/)[Tt]errains/', norm_layer):
            clean_name = re.sub(r'[Tt]errains/', 'Tiles/', name)
            offset_w, offset_h = 4, 4
            crop_w, crop_h = 64, 56
            img = img.crop(
                (offset_w, offset_h, offset_w + crop_w, offset_h + crop_h)
            )
            standalone_name = clean_name
            atlas_names = [clean_name]
            save_standalone = True

            asset_name = re.split(
                r'(?:^|/)[Tt]errains/', norm_layer, maxsplit=1
            )[-1]
            fallback_icon = f'TerrainIcons/{asset_name}'
            terrain_colors[normalize_key(asset_name)] = get_representative_rgb(
                img
            )

          # 2. Process Improvements -> Map to Tiles/ and prepare ImprovementIcons/ fallback
          elif re.search(r'(?:^|/)[Ii]mprovements/', norm_layer):
            clean_name = re.sub(r'[Ii]mprovements/', 'Tiles/', name)
            standalone_name = clean_name
            atlas_names = [clean_name]
            save_standalone = True

            asset_name = re.split(
                r'(?:^|/)[Ii]mprovements/', norm_layer, maxsplit=1
            )[-1]
            fallback_icon = f'ImprovementIcons/{asset_name}'
            improvement_colors[normalize_key(asset_name)] = (
                get_representative_rgb(img)
            )

          # 3. Process Resources -> Map to Tiles/ (if applicable) and prepare ResourceIcons/ fallback
          elif re.search(r'(?:^|/)(?:[Tt]ile)?[Rr]esources/', norm_layer):
            clean_name = re.sub(r'(?:[Tt]ile)?[Rr]esources/', 'Tiles/', name)
            standalone_name = clean_name
            atlas_names = [clean_name]
            save_standalone = True

            asset_name = re.split(
                r'(?:^|/)(?:[Tt]ile)?[Rr]esources/', norm_layer, maxsplit=1
            )[-1]
            fallback_icon = f'ResourceIcons/{asset_name}'

          # 4. Process Units -> Standalone export enabled and prepare UnitIcons/ fallback
          elif re.search(r'(?:^|/)[Uu]nits/', norm_layer):
            standalone_name = name
            atlas_names = [name]
            save_standalone = True

            asset_name = re.split(r'(?:^|/)[Uu]nits/', norm_layer, maxsplit=1)[
                -1
            ]
            fallback_icon = f'UnitIcons/{asset_name}'

          # 5. Process other standalone Images/ or preview
          elif (
              name == 'Images'
              or name.startswith('Images/')
              or name == 'preview'
          ):
            standalone_name = name
            atlas_names = [name]
            save_standalone = True

          # Build structured metadata object for this layer
          layer_obj = {
              'original_name': name,
              'img': img,
              'standalone_name': standalone_name,
              'atlas_names': atlas_names,
              'save_standalone': save_standalone,
              'fallback_icon': fallback_icon,
          }
          layers_meta.append(layer_obj)

        except Exception as e:
          print(f"Warning: Could not load layer '{name}' from '{src}': {e}")

  if not layers_meta:
    print('No layers found for processing.')
    return

  # Step 1: Normalize and collect all existing entry names across layers to check for custom icons
  existing_entries = set()
  for item in layers_meta:
    for aname in item['atlas_names']:
      norm = aname[len('Images/') :] if aname.startswith('Images/') else aname
      existing_entries.add(norm)

  # Step 2: Automatically attach fallback icon entries if dedicated ones don't already exist
  for item in layers_meta:
    fallback_icon = item['fallback_icon']
    if fallback_icon and fallback_icon not in existing_entries:
      item['atlas_names'].append(fallback_icon)
      existing_entries.add(fallback_icon)

  # Step 3: Save standalone files using clean filenames (free of postfixes)
  standalone_items = [item for item in layers_meta if item['save_standalone']]
  if standalone_items:
    print(f'Exporting {len(standalone_items)} standalone image(s)...')
    for item in standalone_items:
      out_filepath = f"{item['standalone_name']}.png"
      dirname = os.path.dirname(out_filepath)
      if dirname:
        os.makedirs(dirname, exist_ok=True)
      item['img'].save(out_filepath, 'PNG')
      print(f'  Saved: {out_filepath}')

  # Step 4: Sort layers by height descending for optimal shelf packing in the atlas
  layers_meta.sort(key=lambda x: x['img'].height, reverse=True)

  max_width = 2048
  padding = 2
  current_x = padding
  current_y = padding
  row_height = 0
  atlas_height = 0

  packed_items = []

  for item in layers_meta:
    w, h = item['img'].size

    # Wrap to next row if image exceeds max width
    if current_x + w + padding > max_width:
      current_x = padding
      current_y += row_height + padding
      row_height = 0

    item['atlas_x'] = current_x
    item['atlas_y'] = current_y
    packed_items.append(item)

    current_x += w + padding
    if h > row_height:
      row_height = h

    needed_height = current_y + row_height + padding
    if needed_height > atlas_height:
      atlas_height = needed_height

  atlas_width = max_width
  print(f'Atlas dimensions: {atlas_width}x{atlas_height}')

  # Create final atlas sprite sheet image
  atlas_img = Image.new('RGBA', (atlas_width, atlas_height), (0, 0, 0, 0))

  for item in packed_items:
    atlas_img.paste(item['img'], (item['atlas_x'], item['atlas_y']))

  # Save output PNG atlas sheet
  atlas_img.save(output_image, 'PNG')
  print(f'Saved atlas image to {output_image}')

  # Step 5: Generate LibGDX .atlas descriptor content
  atlas_content = []
  atlas_content.append(output_image)
  atlas_content.append(f'size: {atlas_width}, {atlas_height}')
  atlas_content.append('format: RGBA8888')
  atlas_content.append('filter: MipMapLinearLinear, MipMapLinearLinear')
  atlas_content.append('repeat: none')

  for item in packed_items:
    w, h = item['img'].size
    # Register all atlas names associated with this item using its packed coordinates
    for entry_name in item['atlas_names']:
      if entry_name.startswith('Images/'):
        entry_name = entry_name[len('Images/') :]

      atlas_content.append(entry_name)
      atlas_content.append('  rotate: false')
      atlas_content.append(f"  xy: {item['atlas_x']}, {item['atlas_y']}")
      atlas_content.append(f'  size: {w}, {h}')
      atlas_content.append(f'  orig: {w}, {h}')
      atlas_content.append('  offset: 0, 0')
      atlas_content.append('  index: -1')

  with open(output_atlas, 'w', encoding='utf-8') as f:
    f.write('\n'.join(atlas_content))

  print(f'Saved atlas descriptor to {output_atlas}')

  # Step 6: Update RGB values in ./jsons for Terrains and Tile Improvements
  update_json_rgb_values(jsons_dir, terrain_colors, improvement_colors)

  print('Done!')


if __name__ == '__main__':
  pack_ora_to_atlas()