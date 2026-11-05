"""Repariert Codex-Threads, die auf den nicht mehr existierenden Provider zeigen.

Hintergrund: Die Config nutzt seit dem 05.11. den Provider `opencode-proxy` mit
`proxy-catalog.json`. In `state_5.sqlite` stehen aeltere Threads aber noch mit
`model_provider = 'opencode-go'` (und Modellen, die nicht mehr im Katalog sind).
Wird so ein Thread geoeffnet, meldet Codex "… is not a valid model ID".

Vorgehen:
  1. Abbruch, solange Codex laeuft (sonst ueberschreibt die App die Aenderung).
  2. Sicherung von state_5.sqlite samt -wal/-shm nach ~/.codex/backups.
  3. Provider auf `opencode-proxy` setzen. Modell bleibt, wenn es im Katalog
     steht, sonst wird es auf das Standardmodell umgeschrieben.
  4. Kontrolle: verbleibende Threads mit unbekanntem Provider/Modell melden.

Aufruf:
    python repair-threads.py            # nur anzeigen (dry run)
    python repair-threads.py --apply    # Sicherung + Update
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time

HOME = os.path.expanduser("~")
CODEX = os.path.join(HOME, ".codex")
DB = os.path.join(CODEX, "state_5.sqlite")
CATALOG = os.path.join(CODEX, "proxy-catalog.json")
OLD_PROVIDER = "opencode-go"
NEW_PROVIDER = "opencode-proxy"


def catalog_slugs() -> set[str]:
    with open(CATALOG, encoding="utf-8") as handle:
        return {entry["slug"] for entry in json.load(handle)["models"]}


def configured_model(slugs: set[str]) -> str:
    """Standardmodell aus der Config, sonst das erste Katalogmodell."""
    try:
        import tomllib

        with open(os.path.join(CODEX, "config.toml"), "rb") as handle:
            model = tomllib.load(handle).get("model")
    except Exception:  # noqa: BLE001 - Diagnose
        model = None
    if isinstance(model, str) and model in slugs:
        return model
    return sorted(slugs)[0]


def codex_running() -> bool:
    import subprocess

    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ChatGPT.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception:  # noqa: BLE001 - Diagnose
        return False
    return "ChatGPT.exe" in out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--include-free",
        action="store_true",
        help="auch Threads mit Free-Modellen auf das Standardmodell umstellen "
        "(Free-Tier ist fuer Agenten gesperrt: 403/429)",
    )
    args = parser.parse_args()

    slugs = catalog_slugs()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "select id, title, model_provider, model from threads where model_provider = ?",
        (OLD_PROVIDER,),
    ).fetchall()
    if args.include_free:
        extra = con.execute(
            "select id, title, model_provider, model from threads where model like '%-free' and model_provider != ?",
            (OLD_PROVIDER,),
        ).fetchall()
        rows = rows + extra
    con.close()

    if not rows:
        print(f"keine Threads mit Provider '{OLD_PROVIDER}'")
        return 0

    print(f"{len(rows)} Threads zum Pruefen:")
    planned = []
    for tid, _title, _provider, model in rows:
        if model and str(model).endswith("-free"):
            target_model = None  # Free-Tier ist fuer Agenten gesperrt
        else:
            target_model = model if model in slugs else None
        planned.append((tid, model, target_model))
        mark = "bleibt" if target_model else "-> Standardmodell"
        print(f"  {tid[:12]}  {str(model):36} {mark}")

    fallback = configured_model(slugs)
    if not args.apply:
        print(f"\nDry run. Mit --apply wird geschrieben; Zielmodell fuer unbekannte: {fallback}")
        return 0

    if codex_running():
        print("Codex laeuft noch - bitte vollstaendig beenden und erneut aufrufen.")
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(CODEX, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        source = DB + suffix
        if os.path.exists(source):
            target = os.path.join(backup_dir, f"state_5.sqlite{suffix}.bak-{stamp}")
            shutil.copy2(source, target)
            print(f"gesichert: {target}")

    con = sqlite3.connect(DB)
    changed = 0
    for tid, _model, target_model in planned:
        new_model = target_model or fallback
        con.execute(
            "update threads set model_provider = ?, model = ? where id = ?",
            (NEW_PROVIDER, new_model, tid),
        )
        changed += 1
    con.commit()
    con.close()
    print(f"\n{changed} Threads aktualisiert auf Provider '{NEW_PROVIDER}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
