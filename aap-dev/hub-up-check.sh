#!/bin/bash
printf 'Hub up check \n-----------\n'
while : ; do
    curl -k --head --fail http://localhost:5001/healthz
    [ $? -eq 0 ] && break
    sleep 3
done
printf 'UP\n'
