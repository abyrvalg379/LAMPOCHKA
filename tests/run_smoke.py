# -*- coding:utf-8 -*-
"""Launch the LAMPOCHKA headless smoke test.

Builds the extension zip (build.py whitelist), installs it into an ISOLATED
user-resources dir (BLENDER_USER_RESOURCES - the host Blender config is
never touched), runs tests/smoke_blender.py headless, reports the verdict.

Usage:
  python tests/run_smoke.py [--blender PATH] [--keep]

Environment:
  BLENDER_BIN  default Blender executable when --blender is not given.

Exit code: 0 = all smoke steps passed, 1 = failure (or Blender crash/timeout).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent  # the addon repo root (build.py lives here)

# must mirror build.py's extension whitelist
ZIP_FILES = ["__init__.py", "update_checker.py", "blender_manifest.toml"]


def find_blender():
    env = os.environ.get("BLENDER_BIN")
    if env:
        return Path(env)
    candidates = []
    if sys.platform == "win32":
        base = Path("C:/Program Files/Blender Foundation")
        if base.exists():
            for d in sorted(base.iterdir(), reverse=True):
                candidates.append(d / "blender.exe")
        candidates += [Path("C:/Program Files/Blender/blender.exe")]
    else:
        which = shutil.which("blender")
        if which:
            return Path(which)
    for c in candidates:
        if c.exists():
            return c
    raise SystemExit("Blender not found - pass --blender PATH or set BLENDER_BIN")


def build_zip(dst: Path) -> Path:
    ext = REPO / "extension"
    missing = [f for f in ZIP_FILES if not (ext / f).exists()]
    if missing:
        raise SystemExit(f"missing files for zip: {missing}")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ZIP_FILES:
            z.write(ext / f, f)
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blender", type=Path, default=None,
                    help="Blender executable (default: BLENDER_BIN or autodetect)")
    ap.add_argument("--keep", action="store_true",
                    help="keep the temp dir (isolated resources) for debugging")
    ap.add_argument("--timeout", type=int, default=600,
                    help="per-invocation Blender timeout in seconds")
    args = ap.parse_args()

    blender = args.blender or find_blender()
    if not blender.exists():
        raise SystemExit(f"Blender not found: {blender}")

    tmp = Path(tempfile.mkdtemp(prefix="lampochka_smoke_"))
    ures = tmp / "user_resources"
    ures.mkdir()
    print(f"[smoke] blender : {blender}")

    zip_path = build_zip(tmp / "lampochka.zip")
    print(f"[smoke] zip     : {zip_path} ({zip_path.stat().st_size} bytes)")

    env = os.environ.copy()
    env["BLENDER_USER_RESOURCES"] = str(ures)

    def run(cmd, what):
        print(f"[smoke] {what}: {' '.join(str(c) for c in cmd)}")
        r = subprocess.run([str(c) for c in cmd], env=env,
                           capture_output=True, text=True,
                           errors="replace", timeout=args.timeout)
        return r

    ok = False
    try:
        r = run([blender, "--command", "extension", "install-file",
                 "-r", "user_default", "-e", zip_path], "install")
        print(r.stdout[-2000:])
        if r.returncode != 0:
            print(r.stderr[-4000:])
            raise SystemExit(f"extension install failed (exit {r.returncode})")

        r = run([blender, "-b", "--factory-startup", "--python",
                 str(TESTS / "smoke_blender.py")], "smoke ")
        print(r.stdout)
        if r.stderr.strip():
            print("--- stderr tail ---")
            print(r.stderr[-4000:])

        verdict = "SMOKE_RESULT:" in r.stdout and \
            r.stdout.rsplit("SMOKE_RESULT:", 1)[1].splitlines()[0].strip()
        ok = r.returncode == 0 and bool(verdict) and verdict.startswith("PASS")
        if not ok:
            print(f"[smoke] FAILED (exit={r.returncode}, verdict={verdict!r})")
        else:
            print(f"[smoke] OK - {verdict}")
        return 0 if ok else 1
    except subprocess.TimeoutExpired:
        print(f"[smoke] FAILED - Blender timed out after {args.timeout}s")
        return 1
    finally:
        if ok and not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        elif not ok:
            print(f"[smoke] temp kept for debugging: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
