
#!/usr/bin/env python3
import json
import re
import sys
import time
import uuid
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    "OwnerPlugins/pluto-tv-m3u/main/pluto-live-BR.m3u"
)
BOOT_URL = "https://boot.pluto.tv/v4/start"
TARGET = Path("plutotv_brasil_v2_categorizada.m3u")
MIN_MATCH_RATIO = 0.90

TVG_ID_RE = re.compile(r'tvg-id="([^"]+)"')
CHANNEL_PATH_RE = re.compile(
    r"/channel/([A-Za-z0-9]+)/master\.m3u8"
)
JMP2_PATH_RE = re.compile(
    r"/plu-([A-Za-z0-9]+)\.m3u8"
)
PLUTO_HOST_HINTS = ("pluto.tv", "plutotv", "jmp2.uk")
BR_FORWARD_IP = "177.47.27.205"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def read_url(url: str, headers: dict | None = None) -> str:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers,
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_boot_data() -> dict:
    params = {
        "appName": "web",
        "appVersion": (
            "8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6"
        ),
        "deviceVersion": "131.0.0",
        "deviceModel": "web",
        "deviceMake": "chrome",
        "deviceType": "web",
        "clientID": str(uuid.uuid4()),
        "clientModelNumber": "1.0.0",
        "deviceId": str(uuid.uuid4()),
        "country": "BR",
        "preferredLanguage": "pt",
        "serverSideAds": "false",
        "drmCapabilities": "widevine:L3",
        "blockingMode": "",
        "clientTime": str(int(time.time())),
    }

    headers = {
        "Origin": "https://pluto.tv",
        "Referer": "https://pluto.tv/",
        "Accept": "*/*",
        "X-Forwarded-For": BR_FORWARD_IP,
    }

    raw = read_url(
        f"{BOOT_URL}?{urlencode(params)}",
        headers=headers,
    )
    data = json.loads(raw)

    token = data.get("sessionToken")
    stitcher = (data.get("servers") or {}).get("stitcher")
    stitcher_params = data.get("stitcherParams")

    if (
        not token
        or not stitcher
        or not isinstance(stitcher_params, str)
    ):
        raise ValueError(
            "A resposta da Pluto não contém os dados "
            "necessários para montar os streams."
        )

    return data


def build_stream_url(channel_id: str, boot: dict) -> str:
    stitcher = boot["servers"]["stitcher"].rstrip("/")
    token = boot["sessionToken"]

    params = dict(
        parse_qsl(
            boot["stitcherParams"],
            keep_blank_values=True,
        )
    )

    # Token e parâmetros pertencentes à mesma sessão.
    params["jwt"] = token
    params["includeExtendedEvents"] = "true"
    params["masterJWTPassthrough"] = "true"

    return (
        f"{stitcher}/v2/stitch/hls/channel/"
        f"{channel_id}/master.m3u8?{urlencode(params)}"
    )


def parse_streams(text: str) -> dict[str, str]:
    channels = {}
    current_id = None

    for raw in text.splitlines():
        line = raw.strip()

        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None

        elif current_id and line.startswith(("http://", "https://")):
            match = CHANNEL_PATH_RE.search(urlparse(line).path)

            if match:
                channels[current_id] = match.group(1)

            current_id = None

    return channels


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


def get_channel_id(
    current_id: str | None,
    url: str,
    source_channels: dict[str, str],
) -> str | None:
    if current_id and current_id in source_channels:
        return source_channels[current_id]

    path = urlparse(url).path

    match = CHANNEL_PATH_RE.search(path)
    if match:
        return match.group(1)

    match = JMP2_PATH_RE.search(path)
    if match:
        return match.group(1)

    return None


def update_playlist(
    current: str,
    source_channels: dict[str, str],
    boot: dict,
) -> tuple[str, int, int]:
    output = []
    current_id = None
    total_pluto = 0
    matched_pluto = 0

    for raw in current.splitlines():
        line = raw.strip()

        if line.startswith("#EXTINF"):
            match = TVG_ID_RE.search(line)
            current_id = match.group(1).strip() if match else None
            output.append(raw)
            continue

        if current_id and line.startswith(("http://", "https://")):
            looks_pluto = is_pluto_url(line)
            channel_id = get_channel_id(
                current_id,
                line,
                source_channels,
            )

            if looks_pluto:
                total_pluto += 1

            if channel_id and (
                looks_pluto
                or current_id in source_channels
            ):
                output.append(build_stream_url(channel_id, boot))
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
        source_channels = parse_streams(source)

        if not source_channels:
            raise ValueError(
                "A fonte não contém IDs de canais reconhecíveis."
            )

        boot = fetch_boot_data()

    except Exception as exc:
        print(
            f"Falha ao obter sessão da Pluto: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "Playlist preservada, sem alterações.",
            file=sys.stderr,
        )
        return 4

    updated, matched, total = update_playlist(
        current,
        source_channels,
        boot,
    )

    if total == 0:
        print(
            "Nenhum canal Pluto identificado.",
            file=sys.stderr,
        )
        return 6

    ratio = matched / total

    print(f"Canais Pluto identificados: {total}")
    print(f"Canais com URL reconstruída: {matched}")
    print(f"Cobertura: {ratio:.1%}")

    if ratio < MIN_MATCH_RATIO:
        print(
            "Cobertura insuficiente. Playlist preservada.",
            file=sys.stderr,
        )
        return 3

    TARGET.write_text(updated, encoding="utf-8")

    print(
        "Playlist atualizada com token de sessão e "
        "parâmetros do stitcher."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
