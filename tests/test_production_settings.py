import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_credentials():
    with pytest.raises(ValidationError, match="Production SECRET_KEY"):
        Settings(_env_file=None, app_env="production",
                 secret_key="change-this-to-a-long-random-secret",
                 bootstrap_admin_username="skunky_admin",
                 bootstrap_admin_password="secure-ci-only-example-password")

    with pytest.raises(ValidationError, match="bootstrap administrator password"):
        Settings(_env_file=None, app_env="production",
                 secret_key="a" * 48,
                 bootstrap_admin_username="skunky_admin",
                 bootstrap_admin_password="change-me-now")

    with pytest.raises(ValidationError, match="administrator username"):
        Settings(_env_file=None, app_env="production",
                 secret_key="a" * 48,
                 bootstrap_admin_username="admin",
                 bootstrap_admin_password="a-unique-non-default-long-password")


def test_production_accepts_configured_auth():
    value = Settings(_env_file=None, app_env="production",
                     secret_key="a" * 48,
                     bootstrap_admin_username="skunky_admin",
                     bootstrap_admin_password="a-unique-non-default-long-password")
    assert value.app_env == "production"
