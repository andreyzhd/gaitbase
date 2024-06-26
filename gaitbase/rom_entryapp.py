# -*- coding: utf-8 -*-
"""
Gaitbase app for entering ROM values.

@author: Jussi (jnu@iki.fi)
"""

import datetime
import json
import logging
from pathlib import Path

import sip
from pkg_resources import resource_filename
from PyQt5 import QtCore, QtWidgets, uic
from PyQt5.QtSql import QSqlQuery
from PyQt5.QtGui import QPalette, QColor

import rom_reporter
from config import cfg
from constants import Constants, Finnish
from widgets import (
    DegLineEdit,
    MyLineEdit,
    qt_message_dialog,
    keyPressEvent_resetOnEsc,
    get_widget_value,
    get_widget_units,
    set_widget_value,
)
from utils import _validate_date

logger = logging.getLogger(__name__)


def pyqt_disable_autoconversion(func):
    """Decorator to disable Qt type autoconversion for a function.

    PyQt functions decorated with this will return QVariants from many Qt
    functions, instead of native Python types. The QVariants then need to be
    manually converted to Python types.
    """

    def wrapper(*args, **kwargs):
        sip.enableautoconversion(QtCore.QVariant, False)
        res = func(*args, **kwargs)
        sip.enableautoconversion(QtCore.QVariant, True)
        return res

    return wrapper


class EntryApp(QtWidgets.QMainWindow):
    """Data entry application"""

    # this signal will be emitted when the window is closing
    closing = QtCore.pyqtSignal(object)

    def __init__(self, database=None, rom_id=None, newly_created=False):
        """_summary_

        Args:
            database QSqlDatabase | None
                The database connection. Can be None if the editor window needs
                to be launched without database access (e.g. for debug purposes)
            rom_id: int | None
                SQL ID of ROM to edit.
            newly_created bool | None
                Whether the entry was newly created. This needs to be explicitly
                specified since we don't create the database entry, it's already
                created by _gaitbase.py.
        """
        super().__init__()
        # load user interface made with Qt Designer
        uifile = resource_filename('gaitbase', 'rom_entryapp.ui')
        uic.loadUi(uifile, self)
        self.confirm_close = True  # used to implement force close
        self.input_widgets = dict()
        self._init_widgets()
        self.data = dict()  # our internal copy of widget input data
        self.read_data_from_widgets()
        # read the widgets at their default state to determine default values
        self.data_default = self.data.copy()
        # whether to update internal dict of variables on input changes
        self.do_update_data = True
        self.rom_id = rom_id
        self.newly_created = newly_created
        self.database = database
        if database is not None:
            # the read only fields contain patient info from the patients table;
            # they are read only once at startup, and never writteh by this module
            self.init_patient_widgets()
            if newly_created:
                # automatically set the date field to current date
                datestr = datetime.datetime.now().strftime('%d.%m.%Y')
                self.dataTiedotPvm.setText(datestr)
                self.values_changed(self.dataTiedotPvm)
            else:
                self.read_data()
                self.update_widgets()

    def force_close(self):
        """Force close without confirmation"""
        self.confirm_close = False
        self.close()

    def db_failure(self, query, fatal=True):
        """Handle database failures"""
        err = query.lastError().databaseText()
        if err:
            msg = f'Got a database error: "{err}"\n'
            msg += 'In case of a locking error, close all other applications '
            msg += 'that may be using the database, and try again.'
        else:
            # empty error seems to occur when all table columns can not be read
            msg = 'Could not read all variables from database. '
            msg += 'This may be due to a mismatch between the UI widgets '
            msg += 'and the database schema.'
        if fatal:
            raise RuntimeError(msg)
        else:
            qt_message_dialog(msg)

    @pyqt_disable_autoconversion
    def select(self, thevars):
        """Do select() on current ROM row to get data.

        thevars is a list of desired variables. Returns a tuple of QVariant
        objects. Afterwards, use QVariant.value() to get the actual values.
        """
        query = QSqlQuery(self.database)
        # form a SQL query for desired variables
        varlist = ','.join(thevars)
        query.prepare(f'SELECT {varlist} FROM roms WHERE rom_id = :rom_id')
        query.bindValue(':rom_id', self.rom_id)
        if not query.exec() or not query.first():
            self.db_failure(query, fatal=True)
        results = tuple(query.value(k) for k in range(len(thevars)))
        return results

    def update_rom(self, thevars, values):
        """Update ROM row with a list of fields and corresponding values"""
        if not len(thevars) == len(values):
            raise ValueError('Arguments need to be of equal length')
        query = QSqlQuery(self.database)
        varlist = ','.join(f'{var} = :{var}' for var in thevars)
        query.prepare(f'UPDATE roms SET {varlist} WHERE rom_id = :rom_id')
        query.bindValue(':rom_id', self.rom_id)
        for var, val in zip(thevars, values):
            query.bindValue(f':{var}', val)
        if not query.exec():
            # it's possible that locking failures may occur here, so make them non-fatal
            self.db_failure(query, fatal=False)

    @property
    def patient_data(self):
        """Return a dictionary of fields and values from the patient table"""
        patient_id = self.select(['patient_id'])[0].value()  # SQL id of current patient
        thevars = ['firstname', 'lastname', 'ssn', 'patient_code', 'diagnosis']
        varlist = ','.join(thevars)
        query = QSqlQuery(self.database)
        query.prepare(f'SELECT {varlist} FROM patients WHERE patient_id = :patient_id')
        query.bindValue(':patient_id', patient_id)
        if not query.exec() or not query.first():
            self.db_failure(query, fatal=True)
        return {var: query.value(k) for k, var in enumerate(thevars)}

    def init_patient_widgets(self):
        """Fill the read-only patient info widgets"""
        for var, value in self.patient_data.items():
            widget_name = 'rdonly_' + var  # corresponding UI widget name
            self.__dict__[widget_name].setText(value)
            self.__dict__[widget_name].setEnabled(False)

    def eventFilter(self, source, event):
        """Captures the FocusOut event for text widgets.

        The idea is to perform data updates when widget focus is lost.
        """
        if event.type() == QtCore.QEvent.FocusOut:
            self.values_changed(source)
        return super().eventFilter(source, event)

    def _init_widgets(self):
        """Initialize and collect the input widgets.

        Also installs some convenience methods etc.
        """

        # collect all widgets (whether data input widgets or something else)
        allwidgets = self.findChildren(QtWidgets.QWidget)
        # data input widgets
        input_widget_prefix = Constants.input_widget_prefix
        data_widgets = [
            w
            for w in allwidgets
            if w.objectName()[: len(input_widget_prefix)] == input_widget_prefix
        ]

        def _weight_normalize(widget):
            """Auto calculate callback for weight normalized widgets"""
            val, weight = (get_widget_value(w) for w in widget._autoinputs)
            noval = Constants.spinbox_novalue_text
            if val == noval or weight == noval:
                set_widget_value(widget, noval)
            else:
                set_widget_value(widget, val / weight)

        def _SCALE_grade_to_pts(widget):
            """Convert SCALE textual grade (Normaali/Alentunnut/Kykenemätön) to points"""
            grade_txt_2_pts = {'Ei mitattu': -1, 'Normaali (2)': 2, 'Alentunnut (1)': 1, 'Kykenemätön (0)': 0}
            tot = -1
            for w in widget._autoinputs:
                cur = grade_txt_2_pts[w.currentText()]
                if cur != -1:
                    if tot == -1:
                        tot = cur
                    else:
                        tot += cur

            widget.setValue(tot)

        # Autowidgets are special widgets with automatically computed values.
        # Their values cannot be directly modified by the user.
        # They must have an ._autocalculate() method which updates the widget,
        # and ._autoinputs list which lists the necessary input widgets.
        #
                
        # Autowidgets for for weight normalized data. Each autowidget has two
        # inputs: the weight and the unnormalized value.
        self.autowidgets = list()
        weight_widget = self.dataAntropPaino
        for widget in data_widgets:
            wname = widget.objectName()
            # handle the 'magic' autowidgets with weight normalized data
            if wname[-4:] == 'Norm':
                self.autowidgets.append(widget)
                # corresponding unnormalized widget
                wname_unnorm = wname.replace('Norm', 'NormUn')
                w_unnorm = self.__dict__[wname_unnorm]
                widget._autoinputs = [w_unnorm, weight_widget]
                widget._autocalculate = lambda w=widget: _weight_normalize(w)

        # Autowidgets for SCALE points - totals
        # Right
        widget = self.findChildren(QtWidgets.QWidget, 'SCALEWholeLimbTotOikPts')[0]
        self.autowidgets.append(widget)
        widget._autoinputs = [self.findChildren(QtWidgets.QWidget, objName)[0] for objName in ['dataSCALELonkkaTotOik',
                                                                                               'dataSCALEPolviTotOik',
                                                                                               'dataSCALENilkkaTotOik',
                                                                                               'dataSCALESTJTotOik',
                                                                                               'dataSCALEVarpaatTotOik']]
        widget._autocalculate = lambda w=widget: _SCALE_grade_to_pts(w)
        
        # Left
        widget = self.findChildren(QtWidgets.QWidget, 'SCALEWholeLimbTotVasPts')[0]
        self.autowidgets.append(widget)
        widget._autoinputs = [self.findChildren(QtWidgets.QWidget, objName)[0] for objName in ['dataSCALELonkkaTotVas',
                                                                                               'dataSCALEPolviTotVas',
                                                                                               'dataSCALENilkkaTotVas',
                                                                                               'dataSCALESTJTotVas',
                                                                                               'dataSCALEVarpaatTotVas']]
        widget._autocalculate = lambda w=widget: _SCALE_grade_to_pts(w)

        # autowidget values cannot be directly modified
        for widget in self.autowidgets:

            # Change the text color in the disabled widgets to black
            palette = widget.palette()
            palette.setColor(QPalette.Disabled, QPalette.Text, QColor('black'))
            widget.setPalette(palette)

            widget.setEnabled(False)

        # set various widget convenience methods/properties, collect input
        # widgets into a dict
        # NOTE: this loop will implicitly cause destruction of certain widgets
        # (e.g. QLineEdits) by replacing them with new ones. Do not try to reuse
        # the 'allwidgets' variable after this loop, it will cause a crash.
        for widget in data_widgets:
            wname = widget.objectName()
            widget_class = widget.__class__.__name__
            if widget_class in ('QSpinBox', 'QDoubleSpinBox'):
                # -lambdas need default arguments because of late binding
                # -lambda expression needs to consume unused 'new value' arg
                widget.valueChanged.connect(
                    lambda new_value, w=widget: self.values_changed(w)
                )
                widget.setLineEdit(MyLineEdit())
                widget.keyPressEvent = lambda event, w=widget: keyPressEvent_resetOnEsc(
                    w, event
                )
            elif widget_class in ('QLineEdit', 'QTextEdit'):
                # for text editors, do not perform data updates on every value change, like so:
                # w.textChanged.connect(lambda new_value, w=w: self.values_changed(w))
                # since it will make the editor slow
                # instead, update the values when focus is lost (editing completed)
                widget.installEventFilter(self)
            elif widget_class == 'QComboBox':
                widget.currentIndexChanged.connect(
                    lambda new_value, w=widget: self.values_changed(w)
                )
            elif widget_class == 'QCheckBox':
                widget.stateChanged.connect(
                    lambda new_value, w=widget: self.values_changed(w)
                )
            elif widget_class == 'CheckableSpinBox':
                widget.valueChanged.connect(lambda w=widget: self.values_changed(w))
                widget.degSpinBox.setLineEdit(DegLineEdit())
            else:
                raise RuntimeError(f'Invalid type of data input widget: {widget_class}')
            self.input_widgets[wname] = widget

        # slot called on tab change
        self.maintab.currentChanged.connect(self.page_change)

        # Set first widget (top widget) of each page. This is used to do
        # focus/selectall on the 1st widget on page change, so that data can be
        # entered immediately.
        self.firstwidget = dict()
        self.firstwidget[self.tabTiedot] = self.rdonly_firstname
        self.firstwidget[self.tabKysely] = self.dataKyselyPaivittainenMatka
        self.firstwidget[self.tabAntrop] = self.dataAntropAlaraajaOik
        self.firstwidget[self.tabLonkka] = self.dataLonkkaFleksioOik
        self.firstwidget[self.tabNilkka] = self.dataNilkkaSoleusCatchOik
        self.firstwidget[self.tabPolvi] = self.dataPolviEkstensioVapOik
        self.firstwidget[self.tabIsokin] = self.dataIsokinPolviEkstensioOik
        self.firstwidget[self.tabVirheas] = self.dataVirheasAnteversioOik
        self.firstwidget[self.tabTasap] = self.dataTasapOik
        self.total_widgets = len(self.input_widgets)

        # widget to varname translation dict
        self.widget_to_var = dict()
        for wname in self.input_widgets:
            varname = wname[len(input_widget_prefix) :]
            self.widget_to_var[wname] = varname

        self.statusbar.showMessage(Finnish.ready.format(n=self.total_widgets))

        # try to increase font size
        self.setStyleSheet(f'QWidget {{ font-size: {cfg.visual.fontsize}pt;}}')

        # FIXME: make sure we always start on 1st tab

    def get_var_units(self, varname):
        """Get units for a variable.

        The units may change dynamically depending on widget states.
        """
        # get widget name corresponding to variable; this is a bit clumsy
        widget_name = [
            wname
            for wname, varname_ in self.widget_to_var.items()
            if varname_ == varname
        ][0]
        widget = self.input_widgets[widget_name]
        return get_widget_units(widget)

    def do_close(self, event):
        """The actual closing ritual"""
        # XXX: we may want to undo the database entry, if no values were entered?
        # XXX: if ROM was newly created, we also create JSON for backup purposes
        # this is for the "beta phase"  only
        if cfg.json.dump_json and self.newly_created:
            # XXX: this will overwrite existing files, but they should be uniquely named due to
            # timestamp in the filename
            fname = self._compose_json_filename()
            try:
                self.dump_json(fname)
            except IOError:  # ignore errors for now
                pass
        self.closing.emit(self.rom_id)
        event.accept()

    def closeEvent(self, event):
        """Confirm and close application."""
        # Since some widgets update only when losing focus, we want to make sure
        # they lose focus before closing the app, so that data is updated.
        self.setFocus()
        if not self.confirm_close:  # force close
            self.do_close(event)
        else:  # closing via ui
            status_ok, msg = self._validate_outputs()
            if status_ok:
                self.do_close(event)
            else:
                qt_message_dialog(msg)
                event.ignore()

    def _validate_outputs(self):
        """Validate inputs before closing"""
        date = self.data['TiedotPvm']
        if not _validate_date(date):
            return False, 'Päivämäärän täytyy olla oikea ja muodossa pp.kk.vvvv'
        else:
            return True, ''

    def values_changed(self, widget):
        """Called whenever value of a widget changes.

        This does several things, most importantly updates the database.
        """
        # find autowidgets that depend on the argument widget and update them
        autowidgets_this = [w for w in self.autowidgets if widget in w._autoinputs]
        for autowidget in autowidgets_this:
            autowidget._autocalculate()
        if self.do_update_data:
            # update internal data dict
            wname = widget.objectName()
            varname = self.widget_to_var[wname]
            newval = get_widget_value(widget)
            self.data[varname] = newval
            # perform the corresponding SQL update
            self.update_rom([varname], [newval])

    def read_data(self):
        """Update the internal data dict from the database"""
        thevars = list(self.data.keys())
        # get data as QVariants, and ignore NULL ones (which correspond to missing data in database)
        qvals = self.select(thevars)
        record_di = {
            var: qval.value() for var, qval in zip(thevars, qvals) if not qval.isNull()
        }
        self.data = self.data_default | record_di

    def _compose_json_filename(self):
        """Make up a JSON filename"""
        pdata = self.patient_data | self.data
        fname = pdata['patient_code']
        fname += '_'
        fname += pdata['lastname'] + pdata['firstname']
        fname += '_'
        fname += datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        fname += '.json'
        return Path(cfg.json.json_path) / fname

    def dump_json(self, fname):
        """Save data into given file in utf-8 encoding"""
        # ID data is not updated from widgets in the SQL version, so get it separately
        rdata = self.data | self.patient_data
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rdata, ensure_ascii=False, indent=True, sort_keys=True))

    @property
    def vars_at_default(self):
        """Return varnames that are at their default values"""
        return [var for var in self.data if self.data[var] == self.data_default[var]]

    def make_text_report(self, template, include_units=True):
        """Create text report from current data"""
        if include_units:
            data = dict()
            for varname, value in self.data.items():
                units = self.get_var_units(varname)
                data[varname] = f'{value}{units}'
        else:
            data = self.data.copy()  # don't mutate the original
        # patient ID data is needed for the report, but it's not part of the ROM
        # table, so get it separately
        report_data = data | self.patient_data
        return rom_reporter.make_text_report(template, report_data, self.vars_at_default)

    def make_excel_report(self, xls_template):
        """Create Excel report from current data"""
        # patient ID data is needed for the report, but it's not part of the ROM
        # table, so get it separately
        report_data = self.data | self.patient_data
        return rom_reporter.make_excel_report(
            xls_template, report_data, self.vars_at_default
        )

    def page_change(self):
        """Callback for tab change"""
        newpage = self.maintab.currentWidget()
        # focus / selectAll on 1st widget of new tab
        if newpage in self.firstwidget:
            widget = self.firstwidget[newpage]
            if widget.isEnabled():
                widget.selectAll()
                widget.setFocus()

    def update_widgets(self):
        """Restore widget input values from the internal data dictionary"""
        # need to disable widget callbacks and automatic data saving while
        # programmatic updating of widgets is taking place
        self.do_update_data = False
        for wname, widget in self.input_widgets.items():
            varname = self.widget_to_var[wname]
            set_widget_value(widget, self.data[varname])
        self.do_update_data = True

    def read_data_from_widgets(self):
        """Read the internal data dictionary from widget inputs.

        Usually not needed, since the dictionary is updated automatically
        whenever widget inputs change.
        """
        for wname, widget in self.input_widgets.items():
            varname = self.widget_to_var[wname]
            self.data[varname] = get_widget_value(widget)
