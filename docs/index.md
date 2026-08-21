# wfi2mask

**Detecção automática de água em imagens WFI dos satélites brasileiros
CBERS-4, CBERS-4A e Amazonia-1.**

O `wfi2mask` automatiza todo o fluxo de trabalho:

1. **Busca e download** — consulta o catálogo do INPE (via
   [cbers4asat](https://cbers4asat.readthedocs.io)) e baixa as bandas
   Azul, Verde, Vermelho e NIR com os metadados XML;
2. **Reflectância TOA** — converte os números digitais (DN) para
   reflectância no topo da atmosfera com coeficientes de calibração
   validados via RadCalNet;
3. **Máscara d'água** — aplica o algoritmo de Matiz (Hue) de
   [Namikawa et al. (2016)](algoritmo.md) aprimorado com filtros NDWI,
   HAND e brilho NIR, e exporta shapefiles com **4 níveis de confiança**.

## Fluxo em duas funções

```python
import wfi2mask

# 1) baixar e converter para TOA
wfi2mask.get_toa(
    date="2025-07-01, 2025-09-30",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
)

# 2) gerar a máscara d'água
wfi2mask.get_water_mask(
    path="./wfi2mask_data/toa",
    bbox=[-46.65, -23.85, -46.45, -23.65],
)
```

## Satélites suportados

| Satélite | Sensor | Resolução | Faixa | Bandas usadas |
|----------|--------|-----------|-------|---------------|
| CBERS-4 | AWFI | 64 m | 866 km | B13 (Azul), B14 (Verde), B15 (Verm.), B16 (NIR) |
| CBERS-4A | WFI | 55 m | 684 km | B5, B6, B7, B8 |
| Amazonia-1 | WFI | 64 m | 740 km | B1, B2, B3, B4 |

!!! warning "Status do projeto"
    O `wfi2mask` é um protótipo em desenvolvimento (v0.1.0). Os limiares do
    algoritmo foram validados com Sentinel-2 em 16 áreas no Brasil e estão
    sendo transferidos para os sensores WFI — os limiares de Matiz podem
    precisar de recalibração. Veja [Algoritmo e limitações](algoritmo.md).
