# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import ReferencePoint, Transform, XYZ

def get_coordinate_system_from_reference_point(referene_point):
    # Get the location of the reference point
    location = reference_point.Position # This is an XYZ location (point)

    # Get the coordinate system of the ReferencePoint (if it's part of a family)
    # The coordinate system might be a transformation or a direction relative to the family)
    transform = referene_point.GetTransform() # Get the transformation matrix (if any)

    # You can extract the basis vectors (axes) from the transform

    if transform:
        b0 = transform.BasisX   # X axis of the coordinate system
        b1 = transform.BasisY   # Y axis of the coordinate system
        b2 = transform.BasisZ   # Z axis of the coordinate system

        # You now have the basis vectors (coordinate axes) and the position of the point
        return location, b0, b1, b2
    else:
        # If no transformation is available, return the location only
        return location, None, None, None