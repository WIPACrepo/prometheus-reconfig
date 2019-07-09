FROM python:3.7-alpine as base

FROM base as builder

RUN mkdir /install
WORKDIR /install

RUN apk add --no-cache git gcc musl-dev libffi-dev openssl-dev

ENV PYTHONPATH=/install/lib/python3.7/site-packages
COPY requirements.txt /requirements.txt
RUN pip install --prefix=/install -r /requirements.txt

FROM base as runtime

COPY --from=builder /install /usr/local
RUN ln -sT /usr/local /install

RUN addgroup -S app && adduser -S -G app app
USER app

WORKDIR /usr/src/app

COPY prometheus_reconfig.py ./

CMD [ "python", "./prometheus_reconfig.py" ]
