
import requests
from datetime import datetime, time, timezone

class HawkinConnector:
    def __init__(self, refresh_token="", base_url="https://cloud.hawkindynamics.com"):
        self.refresh_token = refresh_token
        self.base_url = (base_url or "").rstrip("/")

    def configured(self):
        ok = bool(self.refresh_token and self.base_url)
        return ok, "API token configured" if ok else "Add HAWKIN_REFRESH_TOKEN"

    def _access_token(self):
        r = requests.get(
            f"{self.base_url}/api/token",
            headers={"Authorization": f"Bearer {self.refresh_token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("access_token") or data.get("accessToken")

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token()}"}

    def fetch_athlete_window(self, athlete_name, start_date, end_date):
        headers = self._headers()

        athletes = requests.get(
            f"{self.base_url}/api/v1/athletes",
            params={"includeInactive": "true"},
            headers=headers,
            timeout=30,
        )
        athletes.raise_for_status()
        athlete_payload = athletes.json()
        athlete_list = athlete_payload.get("data", athlete_payload) if isinstance(athlete_payload, dict) else athlete_payload
        athlete_list = athlete_list or []

        q = athlete_name.strip().lower()
        matches = []
        for a in athlete_list:
            first = str(a.get("firstName", a.get("first_name", ""))).strip()
            last = str(a.get("lastName", a.get("last_name", ""))).strip()
            full = str(a.get("name", f"{first} {last}")).strip()
            if q in full.lower():
                matches.append(a)

        if not matches:
            raise ValueError(f"No Hawkin athlete matched '{athlete_name}'")

        athlete = matches[0]
        athlete_id = athlete.get("id") or athlete.get("athleteId") or athlete.get("uid")

        start_ts = int(datetime.combine(start_date, time.min, tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.combine(end_date, time.max, tzinfo=timezone.utc).timestamp())

        tests = requests.get(
            f"{self.base_url}/api/v1",
            params={"from": start_ts, "to": end_ts, "includeInactive": "false"},
            headers=headers,
            timeout=60,
        )
        tests.raise_for_status()
        payload = tests.json()
        test_list = payload.get("data", payload) if isinstance(payload, dict) else payload
        test_list = test_list or []

        filtered = []
        for t in test_list:
            tid = t.get("athleteId") or t.get("athlete_id")
            athlete_obj = t.get("athlete") if isinstance(t.get("athlete"), dict) else {}
            obj_id = athlete_obj.get("id")
            if athlete_id and (tid == athlete_id or obj_id == athlete_id):
                filtered.append(t)

        if not filtered:
            # Some team-scoped payloads may omit athleteId; return the raw window for mapping/debug.
            filtered = test_list

        filtered.sort(key=lambda t: t.get("timestamp", t.get("createdAt", 0)) or 0)

        metrics = {}
        if filtered:
            first = filtered[0]
            last = filtered[-1]
            # Dynamic Hawkin fields vary by test type. Try common names, and preserve raw data.
            candidates = {
                "peak_propulsion_force": ["Peak Propulsive Force(N)", "Peak Propulsion Force(N)", "Peak Propulsive Force"],
                "jump_height": ["Jump Height(m)", "Jump Height"],
            }
            for out_key, names in candidates.items():
                b = next((first.get(n) for n in names if first.get(n) is not None), None)
                f = next((last.get(n) for n in names if last.get(n) is not None), None)
                if b is not None or f is not None:
                    try:
                        b = float(b) if b is not None else None
                        f = float(f) if f is not None else None
                    except Exception:
                        pass
                    metrics[out_key] = {"beginning": b, "final": f}

        return {
            "athlete_match": athlete,
            "test_count": len(filtered),
            "metrics": metrics,
            "raw_first_test": filtered[0] if filtered else None,
            "raw_final_test": filtered[-1] if filtered else None,
        }
