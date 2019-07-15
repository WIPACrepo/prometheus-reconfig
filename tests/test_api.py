import os
import asyncio

import pytest
import requests
import tornado.web
from tornado.httpclient import HTTPRequest
import tornado.testing
from rest_tools.client import RestClient

import prometheus_reconfig


CONFIG = {
    'AUTH_ISSUER': None,
    'AUTH_SECRET': 'secret',
}
for k in CONFIG:
    if k in os.environ:
        CONFIG[k] = os.environ[k]


@pytest.fixture(params=['', 'test'])
def config(monkeypatch, request, tmp_path):
    name = request.param
    filename = str(tmp_path / (name + '.json'))
    if name:
        with open(filename, 'w') as f:
            f.write('[]')
        monkeypatch.setenv(f'PROMETHEUS_{name}_CONFIGFILE', filename)
    yield name
    if name:
        monkeypatch.delenv(f'PROMETHEUS_{name}_CONFIGFILE')

@pytest.fixture
def http_server_port():
    """
    Port used by `http_server`.
    """
    return tornado.testing.bind_unused_port()[-1]

@pytest.fixture
async def rest(monkeypatch, http_server_port):
    """Provide RestClient as a test fixture."""
    monkeypatch.setenv("AUTH_ALGORITHM", "HS512")
    if CONFIG['AUTH_ISSUER']:
        monkeypatch.setenv("AUTH_ISSUER", CONFIG['AUTH_ISSUER'])
    monkeypatch.setenv("AUTH_SECRET", CONFIG['AUTH_SECRET'])
    monkeypatch.setenv("ADDRESS", "localhost")
    monkeypatch.setenv("PORT", str(http_server_port))

    c = prometheus_reconfig.configs()
    server = prometheus_reconfig.app(c)
    server.startup(port=http_server_port)

    def client(role='admin', timeout=0.1):
        if CONFIG['AUTH_ISSUER']:
            r = requests.get(CONFIG['AUTH_ISSUER']+'/token',
                             params={'scope': f'prometheus:{role}'})
            r.raise_for_status()
            t = r.json()['access']
        else:
            raise Exception('testing token service not defined')
        print(t)
        return RestClient(f'http://localhost:{http_server_port}', token=t, timeout=timeout, retries=0)

    yield client
    server.stop()
    await asyncio.sleep(0.01)

@pytest.mark.asyncio
async def test_many(config, rest):
    r = rest()
    ret = await r.request('GET', '/')
    if config:
        assert len(ret) == 1

@pytest.mark.asyncio
async def test_one(config, rest):
    r = rest()
    if config:
        ret = await r.request('GET', '/test')
        assert len(ret['targets']) == 0

        targets = ['foo:1234', 'bar:5678']
        await r.request('PUT', '/test', {'targets':targets})
        ret = await r.request('GET', '/test')
        assert ret['targets'] == targets
    else:
        with pytest.raises(requests.exceptions.HTTPError):
            ret = await r.request('GET', '/test')
            