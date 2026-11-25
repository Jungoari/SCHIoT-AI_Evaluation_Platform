"""
데모 대회용 데이터 준비 (한 번만 실행 → web/apps/core/demo_data/ 에 저장해 저장소에 포함)

딥러닝 수업 미니프로젝트 1~4 와 같은 공개 데이터셋을 데모 크기로 줄여 저장한다.
원본 경로는 인자로 받는다 (정원 PC 의 수업 폴더·Keras 캐시).

    .venv/bin/python scripts/prepare_demo_data.py \\
        --fashion ~/.keras/datasets/fashion-mnist \\
        --har  "~/Desktop/SCH UNIV./3학년/3-2/머신러닝/ML-miniProject/2/train.csv" \\
        --kc   "~/Desktop/SCH UNIV./3학년/3-2/머신러닝/ML-miniProject/무제 폴더/kc_house_data.csv" \\
        --wine "~/Desktop/SCH UNIV./3학년/3-2/머신러닝/ML-miniProject/4/winequality-red.csv"
"""

import argparse
import gzip
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "web" / "apps" / "core" / "demo_data"
SEED = 2026


def fashion(src: Path, n: int):
    # Keras 원본(idx 형식)에서 훈련셋만 읽어 n 개 표본 (수업 규칙: 훈련셋만 사용)
    with gzip.open(src / "train-images-idx3-ubyte.gz") as f:
        X = np.frombuffer(f.read(), np.uint8, offset=16).reshape(-1, 784)
    with gzip.open(src / "train-labels-idx1-ubyte.gz") as f:
        y = np.frombuffer(f.read(), np.uint8, offset=8)
    idx = np.random.default_rng(SEED).choice(len(y), n, replace=False)
    np.savez_compressed(OUT / "fashion_mnist.npz", X=X[idx], y=y[idx])


def har(src: Path, n: int):
    df = pd.read_csv(src)
    df = df.sample(n=n, random_state=SEED).reset_index(drop=True)
    feats = df.drop(columns=["subject", "Activity"]).astype(np.float32)
    np.savez_compressed(OUT / "har.npz", X=feats.to_numpy(np.float16), y=df["Activity"].to_numpy(str),
                        columns=np.array(feats.columns, dtype=str))


def kc(src: Path):
    df = pd.read_csv(src)
    df.to_csv(OUT / "kc_house_data.csv.gz", index=False, compression="gzip")


def wine(src: Path):
    pd.read_csv(src).to_csv(OUT / "winequality_red.csv", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fashion", type=Path, required=True)
    ap.add_argument("--har", type=Path, required=True)
    ap.add_argument("--kc", type=Path, required=True)
    ap.add_argument("--wine", type=Path, required=True)
    ap.add_argument("--fashion-n", type=int, default=6000)
    ap.add_argument("--har-n", type=int, default=4000)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fashion(a.fashion.expanduser(), a.fashion_n)
    har(a.har.expanduser(), a.har_n)
    kc(a.kc.expanduser())
    wine(a.wine.expanduser())
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:28} {p.stat().st_size / 1024:8.0f} KB")
