import requests
import logging

class ToolsRegistrySDK:
    def __init__(self, base_url):

        self.base_url = base_url.rstrip('/')

    def _handle_response(self, response):

        try:
            json_data = response.json()
            logging.info(f"response-data: {json_data}")

            if 'error' in json_data:
                raise Exception(json_data['error'])
            
            return json_data

        except ValueError:
            raise Exception(f"Invalid response from server: {response.text}")

    def create_tool(self, tool_data):

        response = requests.post(f"{self.base_url}/create", json=tool_data)
        return self._handle_response(response)

    def delete_tool(self, tool_id):

        response = requests.delete(f"{self.base_url}/delete/{tool_id}")
        return self._handle_response(response)

    def update_tool(self, tool_id, update_data):

        response = requests.put(
            f"{self.base_url}/update/{tool_id}", json=update_data)
        return self._handle_response(response)

    def get_tool_by_id(self, tool_id):

        response = requests.get(f"{self.base_url}/tools/{tool_id}")
        return self._handle_response(response)

    def execute_query(self, query):

        response = requests.post(
            f"{self.base_url}/query", json={"query": query})
        return self._handle_response(response)

    def search_by_tags(self, tags):

        if not tags:
            raise ValueError("Tags cannot be empty")
        response = requests.post(
            f"{self.base_url}/search/tags", json={"tags": tags})
        return self._handle_response(response)

    def list_all_tools(self):
        """Return every tool in the registry (no filters applied)."""
        response = requests.get(f"{self.base_url}/tools")
        return self._handle_response(response)

    def search_advanced(self, tags=None, tool_type=None, description=None, metadata=None):

        search_params = {
            "tags": tags,
            "tool_type": tool_type,
            "description": description,
            "metadata": metadata,
        }
        # Filter out None values
        search_params = {k: v for k,
                         v in search_params.items() if v is not None}
        response = requests.post(
            f"{self.base_url}/search/advanced", json=search_params)
        return self._handle_response(response)
