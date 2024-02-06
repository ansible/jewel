#!/bin/bash
printf 'eda-server up check '
until $(curl --output /dev/null --silent --head --fail http://localhost:8010/api/eda/v1/ui_auth/) ; do \
    printf '.' ; \
    sleep 3 ; \
done
printf 'UP\n'
