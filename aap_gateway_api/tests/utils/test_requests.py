from urllib.parse import urlparse

import pytest
from django.http.request import HttpRequest

from aap_gateway_api.utils.requests import _validate_regular_hostname, _validate_url_structure, _validate_wildcard_domain, check_csrf_origin, from_proxy


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, False),
        ({"HTTP_X_TRUSTED_PROXY": "anything"}, True),
    ],
)
def test_from_proxy(headers, expected):
    request = HttpRequest()
    for header in headers:
        request.META[header] = headers[header]

    assert from_proxy(request) == expected


@pytest.mark.parametrize(
    "input,message",
    [
        # Valid cases - domains and localhost
        ("https://localhost", None),
        ("http://localhost", None),
        ("https://localhost:8000", None),
        ("http://localhost:3000", None),
        ("https://example.com", None),
        ("http://example.com:8000", None),
        ("https://sub.example.com:443", None),
        ("*", None),  # Special case for development
        ("https://*.example.com", None),
        ("http://*.example.com", None),
        ("https://*.sub.example.com", None),
        # Valid cases - IPv4 addresses
        ("https://127.0.0.1", None),
        ("http://127.0.0.1", None),
        ("https://192.168.1.1", None),
        ("http://10.0.0.1:8080", None),
        ("https://172.16.0.1:3000", None),
        # Valid cases - IPv6 addresses
        ("https://[::1]", None),
        ("http://[::1]", None),
        ("https://[::1]:8000", None),
        ("http://[2001:db8::1]:8080", None),
        ("https://[fe80::1]:3000", None),
        # Invalid cases - missing scheme (Django 4.0+ requirement)
        ("localhost", "The origin must start with either http:// or https://"),
        ("example.com", "The origin must start with either http:// or https://"),
        ("*.example.com", "The origin must start with either http:// or https://"),
        # Invalid cases - invalid schemes
        ("ftp://example.com", "The origin must start with either http:// or https://"),
        ("ws://example.com", "The origin must start with either http:// or https://"),
        ("://example.com", "The origin must start with either http:// or https://"),
        # Invalid cases - empty netloc
        ("https://", "The hostname should not be empty"),
        ("http://", "The hostname should not be empty"),
        # Invalid cases - paths, queries, fragments
        ("https://localhost/path", "The origin must include only the scheme and hostname (no path)"),
        ("https://example.com/api/", "The origin must include only the scheme and hostname (no path)"),
        ("https://example.com?param=value", "The origin must not include query parameters"),
        ("https://example.com#section", "The origin must not include fragments"),
        ("https://example.com/path?query=1#frag", "The origin must include only the scheme and hostname (no path)"),
        # Invalid cases - malformed wildcards
        ("https://sub*.example.com", "wildcard must be at the start of the domain"),
        ("https://example.*.com", "wildcard must be at the start of the domain"),
        ("https://*", "wildcard must be at the start of the domain and followed by a dot"),
        ("https://*.com", "wildcard domain must have a valid domain after"),
        ("https://*.*.example.com", "only one wildcard at the beginning is allowed"),
        ("https://*example.com", "wildcard must be at the start of the domain and followed by a dot"),
        ("https://*.192.168.1.1", "wildcards cannot be used with IP addresses"),
        ("https://*.127.0.0.1", "wildcards cannot be used with IP addresses"),
        # IPv6 wildcard patterns (not allowed)
        ("https://*.::1", "wildcards cannot be used with IP addresses"),
        ("https://*.2001:db8::1", "wildcards cannot be used with IP addresses"),
        ("https://*.fe80::", "wildcards cannot be used with IP addresses"),
        ("https://*.fe80::1:2", "wildcards cannot be used with IP addresses"),
        # Partial IP-like patterns (invalid domain names)
        ("https://*.192.0.1", "invalid domain name after wildcard"),
        ("https://*.10.0", "invalid domain name after wildcard"),
        ("https://*.172.16.0", "invalid domain name after wildcard"),
        ("https://*.2001:db8", "wildcard domain must have a valid domain after"),
        ("https://*.2001:db8:85a3", "wildcard domain must have a valid domain after"),
        ("https://*.fe80:1234", "wildcard domain must have a valid domain after"),
        # Invalid cases - invalid domain names
        ("https://example.c", "invalid domain name"),
        ("https://*.example.c", "invalid domain name after wildcard"),
        ("https://test.123", "invalid domain name"),
        ("https://*.test.123", "invalid domain name after wildcard"),
        ("https://example-.com", "invalid domain name"),
        ("https://-example.com", "invalid domain name"),
        ("https://exam_ple.com", "invalid domain name"),
        ("https://example..com", "invalid domain name"),
        # Invalid cases - unparseable
        (1, "Unable to parse this as a URL"),
        (None, "Unable to parse this as a URL"),
        ("", "The origin must start with either http:// or https://"),
        ("not-a-url", "The origin must start with either http:// or https://"),
    ],
)
def test_check_csrf_origin(input, message):
    results = check_csrf_origin(input)
    if message is None:
        assert results == message
    else:
        assert message in results


class TestValidateUrlStructure:
    """Test cases for _validate_url_structure helper function."""

    @pytest.mark.parametrize(
        "url,expected_error",
        [
            # Valid schemes
            ("https://example.com", None),
            ("http://example.com", None),
            # Invalid schemes
            ("ftp://example.com", "The origin must start with either http:// or https://. Got: ftp://example.com"),
            ("ws://example.com", "The origin must start with either http:// or https://. Got: ws://example.com"),
            ("://example.com", "The origin must start with either http:// or https://. Got: ://example.com"),
            ("", "The origin must start with either http:// or https://. Got: "),
            ("example.com", "The origin must start with either http:// or https://. Got: example.com"),
        ],
    )
    def test_scheme_validation(self, url, expected_error):
        parts = urlparse(url)
        result = _validate_url_structure(parts, url)
        assert result == expected_error

    @pytest.mark.parametrize(
        "url,expected_error",
        [
            # Valid netloc
            ("https://example.com", None),
            ("https://localhost", None),
            ("https://127.0.0.1", None),
            ("https://[::1]", None),
            ("https://example.com:8080", None),
            # Empty netloc
            ("https://", "The hostname should not be empty. Got: https://"),
            ("http://", "The hostname should not be empty. Got: http://"),
        ],
    )
    def test_netloc_validation(self, url, expected_error):
        parts = urlparse(url)
        result = _validate_url_structure(parts, url)
        assert result == expected_error

    @pytest.mark.parametrize(
        "url,expected_error",
        [
            # Valid paths (empty or root)
            ("https://example.com", None),
            ("https://example.com/", None),  # Root path is allowed
            # Invalid paths
            ("https://example.com/path", "The origin must include only the scheme and hostname (no path). Got: https://example.com/path"),
            ("https://example.com/api/v1", "The origin must include only the scheme and hostname (no path). Got: https://example.com/api/v1"),
            ("https://example.com/path/", "The origin must include only the scheme and hostname (no path). Got: https://example.com/path/"),
        ],
    )
    def test_path_validation(self, url, expected_error):
        parts = urlparse(url)
        result = _validate_url_structure(parts, url)
        assert result == expected_error

    @pytest.mark.parametrize(
        "url,expected_error",
        [
            # Valid (no query)
            ("https://example.com", None),
            # Invalid (has query)
            ("https://example.com?param=value", "The origin must not include query parameters. Got: https://example.com?param=value"),
            ("https://example.com?a=1&b=2", "The origin must not include query parameters. Got: https://example.com?a=1&b=2"),
            ("https://example.com?", None),  # Empty query is actually valid
        ],
    )
    def test_query_validation(self, url, expected_error):
        parts = urlparse(url)
        result = _validate_url_structure(parts, url)
        assert result == expected_error

    @pytest.mark.parametrize(
        "url,expected_error",
        [
            # Valid (no fragment)
            ("https://example.com", None),
            # Invalid (has fragment)
            ("https://example.com#section", "The origin must not include fragments. Got: https://example.com#section"),
            ("https://example.com#", None),  # Empty fragment is actually valid
            ("https://example.com#top", "The origin must not include fragments. Got: https://example.com#top"),
        ],
    )
    def test_fragment_validation(self, url, expected_error):
        parts = urlparse(url)
        result = _validate_url_structure(parts, url)
        assert result == expected_error


class TestValidateWildcardDomain:
    """Test cases for _validate_wildcard_domain helper function."""

    @pytest.mark.parametrize(
        "netloc,value,expected_error",
        [
            # Valid wildcard patterns
            ("*.example.com", "https://*.example.com", None),
            ("*.sub.example.com", "https://*.sub.example.com", None),
            ("*.localhost", "https://*.localhost", None),
            ("*.test.org", "https://*.test.org", None),
            # Invalid wildcard placement
            ("*", "https://*", "wildcard must be at the start of the domain and followed by a dot (e.g., '*.example.com'). Got: https://*"),
            (
                "*example.com",
                "https://*example.com",
                "wildcard must be at the start of the domain and followed by a dot (e.g., '*.example.com'). Got: https://*example.com",
            ),
            (
                "sub*.example.com",
                "https://sub*.example.com",
                "wildcard must be at the start of the domain and followed by a dot (e.g., '*.example.com'). Got: https://sub*.example.com",
            ),
            (
                "example.*.com",
                "https://example.*.com",
                "wildcard must be at the start of the domain and followed by a dot (e.g., '*.example.com'). Got: https://example.*.com",
            ),
        ],
    )
    def test_wildcard_placement(self, netloc, value, expected_error):
        result = _validate_wildcard_domain(netloc, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "netloc,value,expected_error",
        [
            # Valid domain parts
            ("*.example.com", "https://*.example.com", None),
            ("*.test.org", "https://*.test.org", None),
            # Empty domain part after wildcard
            ("*.", "https://*.", "wildcard domain must have a valid domain after '*.'. Got: https://*."),
        ],
    )
    def test_domain_part_presence(self, netloc, value, expected_error):
        result = _validate_wildcard_domain(netloc, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "netloc,value,expected_error",
        [
            # Valid (single wildcard)
            ("*.example.com", "https://*.example.com", None),
            # Invalid (multiple wildcards)
            ("*.*.example.com", "https://*.*.example.com", "only one wildcard at the beginning is allowed. Got: https://*.*.example.com"),
            ("*.*", "https://*.*", "only one wildcard at the beginning is allowed. Got: https://*.*"),
        ],
    )
    def test_multiple_wildcards(self, netloc, value, expected_error):
        result = _validate_wildcard_domain(netloc, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "netloc,value,expected_error",
        [
            # Valid domain names
            ("*.example.com", "https://*.example.com", None),
            ("*.test.org", "https://*.test.org", None),
            # IPv4 addresses (not allowed with wildcards)
            ("*.192.168.1.1", "https://*.192.168.1.1", "wildcards cannot be used with IP addresses. Got: https://*.192.168.1.1"),
            ("*.127.0.0.1", "https://*.127.0.0.1", "wildcards cannot be used with IP addresses. Got: https://*.127.0.0.1"),
            ("*.10.0.0.1", "https://*.10.0.0.1", "wildcards cannot be used with IP addresses. Got: https://*.10.0.0.1"),
            # IPv6 addresses (not allowed with wildcards)
            ("*.::1", "https://*.::1", "wildcards cannot be used with IP addresses. Got: https://*.::1"),
            ("*.2001:db8::1", "https://*.2001:db8::1", "wildcards cannot be used with IP addresses. Got: https://*.2001:db8::1"),
            ("*.fe80::", "https://*.fe80::", "wildcards cannot be used with IP addresses. Got: https://*.fe80::"),
            ("*.fe80::1:2", "https://*.fe80::1:2", "wildcards cannot be used with IP addresses. Got: https://*.fe80::1:2"),
            # Partial IPv4-like patterns (not valid IP addresses, treated as domain names)
            ("*.192.0.1", "https://*.192.0.1", "invalid domain name after wildcard: '192.0.1'. Got: https://*.192.0.1"),
            ("*.10.0", "https://*.10.0", "invalid domain name after wildcard: '10.0'. Got: https://*.10.0"),
            ("*.172.16.0", "https://*.172.16.0", "invalid domain name after wildcard: '172.16.0'. Got: https://*.172.16.0"),
            # Partial IPv6-like patterns (not valid IPv6 addresses, treated as domain names)
            ("*.2001:db8", "https://*.2001:db8", "wildcard domain must have a valid domain after '*.'. Got: https://*.2001:db8"),
            ("*.2001:db8:85a3", "https://*.2001:db8:85a3", "wildcard domain must have a valid domain after '*.'. Got: https://*.2001:db8:85a3"),
            ("*.fe80:1234", "https://*.fe80:1234", "wildcard domain must have a valid domain after '*.'. Got: https://*.fe80:1234"),
        ],
    )
    def test_ip_address_rejection(self, netloc, value, expected_error):
        result = _validate_wildcard_domain(netloc, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "netloc,value,expected_error",
        [
            # Valid domain structures
            ("*.example.com", "https://*.example.com", None),
            ("*.sub.example.com", "https://*.sub.example.com", None),
            # Invalid - missing dot in domain part (except localhost)
            ("*.com", "https://*.com", "wildcard domain must have a valid domain after '*.'. Got: https://*.com"),
            # Invalid domain names
            ("*.example.c", "https://*.example.c", "invalid domain name after wildcard: 'example.c'. Got: https://*.example.c"),
            ("*.test.123", "https://*.test.123", "invalid domain name after wildcard: 'test.123'. Got: https://*.test.123"),
            ("*.-example.com", "https://*.-example.com", "invalid domain name after wildcard: '-example.com'. Got: https://*.-example.com"),
            ("*.example-.com", "https://*.example-.com", "invalid domain name after wildcard: 'example-.com'. Got: https://*.example-.com"),
        ],
    )
    def test_domain_name_validation(self, netloc, value, expected_error):
        result = _validate_wildcard_domain(netloc, value)
        assert result == expected_error


class TestValidateRegularHostname:
    """Test cases for _validate_regular_hostname helper function."""

    @pytest.mark.parametrize(
        "hostname,value,expected_error",
        [
            # None/empty hostname
            (None, "https://", None),
            ("", "https://", None),
        ],
    )
    def test_empty_hostname(self, hostname, value, expected_error):
        result = _validate_regular_hostname(hostname, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "hostname,value,expected_error",
        [
            # IPv4 addresses (valid)
            ("127.0.0.1", "https://127.0.0.1", None),
            ("192.168.1.1", "https://192.168.1.1", None),
            ("10.0.0.1", "https://10.0.0.1", None),
            ("172.16.0.1", "https://172.16.0.1", None),
            ("8.8.8.8", "https://8.8.8.8", None),
            ("255.255.255.255", "https://255.255.255.255", None),
            ("0.0.0.0", "https://0.0.0.0", None),
        ],
    )
    def test_ipv4_addresses(self, hostname, value, expected_error):
        result = _validate_regular_hostname(hostname, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "hostname,value,expected_error",
        [
            # IPv6 addresses (valid)
            ("::1", "https://[::1]", None),
            ("2001:db8::1", "https://[2001:db8::1]", None),
            ("fe80::1", "https://[fe80::1]", None),
            ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", "https://[2001:0db8:85a3:0000:0000:8a2e:0370:7334]", None),
        ],
    )
    def test_ipv6_addresses(self, hostname, value, expected_error):
        result = _validate_regular_hostname(hostname, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "hostname,value,expected_error",
        [
            # localhost (special case - always valid)
            ("localhost", "https://localhost", None),
            ("LOCALHOST", "https://LOCALHOST", None),
            ("LocalHost", "https://LocalHost", None),
        ],
    )
    def test_localhost_special_case(self, hostname, value, expected_error):
        result = _validate_regular_hostname(hostname, value)
        assert result == expected_error

    @pytest.mark.parametrize(
        "hostname,value,expected_error",
        [
            # Valid domain names
            ("example.com", "https://example.com", None),
            ("sub.example.com", "https://sub.example.com", None),
            ("test.org", "https://test.org", None),
            ("my-site.co.uk", "https://my-site.co.uk", None),
            ("api-v2.example-site.com", "https://api-v2.example-site.com", None),
            # Invalid domain names
            ("example.c", "https://example.c", "invalid domain name: 'example.c'. Got: https://example.c"),
            ("test.123", "https://test.123", "invalid domain name: 'test.123'. Got: https://test.123"),
            ("-example.com", "https://-example.com", "invalid domain name: '-example.com'. Got: https://-example.com"),
            ("example-.com", "https://example-.com", "invalid domain name: 'example-.com'. Got: https://example-.com"),
            ("exam_ple.com", "https://exam_ple.com", "invalid domain name: 'exam_ple.com'. Got: https://exam_ple.com"),
            ("example..com", "https://example..com", "invalid domain name: 'example..com'. Got: https://example..com"),
            ("", "https://", None),  # Empty hostname is handled separately
        ],
    )
    def test_domain_name_validation(self, hostname, value, expected_error):
        result = _validate_regular_hostname(hostname, value)
        assert result == expected_error
