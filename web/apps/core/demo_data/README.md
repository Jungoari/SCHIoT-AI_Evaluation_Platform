# 데모 데이터 출처

순천향대학교 딥러닝 수업 미니프로젝트 1~4 와 같은 공개 데이터셋을 데모 크기로 줄인 것 (`scripts/prepare_demo_data.py` 로 생성)

| 파일 | 프로젝트 | 원본 | 라이선스 | 데모 크기 |
|---|---|---|---|---|
| `fashion_mnist.npz` | 1. 패션 MNIST 분류 | Fashion-MNIST (Zalando Research) 훈련셋 | MIT | 6,000장 (학습 4,500 · 평가 1,500) |
| `har.npz` | 2. 스마트폰 행동 인식 | UCI Human Activity Recognition Using Smartphones (Kaggle 판 train.csv) | CC BY 4.0 | 4,000행 (학습 3,000 · 평가 1,000), 특성 float16 |
| `kc_house_data.csv.gz` | 3. 킹 카운티 집값 | House Sales in King County, USA (Kaggle) | CC0 1.0 | 21,613행 전체 (학습 17,613 · 평가 4,000) |
| `winequality_red.csv` | 4. 레드 와인 품질 | UCI Wine Quality (Cortez et al., 2009) | CC BY 4.0 | 1,599행 전체 (학습 1,199 · 평가 400) |

- 학습/평가 분리는 `apps/core/demo.py` 에서 고정 시드로 한다. 평가용의 정답 열은 교수만 볼 수 있는 저장소에 보관되고, 학생에게는 정답을 뺀 평가용 입력 데이터만 배포된다
- 수업에서는 학생이 훈련셋으로 직접 5-폴드 교차 검증을 하고 그 평균을 점수로 냈다. 이 플랫폼은 **숨겨 둔 평가용 정답으로 공식 점수를 매기고**, 학생이 출력한 교차 검증 결과는 검토 근거(무결성 검사 I-8)로 쓴다
