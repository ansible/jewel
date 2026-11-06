import importlib

from django.db import migrations


def test_usersessionmembership_migration_uses_conditional_database_operation():
    migration = importlib.import_module('aap_gateway_api.migrations.0022_usersessionmembership')
    [operation] = migration.Migration.operations

    assert isinstance(operation, migrations.SeparateDatabaseAndState)
    assert isinstance(operation.state_operations[0], migrations.CreateModel)

    [database_operation] = operation.database_operations
    assert isinstance(database_operation, migrations.RunSQL)
    assert "to_regclass('aap_gateway_api_usersessionmembership') IS NULL" in database_operation.sql
    assert database_operation.reverse_sql == 'DROP TABLE IF EXISTS "aap_gateway_api_usersessionmembership";'
