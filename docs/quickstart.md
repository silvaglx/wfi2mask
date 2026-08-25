# Guia rápido

## 1. Baixar imagens WFI e gerar reflectância TOA

```python
import wfi2mask as w2m

resultado = w2m.get_toa(
    date="2025-07-01, 2025-09-30",          # intervalo de datas
    bbox=[-46.65, -23.85, -46.45, -23.65],  # Represa Billings/SP
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
    outdir="./wfi2mask_data",
)
```

O catálogo do INPE é consultado para o `bbox` e o `date` informados; os dados brutos (DN) são baixados e salvos em `wfi2mask_data/raw/<satélite>/<cena>/`; cada cena é convertida para reflectância TOA, **recortada no bbox** e salva como GeoTIFF de 4 bandas (1=Azul, 2=Verde, 3=Vermelho, 4=NIR) em `wfi2mask_data/toa/<satélite>/toa_<cena>.tif`. Obs: em caso do `bbox` cair na divisa entre órbitas, **mais de uma cena** é baixada para cobrir toda a área solicitada.


### Data única

```python
w2m.get_toa(
    date="2025-08-13",   # busca em uma janela de ±15 dias
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    user="seu_email@cadastrado_no_inpe.br",
)
```

Com uma única data, o pacote busca a(s) cena(s) **mais próxima(s)** da data
pedida dentro de uma janela de ±15 dias.

### Filtro de nuvem

Percentual de nuvem a partir do [cbers4asat](https://cbers4asat.readthedocs.io)), correspondente a cena inteira: 

```python
w2m.get_toa(
    date="2025-06-01, 2025-09-30",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    max_cloud=20,      # só cenas com ≤ 20 % de nuvem
    max_images=5,      # baixa no máximo 5 cenas (mais recentes primeiro)
    user="seu_email@cadastrado_no_inpe.br",
    s2_matchup=False #default
)
```

```{admonition} Matchup Sentinel-2 para filtro de nuvens diretamente sobre a bbox
:class: note

`s2_matchup=True` e `max_cloud >= 0` filtra as datas WFI que coincidem com Sentinel-2
(±1 dia) e com nuvem ≤ `max_cloud` sobre a bbox selecionada (em testes).
```

## 2. Gerar a máscara d'água

```python
resultado = w2m.get_water_mask(
    path="./wfi2mask_data/toa",   # pasta com as imagens TOA (WFI)
    coarse=100,                    # resolução desejada do produto final (m), default
    hand=15,                       # Valor máximo de HAND (m), default
    include_s2=False,               # if True, adiciona Sentinel-2 no composite de water mask*
)
```

Aplica o algoritmo sobre as imagens TOA recortadas pra bbox armazenadas no
determinado `path`; tiles HAND são **baixados sob demanda** e guardados em
cache (`~/.wfi2mask/hand`) para bbox especifico; cada cena é classificada e exportada 
como shapefile com as 4 classes de confiança de Namikawa et al. (2016); para 2+ cenas, 
uma composição temporal pela **regra da maioria (>50 %)** é aplicada; 
gera plot de demonstração salvo em PNG. 

*`include_s2` também funciona **sem cenas WFI**:

```python
resultado = w2m.get_water_mask(
    bbox=[-46.65, -23.85, -46.45, -23.65],
    s2_date="2025-07-01, 2025-09-30",
    include_s2=True,
)
```

### Ajustando a janela de Matiz (Hue)

```python
w2m.get_water_mask(path="./wfi2mask_data/toa", hue_min=14, hue_max=38)
```

### Saídas

```
water_mask/
├── water_<cena>.shp              # por cena WFI, campo "classe" = 1..4
├── water_S2_<data>.shp           # por data Sentinel-2 (include_s2=True)
├── water_composite_majority.shp  # composição (2+ cenas, WFI + S2)
└── water_mask_overlay.png        # demonstração
```

| classe | label | Matiz (Hue) | Confiança |
|--------|--------|-------------|-----------|
| 1 | WATER | 16°–35° (ou NDWI > 0) | máxima |
| 2 | WATER95 | 35°–36° ∪ 324°–16° | 95 % |
| 3 | WATER90 | 36°–37° ∪ 308°–324° | 90 % |
| 4 | WATER80 | 37°–160° | 80 % |
