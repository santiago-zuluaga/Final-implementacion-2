"""Small, read-only cache benchmark for the three seeded demo products."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env = os.environ.copy()
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                env.setdefault(key.strip(), value.strip())
    return env


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


def docker_stats(services):
    ids = {}
    for service in services:
        result = subprocess.run(['docker', 'compose', 'ps', '-q', service], cwd=ROOT, check=True, capture_output=True, text=True)
        ids[service] = result.stdout.strip()
    result = subprocess.run(
        ['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}', *ids.values()],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    rows = {}
    for line in result.stdout.splitlines():
        name, cpu, memory, memory_pct = line.split('|', 3)
        service = next((key for key, value in ids.items() if value[:12] in name or name.endswith(f'-{key}-1')), name)
        rows[service] = {'container': name, 'cpu': cpu.strip(), 'memory': memory.strip(), 'memory_percent': memory_pct.strip()}
    return rows


def timed_get(session, url):
    start = time.perf_counter()
    response = session.get(url, timeout=5)
    response.raise_for_status()
    return (time.perf_counter() - start) * 1000


def main():
    env = load_env()
    base = os.environ.get('CREDIMARKET_PRODUCTS_URL', 'http://localhost:8001').rstrip('/')
    customers = os.environ.get('CREDIMARKET_CUSTOMERS_URL', 'http://localhost:8002').rstrip('/')
    session = requests.Session()
    login = session.post(f'{customers}/auth/login', json={
        'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD'],
    }, timeout=5)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    before_metrics = session.get(f'{base}/cache/metrics', headers=headers, timeout=5).json()
    before_stats = docker_stats(['products', 'postgres', 'redis'])

    ids = [1, 2, 3]
    misses = []
    for product_id in ids:
        for _ in range(10):
            subprocess.run(
                ['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}'],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            misses.append(timed_get(session, f'{base}/products/{product_id}'))

    hits = [timed_get(session, f'{base}/products/{ids[i % len(ids)]}') for i in range(200)]
    after_stats = docker_stats(['products', 'postgres', 'redis'])
    after_metrics = session.get(f'{base}/cache/metrics', headers=headers, timeout=5).json()

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'method': 'sequential read-only HTTP requests; 30 forced misses (10 per product) followed by 200 warm-cache reads',
        'products': ids,
        'latency_ms': {
            'miss': {'n': len(misses), 'p50': percentile(misses, .50), 'p95': percentile(misses, .95), 'min': round(min(misses), 3), 'max': round(max(misses), 3)},
            'hit': {'n': len(hits), 'p50': percentile(hits, .50), 'p95': percentile(hits, .95), 'min': round(min(hits), 3), 'max': round(max(hits), 3)},
        },
        'cache_counter_delta': {key: after_metrics[key] - before_metrics[key] for key in ('hits', 'misses', 'fallbacks')},
        'process_metrics': {key: after_metrics[key] for key in ('hit_rate', 'p50_ms', 'p95_ms')},
        'docker_stats_snapshot_before': before_stats,
        'docker_stats_snapshot_after': after_stats,
        'limitations': [
            'single local run; sequential traffic, not a capacity or production load test',
            'docker stats CPU is an instantaneous snapshot; memory is the current resident usage',
            'cache hit/miss counters are process-local and reset when Products restarts',
        ],
    }
    target = ROOT / 'artifacts' / 'redis_benchmark.json'
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'Wrote {target.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
