import json
import re
from pathlib import Path

JSON_DIR = Path("./jsons")
UNITTYPES_FILE = JSON_DIR / "UnitTypes.json"
NATIONS_FILE = JSON_DIR / "Nations.json"
UNITS_FILE = JSON_DIR / "Units.json"

COMMENT_RE = re.compile(r"^Comment \[(.*)\]$")
FOR_CIVS_RE = re.compile(r"<for \[([^\]]+)\] Civilizations>")
ONLY_AVAILABLE_RE = re.compile(r"^Only available <for \{([^}]+)\} Civilizations>")
PLAIN_UNBUILDABLE_RE = re.compile(r"^Unbuildable(?:\s*<.*>)?$")


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def parse_brace_list(raw: str) -> list[str]:
    """Parses '{Nation A} {Nation B}' into ['Nation A', 'Nation B']."""
    return [item.strip() for item in re.findall(r"\{([^}]+)\}", raw)]


def format_nation_list(nations: list[str]) -> str:
    if not nations:
        return ""
    if len(nations) == 1:
        return nations[0]
    if len(nations) == 2:
        return f"{nations[0]} and {nations[1]}"
    return f"{', '.join(nations[:-1])}, and {nations[-1]}"


def get_restricted_nations(uniques: list[str], known_nations: set[str]) -> tuple[list[str], bool]:
    """
    Returns (restricted_nations_in_order, unbuildable_for_all).
    Checks Unbuildable/Unavailable <for [...]>, Only available <for {...}>, and plain Unbuildable.
    """
    restricted: list[str] = []
    seen: set[str] = set()
    unbuildable_all = False

    def add_nation(name: str) -> None:
        if name in known_nations and name not in seen:
            seen.add(name)
            restricted.append(name)

    allowed_sets: list[set[str]] = []

    for unique in uniques:
        if not isinstance(unique, str):
            continue

        # 1. Unbuildable / Unavailable for specific civilizations
        if unique.startswith(("Unbuildable", "Unavailable")):
            match = FOR_CIVS_RE.search(unique)
            if match:
                add_nation(match.group(1).strip())
            elif PLAIN_UNBUILDABLE_RE.match(unique.strip()):
                unbuildable_all = True

        # 2. Only available for specific civilizations
        elif unique.startswith("Only available"):
            only_match = ONLY_AVAILABLE_RE.match(unique)
            if only_match:
                allowed_sets.append(set(parse_brace_list(only_match.group(1))))
            else:
                for_match = FOR_CIVS_RE.search(unique)
                if for_match:
                    allowed_sets.append({for_match.group(1).strip()})

    if allowed_sets:
        allowed_union = set().union(*allowed_sets)
        for nation in known_nations:
            if nation not in allowed_union:
                add_nation(nation)

    return restricted, unbuildable_all


def build_access_notice(restricted_nations: list[str], unbuildable_all: bool) -> str | None:
    if unbuildable_all:
        return "Cannot be built by any nation."
    if restricted_nations:
        return f"Cannot be built for {format_nation_list(restricted_nations)}."
    return None


def upsert_comment_unique(uniques: list[str], notice: str) -> list[str]:
    """
    Appends `notice` to an existing `Comment [...]` unique if not already at the end,
    or adds a new `Comment [...]` unique.
    """
    updated = list(uniques)
    for idx, item in enumerate(updated):
        if not isinstance(item, str):
            continue
        match = COMMENT_RE.match(item)
        if match:
            existing_text = match.group(1)
            # Avoid duplicating if the notice is already at the end of the comment
            if existing_text.rstrip().endswith(notice):
                return updated

            separator = "" if not existing_text or existing_text.endswith((" ", "\n")) else " "
            updated[idx] = f"Comment [{existing_text}{separator}{notice}]"
            return updated

    updated.append(f"Comment [{notice}]")
    return updated


def main() -> None:
    unittypes = load_json(UNITTYPES_FILE)
    nations = load_json(NATIONS_FILE)
    units = load_json(UNITS_FILE)

    known_nations = {
        n["name"]
        for n in nations
        if isinstance(n, dict) and isinstance(n.get("name"), str)
    }

    unittype_map = {
        ut["name"]: ut
        for ut in unittypes
        if isinstance(ut, dict) and isinstance(ut.get("name"), str)
    }

    for unit in units:
        if not isinstance(unit, dict):
            continue

        unit_uniques = unit.setdefault("uniques", [])
        combined_uniques: list[str] = []

        unit_type_name = unit.get("unitType") or unit.get("type")
        if isinstance(unit_type_name, str) and unit_type_name in unittype_map:
            ut_uniques = unittype_map[unit_type_name].get("uniques", [])
            if isinstance(ut_uniques, list):
                combined_uniques.extend(ut_uniques)

        if isinstance(unit_uniques, list):
            combined_uniques.extend(unit_uniques)

        restricted_nations, unbuildable_all = get_restricted_nations(
            combined_uniques, known_nations
        )
        notice = build_access_notice(restricted_nations, unbuildable_all)

        if notice:
            unit["uniques"] = upsert_comment_unique(unit_uniques, notice)

    save_json(UNITS_FILE, units)


if __name__ == "__main__":
    main()