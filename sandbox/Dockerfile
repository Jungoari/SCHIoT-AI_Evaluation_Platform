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
# 버전 고정: 재빌드해도 같은 노트북이 같은 결과를 내야 격리 재실행(I-6) 비교가 의미 있다
# pandas·numpy·scikit-learn·joblib·nbformat 은 web/requirements.txt 와 같은 버전으로 맞춘다 (가중치 파일 호환)
RUN pip install "pandas==3.1.1" "numpy==2.5.5" "scikit-learn==1.9.1" "joblib==1.6.0" "nbclient==0.11.0" "nbformat==5.11.1" \
    "ipykernel==7.4.0" "matplotlib==3.11.2" ${EXTRA_PACKAGES} \
 && python -m ipykernel install --prefix /usr/local --name python3
COPY run.py /runner/run.py
USER 65534:65534
WORKDIR /work/input
CMD ["python", "/runner/run.py"]
