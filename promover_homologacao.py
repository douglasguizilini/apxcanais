#!/usr/bin/env python3
import re
import sys
from pathlib import Path

PRODUCTION = Path("plutotv_brasil_v2_categorizada.m3u")
HOMOLOGATION = Path("apxcanais_homologacao.m3u")

EXPECTED_CURRENT = 93
EXPECTED_NEW = 36
EXPECTED_FINAL = 129

TVG_ID_RE = re.compile(r'tvg-id="([^"]*)"')
GROUP_RE = re.compile(r'group-title="([^"]*)"')

RELIGIOUS_TERMS = [
    "relig", "gospel", "igreja", "church", "evangel",
    "catolic", "católic", "biblia", "bíblia", "crist",
    "jesus", "god tv", "tbn", "canção nova", "cancao nova",
    "rede vida", "pai eterno", "novo tempo", "aparecida",
    "shalom", "adventista", "batista", "assembleia de deus",
    "boas novas", "istv",
]


def norm(text):
    text = text.lower()

    replacements = {
        "á": "a", "à": "a", "â": "a", "ã": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    return re.sub(r"\s+", " ", text).strip()


def contains_any(text, terms):
    hay = norm(text)
    return any(norm(term) in hay for term in terms)


def parse_m3u(text):
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

        if extinf and line.startswith("#"):
            extra.append(raw)
            continue

        if extinf and line.startswith(("http://", "https://")):
            tvg_match = TVG_ID_RE.search(extinf)

            entries.append({
                "extinf": extinf,
                "extra": extra[:],
                "url": line,
                "tvg_id": tvg_match.group(1).strip() if tvg_match else "",
                "name": extinf.rsplit(",", 1)[-1].strip(),
            })

            extinf = None
            extra = []

    return entries


def entry_key(entry):
    if entry["tvg_id"]:
        return ("id", entry["tvg_id"].lower())

    return (
        "name",
        norm(entry["name"]),
        entry["url"].split("?", 1)[0],
    )


def clean_group(extinf):
    match = GROUP_RE.search(extinf)

    if not match:
        return extinf

    current = match.group(1)

    if current.startswith("Homologação - "):
        current = current[len("Homologação - "):]

    if current.startswith("REVISAR - "):
        raise RuntimeError(
            "Encontrado canal da lista REVISAR. Promoção abortada."
        )

    return GROUP_RE.sub(
        f'group-title="{current}"',
        extinf,
    )


def main():
    if not PRODUCTION.exists():
        print("ERRO: playlist oficial não encontrada.", file=sys.stderr)
        return 2

    if not HOMOLOGATION.exists():
        print("ERRO: playlist de homologação não encontrada.", file=sys.stderr)
        return 3

    production_text = PRODUCTION.read_text(encoding="utf-8")
    homologation_text = HOMOLOGATION.read_text(encoding="utf-8")

    production_entries = parse_m3u(production_text)
    homologation_entries = parse_m3u(homologation_text)

    print(f"Produção atual: {len(production_entries)} canais")
    print(f"Homologação total: {len(homologation_entries)} canais")

    if len(production_entries) != EXPECTED_CURRENT:
        print(
            f"ERRO: esperávamos {EXPECTED_CURRENT} canais na produção, "
            f"mas encontramos {len(production_entries)}.",
            file=sys.stderr,
        )
        return 4

    production_keys = {
        entry_key(entry)
        for entry in production_entries
    }

    new_entries = []
    seen = set(production_keys)

    for entry in homologation_entries:
        key = entry_key(entry)

        if key in seen:
            continue

        seen.add(key)
        new_entries.append(entry)

    print(f"Novos canais encontrados: {len(new_entries)}")

    if len(new_entries) != EXPECTED_NEW:
        print(
            f"ERRO: esperávamos exatamente {EXPECTED_NEW} novos canais, "
            f"mas encontramos {len(new_entries)}.",
            file=sys.stderr,
        )
        print("A produção NÃO foi alterada.", file=sys.stderr)
        return 5

    for entry in new_entries:
        audit_text = (
            entry["name"] + " "
            + entry["extinf"] + " "
            + entry["url"]
        )

        if contains_any(audit_text, RELIGIOUS_TERMS):
            print(
                f"ERRO: possível canal religioso detectado: "
                f"{entry['name']}",
                file=sys.stderr,
            )
            print("A produção NÃO foi alterada.", file=sys.stderr)
            return 6

    output = production_text.rstrip() + "\n"

    for entry in new_entries:
        output += clean_group(entry["extinf"]) + "\n"

        for extra_line in entry["extra"]:
            output += extra_line + "\n"

        output += entry["url"] + "\n"

    final_entries = parse_m3u(output)

    if len(final_entries) != EXPECTED_FINAL:
        print(
            f"ERRO: a lista final deveria ter {EXPECTED_FINAL} canais, "
            f"mas resultou em {len(final_entries)}.",
            file=sys.stderr,
        )
        print("A produção NÃO foi alterada.", file=sys.stderr)
        return 7

    PRODUCTION.write_text(output, encoding="utf-8")

    print("")
    print("PROMOÇÃO CONCLUÍDA")
    print(f"Produção anterior: {EXPECTED_CURRENT}")
    print(f"Novos aprovados: {EXPECTED_NEW}")
    print(f"Produção final: {EXPECTED_FINAL}")
    print("Nenhum canal da lista REVISAR foi promovido.")
    print("Auditoria religiosa concluída.")
    print("Arquivo oficial atualizado com sucesso.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
