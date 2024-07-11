# Gateway deployment using pre-built images and rootless podman
To support rootless podman installation using prebuilt images you need
to do the following

The redis and envoy proxy images are pulled from brew.registry.redhat.io
So we need to login to brew.registry.redhat.io
Please see the following link for documentation
https://source.redhat.com/groups/public/teamnado/wiki/brew_registry

The gateway image is pulled from a private quay.io repository so we
need to login to quay.io

```
podman login quay.io
podman login brew.registry.redhat.io 
```

We have noticed that docker-compose v2 has issues with pulling images
from brew.registry.redhat.io. You can either use docker compose v1 or
switch to using podman-compose

## Export environment variables for podman
The defaults are tailored to use docker but if you want to use podman
you need to set the following environment variables. 

```shell
export DOCKER_COMPOSE=podman-compose
`````

## Generate the container-startup.yml file for podman

```shell
make container-startup-podman.yml
`````

## Adjust the services you want to start. The line below is just starting the EDA along with gateway service.

```shell
gateway_services: [eda]
`````

## Start containers
We are using pre-built images we need to generate keys and certificates,
the following command generates all the necessary files sets the password and and starts up all the containers.
The container-startup.yml is mounted to the gateway container.
```shell
make docker-compose-stage
`````

## Register services
Once all the containers are started we need to register services with gateway using the following command
```shell
make register-services
`````

## Create and fetch a service key
Once all the containers are started we need to fetch a new service key. The components will use it to resync shared data.
```shell
make fetch-service-key
`````
Store the service key from the output. For EDA, the key will be set to the env variable: EDA_RESOURCE_SERVER__SECRET_KEY``

## Migrate data to EDA 
Once EDA service starts, we need to push sharing data to it
```shell
make migrate-service-data
`````

# UI
To login to the Gateway UI you would password which is stored in the file container-startup.yml
- https://localhost:8443

## cleanup containers
```shell
make docker-compose-stage-cleanup
````


## Local builds
If you have made local changes and want to use your local build of gateway you need to update `gateway_image` inside the generated container-startup.yml

