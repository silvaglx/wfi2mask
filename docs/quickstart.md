# Guia rápido

## 1. Baixar imagens e gerar reflectância TOA

```python
import wfi2mask

resultado = wfi2mask.get_toa(
    date="2025-07-01, 2025-09-30",          # intervalo de datas
    bbox=[-46.65, -23.85, -46.45, -23.65],  # Represa Billings/SP
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
    outdir="./wfi2mask_data",
)
```

O que acontece:

* o catálogo do INPE é consultado para o `bbox` e o período informados;
* o pacote avisa se o `bbox` cair na divisa entre órbitas — nesse caso
  **mais de uma cena** é baixada para cobrir toda a área solicitada;
* os dados brutos (DN) são salvos em `wfi2mask_data/raw/<satélite>/<cena>/`;
* cada cena é convertida para reflectância TOA e salva como GeoTIFF de
  4 bandas (1=Azul, 2=Verde, 3=Vermelho, 4=NIR) em
  `wfi2mask_data/toa/<satélite>/toa_<cena>.tif`.

### Data única

```python
wfi2mask.get_toa(
    date="2025-08-13",   # busca em uma janela de ±15 dias
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
)
```

Com uma única data, o pacote busca a(s) cena(s) **mais próxima(s)** da data
pedida dentro de uma janela de ±15 dias.

### Filtro de nuvem (matchup Sentinel-2)

Os metadados WFI **não trazem** percentual de nuvem confiável. O filtro de
nuvem do `wfi2mask` usa um *matchup* com o Sentinel-2: mantém apenas as
datas WFI que coincidem (±1 dia) com uma aquisição Sentinel-2 com cobertura
de nuvem ≤ `max_cloud`.

```python
wfi2mask.get_toa(
    date="2025-06-01, 2025-09-30",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    max_cloud=20,      # ativa o matchup (≤ 20 % de nuvem no Sentinel-2)
    max_images=5,      # baixa no máximo 5 cenas (mais recentes primeiro)
    user="seu_email@cadastrado_no_inpe.br",
)
```

`max_cloud=-1` (padrão) desativa o matchup e baixa todas as cenas do
período. `max_images` funciona com ou sem `max_cloud`.

## 2. Gerar a máscara d'água

```python
resultado = wfi2mask.get_water_mask(
    path="./wfi2mask_data/toa",             # pasta com as imagens TOA
    bbox=[-46.65, -23.85, -46.45, -23.65],  # recorte da análise
    coarse=100,   # resolução da análise (m)
    hand=15,      # HAND máximo (m)
    ndwi=0.0,     # limiar NDWI
    nir=0.35,     # NIR TOA máximo
)
```

O que acontece:

* as imagens TOA são **recortadas no bbox** e reamostradas para a grade de
  análise (padrão 100 m, compatível com o HAND de ~90 m);
* os tiles HAND necessários são **baixados sob demanda** e guardados em
  cache (`~/.wfi2mask/hand`);
* cada cena é classificada e exportada como shapefile com as 4 classes de
  confiança de Namikawa et al. (2016);
* com 2+ cenas, uma composição temporal pela **regra da maioria (>50 %)**
  também é exportada;
* um plot de demonstração (cor verdadeira + máscara) é salvo em PNG.

### Saídas

```
water_mask/
├── water_<cena>.shp              # por cena, campo "classe" = 1..4
├── water_composite_majority.shp  # composição (2+ cenas)
└── water_mask_overlay.png        # demonstração
```

| classe | rótulo | Matiz (Hue) | Confiança |
|--------|--------|-------------|-----------|
| 1 | WATER | 16°–35° (ou NDWI > 0) | máxima |
| 2 | WATER95 | 35°–36° ∪ 324°–16° | 95 % |
| 3 | WATER90 | 36°–37° ∪ 308°–324° | 90 % |
| 4 | WATER80 | 37°–160° | 80 % |
