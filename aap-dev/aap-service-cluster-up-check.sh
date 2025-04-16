#!/bin/bash
SVC_NAME=$1
SVC_URL=$2
echo "AAP ${SVC_NAME} service up check"
echo "-----------"
while : ; do
    curl -k -s -o /dev/null -w "%{stderr}%{url} :: %{response_code} %{errormsg}\n" --fail "https://localhost/api/${SVC_URL}"
    [ $? -eq 0 ] && break
    sleep 3
done
echo "AAP ${SVC_NAME} service is UP"
