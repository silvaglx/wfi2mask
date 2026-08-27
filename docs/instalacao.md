# Instalação

## Requisitos

* Python ≥ 3.9
* **Nenhum cadastro** é necessário no modo padrão (`catalog='INPE_STAC'`),
  nem para o Sentinel-2 (AWS Open Data).
* Conta (e-mail) cadastrada no
  [catálogo do INPE](https://www.dgi.inpe.br/catalogo/explore) — necessária
  **apenas** para `catalog='INPE_CLASSIC'`, informada em `user=`. Veja
  [Catálogos](catalogos.md).

## Via pip (PyPI)

```bash
pip install wfi2mask
```

## Via pip (GitHub, versão de desenvolvimento)

```bash
pip install git+https://github.com/silvaglx/wfi2mask.git
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
