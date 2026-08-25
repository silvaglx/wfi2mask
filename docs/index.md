# wfi2mask

**Detecção de corpos de água em imagens WFI dos satélites brasileiros
CBERS-4, CBERS-4A e Amazonia-1.**

Como o `wfi2mask` funciona?

1. **Busca e download** — consulta o catálogo do INPE (via
   [cbers4asat](https://cbers4asat.readthedocs.io)) e baixa as bandas
   RGB e NIR com os metadados XML;
2. **Reflectância TOA** — converte os números digitais (DN) para
   reflectância no topo da atmosfera (TOA) com coeficientes de calibração
   validados via RadCalNet (Moiano et al., in prep), **já recortada no bbox** de interesse;
3. **Máscara d'água** — aplica o algoritmo de Matiz (Hue) de
   [Namikawa et al. (2016)](algoritmo.md) aprimorado com filtros NDWI,
   HAND e brilho NIR, e exporta shapefiles com **4 níveis de confiança**.

## Fluxo básico

```python
import wfi2mask as w2m

BBOX = [-46.65, -23.85, -46.45, -23.65]

# 1) baixa cenas WFI e converte para TOA (recortada pra bbox definida)
w2m.get_toa(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
)

# 2) gera a máscara d'água a partir das TOAs baixadas
w2m.get_water_mask(path="./wfi2mask_data/toa")
```

## Satélites suportados

| Satélite | Sensor | Resolução | Faixa | Fonte | Bandas usadas |
|----------|--------|-----------|-------|-------|---------------|
| CBERS-4 | AWFI | 64 m | 866 km | INPE (`get_toa`) | B13 (Azul), B14 (Verde), B15 (Verm.), B16 (NIR) |
| CBERS-4A | WFI | 55 m | 684 km | INPE (`get_toa`) | B5, B6, B7, B8 |
| Amazonia-1 | WFI | 64 m | 740 km | INPE (`get_toa`) | B1, B2, B3, B4 |
| Sentinel-2* | MSI (L2A) | 10 m | 290 km | Cloud AWS (`include_s2=True`) | blue, green, red, nir (+ SCL) |

*Como base do desenvolvimento e da validação do algoritmo inicial, imagens Sentinel-2 são suportadas como entrada da função `get_water_mask` sendo processadas diretamente da nuvem AWS, sem necessidade de download das imagens ou cálculo TOA. Desta forma, o produto Sentinel-2 também pode ser combinado com as cenas WFI baixadas numa única composição via `get_water_mask`.

```{admonition} Status do projeto
:class: warning

O `wfi2mask` é um protótipo em desenvolvimento (v0.2.0). O
algoritmo original (Namikawa et al., 2016) e aprimoramentos (HAND, NDWI)
foram validados sobre imagens Sentinel-2 para 16 áreas no Brasil e estão sendo transferidos 
para os sensores WFI. Os limiares de Matiz (`hue_min`/`hue_max`) são parametrizáveis e 
podem precisar de recalibração. Veja [Algoritmo e limitações](algoritmo.md).
```

```{toctree}
:hidden:
:maxdepth: 2

instalacao
quickstart
api
algoritmo
```
