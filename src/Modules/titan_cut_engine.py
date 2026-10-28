"""Titan Cut — motor de análise de vídeo.

Lê um arquivo de vídeo diretamente do disco (não depende da API do Resolve
para acesso a pixels — a API de scripting do Resolve não expõe frames
decodificados), amostra frames, converte para escala de cinza reduzida e
calcula três métricas por amostra:

  - foco      (variância do Laplaciano — nitidez clássica em visão computacional)
  - exposição (fração de pixels estourados/cortados no histograma de luminância)
  - movimento (magnitude de fluxo óptico entre amostras consecutivas, mais o
    tipo de movimento: estático / pan-tilt / zoom)

As três métricas combinam num score geral (0-100), com pesos ajustáveis.
Sequências contínuas de frames acima do limiar viram "selects" (segmentos
candidatos a manter), com tolerância de "dip" (queda breve) configurável.

Além do score, cada clipe recebe flags automáticas:
  - exposição estourada/cortada
  - corte brusco (mudança abrupta de conteúdo dentro do próprio arquivo)
  - possível duplicata de outro clipe da timeline (hash perceptual)

Determinístico: a mesma entrada sempre produz a mesma saída. Sem IA/ML —
só processamento de imagem clássico, igual à abordagem do Cutdown (Softworks)
que inspirou este projeto.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

MAX_EDGE = 960  # mesmo teto usado pelo Cutdown — equilíbrio entre precisão e velocidade

MOTION_STATIC = "static"
MOTION_PAN_TILT = "pan_tilt"
MOTION_ZOOM = "zoom"

# Abaixo desse deslocamento médio (em px, na imagem redimensionada) o frame
# é considerado parado — ruído de compressão/respiração da câmera, não
# movimento intencional.
_STATIC_MAGNITUDE_PX = 0.6
# |correlação radial| acima disso = o fluxo aponta predominantemente pra
# dentro/fora do centro da imagem = zoom. Abaixo disso, é deslocamento
# predominantemente numa direção = pan/tilt.
_ZOOM_RADIAL_CORR = 0.35
# Diferença média de pixel (0-255) entre amostras consecutivas acima disso
# é tratada como corte brusco de conteúdo (não movimento de câmera).
_HARD_CUT_DIFF = 28.0
# Distância de Hamming (de 64 bits) abaixo disso entre hashes de clipe =
# provável duplicata.
_DUPLICATE_HAMMING_MAX = 8


@dataclasses.dataclass
class FrameScore:
    time_s: float
    focus: float        # 0-100, mais alto = mais nítido
    exposure: float      # 0-100, mais alto = exposição mais equilibrada
    motion: float          # 0-100, mais alto = mais parado (Active→Still, como no Cutdown)
    overall: float
    motion_type: str = MOTION_STATIC  # static | pan_tilt | zoom
    hard_cut: bool = False             # mudança abrupta de conteúdo desde a amostra anterior

    def __repr__(self):
        return (f"FrameScore(t={self.time_s:.2f}s focus={self.focus:.1f} "
                f"exposure={self.exposure:.1f} motion={self.motion:.1f} "
                f"({self.motion_type}) overall={self.overall:.1f})")


@dataclasses.dataclass
class Segment:
    start_s: float
    end_s: float
    mean_score: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclasses.dataclass
class Weights:
    focus: float = 0.4
    exposure: float = 0.3
    motion: float = 0.3

    def normalized(self) -> "Weights":
        total = self.focus + self.exposure + self.motion
        if total <= 0:
            return Weights(1 / 3, 1 / 3, 1 / 3)
        return Weights(self.focus / total, self.exposure / total, self.motion / total)


@dataclasses.dataclass
class Preset:
    """Combinação pronta de pesos/limiar/dip — atalho pra tipos comuns de
    filmagem, no mesmo espírito dos presets do Cutdown."""
    label: str
    weights: Weights
    threshold: float
    dip_tolerance_s: float
    motion_filter: Optional[Set[str]] = None  # None = sem filtro (aceita qualquer tipo)


PRESETS: Dict[str, Preset] = {
    "default": Preset("Padrão", Weights(0.4, 0.3, 0.3), 60.0, 0.5, None),
    "talking_head": Preset(
        "Talking Head", Weights(0.5, 0.3, 0.2), 65.0, 0.8,
        motion_filter={MOTION_STATIC},
    ),
    "action_sports": Preset(
        "Ação/Esporte", Weights(0.3, 0.2, 0.5), 50.0, 0.3,
        motion_filter=None,  # ação tolera e até espera movimento — não filtra por tipo
    ),
    "product_still": Preset(
        "Produto/Still", Weights(0.35, 0.45, 0.2), 70.0, 1.0,
        motion_filter={MOTION_STATIC},
    ),
}


@dataclasses.dataclass
class ClipAnalysis:
    """Resultado completo da análise de um clipe: scores amostra-a-amostra,
    um hash perceptual representativo (pra detectar duplicatas entre clipes
    da timeline) e as flags de qualidade já detectadas dentro do próprio
    arquivo (exposição estourada, corte brusco)."""
    scores: List[FrameScore]
    clip_hash: Optional[int]
    flags: List[str]


def _resize_long_edge(frame: np.ndarray, max_edge: int = MAX_EDGE) -> np.ndarray:
    h, w = frame.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_edge:
        return frame
    scale = max_edge / long_edge
    return cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _focus_score(gray: np.ndarray) -> float:
    """Variância do Laplaciano: quanto maior, mais bordas nítidas e de alto contraste.

    Calibração: valores na faixa 0-2000 cobrem a maior parte de filmagem real
    (testado com conteúdo sintético nítido vs. desfocado). Mapeado em escala
    logarítmica para 0-100 porque a variância cresce muito rápido.
    """
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    variance = lap.var()
    # log1p comprime a cauda longa; 500 é o ponto de meio-score calibrado empiricamente
    score = 100.0 * (np.log1p(variance) / np.log1p(500.0 * 4))
    return float(np.clip(score, 0, 100))


def _exposure_score(gray: np.ndarray) -> Tuple[float, float]:
    """Penaliza pixels estourados (>=250) e cortados (<=5) no histograma.

    Retorna (score, clipped_fraction) — a fração bruta é usada depois pra
    gerar a flag de "exposição estourada" sem recalcular o histograma.
    """
    total = gray.size
    clipped_low = np.count_nonzero(gray <= 5)
    clipped_high = np.count_nonzero(gray >= 250)
    clipped_fraction = (clipped_low + clipped_high) / total
    score = 100.0 * (1.0 - min(clipped_fraction * 3.0, 1.0))
    return float(np.clip(score, 0, 100)), float(clipped_fraction)


def _classify_motion(flow: np.ndarray) -> Tuple[float, str]:
    """Classifica o campo de fluxo óptico denso em estático / pan-tilt / zoom.

    Heurística de visão clássica (sem ML): compara a magnitude média do
    fluxo com um piso de ruído pra decidir se há movimento; se houver,
    compara o fluxo com o campo radial (vetores apontando do centro da
    imagem pra cada pixel) — alta correlação com esse campo radial é zoom
    (tudo se afasta/aproxima do centro), baixa correlação é deslocamento
    numa direção predominante (pan/tilt).
    """
    h, w = flow.shape[:2]
    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    mean_mag = float(magnitude.mean())
    if mean_mag < _STATIC_MAGNITUDE_PX:
        return mean_mag, MOTION_STATIC

    # Correlação com o campo radial (unitário, apontando do centro pra cada
    # pixel). Importante: usamos a média do produto escalar COM sinal, não
    # o valor absoluto — um deslocamento uniforme (pan puro) aponta "pra
    # fora" do centro numa metade da imagem e "pra dentro" na outra, então
    # essas contribuições se cancelam na média assinada (fica perto de 0).
    # Um zoom de verdade aponta radialmente em todo lugar (tudo se afasta
    # ou tudo se aproxima do centro), então a média assinada fica grande
    # (positiva = zoom out, negativa = zoom in). Usar abs(dot) antes de
    # tirar a média, em vez disso, infla a correlação até de um pan puro
    # (testado e corrigido).
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2.0, h / 2.0
    radial_x = (xx - cx)
    radial_y = (yy - cy)
    radial_norm = np.sqrt(radial_x ** 2 + radial_y ** 2) + 1e-6
    radial_x = radial_x / radial_norm
    radial_y = radial_y / radial_norm

    dot = flow[..., 0] * radial_x + flow[..., 1] * radial_y
    radial_corr = float(dot.mean()) / (mean_mag + 1e-6)

    if abs(radial_corr) >= _ZOOM_RADIAL_CORR:
        return mean_mag, MOTION_ZOOM
    return mean_mag, MOTION_PAN_TILT


def _motion_score(prev_gray: Optional[np.ndarray], gray: np.ndarray) -> Tuple[float, str]:
    """Fluxo óptico denso entre a amostra anterior e a atual.

    Score alto = câmera parada (como a sub-métrica "Camera Motion" do Cutdown,
    onde Active→Still e menos movimento pontua mais alto). Primeiro frame do
    clipe não tem referência anterior, então recebe score neutro (100) e tipo
    estático por padrão.
    """
    if prev_gray is None:
        return 100.0, MOTION_STATIC
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, gray, None,
        pyr_scale=0.5, levels=3, winsize=15, iterations=3,
        poly_n=5, poly_sigma=1.2, flags=0,
    )
    mean_mag, motion_type = _classify_motion(flow)
    # 8px de deslocamento médio por amostra já é bastante movimento; acima disso satura em 0
    score = 100.0 * (1.0 - min(mean_mag / 8.0, 1.0))
    return float(np.clip(score, 0, 100)), motion_type


def _avg_hash(gray: np.ndarray, size: int = 8) -> int:
    """Hash perceptual simples (average hash) de 64 bits: redimensiona pra
    8x8, compara cada pixel com a média e empacota os bits resultantes num
    inteiro. Clipes visualmente parecidos (ex.: mesmo take duplicado na
    mídia) produzem hashes com poucos bits diferentes (baixa distância de
    Hamming), mesmo com leve diferença de compressão/corte."""
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    mean = small.mean()
    bits = (small > mean).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def analyze_video(
    path: str,
    sample_rate_hz: float = 4.0,
    weights: Weights = Weights(),
    progress_cb=None,
) -> ClipAnalysis:
    """Analisa um arquivo de vídeo e retorna scores, hash perceptual (pra
    detecção de duplicata entre clipes) e flags de qualidade (exposição
    estourada / corte brusco) encontradas dentro do próprio arquivo.

    progress_cb, se fornecido, é chamado com (frames_done, frames_total) a
    cada amostra — para a UI mostrar progresso sem travar.
    """
    # Força o backend FFmpeg (decodificação por software) em vez do backend
    # padrão do Windows (Media Foundation / MSMF), que usa decodificação por
    # hardware (GPU). Rodando dentro do processo do Resolve — que já usa a
    # GPU pesadamente pra decodificar/exibir o mesmo clipe na timeline — o
    # MSMF trava o processo inteiro (confirmado: 0% de CPU, Resolve inteiro
    # sem responder; o mesmo cv2.VideoCapture rodando fora do Resolve, num
    # Python comum, abre e lê o mesmo arquivo em menos de 1 segundo).
    cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = frame_count / fps if fps > 0 else 0.0

    step_s = 1.0 / sample_rate_hz if sample_rate_hz > 0 else 1.0
    sample_times = list(np.arange(0.0, duration_s, step_s))
    if not sample_times or sample_times[-1] < duration_s - step_s:
        sample_times.append(max(0.0, duration_s - 1.0 / fps))

    w = weights.normalized()
    results: List[FrameScore] = []
    flags: List[str] = []
    prev_gray = None
    clip_hash: Optional[int] = None
    overexposed_samples = 0

    for i, t in enumerate(sample_times):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame = _resize_long_edge(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if clip_hash is None:
            clip_hash = _avg_hash(gray)

        focus = _focus_score(gray)
        exposure, clipped_fraction = _exposure_score(gray)
        motion, motion_type = _motion_score(prev_gray, gray)
        overall = w.focus * focus + w.exposure * exposure + w.motion * motion

        hard_cut = False
        if prev_gray is not None:
            # Mesmo tamanho desde _resize_long_edge, então dá pra comparar direto.
            diff = float(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)).mean())
            if diff >= _HARD_CUT_DIFF:
                hard_cut = True
                flags.append(f"corte brusco em {t:.1f}s")

        if clipped_fraction >= 0.15:
            overexposed_samples += 1

        results.append(FrameScore(t, focus, exposure, motion, overall, motion_type, hard_cut))
        prev_gray = gray

        if progress_cb:
            progress_cb(i + 1, len(sample_times))

    cap.release()

    if results and overexposed_samples / len(results) >= 0.3:
        flags.insert(0, "exposição estourada")

    return ClipAnalysis(scores=results, clip_hash=clip_hash, flags=flags)


def detect_duplicate_clips(clip_hashes: Dict[str, Optional[int]]) -> Dict[str, List[str]]:
    """Compara o hash perceptual de cada clipe contra todos os outros e
    retorna, pra cada caminho de clipe, a lista de nomes de outros clipes
    que parecem ser duplicatas (mesmo take regravado/reimportado)."""
    duplicates: Dict[str, List[str]] = {path: [] for path in clip_hashes}
    paths = [p for p, h in clip_hashes.items() if h is not None]
    for i, path_a in enumerate(paths):
        for path_b in paths[i + 1:]:
            dist = hamming_distance(clip_hashes[path_a], clip_hashes[path_b])
            if dist <= _DUPLICATE_HAMMING_MAX:
                duplicates[path_a].append(path_b)
                duplicates[path_b].append(path_a)
    return duplicates


def build_segments(
    scores: List[FrameScore],
    threshold: float = 60.0,
    min_duration_s: float = 0.5,
    dip_tolerance_s: float = 0.5,
    motion_filter: Optional[Set[str]] = None,
) -> List[Segment]:
    """Agrupa amostras que passam no limiar em segmentos (selects).

    dip_tolerance_s: por quanto tempo um trecho pode cair abaixo do limiar
    antes de quebrar o segmento em dois (equivalente ao "Dip length" do
    Cutdown — evita que uma única amostra fraca corte um take bom ao meio).

    motion_filter: se informado (ex. {"static"}), só considera amostras cujo
    tipo de movimento está no conjunto — usado pelo filtro "Só estático" /
    "Só com movimento" da UI e pelos presets (Talking Head força estático,
    Ação/Esporte aceita qualquer tipo).
    """
    if not scores:
        return []

    segments: List[Segment] = []
    current_start: Optional[float] = None
    current_scores: List[float] = []
    last_pass_time: Optional[float] = None

    def flush(end_time: float):
        nonlocal current_start, current_scores
        if current_start is not None and current_scores:
            if end_time - current_start >= min_duration_s:
                segments.append(Segment(current_start, end_time, float(np.mean(current_scores))))
        current_start = None
        current_scores = []

    for score in scores:
        passed = score.overall >= threshold
        if passed and motion_filter is not None:
            passed = score.motion_type in motion_filter
        if passed:
            if current_start is None:
                current_start = score.time_s
            current_scores.append(score.overall)
            last_pass_time = score.time_s
        else:
            if current_start is not None and last_pass_time is not None:
                if score.time_s - last_pass_time > dip_tolerance_s:
                    flush(last_pass_time)

    if current_start is not None and last_pass_time is not None:
        flush(last_pass_time)

    return segments
