"""Read-only inspection of the REG utility network REST service."""

from arcgis.gis import GIS

root = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2"
gis = GIS("pro")
for suffix in ("/UtilityNetworkServer", "/FeatureServer"):
    url = root + suffix
    response = gis._con.get(url, params={"f": "json"})
    print(suffix, "error:", response.get("error") if isinstance(response, dict) else type(response).__name__)
    if isinstance(response, dict) and "error" not in response:
        print("  keys:", sorted(response.keys()))
        for name in ("currentVersion", "serviceName", "networkSourceId", "networkSources", "domainNetworks", "traceConfigurations"):
            value = response.get(name)
            if value is not None:
                if isinstance(value, (list, dict)):
                    print(" ", name, "count:", len(value))
                else:
                    print(" ", name, ":", value)
