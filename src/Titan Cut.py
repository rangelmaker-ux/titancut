"""Titan Cut — seleção automática dos melhores takes para DaVinci Resolve.

Painel nativo construído com o UIManager do Fusion (mesmo padrão usado pelo
Titan Titles Studio), para rodar dentro do Resolve em:
  Workspace > Scripts > Edit (ou Utility) > Titan Cut

MVP: analisa os clipes da timeline atual (foco, exposição, movimento),
mostra os scores e cria marcadores na timeline nos trechos que passam no
limiar escolhido. Sem presets avançados, sem filtro de movimento de câmera
nesta versão — ver README.md para o roadmap.

STATUS: testado de ponta a ponta dentro do DaVinci Resolve real (Windows) —
abre a partir de Workspace > Scripts > Edit > Titan Cut, analisa a timeline
atual e cria marcadores visíveis na posição correta. Dois bugs de
integração foram encontrados e corrigidos nesse teste manual:

1. cv2.VideoCapture() sem especificar o backend usava Media Foundation
   (decodificação por GPU) no Windows, que trava o processo inteiro ao
   rodar dentro do Resolve (que já usa a GPU pra exibir o mesmo clipe).
   Corrigido forçando cv2.CAP_FFMPEG (decodificação por software) em
   titan_cut_engine.py — mais lento (~0.5s por amostra num clipe 4K) mas
   não trava. Ver comentário em analyze_video().
2. TimelineItem.GetStart() retorna frame ABSOLUTO (mesmo espaço de
   Timeline.GetStartFrame(), ex. ~86400 pra uma timeline 01:00:00:00),
   mas Timeline.AddMarker() espera frame RELATIVO ao início da timeline.
   Sem a conversão, AddMarker() retornava True mas o marcador nunca
   aparecia visível. Corrigido em add_markers_for_segments().
"""
from __future__ import annotations

import os
import sys


def _script_dir():
    """Localiza a pasta deste script sem depender de __file__, que o
    Resolve nem sempre define ao rodar via Workspace > Scripts."""
    for cand in (globals().get("__file__"), sys.argv[0] if sys.argv else None):
        if cand and os.path.exists(cand):
            return os.path.dirname(os.path.abspath(cand))

    homes = []
    if sys.platform == "darwin":
        homes.append(os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts"))
        homes.append(
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts")
    elif sys.platform.startswith("win"):
        homes.append(os.path.join(
            os.environ.get("APPDATA", ""), "Blackmagic Design", "DaVinci Resolve",
            "Support", "Fusion", "Scripts"))
        homes.append(os.path.join(
            os.environ.get("PROGRAMDATA", ""), "Blackmagic Design", "DaVinci Resolve",
            "Fusion", "Scripts"))
    else:
        homes.append(os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts"))
        homes.append("/opt/resolve/Fusion/Scripts")

    for h in homes:
        for sub in ("Edit", "Comp", "Utility"):
            p = os.path.join(h, sub)
            if os.path.isfile(os.path.join(p, "Titan Cut.py")):
                return p
    return os.getcwd()


SCRIPT_DIR = _script_dir()
sys.path.insert(0, os.path.join(SCRIPT_DIR, "Modules"))

import titan_cut_locale as locale  # noqa: E402
from titan_cut_engine import analyze_video, build_segments, Weights  # noqa: E402

# ---------------------------------------------------------------------------
# Conexão com o Resolve (mesmo padrão do Titan Titles Studio.py)
# ---------------------------------------------------------------------------
try:
    resolve
except NameError:
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp("Resolve")

try:
    bmd
except NameError:
    try:
        import fusionscript as bmd
    except ImportError:
        import DaVinciResolveScript as _dvr
        bmd = _dvr.bmd

if resolve is None:
    raise RuntimeError(
        "Não foi possível conectar ao Resolve. Abra o Titan Cut pelo menu "
        "Workspace > Scripts dentro do DaVinci Resolve, não executando o "
        "arquivo .py diretamente."
    )

fusion = resolve.Fusion()
ui = locale.UIProxy(fusion.UIManager)
disp = bmd.UIDispatcher(fusion.UIManager)

WINDOW_ID = "TitanCutWindow"


# ---------------------------------------------------------------------------
# Ponte com o projeto/timeline atual do Resolve
# ---------------------------------------------------------------------------
def current_project_and_timeline():
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if proj is None:
        return None, None
    return proj, proj.GetCurrentTimeline()


def list_timeline_clips(timeline):
    """Retorna [(nome, caminho_do_arquivo, track_item)] para cada clipe de
    vídeo na timeline atual, varrendo todas as faixas de vídeo."""
    clips = []
    if timeline is None:
        return clips
    track_count = timeline.GetTrackCount("video")
    for track_index in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("video", track_index) or []
        for item in items:
            mp_item = item.GetMediaPoolItem()
            if mp_item is None:
                continue
            file_path = mp_item.GetClipProperty("File Path")
            if not file_path:
                continue
            clips.append((mp_item.GetName(), file_path, item))
    return clips


def add_markers_for_segments(timeline, track_item, segments, color="Green"):
    """Cria um marcador no início de cada segmento aprovado.

    AVISO DE ENGENHARIA (confirmado por teste manual real no Resolve):
    TimelineItem.GetStart()/GetEnd() retornam frames ABSOLUTOS no mesmo
    espaço de Timeline.GetStartFrame() (ex.: ~86400+ pra uma timeline que
    começa em 01:00:00:00) — mas Timeline.AddMarker(frameId, ...) espera
    frameId RELATIVO ao início da timeline (0 = primeiro frame). Usar o
    valor absoluto direto cria o marcador bem fora da timeline (nenhum
    erro, AddMarker retorna True, mas o marcador nunca aparece visível).
    Por isso subtraímos timeline.GetStartFrame() pra converter pra
    relativo antes de chamar AddMarker.
    """
    proj, _ = current_project_and_timeline()
    fps = float(proj.GetSetting("timelineFrameRate")) if proj else 25.0

    timeline_start_frame = timeline.GetStartFrame()  # frame absoluto inicial da timeline
    clip_timeline_start = track_item.GetStart()  # frame absoluto onde o clipe começa na timeline
    clip_left_offset = track_item.GetLeftOffset()  # frames cortados no início do clipe de origem

    created = 0
    for segment in segments:
        source_frame = int(round(segment.start_s * fps))
        absolute_frame = clip_timeline_start + (source_frame - clip_left_offset)
        relative_frame = absolute_frame - timeline_start_frame
        if relative_frame < 0:
            relative_frame = 0
        ok = timeline.AddMarker(
            relative_frame,
            color,
            "Titan Cut",
            f"score {segment.mean_score:.0f} · {segment.duration_s:.1f}s",
            1,
        )
        if ok:
            created += 1
    return created


# ---------------------------------------------------------------------------
# Estado da análise
#
# AVISO DE ENGENHARIA (confirmado por teste manual real no Resolve): rodar a
# análise numa threading.Thread separada — mesmo notificando a UI de volta só
# por ui.QueueEvent(), o padrão "oficial" usado pelo Titan Titles Studio —
# travou o processo inteiro (0,2% de CPU no Gerenciador de Tarefas, ou seja,
# parado, não lento). A ponte de scripting do Resolve (fusionscript/
# DaVinciResolveScript) não se mostrou segura para chamadas vindas de uma
# thread diferente da que abriu a conexão, pelo menos não quando há trabalho
# pesado (OpenCV) acontecendo nela. A solução comprovada é não usar thread
# nenhuma: processar tudo direto na thread principal e chamar
# disp.StepLoop() periodicamente para a janela continuar respondendo
# (mesmo padrão que o Titan Titles Studio usa pra trabalho síncrono longo).
# ---------------------------------------------------------------------------
class AnalysisState:
    def __init__(self):
        self.results = {}  # file_path -> (scores, segments, track_item)


state = AnalysisState()


def on_analyze_clicked(win, itm):
    proj, timeline = current_project_and_timeline()
    if timeline is None:
        itm["StatusLabel"].Text = locale.translate("Nenhuma timeline aberta no Resolve.")
        return
    clips = list_timeline_clips(timeline)
    if not clips:
        itm["StatusLabel"].Text = locale.translate("Nenhum clipe na timeline atual.")
        return

    itm["AnalyzeButton"].Enabled = False
    itm["CreateMarkersButton"].Enabled = False
    itm["ResultsList"].Text = ""
    threshold = float(itm["ThresholdSlider"].Value)
    total = len(clips)
    state.results = {}

    for i, (name, path, track_item) in enumerate(clips):
        itm["StatusLabel"].Text = locale.translate("Analisando clipe %s de %s…") % (i + 1, total)
        _pump(win)

        def progress(done, total_frames):
            # Chamado várias vezes por clipe — mantém a janela respondendo
            # durante a decodificação de clipes longos.
            _pump(win)

        try:
            scores = analyze_video(path, sample_rate_hz=4.0, weights=Weights(), progress_cb=progress)
            segments = build_segments(scores, threshold=threshold)
        except Exception as exc:  # noqa: BLE001 — reporta qualquer falha de leitura de arquivo
            scores, segments = [], []
            print(f"[Titan Cut] falha ao analisar {name}: {exc}")

        state.results[path] = (scores, segments, track_item)
        current = itm["ResultsList"].Text or ""
        line = f"{name}: {len(segments)} select(s)"
        itm["ResultsList"].Text = (current + "\n" + line).strip()
        _pump(win)

    itm["AnalyzeButton"].Enabled = True
    itm["CreateMarkersButton"].Enabled = True
    itm["StatusLabel"].Text = locale.translate("Selects encontrados")


def _pump(win):
    """Processa a fila de eventos do Fusion pra janela não parecer travada
    durante a análise síncrona (sem isso, clicar/arrastar/fechar a janela
    não responderia até o fim do processamento)."""
    try:
        disp.StepLoop()
    except Exception as exc:  # noqa: BLE001 — nunca interrompe a análise por isso
        print(f"[Titan Cut] StepLoop falhou: {exc}")


def on_create_markers_clicked(win, itm):
    proj, timeline = current_project_and_timeline()
    if timeline is None:
        return
    created = 0
    for path, (scores, segments, track_item) in state.results.items():
        if segments:
            created += add_markers_for_segments(timeline, track_item, segments)
    itm["StatusLabel"].Text = locale.translate("Marcadores criados: %s") % created


def on_language_changed(win, itm):
    lang_index = itm["LanguageCombo"].CurrentIndex
    locale.configure(locale.LANGUAGES[lang_index])
    # Reconstrói os textos estáticos da janela na nova língua
    apply_static_labels(itm)


def apply_static_labels(itm):
    itm["AnalyzeButton"].Text = locale.translate("Analisar timeline")
    itm["CreateMarkersButton"].Text = locale.translate("Criar marcadores")
    itm["ThresholdLabel"].Text = locale.translate("Limiar de score")


# ---------------------------------------------------------------------------
# Construção da janela
# ---------------------------------------------------------------------------
def build_window():
    win = disp.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "Titan Cut",
            "Geometry": [100, 100, 520, 460],
        },
        ui.VGroup(
            {"Spacing": 8},
            [
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "TitleLabel", "Text": "Titan Cut", "Weight": 1}),
                        ui.ComboBox({"ID": "LanguageCombo", "Weight": 0}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "ThresholdLabel", "Text": locale.translate("Limiar de score"), "Weight": 0}),
                        ui.Slider({"ID": "ThresholdSlider", "Minimum": 0, "Maximum": 100, "Value": 60, "Weight": 1}),
                    ],
                ),
                ui.TextEdit({"ID": "ResultsList", "ReadOnly": True, "Weight": 1}),
                ui.Label({"ID": "StatusLabel", "Text": "", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Button({"ID": "AnalyzeButton", "Text": locale.translate("Analisar timeline"), "Weight": 1}),
                        ui.Button({"ID": "CreateMarkersButton", "Text": locale.translate("Criar marcadores"), "Weight": 1, "Enabled": False}),
                    ],
                ),
            ],
        ),
    )

    itm = locale.wrap_items(win.GetItems())
    for name in locale.LANGUAGE_NAMES:
        itm["LanguageCombo"].AddItem(name)

    win.On[WINDOW_ID].Close = lambda ev: disp.ExitLoop()
    win.On["AnalyzeButton"].Clicked = lambda ev: on_analyze_clicked(win, itm)
    win.On["CreateMarkersButton"].Clicked = lambda ev: on_create_markers_clicked(win, itm)
    win.On["LanguageCombo"].CurrentIndexChanged = lambda ev: on_language_changed(win, itm)

    return win


def main():
    win = build_window()
    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    main()
