import logging
from .client import BaseClient, logger


class TasksDBRegistry(BaseClient):
    """SDK client for interacting with the Tasks DB Registry APIs.

    Supports routing via the Job Gateway (default) or directly to the Tasks DB
    Registry microservice.
    """

    def __init__(
        self,
        base_url,
        use_gateway=True,
        max_retries=3,
        backoff_factor=1.0,
        timeout=10.0,
    ):
        """Initializes the Tasks DB Registry client.

        Args:
            base_url (str): Base URL of the API gateway or direct service.
            use_gateway (bool): If True, routes calls via the Job Gateway
              (/registry/tasks). If False, routes calls directly to the
              registry service (/api/task-listings).
            max_retries (int): Number of retries for transient errors.
            backoff_factor (float): Multiplier for exponential backoff delay.
            timeout (float): Request timeout in seconds.
        """
        super().__init__(base_url, max_retries, backoff_factor, timeout)
        self.use_gateway = use_gateway

    def _get_path(self, endpoint_name, path_param=None):
        if self.use_gateway:
            # Gateway URLs
            if endpoint_name == "create":
                return "/registry/tasks"
            elif endpoint_name == "read":
                return "/registry/tasks"
            elif endpoint_name == "update":
                return "/registry/tasks"
            elif endpoint_name == "delete":
                return "/registry/tasks"
            elif endpoint_name == "get_by_id":
                return f"/registry/tasks/{path_param}"
            elif endpoint_name == "query":
                return "/registry/tasks/query"
            else:
                return f"/registry/tasks/{endpoint_name}"
        else:
            # Direct microservice URLs
            if endpoint_name == "get_by_id":
                return f"/api/task-listings/getById/{path_param}"
            else:
                return f"/api/task-listings/{endpoint_name}"

    def create(self, task_data, max_retries=None, backoff_factor=None):
        """Creates a new Task Listing entry in the registry.

        POST /registry/tasks or POST /api/task-listings/create
        """
        path = self._get_path("create")
        return self._request(
            "POST", path, max_retries, backoff_factor, json=task_data
        )

    def read(
        self, query_params=None, max_retries=None, backoff_factor=None, **kwargs
    ):
        """Reads Task Listing entries from the registry.

        GET /registry/tasks or GET /api/task-listings/read
        """
        path = self._get_path("read")
        params = query_params or kwargs
        return self._request(
            "GET", path, max_retries, backoff_factor, params=params
        )

    def update(
        self,
        filter_data,
        update_data,
        max_retries=None,
        backoff_factor=None,
    ):
        """Updates Task Listing documents matching the filter.

        PUT /registry/tasks or PUT /api/task-listings/update
        """
        path = self._get_path("update")
        payload = {"filter": filter_data, "updateData": update_data}
        return self._request(
            "PUT", path, max_retries, backoff_factor, json=payload
        )

    def delete(self, filter_data, max_retries=None, backoff_factor=None):
        """Deletes Task Listing documents matching the filter.

        DELETE /registry/tasks or DELETE /api/task-listings/delete
        """
        path = self._get_path("delete")
        payload = {"filter": filter_data}
        return self._request(
            "DELETE", path, max_retries, backoff_factor, json=payload
        )

    def get_by_id(self, task_id, max_retries=None, backoff_factor=None):
        """Fetches a specific Task Listing entry by its ID.

        GET /registry/tasks/<task_id> or GET
        /api/task-listings/getById/<task_id>
        """
        path = self._get_path("get_by_id", path_param=task_id)
        return self._request("GET", path, max_retries, backoff_factor)

    def query(self, query_data, max_retries=None, backoff_factor=None):
        """Performs advanced Mongo-style query on Task Listings.

        POST /registry/tasks/query or POST /api/task-listings/query
        """
        path = self._get_path("query")
        return self._request(
            "POST", path, max_retries, backoff_factor, json=query_data
        )

    # Experimental Infrastructure APIs
    # NOTE: These endpoints are documented but not currently implemented in the server backend.
    # When called, these will likely result in a 404 response. They log a warning.

    def manual_health_check(
        self, task_listing_db_id, max_retries=None, backoff_factor=None
    ):
        """[EXPERIMENTAL] Performs manual health check on a target cluster DB.

        POST /manual-health-check or POST
        /api/task-listings/manual-health-check

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling manual_health_check API which is currently unimplemented on server side."
        )
        path = (
            "/manual-health-check"
            if self.use_gateway
            else "/api/task-listings/manual-health-check"
        )
        payload = {"task_listing_db_id": task_listing_db_id}
        return self._request(
            "POST", path, max_retries, backoff_factor, json=payload
        )

    def create_task_db(
        self, db_config, max_retries=None, backoff_factor=None
    ):
        """[EXPERIMENTAL] Deploys a new Task DB instance on a target cluster.

        POST /create-task-db or POST /api/task-listings/create-task-db

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling create_task_db API which is currently unimplemented on server side."
        )
        path = (
            "/create-task-db"
            if self.use_gateway
            else "/api/task-listings/create-task-db"
        )
        return self._request(
            "POST", path, max_retries, backoff_factor, json=db_config
        )

    def resolve_cluster_url(
        self, kube_config, max_retries=None, backoff_factor=None
    ):
        """[EXPERIMENTAL] Extracts public cluster URL from kubeconfig payload.

        GET /resolve-cluster-url or GET /api/task-listings/resolve-cluster-url

        Warning: This API is documented but not implemented in the current
        server package.
        """
        logger.warning(
            "[EXPERIMENTAL] calling resolve_cluster_url API which is currently unimplemented on server side."
        )
        path = (
            "/resolve-cluster-url"
            if self.use_gateway
            else "/api/task-listings/resolve-cluster-url"
        )
        return self._request(
            "GET",
            path,
            max_retries,
            backoff_factor,
            json={"kube_config": kube_config},
        )
