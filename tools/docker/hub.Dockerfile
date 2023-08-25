FROM newswangerd/galaxy_ng_demo

ENV PULP_AAP_GATEWAY_KEY=https://localhost:9080
ENV PULP_GALAXY_AUTHENTICATION_CLASSES="['aap.gateway.auth.JWTAuthentication']"
ENV PULP_AAP_GATEWAY_VALIDATE_CERT=false
ENV PULP_HTTPS=true
ENV GALAXY_PORT=5043

COPY service_lib/ /opt/service_lib/
RUN pip install /opt/service_lib