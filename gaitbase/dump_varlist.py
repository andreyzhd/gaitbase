# -*- coding: utf-8 -*-
"""

Dump gaitbase variable names and their SQLite affinities.

@author: jussi (jnu@iki.fi)
"""

import io
import json
import sys

from PyQt5 import QtWidgets

from gaitbase.rom_entryapp import EntryApp


def _type_affinity(widget):
    """Return type affinity (sqlite) for each widget"""
    widget_class = widget.__class__.__name__
    if widget_class in ('QSpinBox', 'QDoubleSpinBox', 'CheckableSpinBox'):
        return 'NUMERIC'
    else:
        return 'TEXT'


def get_vars_and_affinities():
    """Get a dict of variable names and their SQLite type affinities"""
    app = QtWidgets.QApplication(sys.argv)  # needed for Qt stuff to function
    eapp = EntryApp()
    affs = dict()
    for wname, widget in eapp.input_widgets.items():
        varname = eapp.widget_to_var[wname]
        affs[varname] = _type_affinity(widget)
    return affs


if __name__ == '__main__':

    FN_OUT = "variable_affinity.txt"
    var_affs = get_vars_and_affinities()
    
    with io.open(FN_OUT, 'w', encoding='utf-8') as f:
        f.write(json.dumps(var_affs, ensure_ascii=False, indent=True, sort_keys=True))
    print(f'wrote {len(var_affs)} variables into {FN_OUT}')
