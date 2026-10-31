# 1 export AllAssets.ora
# sudo apt update && sudo apt install -y python3-full python3-venv
# python3 -m venv venv
# 2 source venv/bin/activate
# 3 python3 GenerateAtlas.py

import io
import os
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
  atlas_layers = []
  standalone_images = []

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

        # 1. Replace 'Terrains' with 'Tiles' in the layer name
        name = name.replace('Terrains', 'Tiles')

        try:
          # Extract the layer's PNG data directly from the zip archive
          img_data = z.read(src)
          img = Image.open(io.BytesIO(img_data)).convert('RGBA')

          layer_obj = {'name': name, 'img': img}

          # 2. Add 'Images/' layers to BOTH standalone_images and atlas_layers
          if name == 'Images' or name.startswith('Images/') or name == "preview":
            standalone_images.append(layer_obj)
            atlas_layers.append(layer_obj)
          else:
            atlas_layers.append(layer_obj)

        except Exception as e:
          print(f"Warning: Could not load layer '{name}' from '{src}': {e}")

  # Save standalone file using exact layer name path
  if standalone_images:
      print(f"Exporting {len(standalone_images)} standalone image(s)...")
      for item in standalone_images:
          # Keep original name for standalone disk file path
          out_filepath = f"{item['name']}.png"
          dirname = os.path.dirname(out_filepath)
          if dirname:
              os.makedirs(dirname, exist_ok=True)
          item['img'].save(out_filepath, 'PNG')
          print(f"  Saved: {out_filepath}")

  if not atlas_layers:
    print('No layers found for atlas packing.')
    return

  print(f'Found {len(atlas_layers)} layer(s) for atlas. Packing...')

  # Sort layers by height descending for optimal shelf packing
  atlas_layers.sort(key=lambda x: x['img'].height, reverse=True)

  max_width = 2048
  padding = 2
  current_x = padding
  current_y = padding
  row_height = 0
  atlas_height = 0

  packed_items = []

  for item in atlas_layers:
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

  # Create the final atlas sprite sheet image
  atlas_img = Image.new('RGBA', (atlas_width, atlas_height), (0, 0, 0, 0))

  for item in packed_items:
    atlas_img.paste(item['img'], (item['atlas_x'], item['atlas_y']))

  # Save output PNG
  atlas_img.save(output_image, 'PNG')
  print(f'Saved atlas image to {output_image}')

  # Generate the .atlas text file content matching LibGDX specifications
  atlas_content = []
  atlas_content.append(output_image)
  atlas_content.append(f'size: {atlas_width}, {atlas_height}')
  atlas_content.append('format: RGBA8888')
  atlas_content.append('filter: MipMapLinearLinear, MipMapLinearLinear')
  atlas_content.append('repeat: none')

  for item in packed_items:
    w, h = item['img'].size
    
    atlas_entry_name = item['name']
    if atlas_entry_name.startswith('Images/'):
        atlas_entry_name = atlas_entry_name[len('Images/'):]

    # Helper function to append entry block
    def append_atlas_entry(entry_name):
      atlas_content.append(entry_name)
      atlas_content.append('  rotate: false')
      atlas_content.append(f"  xy: {item['atlas_x']}, {item['atlas_y']}")
      atlas_content.append(f'  size: {w}, {h}')
      atlas_content.append(f'  orig: {w}, {h}')
      atlas_content.append('  offset: 0, 0')
      atlas_content.append('  index: -1')

    # 1. Primary atlas entry
    append_atlas_entry(atlas_entry_name)

    # 2. Secondary atlas entry for Improvements (doubles as its own icon)
    if 'Improvements/' in atlas_entry_name:
        secondary_icon_name = atlas_entry_name.replace('Improvements/', 'ImprovementIcons/', 1)
        append_atlas_entry(secondary_icon_name)


  with open(output_atlas, 'w', encoding='utf-8') as f:
    f.write('\n'.join(atlas_content))

  print(f'Saved atlas descriptor to {output_atlas}')
  print('Done!')


if __name__ == '__main__':
  pack_ora_to_atlas()