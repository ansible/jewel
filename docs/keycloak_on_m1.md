## Keycloak Images on M1 Macs

At the time of this writing, keycloak has an existing [issue](https://github.com/keycloak/keycloak/issues/11543) with Macs using M1 chips. As a workaround, you can use the pre-built image for M1 Macs from https://quay.io/rh_ee_dtoirov/m1/keycloak. You need to change `keycloak_image` in [container_config.yml](../tools/ansible/vars/container_config.yml) to point to this keycloak image: `keycloak_image: quay.io/rh_ee_dtoirov/m1/keycloak`.

 Alternatively, you can also build the keycloak image locally on your M1 Mac by following the below steps:

1. Clone Keycloak containers repository: `git clone git@github.com:keycloak/keycloak-containers.git`
2. Open server directory: `cd keycloak-containers/server`
3. Checkout at desired version, eg. `git checkout 15.0.2`
4. Build docker image: `docker build -t jboss/keycloak:15.0.2 .`
5. Replace `keycloak_image` in [container_config.yml](../tools/ansible/vars/container_config.yml) to point to your locally built keycloak image: `keycloak_image: jboss/keycloak`


References:
- https://github.com/docker/for-mac/issues/5310#issuecomment-877653653