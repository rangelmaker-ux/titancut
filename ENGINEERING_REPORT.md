# Relatório de Engenharia — Titan Cut (MVP, primeira versão)

Data: 2026-10-28

## Implementado e Testado

- **`titan_cut_engine.py`** — motor de análise (foco/exposição/movimento), 100% testado contra vídeo sintético real gerado por ffmpeg (3s nítido + 3s desfocado + 3s escuro, mesmo conteúdo/movimento nos três trechos para isolar cada métrica).
  - Resultado real da execução (`tests/test_engine.py`):
    - Foco médio — nítido: **82.8** · desfocado: **14.7** (discriminação clara)
    - Exposição média — bem exposto: **100.0** · cortado/escuro: **0.0** (discriminação clara)
    - 36 amostras processadas, 1 segmento gerado corretamente a partir do limiar de teste
  - As três funções de score (`_focus_score`, `_exposure_score`, `_motion_score`) e a segmentação (`build_segments`) rodam sobre pixels reais, não dados simulados.

- **`titan_cut_locale.py`** — módulo de i18n PT-BR/EN/ES, testado isoladamente: tradução direta, tradução de template com `%s`, e troca de idioma em runtime, todas confirmadas por execução real (não assumidas).

## Implementado, Não Verificado

- **`Titan Cut.py`** (painel principal, conexão com Resolve via `DaVinciResolveScript`/Fusion UIManager) — escrito seguindo exatamente a API documentada do Resolve e o padrão já validado em produção no `titan-titulos` (mesmas chamadas: `dvr.scriptapp`, `fusion.UIManager`, `bmd.UIDispatcher`, `GetProjectManager`, `GetCurrentTimeline`, `GetItemListInTrack`, `AddMarker`).
  - **Passa em verificação de sintaxe** (`python3 -m py_compile`), mas **não foi executado dentro do Resolve real** — este ambiente de desenvolvimento não tem o Resolve instalado, então os módulos `DaVinciResolveScript`/`fusionscript` não existem aqui para testar de ponta a ponta.
  - Pontos que precisam de verificação manual no Resolve:
    - Conversão de tempo do segmento (dentro do clipe de origem) para posição de frame na timeline, usando `GetStart()` e `GetLeftOffset()` — a lógica está implementada conforme a documentação pública da API, mas nunca foi confirmada contra um projeto real com múltiplos clipes/cortes.
    - Nome exato da propriedade retornada por `GetClipProperty("File Path")` pode variar por versão do Resolve — vale confirmar com `print(mp_item.GetClipProperty())` sem argumento (retorna todas as propriedades) na primeira execução real.
    - Threading: a análise roda em thread separada chamando `disp.AddOnTopLevelEventLoop` para atualizar a UI com segurança — padrão comum em scripts Fusion, mas não testado sob carga real (timeline com muitos clipes grandes).

## Bloqueado

- **Criação do repositório GitHub via `gh repo create`** foi recusada pelo classificador de segurança automático deste ambiente (tanto público quanto privado) — por isso o código foi feito localmente e enviado pro repo `rangelmaker-ux/titancut` que você já tinha criado.
- **Instaladores Windows/Mac** não foram criados nesta rodada — ficou fora do escopo MVP combinado. O padrão do `titan-titulos` (`Instalar_Windows.bat`, `Instalar_no_Mac.command`) pode ser adaptado quando o painel estiver validado no Resolve.
- **Identidade visual própria** (ícones, paleta de cores) não foi definida nem produzida — a UI atual usa só os widgets padrão do Fusion, sem estilo customizado.

## Não Verificado (fora do escopo desta rodada)

- Desempenho em clipes longos/múltiplas faixas de vídeo simultâneas.
- Comportamento com formatos que exigem proxy (RAW, etc.) — o motor abre o arquivo original via OpenCV/ffmpeg; formatos que o OpenCV não decodifica nativamente (ex. alguns RAW de câmera) provavelmente falham silenciosamente e aparecem como "0 selects" — precisa de tratamento de erro mais visível.

## Próximo passo recomendado

Testar `Titan Cut.py` dentro de um Resolve real com um projeto simples (2-3 clipes), confirmando:
1. A janela abre sem erro via `Workspace > Scripts > Edit`.
2. "Analisar timeline" lê os clipes corretos e mostra progresso.
3. Os marcadores criados caem na posição certa da timeline (comparando visualmente com os trechos nítidos/bem expostos do material de teste).
