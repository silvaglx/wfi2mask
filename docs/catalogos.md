# Catálogos
<!--
O INPE publica o acervo WFI por **dois catálogos independentes**, e o
instituto ainda não definiu qual é o oficial. O `wfi2mask` suporta os dois,
selecionáveis pelo parâmetro `catalog=` em `get_products`,
`get_reflectance` e `get_water_mask`.
-->
```python
w2m.get_water_mask(..., catalog="INPE_STAC")      # padrão
w2m.get_water_mask(..., catalog="INPE_CLASSIC")
```

## Comparação

| | `INPE_STAC` (padrão) | `INPE_CLASSIC` |
|---|---|---|
| Origem | `data.inpe.br/bdc/stac/v1` | catálogo clássico via `cbers4asat` |
| Cadastro | **não precisa** | **exige** `user=` (e-mail no INPE) |
| Níveis | SR e DN | apenas DN |
| Leitura | **por janela** — só o bbox trafega | baixa a **cena inteira**, depois recorta |
| Máscara de nuvem | por pixel (CMASK no SR) | não tem |
| Metadado de nuvem | `eo:cloud_cover` (float) | `cloud_cover` (múltiplos de 10 %) |
| Streaming em `get_water_mask` | sim | não (baixa e converte antes) |
<!--
## Eles não veem as mesmas cenas

Esta é a diferença que mais importa. Medindo sobre um mesmo bbox
(Jacareí/SP) no período nov–dez/2025, **sem filtro de nuvem**:

| sensor | clássico | STAC (DN) | só no clássico |
|--------|----------|-----------|----------------|
| CBERS-4A | 15 | 9 | 6 |
| Amazonia-1 | 20 | 12 | 8 |
| CBERS-4 | 40 | 29 | 12 (e 1 só no STAC) |

O clássico lista cerca de 50 % mais cenas. Mas **com filtro de nuvem a
ordem se inverte**: com `max_cloud=30`, o STAC devolveu 5 e 10 cenas
(CBERS-4A e Amazonia-1) contra 4 e 8 do clássico — porque os dois estimam
nuvem de formas diferentes, e o clássico ainda quantiza o valor em múltiplos
de 10 %.

Ou seja: não existe um catálogo "mais completo" em termos absolutos. A
escolha é científica, e por isso ela é sua.
-->
```{admonition} IDs de cena não são intercambiáveis
:class: warning

A mesma aquisição tem identificadores diferentes nos dois catálogos:

* clássico: `CBERS4A_WFI20414020251229ETC2`
* STAC: `CBERS_4A_WFI_20251229_204_140_L4`

Não use o id de um catálogo para procurar no outro. Para casar cenas entre
catálogos, use `(data, path, row)`.
```

## Nomes de produto por catálogo

Os nomes de produto são **únicos entre catálogos**:

```python
w2m.resolve_product("CBERS4A_WFI_L4_DN", catalog="INPE_STAC")
# ValueError: O produto 'CBERS4A_WFI_L4_DN' pertence ao catálogo
# 'INPE_CLASSIC', mas catalog='INPE_STAC' foi informado.
```

Atalhos por satélite (`'cbers4a'`, `'amazonia1'`, `'cbers4'`) continuam
funcionando e resolvem dentro do catálogo pedido:

| atalho | `INPE_STAC` | `INPE_CLASSIC` |
|--------|-------------|----------------|
| `cbers4a` | `CB4A-WFI-L4-SR-1` | `CBERS4A_WFI_L4_DN` |
| `amazonia1` | `AMZ1-WFI-L4-SR-1` | `AMAZONIA1_WFI_L4_DN` |
| `cbers4` | `CB4-WFI-L4-SR-1` | `CBERS4_AWFI_L4_DN` |

## Sentinel-2

O Sentinel-2 vem sempre do **AWS Open Data** (Earth Search), em qualquer um
dos modos. portanto `sentinel-2-l2a` eh o mesmo nas duas listagens.

## Usando o catálogo clássico

```python
w2m.get_reflectance(
    date="2025-07-01, 2025-09-30",
    bbox=BBOX,
    product="CBERS4A_WFI_L4_DN",
    catalog="INPE_CLASSIC",
    user="seu_email@cadastrado_no_inpe.br",   # obrigatório aqui
    max_cloud=20,
)
```
<!-->
Em `get_water_mask`, como não há leitura por janela, o pacote cai no
pipeline original: baixa as cenas para `outdir/_classic/`, converte para TOA
e só então classifica. O aviso é explícito, e o `user=` é validado antes de
qualquer download.
-->

```{admonition} Custo do catálogo clássico
:class: warning

Cada cena é transferida por inteiro antes do recorte. Se o
seu critério não exigir as cenas extras do clássico, o STAC é
substancialmente mais rápido ao definir uma bbox especifica.
```
