# -*- coding: utf-8 -*-
"""

Write all variables and their (sqlite) affinity values into a text file.

@author: jussi (jnu@iki.fi)
"""

import json
import sys
import io
from PyQt5 import QtWidgets

from gaitbase.sql_entryapp import EntryApp

fn_out = "variable_affinity.txt"


def _type_affinity(wname):
    """Return type affinity (sqlite) for each widget"""
    if wname[:2] == 'sp':  # spinbox or doublespinbox
        return 'NUMERIC'
    elif wname[:2] == 'ln':  # lineedit
        return 'TEXT'
    elif wname[:2] == 'cb':  # combobox
        return 'TEXT'
    elif wname[:3] == 'cmt':  # comment text field
        return 'TEXT'
    elif wname[:2] == 'xb':  # checkbox
        return 'TEXT'
    elif wname[:3] == 'csb':  # checkdegspinbox
        return 'NUMERIC'
    else:
        raise RuntimeError('Invalid widget name')


app = QtWidgets.QApplication(sys.argv)  # needed for Qt stuff to function
eapp = EntryApp(None, None, False)
with io.open(fn_out, 'w', encoding='utf-8') as f:
    widget_aff = {val: _type_affinity(key) for key, val in eapp.widget_to_var.items()}
    f.write(json.dumps(widget_aff, ensure_ascii=False, indent=True, sort_keys=True))
