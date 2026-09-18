from .client import BaseClient


class JobSubmission(BaseClient):
    """SDK client for interacting with the Job Submission APIs.

    Responsible for validating, mapping, and submitting tasks/jobs,
    and searching Task DB registries.
    """

    def validate(self, job_data=None, max_retries=None, backoff_factor=None, **kwargs):
        """Validates job submission inputs.

        POST /job-submission/validate

        Args:
            job_data (dict, optional): Full job submission payload.
            max_retries (int, optional): Max retries for this request.
            backoff_factor (float, optional): Backoff factor for this request.
            **kwargs: Extra fields if job_data is not provided.
        """
        payload = job_data or kwargs
        return self._request(
            "POST",
            "/job-submission/validate",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            json=payload
        )

    def map(self, job_data=None, max_retries=None, backoff_factor=None, **kwargs):
        """Maps user-facing job submission format to internal DB format.

        POST /job-submission/map

        Args:
            job_data (dict, optional): Full job submission payload.
            max_retries (int, optional): Max retries for this request.
            backoff_factor (float, optional): Backoff factor for this request.
            **kwargs: Extra fields if job_data is not provided.
        """
        payload = job_data or kwargs
        return self._request(
            "POST",
            "/job-submission/map",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            json=payload
        )

    def submit(self, job_data, assignment_info, max_retries=None, backoff_factor=None):
        """Submits a job with assignment info.

        POST /job-submission/submit

        Args:
            job_data (dict): The job data matching user-facing schema.
            assignment_info (dict): The routing assignment information (e.g. clusterPreference, region).
            max_retries (int, optional): Max retries for this request.
            backoff_factor (float, optional): Backoff factor for this request.
        """
        payload = {
            "jobData": job_data,
            "assignmentInfo": assignment_info
        }
        return self._request(
            "POST",
            "/job-submission/submit",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            json=payload
        )

    def search_task_registries(self, task_registry_id, query, max_retries=None, backoff_factor=None):
        """Searches the Task DB Registry for matching Task DB entries.

        POST /search/task_registries

        Args:
            task_registry_id (str): The ID of the Task DB registry.
            query (dict): Filter query (Mongo-style or query translator DSL format).
            max_retries (int, optional): Max retries for this request.
            backoff_factor (float, optional): Backoff factor for this request.
        """
        payload = {
            "task_registry_id": task_registry_id,
            "query": query
        }
        return self._request(
            "POST",
            "/search/task_registries",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            json=payload
        )

    def search_task_registry(self, task_registry_id, query, max_retries=None, backoff_factor=None):
        """Searches for submitted jobs inside a specific Task DB.

        POST /search/task_registry

        Args:
            task_registry_id (str): The ID of the Task DB registry.
            query (dict): Filter query (Mongo-style or query translator DSL format).
            max_retries (int, optional): Max retries for this request.
            backoff_factor (float, optional): Backoff factor for this request.
        """
        payload = {
            "task_registry_id": task_registry_id,
            "query": query
        }
        return self._request(
            "POST",
            "/search/task_registry",
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            json=payload
        )
