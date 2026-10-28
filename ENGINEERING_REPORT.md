# Relatório de Engenharia — Titan Cut

Data: 2026-10-28 (atualizado — rodada de teste manual da UI pós-MVP)

## Terceiro bug de integração encontrado e corrigido — teste manual desta rodada

**"Criar marcadores" reportava "Marcadores criados: 0" mesmo com selects
encontrados na análise.** Causa raiz, isolada por log em arquivo (mesma
técnica da rodada anterior, já que o Console do Resolve continua
inacessível via automação):

```
add_markers_for_segments: fps=24.0 timeline_start_frame=86400 clip_timeline_start=86400 ...
  segment start_s=0.000 source_frame=0 absolute_frame=86400 relative_frame=0 ok=False
```

`Timeline.AddMarker(frameId, ...)` retorna `False` silenciosamente quando
`frameId=0` — o Resolve não aceita marcador no primeiríssimo frame da
timeline, sem erro nenhum, sem exceção. Qualquer segmento aprovado que
comece bem no início do clipe (ex.: `start_s=0.0`, caso comum quando o
primeiro take da timeline já é um bom take) cai exatamente em
`relative_frame=0` depois da conversão absoluto→relativo, e o marcador
nunca é criado. **Correção**: usar frame `1` como piso em vez de `0` em
`add_markers_for_segments()` (`Titan Cut.py`). **Confirmado corrigido por
teste manual real**: mesmo clipe/mesmo segmento, antes da correção
mostrava "Marcadores criados: 0" de forma 100% reproduzível (3 tentativas
seguidas); depois da correção mostrou "Marcadores criados: 1" e o
marcador verde apareceu visível na régua da timeline, no frame 1.

## UI pós-MVP (presets, pesos, dip, filtro de movimento, flags) — testada manualmente no Resolve real nesta rodada

- Painel inteiro (presets, slider de dip, 3 sliders de peso, combo de
  filtro de movimento, botão de subclipes) renderiza sem erro dentro do
  Resolve.
- Combo de preset "Talking Head" confirmado cascateando corretamente
  limiar, dip, os 3 pesos e o filtro de movimento ao ser selecionado.
- "Analisar timeline" confirmado respeitando pesos/limiar/dip ajustados
  manualmente e via preset — rodado múltiplas vezes com thresholds
  diferentes, contagem de selects mudou de forma consistente com o
  esperado.
- Flag automática de exposição estourada confirmada disparando
  corretamente no clipe de teste (`C8920.MP4`, cena com luz de fundo).
- "Criar marcadores" confirmado funcionando (ver bug acima) — marcador
  verde visível na posição correta da timeline.
- **"Criar subclipes (bin)" — confirmado funcionando por teste manual real.**
  Era o item de maior risco (`MediaPool.AppendToTimeline()` + `SetCurrentTimeline()`
  numa timeline recém-criada, nunca exercitado antes). Clicado com 1 select
  aprovado (`C8920.MP4`): criou a timeline "Titan Cut Selects" no Pool de
  Mídia, trocou automaticamente para ela, e o clipe apareceu corretamente
  com a duração do segmento aprovado (07:17). Status "Subclipes criados: 1
  em 'Titan Cut Selects'" confirmado na UI. `GetClipProperty("FPS")` e
  `AppendToTimeline()` funcionaram como assumido, sem precisar de ajuste.
- **Combo de filtro de movimento testado isoladamente** — selecionar "Só
  com movimento (pan/tilt/zoom)" mudou a contagem de selects de 1 (com
  "Todos") pra 2 no mesmo clipe/mesmo limiar, confirmando que o filtro
  está sendo aplicado de verdade (o filtro reparte regiões contínuas em
  segmentos menores quando parte da região deixa de passar pelo tipo de
  movimento exigido — comportamento esperado, não um bug).

## Implementado em rodada anterior — SEM teste manual no Resolve (sessão sem acesso ao computador)

Tudo abaixo foi implementado numa sessão que perdeu a conexão com o
computador do usuário antes de poder testar a UI nova manualmente —
grande parte já foi validada nesta rodada (ver seção acima); o que ainda
falta está marcado explicitamente.

- **Pesos ajustáveis** (foco/exposição/movimento) — 3 sliders na UI, substituindo os pesos fixos 40/30/30.
- **Tolerância de dip ajustável** — slider (0.0s-3.0s), já existia no motor (`dip_tolerance_s`), só não estava exposto na UI.
- **Classificação de tipo de movimento** (estático / pan-tilt / zoom) — heurística de fluxo óptico clássico: magnitude baixa = estático; magnitude alta + correlação com o campo radial (vetores apontando pro/do centro) = zoom; magnitude alta sem essa correlação = pan/tilt. Testado isoladamente com campos de fluxo sintéticos (zero, puramente horizontal, puramente radial) em `test_engine.py` — a primeira versão da heurística tinha um bug (usava `abs(produto escalar)` antes da média, o que classificava até um pan puro como zoom por simetria; corrigido pra usar a média COM sinal).
- **Filtro de movimento na UI** — combo "Todos / Só estático / Só com movimento", aplicado em `build_segments(motion_filter=...)`.
- **Presets** — Padrão, Talking Head (prioriza foco, exige estático), Ação/Esporte (prioriza movimento, sem filtro de tipo), Produto/Still (prioriza exposição, exige estático). Combo que pré-popula todos os outros sliders; "Personalizado" não mexe em nada.
- **Flags automáticas**:
  - Exposição estourada: ≥30% das amostras do clipe com fração de pixels cortados ≥15%.
  - Corte brusco: diferença média de pixel ≥28 (0-255) entre amostras consecutivas — detecta quando o conteúdo mudou abruptamente dentro do próprio arquivo (ex. múltiplos takes no mesmo clipe de câmera).
  - Possível duplicata: hash perceptual (average hash 8x8 = 64 bits) do primeiro frame de cada clipe, comparado entre todos os clipes da timeline por distância de Hamming (≤8 bits = provável duplicata).
- **Criar subclipes (bin)** — monta uma timeline nova ("Titan Cut Selects") com `MediaPool.AppendToTimeline()`, um item por segmento aprovado de cada clipe. Segue a API pública documentada do Resolve, mas é o item de maior risco desta rodada por não ter sido exercitado: não tenho certeza de 100% se `AppendToTimeline` aceita a timeline recém-criada como alvo implícito (assumi que sim, via `Project.SetCurrentTimeline()` antes de chamar) nem se o nome da propriedade `FPS` em `GetClipProperty("FPS")` é exatamente esse em todas as versões — precisa confirmar na primeira execução real.
- **Instalador Windows** (`installer/windows/Instalar_Titan_Cut.bat`) — copia `src/Titan Cut.py` e `src/Modules/*.py` pra pasta de Scripts do Resolve, detecta Python do sistema (`py -3` ou `python`) e instala `opencv-python`/`numpy` via pip. Não testado rodando de verdade num Windows limpo.

## Implementado e Testado — fim a fim, dentro do Resolve real (Windows), rodada anterior (MVP)

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
