# Guia de publicação — do zero ao Read the Docs

Passo a passo para quem nunca criou um pacote Python. Ao final você terá:
o código no GitHub, os tiles HAND hospedados num Release, a documentação
no Read the Docs e o pacote instalável via `pip`.

---

## Etapa 0 — O que já está pronto

Esta pasta `wfi2mask/` já é um pacote Python completo:

```
wfi2mask/
├── pyproject.toml        # "certidão de nascimento" do pacote (nome, versão, dependências)
├── README.md             # página inicial do GitHub
├── LICENSE               # licença MIT
├── .gitignore            # arquivos que o git deve ignorar
├── mkdocs.yml            # configuração da documentação
├── .readthedocs.yaml     # configuração do Read the Docs
├── src/wfi2mask/         # o código do pacote
├── tests/                # testes automatizados (pytest) — 26 testes passando
├── docs/                 # documentação em pt-BR
└── examples/             # exemplo de uso
```

Teste local (opcional, mas recomendado):

```bash
cd wfi2mask
pip install -e ".[dev]"
pytest
```

---

## Etapa 1 — Criar o repositório no GitHub

1. Crie uma conta em https://github.com (se ainda não tiver);
2. Clique em **New repository**:
   * Nome: `wfi2mask`
   * Visibilidade: **Public**
   * NÃO marque "Add a README" (já temos um);
3. No seu computador, dentro da pasta `wfi2mask/`:

```bash
git init
git add .
git commit -m "wfi2mask v0.1.0 - versao inicial"
git branch -M main
git remote add origin https://github.com/silvaglx/wfi2mask.git
git push -u origin main
```

> Se o `git` pedir autenticação, use um *Personal Access Token*
> (GitHub → Settings → Developer settings → Personal access tokens).

4. ~~Substituir o placeholder `SEU_USUARIO`~~ — **já feito**: todos os
   arquivos apontam para o usuário real `silvaglx`.

A partir de agora **qualquer pessoa** já pode instalar com:

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
```

---

## Etapa 2 — Hospedar os tiles HAND num GitHub Release

1. Extraia os tiles individuais (`s25w050_hnd.tif`, etc.) dos pacotes
   `hnd_s30w060.tar` / `hnd_s60w060.tar` do MERIT Hydro;
2. No repositório: **Releases → Create a new release**;
   * Tag: `hand-v1` (exatamente esse nome — o código aponta para ele)
   * Título: "HAND tiles (MERIT Hydro) v1"
   * Na descrição, cite: Yamazaki et al. (2019), licença CC-BY-NC 4.0 / ODbL 1.0
3. Arraste os arquivos `*_hnd.tif` para a área de *assets* e publique.

Cada asset pode ter até 2 GB (os tiles têm dezenas de MB — sem problema).
O download sob demanda do pacote passa a funcionar automaticamente.

> Dica: comece publicando só os tiles das suas 16 áreas de estudo e vá
> adicionando os demais conforme a necessidade.

---

## Etapa 3 — Ativar o Read the Docs

1. Crie conta em https://about.readthedocs.com (entre com o GitHub);
2. **Add project** → autorize o GitHub → escolha `wfi2mask`;
3. O Read the Docs lê o `.readthedocs.yaml` do repositório e faz o build
   sozinho (tema Material, idioma pt-BR — igual ao cbers4asat);
4. Em poucos minutos a documentação estará em:
   `https://wfi2mask.readthedocs.io`

A cada `git push`, a documentação é reconstruída automaticamente.

---

## Etapa 4 (opcional) — Publicar no PyPI

Para permitir `pip install wfi2mask` (sem o endereço do GitHub):

1. Crie conta em https://pypi.org e gere um *API token*
   (Account settings → API tokens);
2. No terminal:

```bash
pip install build twine
python -m build            # gera dist/wfi2mask-0.1.0.tar.gz e .whl
twine upload dist/*        # usuário: __token__ / senha: o token pypi-...
```

3. Pronto: `pip install wfi2mask` funciona no mundo todo.

> Recomendação: publique no PyPI quando a API estiver estável (por
> enquanto a instalação via GitHub é suficiente e mais fácil de atualizar).

---

## Etapa 5 — Fluxo de trabalho diário

```bash
# editar o código...
pytest                                   # confirmar que os testes passam
git add -A
git commit -m "descricao da mudanca"
git push                                 # docs reconstruem sozinhas
```

Para lançar uma nova versão: aumente `version` no `pyproject.toml`
(ex.: `0.1.1`), commit, push e (opcionalmente) crie um Release/tag
`v0.1.1` no GitHub.
