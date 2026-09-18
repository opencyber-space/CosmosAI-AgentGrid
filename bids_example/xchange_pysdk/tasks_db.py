from .client import BaseClient, logger


class TasksDB(BaseClient):
    """SDK client for interacting with the Tasks DB (Job Listings) APIs.

    Supports routing via the Job Gateway (with a specific `task_registry_id`)
    or directly to the target Tasks DB instance.
    """

    def __init__(
        self,
        base_url,
        task_registry_id=None,
        max_retries=3,
        backoff_factor=1.0,
        timeout=10.0,
    ):
        """Initializes the Tasks DB client.

        Args:
            base_url (str): Base URL of the API gateway / direct service.
            task_registry_id (str, optional): The ID of the Task DB registry
              entry. If provided, routes calls through the Job Gateway path
              (`/jobs/<task_registry_id>`). If not, routes calls directly
              (`/jobs`).
            max_retries (int): Number of retries for transient errors.
            backoff_factor (float): Multiplier for exponential backoff delay.
            timeout (float): Request timeout in seconds.
        """
        super().__init__(base_url, max_retries, backoff_factor, timeout)
        self.task_registry_id = task_registry_id

    def _get_jobs_path(self, suffix=""):
        if self.task_registry_id:
            # Gateway mode: /jobs/<task_registry_id>
            # suffix is e.g. "/<job_id>" or "/query"
            return f"/jobs/{self.task_registry_id}{suffix}"
        else:
            # Direct mode: /jobs
            return f"/jobs{suffix}"

    def create_job(self, job_data, max_retries=None, backoff_factor=None):
        """Creates a new job/task.

        POST /jobs/<task_registry_id> (gateway) or POST /jobs (direct)
        """
        path = self._get_jobs_path()
        return self._request(
            "POST", path, max_retries, backoff_factor, json=job_data
        )

    def get_job(self, job_id, max_retries=None, backoff_factor=None):
        """Retrieves details of a specific job by its ID.

        GET /jobs/<task_registry_id>/<job_id> (gateway) or GET /jobs/<job_id>
        (direct)
        """
        path = self._get_jobs_path(f"/{job_id}")
        return self._request("GET", path, max_retries, backoff_factor)

    def update_job(
        self, job_id, update_data, max_retries=None, backoff_factor=None
    ):
        """Updates an existing job.

        PUT /jobs/<task_registry_id>/<job_id> (gateway) or PUT /jobs/<job_id>
        (direct)
        """
        path = self._get_jobs_path(f"/{job_id}")
        return self._request(
            "PUT", path, max_retries, backoff_factor, json=update_data
        )

    def delete_job(self, job_id, max_retries=None, backoff_factor=None):
        """Deletes a job.

        DELETE /jobs/<task_registry_id>/<job_id> (gateway) or DELETE
        /jobs/<job_id> (direct)
        """
        path = self._get_jobs_path(f"/{job_id}")
        return self._request("DELETE", path, max_retries, backoff_factor)

    def query_jobs(self, query_data, max_retries=None, backoff_factor=None):
        """Queries multiple jobs matching filter criteria.

        POST /jobs/<task_registry_id>/query (gateway) or POST /jobs/query
        (direct)
        """
        path = self._get_jobs_path("/query")
        return self._request(
            "POST", path, max_retries, backoff_factor, json=query_data
        )

    # Experimental Organization Association APIs
    # NOTE: These endpoints are documented but not currently implemented or exposed in the server backend.
    # When called, these will likely result in a 404 response. They log a warning.

    def create_org(self, org_data, max_retries=None, backoff_factor=None):
        """[EXPERIMENTAL] Registers a new organization or agent.

        POST /orgs

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling create_org API which is currently unimplemented on server side."
        )
        return self._request(
            "POST", "/orgs", max_retries, backoff_factor, json=org_data
        )

    def get_org(self, org_id, max_retries=None, backoff_factor=None):
        """[EXPERIMENTAL] Retrieves details of a specific organization.

        GET /orgs/<org_id>

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling get_org API which is currently unimplemented on server side."
        )
        return self._request(
            "GET", f"/orgs/{org_id}", max_retries, backoff_factor
        )

    def update_org(
        self, org_id, update_data, max_retries=None, backoff_factor=None
    ):
        """[EXPERIMENTAL] Updates configuration metadata of an organization.

        PUT /orgs/<org_id>

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling update_org API which is currently unimplemented on server side."
        )
        return self._request(
            "PUT",
            f"/orgs/{org_id}",
            max_retries,
            backoff_factor,
            json=update_data,
        )

    def delete_org(self, org_id, max_retries=None, backoff_factor=None):
        """[EXPERIMENTAL] Deletes an organization registration.

        DELETE /orgs/<org_id>

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling delete_org API which is currently unimplemented on server side."
        )
        return self._request(
            "DELETE", f"/orgs/{org_id}", max_retries, backoff_factor
        )

    def query_orgs(self, query_data, max_retries=None, backoff_factor=None):
        """[EXPERIMENTAL] Queries organizations based on filter criteria.

        POST /orgs/query

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling query_orgs API which is currently unimplemented on server side."
        )
        return self._request(
            "POST", "/orgs/query", max_retries, backoff_factor, json=query_data
        )
