#!/usr/bin/env python3
"""
Einmaliger Check der HP-Shopseiten (gedacht für GitHub Actions).
Meldet pro Artikel EINMAL per Telegram, sobald der Artikel lieferbar ist.

Ein Artikel gilt nur dann als "available", wenn
  - KEIN "Nicht lagernd" gefunden wird UND
  - ein positiver Kauf-Hinweis (z. B. "In den Warenkorb") sichtbar ist.
Findet das Skript weder noch, ist der Status "unknown" und es gibt KEINEN Alarm.

Aufruf:
  python watch.py          # normaler Lauf
  python watch.py --test   # Testlauf: Diagnose + Zusammenfassung per Telegram,
                           # speichert die HTML-Seiten (page_*.html), meldet/markiert nichts
Benötigt die Umgebungsvariablen TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID.
"""

import html as htmllib
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests

TEST = "--test" in sys.argv
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = Path(__file__).with_name("state.json")

URLS = {
    "GT17-0770ng": "https://www.hp.com/de-de/shop/products/desktops/omen-35l-gaming-desktop-gt17-0770ng-pc-d04t7ea-abd",
    "GT16-0779ng": "https://www.hp.com/de-de/shop/products/desktops/omen-35l-gaming-desktop-gt16-0779ng-pc-ba5g4ea-abd",
}

OOS_MARKERS = ["nicht lagernd"]                              # kleingeschrieben
IN_STOCK_MARKERS = ["in den warenkorb", "zum warenkorb hinzufügen"]
PRODUCT_SANITY_TEXT = "omen"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"notified": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def notify(text: str) -> bool:
    """Schickt eine Telegram-Nachricht. Gibt True zurück, wenn sie angekommen ist."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=15,
        )
    except requests.RequestException as e:
        # Fehlertext bewusst nicht ausgeben: er könnte die URL mit dem Token enthalten
        print(f"  Telegram-Fehler: {type(e).__name__}")
        return False

    if r.status_code == 200:
        print("  Telegram gesendet")
        return True
    print(f"  Telegram-Fehler: HTTP {r.status_code} {r.text[:200]}")
    return False


def visible_text(raw: str) -> str:
    """Sichtbarer Seitentext: ohne Script/Style, ohne Tags, Entities aufgelöst, kleingeschrieben."""
    t = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def classify(raw: str) -> tuple[str, str]:
    """Wertet das HTML aus. Gibt (status, detail) zurück: available | out_of_stock | unknown | error"""
    text = visible_text(raw)
    low = re.sub(r"\s+", " ", htmllib.unescape(raw).replace("\xa0", " ").lower())

    if PRODUCT_SANITY_TEXT not in text:
        return "error", f"keine Produktseite ({len(raw)} Zeichen, Captcha?)"

    oos = [m for m in OOS_MARKERS if m in text or m in low]
    instock = [m for m in IN_STOCK_MARKERS if m in text]
    detail = f"Nicht-lagernd: {'ja' if oos else 'nein'}, Kauf-Hinweis: {'ja' if instock else 'nein'}, {len(raw)} Zeichen"

    if oos:
        return "out_of_stock", detail
    if instock:
        return "available", detail
    return "unknown", detail


def check(key: str, url: str) -> tuple[str, str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        return "error", f"Netzwerkfehler: {type(e).__name__}"

    if r.status_code != 200:
        return "error", f"HTTP {r.status_code} (evtl. blockiert)"

    raw = r.text
    if TEST:
        Path(__file__).with_name(f"page_{key}.html").write_text(raw, encoding="utf-8")
        title = re.search(r"(?is)<title>(.*?)</title>", raw)
        print(f"  Diagnose {key}: URL={r.url} Typ={r.headers.get('content-type')} "
              f"Titel={title.group(1).strip()[:80] if title else '-'}")
        print(f"  Textanfang: {visible_text(raw)[:200]}")

    return classify(raw)


def set_output(key: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    if not TOKEN or not CHAT_ID:
        print("FEHLER: TELEGRAM_BOT_TOKEN und/oder TELEGRAM_CHAT_ID fehlen (GitHub-Secrets anlegen).")
        sys.exit(2)

    state = load_state()
    notified = set(state.get("notified", []))
    summary = []

    for key, url in URLS.items():
        if key in notified:
            print(f"{key}: bereits gemeldet, uebersprungen")
            summary.append(f"{key}: bereits gemeldet")
            continue

        status, detail = check(key, url)
        print(f"{key}: {status} - {detail}")
        summary.append(f"{key}: {status} ({detail})")

        # Im Testlauf nie alarmieren und nichts als gemeldet markieren
        if status == "available" and not TEST:
            sent = notify(f"🎉 HP OMEN wieder verfügbar!\n{key} ist nicht mehr 'Nicht lagernd'.\n{url}")
            if sent:  # nur als gemeldet markieren, wenn die Nachricht wirklich raus ist
                notified.add(key)

        time.sleep(random.uniform(2, 6))

    state["notified"] = sorted(notified)
    save_state(state)  # immer schreiben, damit die Datei existiert

    if TEST:
        notify("HP-Watcher Testlauf\n" + "\n".join(summary))

    set_output("all_done", "true" if notified >= set(URLS) else "false")


if __name__ == "__main__":
    main()
