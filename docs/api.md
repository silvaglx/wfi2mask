# Referência da API

## `wfi2mask.get_toa`

```python
import wfi2mask as w2m

w2m.get_toa(
    date=None,          # "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD"
    bbox=None,          # [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    product="all",      # 'amazonia1' | 'cbers4a' | 'cbers4' | 'all' | lista
    max_cloud=-1,       # -1 desativa; >=0 filtra pelo % de nuvem do
    max_images=None,    # limite de cenas por satélite (mais recentes primeiro)
    user=None,          # e-mail cadastrado no catálogo
    outdir="./wfi2mask_data",
    s2_matchup=False,   # matchup com Sentinel-2
    esun=None,          # override dos valores ESUN (ver abaixo)
    acc=None,           # override dos coeficientes ACC (ver abaixo)
)
```

Busca no catálogo do INPE, baixa as bandas Azul/Verde/Vermelho/NIR + XML e
converte para reflectância TOA **já recortada no bbox**.

**Estrutura de saída:**

```
outdir/
├── raw/
│   ├── amazonia1/<cena>/   # DN bruto + XML (cena completa)
│   ├── cbers4/...
│   └── cbers4a/...
└── toa/
    ├── amazonia1/toa_<cena>.tif   # 4 bandas float32 (B,G,R,NIR), recorte no bbox
    └── ...
```

```{admonition} Conversão TOA
:class: note

`ρ_TOA = (π × ACC × DN) / (ESUN × cos θ_sol)`

* **ACC** — coeficientes corrigidos via RadCalNet para CBERS-4A e
  Amazonia-1 (`wfi2mask.constants.ACC_OVERRIDE`); **CBERS-4** ainda
  sendo ajustado.
* **ESUN** — irradiância solar por banda e satélite
  (`wfi2mask.constants.ESUN`).
* **θ_sol** — zênite solar (90° − elevação solar do XML).
```

### Personalizando ESUN e ACC

Os valores ESUN/ACC corrigidos por Moiano et al. (in prep) e NIR são padrões, 
mas podem ser editados de duas formas:

```python
# 1) dict por banda
w2m.get_toa(..., esun={"blue": 1935.0, "green": 1872.0, "red": 1550.0, "nir": 1050.0})

# dict por satélite
w2m.get_toa(..., acc={"amazonia1": {"blue": 0.242, "green": 0.312,
                                    "red": 0.215, "nir": 0.186}})

# 2) antes de chamar get_toa
w2m.constants.ESUN["cbers4a"]["nir"] = 975.0
```
building...
<!--
### Filtro de nuvem

`max_cloud >= 0` filtra a consulta pelo percentual de nuvem do **catálogo
INPE** (nível de cena). Como a cena WFI é enorme (684–866 km), o percentual
pode não representar o seu `bbox` — uma cena parcialmente nublada pode
estar limpa sobre a área de interesse.

`s2_matchup=True` (**experimental, em teste**) adiciona a triagem por
matchup com o Sentinel-2: só mantém datas WFI que coincidem (±1 dia) com
uma aquisição Sentinel-2 com `eo:cloud_cover <= max_cloud`. Outras opções
de mascaramento de nuvem estão em avaliação para versões futuras.

---

## `wfi2mask.get_water_mask`

```python
w2m.get_water_mask(
    path=None,      # diretório com imagens TOA (toa_*.tif), busca recursiva
    bbox=None,      # OPCIONAL: padrão = extensão das próprias imagens
    coarse=100,     # resolução da análise em metros
    hand=15,        # HAND máximo (m)
    ndwi=0.0,       # limiar NDWI
    nir=None,       # None = automático por cena (0.35 WFI / 0.10 Sentinel-2)
    hue_min=16, hue_max=35,   # janela de Matiz de Namikawa (ajustável)
    hand_dir=None,  # pasta local com tiles HAND (opcional, ver nota)
    outdir=None,    # padrão: <path>/../water_mask
    plot=True,      # salvar o plot de demonstração
    include_s2=False,     # soma Sentinel-2 L2A processado direto da nuvem
    s2_date=None,         # período S2; padrão = datas das cenas WFI em path
    s2_max_cloud=20,      # eo:cloud_cover máximo da cena S2 (%); -1 desativa
    s2_max_images=None,   # limite de DATAS S2 (mais recentes primeiro)
)
```

Classifica as imagens TOA locais (saída de `get_toa`) e exporta shapefiles
com as 4 classes de confiança + composição temporal pela regra da maioria
(quando há 2+ cenas).

**Retorno:** `{"scenes": [...], "composite": str|None, "plot": str|None,
"outdir": str}`. Cada item de `scenes` traz `scene`, `satellite`,
`nir_max`, `shapefile`, `n_polygons` e `n_water_px`.

### Sentinel-2 direto da nuvem (`include_s2=True`)

Com `include_s2=True`, cenas **Sentinel-2 L2A** são somadas à análise
**sem baixar nenhum dado**: a busca é feita no Earth Search STAC (AWS Open
Data, sem cadastro) e as bandas (blue/green/red/nir + **SCL**) são lidas
por janelas direto da nuvem, já na grade de análise — só os pixels do
`bbox`, na resolução `coarse`, trafegam pela rede. A reflectância é
convertida para a mesma escala `[0, ~1]` do TOA WFI, a banda SCL é
aplicada como **máscara de nuvem por pixel**, e cada data vira um
shapefile `water_S2_<data>.shp` que entra na composição junto com as
cenas WFI.

O período da busca vem de `s2_date` (mesmos formatos do `date` de
`get_toa`) ou, por padrão, do intervalo de datas das cenas WFI em `path`.
Uma execução **somente Sentinel-2** também é possível: omita `path` e
informe `bbox` e `s2_date`.

```{admonition} Limiar NIR automático
:class: note

Com `nir=None` (padrão), o limiar de brilho NIR é escolhido por cena:
**0,35** para WFI (reflectância TOA, mais clara) e **0,10** para
Sentinel-2 (reflectância de superfície L2A — equivalente ao `NIR < 1000`
da escala ×10 000 usada na validação). Passe um número para fixar o mesmo
limiar em todas as cenas.
```

```{admonition} hand_dir raramente é necessário
:class: tip

O filtro topográfico usa tiles HAND de 5°×5° derivados do MERIT Hydro
(Yamazaki et al., 2019). Os tiles que o `bbox` necessita são baixados
automaticamente do GitHub Release do projeto e guardados em cache
(`~/.wfi2mask/hand`) — nenhuma configuração é necessária. Use `hand_dir=`
apenas para trabalhar offline ou com tiles próprios; as variáveis de
ambiente `WFI2MASK_HAND_URL` e `WFI2MASK_CACHE` permitem trocar a URL
base e a pasta de cache.
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
    tiles_for_bbox,      # nomes dos tiles HAND que cobrem um bbox
)
```

`convert_scene_to_toa` também aceita `bbox=`, `esun=` e `acc=`, com a
mesma semântica do `get_toa`.
-->
