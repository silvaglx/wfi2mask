# Algoritmo e limitações

## Regra de classificação por pixel

```
Água = (Matiz ∈ [16°, 35°) OU NDWI > 0) E (HAND ≤ 15 m) E pixel válido
       [E (NIR < limiar), se o filtro NIR for ativado]
```

O filtro de brilho NIR é **opcional e desativado por padrão** — ative-o por
satélite com `nir={"cbers4a": 0.20, ...}`. Nos produtos SR, "pixel válido"
inclui a máscara de nuvem por pixel (CMASK no WFI, SCL no Sentinel-2).
<!--
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

### Filtro de brilho NIR (opcional)

Água sempre tem reflectância NIR baixa, então um limiar de brilho rejeita
telhados metálicos com NDWI marginalmente positivo. O filtro está
**desativado por padrão** (`nir=None`) e é ativado por satélite:
`nir={"cbers4a": 0.20, "amazonia1": 0.15}`. Valores de referência:
`NIR < 0,35` para TOA e `NIR < 0,10` para reflectância de superfície
(equivalente ao `NIR < 1000` da escala ×10 000 usada na validação).

Esses limiares **não transferem bem entre sensores**: no WFI SR, o mínimo
de NIR sobre a mesma represa variou de 0,03 a 0,11 entre datas
consecutivas, acompanhando a órbita — provável efeito de ângulo de visada
numa faixa de 684–866 km. Por isso a recalibração é necessária antes de
ligar o filtro em produção.

## Agregação temporal — regra da maioria

Cada cena é classificada **independentemente**; um pixel é água na
composição se for classificado como água em **mais de 50 %** das
observações válidas, com mínimo de `max(2, n_cenas // 3)` observações.
-->
## Validação

F1 contra a máscara SCL do Sentinel-2

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
<!--
## Limitações conhecidas

* **Áreas úmidas rasas (Pantanal)** — lagos rasos e vegetação alagada são
  ambíguos; F1 = 0,42. Limitação documentada do método.
* **Água muito escura** — Matiz instável (delta ≈ 0 no HSV); compensada
  pelo NDWI.
* **Telhados metálicos** — falsos positivos em áreas costeiras baixas;
  seriam compensados pelo filtro NIR, hoje desativado por padrão.
* **Calibração TOA** — o ACC vem do XML de cada cena (fonte publicada com o
  produto), mas o **ESUN não é publicado no XML** e vem de tabela, com
  valores provisórios para os três sensores. Os produtos SR não dependem
  disso.
* **Correção Terra–Sol ausente** — erro sazonal de ±3,3 % na TOA. Não
  afeta os produtos SR.
* **Máscara de nuvem** — os produtos SR trazem CMASK por pixel (e o
  Sentinel-2, SCL). No caminho TOA/DN só existe a triagem por percentual da
  **cena inteira** (684–866 km), que pode não representar o bbox; a
  composição pela maioria mitiga nuvens residuais. A semântica do CMASK não
  é documentada pelo INPE — o pacote assume 127 = limpo, o que bateu com a
  nuvem declarada em todas as cenas testadas, mas convém validar.
* **Transferência de limiares** — a janela de Matiz [16°, 35°) foi
  calibrada em RapidEye/Sentinel-2; pode precisar de recalibração para os
  sensores WFI (use o histograma de Matiz como diagnóstico). Os limiares
  são parametrizáveis via `hue_min`/`hue_max` em `get_water_mask`. O mesmo
  vale, de forma ainda mais crítica, para o limiar NIR.
* **Divergência entre catálogos** — os dois catálogos do INPE não listam as
  mesmas cenas, e a diferença muda conforme o filtro de nuvem. Veja
  [Catálogos](catalogos.md).
* **Cobertura do SR** — o produto de reflectância de superfície do
  Amazonia-1 começa em 2024-01-01; antes disso só há DN (→ TOA).
-->
## Referências

* Foley, J.D. et al. (1996). *Computer Graphics: Principles and Practice*. 2ª ed. Addison-Wesley.
* Namikawa, L.M.; Korting, T.; Castejon, E.F. (2016). *Water Body Extraction From RapidEye Images*. RBC 68:1097-1111.
* Pinto, C.T. et al. (2016). *First in-flight radiometric calibration of MUX and WFI on-board CBERS-4*. Remote Sensing 8(5):405.
* Yamazaki, D. et al. (2019). *MERIT Hydro: A high-resolution global hydrography map*. Water Resources Research 55:5053-5073.
