
#!/usr/bin/env python3
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    "OwnerPlugins/pluto-tv-m3u/main/pluto-live-BR.m3u"
)
TARGET = Path("plutotv_brasil_v2_categorizada.m3u")
MIN_MATCH_RATIO = 0.90

TVG_ID_RE = re.compile(r'tvg-id="([^"]+)"')
PLUTO_HOST_HINTS = ("pluto.tv", "plutotv", "jmp2.uk")


def read_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AirPix-Playlist-Updater/4.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def normalize_pluto_url(url: str) -> str:
    """
    Adiciona o parâmetro de eventos estendidos ao manifesto HLS,
    preservando a URL assinada e os parâmetros que já existem.
    """
    if re.search(
        r"(?:[?&])includeExtendedEvents=",
        url,
        flags=re.IGNORECASE,
    ):
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}includeExtendedEvents=true"


def parse_streams(text: str) -> dict[str, str]:
    streams = {}
    current_id = None

    for raw in text.splitlines():
        line = raw.strip()

        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None

        elif current_id and line.startswith(("http://", "https://")):
            streams[current_id] = normalize_pluto_url(line)
            current_id = None

    return streams


def is_pluto_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""

    lowered = url.lower()
    return any(
        hint in host or hint in lowered
        for hint in PLUTO_HOST_HINTS
    )


def update_playlist(
    current: str,
    source_streams: dict[str, str],
) -> tuple[str, int, int]:
    lines = current.splitlines()
    output = []
    current_id = None
    total_pluto = 0
    matched_pluto = 0

    for raw in lines:
        line = raw.strip()

        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None
            output.append(raw)
            continue

        if current_id and line.startswith(("http://", "https://")):
            source_match = current_id in source_streams
            looks_pluto = is_pluto_url(line)

            if source_match or looks_pluto:
                total_pluto += 1

            if source_match:
                output.append(source_streams[current_id])
                matched_pluto += 1
            else:
                output.append(raw)

            current_id = None
            continue

        output.append(raw)

    return (
        "\n".join(output).rstrip() + "\n",
        matched_pluto,
        total_pluto,
    )


def main() -> int:
    if not TARGET.exists():
        print(
            f"Arquivo não encontrado: {TARGET}",
            file=sys.stderr,
        )
        return 2

    current = TARGET.read_text(encoding="utf-8")

    try:
        source = read_url(SOURCE_URL)
    except Exception as exc:
        print(
            f"Falha ao baixar a fonte: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print("Playlist preservada, sem alterações.", file=sys.stderr)
        return 4

    source_streams = parse_streams(source)

    if not source_streams:
        print("Fonte sem streams. Playlist preservada.", file=sys.stderr)
        return 5

    updated, matched, total = update_playlist(
        current,
        source_streams,
    )

    if total == 0:
        print("Nenhum canal Pluto identificado.", file=sys.stderr)
        return 6

    ratio = matched / total

    print(f"Canais Pluto identificados: {total}")
    print(f"Canais correspondentes à fonte: {matched}")
    print(f"Cobertura: {ratio:.1%}")

    if ratio < MIN_MATCH_RATIO:
        print(
            "Cobertura insuficiente. Playlist preservada.",
            file=sys.stderr,
        )
        return 3

    if updated == current:
        print("Nenhuma alteração necessária.")
        return 0

    TARGET.write_text(updated, encoding="utf-8")
    print(
        "Playlist atualizada com URLs completas da fonte "
        "e includeExtendedEvents=true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
