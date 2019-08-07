import os
import json
import asyncio

import pytest
import requests
import tornado.web
from tornado.httpclient import HTTPRequest
import tornado.testing
from rest_tools.client import RestClient

import prometheus_reconfig


@pytest.fixture(params=['', 'test'])
def config(monkeypatch, request, tmp_path):
    name = request.param
    cfgfile = str(tmp_path / 'prometheus_reconfig.json')
    filename = str(tmp_path / (name + '.json'))
    if name:
        with open(filename, 'w') as f:
            f.write('[]')
        with open(cfgfile, 'w') as f:
            json.dump({
              "services": [
                {
                    "name": name,
                    "filename": filename,
                }
              ]
            }, f)
        monkeypatch.setenv(f'CONFIGFILE', cfgfile)
    yield name
    if name:
        monkeypatch.delenv(f'CONFIGFILE')

@pytest.fixture
def http_server_port():
    """
    Port used by `http_server`.
    """
    return tornado.testing.bind_unused_port()[-1]

@pytest.fixture
async def rest(monkeypatch, http_server_port):
    """Provide RestClient as a test fixture."""
    monkeypatch.setenv("ADDRESS", "localhost")
    monkeypatch.setenv("PORT", str(http_server_port))
    monkeypatch.setenv("AUTH_SECRET", "")

    c = prometheus_reconfig.configs()
    server = prometheus_reconfig.app(c)
    server.startup(port=http_server_port)

    def client(timeout=0.1):
        return RestClient(f'http://localhost:{http_server_port}', timeout=timeout, retries=0)

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

        targets2 = ['baz:91011']
        await r.request('PUT', '/test/comp1', {'targets':targets2})
        ret = await r.request('GET', '/test')
        assert ret['targets'] == targets2+targets
        ret = await r.request('GET', '/test/comp1')
        assert ret['targets'] == targets2

        targets3 = ['wut:9675']
        await r.request('PATCH', '/test/comp1', {'targets':targets3})
        ret = await r.request('GET', '/test')
        assert ret['targets'] == targets3+targets2+targets
        ret = await r.request('GET', '/test/comp1')
        assert ret['targets'] == targets3+targets2

        await r.request('DELETE', '/test/comp1')
        ret = await r.request('GET', '/test/comp1')
        assert ret['targets'] == []
        ret = await r.request('GET', '/test')
        assert ret['targets'] == targets

        await r.request('DELETE', '/test')
        ret = await r.request('GET', '/test')
        assert ret['targets'] == []
    else:
        with pytest.raises(requests.exceptions.HTTPError):
            ret = await r.request('GET', '/test')
            