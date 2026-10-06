#!/usr/bin/env python3
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

SOURCE_URL = "https://raw.githubusercontent.com/OwnerPlugins/pluto-tv-m3u/main/pluto-live-BR.m3u"
TARGET = Path("plutotv_brasil_v2_categorizada.m3u")
MIN_MATCH_RATIO = 0.90

TVG_ID_RE = re.compile(r'tvg-id="([^"]+)"')
PLUTO_HOST_HINTS = ("pluto.tv", "plutotv", "jmp2.uk")


def read_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AirPix-Playlist-Updater/2.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_streams(text: str) -> dict[str, str]:
    streams = {}
    current_id = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None
        elif current_id and line.startswith(("http://", "https://")):
            streams[current_id] = line
            current_id = None
    return streams


def is_pluto_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    lowered = url.lower()
    return any(hint in host or hint in lowered for hint in PLUTO_HOST_HINTS)


def update_playlist(current: str, source_streams: dict[str, str]) -> tuple[str, int, int]:
    lines = current.splitlines()
    out = []
    current_id = None
    total_pluto = 0
    matched_pluto = 0

    for raw in lines:
        line = raw.strip()

        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None
            out.append(raw)
            continue

        if current_id and line.startswith(("http://", "https://")):
            has_source_match = current_id in source_streams
            looks_pluto = is_pluto_url(line)
            is_pluto_channel = has_source_match or looks_pluto

            if is_pluto_channel:
                total_pluto += 1

            if has_source_match:
                out.append(source_streams[current_id])
                matched_pluto += 1
            else:
                out.append(raw)

            current_id = None
            continue

        out.append(raw)

    return "\n".join(out).rstrip() + "\n", matched_pluto, total_pluto


def main() -> int:
    if not TARGET.exists():
        print(f"Arquivo não encontrado: {TARGET}", file=sys.stderr)
        return 2

    current = TARGET.read_text(encoding="utf-8")

    try:
        source = read_url(SOURCE_URL)
    except Exception as exc:
        print(f"Falha ao baixar a fonte Pluto: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("A playlist atual foi preservada.", file=sys.stderr)
        return 4

    source_streams = parse_streams(source)

    if not source_streams:
        print("Abortado: a fonte Pluto retornou zero streams.", file=sys.stderr)
        print("A playlist atual foi preservada.", file=sys.stderr)
        return 5

    updated_text, matched, total_pluto = update_playlist(current, source_streams)

    if total_pluto == 0:
        print("Abortado: nenhum canal Pluto foi identificado na playlist.", file=sys.stderr)
        print("A playlist atual foi preservada.", file=sys.stderr)
        return 6

    ratio = matched / total_pluto

    print(f"Canais Pluto identificados na playlist AirPix: {total_pluto}")
    print(f"Canais Pluto encontrados na fonte nova: {matched}")
    print(f"Cobertura Pluto: {ratio:.1%}")
    print("Canais não-Pluto: preservados e fora do cálculo de cobertura.")

    if ratio < MIN_MATCH_RATIO:
        print(
            f"Abortado: cobertura Pluto abaixo do limite de {MIN_MATCH_RATIO:.0%}. "
            "A playlist atual foi preservada.",
            file=sys.stderr,
        )
        return 3

    if updated_text == current:
        print("Nenhuma alteração necessária.")
        return 0

    TARGET.write_text(updated_text, encoding="utf-8")
    print("Playlist atualizada. Canais Pluto renovados; demais canais preservados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
