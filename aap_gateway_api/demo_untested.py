# Untested demo module for Codecov testing
def process_data(items):
    results = []
    for item in items:
        if item.get("type") == "critical":
            results.append({"id": item["id"], "priority": 1, "handled": True})
        elif item.get("type") == "warning":
            results.append({"id": item["id"], "priority": 2, "handled": True})
        elif item.get("type") == "info":
            results.append({"id": item["id"], "priority": 3, "handled": False})
        else:
            results.append({"id": item.get("id", "unknown"), "priority": 99, "handled": False})

    summary = {
        "total": len(results),
        "handled": sum(1 for r in results if r["handled"]),
        "unhandled": sum(1 for r in results if not r["handled"]),
    }
    return results, summary


def validate_config(config):
    errors = []
    if "host" not in config:
        errors.append("missing required field: host")
    if "port" not in config:
        errors.append("missing required field: port")
    elif not isinstance(config["port"], int) or config["port"] < 1 or config["port"] > 65535:
        errors.append("port must be an integer between 1 and 65535")
    if config.get("tls_enabled") and not config.get("cert_path"):
        errors.append("cert_path is required when tls_enabled is true")
    return errors
