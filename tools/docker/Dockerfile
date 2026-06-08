ARG PYTHON=python3.12

FROM quay.io/centos/centos:stream9 AS builder
ARG PYTHON

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en

ARG DJANGO_SETTINGS_MODULE=aap_gateway_api.settings
ENV DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
ENV PYTHONUNBUFFERED=1

RUN sed -i '/^\[crb\]$/,/^enabled=0$/ s/enabled=0/enabled=1/' /etc/yum.repos.d/centos.repo && \
    dnf install -y \
    git \
    gcc \
    "${PYTHON}-devel" \
    "${PYTHON}" \
    "${PYTHON}-pip" \
    libpq \
    libpq-devel \
    libtool-ltdl-devel \
    openldap-devel \
    postgresql \
    less \
    xmlsec1-devel

RUN for dir in \
      /opt/aap_gateway; \
    do mkdir -p "$dir" && chgrp -R 0 "$dir" && chmod -R g=u "$dir" ; done

RUN "/usr/bin/${PYTHON}" -m venv /opt/aap_gateway/venv
RUN echo "/opt/aap_gateway/aap_gateway" > "/opt/aap_gateway/venv/lib/${PYTHON}/site-packages/project.pth"

# See: https://github.com/advisories/GHSA-r9hx-vwmv-q579
RUN /opt/aap_gateway/venv/bin/pip install --upgrade 'setuptools>=65.5.1'

COPY requirements/requirements.txt /tmp/requirements.txt
COPY requirements/requirements_git.txt /tmp/requirements_git.txt
RUN /opt/aap_gateway/venv/bin/pip --no-cache-dir install -r /tmp/requirements.txt
RUN /opt/aap_gateway/venv/bin/pip --no-cache-dir install -r /tmp/requirements_git.txt

FROM quay.io/centos/centos:stream9
ARG PYTHON

RUN dnf module install -y nginx:1.22/common && \
    dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm  && \
    dnf install -y \
    inotify-tools \
    less \
    libpq \
    postgresql \
    "${PYTHON}" \
    "${PYTHON}-pip" \
    supervisor \
    xmlsec1-openssl

COPY --from=builder /opt/aap_gateway /opt/aap_gateway
COPY tools/scripts/launch-gateway /usr/bin/launch-gateway
COPY tools/scripts/auto-reload /usr/bin/auto-reload
COPY tools/scripts/aap-gateway-manage /usr/bin/aap-gateway-manage
COPY tools/configs/nginx.conf /etc/ansible-automation-platform/gateway/nginx.conf
COPY tools/configs/nginx-gateway.conf /etc/ansible-automation-platform/gateway/nginx-gateway.conf
COPY tools/configs/uwsgi.ini /etc/ansible-automation-platform/gateway/uwsgi.ini
COPY tools/configs/supervisord.conf /etc/supervisord.conf
COPY tools/configs/settings.py /etc/ansible-automation-platform/gateway/settings.py


RUN for dir in \
      /etc/nginx \
      /opt/aap_gateway \
      /opt/aap_gateway/src \
      /var/log/supervisor \
      /var/run/supervisor \
      /var/run/uwsgi \
      /var/log/nginx \
      /var/run/django_metrics ; \
    do mkdir -m 0775 -p "$dir" ; chmod g+rwx "$dir" ; chgrp root "$dir" ; done && \
    for file in \
      /etc/nginx/gateway.crt \
      /etc/nginx/gateway.key ; \
    do touch "$file" ; chmod g+rw "$file" ; chgrp root "$file" ; done && \
    ln -s /usr/bin/aap-gateway-manage /usr/bin/gateway-manage

# This is required for the xds protobuf defintions in order for them
# to be compatible with protobuf 3.21+. This should be removed
# once a new version of xds-protos is available
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

COPY aap_gateway_api /opt/aap_gateway/src/aap_gateway_api/
ENV PATH=/opt/aap_gateway/venv/bin:$PATH
ENV PYTHONPATH=/opt/aap_gateway/src

# Pull in the platform-ui, this can change frequently so it should be one of the last things we try and do
COPY --from=quay.io/ansible/platform-ui:latest /usr/share/nginx/html /opt/aap_gateway/platform_ui

USER 1000
EXPOSE 8000

WORKDIR /opt
CMD ["/usr/bin/launch-gateway"]
