# wfi2mask

**Detecção de corpos de água em imagens WFI dos satélites brasileiros
CBERS-4, CBERS-4A e Amazonia-1.**

Como o `wfi2mask` funciona?

1. **Catálogo** — consulta os produtos WFI do INPE, seja pelo
   [STAC](https://data.inpe.br/stac/browser/) ou pelo catálogo clássico
   (via [cbers4asat](https://cbers4asat.readthedocs.io)), à sua escolha;
2. **Reflectância** — usa a reflectância de superfície (SR) já publicada,
   ou converte os números digitais (DN) para o topo da atmosfera (TOA),
   **sempre recortada no bbox** de interesse;
3. **Máscara d'água** — aplica o algoritmo de Matiz (Hue) de
   [Namikawa et al. (2016)](algoritmo.md) aprimorado com filtros NDWI e
   HAND, classificando em **4 níveis de confiança**, e gera um plot
   comparativo cor verdadeira × máscara.

## Fluxo básico

```python
import wfi2mask as w2m

BBOX = [-46.65, -23.85, -46.45, -23.65]

# 1) quais produtos existem?
w2m.get_products()

# 2) máscara d'água direto da nuvem — sem baixar nada, sem cadastro
w2m.get_water_mask(
    bbox=BBOX,
    date="2025-07-01, 2025-09-30",
    product=["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-SR-1"],
)
```

Se preferir guardar as imagens em disco (ou trabalhar com TOA), use o passo
intermediário:

```python
w2m.get_reflectance(date="2025-07-01, 2025-09-30", bbox=BBOX,
                    product="CB4A-WFI-L4-DN-1")     # DN -> TOA
w2m.get_water_mask(path="./wfi2mask_data/reflectance")
```

## Produtos suportados

| Produto | Plataforma | Nível | Resolução | Catálogo |
|---------|-----------|-------|-----------|----------|
| `CB4-WFI-L4-SR-1` / `CB4-WFI-L4-DN-1` | CBERS-4 / AWFI | SR / DN→TOA | 64 m | INPE_STAC |
| `CB4A-WFI-L4-SR-1` / `CB4A-WFI-L4-DN-1` | CBERS-4A / WFI | SR / DN→TOA | 55 m | INPE_STAC |
| `AMZ1-WFI-L4-SR-1` / `AMZ1-WFI-L4-DN-1` | Amazonia-1 / WFI | SR / DN→TOA | 64 m | INPE_STAC |
| `CBERS4_AWFI_L4_DN` | CBERS-4 / AWFI | DN→TOA | 64 m | INPE_CLASSIC |
| `CBERS4A_WFI_L4_DN` | CBERS-4A / WFI | DN→TOA | 55 m | INPE_CLASSIC |
| `AMAZONIA1_WFI_L4_DN` | Amazonia-1 / WFI | DN→TOA | 64 m | INPE_CLASSIC |
| `sentinel-2-l2a`* | Sentinel-2 / MSI | SR (L2A) | 10 m | AWS (ambos) |

`w2m.get_products()` imprime essa lista sempre atualizada, com as limitações
de cada catálogo. Veja [Catálogos](catalogos.md).

*Como base do desenvolvimento e da validação do algoritmo inicial, imagens
Sentinel-2 são suportadas como entrada da função `get_water_mask`, sendo
processadas diretamente da nuvem AWS, sem necessidade de download das imagens
ou cálculo TOA. Desta forma, o produto Sentinel-2 também pode ser combinado
com as cenas WFI numa única composição.

```{admonition} Status do projeto
:class: warning

O `wfi2mask` é um protótipo em desenvolvimento (v0.4.0). O algoritmo
original (Namikawa et al., 2016) e aprimoramentos (HAND, NDWI) foram
validados sobre imagens Sentinel-2 para 16 áreas no Brasil e estão sendo
transferidos para os sensores WFI. Os limiares de Matiz
(`hue_min`/`hue_max`) são parametrizáveis e podem precisar de recalibração.
```

```{toctree}
:hidden:
:maxdepth: 2

instalacao
quickstart
catalogos
api
algoritmo
```
