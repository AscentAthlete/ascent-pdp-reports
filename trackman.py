
import requests

class TrackManConnector:
    def __init__(self, token_url="", data_url="", client_id="", client_secret="", username="", password=""):
        self.token_url = token_url
        self.data_url = data_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password

    def configured(self):
        ok = all([self.token_url, self.data_url, self.client_id, self.client_secret, self.username, self.password])
        return ok, "Data API configured" if ok else "Needs TrackMan Data API credentials"

    def _token(self):
        # TrackMan supplies the exact auth flow/fields with the customer's Data API package.
        # These defaults are intentionally configurable rather than hard-coded.
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
        }
        r = requests.post(self.token_url, data=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("access_token") or data.get("token")

    def fetch_athlete_window(self, athlete_name, start_date, end_date):
        token = self._token()
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "player": athlete_name,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        }
        r = requests.get(self.data_url, params=params, headers=headers, timeout=60)
        r.raise_for_status()
        raw = r.json()

        # Exact field mapping is completed once TrackMan provides the account's schema/docs.
        return {
            "athlete_match": athlete_name,
            "metrics": {},
            "raw": raw,
            "mapping_note": "TrackMan connection works; map your production response fields to PDP metrics."
        }
