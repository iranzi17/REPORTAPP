"""Read-only inspection of the project's saved temporary trace locations."""

import arcpy

path = r"C:\Users\AKIOLI TECHNOLOGY\Documents\ArcGIS\Projects\MyProject6\MyProject6.aprx"
project = arcpy.mp.ArcGISProject(path)
gdb = project.defaultGeodatabase
print("Default GDB:", gdb)
for name in ("UN_Temp_Starting_Points", "UN_Temp_Barriers"):
    fc = gdb + "\\" + name
    if not arcpy.Exists(fc):
        print(name, "absent")
        continue
    fields = [f.name for f in arcpy.ListFields(fc) if f.type != "Geometry"]
    print(name, "fields:", fields)
    print(name, "count:", int(arcpy.management.GetCount(fc)[0]))
    keep = [f for f in fields if f.casefold() in ("featureglobalid", "terminalid", "networksourceid", "objectid", "percentalong")]
    with arcpy.da.SearchCursor(fc, keep) as rows:
        print(name, "locations:", [dict(zip(keep, row)) for row in rows])
