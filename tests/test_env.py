from houseedge.env import load_dotenv


def test_load_dotenv_loads_values_and_preserves_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nBASE_RPC_URL=https://example.invalid/rpc\n"
        "ENVIO_API_TOKEN='secret-token'\n"
        "export OTHER_VALUE=hello\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BASE_RPC_URL", "already-set")
    loaded = load_dotenv(env)
    assert loaded == env
    assert __import__("os").environ["BASE_RPC_URL"] == "already-set"
    assert __import__("os").environ["ENVIO_API_TOKEN"] == "secret-token"
    assert __import__("os").environ["OTHER_VALUE"] == "hello"
