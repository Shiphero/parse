"""Library checks use synthetic records in a rollback-only transaction."""
from datetime import date, datetime, timezone, timedelta
from io import BytesIO
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from routing_guides import guides_api
from routing_guides.config import get_settings
from routing_guides.models import Guide, Retailer
from routing_guides.retailer_icons import MAX_ICON_BYTES, normalize_icon


def picture(fmt='PNG', size=(240, 120), color='red'):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, format=fmt)
    return output.getvalue()


class IconImageTests(unittest.TestCase):
    def test_formats_are_resized_and_normalized_without_trailing_content(self):
        for fmt in ('PNG', 'JPEG', 'WEBP'):
            with self.subTest(format=fmt):
                icon = normalize_icon(picture(fmt) + b'<script>not image content</script>')
                with Image.open(BytesIO(icon)) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, (128, 64))
                    self.assertFalse(image.info)
                self.assertNotIn(b'<script>', icon)

    def test_invalid_oversized_and_high_pixel_inputs_are_rejected(self):
        for content in (b'', b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                        b'x' * (MAX_ICON_BYTES + 1), picture(size=(2001, 2000)), picture('GIF')):
            with self.subTest(size=len(content)):
                with self.assertRaises(ValueError):
                    normalize_icon(content)


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(get_settings().database_url.get_secret_value())
        self.conn = await self.engine.connect()
        self.transaction = await self.conn.begin()
        self.sessions = async_sessionmaker(self.conn, expire_on_commit=False, join_transaction_mode='create_savepoint')
        self.patch = patch.object(guides_api, 'sessions', self.sessions)
        self.patch.start()
        self.app = FastAPI(); self.app.include_router(guides_api.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')
        self.retailer = 'test-' + uuid4().hex
        self.name = 'Retailer ' + uuid4().hex
        async with self.sessions.begin() as session:
            session.add(Retailer(id=self.retailer, name=self.name, discovery_note='Rollback-only fixture'))
            await session.flush()
            for i in range(301):
                session.add(Guide(id=uuid4(), retailer_id=self.retailer, title=f'Guide {i:03}',
                    filename=f'file-{i}.pdf', sha256=uuid4().hex, size_bytes=1,
                    version_label='Special release' if i == 0 else None,
                    status='failed' if i == 300 else 'ready',
                    effective_date=None if i == 0 else date(2025, 1, 1) + timedelta(days=i),
                    created_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)))

    async def asyncTearDown(self):
        await self.client.aclose(); self.patch.stop()
        await self.transaction.rollback(); await self.conn.close(); await self.engine.dispose()

    async def library(self, **params):
        response = await self.client.get('/api/guides', params={'retailer_id': self.retailer, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_large_library_paginates_without_skipping_or_repeating(self):
        ids = []
        for offset in (0, 100, 200, 300):
            result = await self.library(limit=100, offset=offset, sort='title', direction='asc')
            self.assertEqual(result['total'], 301)
            ids.extend(row['id'] for row in result['items'])
            self.assertEqual(result['items'][0]['title'], f'Guide {offset:03}')
        self.assertEqual(len(ids), 301)
        self.assertEqual(len(set(ids)), 301)
        self.assertFalse((await self.library(offset=400))['items'])

    async def test_search_filters_and_sort_apply_before_pagination(self):
        self.assertEqual((await self.library(q=self.name))['total'], 301)
        self.assertEqual((await self.library(q='Special release'))['total'], 1)
        self.assertEqual((await self.library(q='file-300.pdf', status='failed'))['total'], 1)
        self.assertEqual((await self.library(q='file-300.pdf', status='ready'))['total'], 0)
        self.assertEqual((await self.library(q='%'))['total'], 0)
        self.assertEqual((await self.library(sort='title', direction='desc'))['items'][0]['title'], 'Guide 300')
        for direction in ('asc', 'desc'):
            result = await self.library(sort='effective_date', direction=direction, offset=300)
            self.assertIsNone(result['items'][0]['effective_date'])
        for params in ({'sort': 'bad_column'}, {'direction': 'invalid'}, {'limit': 101}):
            response = await self.client.get('/api/guides', params=params)
            self.assertEqual(response.status_code, 422)

    async def test_icons_persist_replace_and_remove_with_no_guide_changes(self):
        endpoint = f'/api/retailers/{self.retailer}/icon'
        headers = {'X-Requested-With': 'routing-guide-parser'}
        self.assertEqual((await self.client.get(endpoint)).status_code, 404)
        blocked = await self.client.put(endpoint, files={'file': ('icon.png', picture(), 'image/png')})
        self.assertEqual(blocked.status_code, 403)
        result = await self.client.put(endpoint, headers=headers, files={'file': ('icon.png', picture(), 'image/png')})
        self.assertEqual(result.status_code, 200, result.text)
        url = result.json()['icon_url']
        library = await self.library()
        retailer = next(r for r in library['retailers'] if r['id'] == self.retailer)
        self.assertEqual(retailer['icon_url'], url)
        image = await self.client.get(url)
        self.assertEqual(image.headers['content-type'], 'image/png')
        self.assertEqual(image.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(Image.open(BytesIO(image.content)).size, (128, 64))
        replacement = await self.client.put(endpoint, headers=headers, files={'file': ('new.jpg', picture('JPEG', color='blue'), 'image/jpeg')})
        self.assertNotEqual(replacement.json()['icon_url'], url)
        invalid = await self.client.put(endpoint, headers=headers, files={'file': ('bad.png', b'<svg/>', 'image/png')})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual((await self.client.get(endpoint)).status_code, 200)
        missing = await self.client.put('/api/retailers/no-such-retailer/icon', headers=headers, files={'file': ('x.png', picture(), 'image/png')})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual((await self.client.delete(endpoint)).status_code, 403)
        removed = await self.client.delete(endpoint, headers=headers)
        self.assertEqual(removed.json(), {'icon_url': None})
        self.assertEqual((await self.client.get(endpoint)).status_code, 404)
        self.assertEqual((await self.library())['total'], 301)

    async def test_create_retailer_normalizes_name_and_initializes_release_head(self):
        from routing_guides.models import ReleaseHead
        headers = {'X-Requested-With': 'routing-guide-parser'}
        name = 'New Retailer ' + uuid4().hex
        blocked = await self.client.post('/api/retailers', json={'name': name})
        self.assertEqual(blocked.status_code, 403)
        result = await self.client.post('/api/retailers', headers=headers, json={'name': '  ' + name.replace(' ', '  ') + '  '})
        self.assertEqual(result.status_code, 201, result.text)
        retailer = result.json()
        self.assertEqual(retailer['name'], name)
        self.assertEqual(retailer['guide_count'], 0)
        self.assertIsNone(retailer['icon_url'])
        async with self.sessions() as session:
            self.assertIsNotNone(await session.get(ReleaseHead, retailer['id']))
        duplicate = await self.client.post('/api/retailers', headers=headers, json={'name': name.upper()})
        self.assertEqual(duplicate.status_code, 409)
        listed = await self.client.get('/api/retailers')
        self.assertIn(retailer, listed.json())
        library = await self.library()
        self.assertIn(retailer, library['retailers'])
        for bad_name in ('', '   ', 'x' * 101):
            response = await self.client.post('/api/retailers', headers=headers, json={'name': bad_name})
            self.assertEqual(response.status_code, 422)

    async def test_rename_keeps_guides_icons_and_id_and_rejects_stale_or_duplicate_names(self):
        headers = {'X-Requested-With': 'routing-guide-parser'}
        endpoint = f'/api/retailers/{self.retailer}'
        icon = await self.client.put(endpoint + '/icon', headers=headers, files={'file': ('icon.png', picture(), 'image/png')})
        renamed = 'Renamed ' + uuid4().hex
        payload = {'name': renamed, 'expected_name': self.name}
        self.assertEqual((await self.client.put(endpoint, json=payload)).status_code, 403)
        result = await self.client.put(endpoint, headers=headers, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['id'], self.retailer)
        self.assertEqual(result.json()['guide_count'], 301)
        self.assertEqual(result.json()['icon_url'], icon.json()['icon_url'])
        self.assertEqual((await self.library(q=renamed))['total'], 301)
        self.assertEqual((await self.client.put(endpoint, headers=headers, json=payload)).status_code, 409)
        second = 'Another ' + uuid4().hex
        await self.client.post('/api/retailers', headers=headers, json={'name': second})
        duplicate = await self.client.put(endpoint, headers=headers, json={'name': second.upper(), 'expected_name': renamed})
        self.assertEqual(duplicate.status_code, 409)
        missing = await self.client.put('/api/retailers/no-such-retailer', headers=headers, json=payload)
        self.assertEqual(missing.status_code, 404)
