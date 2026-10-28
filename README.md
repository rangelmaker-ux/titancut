# Titan Cut

Seleção automática dos melhores takes direto na timeline do DaVinci Resolve — analisa **foco, exposição e movimento** de cada clipe e cria marcadores nos trechos que passam no limiar escolhido. PT-BR / English / Español.

Inspirado pela abordagem do [Cutdown](https://cutdown.app) (Softworks), mas nativo do Resolve: em vez de exportar/importar uma timeline separada, o Titan Cut roda dentro do próprio Resolve e escreve marcadores direto na timeline atual.

## Status

- **Análise + marcadores**: testado de ponta a ponta dentro do DaVinci Resolve real (Windows). Ver [`ENGINEERING_REPORT.md`](ENGINEERING_REPORT.md).
- **Pesos ajustáveis, dip, filtro de movimento, presets, flags automáticas, subclipes/bin**: implementados e cobertos por teste automatizado do motor (`tests/test_engine.py`), mas a UI nova ainda não foi clicada dentro do Resolve real — próximo passo é testar manualmente na máquina do usuário.
- **Instalador Windows**: pronto em `installer/windows/`, ainda não rodado numa instalação real.

## Como funciona

1. Abra uma timeline no Resolve.
2. `Workspace > Scripts > Edit > Titan Cut` (após instalado — ver `installer/windows/README.md`).
3. Escolha um **preset** (Padrão, Talking Head, Ação/Esporte, Produto/Still) ou ajuste manualmente:
   - **Limiar de score**, **tolerância de dip** (quanto tempo um trecho pode cair abaixo do limiar sem cortar o take)
   - **Peso de cada métrica** (foco / exposição / movimento)
   - **Filtro de movimento de câmera**: todos, só estático, ou só com movimento (pan/tilt/zoom)
4. Clique em **Analisar timeline** — o Titan Cut lê cada clipe direto do arquivo de origem (a API do Resolve não expõe pixels decodificados, então a análise acontece fora do Resolve, como o próprio Cutdown faz) e calcula, por amostra:
   - **Foco**: variância do Laplaciano (nitidez clássica em visão computacional)
   - **Exposição**: fração de pixels estourados/cortados no histograma
   - **Movimento**: magnitude de fluxo óptico + classificação do tipo (estático / pan-tilt / zoom)
   - **Flags automáticas**: exposição estourada, corte brusco dentro do arquivo, possível duplicata de outro clipe da timeline (hash perceptual)
5. Clique em **Criar marcadores** para escrever os selects na timeline atual, ou **Criar subclipes (bin)** para reunir todos os selects aprovados numa timeline nova ("Titan Cut Selects").

Determinístico e 100% local — sem IA/ML, sem nuvem, mesmo vídeo sempre dá o mesmo resultado.

## Estrutura

```
src/
  Titan Cut.py             # painel principal — conecta ao Resolve via Fusion UIManager
  Modules/
    titan_cut_engine.py    # motor de análise (CV puro: OpenCV + NumPy)
    titan_cut_locale.py    # i18n PT-BR/EN/ES (mesmo padrão do Titan Titles Studio)
tests/
  test_engine.py            # testa o motor contra vídeo sintético (foco/exposição) + classificação de movimento/duplicatas
  fixtures/sample.mp4       # vídeo de teste gerado por ffmpeg
installer/
  windows/
    Instalar_Titan_Cut.bat  # copia src/ pra pasta de Scripts do Resolve + instala opencv-python/numpy
    README.md
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

- ~~Presets (Talking Head, Action/Sport, etc.)~~ — implementado, falta testar na UI real
- ~~Pesos de métrica ajustáveis na UI~~ — implementado, falta testar na UI real
- ~~Filtro de movimento de câmera (estático, pan, tilt, zoom)~~ — implementado, falta testar na UI real
- ~~Flags automáticas (clipping, corte brusco, duplicado)~~ — implementado, falta testar na UI real
- ~~Criação de subclipes/bins além de marcadores~~ — implementado, falta testar na UI real
- ~~Instalador Windows (.bat)~~ — pronto em `installer/windows/`, falta rodar numa instalação real
- Instalador Mac (.command) — seguindo o padrão do [titan-titulos](https://github.com/rangelmaker-ux/titan-titulos)
- Exportar pra Premiere/Avid/Final Cut — baixa prioridade: o Resolve já exporta EDL/XML/AAF nativamente da timeline atual
- Identidade visual própria (ícones, cores) — ainda não definida

Criação: RangelMaker_. Instagram: [@rangelmaker_](https://instagram.com/rangelmaker_)
