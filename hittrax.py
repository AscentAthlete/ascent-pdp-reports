
import requests

class HitTraxConnector:
    def __init__(self, api_base="", api_key=""):
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = api_key

    def configured(self):
        ok = bool(self.api_base and self.api_key)
        return ok, "API configured" if ok else "Needs HitTrax API access"

    def fetch_athlete_window(self, athlete_name, start_date, end_date):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"athlete": athlete_name, "from": start_date.isoformat(), "to": end_date.isoformat()}
        r = requests.get(self.api_base, headers=headers, params=params, timeout=60)
        r.raise_for_status()
        raw = r.json()
        return {
            "athlete_match": athlete_name,
            "metrics": {},
            "raw": raw,
            "mapping_note": "Map HitTrax response fields after vendor API documentation is supplied."
        }
