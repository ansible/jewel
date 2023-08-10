FROM quay.io/centos/centos:stream9

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en

ARG DJANGO_SETTINGS_MODULE=project.settings
ENV DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE

RUN dnf install -y \
    gcc \
    python3-devel \
    python3 \
    python3-pip \
    libpq \
    libpq-devel \
    postgresql \
    less

RUN dnf module install -y nginx/common

RUN dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    dnf install -y inotify-tools && \
    dnf remove -y epel-release && \
    dnf clean all

RUN mkdir /var/run/uwsgi
RUN /usr/bin/python3 -m pip --no-cache-dir install supervisor
RUN /usr/bin/python3 -m venv /opt/venv
RUN echo "/opt/aap-gateway" > /opt/venv/lib/python3.9/site-packages/project.pth
# See: https://github.com/advisories/GHSA-r9hx-vwmv-q579
RUN /opt/venv/bin/pip install --upgrade 'setuptools>=65.5.1'
COPY requirements/requirements.txt /opt/
RUN /opt/venv/bin/pip --no-cache-dir install -r/opt/requirements.txt

COPY . /opt/aap-gateway

COPY tools/scripts/launch-gateway /usr/bin/launch-gateway
COPY tools/scripts/auto-reload /usr/bin/auto-reload
COPY tools/configs/nginx.conf /etc/nginx/nginx.conf
COPY tools/configs/nginx-gateway.conf /etc/nginx/conf.d/gateway.conf
COPY tools/scripts/gateway-manage /usr/bin/gateway-manage
COPY tools/configs/uwsgi.ini /etc/gateway/uwsgi.ini
COPY tools/configs/supervisord.conf /etc/supervisor/supervisord.conf

RUN for dir in \
      /var/log/supervisor \
      /var/run/supervisor \
      /var/run/uwsgi \
      /opt/aap-gateway \
      /var/log/nginx \
      /var/run/django_metrics ; \
    do mkdir -p $dir ; chgrp -R 0 $dir; chmod -R g=u $dir ; done && \
    echo "\setenv PAGER 'less -SXF'" > /etc/psqlrc

USER 1000
EXPOSE 8000

WORKDIR /opt
CMD /usr/bin/launch-gateway
