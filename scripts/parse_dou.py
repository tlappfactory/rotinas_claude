#!/usr/bin/env python3
"""
parse_dou.py — filtra os XMLs do DOU baixados pelo fetch_inlabs.py por temas SGP/TRT-17.

Critérios de inclusão (combinados em OR):
  (a) Órgão EMISSOR (campo `OrgaoDouSec`/`artCategory` do XML) é um dos PRIORITY_ORGAOS_EMISSOR.
  (b) Texto da matéria contém pelo menos uma STRONG_KEYWORD (regex com fronteira de palavra).

Filtros negativos:
  - "17ª região" combinada com "CREF/CONFEF/Conselho Regional de Educação Física"
    → não é TRT-17.

Score heurístico:
  - +10 por órgão emissor prioritário
  - +5 por keyword forte
  - +1 por keyword fraca

Lê:    <DOU_ROOT>/<YYYY-MM-DD>/extracted/*.xml
Grava: <DOU_ROOT>/<YYYY-MM-DD>/inlabs-filtered.json (ordenado por score desc)
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

# Keywords FORTES — quase sempre sinalizam tema de pessoal/previdência/remuneração.
# Padrões regex aplicados sobre texto normalizado (sem acento, lowercase).
STRONG_KEYWORDS: dict[str, list[str]] = {
    "aposentadoria": [r"\baposentadoria\b", r"\baposentadorias\b", r"\baposentado\b",
                      r"\baposentada\b", r"\baposentados\b", r"\baposentadas\b"],
    "pensao": [r"\bpensao\b", r"\bpensoes\b", r"\bpensionista\b", r"\bpensionistas\b",
               r"\bpensao por morte\b"],
    "abono_permanencia": [r"\babono de permanencia\b"],
    "reversao_aposentado": [r"\breversao de aposentado\b", r"\breversao a atividade\b"],
    "averbacao_tempo": [r"\baverbacao de tempo\b", r"\bcontagem de tempo\b",
                        r"\btempo de contribuicao\b", r"\btempo ficto\b"],
    "acumulacao_cargos": [r"\bacumulacao de cargos\b", r"\bacumulo de cargos\b",
                          r"\bacumulacao licita\b"],
    "teto_remuneratorio": [r"\bteto remuneratorio\b", r"\bsubteto\b",
                           r"\bart\.?\s*37,?\s*xi\b", r"\bteto constitucional\b"],
    "isencao_ir": [r"\bisencao de imposto de renda\b", r"\bisencao do imposto de renda\b",
                   r"\bisencao do ir\b", r"\bmolestia grave\b"],
    "quintos_anuenios_ats": [r"\bquintos\b", r"\banuenios\b",
                             r"\badicional por tempo de servico\b", r"\bvpni\b",
                             r"\bvantagem pessoal nominalmente identificada\b"],
    "funpresp": [r"\bfunpresp\b", r"\bfunpresp-jud\b", r"\bprevidencia complementar\b"],
    "auxilios_pessoal": [r"\bauxilio-alimentacao\b", r"\bauxilio alimentacao\b",
                         r"\bauxilio pre-escolar\b", r"\bauxilio-saude\b",
                         r"\bauxilio saude\b", r"\bauxilio-transporte\b",
                         r"\bauxilio transporte\b", r"\bauxilio-funeral\b",
                         r"\bauxilio-natalidade\b"],
    "licenca_saude": [r"\blicenca para tratamento de saude\b",
                      r"\blicenca por motivo de doenca em pessoa da familia\b",
                      r"\bpessoa da familia\b"],
    "licencas_servidor": [r"\blicenca para capacitacao\b",
                          r"\blicenca para tratar de interesses particulares\b",
                          r"\blicenca-premio\b", r"\blicenca premio\b",
                          r"\blicenca por atividade politica\b",
                          r"\blicenca para mandato classista\b",
                          r"\bmandato classista\b", r"\breconducao\b"],
    "ajuda_custo_transporte": [r"\bajuda de custo\b", r"\bindenizacao de transporte\b"],
    "insalubridade_periculosidade": [r"\badicional de insalubridade\b",
                                     r"\badicional de periculosidade\b",
                                     r"\binsalubridade\b", r"\bpericulosidade\b"],
    "cessao_remocao_permuta": [r"\bcessao\b", r"\bcessoes\b", r"\bredistribuicao\b",
                                r"\bremocao\b", r"\bpermuta\b"],
}

# Keywords FRACAS — só ajudam na classificação; sozinhas NÃO bastam para incluir
# (precisam vir junto com órgão emissor prioritário).
WEAK_KEYWORDS: dict[str, list[str]] = {
    "substituicao_fc_cc": [r"\bsubstituicao\b", r"\bsubstituir\b", r"\bsubstituido\b",
                           r"\bfuncao comissionada\b", r"\bcargo em comissao\b",
                           r"\bcj-\d", r"\bfc-\d", r"\bcc-\d", r"\bfc \d", r"\bcc \d"],
    "competencias_capacitacao": [r"\bgestao por competencias\b", r"\bplano de capacitacao\b",
                                 r"\bavaliacao de desempenho\b", r"\benap\b", r"\benajud\b"],
    "teletrabalho_jornada": [r"\bteletrabalho\b", r"\btrabalho remoto\b",
                             r"\bjornada de trabalho\b",
                             r"\bcondicao especial de trabalho\b", r"\bbanco de horas\b"],
    "estagio_aprendizagem": [r"\bestagio\b", r"\bestagiario\b", r"\baprendizagem\b",
                             r"\bmenor aprendiz\b"],
    "folha_esocial": [r"\bfolha de pagamento\b", r"\besocial\b", r"\bconsignacoes\b",
                      r"\bconsignacao\b"],
}

# Órgãos prioritários — match contra `orgao_xml` + `artCategory` (NÃO no texto inteiro).
# Padrões substring sobre orgao normalizado.
PRIORITY_ORGAOS_EMISSOR: list[str] = [
    "csjt", "conselho superior da justica do trabalho",
    "tst", "tribunal superior do trabalho",
    "cnj", "conselho nacional de justica",
    "tcu", "tribunal de contas da uniao",
    "stf", "supremo tribunal federal",
    "stj", "superior tribunal de justica",
    "trt da 17", "tribunal regional do trabalho da 17",
    "secretaria de gestao e desempenho de pessoal", "sgdp", "decipex", "cgben",
    "ministerio da gestao",  # MGI — entra sempre que combinado com strong keyword
]

# Padrões que indicam que "17ª região" / "17a regiao" NÃO se refere ao TRT-17.
NEGATIVE_PATTERNS_NOT_TRT17: list[str] = [
    "cref", "confef", "conselho regional de educacao fisica",
    "conselho regional de medicina", "crm",
    "conselho regional de farmacia", "crf",
    "conselho regional de odontologia",
    "conselho regional de psicologia",
    "ordem dos advogados",
    "conselho federal de educacao fisica",
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
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


def article_full_text(root: ET.Element) -> str:
    parts = []
    for el in root.iter():
        if el.text:
            parts.append(el.text)
        if el.tail:
            parts.append(el.tail)
    return strip_html(" ".join(parts))


def match_patterns(text_norm: str, patterns_dict: dict[str, list[str]]) -> list[str]:
    hits = []
    for tag, patterns in patterns_dict.items():
        for p in patterns:
            if re.search(p, text_norm):
                hits.append(tag)
                break
    return hits


def match_orgao_emissor(orgao_norm: str, full_text_norm: str) -> list[str]:
    """Match priority orgaos against orgao field (cabeçalho hierárquico do DOU).
    Aplica filtro negativo TRT-17 vs CREF/CONFEF/etc."""
    hits = [o for o in PRIORITY_ORGAOS_EMISSOR if o in orgao_norm]
    # Filtro negativo: se "17" e há indicação de Conselho Regional, remove o TRT-17
    if any("17" in h for h in hits):
        if any(neg in orgao_norm or neg in full_text_norm
               for neg in NEGATIVE_PATTERNS_NOT_TRT17):
            hits = [h for h in hits if "17" not in h]
    return hits


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

    # Texto completo (para casamento de keywords)
    full_text = " ".join(filter(None, [identifica, ementa, titulo, subtitulo, orgao_xml,
                                       assina, cargo, texto, article_full_text(root)]))
    text_norm = normalize(full_text)
    # Cabeçalho hierárquico do órgão emissor (NÃO texto completo)
    orgao_norm = normalize(orgao_xml + " " + art_category)

    orgao_hits = match_orgao_emissor(orgao_norm, text_norm)
    strong_hits = match_patterns(text_norm, STRONG_KEYWORDS)
    weak_hits = match_patterns(text_norm, WEAK_KEYWORDS)

    # Critério de inclusão: órgão emissor prioritário OU keyword forte
    if not orgao_hits and not strong_hits:
        return None

    score = 10 * len(orgao_hits) + 5 * len(strong_hits) + 1 * len(weak_hits)

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
        "texto_resumo": (strip_html(texto) or article_full_text(root))[:600],
        "assina": assina,
        "cargo": cargo,
        "page": number_page,
        "edition": edition,
        "url": url,
        "orgao_emissor_hits": orgao_hits,
        "strong_keywords": sorted(set(strong_hits)),
        "weak_keywords": sorted(set(weak_hits)),
        "score": score,
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

    matches.sort(key=lambda m: (-m["score"], m.get("section", ""),
                                m.get("art_type", ""), m.get("identifica", "")))

    payload = {
        "date": day_dir.name,
        "total_xml_files": len(xmls),
        "matched_articles": len(matches),
        "parse_errors": parse_errors,
        "strong_keyword_tags": list(STRONG_KEYWORDS.keys()),
        "weak_keyword_tags": list(WEAK_KEYWORDS.keys()),
        "priority_orgaos": PRIORITY_ORGAOS_EMISSOR,
        "articles": matches,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"date": day_dir.name, "status": "ok", "matches": len(matches),
            "total": len(xmls), "errors": len(parse_errors)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="Data YYYY-MM-DD; se omitida, processa todas.")
    ap.add_argument("--force", action="store_true",
                    help="Reprocessa mesmo se JSON já existe.")
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
