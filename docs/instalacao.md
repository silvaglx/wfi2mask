# Instalação

## Requisitos

* Python ≥ 3.9
* Conta (e-mail) cadastrada no
  [catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore) —
  necessária para o download das imagens WFI (`get_toa`). O Sentinel-2
  (`include_s2=True` em `get_water_mask`) não exige cadastro.

## Via pip (PyPI)

```bash
pip install wfi2mask
```

## Via pip (GitHub, versão de desenvolvimento)

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
```

## Para desenvolvimento

```bash
git clone https://github.com/silvaglx/wfi2mask.git
cd wfi2mask
pip install -e ".[dev]"
pytest            # rodar os testes
```

## Dependências

Instaladas automaticamente pelo pip:

`numpy`, `rasterio`, `geopandas`, `shapely`, `pyproj`, `matplotlib`,
`tqdm`, `requests`, `cbers4asat`, `pystac-client`.

```{admonition} Ambientes conda
:class: tip

Em Windows, `rasterio` e `geopandas` instalam com mais facilidade via
conda-forge:

    conda create -n wfi2mask -c conda-forge python=3.11 rasterio geopandas
    conda activate wfi2mask
    pip install wfi2mask
```
