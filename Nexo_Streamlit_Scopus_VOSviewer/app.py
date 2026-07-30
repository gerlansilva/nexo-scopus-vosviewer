from __future__ import annotations

import base64
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from scopus_pdf_pipeline import (
    REVIEW_COLUMNS,
    build_command,
    extract_command,
    validate_review,
)


APP_DIR = Path(__file__).parent
LOGO_PATH = APP_DIR / "assets" / "logo.svg"

st.set_page_config(
    page_title="Nexo — PDFs para Scopus",
    page_icon=str(LOGO_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap');

        :root {
          --ink: #17332f;
          --muted: #667773;
          --paper: #fbfcf9;
          --line: #dfe7e2;
          --sage: #e8f0eb;
          --coral: #e66d50;
          --green: #1f5b50;
        }
        .stApp { background: var(--paper); color: var(--ink); }
        .block-container { max-width: 1180px; padding: 2.2rem 2.2rem 5rem; }
        header[data-testid="stHeader"] { background: transparent; }
        #MainMenu, footer { visibility: hidden; }
        h1, h2, h3 { color: var(--ink); letter-spacing: -0.03em; }
        h1, h2 { font-family: "Newsreader", Georgia, serif !important; }
        p, label, button, input, textarea, [data-testid="stMetricValue"] {
          font-family: "DM Sans", sans-serif !important;
        }
        .nexo-header {
          display: flex; align-items: center; justify-content: space-between;
          padding-bottom: 1.25rem; border-bottom: 1px solid var(--line);
          margin-bottom: 2.4rem;
        }
        .nexo-brand { display: flex; align-items: center; gap: .8rem; }
        .nexo-brand img { width: 42px; height: 42px; }
        .nexo-wordmark { font: 600 1.28rem/1 "DM Sans", sans-serif; color: var(--ink); }
        .nexo-tag { font: 500 .72rem/1 "DM Sans", sans-serif; color: var(--muted);
          letter-spacing: .08em; text-transform: uppercase; margin-top: .35rem; }
        .nexo-version { color: var(--muted); font: 500 .78rem "DM Sans", sans-serif; }
        .hero { max-width: 820px; margin: 0 0 2.4rem; }
        .eyebrow { color: var(--coral); font: 700 .74rem "DM Sans", sans-serif;
          letter-spacing: .12em; text-transform: uppercase; margin-bottom: .8rem; }
        .hero h1 { font-size: clamp(2.55rem, 5vw, 4.75rem); line-height: .98;
          font-weight: 500; margin: 0 0 1rem; }
        .hero p { color: var(--muted); font: 400 1.05rem/1.7 "DM Sans", sans-serif;
          max-width: 720px; margin: 0; }
        .stepbar { display: grid; grid-template-columns: repeat(3,1fr); gap: .7rem;
          margin: 1.8rem 0 1.2rem; }
        .step { border-top: 2px solid var(--line); padding: .7rem .1rem 0;
          color: var(--muted); font: 600 .78rem "DM Sans", sans-serif; }
        .step.active { border-color: var(--coral); color: var(--ink); }
        .step.done { border-color: var(--green); color: var(--green); }
        div[data-testid="stFileUploader"] {
          background: white; border: 1px solid var(--line); border-radius: 18px;
          padding: .55rem;
        }
        div[data-testid="stFileUploaderDropzone"] {
          border: 1px dashed #9fb3aa; background: #f7faf7; border-radius: 13px;
          min-height: 150px;
        }
        div[data-testid="stMetric"] {
          background: white; border: 1px solid var(--line); border-radius: 14px;
          padding: 1rem 1.1rem;
        }
        div[data-testid="stMetricValue"] { color: var(--ink); }
        .stButton > button, .stDownloadButton > button {
          border-radius: 999px; border: 1px solid var(--green); font-weight: 700;
          min-height: 43px; padding: 0 1.35rem;
        }
        .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
          background: var(--green); color: white;
        }
        .stButton > button[kind="primary"]:hover,
        .stDownloadButton > button[kind="primary"]:hover {
          background: #16483f; border-color: #16483f;
        }
        [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
        div[data-testid="stAlert"] { border-radius: 12px; }
        .note { background: var(--sage); border-radius: 14px; padding: 1rem 1.1rem;
          color: #35544d; font: 500 .86rem/1.55 "DM Sans", sans-serif; }
        .format-chip { display: inline-block; margin-top: .8rem; padding: .48rem .72rem;
          background: white; border: 1px solid var(--line); border-radius: 8px;
          color: var(--ink); font: 600 .82rem "DM Sans", monospace; }
        @media (max-width: 700px) {
          .block-container { padding: 1.2rem 1rem 3rem; }
          .stepbar { grid-template-columns: 1fr; }
          .nexo-version { display:none; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def svg_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{payload}"


def header() -> None:
    st.markdown(
        f"""
        <div class="nexo-header">
          <div class="nexo-brand">
            <img src="{svg_data_uri(LOGO_PATH)}" alt="Nexo">
            <div>
              <div class="nexo-wordmark">Nexo</div>
              <div class="nexo-tag">referências científicas</div>
            </div>
          </div>
          <div class="nexo-version">PDF → Scopus / VOSviewer</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def steps(active: int) -> None:
    labels = ["1. Enviar artigos", "2. Revisar referências", "3. Exportar base"]
    items = []
    for index, label in enumerate(labels, start=1):
        status = "done" if index < active else "active" if index == active else ""
        items.append(f'<div class="step {status}">{label}</div>')
    st.markdown(f'<div class="stepbar">{"".join(items)}</div>', unsafe_allow_html=True)


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def reset_project() -> None:
    for key in [
        "articles_df", "review_df", "audit_df", "final_files", "source_names",
        "failed_pdfs",
    ]:
        st.session_state.pop(key, None)


def extract_uploads(files) -> None:
    with tempfile.TemporaryDirectory(prefix="nexo_extract_") as tmp:
        root = Path(tmp)
        pdf_dir = root / "pdfs"
        output_dir = root / "result"
        pdf_dir.mkdir()
        for uploaded in files:
            safe_name = Path(uploaded.name).name
            (pdf_dir / safe_name).write_bytes(uploaded.getvalue())
        extract_command(pdf_dir, output_dir, None)
        st.session_state.articles_df = pd.read_csv(
            output_dir / "artigos_metadados.csv", dtype=str, keep_default_na=False
        )
        st.session_state.review_df = pd.read_csv(
            output_dir / "referencias_revisao.csv", dtype=str, keep_default_na=False
        )
        st.session_state.audit_df = pd.read_csv(
            output_dir / "auditoria_extracao.csv", dtype=str, keep_default_na=False
        )
        audit = st.session_state.audit_df
        st.session_state.failed_pdfs = audit.loc[
            audit["processing_status"].eq("error"),
            ["pdf_file", "processing_error"],
        ].to_dict("records")
        st.session_state.source_names = [file.name for file in files]
        st.session_state.pop("final_files", None)


def build_outputs(review_df: pd.DataFrame) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="nexo_build_") as tmp:
        root = Path(tmp)
        articles_path = root / "artigos_metadados.csv"
        review_path = root / "referencias_revisao.csv"
        output_dir = root / "final"
        st.session_state.articles_df.to_csv(
            articles_path, index=False, encoding="utf-8-sig", quoting=1
        )
        review_df.to_csv(review_path, index=False, encoding="utf-8-sig", quoting=1)
        build_command(articles_path, review_path, output_dir, strict=True)
        result = {}
        for path in output_dir.iterdir():
            if path.is_file():
                result[path.name] = path.read_bytes()
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in result.items():
                archive.writestr(name, content)
        result["Nexo_resultados.zip"] = bundle.getvalue()
        return result


inject_styles()
header()

st.markdown(
    """
    <section class="hero">
      <div class="eyebrow">Do corpus bruto à base confiável</div>
      <h1>Referências organizadas,<br>sem ruído no mapa.</h1>
      <p>Envie os artigos em PDF, revise apenas o que exige atenção e exporte
      uma base compatível com Scopus e VOSviewer. Cada obra permanece inteira,
      com todos os coautores.</p>
      <div class="format-chip">Autor(es), título, fonte, (ano)</div>
    </section>
    """,
    unsafe_allow_html=True,
)

if "review_df" not in st.session_state:
    steps(1)
    left, right = st.columns([1.65, 0.75], gap="large")
    with left:
        uploads = st.file_uploader(
            "Artigos do corpus",
            type=["pdf"],
            accept_multiple_files=True,
            help="Selecione somente os artigos que pertencem a este corpus.",
        )
        if uploads:
            st.caption(f"{len(uploads)} arquivo(s) selecionado(s)")
            if st.button("Processar artigos", type="primary", use_container_width=False):
                with st.spinner("Lendo os artigos e estruturando as referências…"):
                    try:
                        extract_uploads(uploads)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível processar o corpus: {exc}")
    with right:
        st.markdown(
            """
            <div class="note">
              <strong>Antes de começar</strong><br><br>
              Inclua somente artigos do corpus. Textos teóricos, memoriais e
              versões duplicadas serão processados se forem enviados.
              <br><br>
              Os PDFs ficam apenas durante o processamento da sessão.
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    review_df = st.session_state.review_df.copy()
    invalid = review_df["status"].ne("ok").sum()
    included = ~review_df["include"].str.lower().isin(["no", "não", "nao", "0", "false"])

    if "final_files" not in st.session_state:
        steps(2)
        failed_pdfs = st.session_state.get("failed_pdfs", [])
        if failed_pdfs:
            st.warning(
                f"{len(failed_pdfs)} PDF(s) não puderam ser lidos; "
                "os demais foram processados normalmente."
            )
            with st.expander("Ver PDFs que exigem atenção"):
                for item in failed_pdfs:
                    st.write(f"**{item['pdf_file']}** — {item['processing_error']}")
        top_left, top_right = st.columns([4, 1])
        with top_left:
            st.subheader("Revisão do corpus")
            st.caption(
                "Edite Autor(es), título, fonte e ano. Use “no” em include para remover ruídos."
            )
        with top_right:
            if st.button("Trocar corpus", use_container_width=True):
                reset_project()
                st.rerun()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Artigos", len(st.session_state.articles_df))
        m2.metric("Referências", int(included.sum()))
        m3.metric("Prontas", int((review_df["status"] == "ok").sum()))
        m4.metric("Revisar", int(invalid))

        display_columns = [
            "include", "pdf_file", "reference_order", "authors", "title",
            "source", "year", "status", "warnings",
        ]
        edited = st.data_editor(
            review_df[display_columns],
            use_container_width=True,
            hide_index=True,
            height=520,
            disabled=["pdf_file", "reference_order", "status", "warnings"],
            column_config={
                "include": st.column_config.SelectboxColumn(
                    "Incluir", options=["yes", "no"], width="small"
                ),
                "pdf_file": st.column_config.TextColumn("Artigo", width="medium"),
                "reference_order": st.column_config.NumberColumn("Nº", width="small"),
                "authors": st.column_config.TextColumn("Autor(es)", width="large"),
                "title": st.column_config.TextColumn("Título", width="large"),
                "source": st.column_config.TextColumn("Fonte", width="medium"),
                "year": st.column_config.TextColumn("Ano", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "warnings": st.column_config.TextColumn("Avisos", width="medium"),
            },
            key="reference_editor",
        )

        updated = review_df.copy()
        for column in display_columns:
            updated[column] = edited[column]
        checked_rows = validate_review(updated.to_dict("records"), strict=False)
        checked = pd.DataFrame(checked_rows, columns=REVIEW_COLUMNS)
        remaining = int((checked["status"] != "ok").sum())
        st.session_state.review_df = checked

        c1, c2 = st.columns([1, 1])
        with c1:
            st.download_button(
                "Baixar planilha de revisão",
                df_to_csv_bytes(checked),
                "referencias_revisao.csv",
                "text/csv",
                use_container_width=True,
            )
        with c2:
            if st.button(
                "Validar e gerar base",
                type="primary",
                use_container_width=True,
                disabled=remaining > 0,
            ):
                with st.spinner("Validando separadores e construindo a base…"):
                    try:
                        st.session_state.final_files = build_outputs(checked)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        if remaining:
            st.warning(
                f"{remaining} referência(s) ainda precisam de correção. "
                "Preencha os quatro campos ou marque include = no quando for ruído."
            )
        else:
            st.success("Todas as referências incluídas passaram pela validação.")
    else:
        steps(3)
        st.subheader("Base pronta para análise")
        st.write(
            "A estrutura foi validada: vírgulas dentro de cada obra e ponto e vírgula "
            "somente entre referências completas."
        )
        files = st.session_state.final_files
        c1, c2 = st.columns([1.1, 1])
        with c1:
            st.download_button(
                "Baixar pacote completo",
                files["Nexo_resultados.zip"],
                "Nexo_resultados.zip",
                "application/zip",
                type="primary",
                use_container_width=True,
            )
        with c2:
            st.download_button(
                "Baixar CSV Scopus/VOSviewer",
                files["corpus_scopus_vosviewer.csv"],
                "corpus_scopus_vosviewer.csv",
                "text/csv",
                use_container_width=True,
            )
        st.markdown(
            """
            <div class="note" style="margin-top:1rem">
              <strong>No VOSviewer</strong><br>
              Crie um mapa novo e importe o CSV. Para preservar os coautores,
              não edite manualmente os separadores do campo References.
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Processar outro corpus"):
            reset_project()
            st.rerun()
