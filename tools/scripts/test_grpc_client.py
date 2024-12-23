#!/usr/bin/env python

import sys

import grpc
from envoy.service.auth.v3 import external_auth_pb2, external_auth_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = external_auth_pb2_grpc.AuthorizationStub(channel)

# The easiest way to get these bytes is to put a breakpoint into control_plane.py Check function
# Make a request and go into the debugger
# In there you should have a request object as a parameter
# request.SerializeToString()
# To see the request in plain text just display request and it will look like:
#      (Pdb) request
#      attributes {
#        source {
#          address {
#            socket_address {
#              address: "172.19.0.1"
#              port_value: 58060
#            }
#          }
#        }
#        destination {
#          address {
#            socket_address {
#              address: "172.19.0.5"
#              port_value: 9080
#            }
#          }
#          principal: "CN=localhost,OU=Gateway Development,O=Ansible,L=Durham,ST=North Carolina,C=US"
#        }
#        request {
#          time {
#            seconds: 1734617181
#            nanos: 337827968
#          }
#          http {
#            id: "2425209222661931451"
#            method: "POST"
#            headers {
#              key: ":authority"
#              value: "localhost"
#            }
#            headers {
#              key: ":method"
#              value: "POST"
#            }
#            headers {
#              key: ":path"
#              value: "/application/deployConfigs"
#            }
#            headers {
#              key: ":scheme"
#              value: "https"
#            }
#            headers {
#              key: "accept"
#              value: "*/*"
#            }
#            headers {
#              key: "accept-encoding"
#              value: "gzip, deflate, br"
#            }
#            headers {
#              key: "accept-language"
#              value: "en-us"
#            }
#            headers {
#              key: "content-length"
#              value: "71"
#            }
#            headers {
#              key: "content-type"
#              value: "application/json"
#            }
#            headers {
#              key: "user-agent"
#              value: "SteelSeries%20GG (unknown version) CFNetwork/1568.200.51 Darwin/24.1.0"
#            }
#            headers {
#              key: "x-envoy-auth-partial-body"
#              value: "false"
#            }
#            headers {
#              key: "x-envoy-internal"
#              value: "true"
#            }
#            headers {
#              key: "x-forwarded-for"
#              value: "172.19.0.1"
#            }
#            headers {
#              key: "x-forwarded-proto"
#              value: "https"
#            }
#            headers {
#              key: "x-request-id"
#              value: "9d932969-7840-4804-8ad4-5ff105b3ac13"
#            }
#            path: "/application/deployConfigs"
#            host: "localhost"
#            scheme: "https"
#            size: 71
#            protocol: "HTTP/1.1"
#            raw_body: "{\"path\":\"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\"}"
#          }
#        }
#        metadata_context {
#        }
#      }


bytes = b'\n\xa2\x06\n\x14\n\x12\n\x10\x12\n172.19.0.1\x18\xac\xeb\x03\x12b\n\x11\n\x0f\x12\n172.19.0.5\x18\xf8F"MCN=localhost,OU=Gateway Development,O=Ansible,L=Durham,ST=North Carolina,C=US"\xa3\x05\n\x0b\x08\xe6\x99\x91\xbb\x06\x10\xfb\xf7\xf26\x12\x93\x05\n\x1413960285231039457446\x12\x04POST\x1a\x0f\n\x07:method\x12\x04POST\x1a\x10\n\x07:scheme\x12\x05https\x1a\x1a\n\x11x-forwarded-proto\x12\x05https\x1a\x14\n\x0econtent-length\x12\x0278\x1a"\n\x19x-envoy-auth-partial-body\x12\x05false\x1a#\n\x05:path\x12\x1a/application/deployConfigs\x1a\x1d\n\x0fx-forwarded-for\x12\n172.19.0.1\x1a\x18\n\x10x-envoy-internal\x12\x04true\x1aT\n\nuser-agent\x12FSteelSeries%20GG (unknown version) CFNetwork/1568.200.51 Darwin/24.1.0\x1a\x18\n\x0faccept-language\x12\x05en-us\x1a$\n\x0faccept-encoding\x12\x11gzip, deflate, br\x1a\r\n\x06accept\x12\x03*/*\x1a4\n\x0cx-request-id\x12$8c6eb73a-84f9-4123-9bfa-55d850633e3c\x1a \n\x0ccontent-type\x12\x10application/json\x1a\x17\n\n:authority\x12\tlocalhost"\x1a/application/deployConfigs*\tlocalhost2\x05httpsHNR\x08HTTP/1.1bN{"path":"/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"}Z\x00'  # noqa: E501

try:
    number_of_calls = int(sys.argv[1])
except Exception:
    number_of_calls = 100

for i in range(number_of_calls):
    request = external_auth_pb2.CheckRequest.FromString(bytes)
    response = stub.Check(request, None)
    print(response)
