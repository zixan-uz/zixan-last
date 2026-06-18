"""Phase 1 tests.

These are DB-free: the require_json_bool tests are pure, and the endpoint tests use
RequestFactory with the auth/DIAMOR layers mocked, so they assert the request/auth/error
contract without a live database. (CSRF is enforced by middleware in production;
RequestFactory bypasses middleware, so these focus on view logic.)

Run:  python manage.py test diamor_runtime  (or point your test runner at this module)
"""
import json
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from diamor_runtime import views
from diamor_runtime.db import Http400, Http403


class RequireJsonBoolTests(SimpleTestCase):
    def test_true_accepted(self):
        self.assertIs(views.require_json_bool({"approve": True}, "approve"), True)

    def test_false_accepted(self):
        self.assertIs(views.require_json_bool({"approve": False}, "approve"), False)

    def test_string_false_rejected(self):
        with self.assertRaises(Http400) as ctx:
            views.require_json_bool({"approve": "false"}, "approve")
        self.assertEqual(ctx.exception.status, 400)

    def test_string_true_rejected(self):
        with self.assertRaises(Http400):
            views.require_json_bool({"approve": "true"}, "approve")

    def test_int_one_rejected(self):
        with self.assertRaises(Http400):
            views.require_json_bool({"approve": 1}, "approve")

    def test_int_zero_rejected(self):
        with self.assertRaises(Http400):
            views.require_json_bool({"approve": 0}, "approve")

    def test_yes_rejected(self):
        with self.assertRaises(Http400):
            views.require_json_bool({"approve": "yes"}, "approve")

    def test_missing_rejected(self):
        with self.assertRaises(Http400):
            views.require_json_bool({}, "approve")


class DisclosureEndpointTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def _post(self, payload):
        return self.rf.post(
            "/diamor/phase1/disclosure/decide",
            data=json.dumps(payload),
            content_type="application/json",
        )

    @staticmethod
    def _user(authed=True, staff=True, uid=7):
        u = mock.Mock()
        u.is_authenticated = authed
        u.is_staff = staff
        u.id = uid
        return u

    def test_unauthenticated_401(self):
        req = self._post({"approve": True, "request_id": 1})
        req.user = self._user(authed=False)
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 401)

    @mock.patch("diamor_runtime.views.resolve_staff_party", side_effect=Http403("no map"))
    def test_logged_in_but_unmapped_403(self, _resolve):
        req = self._post({"approve": True, "request_id": 1})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 403)

    @mock.patch("diamor_runtime.views.diamor_manager_session")
    @mock.patch("diamor_runtime.views.run_domain", return_value=None)
    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_approve_true_200(self, _resolve, _run_domain, _session):
        cm = mock.MagicMock()
        cm.__enter__.return_value = mock.Mock()
        _session.return_value = cm
        req = self._post({"approve": True, "request_id": 42})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertEqual(body["approved"], True)
        self.assertEqual(body["request_id"], 42)

    @mock.patch("diamor_runtime.views.diamor_manager_session")
    @mock.patch("diamor_runtime.views.run_domain", return_value=None)
    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_approve_false_200(self, _resolve, _run_domain, _session):
        cm = mock.MagicMock()
        cm.__enter__.return_value = mock.Mock()
        _session.return_value = cm
        req = self._post({"approve": False, "request_id": 42})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["approved"], False)

    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_string_false_400(self, _resolve):
        req = self._post({"approve": "false", "request_id": 42})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 400)

    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_string_true_400(self, _resolve):
        req = self._post({"approve": "true", "request_id": 42})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 400)

    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_int_one_400(self, _resolve):
        req = self._post({"approve": 1, "request_id": 42})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 400)

    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_missing_request_id_400(self, _resolve):
        req = self._post({"approve": True})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 400)

    @mock.patch("diamor_runtime.views.diamor_manager_session")
    @mock.patch("diamor_runtime.views.run_domain", return_value=None)
    @mock.patch("diamor_runtime.views.resolve_staff_party", return_value=9001)
    def test_client_decided_by_is_ignored(self, _resolve, run_domain, _session):
        # The client tries to inject decided_by=123456; the mapped staff party is 9001.
        cm = mock.MagicMock()
        cm.__enter__.return_value = mock.Mock()
        _session.return_value = cm
        req = self._post({"approve": True, "request_id": 42, "decided_by": 123456})
        req.user = self._user()
        resp = views.disclosure_decision(req)
        self.assertEqual(resp.status_code, 200)
        run_domain.assert_called_once()
        # decide_disclosure_request is called with [request_id, approve, staff_party_id]
        # — the SERVER-resolved party, never the client-supplied decided_by.
        params = run_domain.call_args.args[2]
        self.assertEqual(params, [42, True, 9001])
        self.assertNotIn(123456, params)
        # The session is bound to the mapped party too, never the client value.
        _session.assert_called_once_with(9001)
