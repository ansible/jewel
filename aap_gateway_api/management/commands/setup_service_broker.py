"""Provision the SQL Server Service Broker objects dispatcherd's sql_server broker needs.

dispatcherd deliberately never provisions itself ("Starting dispatcherd or
publishing a task never runs setup automatically"), so development, test, and
CI environments run this command before dispatcherd starts. It is a no-op on
non-SQL Server backends.
"""

import logging

from django.core.management.base import BaseCommand
from django.db import connections

logger = logging.getLogger('aap.gateway.management.commands.setup_service_broker')

_ROLE_MEMBERSHIP_SQL = (
    "SELECT DP1.name "
    "FROM sys.database_role_members DRM "
    "JOIN sys.database_principals DP1 ON DRM.role_principal_id = DP1.principal_id "
    "JOIN sys.database_principals DP2 ON DRM.member_principal_id = DP2.principal_id "
    "WHERE DP1.name = 'dispatcherd_runtime' AND DP2.name = %s"
)


def provision_service_broker(using: str = "default", stdout=print) -> None:
    """Enable Service Broker and install dispatcherd's runtime objects.

    Idempotent: enabling an already-enabled database and re-running
    ``Broker.setup_database`` are both safe. Uses the credentials of the
    selected Django database alias, so dev/test environments that run as
    ``sa`` need no extra configuration; production provisioning (dedicated
    DDL login, runtime user grants) stays an administrative step.
    """
    connection = connections[using]
    if connection.vendor != "microsoft":
        stdout("Service Broker setup is not required for this database backend; skipping.")
        return

    from ansible_base.lib.mssql.notify import get_sql_server_notify_conn_string
    from dispatcherd.brokers.sqlserver import Broker

    db_name = connection.settings_dict["NAME"]
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER DATABASE {connection.ops.quote_name(db_name)} SET ENABLE_BROKER WITH ROLLBACK IMMEDIATE")

    Broker.setup_database({"connection_string": get_sql_server_notify_conn_string(alias=using)})

    db_user = connection.settings_dict["USER"]
    with connection.cursor() as cursor:
        cursor.execute(_ROLE_MEMBERSHIP_SQL, [db_user])
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER ROLE dispatcherd_runtime ADD MEMBER {connection.ops.quote_name(db_user)}")

    stdout(f"Service Broker enabled and dispatcherd runtime objects installed for database {db_name}.")


class Command(BaseCommand):
    help = "Provision SQL Server Service Broker objects for dispatcherd (no-op on other backends)"

    def handle(self, *args, **options):
        provision_service_broker(stdout=self.stdout.write)
