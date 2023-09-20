function envoy_on_response(handle)
    -- This script rewrites urls in the response by replacing the service base path
    -- in Location headers and in the request body.
    -- ex: translates /service-path/galaxy/ to /gateway-path/hub/ in service response bodies
    handle:logDebug("Running lua script to rewrite response body.")

    local location = handle:headers():get("Location")
    local prefix_rewrite = handle:metadata():get("prefix")
    local prefix = handle:metadata():get("prefix_rewrite")

    if location then
        
        local new_location = string.gsub(location, prefix, prefix_rewrite)
        handle:headers():replace("Location", new_location)
    end
    local body = handle:body()
    if body then
        body_bytes = body:getBytes(0, body:length())
        local modified_body = string.gsub(body_bytes, prefix, prefix_rewrite)

        local content_length = handle:body():setBytes(modified_body)
        handle:headers():replace("content-length", content_length)
    end
end

function envoy_on_request(handle)
    -- Translate urls in the request body back to the service's base path.
    -- ex: translates /gateway-path/hub/ to /service-path/galaxy/ in service request bodies
    handle:logInfo("Running lua script to rewrite request body.")

    local prefix_rewrite = handle:metadata():get("prefix")
    local prefix = handle:metadata():get("prefix_rewrite")

    local body = handle:body()
    if body then
        body_bytes = body:getBytes(0, body:length())
        local modified_body = string.gsub(body_bytes, prefix_rewrite, prefix)

        local content_length = handle:body():setBytes(modified_body)
        handle:headers():replace("content-length", content_length)
    end
end