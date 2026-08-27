# Guia rápido

## 0. Ver os produtos disponíveis

```python
import wfi2mask as w2m

w2m.get_products()
```

Imprime o nome de cada produto, plataforma, nível de processamento,
resolução e catálogo de origem, além das limitações de cada catálogo. É o
nome do **PRODUTO** dessa lista que você usa em `product=`. Filtre com
`catalog=`, `level=` ou `source=`, e use `verbose=False` para só receber a
lista em Python.

## 1. Máscara d'água direto da nuvem

O caminho mais curto não baixa nada e não exige cadastro:

```python
resultado = w2m.get_water_mask(
    bbox=[-46.65, -23.85, -46.45, -23.65],   # Represa Billings/SP
    date="2025-07-01, 2025-09-30",
    product=["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-SR-1"],
    max_cloud=20,      # % de nuvem da cena; -1 desativa
    max_images=5,      # no máximo 5 cenas por produto (mais recentes primeiro)
)
```

As cenas de reflectância de superfície são lidas **por janela** direto do
STAC do INPE — só os pixels do `bbox`, já na resolução de análise, trafegam
pela rede. Os tiles HAND necessários são baixados sob demanda e guardados em
cache (`~/.wfi2mask/hand`). Cada cena é classificada nas 4 classes de
confiança de Namikawa et al. (2016); com 2+ cenas aplica-se a composição
temporal pela **regra da maioria (>50 %)**; e o resultado é um plot
comparativo salvo em PNG.

### Somando o Sentinel-2

```python
w2m.get_water_mask(
    bbox=BBOX, date="2025-07-01, 2025-09-30",
    product=["CB4A-WFI-L4-SR-1", "sentinel-2-l2a"],
)
```

Basta incluir `sentinel-2-l2a` na lista (equivale a `include_s2=True`). As
cenas entram na mesma composição das WFI, com a máscara SCL aplicada por
pixel. Também funciona **sem nenhuma cena WFI**, informando só
`sentinel-2-l2a`.

### Escolhendo o catálogo

```python
w2m.get_water_mask(..., catalog="INPE_CLASSIC",
                   user="seu_email@cadastrado_no_inpe.br")
```

O catálogo clássico não tem leitura por janela, então nesse modo as cenas
são baixadas por inteiro e convertidas para TOA antes da classificação.
Veja [Catálogos](catalogos.md) para as diferenças.

## 2. Baixar a reflectância (opcional)

Use quando quiser guardar as imagens, reprocessar várias vezes ou trabalhar
com TOA:

```python
resultado = w2m.get_reflectance(
    date="2025-07-01, 2025-09-30",
    bbox=[-46.65, -23.85, -46.45, -23.65],
    product="CB4A-WFI-L4-SR-1",     # ou "CB4A-WFI-L4-DN-1" para TOA
    max_cloud=20,
    outdir="./wfi2mask_data",
)
```

O nível vem do nome do produto: `-SR-` grava a reflectância de superfície
como publicada (mais a banda CMASK), `-DN-` converte para TOA com
`ρ = π·ACC·DN / (ESUN·cos θ_sol)`. Em ambos os casos a saída é recortada no
bbox, em `wfi2mask_data/reflectance/<PRODUTO>/refl_<cena>.tif`.

Depois é só apontar a pasta:

```python
w2m.get_water_mask(path="./wfi2mask_data/reflectance")
```

O `bbox` não precisa ser repetido — a extensão das próprias imagens é usada.
Cada arquivo carrega uma tag `PRODUCT_LEVEL`, então cenas SR e TOA podem
conviver na mesma pasta e na mesma composição.

### Data única

```python
w2m.get_reflectance(date="2025-08-13", bbox=BBOX, product="CB4A-WFI-L4-SR-1")
```

Com uma única data, o pacote busca na janela de ±15 dias e mantém a(s)
cena(s) **mais próxima(s)** da data pedida.

```{admonition} O percentual de nuvem é da cena inteira
:class: warning

`max_cloud` filtra pelo percentual de nuvem da **cena WFI completa** (faixa
de 684–866 km), que pode não representar o seu `bbox`. Nos produtos SR isso
é compensado pela máscara CMASK por pixel; no TOA, não.
```

## 3. Ajustes do algoritmo

### Janela de Matiz (Hue)

```python
w2m.get_water_mask(..., hue_min=14, hue_max=38)
```

### Filtro NIR (desativado por padrão)

```python
w2m.get_water_mask(..., nir={"cbers4a": 0.20, "amazonia1": 0.15})
```

Sem `nir=`, nenhum pixel é rejeitado por brilho NIR. Passe um dicionário
para ligar o filtro por satélite — os que ficarem de fora do dicionário
continuam sem filtro. Um número simples vale para todas as cenas.

### Saídas

```
water_mask/
└── water_mask_overlay.png     # cor verdadeira × máscara d'água
```

A exportação vetorial está desativada nesta versão. O retorno traz as
estatísticas por cena:

```python
{'outdir': ..., 'plot': ...,
 'scenes': [{'scene', 'satellite', 'level', 'nir_max', 'n_water_px'}, ...]}
```

| classe | label | Matiz (Hue) | Confiança |
|--------|--------|-------------|-----------|
| 1 | WATER | 16°–35° (ou NDWI > 0) | máxima |
| 2 | WATER95 | 35°–36° ∪ 324°–16° | 95 % |
| 3 | WATER90 | 36°–37° ∪ 308°–324° | 90 % |
| 4 | WATER80 | 37°–160° | 80 % |
