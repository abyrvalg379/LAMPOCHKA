"""Build LAMPOCHKA: extension-only zip into out/v<version>.

Legacy (Blender 3.6) support is dropped by decision of 2026-09-22 —
the extension targets Blender 4.2+ and is the only build.

Usage: python build.py            — public build (no libraries)
       python build.py --team     — also builds the team zip with the
                                    personal library bundled (NOT for publishing)
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

WORK = Path(__file__).resolve().parent
EXT = WORK / "extension"
OUT = WORK.parent / "out"
# personal library (PLS/Lumio derived) — bundled ONLY into the team zip
LIB_SOURCES = {
    "presets": WORK.parent / "presets" / "PLS",
    "gobos": WORK.parent / "presets" / "gobos",
    "ies": WORK.parent / "presets" / "ies",
    "hdri": Path("E:/3D/HDRI"),
}
# folders never bundled (user keeps them out of the browser)
LIB_EXCLUDE_DIRS = {"SP_big"}
# already-compressed formats — storing is much faster than deflating
STORED_EXT = {".exr", ".hdr", ".jpg", ".jpeg", ".png"}
TEAM_NOTE = """LAMPOCHKA TEAM BUILD — внутренняя сборка для команды VVERH.

Содержит библиотеки пресетов, собранные из коммерческих продуктов
(Pro-Lighting Studio, Lumio). Использовать только внутри студии.
НЕ публиковать и НЕ передавать третьим лицам.

Установка: как обычное расширение (Install from Disk).
Папки библиотек подхватятся автоматически; свои пути можно задать
в панели и в Preferences — они имеют приоритет.
"""


def main():
    manifest = (EXT / "blender_manifest.toml").read_text(encoding="utf-8")
    # ^-anchored: otherwise schema_version matches first
    ver = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"', manifest, re.MULTILINE)
    if not ver:
        sys.exit("build.py: no version line in blender_manifest.toml")
    version = ".".join(ver.groups())

    dest = OUT / f"v{version}"
    dest.mkdir(parents=True, exist_ok=True)

    ext_zip = dest / "lampochka_extension.zip"
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(EXT / "__init__.py", "__init__.py")
        z.write(EXT / "blender_manifest.toml", "blender_manifest.toml")

    for name in ("README.md", "README.ru.md", "LICENSE"):
        src = WORK / name
        if src.exists():
            shutil.copy2(src, dest / name)

    print(f"v{version}:")
    print(f"  {ext_zip}")

    if "--team" in sys.argv:
        build_team(dest)


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
            rel = path.relative_to(src_dir)
            if any(part in LIB_EXCLUDE_DIRS for part in rel.parts):
                continue
            arc = f"{arc_prefix}/{sub}/{rel.as_posix()}"
            if path.suffix.lower() in STORED_EXT:
                z.write(path, arc, compress_type=zipfile.ZIP_STORED)
            else:
                z.write(path, arc)
            count += 1
    return count


def build_team(dest):
    note_dest = dest / "TEAM_BUILD.txt"
    note_dest.write_text(TEAM_NOTE, encoding="utf-8")

    ext_zip = dest / "lampochka_team_extension.zip"
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(EXT / "__init__.py", "__init__.py")
        z.write(EXT / "blender_manifest.toml", "blender_manifest.toml")
        z.write(note_dest, "TEAM_BUILD.txt")
        n = _add_library(z, "libraries")
    print(f"  team: {ext_zip} ({n} library files)")


if __name__ == "__main__":
    main()
