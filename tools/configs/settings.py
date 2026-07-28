# gateway override settings. Settings here will override the default django settings

# Turn on file logging
# LOGGING['handlers']['file']['class'] = 'logging.handlers.WatchedFileHandler'  # NOSONAR
# LOGGING['handlers']['file']['filename'] = '/var/log/ansible-automation-platform/gateway/gateway.log'  # NOSONAR

# GRPC_SERVER_PROCESSES = 5  # NOSONAR
# GRPC_SERVER_MAX_THREADS_PER_PROCESS = 10  # NOSONAR
# GRPC_SERVER_AUTH_SERVICE_TIMEOUT = '30s'  # NOSONAR

###############################################################################
# !!!!!!!!!!!! CAUTION !!!!!!!!!!!
#
# This file may be managed by an installer or operator, which
# will override any changes made to its contents.
# In order for changes to apply, the gateway service must be restarted
#
###############################################################################
