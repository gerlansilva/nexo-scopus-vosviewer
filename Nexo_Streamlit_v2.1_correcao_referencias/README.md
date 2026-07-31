# Nexo

Aplicação web para transformar artigos em PDF em uma base compatível com
Scopus/VOSviewer, com referências no padrão:

```text
Autor(es), título, fonte, (ano)
```

## Versão 2.1 — extração conservadora

Esta versão corrige a segmentação que podia separar coautores ou unir obras:

- reconhece referências ABNT, APA, numeradas e autoria repetida por travessão;
- escolhe o ano da publicação antes de “Disponível em/Acesso em”;
- preserva os coautores dentro da mesma obra;
- detecta referências possivelmente coladas;
- não aprova apenas porque os quatro campos estão preenchidos;
- marca `et al.` como autoria truncada;
- mostra a referência original ao lado dos campos editáveis.

Avisos como `possible_joined_references`, `truncated_authors` e
`implausible_authors` exigem conferência. O programa deliberadamente prefere
pedir revisão a gerar uma rede bibliometricamente incorreta.

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

## PDFs criptografados

O projeto inclui `cryptography`, exigido pelo `pypdf` para abrir documentos
protegidos com criptografia AES. Após atualizar `requirements.txt` no GitHub,
reinicie o aplicativo para que a hospedagem reinstale as dependências.

PDFs protegidos por senha ou corrompidos são listados individualmente na etapa
de revisão. Os demais arquivos do corpus continuam sendo processados.

## Arquivos principais

- `app.py`: interface e fluxo web;
- `scopus_pdf_pipeline.py`: extração, validação e exportação;
- `assets/logo.svg`: identidade visual vetorial;
- `.streamlit/config.toml`: tema da aplicação;
- `requirements.txt`: dependências da hospedagem.
