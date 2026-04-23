# Configuring Envoy Routing

There are four core items in the gateway proxy configuration. These are:

## HTTP Ports

This defines the ports that envoy will listen for traffic on (such as 80 and 443)

- Module: `ansible.platform.http_ports`
- API Endpoint: `/api/gateway/v1/http_ports/`
- Django Model: `aap_gateway_api.models.HTTPPort`

Fields:

- `name`: unique human readable name.
- `number`: port number for Envoy to listen to requests on.
- `use_https`: secure this port with HTTPS.
- `is_api_port`: indicates that this port will be used to serve all of the `/api/` paths (`/api/controller/`, `/api/gateway/`, etc.)

## Service Clusters

Clusters are a logical grouping of nodes that represent a specific service. 

- Module: `ansible.platform.service_clusters`
- API Endpoint: `/api/gateway/v1/service_clusters/`
- Django Model: `aap_gateway_api.models.ServiceCluster`

Fields:

- `name`: unique human readable name.
- `service_type`: type of cluster .
- There are a bunch of settings here for configuring load balancing in Envoy. The defaults here should be good enough for most deployments.

## Service Nodes

Nodes represent an individual server, VM, container within a service cluster where the one of the services is running.

- Module: `ansible.platform.service_nodes`
- API Endpoint: `/api/gateway/v1/service_nodes/`
- Django Model: `aap_gateway_api.models.ServiceNode`

Fields:

- `name`: unique human readable name.
- `address`: DNS or IP address where envoy can proxy requests to. In most cases this needs to be reachable over the network, however for single node Gateway clusters, this could be localhost or a socket.
- `tags`: list of values which indicate what web services are available on this node.
- `service_cluster`: reference to the service cluster that this node is a part of.

## Routes

Routes represent a path on one of the configured HTTP Ports where Envoy will listen for network requests. Routes are proxied to a single ServiceCluster, where they are load balanced between a user specified set of nodes in the cluster. Routes are never configured directly. Instead they contain two subtypes.

Common Fields:

- `name`: unique human readable name.
- `http_port`: reference to the HTTP Port object where this route will listen on.
- `service_cluster`: reference to the service cluster that this route will send traffic to.
- `service_port`: this is the port on the service node where the traffic from this route will get sent to.
- `is_service_https`: indicate whether the service cluster is using HTTP. or not. This tells envoy if it needs to proxy the request using HTTP or HTTPS. Envoy will handle SSL termination either way.
- `service_path`: path on the service node to proxy the request to.
- `gateway_path`: path on the gateway that envoy will use to match requests for this route.
- `enable_gateway_auth`: if this is false, envoy will not try to authenticate the request. If it is true, envoy will attempt to authenticate the request, but won't block unauthenticated requests from being proxied to the service.
- `order`: order in which the route should be resolved in. This determines precedence if two paths overlap.
- `node_tags`: determines the set of nodes in the service cluster to send requests to.
- `enable_mtls`: sets mutual tls on the route.

### Route Examples

Routes are the most complicated object to understand, so we'll explore some example Routes using the following service cluster:

Service Cluster: EDA
Nodes:

- webhook.example.com, tags: webhook
- api.example.com, tags: api

**Example Route 1:**

```yaml
service_port: 443
node_tags: ""
service_path: "/api/"
gateway_path: "/api/eda/"
enable_gateway_auth: true
is_service_https: true
```

This route will match any request on the gateway at `/api/eda/` and proxy them to both of the configured EDA nodes (webhook.example.com and api.example.com). In this case, the service port is 443 and service path is `/api/`, so all requests proxied through this route will go to one of the following URLs:

- `https://webhook.example.com:443/api/`
- `https://api.example.com:443/api/`

The urls that are proxied for a route are formatted something like this: `{"https" if is_service_https else "http"}://{node_address}:{service_port}/{service_path}`.

Note that one limitation of the current configuration is that all nodes configured for a route must all use the same protocol (http or https), port and path. You can't have a route that sends traffic to port 1234 on node1 and 4321 on node2.

In this example, `is_service_https` is set to true, so the gateway will be checking authentication headers on every request.

**Example Route 2:**

```yaml
service_port: 8000
node_tags: "webhook"
service_path: "/"
gateway_path: "/eda-webhooks/"
enable_gateway_auth: false
is_service_https: false
```

This route will only send traffic to the following URL:

- `http://webhook.example.com:8000/`

We used `http` as the protocol, because of `is_service_https: false`, `/` for the path because of `service_path: "/"` and `8000` for the port because of `service_port: 8000`.

In this case we're only routing to `webhook.example.com` because of the `node_tags: "webhook"`.

**Example Route 3:**

```yaml
service_port: 8000
node_tags: "webhook,api"
service_path: "/"
gateway_path: "/eda-webhooks/"
enable_gateway_auth: false
is_service_https: false
```

This route is identical to the previous example, except we are also selecting the `api` nodes as well. It will result in load balancing requests to `/eda-webhooks/` on gateway between the following urls:

- `http://webhook.example.com:8000/`
- `http://api.example.com:8000/`

### Service API Routes

Service API Routes: these are routes that live on the `/api/` base path. They must all be served from the same HTTP Port, which is tagged with the `is_api_port` flag. The path for these routes must follow the `/api/<service_slug/` pattern.

- Module: `ansible.platform.services`
- API Endpoint: `/api/gateway/v1/services/`
- Django Model: `aap_gateway_api.models.ServiceAPIRoute`

Fields:

- `api_slug`: this replaces the `gateway_path` field on the normal Route model. The path for service API routes will always be `/api/<api_slug>/`.

### Additional Routes

Additional routes encompass every other potential API route in the gateway. This includes things like the container registry in Hub, static files and eda webhooks. They can be served from the API port, or any other configured port. The main requirement with these routes is that they cannot be served from the `/api` path on the API port.

- Module: `ansible.platform.routes`
- API Endpoint: `/api/gateway/v1/routes/`
- Django Model: `aap_gateway_api.models.AdditionalRoute`

## Putting it All together

These objects all interact with each other when requests are received by the gateway as follows:

```mermaid
flowchart
    request{{"HTTP Requests"}}
    port["HTTP Ports"]
    route["Routes"]
    cluster["Service Clusters"]
    node["Service Nodes"]

    request -- HTTP Requests are sent to one of the <br> ports that envoy is listening on  --> port
    port -- the correct route is selected based <br> on the path in the HTTP request --> route
    route -- the request is sent to whichever <br> cluster is mapped to the route --> cluster
    cluster -- the request is load balanced between <br> all the configured nodes in the cluster and <br> proxied onwards to the selected node --> node
```

### Examples

For the examples will be using this as the legend:

```mermaid
flowchart
    subgraph Legend
        port{{HTTP Port}}
        route[/Additional Route/]
        service>Service API Route]

        subgraph cluster[Service Cluster]
            node([Service Node])
        end
    end
```

#### Basic Single Node Deployment With all Services

Gateway Nodes:

- gw.example.com

Controller Nodes:

- controller.example.com

EDA Nodes:

- Webhook: eda.example.com
- API: eda.example.com

Hub Nodes:

- API: hub.example.com

```mermaid
flowchart LR
    port{{API Port: 443}}

    gw_api>"/api/gateway/"]
    ctr_api>"/api/controller/"]
    eda_api>"/api/eda/"]
    hub_api>"/api/galaxy/"]

    eda_webhook[/"/eda-webhooks/"/]
    hub_container[/"/v2/ (container registry)"/]


    subgraph gw[Gateway]
        gwn1([gw.example.com])
    end

    subgraph ctr[Controller]
        ctrn1([controller.example.com])
    end

    subgraph eda[EDA]
        edan1([eda.example.com])
    end

    subgraph hub[Hub]
        hubn1([hub.example.com])
    end

    port --> gw_api
    port --> ctr_api
    port --> eda_api
    port --> hub_api

    port --> eda_webhook
    port --> hub_container

    gw_api -- :443/api/gateway --> gwn1
    ctr_api -- :443/api/controller --> ctrn1
    eda_api -- :443/api/eda --> edan1
    hub_api -- :443/api/galaxy --> hubn1

    eda_webhook -- :443/ --> edan1
    hub_container -- :443/ --> hubn1
```

#### Upgraded HA Cluster

For this scenario we will have multiple controller nodes behind a load balancer. In this case, while controller has multiple physical nodes, we only configure one one node in controller, which will be for the load balancer.

Controller Nodes:

- Behind Load Balancer:
  - c1.example.com
  - c2.example.com
- Load Balancer: controller.example.com

```mermaid
flowchart LR
    port{{API Port: 443}}
    ctr_api>"/api/controller/"]
    c1[c1.example.com]
    c2[c2.example.com]

    l[Load Balancer]

    subgraph ctr[Controller]
        ctrn1([controller.example.com])
    end

    port --> ctr_api
    ctr_api -- :443/api/controller --> ctrn1

    ctrn1 --> l

    l --> c1
    l --> c2
```

#### Load Balancing Through Envoy

Controller Nodes:

- c1.example.com
- c2.example.com

```mermaid
flowchart LR
    port{{API Port: 443}}
    ctr_api>"/api/controller/"]

    subgraph ctr[Controller]
        c1([c1.example.com])
        c2([c2.example.com])
    end

    port --> ctr_api
    ctr_api -- :443/api/controller --> c1
    ctr_api -- :443/api/controller --> c2
```

#### Nodes with Different Tags

Nodes and routes can be tagged with arbitrary values that allows a route to only send traffic to a subset of the configured service nodes. In this example, the EDA nodes can service API or webhook traffic.

EDA Nodes:

- Hybrid: eda-hybrid.example.com
- API: eda-api.example.com
- Webhook: eda-webhook.example.com

```mermaid
flowchart LR
    port{{API Port: 443}}

    eda_api>"/api/eda/ <br/> tags:api"]
    eda_webhook[/"/eda-webhooks/ <br> tags:webhook"/]

    subgraph eda[EDA]
        api(["eda-api.example.com <br/> tags:api"])
        hybrid(["eda-hybrid.example.com <br/> tags:api,webhook"])
        webhook(["eda-webhook.example.com <br/> tags:webhook"])
    end

    port --> eda_api
    port --> eda_webhook

    eda_api -- :443/api/eda --> hybrid
    eda_api -- :443/api/eda --> api

    eda_webhook -- :8000/ --> hybrid
    eda_webhook -- :8000/ --> webhook
```

#### Multiple Ports

This is the same example as above, except EDA webhooks are served on a separate port.

EDA Nodes:

- Hybrid: eda-hybrid.example.com
- API: eda-api.example.com
- Webhook: eda-webhook.example.com

```mermaid
flowchart LR
    port{{API Port: 443}}
    webhook_port{{Webhook Port: 8443}}

    eda_api>"/api/eda/ <br/> tags:api"]
    eda_webhook[/"/eda-webhooks/ <br> tags:webhook"/]

    subgraph eda[EDA]
        api(["eda-api.example.com <br/> tags:api"])
        hybrid(["eda-hybrid.example.com <br/> tags:api,webhook"])
        webhook(["eda-webhook.example.com <br/> tags:webhook"])
    end

    port --> eda_api
    webhook_port --> eda_webhook

    eda_api -- :443/api/eda --> hybrid
    eda_api -- :443/api/eda --> api

    eda_webhook -- :8000/ --> hybrid
    eda_webhook -- :8000/ --> webhook
```
