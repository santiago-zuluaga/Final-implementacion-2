"""Verify a durable RabbitMQ queue retains a persistent message across restart."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
base = os.getenv("RABBIT_MANAGEMENT_URL", "http://localhost:15672").rstrip("/")
auth = (os.environ["RABBIT_USER"], os.environ["RABBIT_PASSWORD"])
vhost = "%2F"
queue = f"acceptance.persistence.{uuid.uuid4().hex}"
payload = f"credimarket-persistence-probe-{uuid.uuid4().hex}"


def wait_management():
    for _ in range(30):
        try:
            response = requests.get(f"{base}/api/overview", auth=auth, timeout=2)
            response.raise_for_status()
            return
        except requests.RequestException:
            time.sleep(1)
    raise RuntimeError("RabbitMQ Management did not become healthy")


queue_url = f"{base}/api/queues/{vhost}/{queue}"


def peek(ackmode):
    response = requests.post(f"{queue_url}/get", auth=auth, json={
        "count": 1, "ackmode": ackmode, "encoding": "auto", "truncate": 50000,
    }, timeout=5)
    response.raise_for_status()
    messages = response.json()
    return messages[0]["payload"] if messages else None


try:
    response = requests.put(queue_url, auth=auth, json={"durable": True, "auto_delete": False, "arguments": {}}, timeout=5)
    response.raise_for_status()
    response = requests.post(f"{base}/api/exchanges/{vhost}/amq.default/publish", auth=auth, json={
        "properties": {"delivery_mode": 2}, "routing_key": queue,
        "payload": payload, "payload_encoding": "string",
    }, timeout=5)
    response.raise_for_status()
    if not response.json().get("routed"):
        raise RuntimeError("RabbitMQ did not route the persistent probe")
    before = peek("ack_requeue_true")
    if before != payload:
        raise AssertionError("Persistent probe was not readable before restart")

    subprocess.run(["docker", "compose", "restart", "rabbitmq"], cwd=ROOT, check=True, capture_output=True, text=True)
    wait_management()
    details = requests.get(queue_url, auth=auth, timeout=5).json()
    after = peek("ack_requeue_false")
    if after != payload or not details["durable"]:
        raise AssertionError("Persistent message or durable queue did not survive restart")
    report = {"queue_durable": details["durable"], "persistent_message_survived": after == payload, "message_read_before_restart": before == payload, "message_read_after_restart": after == payload, "passed": True}
finally:
    try:
        requests.delete(queue_url, auth=auth, timeout=5)
    except requests.RequestException:
        pass

(ROOT / "artifacts" / "rabbit_persistence_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
