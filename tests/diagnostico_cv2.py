"""Diagnostico isolado: testa se o OpenCV consegue abrir e ler o clipe de
camera FORA do DaVinci Resolve, pra isolar se o travamento e do cv2/codec
ou de alguma coisa especifica da integracao com o Resolve.

Como usar (fora do Resolve, num PowerShell/cmd normal):
    python diagnostico_cv2.py "C:\\caminho\\para\\C8920.MP4"

Se travar aqui tambem (sem nenhum print depois de "Abrindo..."), o problema
e do cv2/codec nesse arquivo, nao da integracao com o Resolve. Se rodar
rapido e completo, o problema e especifico de rodar dentro do Resolve.
"""
import sys
import time

if len(sys.argv) < 2:
    print("Uso: python diagnostico_cv2.py \"caminho\\do\\video.mp4\"")
    sys.exit(1)

path = sys.argv[1]

print("Importando cv2...", flush=True)
t0 = time.time()
import cv2  # noqa: E402
print(f"  cv2 {cv2.__version__} importado em {time.time() - t0:.2f}s", flush=True)

print(f"Abrindo (backend FFmpeg, igual ao Titan Cut agora): {path}", flush=True)
t0 = time.time()
cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
print(f"  VideoCapture() retornou em {time.time() - t0:.2f}s", flush=True)

print(f"  isOpened() = {cap.isOpened()}", flush=True)

fps = cap.get(cv2.CAP_PROP_FPS)
frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
print(f"  fps={fps} frame_count={frame_count}", flush=True)

print("Lendo o primeiro frame (cap.read())...", flush=True)
t0 = time.time()
ok, frame = cap.read()
print(f"  read() retornou em {time.time() - t0:.2f}s — ok={ok} frame={None if frame is None else frame.shape}", flush=True)

print("Buscando (seek) pro meio do video (cap.set + read)...", flush=True)
t0 = time.time()
cap.set(cv2.CAP_PROP_POS_MSEC, 4000.0)
ok, frame = cap.read()
print(f"  seek+read retornou em {time.time() - t0:.2f}s — ok={ok}", flush=True)

cap.release()
print("Concluido sem travar.", flush=True)
