#!/bin/bash
printf 'Gateway up check \n-----------\n'
while : ; do
    curl -k --head --fail https://localhost/api/gateway/v1/
    [ $? -eq 0 ] && break
    sleep 3
done
printf 'UP\n'

