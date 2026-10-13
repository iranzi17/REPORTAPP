"""Read-only look at project utility-network source paths."""

import arcpy

path = r"C:\Users\AKIOLI TECHNOLOGY\Documents\ArcGIS\Projects\MyProject6\MyProject6.aprx"
project = arcpy.mp.ArcGISProject(path)
for active_map in project.listMaps():
    print("MAP", active_map.name)
    for layer in active_map.listLayers():
        name = layer.name
        if any(term in name.casefold() for term in ("utility", "electric line", "electric device", "starting point", "barrier")):
            try:
                source = layer.dataSource
            except Exception:
                source = "[no data source]"
            print(" ", name, source)
