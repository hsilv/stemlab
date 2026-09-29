"""Run inside the API container with the worker and broker running."""

from stemlab.worker import ping

result = ping.delay().get(timeout=30)
assert result == {"status": "ok", "worker": "stemlab"}, result
print("Queue -> worker -> result backend: OK")
