#!/usr/bin/env python3
"""Spremlja prosta mesta na https://gasilec.net/izobrazevanje/ in pošilja ntfy obvestila.

Nastavitve (okoljske spremenljivke):
  NTFY_TOPIC  - ime ntfy teme (obvezno), npr. gasilci-ida-x7k2p9
  FILTRI      - seznam iskanih nizov, ločen z vejicami, npr. "IDA, modul A"
                Primerjava je neodvisna od velikih/malih črk in išče po oznaki tečaja.
                Prazno = vsi tečaji.
  NTFY_SERVER - privzeto https://ntfy.sh
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://gasilec.net/izobrazevanje/"
STATE_FILE = Path(__file__).with_name("stanje.json")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
FILTRI = [f.strip().lower() for f in os.environ.get("FILTRI", "").split(",") if f.strip()]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def preberi_tabelo(html: str) -> tuple[str, list[dict]]:
    """Vrne (čas posodobitve, seznam tečajev)."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_idx = None
        cols = {}
        posodobljeno = ""
        for i, tr in enumerate(rows):
            cells = [norm(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
            low = [c.lower() for c in cells]
            if any(c.startswith("posodobljeno") for c in low):
                posodobljeno = next((c for c in cells if re.search(r"\d", c)), "")
            if any("oznaka" in c for c in low):
                header_idx = i
                for j, c in enumerate(low):
                    if "oznaka" in c:
                        cols["oznaka"] = j
                    elif "lokacija" in c:
                        cols["lokacija"] = j
                    elif "termin" in c:
                        cols["termin"] = j
                    elif "mest" in c:
                        cols["mesta"] = j
                    elif "opomba" in c:
                        cols["opomba"] = j
                break
        if header_idx is None or "oznaka" not in cols:
            continue

        tecaji = []
        for tr in rows[header_idx + 1:]:
            cells = [norm(td.get_text(" ")) for td in tr.find_all(["td", "th"])]

            def get(name):
                j = cols.get(name)
                return cells[j] if j is not None and j < len(cells) else ""

            oznaka = get("oznaka")
            if not oznaka:
                continue
            m = re.search(r"\d+", get("mesta"))
            tecaji.append({
                "oznaka": oznaka,
                "lokacija": get("lokacija"),
                "termin": get("termin"),
                "mesta": int(m.group()) if m else 0,
                "opomba": get("opomba"),
            })
        return posodobljeno, tecaji
    raise RuntimeError("Tabele s tečaji ni bilo mogoče najti – se je stran spremenila?")


def kljuc(t: dict) -> str:
    return f"{t['oznaka']} | {t['lokacija']} | {t['termin']}"


def ustreza(t: dict) -> bool:
    if not FILTRI:
        return True
    oz = t["oznaka"].lower()
    return any(f in oz for f in FILTRI)


def opis(t: dict) -> str:
    s = f"{t['oznaka']} – {t['lokacija']}, {t['termin']}\nProsta mesta: {t['mesta']}"
    if t["opomba"]:
        s += f"\n({t['opomba']})"
    return s


def poslji(naslov: str, sporocilo: str, prioriteta: int = 4) -> None:
    if not NTFY_TOPIC:
        print("[ntfy izklopljen – NTFY_TOPIC ni nastavljen]\n", naslov, "\n", sporocilo)
        return
    r = requests.post(
        NTFY_SERVER,
        json={
            "topic": NTFY_TOPIC,
            "title": naslov,
            "message": sporocilo,
            "priority": prioriteta,
            "tags": ["fire_engine"],
            "click": URL,
        },
        timeout=20,
    )
    r.raise_for_status()


def main() -> int:
    resp = requests.get(URL, timeout=30, headers={"User-Agent": "gasilec-prosta-mesta/1.0 (osebno obvestilo)"})
    resp.raise_for_status()
    posodobljeno, tecaji = preberi_tabelo(resp.text)
    print(f"Posodobljeno na strani: {posodobljeno or '?'}; tečajev v tabeli: {len(tecaji)}")

    prej = None
    if STATE_FILE.exists():
        prej = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    zdaj = {"posodobljeno": posodobljeno, "tecaji": {kljuc(t): t for t in tecaji}}
    izbrani = [t for t in tecaji if ustreza(t)]

    if prej is None:
        # Prvi zagon: samo potrdi, da spremljanje deluje.
        if izbrani:
            vsebina = "\n\n".join(opis(t) for t in izbrani)
        else:
            vsebina = "Trenutno ni prostih mest za izbrane tečaje."
        poslji("Spremljanje vklopljeno", f"Filter: {', '.join(FILTRI) or 'vsi'}\n\n{vsebina}", prioriteta=3)
    else:
        prej_t = prej.get("tecaji", {})
        nova = []
        for t in izbrani:
            star = prej_t.get(kljuc(t))
            if star is None:
                nova.append(("Novo prosto mesto", t))
            elif t["mesta"] > star.get("mesta", 0):
                nova.append((f"Več mest ({star.get('mesta', 0)} → {t['mesta']})", t))
        for naslov, t in nova:
            print("OBVESTILO:", naslov, opis(t))
            poslji(f"{naslov}: {t['oznaka']}", opis(t), prioriteta=5)
        if not nova:
            print("Ni novih prostih mest za izbrane tečaje.")

    if prej != zdaj:
        STATE_FILE.write_text(json.dumps(zdaj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Stanje posodobljeno.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
