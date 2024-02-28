import os
from io import StringIO
from unittest import mock

import pytest
import yaml
from django.core.management import CommandError, call_command

from aap_gateway_api.models import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode

SERVICE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'service_config.yml')


@pytest.fixture
def service_config():
    with open(SERVICE_CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


SERVICE_CONFIG_PATH_INVALID_SERVICE_TYPE = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'service_config_invalid_service_type.yml')


def test_register_service_no_args():
    expected_message = "the following arguments are required: --config"
    with pytest.raises(CommandError) as e:
        call_command('register_service')
    assert expected_message in str(e.value)


def test_register_service_config_does_not_exist():
    with pytest.raises(CommandError) as e:
        call_command('register_service', '--config', 'doesnotexist.yml')
    assert "doesnotexist.yml does not exist" in str(e.value)


@mock.patch('aap_gateway_api.management.commands.register_service.yaml.safe_load', return_value=123)
def test_register_service_yaml_is_not_dict(safe_load):
    with pytest.raises(CommandError) as e:
        call_command('register_service', '--config', SERVICE_CONFIG_PATH)
    assert "is not valid YAML" in str(e.value)


@pytest.mark.django_db
def test_register_service_yaml_success(service_config):
    out = StringIO()
    err = StringIO()

    call_command('register_service', '--config', SERVICE_CONFIG_PATH, stdout=out, stderr=err)

    for service_type, params in service_config['services'].items():
        assert f"Creating cluster for {service_type}" in out.getvalue()
        sc = ServiceCluster.objects.get(service_type=service_type)
        assert ServiceAPIRoute.objects.filter(service_cluster=sc, name=f"{service_type} api").exists()
        for instance in params['nodes']:
            assert ServiceNode.objects.filter(service_cluster=sc, **instance).exists()

        if service_type in ("hub"):
            assert AdditionalRoute.objects.filter(service_port=params['api_port'], service_cluster=sc).exists()
        else:
            assert not AdditionalRoute.objects.filter(service_port=params['api_port'], service_cluster=sc).exists()


@pytest.mark.django_db
def test_register_service_invalid_service_type(service_config):
    service_config['services']['gateway']['type'] = 'invalid_service_type'

    with mock.patch(
        'aap_gateway_api.management.commands.register_service.yaml.safe_load',
        return_value=service_config,
    ):
        with pytest.raises(CommandError) as e:
            call_command('register_service', '--config', SERVICE_CONFIG_PATH)
        assert "invalid_service_type is not allowed" in str(e.value)


@pytest.mark.parametrize(
    "yaml_key",
    [
        "proxy",
        "proxy.use_tls",
        "proxy.api_port",
        "services",
        "services.gateway",
        "services.gateway.use_tls",
        "services.gateway.api_port",
        "services.gateway.control_plane_port",
        "services.gateway.service_root",
        "services.gateway.type",
        "services.gateway.nodes",
    ],
)
@pytest.mark.django_db
@pytest.mark.xfail(reason="https://issues.redhat.com/browse/AAP-16816")
def test_register_service_never_throws_KeyError(yaml_key, service_config):
    if "." in yaml_key:
        yaml_key = yaml_key.split(".")
    else:
        yaml_key = [yaml_key]

    def _delete_key(d, keys):
        if len(keys) == 1:
            del d[keys[0]]
        else:
            _delete_key(d[keys[0]], keys[1:])

    _delete_key(service_config, yaml_key)

    with mock.patch(
        'aap_gateway_api.management.commands.register_service.yaml.safe_load',
        return_value=service_config,
    ):
        out = StringIO()
        err = StringIO()

        try:
            call_command('register_service', '--config', SERVICE_CONFIG_PATH, stdout=out, stderr=err)
        except KeyError:
            pytest.fail(f"KeyError thrown for {yaml_key}")
