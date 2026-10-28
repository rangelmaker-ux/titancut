"""Titan Cut — seleção automática dos melhores takes para DaVinci Resolve.

Painel nativo construído com o UIManager do Fusion (mesmo padrão usado pelo
Titan Titles Studio), para rodar dentro do Resolve em:
  Workspace > Scripts > Edit (ou Utility) > Titan Cut

Analisa os clipes da timeline atual (foco, exposição, movimento — com
classificação de tipo: estático/pan-tilt/zoom), gera flags automáticas
(exposição estourada, corte brusco, possível duplicata entre clipes),
cria marcadores nos trechos aprovados e pode reunir os selects numa
timeline/bin separada ("Titan Cut Selects"), tudo com pesos, limiar, dip
e filtro de movimento ajustáveis pela UI (ou por um dos presets prontos).

STATUS:
- Fluxo de análise + marcadores: testado de ponta a ponta dentro do
  DaVinci Resolve real (Windows). Dois bugs de integração encontrados e
  corrigidos nesse teste manual:
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
- Pesos/dip/filtro de movimento/presets/flags: lógica implementada e
  coberta por teste automatizado do motor (tests/test_engine.py), mas a
  UI NOVA em si (sliders extras, combo de preset) AINDA NÃO foi clicada
  dentro do Resolve real nesta rodada — a sessão que fez o teste manual
  anterior perdeu a conexão com o computador antes de chegar aqui.
- Criar subclipes/bin: usa MediaPool.AppendToTimeline() pra montar uma
  timeline nova ("Titan Cut Selects") com cada segmento aprovado. Segue a
  API documentada do Resolve, mas AINDA NÃO foi testado dentro do app —
  é o próximo ponto a verificar manualmente (ver add_subclips_for_segments).
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
from titan_cut_engine import (  # noqa: E402
    analyze_video, build_segments, detect_duplicate_clips,
    MOTION_PAN_TILT, MOTION_STATIC, MOTION_ZOOM, PRESETS, Weights,
)

# Ordem fixa do combo de preset — índice -> chave em PRESETS, com um item
# extra no final ("Personalizado") que não aplica nada, só sinaliza que o
# usuário está ajustando os sliders manualmente.
PRESET_ORDER = ["default", "talking_head", "action_sports", "product_still"]
PRESET_LABELS = [PRESETS[k].label for k in PRESET_ORDER] + ["Personalizado"]

# Índice do combo de filtro de movimento -> conjunto de tipos aceitos
# (None = sem filtro, aceita qualquer amostra que passe no limiar de score).
MOTION_FILTER_OPTIONS = [None, {MOTION_STATIC}, {MOTION_PAN_TILT, MOTION_ZOOM}]


def _motion_filter_to_index(motion_filter):
    if motion_filter is None:
        return 0
    if motion_filter == {MOTION_STATIC}:
        return 1
    return 2


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
    """Retorna [(nome, caminho_do_arquivo, track_item, media_pool_item)]
    para cada clipe de vídeo na timeline atual, varrendo todas as faixas."""
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
            clips.append((mp_item.GetName(), file_path, item, mp_item))
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


def _source_fps(mp_item, fallback_fps):
    raw = mp_item.GetClipProperty("FPS")
    try:
        fps = float(raw)
        if fps > 0:
            return fps
    except (TypeError, ValueError):
        pass
    return fallback_fps


def add_subclips_for_segments(proj, mediapool, entries, timeline_fps):
    """Cria uma timeline nova ("Titan Cut Selects") com cada segmento
    aprovado de cada clipe, usando MediaPool.AppendToTimeline — o
    equivalente editorial a "subclipes numa bin" (o Resolve não tem uma
    API pública de subclipe avulso fora de uma timeline).

    entries: lista de (mp_item, segments) — um item por clipe analisado.

    AVISO DE ENGENHARIA: segue a API pública documentada do Resolve
    (MediaPool.CreateEmptyTimeline, Project.SetCurrentTimeline,
    MediaPool.AppendToTimeline com dicts mediaPoolItem/startFrame/
    endFrame), mas ainda não foi exercitada dentro do Resolve real nesta
    rodada — verificar visualmente na primeira execução.
    """
    base_name = "Titan Cut Selects"
    name = base_name
    suffix = 1
    new_timeline = mediapool.CreateEmptyTimeline(name)
    while new_timeline is None and suffix < 50:
        suffix += 1
        name = f"{base_name} {suffix}"
        new_timeline = mediapool.CreateEmptyTimeline(name)
    if new_timeline is None:
        return 0

    proj.SetCurrentTimeline(new_timeline)

    clip_infos = []
    for mp_item, segments in entries:
        fps = _source_fps(mp_item, timeline_fps)
        for segment in segments:
            start_frame = int(round(segment.start_s * fps))
            end_frame = max(start_frame + 1, int(round(segment.end_s * fps)))
            clip_infos.append({
                "mediaPoolItem": mp_item,
                "startFrame": start_frame,
                "endFrame": end_frame,
            })

    if not clip_infos:
        return 0

    created_items = mediapool.AppendToTimeline(clip_infos)
    return len(created_items) if created_items else 0


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
        self.results = {}  # file_path -> {"name", "segments", "track_item", "mp_item", "flags"}


state = AnalysisState()


def on_preset_changed(win, itm):
    index = itm["PresetCombo"].CurrentIndex
    if index < 0 or index >= len(PRESET_ORDER):
        return  # "Personalizado" — não mexe nos sliders
    preset = PRESETS[PRESET_ORDER[index]]
    itm["ThresholdSlider"].Value = preset.threshold
    itm["DipSlider"].Value = round(preset.dip_tolerance_s * 10)
    itm["FocusWeightSlider"].Value = round(preset.weights.focus * 100)
    itm["ExposureWeightSlider"].Value = round(preset.weights.exposure * 100)
    itm["MotionWeightSlider"].Value = round(preset.weights.motion * 100)
    itm["MotionFilterCombo"].CurrentIndex = _motion_filter_to_index(preset.motion_filter)


def _current_weights(itm):
    return Weights(
        focus=float(itm["FocusWeightSlider"].Value),
        exposure=float(itm["ExposureWeightSlider"].Value),
        motion=float(itm["MotionWeightSlider"].Value),
    )


def _current_motion_filter(itm):
    index = itm["MotionFilterCombo"].CurrentIndex
    if 0 <= index < len(MOTION_FILTER_OPTIONS):
        return MOTION_FILTER_OPTIONS[index]
    return None


def _translated_flags(flags, name_by_path, duplicates_for_path):
    out = []
    for flag in flags:
        out.append(locale.translate(flag))
    for other_path in duplicates_for_path:
        other_name = name_by_path.get(other_path, other_path)
        out.append(locale.translate("possível duplicado de %s") % other_name)
    return out


def _render_results(itm):
    lines = []
    for info in state.results.values():
        line = f"{info['name']}: {len(info['segments'])} select(s)"
        if info["flags"]:
            line += "  ⚠ " + "; ".join(info["flags"])
        lines.append(line)
    itm["ResultsList"].Text = "\n".join(lines)


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
    itm["CreateSubclipsButton"].Enabled = False
    itm["ResultsList"].Text = ""
    threshold = float(itm["ThresholdSlider"].Value)
    dip_tolerance_s = float(itm["DipSlider"].Value) / 10.0
    weights = _current_weights(itm)
    motion_filter = _current_motion_filter(itm)
    total = len(clips)
    state.results = {}
    clip_hashes = {}
    name_by_path = {}

    for i, (name, path, track_item, mp_item) in enumerate(clips):
        itm["StatusLabel"].Text = locale.translate("Analisando clipe %s de %s…") % (i + 1, total)
        _pump(win)

        def progress(done, total_frames):
            # Chamado várias vezes por clipe — mantém a janela respondendo
            # durante a decodificação de clipes longos.
            _pump(win)

        try:
            analysis = analyze_video(path, sample_rate_hz=4.0, weights=weights, progress_cb=progress)
            segments = build_segments(
                analysis.scores,
                threshold=threshold,
                dip_tolerance_s=dip_tolerance_s,
                motion_filter=motion_filter,
            )
            flags = list(analysis.flags)
            clip_hash = analysis.clip_hash
        except Exception as exc:  # noqa: BLE001 — reporta qualquer falha de leitura de arquivo
            segments, flags, clip_hash = [], [], None
            print(f"[Titan Cut] falha ao analisar {name}: {exc}")

        name_by_path[path] = name
        clip_hashes[path] = clip_hash
        state.results[path] = {
            "name": name,
            "segments": segments,
            "track_item": track_item,
            "mp_item": mp_item,
            "flags": flags,
        }
        _render_results(itm)
        _pump(win)

    # Duplicatas só dá pra saber depois que todos os clipes foram
    # analisados (compara o hash de cada um contra todos os outros).
    duplicates = detect_duplicate_clips(clip_hashes)
    for path, info in state.results.items():
        info["flags"] = _translated_flags(info["flags"], name_by_path, duplicates.get(path, []))
    _render_results(itm)

    itm["AnalyzeButton"].Enabled = True
    itm["CreateMarkersButton"].Enabled = True
    itm["CreateSubclipsButton"].Enabled = True
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
    if timeline is None or not state.results:
        itm["StatusLabel"].Text = locale.translate("Analise a timeline primeiro.")
        return
    created = 0
    for info in state.results.values():
        if info["segments"]:
            created += add_markers_for_segments(timeline, info["track_item"], info["segments"])
    itm["StatusLabel"].Text = locale.translate("Marcadores criados: %s") % created


def on_create_subclips_clicked(win, itm):
    proj, timeline = current_project_and_timeline()
    if proj is None or not state.results:
        itm["StatusLabel"].Text = locale.translate("Analise a timeline primeiro.")
        return
    mediapool = proj.GetMediaPool()
    fps = float(proj.GetSetting("timelineFrameRate")) if proj else 25.0
    entries = [
        (info["mp_item"], info["segments"])
        for info in state.results.values()
        if info["segments"]
    ]
    created = add_subclips_for_segments(proj, mediapool, entries, fps)
    itm["StatusLabel"].Text = locale.translate('Subclipes criados: %s em "Titan Cut Selects"') % created


def on_language_changed(win, itm):
    lang_index = itm["LanguageCombo"].CurrentIndex
    locale.configure(locale.LANGUAGES[lang_index])
    # Reconstrói os textos estáticos da janela na nova língua
    apply_static_labels(itm)


def apply_static_labels(itm):
    itm["AnalyzeButton"].Text = locale.translate("Analisar timeline")
    itm["CreateMarkersButton"].Text = locale.translate("Criar marcadores")
    itm["CreateSubclipsButton"].Text = locale.translate("Criar subclipes (bin)")
    itm["ThresholdLabel"].Text = locale.translate("Limiar de score")
    itm["DipLabel"].Text = locale.translate("Tolerância de queda (dip)")
    itm["WeightsLabel"].Text = locale.translate("Peso das métricas")
    itm["FocusLabel"].Text = locale.translate("Foco")
    itm["ExposureLabel"].Text = locale.translate("Exposição")
    itm["MotionLabel"].Text = locale.translate("Movimento")
    itm["MotionFilterLabel"].Text = locale.translate("Movimento de câmera")
    itm["PresetLabel"].Text = locale.translate("Preset")


# ---------------------------------------------------------------------------
# Construção da janela
# ---------------------------------------------------------------------------
def build_window():
    win = disp.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "Titan Cut",
            "Geometry": [100, 100, 560, 700],
        },
        ui.VGroup(
            {"Spacing": 6},
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
                        ui.Label({"ID": "PresetLabel", "Text": locale.translate("Preset"), "Weight": 0}),
                        ui.ComboBox({"ID": "PresetCombo", "Weight": 1}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "ThresholdLabel", "Text": locale.translate("Limiar de score"), "Weight": 0}),
                        ui.Slider({"ID": "ThresholdSlider", "Minimum": 0, "Maximum": 100, "Value": 60, "Weight": 1}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "DipLabel", "Text": locale.translate("Tolerância de queda (dip)"), "Weight": 0}),
                        # Unidade interna: décimos de segundo (0-30 = 0.0s-3.0s)
                        ui.Slider({"ID": "DipSlider", "Minimum": 0, "Maximum": 30, "Value": 5, "Weight": 1}),
                    ],
                ),
                ui.Label({"ID": "WeightsLabel", "Text": locale.translate("Peso das métricas"), "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "FocusLabel", "Text": locale.translate("Foco"), "Weight": 0}),
                        ui.Slider({"ID": "FocusWeightSlider", "Minimum": 0, "Maximum": 100, "Value": 40, "Weight": 1}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "ExposureLabel", "Text": locale.translate("Exposição"), "Weight": 0}),
                        ui.Slider({"ID": "ExposureWeightSlider", "Minimum": 0, "Maximum": 100, "Value": 30, "Weight": 1}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "MotionLabel", "Text": locale.translate("Movimento"), "Weight": 0}),
                        ui.Slider({"ID": "MotionWeightSlider", "Minimum": 0, "Maximum": 100, "Value": 30, "Weight": 1}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "MotionFilterLabel", "Text": locale.translate("Movimento de câmera"), "Weight": 0}),
                        ui.ComboBox({"ID": "MotionFilterCombo", "Weight": 1}),
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
                ui.Button({"ID": "CreateSubclipsButton", "Text": locale.translate("Criar subclipes (bin)"), "Weight": 0, "Enabled": False}),
            ],
        ),
    )

    itm = locale.wrap_items(win.GetItems())
    for name in locale.LANGUAGE_NAMES:
        itm["LanguageCombo"].AddItem(name)
    for label in PRESET_LABELS:
        itm["PresetCombo"].AddItem(locale.translate(label))
    for label in (
        locale.translate("Todos"),
        locale.translate("Só estático"),
        locale.translate("Só com movimento (pan/tilt/zoom)"),
    ):
        itm["MotionFilterCombo"].AddItem(label)

    win.On[WINDOW_ID].Close = lambda ev: disp.ExitLoop()
    win.On["AnalyzeButton"].Clicked = lambda ev: on_analyze_clicked(win, itm)
    win.On["CreateMarkersButton"].Clicked = lambda ev: on_create_markers_clicked(win, itm)
    win.On["CreateSubclipsButton"].Clicked = lambda ev: on_create_subclips_clicked(win, itm)
    win.On["PresetCombo"].CurrentIndexChanged = lambda ev: on_preset_changed(win, itm)
    win.On["LanguageCombo"].CurrentIndexChanged = lambda ev: on_language_changed(win, itm)

    return win


def main():
    win = build_window()
    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    main()
