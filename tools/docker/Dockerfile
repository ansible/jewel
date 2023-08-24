ARG PYTHON=python3.11

FROM quay.io/centos/centos:stream9 as builder
ARG PYTHON

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en

RUN dnf install -y \
    gcc \
    ${PYTHON}-devel \
    ${PYTHON} \
    ${PYTHON}-pip \
    libpq \
    libpq-devel \
    postgresql \
    less

RUN for dir in \
      /opt/aap_gateway; \
    do mkdir -p $dir && chgrp -R 0 $dir && chmod -R g=u $dir ; done

RUN /usr/bin/${PYTHON} -m venv /opt/aap_gateway/venv
RUN echo "/opt/aap_gateway/aap_gateway" > /opt/aap_gateway/venv/lib/${PYTHON}/site-packages/project.pth

# See: https://github.com/advisories/GHSA-r9hx-vwmv-q579
RUN /opt/aap_gateway/venv/bin/pip install --upgrade 'setuptools>=65.5.1'

COPY requirements/requirements.txt /tmp/requirements.txt
RUN /opt/aap_gateway/venv/bin/pip --no-cache-dir install -r /tmp/requirements.txt

FROM quay.io/centos/centos:stream9
ARG PYTHON

RUN dnf module install -y nginx/common && \
    dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm  && \
    dnf install -y \
    inotify-tools \
    less \
    libpq \
    postgresql \
    ${PYTHON} \
    ${PYTHON}-pip \
    supervisor

COPY --from=builder /opt/aap_gateway /opt/aap_gateway
COPY tools/scripts/launch-gateway /usr/bin/launch-gateway
COPY tools/scripts/auto-reload /usr/bin/auto-reload
COPY tools/configs/nginx.conf /etc/nginx/nginx.conf
COPY tools/configs/nginx.crt /etc/nginx/nginx.crt
COPY tools/configs/nginx.key /etc/nginx/nginx.key
COPY tools/configs/nginx-gateway.conf /etc/nginx/conf.d/gateway.conf
COPY tools/scripts/gateway-manage /usr/bin/gateway-manage
COPY tools/configs/uwsgi.ini /etc/gateway/uwsgi.ini
COPY tools/configs/supervisord.conf /etc/supervisord.conf

RUN for dir in \
      /etc/nginx \
      /opt/aap_gateway \
      /var/log/supervisor \
      /var/run/supervisor \
      /var/run/uwsgi \
      /var/log/nginx \
      /var/run/django_metrics ; \
    do mkdir -m 0775 -p $dir ; chmod g+rwx $dir ; chgrp root $dir ; done && \
    for file in \
      /etc/nginx/nginx.crt \
      /etc/nginx/nginx.key ; \
    do touch $file ; chmod g+rw $file ; chgrp root $file ; done

USER 1000
EXPOSE 8000

WORKDIR /opt
CMD /usr/bin/launch-gateway
