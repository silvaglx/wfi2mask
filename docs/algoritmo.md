# Algoritmo e limitações

## Regra de classificação por pixel

```
Água = (Matiz ∈ [16°, 35°) OU NDWI > 0) E (HAND ≤ 15 m) E (NIR < 0,35) E pixel válido
```

### Matiz de Namikawa (R2G3B5)

Composição colorida com **Verde → canal R**, **Vermelho → canal G** e
**NIR → canal B**, seguida da transformação HSV (Foley et al., 1996). A água
concentra-se numa janela estreita de Matiz. As bandas são normalizadas por
cena e por banda pelo percentil 99.

O nome "R2G3B5" vem dos números de banda do RapidEye (B2=Verde, B3=Vermelho,
B5=NIR) usados no artigo original — **não** dos canais RGB.

### Classes de confiança (Namikawa et al., 2016)

| classe | label | Matiz | confiança |
|--------|--------|-------|-----------|
| 1 | WATER | 16°–35° | máxima |
| 2 | WATER95 | 35°–36° ∪ 324°–360° ∪ 0°–16° | 95 % |
| 3 | WATER90 | 36°–37° ∪ 308°–324° | 90 % |
| 4 | WATER80 | 37°–160° | 80 % |

Pixels recuperados apenas pelo NDWI (água escura, cujo Matiz é instável)
recebem a classe 1 — NDWI > 0 é um sinal fisicamente forte de água.

### NDWI — recuperação de água escura

`NDWI = (Verde − NIR) / (Verde + NIR)`, calculado com os valores **brutos**
(não normalizados — o índice é autonormalizante). Recupera águas escuras,
eutrofizadas ou pretas que falham no teste de Matiz.

### HAND — filtro topográfico

Remove falsos positivos em terreno elevado (sombras de relevo, áreas urbanas
escuras). Usa tiles de 5°×5° do MERIT Hydro (Yamazaki et al., 2019),
baixados automaticamente sob demanda e mantidos em cache local.

### Filtro de brilho NIR

Água sempre tem reflectância NIR baixa; telhados metálicos com NDWI
marginalmente positivo são rejeitados pelo limiar NIR, escolhido
automaticamente por cena: `NIR < 0,35` para WFI (reflectância TOA) e
`NIR < 0,10` para Sentinel-2 (reflectância de superfície L2A, equivalente
ao `NIR < 1000` da escala ×10 000 usada na validação).

## Agregação temporal — regra da maioria

Cada cena é classificada **independentemente**; um pixel é água na
composição se for classificado como água em **mais de 50 %** das
observações válidas, com mínimo de `max(2, n_cenas // 3)` observações.

## Validação

Limiares validados com Sentinel-2 L2A em 16 áreas no Brasil (F1 contra a
máscara SCL, agregação simétrica):

| Área | F1 | Área | F1 |
|------|----|------|----|
| Sobradinho | 0,993 | Balbina | 0,992 |
| Lagoa dos Patos | 0,988 | Três Marias | 0,985 |
| Porto Primavera | 0,984 | Furnas | 0,982 |
| Santarém | 0,977 | Tucuruí | 0,976 |
| Serra da Mesa | 0,972 | Billings | 0,968 |
| Xingó | 0,961 | Manso | 0,942 |
| Jacareí | 0,926 | Itaipu | — |
| **Castanhão** | **0,578** | **Pantanal** | **0,424** |

## Limitações conhecidas

* **Áreas úmidas rasas (Pantanal)** — lagos rasos e vegetação alagada são
  ambíguos; F1 = 0,42. Limitação documentada do método.
* **Água muito escura** — Matiz instável (delta ≈ 0 no HSV); compensada
  pelo NDWI.
* **Telhados metálicos** — falsos positivos em áreas costeiras baixas;
  compensados pelo filtro NIR.
* **Calibração CBERS-4** — valores ESUN aproximados (sem fonte validada);
  CBERS-4A e Amazonia-1 têm valores validados via RadCalNet.
* **Sem máscara de nuvem por pixel no WFI** — a triagem usa o percentual
  de nuvem do catálogo INPE, que se refere à cena inteira (684–866 km) e
  pode não representar o bbox; a composição pela maioria mitiga nuvens
  residuais. Cenas Sentinel-2 (via `include_s2=True`) têm máscara por
  pixel (SCL).
  Um matchup de datas com o Sentinel-2 existe em caráter experimental
  (`s2_matchup=True`) e outras opções estão em avaliação.
* **Transferência de limiares** — a janela de Matiz [16°, 35°) foi
  calibrada em RapidEye/Sentinel-2; pode precisar de recalibração para os
  sensores WFI (use o histograma de Matiz como diagnóstico). Os limiares
  são parametrizáveis via `hue_min`/`hue_max` em `get_water_mask`.
* **Correção Terra–Sol ausente** — erro sazonal de ±3,3 % na TOA.

## Referências

* Foley, J.D. et al. (1996). *Computer Graphics: Principles and Practice*. 2ª ed. Addison-Wesley.
* Namikawa, L.M.; Korting, T.; Castejon, E.F. (2016). *Water Body Extraction From RapidEye Images*. RBC 68:1097-1111.
* Pinto, C.T. et al. (2016). *First in-flight radiometric calibration of MUX and WFI on-board CBERS-4*. Remote Sensing 8(5):405.
* Yamazaki, D. et al. (2019). *MERIT Hydro: A high-resolution global hydrography map*. Water Resources Research 55:5053-5073.
