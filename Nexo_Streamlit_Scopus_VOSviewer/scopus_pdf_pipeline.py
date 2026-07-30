#!/usr/bin/env python3
"""
Pipeline reprodutível: PDFs de artigos -> CSV no formato Scopus/VOSviewer.

O programa trabalha em duas passagens:

1. ``extract`` extrai metadados e referências dos PDFs, limpa ruídos e cria
   uma planilha CSV de revisão.
2. ``build`` usa a revisão (eventualmente corrigida por uma pessoa) para gerar
   o CSV final com as 45 colunas de uma exportação Scopus.

Também existe ``run``, que executa as duas passagens automaticamente. Para um
corpus científico real, recomenda-se sempre conferir ``referencias_revisao.csv``
antes de executar ``build``: PDFs usam estilos e layouts diferentes e nenhuma
expressão regular é capaz de reconstruir com segurança todas as referências.

Formato final de cada referência:
    Autor(es), título, fonte, (ano)

Regras para o VOSviewer:
    - vírgula separa coautores e campos dentro de uma obra;
    - ponto e vírgula separa apenas referências completas;
    - DOI, URL, ISBN, volume, número e páginas são removidos;
    - uma referência ambígua fica marcada para revisão, não é completada por
      suposição.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Instale as dependências: pip install -r requirements.txt") from exc


SCOPUS_COLUMNS = [
    "Authors", "Author full names", "Author(s) ID", "Title", "Year",
    "Source title", "Volume", "Issue", "Art. No.", "Page start", "Page end",
    "Cited by", "DOI", "Link", "Affiliations", "Authors with affiliations",
    "Abstract", "Author Keywords", "Index Keywords",
    "Molecular Sequence Numbers", "Chemicals/CAS", "Tradenames",
    "Manufacturers", "Funding Details", "Funding Texts", "References",
    "Correspondence Address", "Editors", "Publisher", "Sponsors",
    "Conference name", "Conference date", "Conference location",
    "Conference code", "ISSN", "ISBN", "CODEN", "PubMed ID",
    "Language of Original Document", "Abbreviated Source Title",
    "Document Type", "Publication Stage", "Open Access", "Source", "EID",
]

REVIEW_COLUMNS = [
    "article_id", "pdf_file", "reference_order", "reference_original",
    "authors", "title", "source", "year", "reference_standardized",
    "document_type", "status", "warnings", "include",
]

NOISE_LINE_PATTERNS = [
    r"^\s*\d+\s*$",
    r"^\s*\d+\s+(?:of|de)\s+\d+\s*$",
    r"^\s*(?:refer[eê]ncias(?: bibliogr[aá]ficas)?|references)\s*$",
    r"^\s*(?:received|accepted|approved|recebido|aprovado|submetido)\b",
    r"^\s*(?:como citar|how to cite|creative commons|this work is licensed)\b",
    r"^\s*(?:issn|e-issn|doi)\s*:",
    r"^\s*(?:copyright|©)\b",
]

STOP_SECTION_PATTERNS = [
    r"^\s*(?:notas|notes|agradecimentos|acknowledg(?:e)?ments)\s*$",
    r"^\s*(?:contribui[cç][aã]o de autoria|credit author statement)\b",
    r"^\s*(?:como citar|how to cite)\b",
]

FORBIDDEN = re.compile(
    r"https?://|www\.|\bdoi\b|\b10\.\d{4,9}/|\bisbn\b|"
    r"\b(?:v\.|vol\.|volume|n\.|no\.|issue|p\.|pp\.)\s*\d",
    re.I,
)

YEAR_RE = re.compile(r"(?<!\d)((?:18|19|20)\d{2})[a-z]?(?!\d)")


@dataclass
class Reference:
    article_id: str
    pdf_file: str
    reference_order: int
    reference_original: str
    authors: str = ""
    title: str = ""
    source: str = ""
    year: str = ""
    reference_standardized: str = ""
    document_type: str = "unknown"
    status: str = "review"
    warnings: str = ""
    include: str = "yes"


def compact(value: object) -> str:
    """Normaliza espaços e caracteres invisíveis sem remover acentos."""
    text = "" if value is None else str(value)
    text = text.replace("\u00ad", "").replace("\u00a0", " ")
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def stable_article_id(path: Path) -> str:
    digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:10]
    return f"ART-{digest}"


def extract_pdf_text(path: Path) -> tuple[str, list[str]]:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise ValueError("PDF criptografado e não pôde ser desbloqueado") from exc
        if not unlocked:
            raise ValueError("PDF protegido por senha")
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages), pages


def find_reference_section(text: str) -> str:
    matches = list(
        re.finditer(
            r"(?im)^\s*(?:refer[eê]ncias(?: bibliogr[aá]ficas)?|references)\s*$",
            text,
        )
    )
    if not matches:
        return ""
    return text[matches[-1].end():]


def is_noise_line(line: str) -> bool:
    return any(re.search(pattern, line, re.I) for pattern in NOISE_LINE_PATTERNS)


def is_stop_line(line: str) -> bool:
    return any(re.search(pattern, line, re.I) for pattern in STOP_SECTION_PATTERNS)


def line_starts_reference(line: str) -> bool:
    """Reconhece inícios comuns em APA, ABNT e autoria institucional."""
    line = compact(line)
    if not line:
        return False
    institution = (
        r"^(?:Brasil|Portugal|Australia|Austrália|UNESCO|OECD|OCDE|NCTM|"
        r"INEP|IBGE|Minist[eé]rio|Conselho|American Statistical Association)\b"
    )
    apa = (
        r"^[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+(?:\s+(?:da|de|do|dos|del|"
        r"van|von))?(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+)?,"
    )
    abnt = (
        r"^[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’\-]{1,}(?:\s+(?:DA|DE|DO|DAS|DOS|"
        r"NETO|FILHO|J[ÚU]NIOR))*[,.;]"
    )
    return bool(
        re.match(institution, line, re.I)
        or re.match(abnt, line)
        or (
            re.match(apa, line)
            and re.search(r"\((?:18|19|20)\d{2}[a-z]?\)", line[:240], re.I)
        )
    )


def segment_references(section: str) -> list[str]:
    lines = []
    for raw in section.splitlines():
        line = compact(raw.lstrip("\f"))
        if is_stop_line(line):
            break
        if not line or is_noise_line(line):
            continue
        lines.append(line)

    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        starts = line_starts_reference(line)
        current_text = compact(" ".join(current))
        current_has_year = bool(YEAR_RE.search(current_text))
        if starts and current and current_has_year:
            blocks.append(current_text)
            current = [line]
        elif current:
            current.append(line)
        elif starts:
            current = [line]
    if current:
        blocks.append(compact(" ".join(current)))
    return [block for block in blocks if len(block) >= 20]


def remove_urls_and_details(value: str) -> str:
    value = compact(value)
    value = re.sub(r"\bhttps?://\S+|\bwww\.\S+", "", value, flags=re.I)
    value = re.sub(r"\bdoi\s*:?\s*\S+|\b10\.\d{4,9}/\S+", "", value, flags=re.I)
    value = re.sub(r"\bisbn(?:-1[03])?\s*:?\s*[\dXx\-– ]+", "", value, flags=re.I)
    value = re.sub(r"\bdispon[ií]vel em\s*:.*$", "", value, flags=re.I)
    value = re.sub(r"\bacesso em\s*:.*$", "", value, flags=re.I)
    value = re.sub(
        r",?\s*(?:v\.|vol\.|volume)\s*[\w\-–]+"
        r"(?:\s*,?\s*(?:n\.|no\.|issue)\s*[\w\-–]+)?"
        r"(?:\s*,?\s*(?:p\.|pp\.)\s*[\w\-–]+)?",
        "", value, flags=re.I,
    )
    value = re.sub(r",?\s*(?:n\.|no\.|issue)\s*[\w\-–]+", "", value, flags=re.I)
    value = re.sub(r",?\s*(?:p\.|pp\.)\s*\d+(?:\s*[-–]\s*\d+)?", "", value, flags=re.I)
    value = re.sub(r",?\s*\d+\s*\(\s*\d+\s*\)\s*:?\s*\d+(?:\s*[-–]\s*\d+)?", "", value)
    value = re.sub(r"\s+,", ",", value)
    value = re.sub(r",(?:\s*,)+", ",", value)
    return compact(value).strip(" ,.;")


def detect_style(ref: str) -> str:
    if re.search(r"\((?:18|19|20)\d{2}[a-z]?\)", ref[:240]):
        return "apa"
    return "abnt"


def extract_year(ref: str) -> str:
    years = YEAR_RE.findall(ref)
    return years[-1] if years else ""


def extract_author_block(ref: str, style: str, year: str) -> str:
    if style == "apa" and year:
        match = re.match(rf"^(.+?)\s*\(\s*{re.escape(year)}[a-z]?\s*\)", ref)
        if match:
            return compact(match.group(1)).strip(" .;")
    match = re.match(r"^(.+?)\.\s+(?=[A-ZÀ-ÖØ-Þ0-9“\"(])", ref)
    return compact(match.group(1)).strip(" .;") if match else ""


def initials(given: str) -> str:
    letters = re.findall(r"(?<!\w)[A-ZÀ-ÖØ-Þ]", given.upper())
    return " ".join(f"{letter}." for letter in letters)


def normalize_person(name: str) -> str:
    name = compact(name).strip(" .;,")
    if not name:
        return ""
    if "," in name:
        surname, given = [compact(x) for x in name.split(",", 1)]
        ini = initials(given)
        return compact(f"{surname.title()} {ini}") if ini else surname.title()
    # Nomes institucionais devem permanecer inteiros.
    if len(name.split()) > 5 or name.isupper() and " " in name:
        return name.title()
    return name


def normalize_authors(block: str) -> str:
    """Produz autores separados por vírgula, nunca por ponto e vírgula."""
    block = compact(block)
    if not block:
        return ""
    block = re.sub(r"\bet\s+al\.?", "", block, flags=re.I).strip(" ,.;")
    people = re.split(r"\s*;\s*|\s+&\s+|\s+\band\b\s+|\s+\be\b\s+|\s+\by\b\s+", block, flags=re.I)
    normalized = [normalize_person(person) for person in people]
    return ", ".join(person for person in normalized if person).replace(";", ",")


def remove_opening_and_year(ref: str, author_block: str, year: str) -> str:
    body = compact(ref)
    if author_block and body.startswith(author_block):
        body = body[len(author_block):].lstrip(" .;,")
    if year:
        body = re.sub(rf"^\(\s*{re.escape(year)}[a-z]?\s*\)\.?\s*", "", body)
        body = re.sub(rf"[,.;:\s]*\(?{re.escape(year)}\)?\.?\s*$", "", body)
    return remove_urls_and_details(body)


def detect_document_type(body: str) -> str:
    low = fold(body)
    if "tese" in low or "doctoral thesis" in low:
        return "thesis"
    if "dissertacao" in low or "master s thesis" in low:
        return "dissertation"
    if re.search(r"\b(?:in:|anais|proceedings)\b", body, re.I):
        return "chapter_or_event"
    if re.search(r"\b(?:lei|decreto|resolu[cç][aã]o|curriculum|diretrizes)\b", body, re.I):
        return "official_document"
    if re.search(r"\b(?:journal|revista|education|educa[cç][aã]o|teaching)\b", body, re.I):
        return "article_or_book"
    return "unknown"


def split_title_source(body: str, document_type: str) -> tuple[str, str]:
    body = compact(body).strip(" .;,")
    if not body:
        return "", ""

    if document_type in {"thesis", "dissertation"}:
        parts = re.split(
            r"\.\s+(?=(?:Tese|Disserta[cç][aã]o|Doctoral thesis|Master.?s thesis))",
            body, maxsplit=1, flags=re.I,
        )
        if len(parts) == 2:
            institution = re.split(r"[–-]", parts[1])[-1]
            return compact(parts[0]), compact(institution).strip(" .;,")

    if document_type == "chapter_or_event":
        parts = re.split(r"\.\s+(?=(?:In:|Anais|Proceedings))", body, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return compact(parts[0]), compact(re.sub(r"^In:\s*", "", parts[1], flags=re.I))

    # Em referências de artigos e livros, o primeiro ponto após o título é a
    # divisão mais conservadora. Se não existir, a referência fica para revisão.
    parts = re.split(r"\.\s+", body, maxsplit=1)
    if len(parts) == 2:
        title, source = parts
        source = re.split(
            r",\s*(?:v\.|vol\.|volume|n\.|no\.|issue|p\.|pp\.|\d+\s*\()",
            source, maxsplit=1, flags=re.I,
        )[0]
        return compact(title).strip(" .;,"), compact(source).strip(" .;,")
    return body, ""


def build_minimal(authors: str, title: str, source: str, year: str) -> str:
    # ``remove_urls_and_details`` remove pontuação terminal; nas autorias isso
    # apagaria o ponto da última inicial (``Moore D. S.``). Recolocamos o ponto
    # quando o bloco termina em uma inicial.
    clean_authors = remove_urls_and_details(authors).replace(";", ",")
    if re.search(r"(?:^|[\s,])[A-ZÀ-ÖØ-Þ]$", clean_authors):
        clean_authors += "."
    values = [
        clean_authors,
        remove_urls_and_details(title).replace(";", ","),
        remove_urls_and_details(source).replace(";", ","),
    ]
    result = ", ".join(value for value in values if value)
    if year:
        result = f"{result}, ({year})"
    return re.sub(r"\s+,", ",", compact(result)).strip(" ,.;")


def parse_reference(article_id: str, pdf_file: str, order: int, raw: str) -> Reference:
    style = detect_style(raw)
    year = extract_year(raw)
    author_block = extract_author_block(raw, style, year)
    authors = normalize_authors(author_block)
    body = remove_opening_and_year(raw, author_block, year)
    document_type = detect_document_type(body)
    title, source = split_title_source(body, document_type)
    standardized = build_minimal(authors, title, source, year)

    warnings = []
    if not authors:
        warnings.append("missing_authors")
    if not title:
        warnings.append("missing_title")
    if not source:
        warnings.append("missing_source")
    if not year:
        warnings.append("missing_year")
    if FORBIDDEN.search(standardized):
        warnings.append("forbidden_detail")
    if ";" in standardized:
        warnings.append("internal_semicolon")
    status = "ok" if not warnings else "review"

    return Reference(
        article_id=article_id,
        pdf_file=pdf_file,
        reference_order=order,
        reference_original=raw,
        authors=authors,
        title=title,
        source=source,
        year=year,
        reference_standardized=standardized,
        document_type=document_type,
        status=status,
        warnings=";".join(warnings),
    )


def guess_article_metadata(path: Path, pages: list[str]) -> dict[str, str]:
    first = compact(pages[0] if pages else "")
    doi_match = re.search(r"\b10\.\d{4,9}/[^\s<>\";,]+", first, re.I)
    year_match = YEAR_RE.search(first)
    title_lines = [
        compact(line) for line in (pages[0].splitlines() if pages else [])
        if 20 <= len(compact(line)) <= 250 and not is_noise_line(compact(line))
    ]
    title = max(title_lines[:30], key=len, default=path.stem)
    return {
        "pdf_file": path.name,
        "article_id": stable_article_id(path),
        "Authors": "",
        "Author full names": "",
        "Title": title,
        "Year": year_match.group(1) if year_match else "",
        "Source title": "",
        "DOI": doi_match.group(0).rstrip(".") if doi_match else "",
        "Abstract": "",
        "Author Keywords": "",
        "Language of Original Document": "",
    }


def read_metadata_csv(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        filename = compact(row.get("pdf_file", ""))
        if not filename:
            raise ValueError("O CSV de metadados precisa da coluna pdf_file.")
        result[filename] = {key: compact(value) for key, value in row.items()}
    return result


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=columns, extrasaction="ignore", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(rows)


def load_review(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing = [column for column in REVIEW_COLUMNS if column not in (rows[0] if rows else {})]
    if missing:
        raise ValueError(f"Colunas ausentes na revisão: {', '.join(missing)}")
    return rows


def validate_review(rows: list[dict[str, str]], strict: bool) -> list[dict[str, str]]:
    errors = []
    cleaned = []
    for position, row in enumerate(rows, start=2):
        if fold(row.get("include", "yes")) in {"no", "nao", "0", "false"}:
            continue
        authors = compact(row.get("authors", "")).replace(";", ",")
        title = compact(row.get("title", "")).replace(";", ",")
        source = compact(row.get("source", "")).replace(";", ",")
        year = compact(row.get("year", ""))
        reference = build_minimal(authors, title, source, year)
        row = dict(row)
        row.update(
            authors=authors,
            title=title,
            source=source,
            year=year,
            reference_standardized=reference,
        )
        row_errors = []
        if not all([authors, title, source, year]):
            row_errors.append("missing_required_field")
        if not re.fullmatch(r"(?:18|19|20)\d{2}", year):
            row_errors.append("invalid_year")
        if FORBIDDEN.search(reference):
            row_errors.append("forbidden_detail")
        if ";" in reference:
            row_errors.append("internal_semicolon")
        if row_errors:
            errors.append(
                {
                    "csv_line": position,
                    "article_id": row.get("article_id", ""),
                    "reference_order": row.get("reference_order", ""),
                    "errors": ";".join(row_errors),
                    "reference": reference,
                }
            )
        row["status"] = "ok" if not row_errors else "review"
        row["warnings"] = ";".join(row_errors)
        cleaned.append(row)
    if strict and errors:
        raise ValueError(
            f"{len(errors)} referências ainda exigem revisão; veja auditoria_erros.csv."
        )
    return cleaned


def extract_command(pdf_dir: Path, output_dir: Path, metadata_csv: Path | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    supplied = read_metadata_csv(metadata_csv)
    pdfs = sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())
    if not pdfs:
        raise FileNotFoundError(f"Nenhum PDF encontrado em {pdf_dir}")

    article_rows = []
    reference_rows: list[Reference] = []
    extraction_audit = []

    for pdf in pdfs:
        try:
            text, pages = extract_pdf_text(pdf)
        except Exception as exc:
            extraction_audit.append(
                {
                    "article_id": stable_article_id(pdf),
                    "pdf_file": pdf.name,
                    "pages": "",
                    "processing_status": "error",
                    "processing_error": str(exc),
                    "reference_heading_found": "no",
                    "references_segmented": 0,
                    "references_ok": 0,
                    "references_review": 0,
                }
            )
            continue
        guessed = guess_article_metadata(pdf, pages)
        provided = supplied.get(pdf.name, {})
        guessed.update({key: value for key, value in provided.items() if value})
        article_id = guessed.get("article_id") or stable_article_id(pdf)
        guessed["article_id"] = article_id
        guessed["pdf_file"] = pdf.name
        article_rows.append(guessed)

        section = find_reference_section(text)
        blocks = segment_references(section) if section else []
        for order, block in enumerate(blocks, start=1):
            reference_rows.append(parse_reference(article_id, pdf.name, order, block))
        extraction_audit.append(
            {
                "article_id": article_id,
                "pdf_file": pdf.name,
                "pages": len(pages),
                "processing_status": "ok",
                "processing_error": "",
                "reference_heading_found": "yes" if section else "no",
                "references_segmented": len(blocks),
                "references_ok": sum(
                    1 for item in reference_rows
                    if item.article_id == article_id and item.status == "ok"
                ),
                "references_review": sum(
                    1 for item in reference_rows
                    if item.article_id == article_id and item.status != "ok"
                ),
            }
        )

    if not article_rows:
        details = "; ".join(
            f"{row['pdf_file']}: {row['processing_error']}"
            for row in extraction_audit
        )
        raise RuntimeError(f"Nenhum PDF pôde ser processado. {details}")

    article_columns = ["article_id", "pdf_file"] + [
        col for col in SCOPUS_COLUMNS if col != "References"
    ]
    write_csv(output_dir / "artigos_metadados.csv", article_columns, article_rows)
    write_csv(
        output_dir / "referencias_revisao.csv",
        REVIEW_COLUMNS,
        [asdict(item) for item in reference_rows],
    )
    write_csv(
        output_dir / "auditoria_extracao.csv",
        list(extraction_audit[0]),
        extraction_audit,
    )
    print(f"PDFs: {len(pdfs)}")
    print(f"Referências segmentadas: {len(reference_rows)}")
    print(f"Revisar: {sum(item.status != 'ok' for item in reference_rows)}")
    print(f"Saída: {output_dir}")


def build_command(
    article_csv: Path,
    review_csv: Path,
    output_dir: Path,
    strict: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with article_csv.open(encoding="utf-8-sig", newline="") as handle:
        articles = list(csv.DictReader(handle))
    review_original = load_review(review_csv)

    try:
        review = validate_review(review_original, strict=False)
    except Exception:
        raise
    error_rows = [
        {
            "csv_line": index + 2,
            "article_id": row.get("article_id", ""),
            "reference_order": row.get("reference_order", ""),
            "errors": row.get("warnings", ""),
            "reference": row.get("reference_standardized", ""),
        }
        for index, row in enumerate(review)
        if row.get("status") != "ok"
    ]
    write_csv(
        output_dir / "auditoria_erros.csv",
        ["csv_line", "article_id", "reference_order", "errors", "reference"],
        error_rows,
    )
    if strict and error_rows:
        raise ValueError(
            f"{len(error_rows)} referências ainda exigem revisão. "
            f"Corrija {review_csv} usando {output_dir / 'auditoria_erros.csv'}."
        )

    by_article: dict[str, list[dict[str, str]]] = {}
    for row in review:
        by_article.setdefault(row["article_id"], []).append(row)
    for rows in by_article.values():
        rows.sort(key=lambda x: int(x.get("reference_order") or 0))

    scopus_rows = []
    for article in articles:
        article_id = article.get("article_id", "")
        row = {column: compact(article.get(column, "")) for column in SCOPUS_COLUMNS}
        references = [
            item["reference_standardized"]
            for item in by_article.get(article_id, [])
            if item["reference_standardized"] and (not strict or item["status"] == "ok")
        ]
        row["References"] = "; ".join(references)
        row["Document Type"] = row["Document Type"] or "Article"
        row["Publication Stage"] = row["Publication Stage"] or "Final"
        row["Source"] = row["Source"] or "PDF corpus"
        scopus_rows.append(row)

    if len(scopus_rows) != len(articles):
        raise AssertionError("A quantidade de artigos mudou durante a exportação.")
    if any(";;" in row["References"] for row in scopus_rows):
        raise AssertionError("Separador duplicado detectado.")

    write_csv(output_dir / "corpus_scopus_vosviewer.csv", SCOPUS_COLUMNS, scopus_rows)
    write_csv(output_dir / "referencias_padronizadas.csv", REVIEW_COLUMNS, review)

    summary = {
        "articles": len(scopus_rows),
        "references_included": len(review),
        "references_ok": sum(row["status"] == "ok" for row in review),
        "references_review": sum(row["status"] != "ok" for row in review),
        "scopus_columns": len(SCOPUS_COLUMNS),
        "format": "Autor(es), título, fonte, (ano)",
        "strict": strict,
    }
    (output_dir / "resumo.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"CSV Scopus: {output_dir / 'corpus_scopus_vosviewer.csv'}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrai PDFs e gera CSV Scopus/VOSviewer com referências mínimas."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract_p = sub.add_parser("extract", help="Extrai PDFs e cria CSVs para revisão.")
    extract_p.add_argument("--pdf-dir", type=Path, required=True)
    extract_p.add_argument("--output-dir", type=Path, required=True)
    extract_p.add_argument("--metadata-csv", type=Path)

    build_p = sub.add_parser("build", help="Gera o CSV Scopus a partir da revisão.")
    build_p.add_argument("--articles", type=Path, required=True)
    build_p.add_argument("--references", type=Path, required=True)
    build_p.add_argument("--output-dir", type=Path, required=True)
    build_p.add_argument(
        "--allow-review",
        action="store_true",
        help="Exporta mesmo com referências incompletas (não recomendado).",
    )

    run_p = sub.add_parser("run", help="Executa extração e construção automática.")
    run_p.add_argument("--pdf-dir", type=Path, required=True)
    run_p.add_argument("--output-dir", type=Path, required=True)
    run_p.add_argument("--metadata-csv", type=Path)
    run_p.add_argument(
        "--allow-review",
        action="store_true",
        help="Exporta mesmo com referências incompletas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "extract":
            extract_command(args.pdf_dir, args.output_dir, args.metadata_csv)
        elif args.command == "build":
            build_command(
                args.articles, args.references, args.output_dir,
                strict=not args.allow_review,
            )
        elif args.command == "run":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            extract_command(args.pdf_dir, args.output_dir, args.metadata_csv)
            build_command(
                args.output_dir / "artigos_metadados.csv",
                args.output_dir / "referencias_revisao.csv",
                args.output_dir,
                strict=not args.allow_review,
            )
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
