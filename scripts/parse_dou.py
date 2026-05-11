#!/usr/bin/env python3
"""
parse_dou.py — filtra os XMLs do DOU baixados pelo fetch_inlabs.py por temas SGP/TRT-17.

Lê:    <DOU_ROOT>/<YYYY-MM-DD>/extracted/*.xml
Grava: <DOU_ROOT>/<YYYY-MM-DD>/inlabs-filtered.json
"""
import argparse
import html
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DOU_ROOT = Path(os.environ.get("DOU_ROOT", REPO_ROOT / "dou"))

KEYWORDS: dict[str, list[str]] = {
    "aposentadoria": ["aposentadoria", "aposenta", "aposentado", "aposentada"],
    "pensao": ["pensão", "pensao", "pensionista"],
    "abono_permanencia": ["abono de permanência", "abono de permanencia"],
    "reversao": ["reversão", "reversao"],
    "averbacao_tempo": ["averbação de tempo", "averbacao de tempo", "contagem de tempo", "tempo de contribuição"],
    "acumulacao_cargos": ["acumulação de cargos", "acumulacao de cargos", "acúmulo de cargos", "acumulo de cargos"],
    "teto_remuneratorio": ["teto remuneratório", "teto remuneratorio", "subteto", "art. 37, xi"],
    "isencao_ir": ["isenção de imposto de renda", "isencao de imposto de renda", "isenção do ir", "moléstia grave", "molestia grave"],
    "quintos_anuenios_ats": ["quintos", "anuênios", "anuenios", "adicional por tempo de serviço", "ats"],
    "ajuda_custo": ["ajuda de custo", "indenização de transporte", "indenizacao de transporte"],
    "cessao_redistribuicao": ["cessão", "cessao ", "redistribuição", "redistribuicao", "remoção", "remocao ", "permuta"],
    "substituicao_fc_cc": ["substituição", "substituicao", "função comissionada", "funcao comissionada", "cargo em comissão", "cargo em comissao", " fc-", " cc-"],
    "insalubridade_periculosidade": ["insalubridade", "periculosidade", "adicional ocupacional"],
    "licencas_gerais": ["licença para capacitação", "licença para tratar de interesses particulares", "licença-prêmio",
                        "licença premio", "licença atividade política", "licença mandato classista", "licença gestante",
                        "licença paternidade", "licença adotante", "licença cônjuge", "licença conjuge", "recondução",
                        "reconducao"],
    "licenca_saude": ["licença para tratamento de saúde", "licenca para tratamento de saude", "licença por motivo de doença",
                      "licenca por motivo de doenca", "pessoa da família", "pessoa da familia"],
    "folha_esocial": ["folha de pagamento", "esocial", "consignações", "consignacoes", "consignação", "consignacao"],
    "funpresp": ["funpresp", "funpresp-jud", "previdência complementar", "previdencia complementar"],
    "auxilios": ["auxílio-alimentação", "auxilio-alimentacao", "auxílio pré-escolar", "auxilio pre-escolar",
                 "auxílio-saúde", "auxilio-saude", "auxílio-transporte", "auxilio-transporte", "auxílio-funeral",
                 "auxilio-funeral", "auxílio-natalidade", "auxilio-natalidade"],
    "competencias_capacitacao": ["gestão por competências", "gestao por competencias", "plano de capacitação",
                                 "plano de capacitacao", "avaliação de desempenho", "avaliacao de desempenho",
                                 "ensino a distância", "ena", "enajud"],
    "teletrabalho_jornada": ["teletrabalho", "trabalho remoto", "jornada de trabalho", "condição especial de trabalho",
                             "condicao especial de trabalho", "banco de horas"],
    "estagio_aprendizagem": ["estágio", "estagio", "aprendizagem", "menor aprendiz"],
}

PRIORITY_ORGAOS: list[str] = [
    "csjt", "tst", "tribunal superior do trabalho",
    "cnj", "conselho nacional de justiça", "conselho nacional de justica",
    "tcu", "tribunal de contas da união", "tribunal de contas da uniao",
    "stf", "supremo tribunal federal",
    "stj", "superior tribunal de justiça", "superior tribunal de justica",
    "trt da 17", "trt 17", "trt-17", "17ª região", "17a regiao",
    "ministério da gestão", "ministerio da gestao", "mgi/sgp",
    "secretaria de gestão e desempenho de pessoal", "secretaria de gestao e desempenho de pessoal", "sgdp",
    "funpresp-jud", "previc",
    "receita federal",
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_field(root: ET.Element, *tags: str) -> str:
    for tag in tags:
        for el in root.iter():
            if el.tag.lower() == tag.lower() and el.text:
                return strip_html(el.text)
    return ""


def article_text(root: ET.Element) -> str:
    parts = []
    for el in root.iter():
        if el.text:
            parts.append(el.text)
        if el.tail:
            parts.append(el.tail)
    return strip_html(" ".join(parts))


def match_keywords(haystack_norm: str) -> list[str]:
    hits = []
    for tag, terms in KEYWORDS.items():
        for t in terms:
            if normalize(t) in haystack_norm:
                hits.append(tag)
                break
    return hits


def match_orgaos(haystack_norm: str) -> list[str]:
    return [o for o in PRIORITY_ORGAOS if normalize(o) in haystack_norm]


def parse_xml_file(path: Path) -> dict | None:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return {"_parse_error": f"{path.name}: {exc}"}
    root = tree.getroot()

    attrs = root.attrib if root.tag.lower() == "article" else {}
    if not attrs:
        art = next((e for e in root.iter() if e.tag.lower() == "article"), None)
        if art is not None:
            attrs = art.attrib

    identifica = extract_field(root, "Identifica", "identifica")
    ementa = extract_field(root, "Ementa", "ementa")
    titulo = extract_field(root, "Titulo", "titulo")
    subtitulo = extract_field(root, "SubTitulo", "subtitulo")
    orgao_xml = extract_field(root, "OrgaoDouSec", "Orgao", "orgao")
    assina = extract_field(root, "Assina", "assina")
    cargo = extract_field(root, "Cargo", "cargo")
    texto = extract_field(root, "Texto", "texto")

    pub_name = attrs.get("pubName") or attrs.get("pubname") or ""
    pub_date = attrs.get("pubDate") or attrs.get("pubdate") or ""
    art_type = attrs.get("artType") or attrs.get("arttype") or ""
    art_category = attrs.get("artCategory") or attrs.get("artcategory") or ""
    number_page = attrs.get("numberPage") or attrs.get("numberpage") or ""
    edition = attrs.get("editionNumber") or attrs.get("editionnumber") or ""
    id_oficio = attrs.get("idOficio") or attrs.get("idoficio") or ""
    art_id = attrs.get("id") or ""
    name_slug = attrs.get("name") or ""

    full_text = " ".join(filter(None, [identifica, ementa, titulo, subtitulo, orgao_xml,
                                       assina, cargo, texto, art_type, art_category,
                                       article_text(root)]))
    hay = normalize(full_text)

    kw_hits = match_keywords(hay)
    orgao_hits = match_orgaos(hay)
    if not kw_hits and not orgao_hits:
        return None

    url = ""
    if name_slug and id_oficio:
        url = f"https://www.in.gov.br/web/dou/-/{name_slug}-{id_oficio}"
    elif name_slug:
        url = f"https://www.in.gov.br/web/dou/-/{name_slug}"

    return {
        "id": art_id,
        "section": pub_name,
        "pub_date": pub_date,
        "art_type": art_type,
        "art_category": art_category,
        "identifica": identifica,
        "orgao": orgao_xml,
        "ementa": ementa or titulo,
        "titulo": titulo,
        "subtitulo": subtitulo,
        "texto_resumo": (strip_html(texto) or article_text(root))[:600],
        "assina": assina,
        "cargo": cargo,
        "page": number_page,
        "edition": edition,
        "url": url,
        "keywords_matched": sorted(set(kw_hits)),
        "orgaos_matched": sorted(set(orgao_hits)),
        "xml_file": path.name,
    }


def process_date(day_dir: Path, force: bool) -> dict:
    extracted = day_dir / "extracted"
    out_path = day_dir / "inlabs-filtered.json"
    if not extracted.exists():
        return {"date": day_dir.name, "status": "no_extracted_dir", "matches": 0}
    if out_path.exists() and not force:
        return {"date": day_dir.name, "status": "already_parsed", "matches": "?"}

    xmls = sorted(extracted.glob("*.xml"))
    if not xmls:
        return {"date": day_dir.name, "status": "no_xml_files", "matches": 0}

    matches: list[dict] = []
    parse_errors: list[str] = []
    for x in xmls:
        result = parse_xml_file(x)
        if result is None:
            continue
        if "_parse_error" in result:
            parse_errors.append(result["_parse_error"])
            continue
        matches.append(result)

    matches.sort(key=lambda m: (m.get("section", ""), m.get("art_type", ""), m.get("identifica", "")))

    payload = {
        "date": day_dir.name,
        "total_xml_files": len(xmls),
        "matched_articles": len(matches),
        "parse_errors": parse_errors,
        "keywords_dictionary": list(KEYWORDS.keys()),
        "priority_orgaos": PRIORITY_ORGAOS,
        "articles": matches,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"date": day_dir.name, "status": "ok", "matches": len(matches),
            "total": len(xmls), "errors": len(parse_errors)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="Data YYYY-MM-DD; se omitida, processa todas.")
    ap.add_argument("--force", action="store_true", help="Reprocessa mesmo se JSON já existe.")
    args = ap.parse_args()

    if args.date:
        day_dirs = [DOU_ROOT / args.date]
    else:
        if not DOU_ROOT.exists():
            sys.exit(f"Nenhum diretório de DOU encontrado em {DOU_ROOT}.")
        day_dirs = sorted(p for p in DOU_ROOT.iterdir() if p.is_dir())

    if not day_dirs or not day_dirs[0].exists():
        sys.exit(f"Nenhum diretório de data encontrado em {DOU_ROOT}.")

    for d in day_dirs:
        summary = process_date(d, args.force)
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
