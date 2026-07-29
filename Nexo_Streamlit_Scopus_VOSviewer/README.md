# Nexo

Aplicação web para transformar artigos em PDF em uma base compatível com
Scopus/VOSviewer, com referências no padrão:

```text
Autor(es), título, fonte, (ano)
```

## Executar localmente

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Publicar no Streamlit Community Cloud

1. Crie um repositório no GitHub e envie o conteúdo desta pasta.
2. No Streamlit Community Cloud, escolha **Create app**.
3. Selecione o repositório, a branch `main` e o arquivo `app.py`.
4. Clique em **Deploy**.

Não é necessário configurar chave de API. O processamento é feito durante a
sessão e os arquivos temporários são eliminados ao final de cada etapa.

## Arquivos principais

- `app.py`: interface e fluxo web;
- `scopus_pdf_pipeline.py`: extração, validação e exportação;
- `assets/logo.svg`: identidade visual vetorial;
- `.streamlit/config.toml`: tema da aplicação;
- `requirements.txt`: dependências da hospedagem.
