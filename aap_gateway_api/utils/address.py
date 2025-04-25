import ipaddress


def classify_address_string(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "hostname"

    if ip.version == 6:
        return "ipv6"
    if ip.version == 4:
        return "ipv4"

    raise ValueError(f"unknown IP type: {value}")


def is_hostname_address_string(value: str) -> bool:
    return classify_address_string(value) == "hostname"


def is_ipv4_address_string(value: str) -> bool:
    return classify_address_string(value) == "ipv4"


def is_ipv6_address_string(value: str) -> bool:
    return classify_address_string(value) == "ipv6"
