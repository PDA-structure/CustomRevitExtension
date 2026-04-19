############################### IMPROVEMENT CHECK IF ELEMENTS ###################################################
# 1. CHECK IF ELEMENTS ARE CONNECTED
# 2. LOOP THROUGH THE LIST AND CHECK IF THERE IS DUPLICATED NODES OR MEMBERS ( IF SO REMOVED THEM FROM THE LIST PRIOR TO EXPORTING)
# 3. EXPORT TO DOWNLOAD FOLDER

################################## ANALYTICAL MEMBER CREATION FROM MODEL LINES ##############################################
# Imports
from Autodesk.Revit.DB import FilteredElementCollector, Wall, LocationCurve, BuiltInCategory, Transaction
from Autodesk.Revit.DB.Structure import AnalyticalMember

# Variables
doc = __revit__.ActiveUIDocument.Document   #type: Document
uidoc = __revit__.ActiveUIDocument

##################################################################################
# Iterate through each element instance


t = Transaction(doc, 'Create analytical Elements from Lines (inc. detail and model lines)')
t.Start()

model_lines = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Lines) \
    .WhereElementIsNotElementType().ToElements()

for el in model_lines:
    # Get the LocationCurve from the element
    location_curve = el.Location
    # Check if the location is a LocationCurve

    if isinstance(location_curve, LocationCurve):
        #Access the curve (Line, Arc)
        curve = location_curve.Curve
        analytical_model = AnalyticalMember.Create(doc, curve)

t.Commit()









