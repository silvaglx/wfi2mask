# wfi2mask

**Detecção automática de água em imagens WFI dos satélites brasileiros
CBERS-4, CBERS-4A e Amazonia-1 — com suporte também ao Sentinel-2.**

O `wfi2mask` automatiza todo o fluxo de trabalho:

1. **Busca e download** — consulta o catálogo do INPE (via
   [cbers4asat](https://cbers4asat.readthedocs.io)) e baixa as bandas
   Azul, Verde, Vermelho e NIR com os metadados XML;
2. **Reflectância TOA** — converte os números digitais (DN) para
   reflectância no topo da atmosfera com coeficientes de calibração
   validados via RadCalNet, **já recortada no bbox** de interesse;
3. **Máscara d'água** — aplica o algoritmo de Matiz (Hue) de
   [Namikawa et al. (2016)](algoritmo.md) aprimorado com filtros NDWI,
   HAND e brilho NIR, e exporta shapefiles com **4 níveis de confiança**.
   Com `include_s2=True`, cenas Sentinel-2 L2A são processadas **direto da
   nuvem** (AWS, sem download nem cadastro) e **combinadas com o WFI numa
   única composição**.

## Fluxo básico

```python
import wfi2mask as w2m

BBOX = [-46.65, -23.85, -46.45, -23.65]

# 1) baixar as cenas WFI e converter para TOA (recortado no bbox)
w2m.get_toa(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
)

# 2) gerar a máscara d'água; include_s2=True soma o Sentinel-2
#    (processado direto da nuvem, sem baixar nada) à composição
w2m.get_water_mask(path="./wfi2mask_data/toa", include_s2=True)
```

## Satélites suportados

| Satélite | Sensor | Resolução | Faixa | Fonte | Bandas usadas |
|----------|--------|-----------|-------|-------|---------------|
| CBERS-4 | AWFI | 64 m | 866 km | INPE (`get_toa`) | B13 (Azul), B14 (Verde), B15 (Verm.), B16 (NIR) |
| CBERS-4A | WFI | 55 m | 684 km | INPE (`get_toa`) | B5, B6, B7, B8 |
| Amazonia-1 | WFI | 64 m | 740 km | INPE (`get_toa`) | B1, B2, B3, B4 |
| Sentinel-2 | MSI (L2A) | 10 m | 290 km | nuvem AWS (`include_s2=True`) | blue, green, red, nir (+ SCL) |

O Sentinel-2 não é um sensor WFI, mas foi a base do desenvolvimento e da
validação do algoritmo (16 áreas no Brasil) — por isso é suportado como
entrada de `get_water_mask`, sozinho ou em conjunto com as cenas WFI.

```{admonition} Status do projeto
:class: warning

O `wfi2mask` é um protótipo em desenvolvimento (v0.2.0). Os limiares do
algoritmo foram validados com Sentinel-2 em 16 áreas no Brasil e estão
sendo transferidos para os sensores WFI — os limiares de Matiz
(`hue_min`/`hue_max`) são parametrizáveis e podem precisar de
recalibração. Veja [Algoritmo e limitações](algoritmo.md).
```

```{toctree}
:hidden:
:maxdepth: 2

instalacao
quickstart
api
algoritmo
```
