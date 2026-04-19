# Imports
from Autodesk.Revit.DB import *

#VARIABLES
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document  #type: Document

############################# Units converter function ######################################
def convert_internal_units(value, get_internal=True):
    # type: (float, bool) -> float
    """Function to convert Internal units to meters or vice versa.
    :param value:        Value to convert
    :param get_internal: True - Convert to Internal / False - Convert from Internal
    :return:             Length in Internal units or Meters."""
    if get_internal:
        return UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Meters)
    return UnitUtils.ConvertFromInternalUnits(value, UnitTypeId.Meters)

############################# Point Converter Class ######################################
class PointConverter:
    pt_internal = None
    pt_survey = None
    pt_project = None

    def __init__(self, x, y, z, coord_sys='internal', input_units='m'):
        # type:(float, float, float, str, str)
        """ PointConverter - Convert coordinate into desired coordinate system.
        Args:
            x : Float in meters representing the x-coordinate.
            y : Float in meters representing the y-coordinate.
            z : Float in meters representing the z-coordinate.
            coord_sys : Coordinate System of provided coordinates.
                        Possible values: 'internal'/'project'/'survey'
            input_units : Float in meters representing the z-coordinate.
                          Possible Values: 'm' / 'ft' """

        # Get Systems Transform
        srvTrans = self.GetSurveyTransform()
        projTrans = self.GetProjectTransform()

        # Convert to Internal Units
        if input_units == 'm':
            x = convert_internal_units(x, get_internal=True)  # Convert Units to Internal
            y = convert_internal_units(y, get_internal=True)  # Convert Units to Internal
            z = convert_internal_units(z, get_internal=True)  # Convert Units to Internal

        # 1. INTERNAL COORDINATE SYSTEM
        if coord_sys.lower() == 'internal':
            self.pt_internal = XYZ(x, y, z)
            self.pt_survey = self.ApplyInverseTransformation(srvTrans, self.pt_internal)
            self.pt_project = self.ApplyInverseTransformation(projTrans, self.pt_internal)

        # 2. PROJECT COORDINATE SYSTEM
        elif coord_sys.lower() == 'project':
            self.pt_project = XYZ(x, y, z)
            self.pt_internal = self.ApplyTransformation(projTrans, self.pt_project)
            self.pt_survey = self.ApplyInverseTransformation(srvTrans, self.pt_internal)

        # 3. SURVEY COORDINATE SYSTEM
        elif coord_sys.lower() == 'survey':
            self.pt_survey = XYZ(x, y, z)
            self.pt_internal = self.ApplyTransformation(srvTrans, self.pt_survey)
            self.pt_project = self.ApplyInverseTransformation(projTrans, self.pt_internal)

        else:
            raise Exception("Wrong argument value for 'coord_sys' in PointConverter class.")

    # HELPING METHODS
    def GetSurveyTransform(self):
        """Gets the Active Project Locations Transform (Survey)."""
        return doc.ActiveProjectLocation.GetTotalTransform()

    def GetProjectTransform(self):
        """Get the Project Base Points Transform."""
        basePtLoc = next((l for l in FilteredElementCollector(doc)\
                         .OfClass(ProjectLocation)\
                         .WhereElementIsNotElementType()\
                         .ToElements() if l.Name in ['Project', 'Projekt']), None)
        return basePtLoc.GetTotalTransform()

    def ApplyInverseTransformation(self, t, pt):
        """Applies the inverse transformation of
        the given Transform to the given point."""
        return t.Inverse.OfPoint(pt)

    def ApplyTransformation(self, t, pt):
        """Applies the transformation of
        the given Transform to the given point."""
        return t.OfPoint(pt)

############################ Point Coordinate in meter function ##################################
def print_coord_in_m(pt, prefix=""):
    #type: (XYZ, str)
    """Helper Function to display Point Coordinates
    in Meters to compare to Coordinates displayed in Revit."""
    x = round(convert_internal_units(pt.X, get_internal=False), 4)
    y = round(convert_internal_units(pt.Y, get_internal=False), 4)
    z = round(convert_internal_units(pt.Z, get_internal=False), 4)
    print(prefix, 'N:{}'.format(y), 'E:{}'.format(x))
    # print(prefix, 'N/S:{}'.format(y), 'E/W:{}'.format(x), 'Elev:{}'.format(z))
    # print(prefix, 'X:{}'.format(x), 'Y:{}'.format(y), 'Z:{}'.format(z))
