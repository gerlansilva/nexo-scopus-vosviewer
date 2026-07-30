from scopus_pdf_pipeline import parse_reference, segment_references


def test_abnt_uses_publication_year_and_preserves_coauthors():
    raw = (
        "SANTOS, R. M. dos; SILVA, A. B. Título da obra. "
        "Revista Exemplo, v. 2, n. 1, p. 1-10, 2014. "
        "Disponível em: http://example.org. Acesso em: 22 set. 2016."
    )
    ref = parse_reference("A", "artigo.pdf", 1, raw)
    assert ref.year == "2014"
    assert ref.authors == "Santos R. M., Silva A. B."
    assert ref.title == "Título da obra"
    assert ref.source == "Revista Exemplo"
    assert ref.status == "ok"


def test_apa_preserves_both_authors():
    raw = (
        "Cobb, G. W., & Moore, D. S. (1997). Mathematics, statistics, "
        "and teaching. The American Mathematical Monthly, 104(9), 801–823."
    )
    ref = parse_reference("A", "artigo.pdf", 1, raw)
    assert ref.authors == "Cobb G. W., Moore D. S."
    assert ref.year == "1997"


def test_repeated_author_dash_becomes_new_reference():
    section = (
        "Cobb, G. W., & Moore, D. S. (1997). First title. First Journal.\n"
        "——. (2001). Second title. Second Journal."
    )
    blocks = segment_references(section)
    assert len(blocks) == 2
    assert blocks[1].startswith("Cobb, G. W., & Moore, D. S.")


def test_et_al_requires_review():
    raw = "FIORENTINI, D. et al. Formação de professores. Educação em Revista, 2002."
    ref = parse_reference("A", "artigo.pdf", 1, raw)
    assert ref.status == "review"
    assert "truncated_authors" in ref.warnings
