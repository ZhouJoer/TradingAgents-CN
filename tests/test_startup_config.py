from app.__main__ import parse_env_bind_values, parse_port_owner_pids


def test_parse_env_bind_values_reads_host_and_port_without_settings_import():
    values = parse_env_bind_values([
        "# comment",
        "HOST='127.0.0.1'",
        'API_PORT="18000"',
        "MONGODB_PASSWORD=secret=value",
        "invalid-line",
    ])

    assert values["HOST"] == "127.0.0.1"
    assert values["API_PORT"] == "18000"
    assert values["MONGODB_PASSWORD"] == "secret=value"
    assert "invalid-line" not in values


def test_parse_port_owner_pids_extracts_unique_listening_tcp_pids():
    output = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       1234
  TCP    [::]:8000              [::]:0                 LISTENING       1234
  TCP    127.0.0.1:8001         0.0.0.0:0              LISTENING       5678
  UDP    0.0.0.0:8000           *:*                                    9999
"""

    assert parse_port_owner_pids(output, 8000) == ["1234"]
