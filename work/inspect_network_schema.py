"""Read-only utility-network schema lookup for transformer terminal choice."""

import json
from pathlib import Path

from arcgis.gis import GIS

url = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer/queryDataElements"
gis = GIS("pro")
result = gis._con.get(url, params={"f": "json", "layers": "[0]"})
print("Error:", result.get("error"))
elements = result.get("layerDataElements", [])
print("Elements:", len(elements))
for entry in elements:
    data = entry.get("dataElement", {})
    print("Layer:", entry.get("layerId"), "keys:", sorted(data.keys()))
    for config in data.get("terminalConfigurations", []):
        print("Terminal configuration:", config.get("terminalConfigurationId"), config.get("terminalConfigurationName"),
              [(t.get("terminalId"), t.get("terminalName")) for t in config.get("terminals", [])])
    for domain in data.get("domainNetworks", []):
        print("Domain:", domain.get("domainNetworkName"), "junction sources:", len(domain.get("junctionSources", [])),
              "edge sources:", len(domain.get("edgeSources", [])))
        for source in domain.get("junctionSources", []):
            if source.get("networkSourceId") == 16 or source.get("featureLayerId") == 7:
                print("Transformer source:", json.dumps(source)[:5000])
Path(__file__).with_name("network_schema.json").write_text(json.dumps(result), encoding="utf-8")
