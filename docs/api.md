# Referência da API

O pacote tem três funções principais:

| função | o que faz |
|--------|-----------|
| `get_products` | lista os produtos e catálogos disponíveis |
| `get_reflectance` | baixa a reflectância (SR) ou converte DN → TOA, recortada no bbox |
| `get_water_mask` | gera a máscara d'água e o plot comparativo |

---

## `wfi2mask.get_products`

```python
import wfi2mask as w2m

w2m.get_products(
    catalog=None,   # 'INPE_STAC' (padrão) | 'INPE_CLASSIC' | 'all'
    level=None,     # 'sr' | 'dn'
    source=None,    # 'inpe' | 'aws'
    verbose=True,   # imprime a tabela
)
```

Lista os produtos que o pacote consegue processar, imprimindo nome,
plataforma, nível, resolução, catálogo e as limitações de cada catálogo.

**Retorno:** lista de dicionários com `id`, `catalog`, `platform`, `level`,
`gsd`, `source`, `desc` e `coverage_start` (quando aplicável).

É o `id` dessa lista que se usa em `product=` nas outras funções.

---

## `wfi2mask.get_reflectance`

```python
w2m.get_reflectance(
    date=None,          # "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD"
    bbox=None,          # [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    product="all",      # nome(s) do produto, ou 'all'
    catalog=None,       # 'INPE_STAC' (padrão) | 'INPE_CLASSIC'
    max_cloud=-1,       # -1 desativa; >=0 filtra pelo % de nuvem da cena
    max_images=None,    # limite de cenas por produto (mais recentes primeiro)
    outdir="./wfi2mask_data",
    esun=None,          # override do ESUN (só no caminho DN -> TOA)
    acc=None,           # override do ACC  (só no caminho DN -> TOA)
    s2_matchup=False,   # experimental: matchup de datas com Sentinel-2
    save_dn=False,      # grava também o DN recortado (produtos DN)
    user=None,          # obrigatório apenas em catalog='INPE_CLASSIC'
)
```

Uma função para os dois níveis — **o nome do produto decide**:

* `*-L4-SR-*` → reflectância de superfície como publicada, sem calibração
  envolvida, acompanhada da banda CMASK;
* `*-L4-DN-*` → números digitais convertidos para TOA.

No catálogo STAC as bandas são lidas **por janela**: só o bbox trafega e a
cena nunca é baixada por inteiro.

**Estrutura de saída:**

```
outdir/
├── raw/                        # só em catalog='INPE_CLASSIC' (cena inteira)
└── reflectance/
    ├── CB4A-WFI-L4-SR-1/refl_<cena>.tif   # 5 bandas: B,G,R,NIR,CMASK
    └── CB4A-WFI-L4-DN-1/refl_<cena>.tif   # 4 bandas: B,G,R,NIR (TOA)
```

Os arquivos são float32 em reflectância `[0, ~1]` e carregam as tags
`PRODUCT`, `PRODUCT_LEVEL`, `CATALOG`, `SATELLITE`, `SCENE_ID`, `BBOX` e
`MASK_BAND` — é assim que o `get_water_mask` sabe tratar cada cena.

**Retorno:** lista de dicionários com `scene`, `product`, `satellite`,
`level`, `path` e `cloud_cover`; produtos DN trazem também `zenith` e `acc`.

```{admonition} Conversão TOA
:class: note

`ρ_TOA = (π × ACC × DN) / (ESUN × cos θ_sol)`

* **ACC** — lido do XML de cada cena
  (`<absoluteCalibrationCoefficient>`), que é a fonte publicada junto com o
  produto. A tabela `constants.ACC_OVERRIDE` vem **vazia** de propósito.
* **ESUN** — não é publicado no XML, então vem de tabela
  (`constants.ESUN`). Trate os valores como provisórios.
* **θ_sol** — zênite solar (90° − elevação solar do XML).
* A correção de distância Terra–Sol (d²) não é aplicada (erro sazonal de
  ±3,3 %).
```

### Personalizando ESUN e ACC

```python
# dict por banda (vale para todas as cenas)
w2m.get_reflectance(..., esun={"blue": 1935.0, "green": 1872.0,
                               "red": 1550.0, "nir": 1050.0})

# dict por satélite
w2m.get_reflectance(..., acc={"amazonia1": {"blue": 0.242, "green": 0.312,
                                            "red": 0.215, "nir": 0.186}})

# ou, globalmente, antes de chamar
w2m.constants.ACC_OVERRIDE["cbers4a"] = {...}
w2m.constants.ESUN["cbers4a"]["nir"] = 975.0
```

```{admonition} Cuidado ao editar constantes em runtime
:class: warning

Isso funciona para `ESUN` e `ACC_OVERRIDE` porque são **dicionários**,
mutados no lugar. Não funciona para constantes escalares como
`DEFAULT_NIR_MAX`: os módulos as importam por valor, então reatribuí-las em
`constants` não tem efeito. Para essas, use o parâmetro da função.
```

---

## `wfi2mask.get_water_mask`

```python
w2m.get_water_mask(
    path=None,      # pasta com refl_*.tif (saída de get_reflectance)
    bbox=None,      # opcional quando há path; obrigatório no streaming
    date=None,      # período; ativa a busca no catálogo
    catalog=None,   # 'INPE_STAC' (padrão) | 'INPE_CLASSIC'
    level="sr",     # nível dos produtos WFI buscados: 'sr' | 'dn'
    max_cloud=20,   # % de nuvem da cena; -1 desativa
    max_images=None,
    user=None,      # obrigatório apenas em catalog='INPE_CLASSIC'
    product=None,   # nome(s) do produto; filtra local E define o streaming
    coarse=100,     # resolução da análise em metros
    hand=15,        # HAND máximo (m)
    ndwi=0.0,       # limiar NDWI
    nir=None,       # None = SEM filtro NIR; dict por satélite para ligar
    hue_min=16, hue_max=35,
    hand_dir=None,  # pasta local com tiles HAND (raramente necessário)
    outdir=None,
    plot=True,
)
```

Três fontes podem ser combinadas numa mesma execução, todas caindo na mesma
grade de análise, de modo que a composição por maioria mistura livremente:

* **WFI da nuvem** — informe `date` (e opcionalmente `product`);
* **arquivos locais** — informe `path`; o nível de cada arquivo vem da tag
  `PRODUCT_LEVEL`, então SR e TOA convivem;
* **Sentinel-2** — inclua `sentinel-2-l2a` em `product` (ou
  `include_s2=True`).

**Retorno:** `{"scenes": [...], "plot": str|None, "outdir": str}`. Cada
item de `scenes` traz `scene`, `satellite`, `level`, `nir_max` e
`n_water_px`.

```{admonition} Exportação vetorial desativada
:class: note

Nesta versão a única saída em disco é o plot comparativo
`water_mask_overlay.png` (cor verdadeira × máscara). A composição por
maioria continua sendo calculada em memória — é o que alimenta o plot —, mas
não é vetorizada.
```

### Filtro NIR

```python
w2m.get_water_mask(..., nir={"cbers4": 0.35, "amazonia1": 0.30})
```

Por padrão (`nir=None`) **não há filtro NIR**. Satélites ausentes do
dicionário continuam sem filtro; um número simples aplica o mesmo limiar a
todas as cenas. Valores de referência ficam em
`constants.DEFAULT_NIR_MAX_BY_LEVEL` (0,35 para TOA e 0,10 para SR), mas
eles **não transferem bem** entre sensores — veja
[Algoritmo e limitações](algoritmo.md).

### Parâmetros Sentinel-2

`s2_date`, `s2_max_cloud` e `s2_max_images` permitem controlar a busca do
Sentinel-2 separadamente. Por padrão herdam `date`, `max_cloud` e
`max_images`.

```{admonition} hand_dir raramente é necessário
:class: tip

O filtro topográfico usa tiles HAND de 5°×5° derivados do MERIT Hydro
(Yamazaki et al., 2019). Os tiles que o `bbox` necessita são baixados
automaticamente do GitHub Release do projeto e guardados em cache
(`~/.wfi2mask/hand`) — nenhuma configuração é necessária. Use `hand_dir=`
apenas para trabalhar offline ou com tiles próprios; as variáveis de
ambiente `WFI2MASK_HAND_URL` e `WFI2MASK_CACHE` permitem trocar a URL base
e a pasta de cache.
```

---

## Funções de baixo nível

Para usuários avançados (arrays NumPy diretamente):

```python
from wfi2mask import (
    classify_scene,      # classifica uma cena (Verde, Vermelho, NIR [+HAND])
    majority_composite,  # agregação temporal pela regra da maioria
    norm_scene,          # normalização p99 por cena/banda
    rgb_to_hsv_hue,      # Matiz HSV vetorizado (Foley et al., 1996)
    convert_scene_to_toa,# converte uma pasta de cena DN para GeoTIFF TOA
    resolve_product,     # nome de produto -> entrada do registro
    search_scenes,       # busca no STAC do INPE
    tiles_for_bbox,      # nomes dos tiles HAND que cobrem um bbox
)
```

`convert_scene_to_toa` aceita `bbox=`, `esun=` e `acc=`, com a mesma
semântica do `get_reflectance`. `classify_scene` aceita `nir_max=None`
(padrão) para desligar o filtro NIR.

```{admonition} get_toa foi renomeada
:class: warning

`get_toa()` continua existindo como alias de `get_reflectance()`, com aviso
de depreciação, e resolve atalhos de satélite para os produtos **DN → TOA**
— mantendo o comportamento que o nome promete. Migre para
`get_reflectance()` nomeando o produto explicitamente.
```
