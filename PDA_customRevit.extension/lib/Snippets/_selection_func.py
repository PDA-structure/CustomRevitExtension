# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import*
from Autodesk.Revit.UI.Selection import ISelectionFilter, Selection

app = __revit__.Application
uidoc = __revit__.ActiveUIDocument        #type:
doc = __revit__.ActiveUIDocument.Document #type: Document

selection = uidoc.Selection #type: Selection

###################### Get selected elements ##########################################
def get_selected_elements(filter_types=None):
    '''Get Selected Elements in Revit UI.
     A list of types for filter_types parameter can be provided (Optional)

     e.g.
     sel_walls = get_selected_elements([Wall])
     '''
    selected_element_ids = uidoc.Selection.GetElementIds()
    selected_elements = [doc.GetElement(e_id) for e_id in selected_element_ids]

    if filter_types:
        return [el for el in selected_elements if type(el) in filter_types]
    return selected_elements

###################################### # class -> ISelectionFilter_Classes ###############################
class ISelectionFilter_Classes(ISelectionFilter):
    def __init__(self, allowed_types):
        ''' ISelectionFilter made to filter with types
        :param allowed_types: list of allowed Types'''

        self.allowed_types = allowed_types

    def AllowElement(self, element):
        if type(element) in self.allowed_types:
            return True

###################################### # class -> ISelectionFilter_Categories #############################
class ISelectionFilter_Categories(ISelectionFilter):

    def __init__(self, allowed_categories):
        ''' ISelectionFilter made to filter with categories
        :param allowed_categoriess: list of allowed Categories'''
        self.allowed_categories = allowed_categories

    def AllowElement(self, element):
        if element.Category.BuiltInCategory in self.allowed_categories:
            return True