"""Exercise the built image with disposable PostgreSQL/storage; never use local guide data.

Usage: python3 scripts/smoke_production.py [image]
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def wait_for(check, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, urllib.error.URLError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise RuntimeError('Timed out waiting for smoke-test service.')


def pdf():
    content = b'BT /F1 12 Tf 50 700 Td (Synthetic guide: cartons must not exceed 50 lb.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    data, offsets = b'%PDF-1.4\n', [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


def main(image):
    prefix = 'parse-smoke-' + uuid4().hex[:10]
    containers = []
    network = volume = None
    try:
        network = docker('network', 'create', prefix)
        volume = docker('volume', 'create', prefix)
        db = docker('run', '-d', '--network', network, '--name', prefix + '-db',
            '-e', 'POSTGRES_USER=routing', '-e', 'POSTGRES_PASSWORD=smoke-only-password',
            '-e', 'POSTGRES_DB=routing', 'postgres:17-bookworm')
        containers.append(db)
        wait_for(lambda: subprocess.run(['docker', 'exec', db, 'pg_isready', '-U', 'routing', '-d', 'routing'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        common = ['--network', network, '-v', volume + ':/data', '-e',
                  f'DATABASE_URL=postgresql+psycopg://routing:smoke-only-password@{prefix}-db:5432/routing',
                  '-e', 'ANTHROPIC_API_KEY=smoke-only-key']
        docker('run', '--rm', *common, image, 'python', '-m', 'routing_guides.bootstrap')
        api = docker('run', '-d', *common, '-p', '127.0.0.1::8000', image)
        containers.append(api)
        worker = docker('run', '-d', *common, image, 'python', '-m', 'routing_guides.worker')
        containers.append(worker)
        port = json.loads(docker('inspect', api))[0]['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
        base = 'http://127.0.0.1:' + port

        def request(path, body=None, method=None, content_type='application/json'):
            data = json.dumps(body).encode() if isinstance(body, dict) else body
            return urllib.request.urlopen(urllib.request.Request(base + path, data=data, method=method,
                headers={'Content-Type': content_type, 'X-Requested-With': 'routing-guide-parser'}), timeout=10)

        wait_for(lambda: request('/api/health/ready').status == 200)
        assert b'<html' in request('/').read()
        connections = json.load(request('/api/connections'))
        assert all(c['credential_managed'] for c in connections)
        assert b'smoke-only-key' not in json.dumps(connections).encode()
        request('/api/connections/anthropic', {'key': None, 'model': 'smoke-model'}, 'PUT')
        try:
            request('/api/connections/anthropic', {'key': 'replacement', 'model': 'bad'}, 'PUT')
            raise AssertionError('Managed credential edit was accepted')
        except urllib.error.HTTPError as exc:
            assert exc.code == 422
        request('/api/settings', {'max_upload_mb': 512}, 'PUT')
        docker('run', '--rm', *common, image, 'python', '-m', 'routing_guides.bootstrap')
        assert json.load(request('/api/settings'))['max_upload_mb'] == 512
        assert next(c for c in json.load(request('/api/connections')) if c['id'] == 'anthropic')['model'] == 'smoke-model'
        library = json.load(request('/api/guides'))
        boundary = uuid4().hex
        body = b''
        for name, value in {'retailer_id': library['retailers'][0]['id'], 'title': 'Synthetic smoke guide'}.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
        body += pdf() + f'\r\n--{boundary}--\r\n'.encode()
        guide = json.load(request('/api/guides', body, 'POST', 'multipart/form-data; boundary=' + boundary))['guide']
        wait_for(lambda: json.load(request('/api/guides/' + guide['id']))['status'] == 'ready')
        run = json.load(request(f'/api/guides/{guide["id"]}/analysis',
            {'provider': 'manual', 'request_id': str(uuid4())}, 'POST'))
        assert run['status'] == 'complete' and len(run['payload']['coverage']) == 1
        docker('exec', worker, 'python', '-m', 'routing_guides.worker_health')
        print('Production smoke passed: UI/API, managed secrets, persistent preferences, migrations, PDF upload/preparation and worker health.')
    finally:
        for container in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', '-v', container], check=False, stdout=subprocess.DEVNULL)
        if volume:
            subprocess.run(['docker', 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
        if network:
            subprocess.run(['docker', 'network', 'rm', network], check=False, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'parse-production:local')
