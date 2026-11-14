import json
from pathlib import Path


def test_functions_registered_without_cloud_connection(monkeypatch):
    monkeypatch.setenv("IMAGE_QUEUE_NAME", "image-analysis")
    import function_app

    functions = function_app.app.get_functions()
    bindings = [json.loads(fn.get_function_json())["bindings"] for fn in functions]
    types = [binding["type"] for group in bindings for binding in group]
    assert types.count("httpTrigger") == 1
    assert types.count("queueTrigger") == 2
    assert types.count("timerTrigger") == 3
    http = next(b for group in bindings for b in group if b["type"] == "httpTrigger")
    assert http["authLevel"].lower() == "anonymous"
    config = json.loads((Path(__file__).resolve().parents[1] / "host.json").read_text())
    assert config["extensions"]["http"]["routePrefix"] == ""
    assert config["extensions"]["queues"]["messageEncoding"] == "base64"
