#!/usr/bin/env python3
import concurrent.futures
import ipaddress
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

PRODUCTION = Path("plutotv_brasil_v2_categorizada.m3u")
OUTPUT = Path("apxcanais_homologacao.m3u")
REVIEW = Path("apxcanais_revisar.m3u")
REPORT = Path("RELATORIO_HOMOLOGACAO.md")

SOURCES = [
    ("iptv-org Brasil", "https://iptv-org.github.io/iptv/countries/br.m3u"),
    ("Free-TV Brasil", "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_brazil.m3u8"),
]

TIMEOUT = 8
MAX_WORKERS = 20
USER_AGENT = "APX-Canais-Homologacao/3.1"

TVG_ID_RE = re.compile(r'tvg-id="([^"]*)"')
GROUP_RE = re.compile(r'group-title="([^"]*)"')

MOTO_BIKE_TERMS = [
    "motocross", "supercross", "enduro", "trial", "motorcycle",
    "mountain bike", "mtb", "downhill", "bmx", "bike", "ciclismo", "cycling",
]

BLOCK_TERMS = [
    "agro", "agricultura", "pecuaria", "pecuária", "canal do boi", "rural", "terra viva",

    "sport", "sports", "futebol", "football", "soccer", "premiere", "sportv",
    "espn", "bandsports", "basket", "basquete", "volei", "vôlei", "tenis", "tênis",
    "golf", "poker", "world poker tour", "fifa+", "fifa plus", "ge fast",
    "n sports", "nsports", "fish tv", "woohoo",

    "mma", "ufc", "boxe", "boxing", "wrestling", "kickboxing", "combate",

    "formula 1", "fórmula 1", "nascar", "stock car", "autoracing", "auto racing",
    "motorsport", "motorsports", "floracing",

    "relig", "gospel", "igreja", "church", "evangel", "catolic", "católic",
    "biblia", "bíblia", "crist", "jesus", "god tv", "tbn", "canção nova",
    "cancao nova", "rede vida", "pai eterno", "novo tempo", "aparecida",
    "shalom", "rcc", "adventista", "batista", "assembleia de deus",
    "boas novas", "istv",

    "partido", "parlamento", "senado", "legislative", "legislativo",
    "assembleia legislativa", "camara legislativa", "câmara legislativa",
    "tv camara", "tv câmara", "tv justiça", "tv justica",

    "shopping", "shop", "telemarket", "televendas", "vendas", "radio", "rádio",

    "culture", "cultura", "arte 1", "curta!", "museum", "museu", "classique",

    "anime", "boruto", "naruto", "one piece",

    "intervention", "british screen classics", "cbs news 24/7", "cnn headlines",
    "gloob", "discovery kids", "disney junior", "hgtv", "gnt",

    "tv paraense", "grande natal", "tv zoom", "o dia tv", "canal 38",
    "j3news", "tcm 10", "tv a folha", "amazon sat", "sic tv", "tv a critica",
    "tv a crítica", "tv difusao", "tv difusão", "tv futuro", "unisul", "stz tv",
    "tv metropole", "tv metrópole", "tv parana turismo", "tv paraná turismo",
    "tv guara", "tv guará", "tv pantanal", "nova era tv",
]

PAY_TV_TERMS = [
    "a&e latin america", "adult swim latin america", "lifetime latin america",
    "amc latin america", "axn", "sony movies", "sony channel",
    "studio universal", "tnt novelas", "nickelodeon",
]

REGIONAL_TERMS = [
    "interior", "litoral", "comunitaria", "comunitária", "metropolitano",
    "municipal", "prefeitura", "cidade verde", "grande natal",
    "viçosa", "vicosa", "natal", "maricá", "marica", "passo fundo",
    "petrópolis", "petropolis", "são raimundo", "sao raimundo",
    "cuiabá", "cuiaba", "brusque", "são mateus", "sao mateus",
    "sul bahia", "bahia", "paraná", "parana", "pantanal ms",
    "rio de janeiro", "tv aldeia", "araruna", "marajoara",
    "tv fronteira", "tv vila real", "tv clube", "rede meio norte",
    "rede minas", "tve rs", "tve bahia", "tv ufop",
    "sbt interior", "rbatv", "rede sptv", "tv alianca catarinense",
    "tv alternativa", "tv litoral rn", "tv itape", "tvitape",
    "tv sim cachoeiro", "tv sim sao mateus", "tv sim são mateus",
    "tv curuca", "tvc-rio",
]

REGIONAL_ALLOW = [
    "canal uol", "record news", "sbt news", "rede tv!", "rede tv",
    "tv brasil", "smithsonian channel", "red bull tv", "travel box brazil",
    "music box brazil", "mtv ",
]

REVIEW_TERMS = [
    "24/7", "24h", "24 h", "by a&e", "storage wars",
]

APPROVED_EXPLICIT = ["mtv catfish"]

RELIGIOUS_TERMS = [
    "relig", "gospel", "igreja", "church", "evangel", "catolic", "católic",
    "biblia", "bíblia", "crist", "jesus", "god tv", "tbn", "canção nova",
    "cancao nova", "rede vida", "pai eterno", "novo tempo", "aparecida",
    "shalom", "rcc", "adventista", "batista", "assembleia de deus",
    "boas novas", "istv",
]


def fetch(url, limit=None):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return response.read(limit) if limit else response.read()


def norm(text):
    text = text.lower()
    replacements = {
        "á": "a", "à": "a", "â": "a", "ã": "a", "é": "e", "ê": "e", "í": "i",
        "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ç": "c",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def clean_name(name):
    text = re.sub(r"\([^)]*\)", "", name)
    text = re.sub(r"\[[^]]*\]", "", text)
    text = norm(text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def contains_any(haystack, terms):
    normalized = norm(haystack)
    return any(norm(term) in normalized for term in terms)


def parse_m3u(text, source):
    entries = []
    extinf = None
    extra = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):
            extinf = raw
            extra = []
            continue

        if extinf and line.startswith("#") and not line.startswith("#EXTINF"):
            extra.append(raw)
            continue

        if extinf and line.startswith(("http://", "https://")):
            name = extinf.rsplit(",", 1)[-1].strip()
            tvg = TVG_ID_RE.search(extinf)
            group = GROUP_RE.search(extinf)

            entries.append({
                "extinf": extinf,
                "extra": extra[:],
                "url": line,
                "name": name,
                "name_key": clean_name(name),
                "tvg_id": tvg.group(1).strip() if tvg else "",
                "group": group.group(1).strip() if group else "",
                "source": source,
            })

            extinf = None
            extra = []

    return entries


def production_keys(text):
    ids, names, urls = set(), set(), set()

    for entry in parse_m3u(text, "produção"):
        if entry["tvg_id"]:
            ids.add(entry["tvg_id"].lower())
        if entry["name_key"]:
            names.add(entry["name_key"])
        urls.add(entry["url"].split("?", 1)[0])

    return ids, names, urls


def is_raw_ip_host(url):
    host = (urlparse(url).hostname or "").strip()

    if not host:
        return False

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def classify(entry):
    hay = f'{entry["name"]} {entry["group"]} {entry["extinf"]}'

    if contains_any(hay, APPROVED_EXPLICIT):
        return "keep", "aprovado explicitamente"

    if contains_any(hay, MOTO_BIKE_TERMS):
        return "keep", "moto/bike permitido"

    if contains_any(hay, BLOCK_TERMS):
        return "block", "excluído pela curadoria"

    if contains_any(hay, PAY_TV_TERMS):
        return "block", "marca de TV por assinatura/retransmissão"

    if "[geo-blocked]" in hay.lower():
        return "block", "geo-blocked"

    regional = contains_any(hay, REGIONAL_TERMS)
    regional_allowed = contains_any(hay, REGIONAL_ALLOW)

    if regional and not regional_allowed:
        return "block", "canal regional/local"

    if is_raw_ip_host(entry["url"]):
        return "review", "origem por IP direto — revisar legitimidade"

    if contains_any(hay, REVIEW_TERMS):
        return "review", "temático para revisão manual"

    return "keep", "candidato"


def validate_hls(entry):
    url = entry["url"]

    if "youtube.com/" in url or "youtu.be/" in url:
        return False, "YouTube"

    if ".mpd" in url.lower():
        return False, "DASH/MPD"

    if (urlparse(url).hostname or "").lower() in {"localhost", "127.0.0.1"}:
        return False, "host local"

    try:
        text = fetch(url, 16384).decode("utf-8", errors="ignore")
        ok = "#EXTM3U" in text[:16384]
        return ok, "ok" if ok else "não parece HLS"
    except Exception as exc:
        return False, type(exc).__name__


def retag(extinf, prefix):
    group_match = GROUP_RE.search(extinf)
    current = group_match.group(1) if group_match else "Outros"
    new_group = f"{prefix} - {current}"

    if group_match:
        return GROUP_RE.sub(f'group-title="{new_group}"', extinf)

    comma = extinf.rfind(",")

    if comma >= 0:
        return extinf[:comma] + f' group-title="{new_group}"' + extinf[comma:]

    return extinf


def write_playlist(path, production, entries, prefix):
    out = production.rstrip() + "\n"

    for entry in sorted(entries, key=lambda item: (item["group"], item["name"].lower())):
        out += retag(entry["extinf"], prefix) + "\n"

        for extra_line in entry["extra"]:
            out += extra_line + "\n"

        out += entry["url"] + "\n"

    path.write_text(out, encoding="utf-8")


def main():
    if not PRODUCTION.exists():
        raise SystemExit("Playlist de produção não encontrada.")

    production = PRODUCTION.read_text(encoding="utf-8")
    prod_ids, prod_names, prod_urls = production_keys(production)

    candidates = []
    source_counts = {}
    fetch_errors = []

    for source_name, url in SOURCES:
        try:
            parsed = parse_m3u(
                fetch(url).decode("utf-8", errors="replace"),
                source_name,
            )
            candidates.extend(parsed)
            source_counts[source_name] = len(parsed)
        except Exception as exc:
            source_counts[source_name] = 0
            fetch_errors.append(
                f"{source_name}: {type(exc).__name__}: {exc}"
            )

    seen_ids = set(prod_ids)
    seen_names = set(prod_names)
    seen_urls = set(prod_urls)

    unique = []
    duplicates = 0

    for entry in candidates:
        tvg_id = entry["tvg_id"].lower() if entry["tvg_id"] else ""
        name_key = entry["name_key"]
        url_key = entry["url"].split("?", 1)[0]

        duplicated = (
            (tvg_id and tvg_id in seen_ids)
            or (name_key and name_key in seen_names)
            or url_key in seen_urls
        )

        if duplicated:
            duplicates += 1
            continue

        if tvg_id:
            seen_ids.add(tvg_id)

        if name_key:
            seen_names.add(name_key)

        seen_urls.add(url_key)
        unique.append(entry)

    keep_raw = []
    review_raw = []
    blocked = []

    for entry in unique:
        status, reason = classify(entry)

        if status == "block":
            blocked.append((entry, reason))
        elif status == "review":
            review_raw.append(entry)
        else:
            keep_raw.append(entry)

    def validate_many(items):
        good = []
        bad = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(validate_hls, entry): entry
                for entry in items
            }

            for future in concurrent.futures.as_completed(futures):
                entry = futures[future]
                ok, reason = future.result()

                if ok:
                    good.append(entry)
                else:
                    bad.append((entry, reason))

        return good, bad

    keep, failed_keep = validate_many(keep_raw)
    review, failed_review = validate_many(review_raw)

    write_playlist(OUTPUT, production, keep, "Homologação")
    write_playlist(REVIEW, production, review, "REVISAR")

    prod_count = len(parse_m3u(production, "produção"))

    blocked_religious = sum(
        1
        for entry, _ in blocked
        if contains_any(
            f'{entry["name"]} {entry["group"]} {entry["extinf"]}',
            RELIGIOUS_TERMS,
        )
    )

    report = [
        "# Relatório de Homologação — APX Canais",
        "",
        "**A playlist oficial não é alterada por esta automação.**",
        "",
        f"- Produção preservada: **{prod_count} canais**",
        f"- Entradas coletadas: **{len(candidates)}**",
        f"- Duplicados removidos: **{duplicates}**",
        f"- Excluídos pela curadoria: **{len(blocked)}**",
        f"- Religiosos bloqueados: **{blocked_religious}**",
        f"- Novos canais aprovados tecnicamente para homologação: **{len(keep)}**",
        f"- Canais enviados para revisão manual: **{len(review)}**",
        f"- Links que falharam no teste: **{len(failed_keep) + len(failed_review)}**",
        "",
        "## Regras atuais",
        "- A lista oficial atual é preservada integralmente.",
        "- Prioridade para conteúdo em português/PT-BR.",
        "- RELIGIOSO: bloqueio absoluto para novos canais.",
        "- Excluídos: agronegócio, futebol/esportes fora de moto-bike, lutas, automobilismo de carros, política/legislativo, shopping, rádio, cultura/arte, anime e canais muito regionais.",
        "- Marcas de TV por assinatura não entram automaticamente.",
        "- Links por IP direto ficam em revisão, não em aprovação automática.",
        "- A automação não promove novos canais diretamente para a produção.",
        "",
        "## Observação de origem",
        "As fontes agregam links publicamente acessíveis, mas isso não é garantia independente de licenciamento de cada retransmissão. Por isso a homologação é conservadora e não promove automaticamente marcas pagas ou links diretos por IP.",
        "",
        "## Observação sobre idioma",
        "A fonte brasileira aumenta a chance de áudio em português, mas a M3U sozinha não garante dublagem/PT-BR.",
        "",
        "## Fontes",
    ]

    for source_name, _ in SOURCES:
        report.append(
            f"- {source_name}: {source_counts.get(source_name, 0)} entradas"
        )

    if fetch_errors:
        report += ["", "## Falhas de fonte"]
        report += [f"- {item}" for item in fetch_errors]

    REPORT.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print(f"Produção preservada: {prod_count}")
    print(f"Homologação: {len(keep)}")
    print(f"Revisar: {len(review)}")
    print(f"Bloqueados: {len(blocked)}")
    print(f"Religiosos bloqueados: {blocked_religious}")


if __name__ == "__main__":
    main()
