import unittest
from unittest.mock import patch, MagicMock
import logging
import requests

from xchange_pysdk.client import BaseClient, XchangeSDKError, logger as sdk_logger
from xchange_pysdk.job_submission import JobSubmission
from xchange_pysdk.registry import TasksDBRegistry
from xchange_pysdk.tasks_db import TasksDB


class TestBaseClient(unittest.TestCase):
    @patch("requests.Session.request")
    def test_request_success_json(self, mock_request):
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": {"key": "val"}}
        mock_request.return_value = mock_response

        client = BaseClient("http://localhost:8000")
        res = client._request("POST", "/test-path", json={"foo": "bar"})

        self.assertEqual(res, {"success": True, "data": {"key": "val"}})
        mock_request.assert_called_once_with(
            "POST",
            "http://localhost:8000/test-path",
            timeout=10.0,
            json={"foo": "bar"},
        )

    @patch("requests.Session.request")
    def test_request_business_failure(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": False, "message": "Invalid field value"}
        mock_request.return_value = mock_response

        client = BaseClient("http://localhost:8000")
        with self.assertRaises(XchangeSDKError) as context:
            client._request("POST", "/test-path", json={})
        
        self.assertEqual(str(context.exception), "Invalid field value")
        self.assertEqual(context.exception.status_code, 200)

    @patch("requests.Session.request")
    def test_request_client_error(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"success": False, "message": "Bad request body"}
        mock_request.return_value = mock_response

        client = BaseClient("http://localhost:8000")
        with self.assertRaises(XchangeSDKError) as context:
            # Client errors (400) shouldn't be retried
            client._request("POST", "/test-path")
        
        self.assertEqual(str(context.exception), "Bad request body")
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(mock_request.call_count, 1)

    @patch("time.sleep")  # Avoid delay in tests
    @patch("requests.Session.request")
    def test_request_transient_retry(self, mock_request, mock_sleep):
        # First call is a transient server error (500), second call succeeds
        mock_response_err = MagicMock()
        mock_response_err.status_code = 500
        mock_response_err.raise_for_status.side_effect = requests.HTTPError("Internal error", response=mock_response_err)

        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 201
        mock_response_ok.json.return_value = {"success": True, "data": "created"}

        mock_request.side_effect = [mock_response_err, mock_response_ok]

        client = BaseClient("http://localhost:8000", max_retries=2, backoff_factor=0.01)
        res = client._request("POST", "/test-path")

        self.assertEqual(res, {"success": True, "data": "created"})
        self.assertEqual(mock_request.call_count, 2)
        mock_sleep.assert_called_once_with(0.01)


class TestJobSubmission(unittest.TestCase):
    @patch("requests.Session.request")
    def test_job_submission_endpoints(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": "success"}
        mock_request.return_value = mock_response

        client = JobSubmission("http://gateway:8000")

        # Test validate dict
        client.validate({"jobId": "123"})
        mock_request.assert_called_with(
            "POST", "http://gateway:8000/job-submission/validate", timeout=10.0, json={"jobId": "123"}
        )

        # Test validate kwargs
        client.validate(jobId="123", submittedBy="user")
        mock_request.assert_called_with(
            "POST", "http://gateway:8000/job-submission/validate", timeout=10.0, json={"jobId": "123", "submittedBy": "user"}
        )

        # Test map
        client.map(jobId="123")
        mock_request.assert_called_with(
            "POST", "http://gateway:8000/job-submission/map", timeout=10.0, json={"jobId": "123"}
        )

        # Test submit
        client.submit({"jobId": "123"}, {"region": "us-east"})
        mock_request.assert_called_with(
            "POST",
            "http://gateway:8000/job-submission/submit",
            timeout=10.0,
            json={"jobData": {"jobId": "123"}, "assignmentInfo": {"region": "us-east"}},
        )

        # Test search_task_registries
        client.search_task_registries("registry-1", {"query": "tags"})
        mock_request.assert_called_with(
            "POST",
            "http://gateway:8000/search/task_registries",
            timeout=10.0,
            json={"task_registry_id": "registry-1", "query": {"query": "tags"}},
        )

        # Test search_task_registry
        client.search_task_registry("registry-1", {"query": "jobs"})
        mock_request.assert_called_with(
            "POST",
            "http://gateway:8000/search/task_registry",
            timeout=10.0,
            json={"task_registry_id": "registry-1", "query": {"query": "jobs"}},
        )


class TestTasksDBRegistry(unittest.TestCase):
    @patch("requests.Session.request")
    def test_gateway_routing(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": []}
        mock_request.return_value = mock_response

        # Gateway routing is default (use_gateway=True)
        registry = TasksDBRegistry("http://gateway:8000")

        registry.create({"listing_id": "db-1"})
        mock_request.assert_called_with(
            "POST", "http://gateway:8000/registry/tasks", timeout=10.0, json={"listing_id": "db-1"}
        )

        registry.read(cluster_id="c-1")
        mock_request.assert_called_with(
            "GET", "http://gateway:8000/registry/tasks", timeout=10.0, params={"cluster_id": "c-1"}
        )

        registry.update({"listing_id": "db-1"}, {"status": "active"})
        mock_request.assert_called_with(
            "PUT",
            "http://gateway:8000/registry/tasks",
            timeout=10.0,
            json={"filter": {"listing_id": "db-1"}, "updateData": {"status": "active"}},
        )

        registry.delete({"listing_id": "db-1"})
        mock_request.assert_called_with(
            "DELETE",
            "http://gateway:8000/registry/tasks",
            timeout=10.0,
            json={"filter": {"listing_id": "db-1"}},
        )

        registry.get_by_id("db-1")
        mock_request.assert_called_with(
            "GET", "http://gateway:8000/registry/tasks/db-1", timeout=10.0
        )

        registry.query({"visibility": "public"})
        mock_request.assert_called_with(
            "POST",
            "http://gateway:8000/registry/tasks/query",
            timeout=10.0,
            json={"visibility": "public"},
        )

    @patch("requests.Session.request")
    def test_direct_routing(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": []}
        mock_request.return_value = mock_response

        # Direct microservice routing (use_gateway=False)
        registry = TasksDBRegistry("http://registry-service:3000", use_gateway=False)

        registry.create({"listing_id": "db-1"})
        mock_request.assert_called_with(
            "POST", "http://registry-service:3000/api/task-listings/create", timeout=10.0, json={"listing_id": "db-1"}
        )

        registry.get_by_id("db-1")
        mock_request.assert_called_with(
            "GET", "http://registry-service:3000/api/task-listings/getById/db-1", timeout=10.0
        )

    @patch("requests.Session.request")
    def test_experimental_infra_warning(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": "ok"}
        mock_request.return_value = mock_response

        registry = TasksDBRegistry("http://gateway:8000")

        with patch.object(sdk_logger, "warning") as mock_warning:
            registry.manual_health_check("db-1")
            mock_warning.assert_called_once()
            self.assertIn("experimental", mock_warning.call_args[0][0].lower())

        with patch.object(sdk_logger, "warning") as mock_warning:
            registry.create_task_db({"size": 10})
            mock_warning.assert_called_once()

        with patch.object(sdk_logger, "warning") as mock_warning:
            registry.resolve_cluster_url({"kube": "conf"})
            mock_warning.assert_called_once()


class TestTasksDB(unittest.TestCase):
    @patch("requests.Session.request")
    def test_gateway_routing_jobs(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": {}}
        mock_request.return_value = mock_response

        # TasksDB initialized with task_registry_id defaults to Gateway mode
        db = TasksDB("http://gateway:8000", task_registry_id="reg-123")

        db.create_job({"jobId": "job-1"})
        mock_request.assert_called_with(
            "POST", "http://gateway:8000/jobs/reg-123", timeout=10.0, json={"jobId": "job-1"}
        )

        db.get_job("job-1")
        mock_request.assert_called_with(
            "GET", "http://gateway:8000/jobs/reg-123/job-1", timeout=10.0
        )

        db.update_job("job-1", {"status": "completed"})
        mock_request.assert_called_with(
            "PUT", "http://gateway:8000/jobs/reg-123/job-1", timeout=10.0, json={"status": "completed"}
        )

        db.delete_job("job-1")
        mock_request.assert_called_with(
            "DELETE", "http://gateway:8000/jobs/reg-123/job-1", timeout=10.0
        )

        db.query_jobs({"submitted_by": "user"})
        mock_request.assert_called_with(
            "POST",
            "http://gateway:8000/jobs/reg-123/query",
            timeout=10.0,
            json={"submitted_by": "user"},
        )

    @patch("requests.Session.request")
    def test_direct_routing_jobs(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": {}}
        mock_request.return_value = mock_response

        # TasksDB initialized without task_registry_id defaults to Direct mode
        db = TasksDB("http://tasks-db-instance:3000")

        db.create_job({"jobId": "job-1"})
        mock_request.assert_called_with(
            "POST", "http://tasks-db-instance:3000/jobs", timeout=10.0, json={"jobId": "job-1"}
        )

        db.get_job("job-1")
        mock_request.assert_called_with(
            "GET", "http://tasks-db-instance:3000/jobs/job-1", timeout=10.0
        )

    @patch("requests.Session.request")
    def test_experimental_org_warning(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": "ok"}
        mock_request.return_value = mock_response

        db = TasksDB("http://tasks-db-instance:3000")

        with patch.object(sdk_logger, "warning") as mock_warning:
            db.create_org({"org_id": "org-1"})
            mock_warning.assert_called_once()
            self.assertIn("experimental", mock_warning.call_args[0][0].lower())

        with patch.object(sdk_logger, "warning") as mock_warning:
            db.get_org("org-1")
            mock_warning.assert_called_once()

        with patch.object(sdk_logger, "warning") as mock_warning:
            db.update_org("org-1", {"metadata": {}})
            mock_warning.assert_called_once()

        with patch.object(sdk_logger, "warning") as mock_warning:
            db.delete_org("org-1")
            mock_warning.assert_called_once()

        with patch.object(sdk_logger, "warning") as mock_warning:
            db.query_orgs({"region": "us-east"})
            mock_warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
