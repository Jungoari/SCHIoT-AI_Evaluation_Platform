# ------------------------------------------------------------
# 참여자 노트북 격리 실행 이미지
#  - 네트워크·권한은 실행 시 docker run 옵션으로 차단 (apps/integrity/sandbox.py)
#  - 정답 파일은 이 이미지에도, 실행 폴더에도 들어가지 않는다
#  - PyTorch/TensorFlow 모델도 검증하려면 아래 EXTRA_PACKAGES 에 추가해 빌드
# ------------------------------------------------------------
FROM python:3.13-slim
ARG EXTRA_PACKAGES=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp JUPYTER_RUNTIME_DIR=/tmp/jupyter IPYTHONDIR=/tmp/ipython MPLCONFIGDIR=/tmp/mpl
RUN pip install "pandas>=2.2" "numpy>=2" "scikit-learn>=1.5" "joblib" "nbclient>=0.10" "nbformat>=5.10" \
    "ipykernel>=6" "matplotlib" ${EXTRA_PACKAGES} \
 && python -m ipykernel install --prefix /usr/local --name python3
COPY run.py /runner/run.py
USER 65534:65534
WORKDIR /work/input
CMD ["python", "/runner/run.py"]
