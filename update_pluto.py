#!/usr/bin/env python3
import re
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/OwnerPlugins/pluto-tv-m3u/main/pluto-live-BR.m3u"
TARGET = Path("plutotv_brasil_v2_categorizada.m3u")
MIN_MATCH_RATIO = 0.90

TVG_ID_RE = re.compile(r'tvg-id="([^"]+)"')

def read_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AirPix-Playlist-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")

def parse_streams(text: str) -> dict[str, str]:
    streams = {}
    current_id = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1) if match else None
        elif current_id and line.startswith(("http://", "https://")):
            streams[current_id] = line
            current_id = None
    return streams

def update_playlist(current: str, source_streams: dict[str, str]) -> tuple[str, int, int]:
    lines = current.splitlines()
    out = []
    current_id = None
    total = 0
    updated = 0

    for raw in lines:
        line = raw.strip()
        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1) if match else None
            if current_id:
                total += 1
            out.append(raw)
            continue

        if current_id and line.startswith(("http://", "https://")):
            new_url = source_streams.get(current_id)
            if new_url:
                out.append(new_url)
                updated += 1
            else:
                out.append(raw)
            current_id = None
            continue

        out.append(raw)

    return "\n".join(out).rstrip() + "\n", updated, total

def main() -> int:
    if not TARGET.exists():
        print(f"Arquivo não encontrado: {TARGET}", file=sys.stderr)
        return 2

    current = TARGET.read_text(encoding="utf-8")
    source = read_url(SOURCE_URL)
    source_streams = parse_streams(source)

    updated_text, matched, total = update_playlist(current, source_streams)
    ratio = (matched / total) if total else 0

    print(f"Canais na playlist AirPix: {total}")
    print(f"Canais encontrados na fonte nova: {matched}")
    print(f"Cobertura: {ratio:.1%}")

    if ratio < MIN_MATCH_RATIO:
        print(
            f"Abortado: cobertura abaixo do limite de {MIN_MATCH_RATIO:.0%}. "
            "A playlist atual foi preservada.",
            file=sys.stderr,
        )
        return 3

    if updated_text == current:
        print("Nenhuma alteração necessária.")
        return 0

    TARGET.write_text(updated_text, encoding="utf-8")
    print("Playlist atualizada com os streams mais recentes.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
