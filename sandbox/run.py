"""
샌드박스 안에서 실행되는 러너

- /work/input/notebook.ipynb 를 읽어 실행할 셀을 고른다
    'setup' 또는 'inference' 태그가 있으면 그 셀만 (학습 재실행 없이 추론만 → 검증 시간 단축)
    태그가 없으면 노트북 전체
- 결과 CSV 는 노트북이 환경 변수 OUTPUT_PATH(/work/output/submission.csv)에 저장해야 한다
"""

import sys
import time

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

NB_PATH = "/work/input/notebook.ipynb"
CELL_TIMEOUT = 240


def select_cells(nb):
    tagged = [c for c in nb.cells if c.cell_type == "code" and {"setup", "inference"} & set(c.metadata.get("tags", []))]
    if any("inference" in c.metadata.get("tags", []) for c in tagged):
        print(f"[runner] 태그 셀만 실행: {len(tagged)}개 (setup/inference)")
        return tagged
    code = [c for c in nb.cells if c.cell_type == "code"]
    print(f"[runner] inference 태그가 없어 전체 코드 셀 실행: {len(code)}개")
    return code


def main():
    nb = nbformat.read(NB_PATH, as_version=4)
    cells = select_cells(nb)
    for c in cells:
        c.outputs = []
        # IPython 셸 명령(!pip 등)은 네트워크가 없으므로 주석 처리
        c.source = "\n".join("# [sandbox] " + line if line.lstrip().startswith("!") else line for line in c.source.splitlines())
    nb.cells = cells
    started = time.monotonic()
    client = NotebookClient(nb, timeout=CELL_TIMEOUT, kernel_name="python3", allow_errors=False,
                            resources={"metadata": {"path": "/work/input"}})
    code = 0
    try:
        client.execute()
        print(f"[runner] 실행 완료 ({time.monotonic() - started:.1f}초)")
    except CellExecutionError as exc:
        print("[runner] 셀 실행 오류:")
        print(str(exc)[-3000:])
        code = 2
    except Exception as exc:  # 커널 시작 실패·메모리 초과로 커널 종료 등
        print(f"[runner] 실행 실패: {type(exc).__name__}: {exc}")
        code = 3
    finally:
        dump_outputs(nb)
    return code


def dump_outputs(nb):
    """셀 출력(텍스트)을 로그로 남겨 검토자가 확인할 수 있게 한다"""
    print("[runner] ---- 셀 출력 ----")
    for i, cell in enumerate(nb.cells, start=1):
        for out in cell.get("outputs", []):
            if out.get("output_type") == "stream":
                for line in str(out.get("text", "")).splitlines():
                    print(f"[cell {i}] {line}")
            elif out.get("output_type") == "error":
                print(f"[cell {i}] {out.get('ename')}: {out.get('evalue')}")


if __name__ == "__main__":
    sys.exit(main())
