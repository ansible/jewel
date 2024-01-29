#!/bin/bash
printf 'AWX up check '
until $(curl -k --output /dev/null --silent --head --fail https://localhost:8043/api/v2/ping/) ; do \
    printf '.' ; \
    sleep 3 ; \
done
printf 'UP\n'
