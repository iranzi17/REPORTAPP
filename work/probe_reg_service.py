"""Read-only availability check for the REG service layers."""

import requests

BASE = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"
BOUNDARY = "https://gisweb.reg.rw/server/rest/services/Hosted/Sector_and_Cell_Boundaries/FeatureServer"


def main():
    session = requests.Session()
    for label, url in (
        ("transformers", BASE + "/7"),
        ("lv_lines", BASE + "/10"),
        ("sectors", BOUNDARY + "/0"),
    ):
        try:
            response = session.get(url, params={"f": "json"}, timeout=20)
            payload = response.json()
            error = payload.get("error") or {}
            print(label, "HTTP", response.status_code, "name", payload.get("name", ""), "error", error.get("code", ""), error.get("message", ""))
        except Exception as exc:
            print(label, type(exc).__name__, str(exc)[:150])


if __name__ == "__main__":
    main()
