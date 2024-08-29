#!/bin/bash
printf 'AWX up check \n-----------\n'
while : ; do
    curl -k --head --fail https://localhost:8043/api/v2/ping/
    [ $? -eq 0 ] && break
    sleep 3
done
printf 'UP\n'
