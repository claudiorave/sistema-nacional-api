from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class NationalJWTScheme(SimpleJWTScheme):
    target_class = "national.authentication.NationalJWTAuthentication"


def exclude_duplicate_login_alias(endpoints, **kwargs):
    return [endpoint for endpoint in endpoints if endpoint[0] != "/login/"]
