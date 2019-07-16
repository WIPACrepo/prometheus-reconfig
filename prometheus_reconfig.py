"""
Reconfigure prometheus SD configs via http.

ENV Args:
    PROMETHEUS_<name>_CONFIGFILE = <path to sd config file>
    AUTH_SECRET = auth secret
    AUTH_ISSUER = auth issuer (default: IceCube token service)
    AUTH_ALGORITHM = auth algorithm (default: RS256)
"""

import os
import json
import logging

from rest_tools.client import json_decode
from rest_tools.server import RestServer, RestHandler, scope_role_auth
from tornado.web import HTTPError
from tornado.ioloop import IOLoop


### first, handle prometheus sd configs
# [
#     {
#         "targets": [ "$HOSTNAME" ],
#         "labels": {
#             "service": "$SERVICENAME"
#         },
#     }
# ]


class PromConfig:
    def __init__(self, name, filename):
        if not os.path.exists(filename):
            raise Exception(f'file {filename} must exist')
        if not filename.endswith('.json'):
            raise Exception(f'file {filename} must be json')
        self.name = name
        self.filename = filename

    def get(self):
        with open(self.filename) as f:
            data = json.load(f)
            logging.debug('get(%s) %r', self.filename, data)
            for s in data:
                if s['labels']['service'] == self.name:
                    return s['targets']
        return []

    def set(self, targets):
        data = [{
            'targets': targets,
            'labels': {'service': self.name},
        }]
        with open(self.filename) as f:
            old_data = json.load(f)
        for s in old_data:
            if s['labels']['service'] != self.name:
                data.append(s)
        logging.debug('set(%s) %r', self.filename, data)
        with open(self.filename, 'w') as f:
            json.dump(data, f)


### now do the http server

role_auth = partial(scope_role_auth, perfix='prometheus-reconfig')

class MyHandler(RestHandler):
    def initialize(self, prom_configs=None, **kwargs):
        super(MyHandler, self).initialize(**kwargs)
        self.prom_configs = prom_configs

class AllConfigs(MyHandler):
    @role_auth(roles=['read'])
    async def get(self):
        ret = {}
        for n in self.prom_configs:
            ret[n] = self.prom_configs[n].get()
        self.write(ret)

class SingleConfig(MyHandler):
    @role_auth(roles=['read'])
    async def get(self, name):
        if name not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        ret = self.prom_configs[name].get()
        self.write({'targets':ret})

    @role_auth(roles=['write'])
    async def put(self, name):
        if name not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        req = json_decode(self.request.body)
        if 'targets' not in req:
            raise HTTPError(400, reason='missing "targets" param')
        targets = req['targets']
        if not isinstance(targets, list):
            raise HTTPError(400, reason='"targets" param is not a list')
        self.prom_configs[name].set(targets)
        self.write({})


### now configure

def configs():
    prom_configs = {}
    for e in os.environ:
        if e.startswith('PROMETHEUS_') and e.endswith('_CONFIGFILE'):
            name = '_'.join(e.split('_')[1:-1])
            filename = os.environ[e]
            prom_configs[name] = PromConfig(name, filename)
    config = {
        'prom_config': prom_configs,
        'auth': {
            'secret': os.environ.get('AUTH_SECRET'),
            'issuer': os.environ.get('AUTH_ISSUER', 'https://tokens.icecube.wisc.edu'),
            'algorithm': os.environ.get('AUTH_ALGORITHM', 'RS256'),
        },
        'address': os.environ.get('ADDRESS', ''),
        'port': int(os.environ.get('PORT', '8080')),
        'loglevel': os.environ.get('LOGLEVEL', 'INFO'),
    }
    return config

def app(config):
    kwargs = {'prom_configs': config['prom_config']}
    server = RestServer(auth=config['auth'])
    server.add_route(r'/', AllConfigs, kwargs)
    server.add_route(r'/(?P<name>[^\?]+)', SingleConfig, kwargs)
    return server

def main():
    config = configs()
    logging.basicConfig(level=config['loglevel'])
    server = app(config)
    server.startup(address=config['address'], port=config['port'])
    IOLoop.current().start()

if __name__ == '__main__':
    main()
