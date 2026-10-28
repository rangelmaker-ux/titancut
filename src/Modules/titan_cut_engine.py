"""Titan Cut — motor de análise de vídeo.

Lê um arquivo de vídeo diretamente do disco (não depende da API do Resolve
para acesso a pixels — a API de scripting do Resolve não expõe frames
decodificados), amostra frames, converte para escala de cinza reduzida e
calcula três métricas por amostra:

  - foco      (variância do Laplaciano — nitidez clássica em visão computacional)
  - exposição (fração de pixels estourados/cortados no histograma de luminância)
  - movimento (magnitude de fluxo óptico entre amostras consecutivas)

As três métricas combinam num score geral (0-100). Sequências contínuas de
frames acima do limiar viram "selects" (segmentos candidatos a manter).

Determinístico: a mesma entrada sempre produz a mesma saída. Sem IA/ML —
só processamento de imagem clássico, igual à abordagem do Cutdown (Softworks)
que inspirou este projeto.
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

import cv2
import numpy as np

MAX_EDGE = 960  # mesmo teto usado pelo Cutdown — equilíbrio entre precisão e velocidade


@dataclasses.dataclass
class FrameScore:
    time_s: float
    focus: float       # 0-100, mais alto = mais nítido
    exposure: float     # 0-100, mais alto = exposição mais equilibrada
    motion: float        # 0-100, mais alto = mais parado (como no Cutdown: Active→Still)
    overall: float

    def __repr__(self):
        return (f"FrameScore(t={self.time_s:.2f}s focus={self.focus:.1f} "
                f"exposure={self.exposure:.1f} motion={self.motion:.1f} "
                f"overall={self.overall:.1f})")


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


def _exposure_score(gray: np.ndarray) -> float:
    """Penaliza pixels estourados (>=250) e cortados (<=5) no histograma."""
    total = gray.size
    clipped_low = np.count_nonzero(gray <= 5)
    clipped_high = np.count_nonzero(gray >= 250)
    clipped_fraction = (clipped_low + clipped_high) / total
    score = 100.0 * (1.0 - min(clipped_fraction * 3.0, 1.0))
    return float(np.clip(score, 0, 100))


def _motion_score(prev_gray: Optional[np.ndarray], gray: np.ndarray) -> float:
    """Fluxo óptico denso entre a amostra anterior e a atual.

    Score alto = câmera parada (como a sub-métrica "Camera Motion" do Cutdown,
    onde Active→Still e menos movimento pontua mais alto). Primeiro frame do
    clipe não tem referência anterior, então recebe score neutro (100).
    """
    if prev_gray is None:
        return 100.0
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, gray, None,
        pyr_scale=0.5, levels=3, winsize=15, iterations=3,
        poly_n=5, poly_sigma=1.2, flags=0,
    )
    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    mean_mag = float(magnitude.mean())
    # 8px de deslocamento médio por amostra já é bastante movimento; acima disso satura em 0
    score = 100.0 * (1.0 - min(mean_mag / 8.0, 1.0))
    return float(np.clip(score, 0, 100))


def analyze_video(
    path: str,
    sample_rate_hz: float = 4.0,
    weights: Weights = Weights(),
    progress_cb=None,
) -> List[FrameScore]:
    """Analisa um arquivo de vídeo e retorna o score de cada amostra.

    progress_cb, se fornecido, é chamado com (frames_done, frames_total) a
    cada amostra — para a UI mostrar progresso sem travar.
    """
    cap = cv2.VideoCapture(path)
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
    prev_gray = None

    for i, t in enumerate(sample_times):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame = _resize_long_edge(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        focus = _focus_score(gray)
        exposure = _exposure_score(gray)
        motion = _motion_score(prev_gray, gray)
        overall = w.focus * focus + w.exposure * exposure + w.motion * motion

        results.append(FrameScore(t, focus, exposure, motion, overall))
        prev_gray = gray

        if progress_cb:
            progress_cb(i + 1, len(sample_times))

    cap.release()
    return results


def build_segments(
    scores: List[FrameScore],
    threshold: float = 60.0,
    min_duration_s: float = 0.5,
    dip_tolerance_s: float = 0.5,
) -> List[Segment]:
    """Agrupa amostras que passam no limiar em segmentos (selects).

    dip_tolerance_s: por quanto tempo um trecho pode cair abaixo do limiar
    antes de quebrar o segmento em dois (equivalente ao "Dip length" do
    Cutdown — evita que uma única amostra fraca corte um take bom ao meio).
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
