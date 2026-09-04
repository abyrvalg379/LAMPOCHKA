"""Build LAMPOCHKA: generate legacy from extension + zips into out/v<version>.

The legacy package gets a generated bl_info preamble. The v2.4.1/v2.5.0
regression (legacy shipped without bl_info) must never repeat, so this
script is the only supported way to build the zips.

Usage: python build.py            — public build (no libraries)
       python build.py --team     — also builds team zips with the personal
                                    library bundled (NOT for publishing)
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

WORK = Path(__file__).resolve().parent
EXT = WORK / "extension"
LEGACY = WORK / "legacy" / "lampochka"
OUT = WORK.parent / "out"
# personal library (PLS/Lumio derived) — bundled ONLY into team zips
LIB_SOURCES = {
    "presets": WORK.parent / "presets" / "PLS",
    "gobos": WORK.parent / "presets" / "gobos",
    "ies": WORK.parent / "presets" / "ies",
}
TEAM_NOTE = """LAMPOCHKA TEAM BUILD — внутренняя сборка для команды VVERH.

Содержит библиотеки пресетов, собранные из коммерческих продуктов
(Pro-Lighting Studio, Lumio). Использовать только внутри студии.
НЕ публиковать и НЕ передавать третьим лицам.

Установка: как обычный аддон (Install from Disk / Install).
Папки библиотек подхватятся автоматически; свои пути можно задать
в панели и в Preferences — они имеют приоритет.
"""

BL_INFO = '''"""LAMPOCHKA — manage all lights in the scene."""
bl_info = {
    "name": "LAMPOCHKA",
    "author": "Maksim Kovalev",
    "version": (%VERSION%),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > LAMPOCHKA",
    "description": "Manage all lights in the scene + HDRI/IES/Gobo browsers, sun helper, light linking, presets",
    "doc_url": "https://github.com/abyrvalg379/lampochka",
    "license": "GPL-3.0-or-later",
    "category": "Lighting",
}
'''


def main():
    manifest = (EXT / "blender_manifest.toml").read_text(encoding="utf-8")
    # ^-anchored: otherwise schema_version matches first
    ver = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"', manifest, re.MULTILINE)
    if not ver:
        sys.exit("build.py: no version line in blender_manifest.toml")
    v = tuple(int(g) for g in ver.groups())
    version = ".".join(str(x) for x in v)

    body = (EXT / "__init__.py").read_text(encoding="utf-8")
    header = BL_INFO.replace("%VERSION%", "{}, {}, {}".format(v[0], v[1], v[2]))
    LEGACY.mkdir(parents=True, exist_ok=True)
    (LEGACY / "__init__.py").write_text(header + "\n" + body, encoding="utf-8")

    dest = OUT / f"v{version}"
    dest.mkdir(parents=True, exist_ok=True)

    ext_zip = dest / "lampochka_extension.zip"
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(EXT / "__init__.py", "__init__.py")
        z.write(EXT / "blender_manifest.toml", "blender_manifest.toml")

    leg_zip = dest / "lampochka_legacy.zip"
    with zipfile.ZipFile(leg_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(LEGACY / "__init__.py", "lampochka/__init__.py")

    for name in ("README.md", "README_ru.md", "LICENSE"):
        src = WORK / name
        if src.exists():
            shutil.copy2(src, dest / name)

    print(f"v{version}:")
    print(f"  {ext_zip}")
    print(f"  {leg_zip}")

    if "--team" in sys.argv:
        build_team(dest, version, body)


def _add_library(z, arc_prefix):
    """Bundle the personal library into the package."""
    count = 0
    for sub, src_dir in LIB_SOURCES.items():
        if not src_dir.is_dir():
            print(f"  ! library source missing: {src_dir}")
            continue
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".blend":
                continue  # heavy sources stay local
            arc = f"{arc_prefix}/{sub}/{path.relative_to(src_dir).as_posix()}"
            z.write(path, arc)
            count += 1
    return count


def build_team(dest, version, body):
    header = BL_INFO.replace("%VERSION%", "{}, {}, {}".format(*version.split(".")))
    note_dest = dest / "TEAM_BUILD.txt"
    note_dest.write_text(TEAM_NOTE, encoding="utf-8")

    ext_zip = dest / "lampochka_team_extension.zip"
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__init__.py", body)
        z.writestr("blender_manifest.toml",
                   (EXT / "blender_manifest.toml").read_text(encoding="utf-8"))
        z.writestr("TEAM_BUILD.txt", TEAM_NOTE)
        n = _add_library(z, "libraries")
    print(f"  team: {ext_zip} ({n} library files)")

    leg_zip = dest / "lampochka_team_legacy.zip"
    with zipfile.ZipFile(leg_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lampochka/__init__.py", header + chr(10) + body)
        z.writestr("lampochka/TEAM_BUILD.txt", TEAM_NOTE)
        _add_library(z, "lampochka/libraries")
    print(f"  team: {leg_zip}")


if __name__ == "__main__":
    main()
