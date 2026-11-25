"""
docker-compose.yml 보안 구성 회귀 테스트

Docker 소켓은 'docker-proxy' 한 곳에만 연결되어야 하고, 샌드박스 워커는 root 가 아닌 사용자로
프록시를 거쳐서만 컨테이너를 띄워야 한다. 누군가 실수로 소켓을 다시 직접 연결하면 이 테스트가 실패한다.
(YAML 라이브러리 없이 들여쓰기로 서비스 블록을 나눈다)
"""

from pathlib import Path

import pytest

COMPOSE = Path(__file__).resolve().parents[4] / "docker-compose.yml"


def _blocks(text: str) -> dict[str, str]:
    """최상위 'services:' 아래 서비스 이름 → 해당 서비스 설정 문자열"""
    services, current, section = {}, None, None
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")):
            section = line.rstrip(":")
            current = None
            continue
        if section == "services" and line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":") \
                and not line.strip().startswith("#"):
            current = line.strip().rstrip(":")
            services[current] = ""
            continue
        if section == "services" and current:
            services[current] += line + "\n"
    return services


@pytest.fixture(scope="module")
def services():
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml 없음 (저장소 밖에서 실행)")
    return _blocks(COMPOSE.read_text(encoding="utf-8"))


def test_docker_socket_only_in_proxy_and_read_only(services):
    with_socket = [name for name, body in services.items() if "docker.sock" in body]
    assert with_socket == ["docker-proxy"]
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in services["docker-proxy"]


def test_proxy_allows_only_containers(services):
    proxy = services["docker-proxy"]
    assert "CONTAINERS: 1" in proxy
    for denied in ("IMAGES", "VOLUMES", "NETWORKS", "EXEC", "INFO"):
        assert f"{denied}: 0" in proxy, denied
    # 프록시는 외부와 단절된 전용 망에만 연결
    assert "- docker-api" in proxy and "- default" not in proxy


def test_sandbox_worker_non_root_and_uses_proxy(services):
    sw = services["sandbox-worker"]
    assert "DOCKER_HOST: tcp://docker-proxy:2375" in sw
    assert "user:" not in sw  # 이미지 기본 사용자(app, uid 1000) 로 실행
    assert "labels" not in sw  # 정답 볼륨 없음


def test_only_sandbox_worker_can_reach_proxy(services):
    reach = [name for name, body in services.items() if "- docker-api" in body]
    assert sorted(reach) == ["docker-proxy", "sandbox-worker"]


def test_docker_api_network_is_internal():
    text = COMPOSE.read_text(encoding="utf-8")
    net = text[text.index("\nnetworks:"):text.index("\nvolumes:")]
    assert "docker-api:" in net and "internal: true" in net
