# Referência da API

## `wfi2mask.get_toa`

```python
wfi2mask.get_toa(
    date=None,          # "AAAA-MM-DD" ou "AAAA-MM-DD, AAAA-MM-DD"
    bbox=None,          # [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    product="all",      # 'amazonia1' | 'cbers4a' | 'cbers4' | 'all' | lista
    max_cloud=-1,       # -1 desativa; >=0 ativa o matchup Sentinel-2 (%)
    max_images=None,    # limite de cenas por satélite (mais recentes primeiro)
    user=None,          # e-mail cadastrado no catálogo do INPE (obrigatório)
    outdir="./wfi2mask_data",
)
```

Busca no catálogo do INPE, baixa as bandas Azul/Verde/Vermelho/NIR + XML e
converte para reflectância TOA.

**Retorno:** lista de dicionários, um por cena convertida —
`{"scene", "satellite", "path", "zenith", "acc"}`.

**Estrutura de saída:**

```
outdir/
├── raw/
│   ├── amazonia1/<cena>/   # DN bruto + XML
│   ├── cbers4/...
│   └── cbers4a/...
└── toa/
    ├── amazonia1/toa_<cena>.tif   # 4 bandas float32 (B,G,R,NIR)
    └── ...
```

!!! note "Conversão TOA"
    `ρ_TOA = (π × ACC × DN) / (ESUN × cos θ_sol)`

    * **ACC** — coeficientes validados via RadCalNet para CBERS-4A e
      Amazonia-1; para CBERS-4 o ACC é lido do XML de cada cena.
    * **ESUN** — irradiância solar exoatmosférica por banda e satélite.
    * **θ_sol** — zênite solar (90° − elevação solar do XML).
    * Limitação: a correção de distância Terra–Sol (d²) não é aplicada
      (erro sazonal de ±3,3 %).

---

## `wfi2mask.get_water_mask`

```python
wfi2mask.get_water_mask(
    path=None,      # diretório com imagens TOA (toa_*.tif), busca recursiva
    bbox=None,      # recorte da análise [lon_min, lat_min, lon_max, lat_max]
    coarse=100,     # resolução da análise em metros
    hand=15,        # HAND máximo (m)
    ndwi=0.0,       # limiar NDWI
    nir=0.35,       # reflectância NIR TOA máxima
    hue_min=16, hue_max=35,   # janela de Matiz de Namikawa
    hand_dir=None,  # pasta local com tiles HAND (opcional)
    outdir=None,    # padrão: <path>/../water_mask
    plot=True,      # salvar o plot de demonstração
)
```

Classifica as imagens TOA e exporta shapefiles com as 4 classes de
confiança + composição temporal pela regra da maioria (quando há 2+ cenas).

**Retorno:** `{"scenes": [...], "composite": str|None, "plot": str|None,
"outdir": str}`.

!!! warning "NIR: WFI ≠ Sentinel-2"
    No Sentinel-2 L2A o limiar era `NIR < 1000` porque a reflectância vem
    multiplicada por 10 000. As imagens TOA do `wfi2mask` são reflectância
    real em `[0, ~1]` — o padrão equivalente validado para WFI é
    **`nir=0.35`**.

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
