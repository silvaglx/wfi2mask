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

O percentual de nuvem do **catálogo INPE** é usado diretamente:

```python
w2m.get_toa(
    date="2025-06-01, 2025-09-30",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="amazonia1",
    max_cloud=20,      # só cenas com ≤ 20 % de nuvem no catálogo INPE
    max_images=5,      # baixa no máximo 5 cenas (mais recentes primeiro)
    user="seu_email@cadastrado_no_inpe.br",
)
```

`max_cloud=-1` (padrão) desativa o filtro e baixa todas as cenas do
período. `max_images` funciona com ou sem `max_cloud`.

```{admonition} O percentual é da cena inteira
:class: warning

O percentual de nuvem refere-se à **cena WFI completa** (faixa de
684–866 km). Uma cena "20 % nublada" pode estar totalmente limpa sobre o
seu `bbox` — e vice-versa. Use valores generosos e confie na composição
temporal pela regra da maioria para eliminar nuvens residuais.
```

```{admonition} Matchup Sentinel-2 (experimental)
:class: note

Uma triagem alternativa por *matchup* de datas com o Sentinel-2 está
disponível em caráter **experimental** (`s2_matchup=True`, requer
`max_cloud >= 0`): mantém apenas as datas WFI que coincidem (±1 dia) com
uma aquisição Sentinel-2 com nuvem ≤ `max_cloud`. Está **em teste/espera**
— outras opções de mascaramento de nuvem estão sendo consideradas para
versões futuras.
```

## 2. Gerar a máscara d'água

```python
resultado = w2m.get_water_mask(
    path="./wfi2mask_data/toa",   # pasta com as imagens TOA (WFI)
    coarse=100,                    # resolução da análise (m)
    hand=15,                       # HAND máximo (m)
    include_s2=True,               # soma Sentinel-2 direto da nuvem (opcional)
)
```

O que acontece:

* o `bbox` **não precisa ser repetido**: as imagens já vêm recortadas do
  `get_toa` e sua extensão é usada automaticamente (passe `bbox=` apenas
  para analisar uma sub-área);
* os tiles HAND necessários são **baixados sob demanda** e guardados em
  cache (`~/.wfi2mask/hand`);
* cada cena é classificada e exportada como shapefile com as 4 classes de
  confiança de Namikawa et al. (2016);
* com 2+ cenas, uma composição temporal pela **regra da maioria (>50 %)**
  também é exportada;
* um plot de demonstração (cor verdadeira + máscara) é salvo em PNG.

### Sentinel-2 direto da nuvem (`include_s2=True`)

Com `include_s2=True`, cenas **Sentinel-2 L2A** são somadas à composição
**sem baixar nenhum dado**: as imagens são lidas por janelas direto da
nuvem (AWS Open Data, sem cadastro), já na grade de análise — só os pixels
do `bbox` trafegam pela rede.

* o **período** é inferido automaticamente das datas das cenas WFI em
  `path` (ou informe `s2_date="2025-07-01, 2025-09-30"`);
* `s2_max_cloud=20` filtra pelo `eo:cloud_cover` da cena e, além disso,
  cada cena recebe a máscara de nuvem **por pixel** (banda SCL da ESA) —
  algo que o WFI não oferece;
* o limiar NIR é escolhido **automaticamente por cena**: 0,35 para WFI
  (TOA) e 0,10 para Sentinel-2 (reflectância de superfície) — passe
  `nir=` para fixar um valor único;
* também funciona **sem cenas WFI** (só Sentinel-2):

```python
resultado = w2m.get_water_mask(
    bbox=[-46.65, -23.85, -46.45, -23.65],
    s2_date="2025-07-01, 2025-09-30",
    include_s2=True,
)
```

### Ajustando a janela de Matiz (Hue)

Os limiares de Matiz são parâmetros — os padrões (16° e 35°) podem ser
alterados, por exemplo para uma recalibração dos sensores WFI:

```python
w2m.get_water_mask(path="./wfi2mask_data/toa", hue_min=14, hue_max=38)
```

As classes de confiança se adaptam automaticamente à janela escolhida.

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
