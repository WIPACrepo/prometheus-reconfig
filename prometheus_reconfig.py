"""
Reconfigure prometheus SD configs via http.

ENV Args:
    CONFIGFILE = path to prometheus_reconfig json file
    AUTH_SECRET = auth secret
    AUTH_ISSUER = auth issuer (default: IceCube token service)
    AUTH_ALGORITHM = auth algorithm (default: RS256)

Config file format (json):
{
  "services": [
    {
        "name": <service name>,
        "filename": <path to sd config file>
    }
  ]
}
"""

import os
import json
import logging
from functools import partial

from rest_tools.client import json_decode
from rest_tools.server import RestServer, RestHandler, RestHandlerSetup, scope_role_auth
from tornado.web import HTTPError
from tornado.ioloop import IOLoop


### first, handle prometheus sd configs
# [
#     {
#         "targets": [ "$HOSTNAME" ],
#         "labels": {
#             "service": "$SERVICENAME",
#             "component": "$COMPONENTNAME"
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

    def get(self, component=None):
        targets = []
        with open(self.filename) as f:
            data = json.load(f)
            logging.debug('get(%s) %r', self.filename, data)
            for s in data:
                if s['labels']['service'] == self.name:
                    if (component and s['labels'].get('component','') == component) or not component:
                        targets.extend(s['targets'])
        return targets

    def set_service(self, targets):
        """
        Overwrite targets for all components.
        
        Args:
            targets (list): list of targets
        """
        data = []
        if targets:
            data.append({
                'targets': targets,
                'labels': {'service': self.name},
            })
        with open(self.filename) as f:
            old_data = json.load(f)
        for s in old_data:
            if s['labels']['service'] != self.name:
                data.append(s)
        logging.debug('set(%s) %r', self.filename, data)
        with open(self.filename, 'w') as f:
            json.dump(data, f)

    def set_component(self, component, targets):
        """
        Overwrite targets for a single component.

        Args:
            component (str): name of component
            targets (list): list of targets
        """
        data = []
        if targets:
            data.append({
                'targets': targets,
                'labels': {'service': self.name, 'component': component},
            })
        with open(self.filename) as f:
            old_data = json.load(f)
        for s in old_data:
            if s['labels']['service'] != self.name or s['labels'].get('component','') != component:
                data.append(s)
        logging.debug('set(%s) %r', self.filename, data)
        with open(self.filename, 'w') as f:
            json.dump(data, f)

    def add_component(self, component, targets):
        """
        Append to targets for a single component.

        Args:
            component (str): name of component
            targets (list): list of targets
        """
        data = [{
            'targets': targets,
            'labels': {'service': self.name, 'component': component},
        }]
        with open(self.filename) as f:
            old_data = json.load(f)
        for s in old_data:
            if s['labels']['service'] == self.name and s['labels'].get('component','') == component:
                data[0]['targets'].extend(s['targets'])
            else:
                data.append(s)
        logging.debug('set(%s) %r', self.filename, data)
        with open(self.filename, 'w') as f:
            json.dump(data, f)


### now do the http server

role_auth = partial(scope_role_auth, prefix='prometheus-reconfig')

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

class ServiceConfig(MyHandler):
    @role_auth(roles=['read'])
    async def get(self, service):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        ret = self.prom_configs[service].get()
        self.write({'targets':ret})

    @role_auth(roles=['write'])
    async def put(self, service):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        req = json_decode(self.request.body)
        if 'targets' not in req:
            raise HTTPError(400, reason='missing "targets" param')
        targets = req['targets']
        if not isinstance(targets, list):
            raise HTTPError(400, reason='"targets" param is not a list')
        self.prom_configs[service].set_service(targets)
        self.write({})

    @role_auth(roles=['write'])
    async def delete(self, service):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        targets = []
        self.prom_configs[service].set_service(targets)
        self.write({})

class ComponentConfig(MyHandler):
    @role_auth(roles=['read'])
    async def get(self, service, component):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        ret = self.prom_configs[service].get(component)
        self.write({'targets':ret})

    @role_auth(roles=['write'])
    async def put(self, service, component):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        req = json_decode(self.request.body)
        if 'targets' not in req:
            raise HTTPError(400, reason='missing "targets" param')
        targets = req['targets']
        if not isinstance(targets, list):
            raise HTTPError(400, reason='"targets" param is not a list')
        self.prom_configs[service].set_component(component, targets)
        self.write({})

    @role_auth(roles=['write'])
    async def patch(self, service, component):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        req = json_decode(self.request.body)
        if 'targets' not in req:
            raise HTTPError(400, reason='missing "targets" param')
        targets = req['targets']
        if not isinstance(targets, list):
            raise HTTPError(400, reason='"targets" param is not a list')
        self.prom_configs[service].add_component(component, targets)
        self.write({})

    @role_auth(roles=['write'])
    async def delete(self, service, component):
        if service not in self.prom_configs:
            raise HTTPError(404, reason='config not found')
        targets = []
        self.prom_configs[service].set_component(component, targets)
        self.write({})


### now configure

def configs():
    prom_configs = {}
    cfgfile = os.environ.get('CONFIGFILE', '/etc/prometheus_reconfig.json')
    try:
        data = json.load(open(cfgfile))
    except Exception:
        print('could not open cfgfile at', cfgfile)
        data = {'services':[]}
    prom_configs = {args['name']:PromConfig(**args) for args in data['services']}
    config = {
        'prom_config': prom_configs,
        'auth': {
            'secret': os.environ.get('AUTH_SECRET'),
            'issuer': os.environ.get('AUTH_ISSUER', 'https://tokens.icecube.wisc.edu'),
            'algorithm': os.environ.get('AUTH_ALGORITHM', 'RS512'),
        },
        'address': os.environ.get('ADDRESS', ''),
        'port': int(os.environ.get('PORT', '8080')),
        'loglevel': os.environ.get('LOGLEVEL', 'INFO'),
    }
    return config

def app(config):
    kwargs = RestHandlerSetup(config)
    kwargs.update({'prom_configs': config['prom_config']})
    logging.info('services available:'
    for service in kwargs['prom_configs']:
        logging.info('   %s', service)
    server = RestServer()
    server.add_route(r'/', AllConfigs, kwargs)
    server.add_route(r'/(?P<service>\w+)', ServiceConfig, kwargs)
    server.add_route(r'/(?P<service>\w+)/(?P<component>\w+)', ComponentConfig, kwargs)
    return server

def main():
    config = configs()
    logging.basicConfig(level=config['loglevel'])
    server = app(config)
    server.startup(address=config['address'], port=config['port'])
    IOLoop.current().start()

if __name__ == '__main__':
    main()
