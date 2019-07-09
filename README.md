# prometheus-reconfig
Reconfigure a prometheus instance via API

Uses the [IceCube Token Service](https://github.com/WIPACrepo/token-service) for authorization.

## Env Variables

PROMETHEUS_*_CONFIGFILE : The service to be updated, named by the wildcard.
  This should be a Prometheus SD target file.

TOKEN_SERVICE : The url for the IceCube Token Service.

## Run

Run the script by doing (for example):

    PROMETHEUS_SD_CONFIGFILE=/etc/prometheus/sd.conf \
      TOKEN_SERVICE=https://tokens.icecube.wisc.edu \
      python prometheus_reconfig.py

## Docker

Docker can be used to run as well:

    docker run --rm -v /etc/prometheus/sd.conf:/etc/prometheus/sd.conf \
      -e PROMETHEUS_SD_CONFIGFILE=/etc/prometheus/sd.conf \
      -e TOKEN_SERVICE=https://tokens.icecube.wisc.edu \
      wipac/prometheus-reconfig
