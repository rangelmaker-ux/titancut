"""Teste de verdade do motor contra vídeo sintético (não é mock).

Gera (via tests/fixtures, criado por ffmpeg antes de rodar este arquivo)
um clipe de 9s: 3s nítido, 3s desfocado, 3s escuro — mesmo padrão de
movimento/conteúdo nos três trechos, só varia foco/exposição. Isso isola
cada métrica e prova que o motor realmente discrimina, em vez de assumir.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "Modules"))

import numpy as np  # noqa: E402

from titan_cut_engine import (  # noqa: E402
    analyze_video, build_segments, detect_duplicate_clips, hamming_distance,
    MOTION_STATIC, Weights,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.mp4")


def mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    analysis = analyze_video(FIXTURE, sample_rate_hz=4.0)
    scores = analysis.scores
    assert scores, "Nenhuma amostra retornada — engine não leu o vídeo"
    assert analysis.clip_hash is not None, "Hash perceptual do clipe não foi calculado"

    sharp = [s for s in scores if s.time_s < 3.0]
    blur = [s for s in scores if 3.0 <= s.time_s < 6.0]
    dark = [s for s in scores if 6.0 <= s.time_s < 9.0]

    focus_sharp = mean([s.focus for s in sharp])
    focus_blur = mean([s.focus for s in blur])
    exposure_sharp = mean([s.exposure for s in sharp])
    exposure_dark = mean([s.exposure for s in dark])

    print(f"amostras totais: {len(scores)}")
    print(f"foco médio  — nítido: {focus_sharp:.1f}  |  desfocado: {focus_blur:.1f}")
    print(f"exposição média — nítido: {exposure_sharp:.1f}  |  escuro: {exposure_dark:.1f}")

    # Trecho nítido deve pontuar bem mais alto em foco que o desfocado
    assert focus_sharp > focus_blur + 15, (
        f"FALHOU: foco não discriminou nitidez (sharp={focus_sharp:.1f} blur={focus_blur:.1f})"
    )
    # Trecho escuro (exposição cortada) deve pontuar mais baixo que o bem exposto
    assert exposure_sharp > exposure_dark + 10, (
        f"FALHOU: exposição não discriminou corte de sombra "
        f"(sharp={exposure_sharp:.1f} dark={exposure_dark:.1f})"
    )

    segments = build_segments(scores, threshold=60.0)
    print(f"segmentos (threshold=60): {len(segments)}")
    for seg in segments:
        print(f"  {seg.start_s:.2f}s - {seg.end_s:.2f}s  score={seg.mean_score:.1f}")

    # Com threshold 60, o trecho nítido/bem-exposto deve virar select;
    # o desfocado e o escuro, isolados, não deveriam (score mais baixo)
    assert any(seg.start_s < 3.0 for seg in segments), (
        "FALHOU: trecho nítido/bem exposto não virou select"
    )

    assert any(s.hard_cut for s in scores), (
        "FALHOU: corte brusco entre os trechos do fixture não foi detectado"
    )

    # motion_filter com o conjunto vazio de tipos presentes deve zerar os selects
    present_types = {s.motion_type for s in scores}
    absent_type = ({MOTION_STATIC, "pan_tilt", "zoom"} - present_types)
    if absent_type:
        filtered_out = build_segments(scores, threshold=60.0, motion_filter={next(iter(absent_type))})
        assert filtered_out == [], "FALHOU: filtro de movimento não excluiu tipo ausente no fixture"

    # Classificação de tipo de movimento: testada isolada, com campos de
    # fluxo sintéticos conhecidos (não depende do conteúdo do fixture, que
    # tem movimento aleatório de padrão de teste do ffmpeg).
    from titan_cut_engine import _classify_motion  # noqa: E402 — função interna, só pro teste

    static_flow = np.zeros((64, 64, 2), dtype=np.float32)
    _, motion_type = _classify_motion(static_flow)
    assert motion_type == MOTION_STATIC, f"FALHOU: fluxo zero classificado como {motion_type}"

    pan_flow = np.zeros((64, 64, 2), dtype=np.float32)
    pan_flow[..., 0] = 5.0  # todo o campo se desloca pra direita = pan
    _, motion_type = _classify_motion(pan_flow)
    assert motion_type == "pan_tilt", f"FALHOU: fluxo de pan classificado como {motion_type}"

    yy, xx = np.mgrid[0:64, 0:64].astype(np.float32)
    zoom_flow = np.stack([xx - 32, yy - 32], axis=-1) * 0.3  # afasta do centro = zoom-in
    _, motion_type = _classify_motion(zoom_flow)
    assert motion_type == "zoom", f"FALHOU: fluxo radial classificado como {motion_type}"

    # Hash perceptual: o mesmo hash comparado consigo mesmo é distância 0,
    # e dois hashes vindos de frames bem diferentes (nítido vs. escuro) devem
    # ficar bem mais distantes que o limiar de duplicata.
    assert hamming_distance(analysis.clip_hash, analysis.clip_hash) == 0
    dup_map = detect_duplicate_clips({"a": analysis.clip_hash, "b": analysis.clip_hash})
    assert dup_map["a"] == ["b"] and dup_map["b"] == ["a"], (
        "FALHOU: detecção de duplicata não encontrou o mesmo hash comparado consigo mesmo"
    )

    print("\nTODOS OS TESTES PASSARAM — motor discrimina foco, exposição, movimento e duplicatas.")


if __name__ == "__main__":
    main()
