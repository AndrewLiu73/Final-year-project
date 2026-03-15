from locust import HttpUser, task
class HyperTrackerUser(HttpUser):

    @task(3)
    def get_profitable_traders(self):
        self.client.get("/api/users/profitable?page=1&page_size=100")

    @task(2)
    def get_profitable_with_filters(self):
        self.client.get("/api/users/profitable?min_winrate=60&is_bot=false&page=1&page_size=100")

    @task(2)
    def get_large_positions(self):
        self.client.get("/api/large-positions")

    @task(1)
    def get_exchange_oi(self):
        self.client.get("/api/exchange-oi")

    @task(1)
    def get_bias_summaries(self):
        self.client.get("/api/bias-summaries")
