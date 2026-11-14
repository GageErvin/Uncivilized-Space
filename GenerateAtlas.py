# 1 export AllAssets.ora
# sudo apt update && sudo apt install -y python3-full python3-venv
# python3 -m venv venv
# 2 source venv/bin/activate
# 3 python3 GenerateAtlas.py


import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image


def pack_ora_to_atlas(
    ora_path='AllAssets.ora',
    output_image='game.png',
    output_atlas='game.atlas',
):
  if not os.path.exists(ora_path):
    print(f"Error: '{ora_path}' not found in the current directory.")
    print('Please export your GIMP project as an OpenRaster (.ora) file first.')
    return

  print(f"Reading layers from '{ora_path}'...")
  layers_meta = []

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
          is_improvement = False
          is_unit = False

          # 1. Process Terrains -> Map to Tiles/ with standard crop and standalone export
          if bool(re.search(r'[Tt]errains/', name)):
            clean_name = re.sub(r'[Tt]errains/', 'Tiles/', name)
            offset_w, offset_h = 4, 4
            crop_w, crop_h = 64, 56
            img = img.crop(
                (offset_w, offset_h, offset_w + crop_w, offset_h + crop_h)
            )
            standalone_name = clean_name
            atlas_names = [clean_name]
            save_standalone = True

          # 2. Process Improvements -> Map to Tiles/ (clean standalone name without 'T', but 'T' in atlas)
          elif bool(re.search(r'[Ii]mprovements/', name)):
            clean_name = re.sub(r'[Ii]mprovements/', 'Tiles/', name)
            standalone_name = clean_name
            atlas_names = [clean_name]
            save_standalone = True
            is_improvement = True

          # 3. Process Units -> Standalone export enabled
          elif bool(re.search(r'[Uu]nits/', name)):
            standalone_name = name
            atlas_names = [name]
            save_standalone = True
            is_unit = True

          # 4. Process standalone Images/ or preview
          elif name == 'Images' or name.startswith('Images/') or name == 'preview':
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
              'is_improvement': is_improvement,
              'is_unit': is_unit,
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
      norm = aname[len('Images/')] if aname.startswith('Images/') else aname
      existing_entries.add(norm)

  # Step 2: Automatically attach fallback icon entries if dedicated ones don't already exist
  for item in layers_meta:
    primary_name = item['atlas_names'][0]
    norm_primary = (
        primary_name[len('Images/')]
        if primary_name.startswith('Images/')
        else primary_name
    )

    if item['is_improvement']:
      fallback_icon = re.sub(
          r'^(?:.*?/)?[Tt]iles/', 'ImprovementIcons/', norm_primary
      )
      if fallback_icon not in existing_entries:
        item['atlas_names'].append(fallback_icon)
        existing_entries.add(fallback_icon)

    elif item['is_unit']:
      fallback_icon = re.sub(
          r'^(?:.*?/)?[Uu]nits/', 'UnitIcons/', norm_primary
      )
      if fallback_icon not in existing_entries:
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
  print('Done!')


if __name__ == '__main__':
  pack_ora_to_atlas()