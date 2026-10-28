"""Titan Cut — seleção automática dos melhores takes para DaVinci Resolve.

Painel nativo construído com o UIManager do Fusion (mesmo padrão usado pelo
Titan Titles Studio), para rodar dentro do Resolve em:
  Workspace > Scripts > Edit (ou Utility) > Titan Cut

MVP: analisa os clipes da timeline atual (foco, exposição, movimento),
mostra os scores e cria marcadores na timeline nos trechos que passam no
limiar escolhido. Sem presets avançados, sem filtro de movimento de câmera
nesta versão — ver README.md para o roadmap.

AVISO DE ENGENHARIA: este arquivo foi implementado seguindo exatamente a
API documentada de scripting do Resolve e o padrão de UI já validado no
Titan Titles Studio (mesmo import, mesmo UIManager/UIDispatcher). O motor
de análise (titan_cut_engine.py) foi testado de verdade contra vídeo
sintético. A integração completa com o Resolve real (este arquivo) AINDA
NÃO foi testada dentro do aplicativo — não há Resolve disponível neste
ambiente de desenvolvimento. Teste manual no Resolve é o próximo passo
obrigatório antes de qualquer uso em produção.
"""
from __future__ import annotations

import os
import sys
import threading


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

    O deslocamento do clipe na timeline (GetStart) é somado ao tempo do
    segmento dentro do arquivo de origem, descontando o ponto de entrada
    do clipe (GetLeftOffset) — ambos em frames, igual ao resto da API do
    Resolve. O frame rate da timeline converte segundos -> frames.
    """
    proj, _ = current_project_and_timeline()
    fps = float(proj.GetSetting("timelineFrameRate")) if proj else 25.0

    clip_timeline_start = track_item.GetStart()  # frame na timeline
    clip_left_offset = track_item.GetLeftOffset()  # frames cortados no início do clipe de origem

    created = 0
    for segment in segments:
        source_frame = int(round(segment.start_s * fps))
        timeline_frame = clip_timeline_start + (source_frame - clip_left_offset)
        ok = timeline.AddMarker(
            timeline_frame,
            color,
            "Titan Cut",
            f"score {segment.mean_score:.0f} · {segment.duration_s:.1f}s",
            1,
        )
        if ok:
            created += 1
    return created


# ---------------------------------------------------------------------------
# Estado da análise (roda em thread separada para não travar a UI)
# ---------------------------------------------------------------------------
class AnalysisState:
    def __init__(self):
        self.running = False
        self.results = {}  # file_path -> (scores, segments, track_item)
        self.lock = threading.Lock()


state = AnalysisState()


def run_analysis(clips, threshold, itm, win):
    state.running = True
    total = len(clips)
    for i, (name, path, track_item) in enumerate(clips):
        if not state.running:
            break

        def _set_status(text):
            itm["StatusLabel"].Text = text

        def progress(done, total_frames, _i=i, _name=name):
            # Nunca escreve na UI direto da thread de análise — o UIManager do
            # Fusion não é thread-safe e trava silenciosamente se você tentar
            # (foi exatamente esse travamento que o teste manual no Resolve
            # revelou). Toda atualização de UI precisa passar pelo event loop
            # principal via AddOnTopLevelEventLoop.
            text = locale.translate("Analisando clipe %s de %s…") % (_i + 1, total)
            disp.AddOnTopLevelEventLoop(lambda t=text: _set_status(t))

        try:
            scores = analyze_video(path, sample_rate_hz=4.0, weights=Weights(), progress_cb=progress)
            segments = build_segments(scores, threshold=threshold)
        except Exception as exc:  # noqa: BLE001 — reporta qualquer falha de leitura de arquivo
            scores, segments = [], []
            print(f"[Titan Cut] falha ao analisar {path}: {exc}")

        with state.lock:
            state.results[path] = (scores, segments, track_item)

        disp.AddOnTopLevelEventLoop(lambda n=name, s=segments: refresh_results_row(itm, n, s))

    state.running = False
    disp.AddOnTopLevelEventLoop(lambda: finish_analysis(itm))


def refresh_results_row(itm, name, segments):
    current = itm["ResultsList"].Text or ""
    line = f"{name}: {len(segments)} select(s)"
    itm["ResultsList"].Text = (current + "\n" + line).strip()


def finish_analysis(itm):
    itm["AnalyzeButton"].Enabled = True
    itm["CreateMarkersButton"].Enabled = True
    itm["StatusLabel"].Text = locale.translate("Selects encontrados")


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

    t = threading.Thread(target=run_analysis, args=(clips, threshold, itm, win), daemon=True)
    t.start()


def on_create_markers_clicked(win, itm):
    proj, timeline = current_project_and_timeline()
    if timeline is None:
        return
    created = 0
    with state.lock:
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
