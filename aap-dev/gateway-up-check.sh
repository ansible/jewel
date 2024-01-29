#!/bin/bash
printf 'Gateway up check '
until $(curl -k --output /dev/null --silent --head --fail https://localhost/api/gateway/v1/) ; do \
    printf '.' ; \
    sleep 3 ; \
done
printf 'UP\n'

