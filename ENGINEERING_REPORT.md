# Relatório de Engenharia — Titan Cut (MVP)

Data: 2026-10-28 (atualizado após teste manual real no Resolve)

## Implementado e Testado — fim a fim, dentro do Resolve real (Windows)

- **`Titan Cut.py` + `titan_cut_engine.py`**: testado de ponta a ponta dentro do
  DaVinci Resolve real (não só sintaxe/unidade). Fluxo completo confirmado:
  abrir via `Workspace > Scripts > Edit > Titan Cut` → "Analisar timeline" lê o
  clipe da timeline, roda a análise e mostra o resultado (`N select(s)`) →
  "Criar marcadores" cria um marcador verde visível, na posição correta da
  timeline.
- **`titan_cut_engine.py`** — motor de análise (foco/exposição/movimento),
  testado contra vídeo sintético (ver `tests/test_engine.py`: foco 82.8 vs
  14.7, exposição 100.0 vs 0.0) **e** contra clipe de câmera real 4K
  (`C8920.MP4`, 8s/240 frames) dentro do Resolve.
- **`titan_cut_locale.py`** — i18n PT-BR/EN/ES, testado isoladamente.

## Dois bugs de integração encontrados e corrigidos no teste manual

1. **Travamento total do Resolve ao clicar "Analisar timeline"** (bug
   original reportado pelo usuário). Causa raiz, isolada por eliminação
   sistemática:
   - NÃO era threading (testado com `AddOnTopLevelEventLoop`, depois com o
     padrão `ui.QueueEvent`+`queue.Queue` do `titan-titulos` — ambos
     continuaram travando).
   - NÃO era decodificação lenta (confirmado via Gerenciador de Tarefas:
     0,2% de CPU durante o travamento = parado, não processando).
   - NÃO era o arquivo/codec em si (um script standalone rodando
     `cv2.VideoCapture` fora do Resolve abriu e leu o mesmo arquivo 4K em
     menos de 1 segundo).
   - **Causa real**: `cv2.VideoCapture()` sem especificar backend usa Media
     Foundation (MSMF) no Windows, que decodifica via GPU. Rodando dentro do
     processo do Resolve — que já usa a GPU pesadamente pra decodificar/
     exibir o mesmo clipe carregado na timeline — os dois brigam pelo
     decodificador de hardware e travam o processo inteiro.
   - **Correção**: forçar `cv2.VideoCapture(path, cv2.CAP_FFMPEG)` (software,
     sem GPU) em `analyze_video()`. Mais lento (~0,4–0,8s por amostra num
     clipe 4K — a análise de 33 amostras leva uns 15-17s), mas não trava mais
     o Resolve, que permanece 100% responsivo durante a análise.
   - Arquitetura final da análise: **síncrona na thread principal**, com
     `disp.StepLoop()` chamado a cada amostra pra janela continuar
     respondendo (nenhuma thread separada) — ver comentário "AVISO DE
     ENGENHARIA" em `Titan Cut.py`.

2. **"Criar marcadores" retornava sucesso mas nenhum marcador aparecia na
   timeline.** Causa: `TimelineItem.GetStart()` retorna o frame **absoluto**
   (mesmo espaço de `Timeline.GetStartFrame()`, ex. ~86400 numa timeline que
   começa em `01:00:00:00`), mas `Timeline.AddMarker(frameId, ...)` espera um
   frame **relativo** ao início da timeline. Sem a conversão, o marcador era
   criado numa posição fora da área visível/válida — `AddMarker()` retornava
   `True` (sem erro), então o bug passava despercebido sem inspecionar o
   resultado visualmente. **Correção**: subtrair `timeline.GetStartFrame()`
   antes de chamar `AddMarker()`, em `add_markers_for_segments()`.

## Como os bugs foram diagnosticados (sem acesso ao Console do Resolve)

Não foi possível digitar no Console Python do Resolve (Py3) via automação
desta sessão (texto nunca registrava). Diagnóstico feito por:
1. Testes manuais repetidos direto na UI do plugin, com monitoramento do
   Gerenciador de Tarefas (CPU) pra distinguir "travado" de "lento".
2. Script standalone (`tests/diagnostico_cv2.py`) rodado pelo usuário fora do
   Resolve, isolando se o problema era do cv2/arquivo ou específico da
   integração com o Resolve.
3. Log em arquivo (escrito pelo próprio `titan_cut_engine.py` numa pasta já
   sincronizada, já que stdout não é visível ao rodar via
   `Workspace > Scripts`) — revelou que a análise NUNCA estava travada depois
   do fix do backend: só demorava ~17s e cliques repetidos no botão
   reiniciavam a análise do zero, dando a falsa impressão de travamento.

## Bloqueado / fora do escopo desta rodada

- Instaladores Windows/Mac (`Instalar_Windows.bat`, `Instalar_no_Mac.command`,
  no padrão do `titan-titulos`) — ainda não criados.
- Identidade visual própria (ícones, paleta) — UI ainda usa só os widgets
  padrão do Fusion.

## Não verificado (fora do escopo desta rodada)

- Desempenho com timelines de múltiplos clipes/múltiplas faixas de vídeo
  simultâneas (testado só com 1 clipe).
- Comportamento com formatos que o OpenCV não decodifica nativamente (RAW de
  câmera, etc.) — provavelmente falha silenciosamente como "0 selects"; vale
  melhorar a mensagem de erro.
- Nome exato da propriedade `GetClipProperty("File Path")` noutras versões
  do Resolve (funcionou na testada, Resolve Studio 21).

## Próximo passo recomendado

MVP funcional confirmado. Próximos passos ficam a critério do usuário:
presets, pesos ajustáveis na UI, filtro de movimento de câmera, instaladores,
identidade visual — ver roadmap no `README.md`.
