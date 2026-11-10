import os
import re
import json
from pathlib import Path

def strip_c_style_comments(text):
    # Strip multi-line comments /* ... */
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Strip single-line comments // ...
    text = re.sub(r'//.*', '', text)
    return text

def main():
    output_filename = "out.md"
    # Add any filenames you want to skip here
    skip_list = {"CityStateTypes.json", "Events.json", "GlobalUniques.json", "ModOptions.json", "Quests.json", "Ruins.json", "TileResources.json", "VictoryTypes.json"}
    json_dir = Path("jsons")

    # Clear or initialize the output file
    with open(output_filename, "w", encoding="utf-8") as out_f:
        pass

    if not json_dir.exists():
        print(f"Directory '{json_dir}' does not exist.")
        return

    # Loop through all JSON files in the directory
    for file_path in sorted(json_dir.glob("*.json")):
        filename = file_path.name

        # Skip if matches output file or skip list
        if filename == output_filename or filename in skip_list:
            continue

        try:
            # Read file content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Strip C-style comments
            clean_content = strip_c_style_comments(content)

            # Parse JSON and dump it compactly on a single line
            data = json.loads(clean_content)
            compact_json = json.dumps(data, separators=(",", ":"))

            # Append to out.md
            with open(output_filename, "a", encoding="utf-8") as out_f:
                out_f.write(f"# {file_path}\n")
                out_f.write("```json\n")
                out_f.write(f"{compact_json}\n")
                out_f.write("```\n\n")
                
            print(f"Processed: {filename}")

        except Exception as e:
            print(f"Error processing {filename}: {e}")

if __name__ == "__main__":
    main()