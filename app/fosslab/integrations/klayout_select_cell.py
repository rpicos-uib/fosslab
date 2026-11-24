# Run by KLayout (-rr, with -rd cell=NAME) after loading a layout:
# show cell NAME, for a GDS file that holds many cells.
import pya

name = globals().get("cell", "")
view = pya.CellView.active()
if name and view.is_valid() and view.layout().cell(name) is not None:
    view.cell_name = name
    pya.LayoutView.current().zoom_fit()
