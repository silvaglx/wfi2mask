# wfi2mask

**Detecção de corpos de água em imagens WFI dos satélites brasileiros CBERS-4, CBERS-4A e Amazonia-1.**

Como o wfi2mask funciona?

O `wfi2mask` busca imagens WFI nos catálogos do INPE, usa a reflectância de
superfície publicada (ou converte DN para TOA) recortada na área de
interesse, e gera máscaras d'água com 4 níveis de confiança, seguindo o
algoritmo de **Namikawa et al. (2016)** aprimorado.

> Status: protótipo em desenvolvimento (v0.4.0), já testável.

## Instalação

```bash
pip install wfi2mask
```

ou, para a versão de desenvolvimento:

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
```

**Nenhum cadastro é necessário** no modo padrão (STAC do INPE) nem para o
Sentinel-2. Uma conta no [catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore)
é exigida apenas se você optar por `catalog='INPE_CLASSIC'`.

## Uso rápido

```python
import wfi2mask as w2m

# quais produtos existem?
w2m.get_products()

# máscara d'água direto da nuvem — nada é baixado
w2m.get_water_mask(
    bbox=[-46.65, -23.85, -46.45, -23.65],
    date="2025-07-01, 2025-09-30",
    product=["CB4A-WFI-L4-SR-1", "AMZ1-WFI-L4-SR-1"],
    max_cloud=20,
)
```

Para guardar as imagens em disco (ou trabalhar com TOA):

```python
w2m.get_reflectance(date="2025-07-01, 2025-09-30", bbox=BBOX,
                    product="CB4A-WFI-L4-DN-1")   # DN -> TOA
w2m.get_water_mask(path="./wfi2mask_data/reflectance")
```

## Catálogos

O INPE publica o acervo WFI por dois catálogos independentes, sem definição
de qual é o oficial — e eles **não listam as mesmas cenas**. O pacote
suporta ambos via `catalog='INPE_STAC'` (padrão, sem cadastro, com leitura
por janela e máscara de nuvem por pixel) ou `catalog='INPE_CLASSIC'`
(mais cenas, mas exige cadastro e baixa a cena inteira). Detalhes na
documentação.

## Documentação

https://wfi2mask.readthedocs.io

## Referências

* Namikawa, L.M.; Korting, T.; Castejon, E.F. (2016). *Water Body Extraction
  From RapidEye Images*. RBC 68:1097-1111.
* Yamazaki, D. et al. (2019). *MERIT Hydro: A high-resolution global
  hydrography map*. Water Resources Research 55:5053-5073.
* Pinto, C.T. et al. (2016). *First in-flight radiometric calibration of MUX
  and WFI on-board CBERS-4*. Remote Sensing 8(5):405.
