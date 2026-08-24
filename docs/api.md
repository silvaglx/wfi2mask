# Referência da API

## `wfi2mask.get_toa`

```python
import wfi2mask as w2m

w2m.get_toa(
    date=None,          # "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD"
    bbox=None,          # [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    product="all",      # 'amazonia1' | 'cbers4a' | 'cbers4' | 'all' | lista
    max_cloud=-1,       # -1 desativa; >=0 filtra pelo % de nuvem do INPE
    max_images=None,    # limite de cenas por satélite (mais recentes primeiro)
    user=None,          # e-mail cadastrado no catálogo do INPE (obrigatório)
    outdir="./wfi2mask_data",
    s2_matchup=False,   # EXPERIMENTAL: triagem por matchup com Sentinel-2
    esun=None,          # override dos valores ESUN (ver abaixo)
    acc=None,           # override dos coeficientes ACC (ver abaixo)
)
```

Busca no catálogo do INPE, baixa as bandas Azul/Verde/Vermelho/NIR + XML e
converte para reflectância TOA **já recortada no bbox**.

**Retorno:** lista de dicionários, um por cena convertida —
`{"scene", "satellite", "path", "zenith", "acc"}`.

**Estrutura de saída:**

```
outdir/
├── raw/
│   ├── amazonia1/<cena>/   # DN bruto + XML (cena completa)
│   ├── cbers4/...
│   └── cbers4a/...
└── toa/
    ├── amazonia1/toa_<cena>.tif   # 4 bandas float32 (B,G,R,NIR), recorte no bbox
    ├── ...
    └── sentinel2/toa_S2_<data>.tif  # produtos de get_s2 (5 bandas, com SCL)
```

```{admonition} Conversão TOA
:class: note

`ρ_TOA = (π × ACC × DN) / (ESUN × cos θ_sol)`

* **ACC** — coeficientes validados via RadCalNet para CBERS-4A e
  Amazonia-1 (`wfi2mask.constants.ACC_OVERRIDE`); para o **CBERS-4** não
  há valores validados, então o ACC é lido do XML de cada cena.
* **ESUN** — irradiância solar exoatmosférica por banda e satélite
  (`wfi2mask.constants.ESUN`).
* **θ_sol** — zênite solar (90° − elevação solar do XML).
* Limitação: a correção de distância Terra–Sol (d²) não é aplicada
  (erro sazonal de ±3,3 %).
```

### Personalizando ESUN e ACC

Os valores validados são os **padrões**, mas podem ser editados de duas
formas:

```python
# 1) por chamada — dict por banda (vale para todas as cenas)...
w2m.get_toa(..., esun={"blue": 1935.0, "green": 1872.0, "red": 1550.0, "nir": 1050.0})

# ...ou dict por satélite (só afeta o satélite indicado)
w2m.get_toa(..., acc={"amazonia1": {"blue": 0.242, "green": 0.312,
                                    "red": 0.215, "nir": 0.186}})

# 2) globalmente, editando os padrões antes de chamar get_toa
w2m.constants.ESUN["cbers4a"]["nir"] = 975.0
```

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

## `wfi2mask.get_s2`

```python
w2m.get_s2(
    date=None,          # "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD"
    bbox=None,          # [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    max_cloud=20,       # eo:cloud_cover máximo da cena (%); -1 desativa
    max_images=None,    # limite de DATAS (mais recentes primeiro)
    outdir="./wfi2mask_data",
    resolution=10,      # resolução de saída (m)
)
```

Contrapartida Sentinel-2 do `get_toa` (que continua exclusivo WFI/INPE):
busca cenas **Sentinel-2 L2A** no Earth Search STAC (AWS Open Data, sem
cadastro), recorta no bbox, faz o mosaico por data e salva em
`outdir/toa/sentinel2/toa_S2_<data>.tif` — no mesmo layout do `get_toa`,
para que `get_water_mask` as encontre automaticamente (sozinhas ou junto
com as cenas WFI).

Cada produto tem **5 bandas float32**: 1=Azul, 2=Verde, 3=Vermelho, 4=NIR
(reflectância de superfície já dividida por 10 000, ou seja em `[0, ~1]`,
mesma convenção do TOA WFI) e 5=**SCL** (Scene Classification Layer da
ESA), usada pelo `get_water_mask` como máscara de nuvem por pixel.

**Retorno:** lista de dicionários —
`{"scene", "satellite", "path", "date", "n_items"}`.

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
)
```

Classifica as imagens TOA — WFI (`get_toa`) e/ou Sentinel-2 (`get_s2`) —
e exporta shapefiles com as 4 classes de confiança + composição temporal
pela regra da maioria (quando há 2+ cenas, **misturando os satélites**).

**Retorno:** `{"scenes": [...], "composite": str|None, "plot": str|None,
"outdir": str}`. Cada item de `scenes` traz `scene`, `satellite`,
`nir_max`, `shapefile`, `n_polygons` e `n_water_px`.

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

Os tiles HAND são baixados automaticamente do GitHub Release do projeto e
guardados em cache (`~/.wfi2mask/hand`). Use `hand_dir=` apenas para
trabalhar offline ou com tiles próprios.
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
