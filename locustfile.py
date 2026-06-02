
from locust import HttpUser, task, between
import uuid


class ProxyUser(HttpUser):

    wait_time = between(0.1, 0.5)

    @task
    def test_proxy(self):

        self.client.post(
            "/proxy",
            json={
                "model": "deepseek/deepseek-chat",
                "session_id": str(uuid.uuid4()),
                "messages": [
                    {
                        "role": "user",
                        "content": "What is 2 + 2?"
                    }
                ]
            }
        )
