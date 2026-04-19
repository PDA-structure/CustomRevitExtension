################################## ANALYTICAL MEMBER CREATION FROM STRUCTURAL ELEMENTS ##############################################
# Imports
from Autodesk.Revit.DB import FilteredElementCollector, Wall, LocationCurve, BuiltInCategory, Transaction
from Autodesk.Revit.DB.Structure import AnalyticalMember

# Variables
doc = __revit__.ActiveUIDocument.Document   #type: Document
uidoc = __revit__.ActiveUIDocument

##################################################################################
# Iterate through each element instance


t = Transaction(doc, 'Create analytical Elements from Structural Framing')
t.Start()

structural_framing = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming) \
    .WhereElementIsNotElementType().ToElements()

for el in structural_framing:
    # Get the LocationCurve from the element
    location_curve = el.Location
    # Check if the location is a LocationCurve

    if isinstance(location_curve, LocationCurve):
        #Access the curve (Line, Arc)
        curve = location_curve.Curve
        analytical_model = AnalyticalMember.Create(doc, curve)

t.Commit()
