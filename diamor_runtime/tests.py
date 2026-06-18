from django.conf import settings
from django.test import SimpleTestCase

from diamor_runtime.routers import DiamorRuntimeRouter


class DiamorRuntimeRouterTests(SimpleTestCase):
    def setUp(self):
        self.router = DiamorRuntimeRouter()

    def test_router_is_registered(self):
        self.assertIn(
            "diamor_runtime.routers.DiamorRuntimeRouter",
            list(getattr(settings, "DATABASE_ROUTERS", [])),
        )

    def test_diamor_runtime_migrates_only_to_diamor_app(self):
        self.assertTrue(
            self.router.allow_migrate(
                "diamor_app",
                "diamor_runtime",
                model_name="diamorstaffidentitymap",
            )
        )

        self.assertFalse(
            self.router.allow_migrate(
                "default",
                "diamor_runtime",
                model_name="diamorstaffidentitymap",
            )
        )

        self.assertFalse(
            self.router.allow_migrate(
                "diamor",
                "diamor_runtime",
                model_name="diamorstaffidentitymap",
            )
        )

    def test_raw_diamor_alias_never_receives_django_migrations(self):
        self.assertFalse(self.router.allow_migrate("diamor", "auth"))
        self.assertFalse(self.router.allow_migrate("diamor", "admin"))
        self.assertFalse(self.router.allow_migrate("diamor", "sessions"))

    def test_diamor_app_is_reserved_for_diamor_runtime_only(self):
        self.assertFalse(self.router.allow_migrate("diamor_app", "auth"))
        self.assertFalse(self.router.allow_migrate("diamor_app", "admin"))
        self.assertFalse(self.router.allow_migrate("diamor_app", "sessions"))
