from django.contrib.auth.hashers import Argon2PasswordHasher


class OwaspRecommendedArgon2PasswordHasher(Argon2PasswordHasher):
    """
    The default django Argon2 hasher sets parallelism to 8, which is
    too much for the authentication service to handle when it is evaluating
    basic authentication.
    """

    time_cost = 1
    memory_cost = 102400
    parallelism = 1
