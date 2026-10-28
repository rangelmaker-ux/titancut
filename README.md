# Titan Cut

Seleção automática dos melhores takes direto na timeline do DaVinci Resolve — analisa **foco, exposição e movimento** de cada clipe e cria marcadores nos trechos que passam no limiar escolhido. PT-BR / English / Español.

Inspirado pela abordagem do [Cutdown](https://cutdown.app) (Softworks), mas nativo do Resolve: em vez de exportar/importar uma timeline separada, o Titan Cut roda dentro do próprio Resolve e escreve marcadores direto na timeline atual.

## Status

MVP em desenvolvimento. Ver [`ENGINEERING_REPORT.md`](ENGINEERING_REPORT.md) para o que está **Implementado / Testado / Bloqueado / Não Verificado**.

## Como funciona

1. Abra uma timeline no Resolve.
2. `Workspace > Scripts > Edit > Titan Cut` (após instalado — ver Instalação).
3. Clique em **Analisar timeline** — o Titan Cut lê cada clipe direto do arquivo de origem (a API do Resolve não expõe pixels decodificados, então a análise acontece fora do Resolve, como o próprio Cutdown faz) e calcula três métricas por amostra:
   - **Foco**: variância do Laplaciano (nitidez clássica em visão computacional)
   - **Exposição**: fração de pixels estourados/cortados no histograma
   - **Movimento**: magnitude de fluxo óptico entre amostras (prefere câmera parada)
4. Ajuste o **limiar de score** e clique em **Criar marcadores** para escrever os selects na timeline.

Determinístico e 100% local — sem IA/ML, sem nuvem, mesmo vídeo sempre dá o mesmo resultado.

## Estrutura

```
src/
  Titan Cut.py             # painel principal — conecta ao Resolve via Fusion UIManager
  Modules/
    titan_cut_engine.py    # motor de análise (CV puro: OpenCV + NumPy)
    titan_cut_locale.py    # i18n PT-BR/EN/ES (mesmo padrão do Titan Titles Studio)
tests/
  test_engine.py            # testa o motor contra vídeo sintético (foco/exposição)
  fixtures/sample.mp4       # vídeo de teste gerado por ffmpeg
```

> `titan_cut_engine.py` e `titan_cut_locale.py` ficam dentro de `Modules/`
> de propósito: o Resolve lista no menu `Workspace > Scripts` qualquer
> `.py` solto direto na pasta `Edit`/`Utility`, então um arquivo de apoio
> ali vira um item de menu que não faz nada quando clicado. Só
> `Titan Cut.py` deve ficar na raiz da pasta de scripts.

## Rodar os testes do motor

```bash
pip install opencv-python numpy
python3 tests/test_engine.py
```

## Roadmap (pós-MVP)

- Presets (Talking Head, Action/Sport, etc.)
- Pesos de métrica ajustáveis na UI (hoje são fixos: 40% foco / 30% exposição / 30% movimento)
- Filtro de movimento de câmera (estático, pan, tilt, zoom)
- Flags automáticas (clipping, corte brusco, duplicado)
- Criação de subclipes/bins além de marcadores
- Instaladores Windows (.bat) e Mac (.command) — seguindo o padrão do [titan-titulos](https://github.com/rangelmaker-ux/titan-titulos)
- Identidade visual própria (ícones, cores) — ainda não definida

Criação: RangelMaker_. Instagram: [@rangelmaker_](https://instagram.com/rangelmaker_)
