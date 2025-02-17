#!/bin/bash
printf 'Lightspeed up check \n-----------\n'
while : ; do
    curl -k --head --fail http://localhost:7080/api/v1/health/
    [ $? -eq 0 ] && break
    sleep 3
done
printf 'UP\n'
