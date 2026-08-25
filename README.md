# wfi2mask

**Detecção de corpos de água em imagens WFI dos satélites brasileiros CBERS-4, CBERS-4A e Amazonia-1.**

Como o wfi2mask funciona?

O `wfi2mask` busca imagens no catálogo do INPE, converte para reflectância TOA recortada na área de interesse e gera
máscaras d'água com 4 níveis de confiança, seguindo o algoritmo de **Namikawa et al. (2016)** aprimorado.

> Status: protótipo em desenvolvimento (v0.2.0), já testável.

## Instalação

```bash
pip install wfi2mask
```

ou, para a versão de desenvolvimento:

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
```

Requisito: conta (e-mail) cadastrada no
[catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore) para o download
das imagens WFI.

## Documentação

https://wfi2mask.readthedocs.io

## Referências

* Namikawa, L.M.; Korting, T.; Castejon, E.F. (2016). *Water Body Extraction
  From RapidEye Images*. RBC 68:1097-1111.
* Yamazaki, D. et al. (2019). *MERIT Hydro: A high-resolution global
  hydrography map*. Water Resources Research 55:5053-5073.
* Pinto, C.T. et al. (2016). *First in-flight radiometric calibration of MUX
  and WFI on-board CBERS-4*. Remote Sensing 8(5):405.
