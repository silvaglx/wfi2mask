# Dados HAND

O filtro topográfico do `wfi2mask` usa o **HAND** (*Height Above Nearest
Drainage* — altura acima da drenagem mais próxima) derivado do
[MERIT Hydro](https://global-hydrodynamics.github.io/MERIT_Hydro/)
(Yamazaki et al., 2019), com ~90 m de resolução. Pixels com HAND acima do
limiar (padrão 15 m) são rejeitados, eliminando falsos positivos em sombras
de relevo e áreas urbanas escuras.

## Download sob demanda

O conjunto completo para o Brasil tem ~2,5 GB, mas o `wfi2mask` **não**
exige baixar tudo: os dados são divididos em tiles de 5°×5° nomeados pelo
canto inferior esquerdo (ex.: `s25w050_hnd.tif`), e a função
`get_water_mask` calcula quais tiles o `bbox` necessita e baixa **apenas
esses**, guardando-os em cache local:

```
~/.wfi2mask/hand/       # cache (reutilizado entre execuções)
```

Um `bbox` típico precisa de 1 tile (algumas dezenas de MB); um `bbox` que
cruza a divisa de tiles usa 2 ou mais — o pacote avisa e faz o mosaico
automaticamente.

## Configuração

| Variável de ambiente | Efeito |
|----------------------|--------|
| `WFI2MASK_HAND_URL` | URL base alternativa para os tiles |
| `WFI2MASK_CACHE` | pasta de cache alternativa |

Também é possível apontar uma pasta local com os tiles:

```python
wfi2mask.get_water_mask(..., hand_dir="D:/dados/hand")
```

Se um tile não puder ser obtido, o pacote avisa e prossegue **sem** o
filtro HAND naquela área (com aviso explícito).

## Para mantenedores: hospedando os tiles

Os tiles são distribuídos como *assets* de um **GitHub Release** do
repositório (limite de 2 GB por arquivo — cada tile tem só dezenas de MB):

1. Extraia os tiles dos pacotes `hnd_s30w060.tar` / `hnd_s60w060.tar` do
   MERIT Hydro;
2. No GitHub, crie um Release com a tag `hand-v1`;
3. Anexe os arquivos `sXXwYYY_hnd.tif` individuais como assets;
4. Confirme que `HAND_RELEASE_BASE_URL` em `src/wfi2mask/constants.py`
   aponta para `https://github.com/SEU_USUARIO/wfi2mask/releases/download/hand-v1`.

!!! note "Licença dos dados"
    O MERIT Hydro é distribuído sob licença dupla CC-BY-NC 4.0 / ODbL 1.0.
    A redistribuição dos tiles derivados deve citar Yamazaki et al. (2019)
    e manter os termos da licença.
