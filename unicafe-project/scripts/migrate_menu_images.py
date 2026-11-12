"""Normalize demo menu data on existing Firestore menu documents.

The script matches documents by their current display name and updates their
BDT price, stock, availability, and local image path. Firestore document IDs
and descriptive fields are preserved. Run without ``--apply`` to preview the
changes first.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_db  # noqa: E402
from app.repositories.menu import MenuRepository  # noqa: E402


MENU_UPDATES = {
    "classic latte": {
        "price": 180,
        "stock_quantity": 25,
        "is_available": True,
        "image_url": "/static/images/menu/classic-latte.jpg",
    },
    "iced americano": {
        "price": 160,
        "stock_quantity": 30,
        "is_available": True,
        "image_url": "/static/images/menu/iced-americano.jpg",
    },
    "matcha latte": {
        "price": 220,
        "stock_quantity": 18,
        "is_available": True,
        "image_url": "/static/images/menu/matcha-latte.jpg",
    },
    "cappuccino": {
        "price": 190,
        "stock_quantity": 25,
        "is_available": True,
        "image_url": "/static/images/menu/cappuccino.jpg",
    },
    "blueberry muffin": {
        "price": 120,
        "stock_quantity": 20,
        "is_available": True,
        "image_url": "/static/images/menu/blueberry-muffin.jpg",
    },
    "chocolate croissant": {
        "price": 140,
        "stock_quantity": 15,
        "is_available": True,
        "image_url": "/static/images/menu/chocolate-croissant.jpg",
    },
    "chicken sandwich": {
        "price": 250,
        "stock_quantity": 20,
        "is_available": True,
        "image_url": "/static/images/menu/chicken-sandwich.jpg",
    },
    "cheese toast": {
        "price": 150,
        "stock_quantity": 25,
        "is_available": True,
        "image_url": "/static/images/menu/cheese-toast.jpg",
    },
    "turkey club wrap": {
        "price": 280,
        "stock_quantity": 15,
        "is_available": True,
        "image_url": "/static/images/menu/turkey-club-wrap.jpg",
    },
    "vegan wrap": {
        "price": 240,
        "stock_quantity": 18,
        "is_available": True,
        "image_url": "/static/images/menu/vegan-wrap.jpg",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write image_url changes to Firestore (default: preview only)",
    )
    args = parser.parse_args()

    db = get_db()
    if db is None:
        raise SystemExit("Firestore is unavailable; check the local Firebase configuration")

    repository = MenuRepository(db)
    menu_items = repository.list_all(include_unavailable=True)
    matched_names: set[str] = set()
    pending: list[tuple[str, str, dict[str, object]]] = []

    for item in menu_items:
        name = str(item.get("name") or "").strip()
        key = name.casefold()
        updates = MENU_UPDATES.get(key)
        if updates is None:
            continue
        matched_names.add(key)
        changed = {
            field: value
            for field, value in updates.items()
            if item.get(field) != value
        }
        if not changed:
            continue
        pending.append((str(item["id"]), name, changed))

    missing = sorted(set(MENU_UPDATES) - matched_names)
    mode = "APPLY" if args.apply else "PREVIEW"
    for item_id, name, updates in pending:
        summary = ", ".join(f"{key}={value!r}" for key, value in updates.items())
        print(f"[{mode}] {item_id}: {name} -> {summary}")
        if args.apply:
            repository.update(item_id, updates)

    print(
        f"Matched {len(matched_names)} of {len(MENU_UPDATES)} demo items; "
        f"{len(pending)} change(s) {'applied' if args.apply else 'pending'}."
    )
    if missing:
        print("Missing Firestore menu names: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
