#!/usr/bin/env python3
"""
Einmaliger Check der HP-Shopseiten (gedacht für GitHub Actions).
Meldet pro Artikel EINMAL per ntfy.sh, sobald "Nicht lagernd" verschwindet.

Aufruf:
  python watch.py          # normaler Lauf
  python watch.py --test   # Testlauf: schickt immer eine Zusammenfassung ans Handy
Benötigt die Umgebungsvariable NTFY_TOPIC (in GitHub als Secret hinterlegt).
"""

import json
import os
import random
import sys
import time
from pathlib import Path

import requests

TEST = "--test" in sys.argv
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
STATE_FILE = Path(__file__).with_name("state.json")

URLS = {
    "GT17-0770ng": "https://www.hp.com/de-de/shop/products/desktops/omen-35l-gaming-desktop-gt17-0770ng-pc-d04t7ea-abd",
    "GT16-0779ng": "https://www.hp.com/de-de/shop/products/desktops/omen-35l-gaming-desktop-gt16-0779ng-pc-ba5g4ea-abd",
}

OUT_OF_STOCK_TEXT = "Nicht lagernd"
PRODUCT_SANITY_TEXT = "OMEN"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"notified": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def notify(title: str, message: str, click_url: str | None = None, priority: str = "default") -> None:
    # HTTP-Header müssen ASCII sein -> keine Umlaute im Titel
    headers = {"Title": title, "Priority": priority, "Tags": "tada"}
    if click_url:
        headers["Click"] = click_url
    try:
        r = requests.post(
            f"https://ntfy.sh/{TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        print(f"  ntfy gesendet: {title}")
    except requests.RequestException as e:
        print(f"  ntfy-Fehler: {e}")


def check(url: str) -> tuple[str, str]:
    """Gibt (status, detail) zurück. status: available | out_of_stock | error"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        return "error", f"Netzwerkfehler: {e}"

    if r.status_code != 200:
        return "error", f"HTTP {r.status_code} (evtl. blockiert)"

    html = r.text
    if PRODUCT_SANITY_TEXT not in html:
        return "error", f"HTTP 200, aber keine Produktseite ({len(html)} Zeichen, Captcha?)"

    if OUT_OF_STOCK_TEXT in html:
        return "out_of_stock", f"HTTP 200, '{OUT_OF_STOCK_TEXT}' gefunden"
    return "available", f"HTTP 200, '{OUT_OF_STOCK_TEXT}' NICHT gefunden"


def set_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    if not TOPIC:
        print("FEHLER: Umgebungsvariable NTFY_TOPIC fehlt (GitHub-Secret anlegen).")
        sys.exit(2)

    state = load_state()
    notified = set(state.get("notified", []))
    summary = []

    for key, url in URLS.items():
        if key in notified:
            print(f"{key}: bereits gemeldet, uebersprungen")
            summary.append(f"{key}: bereits gemeldet")
            continue

        status, detail = check(url)
        print(f"{key}: {status} - {detail}")
        summary.append(f"{key}: {status} ({detail})")

        if status == "available":
            notify(
                "HP OMEN wieder verfuegbar!",
                f"{key} ist nicht mehr 'Nicht lagernd'.",
                click_url=url,
                priority="high",
            )
            notified.add(key)

        time.sleep(random.uniform(2, 6))

    state["notified"] = sorted(notified)
    save_state(state)  # immer schreiben, damit die Datei existiert

    if TEST:
        notify("HP-Watcher Testlauf", "\n".join(summary))

    set_output("all_done", "true" if notified >= set(URLS) else "false")


if __name__ == "__main__":
    main()
