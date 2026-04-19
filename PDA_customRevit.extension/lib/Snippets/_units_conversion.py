# -*- coding: utf-8 -*-
# IMPORTS
# ==================================================
from Autodesk.Revit.DB import *
# VARIABLES
# ==================================================
app      = __revit__.Application
rvt_year = int(app.VersionNumber)


# FUNCTIONS
# ==================================================
def convert_internal_units(value, get_internal = True, units='m'):
    #type: (float, bool, str) -> float
    """Function to convert Internal units to meters or vice versa.
    :param value:        Value to convert
    :param get_internal: True to get internal units, False to get Meters
    :param units:        Select desired Units: ['m', 'm2']
    :return:             Length in Internal units or Meters."""

    if rvt_year >= 2021:
        from Autodesk.Revit.DB import UnitTypeId
        if   units == 'm' : units = UnitTypeId.Meters
        elif units == 'mm': units = UnitTypeId.Millimeters
        elif units == 'cm': units = UnitTypeId.Centimeters
        elif units == "m2": units = UnitTypeId.SquareMeters
        elif units == 'm3': units = UnitTypeId.CubicMeters

    else:
        from Autodesk.Revit.DB import DisplayUnitType
        if   units == 'm' : units = DisplayUnitType.DUT_METERS
        elif units == "m2": units = DisplayUnitType.DUT_SQUARE_METERS
        elif units == "cm": units = DisplayUnitType.DUT_CENTIMETERS


    if get_internal:
        return UnitUtils.ConvertToInternalUnits(value, units)
    return UnitUtils.ConvertFromInternalUnits(value, units)