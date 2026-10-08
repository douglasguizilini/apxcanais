
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
        headers={"User-Agent": "AirPix-Playlist-Updater/3.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
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
    return any(
        hint in host or hint in lowered
        for hint in PLUTO_HOST_HINTS
    )


def stable_pluto_url(channel_id: str) -> str | None:
    """
    Retorna um endereço de redirecionamento por ID,
    evitando salvar URLs com JWT temporário.
    """
    if re.fullmatch(r"[0-9a-fA-F]{24}", channel_id):
        return f"https://jmp2.uk/plu-{channel_id}.m3u8"

    return None


def update_playlist(
    current: str,
    source_streams: dict[str, str],
) -> tuple[str, int, int, int]:
    lines = current.splitlines()
    output = []
    current_id = None

    total_pluto = 0
    matched_pluto = 0
    converted_urls = 0

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
            is_pluto_channel = source_match or looks_pluto

            if is_pluto_channel:
                total_pluto += 1

            if source_match:
                matched_pluto += 1

            stable_url = (
                stable_pluto_url(current_id)
                if is_pluto_channel
                else None
            )

            if stable_url:
                output.append(stable_url)
                if line != stable_url:
                    converted_urls += 1
            elif source_match:
                # Para IDs não reconhecidos, preserva a URL da fonte.
                output.append(source_streams[current_id])
            else:
                output.append(raw)

            current_id = None
            continue

        output.append(raw)

    updated = "\n".join(output).rstrip() + "\n"

    return updated, matched_pluto, total_pluto, converted_urls


def main() -> int:
    if not TARGET.exists():
        print(f"Arquivo não encontrado: {TARGET}", file=sys.stderr)
        return 2

    current = TARGET.read_text(encoding="utf-8")

    try:
        source = read_url(SOURCE_URL)
    except Exception as exc:
        print(
            f"Falha ao baixar a fonte Pluto: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print("A playlist atual foi preservada.", file=sys.stderr)
        return 4

    source_streams = parse_streams(source)

    if not source_streams:
        print("Abortado: a fonte Pluto retornou zero streams.", file=sys.stderr)
        print("A playlist atual foi preservada.", file=sys.stderr)
        return 5

    updated, matched, total_pluto, converted = update_playlist(
        current,
        source_streams,
    )

    if total_pluto == 0:
        print(
            "Abortado: nenhum canal Pluto foi identificado.",
            file=sys.stderr,
        )
        return 6

    ratio = matched / total_pluto

    print(f"Canais Pluto identificados: {total_pluto}")
    print(f"Canais encontrados na fonte: {matched}")
    print(f"Cobertura da fonte: {ratio:.1%}")
    print(f"URLs convertidas para redirecionamento: {converted}")

    if ratio < MIN_MATCH_RATIO:
        print(
            f"Abortado: cobertura abaixo de {MIN_MATCH_RATIO:.0%}. "
            "A playlist atual foi preservada.",
            file=sys.stderr,
        )
        return 3

    if updated == current:
        print("Nenhuma alteração necessária.")
        return 0

    TARGET.write_text(updated, encoding="utf-8")
    print("Playlist atualizada com os endereços de redirecionamento.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
