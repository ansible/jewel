#!/bin/bash
printf 'eda-server up check \n-----------\n'
while : ; do
    curl -k --head --fail http://localhost:8010/api/eda/v1/auth/session/login/
    [ $? -eq 0 ] && break
    sleep 3
done
printf 'UP\n'
