import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routing_guides.frontend import mount_frontend


class FrontendTests(unittest.TestCase):
    def test_ui_and_api_share_origin_without_hiding_missing_api_or_assets(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'index.html').write_text('<html>PARSE</html>')
            (root / 'assets').mkdir()
            (root / 'assets' / 'app.js').write_text('window.parse = true;')
            app = FastAPI()

            @app.get('/api/health/ready')
            def ready():
                return {'status': 'ready'}

            mount_frontend(app, root)
            with TestClient(app) as client:
                self.assertIn('PARSE', client.get('/').text)
                self.assertIn('window.parse', client.get('/assets/app.js').text)
                self.assertEqual(client.get('/api/health/ready').json(), {'status': 'ready'})
                self.assertEqual(client.get('/api/missing').status_code, 404)
                self.assertEqual(client.get('/assets/missing.js').status_code, 404)
                self.assertNotIn('PARSE', client.get('/%2e%2e/alembic.ini').text)
