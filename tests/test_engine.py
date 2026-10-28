"""Teste de verdade do motor contra vídeo sintético (não é mock).

Gera (via tests/fixtures, criado por ffmpeg antes de rodar este arquivo)
um clipe de 9s: 3s nítido, 3s desfocado, 3s escuro — mesmo padrão de
movimento/conteúdo nos três trechos, só varia foco/exposição. Isso isola
cada métrica e prova que o motor realmente discrimina, em vez de assumir.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "Modules"))

from titan_cut_engine import analyze_video, build_segments, Weights  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.mp4")


def mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    scores = analyze_video(FIXTURE, sample_rate_hz=4.0)
    assert scores, "Nenhuma amostra retornada — engine não leu o vídeo"

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

    print("\nTODOS OS TESTES PASSARAM — motor discrimina foco e exposição corretamente.")


if __name__ == "__main__":
    main()
