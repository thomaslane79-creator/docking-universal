"""Presentation-only compound selection and host-rendered 2D inspection."""

import threading

from .qt import QtCore, QtGui, QtWidgets
from .navigation_table import NavigationTable


class CompoundPreview(QtWidgets.QWidget):
    """Paint-only content: a molecule/status must never change layout hints."""

    def __init__(self):
        super().__init__()
        self.picture = None
        self.message = "Click a compound to inspect its 2D structure."
        self.setMinimumWidth(220)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored)

    def sizeHint(self):
        return QtCore.QSize(300, 240)

    def minimumSizeHint(self):
        return QtCore.QSize(220, 180)

    def clear(self):
        self.picture, self.message = None, ""
        self.update()

    def setText(self, text):
        self.picture, self.message = None, str(text)
        self.update()

    def setPixmap(self, pixmap):
        self.picture, self.message = pixmap, ""
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor('white'))
        painter.setPen(QtGui.QColor('#aaa'))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        area = self.rect().adjusted(8, 8, -8, -8)
        if self.picture is not None and not self.picture.isNull():
            size = self.picture.size().scaled(area.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            target = QtCore.QRect(QtCore.QPoint(), size)
            target.moveCenter(area.center())
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target, self.picture, self.picture.rect())
        else:
            painter.setPen(QtGui.QColor('#222'))
            painter.drawText(area, QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.TextFlag.TextWordWrap, self.message)


class LibraryReadTask(QtCore.QObject):
    finished = QtCore.pyqtSignal(object, object)

    def start(self, operation):
        def work():
            try:
                result, error = operation(), None
            except Exception as exc:
                result, error = None, str(exc)
            self.finished.emit(result, error)
        threading.Thread(target=work, name="du-ligand-library-read", daemon=True).start()


class LigandLibraryPanel(QtWidgets.QWidget):
    loadRequested = QtCore.pyqtSignal()
    previewRequested = QtCore.pyqtSignal(str)
    selectionChanged = QtCore.pyqtSignal()
    columnsApprovalRequested = QtCore.pyqtSignal(object)
    sheetRequested = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library = None
        self.loading = False
        self.read_error = None
        self._pixmap = None
        self._selected_ids = set()
        self._page = 0
        self._valid_ids = set()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.read_button = QtWidgets.QPushButton("Read/select compounds…")
        self.read_button.clicked.connect(self.loadRequested)
        self.summary = QtWidgets.QLabel("All source compounds are used unless you read the library and choose a subset.")
        self.summary.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.read_button)
        row.addWidget(self.summary, 1)
        layout.addLayout(row)
        self.mapping_box = QtWidgets.QGroupBox('Review table columns')
        mapping_layout = QtWidgets.QGridLayout(self.mapping_box)
        self.sheet_combo = QtWidgets.QComboBox()
        self.sheet_label = QtWidgets.QLabel('Worksheet')
        self.smiles_column = QtWidgets.QComboBox()
        self.name_column = QtWidgets.QComboBox()
        for combo in (self.sheet_combo, self.smiles_column, self.name_column):
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
        mapping_layout.addWidget(self.sheet_label, 0, 0)
        mapping_layout.addWidget(self.sheet_combo, 0, 1)
        mapping_layout.addWidget(QtWidgets.QLabel('SMILES column'), 1, 0)
        mapping_layout.addWidget(self.smiles_column, 1, 1)
        mapping_layout.addWidget(QtWidgets.QLabel('Name / ID column'), 1, 2)
        mapping_layout.addWidget(self.name_column, 1, 3)
        self.approve_columns = QtWidgets.QPushButton('Use these columns')
        self.mapping_status = QtWidgets.QLabel('Suggested columns only — review and approve before compounds load.')
        self.mapping_status.setWordWrap(True)
        mapping_layout.addWidget(self.mapping_status, 2, 0, 1, 3)
        mapping_layout.addWidget(self.approve_columns, 2, 3)
        self.smiles_column.currentIndexChanged.connect(self._mapping_changed)
        self.name_column.currentIndexChanged.connect(self._mapping_changed)
        self.sheet_combo.currentIndexChanged.connect(self._sheet_changed)
        self.approve_columns.clicked.connect(self._approve_mapping)
        layout.addWidget(self.mapping_box)
        self.mapping_box.hide()
        self.review = QtWidgets.QWidget()
        review_layout = QtWidgets.QVBoxLayout(self.review)
        review_layout.setContentsMargins(0, 0, 0, 0)
        controls = QtWidgets.QHBoxLayout()
        self.all_button = QtWidgets.QPushButton("Select all valid")
        self.none_button = QtWidgets.QPushButton("Clear selection")
        self.all_button.clicked.connect(lambda: self.set_all(True))
        self.none_button.clicked.connect(lambda: self.set_all(False))
        self.all_button.setToolTip("Select every valid compound across ALL pages")
        self.none_button.setToolTip("Clear the docking selection across ALL pages")
        controls.addWidget(self.all_button)
        controls.addWidget(self.none_button)
        controls.addWidget(QtWidgets.QLabel("Check Dock to include; click a row to inspect."), 1)
        review_layout.addLayout(controls)
        pages = QtWidgets.QHBoxLayout()
        self.previous_button = QtWidgets.QPushButton("Previous")
        self.next_button = QtWidgets.QPushButton("Next")
        self.page_number = QtWidgets.QSpinBox()
        self.page_number.setPrefix("Page ")
        self.page_total = QtWidgets.QLabel()
        self.page_size = QtWidgets.QComboBox()
        for size in (25, 50, 100, 250):
            self.page_size.addItem(str(size), size)
        self.page_size.setCurrentIndex(1)
        self.page_range = QtWidgets.QLabel()
        pages.addWidget(self.previous_button)
        pages.addWidget(self.page_number)
        pages.addWidget(self.page_total)
        pages.addWidget(self.next_button)
        pages.addStretch(1)
        pages.addWidget(self.page_range)
        pages.addWidget(QtWidgets.QLabel("Rows per page:"))
        pages.addWidget(self.page_size)
        review_layout.addLayout(pages)
        self.previous_button.clicked.connect(lambda: self.set_page(self._page - 1))
        self.next_button.clicked.connect(lambda: self.set_page(self._page + 1))
        self.page_number.valueChanged.connect(lambda number: self.set_page(number - 1))
        self.page_size.currentIndexChanged.connect(self._page_size_changed)
        self.splitter = QtWidgets.QSplitter()
        self.table = NavigationTable(0, 6)
        self.table.setHorizontalHeaderLabels(("Dock", "Compound", "Source / record", "Formula", "Charge", "Status"))
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((48, 180, 150, 95, 60, 190)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._changed)
        self.table.currentCellChanged.connect(self._inspect)
        self.preview = CompoundPreview()
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([700, 300])
        self.splitter.splitterMoved.connect(lambda *_args: self._fit_preview())
        self.splitter.setMinimumHeight(240)
        self.splitter.setMaximumHeight(370)
        review_layout.addWidget(self.splitter)
        self.preview_basis = QtWidgets.QLabel(
            'Input structure and charge as supplied — not adjusted to the protocol pH. '
            'Protonation/tautomer states are prepared later for docking.')
        self.preview_basis.setWordWrap(True)
        review_layout.addWidget(self.preview_basis)
        layout.addWidget(self.review)
        self.review.hide()

    def clear(self):
        self.library = None
        self._selected_ids.clear()
        self._valid_ids.clear()
        self._page = 0
        self.loading = False
        self.read_error = None
        self._pixmap = None
        self.table.setRowCount(0)
        self.review.hide()
        self.mapping_box.hide()
        self.read_button.setEnabled(True)
        self.summary.setText("All source compounds are used unless you read the library and choose a subset.")
        self.selectionChanged.emit()

    def set_library(self, library):
        self.library = library
        self._selected_ids.clear()
        if 'table' in library:
            table = library['table']
            blockers = [QtCore.QSignalBlocker(combo) for combo in (self.sheet_combo, self.smiles_column, self.name_column)]
            self.sheet_combo.clear()
            self.sheet_combo.addItems(table['sheets'])
            self.sheet_combo.setCurrentText(table['sheet'] or '')
            self.sheet_combo.setVisible(bool(table['sheets']))
            self.sheet_label.setVisible(bool(table['sheets']))
            self.smiles_column.clear()
            self.name_column.clear()
            self.smiles_column.addItem('Choose a column…', None)
            self.name_column.addItem('None — use Compound number', None)
            for column in table['columns']:
                label = f"{column['label']} (column {column['index'] + 1})"
                self.smiles_column.addItem(label, column['index'])
                self.name_column.addItem(label, column['index'])
            mapping = library.get('column_mapping', {})
            for combo, key, suggestion in ((self.smiles_column, 'smiles_column', 'suggested_smiles_column'),
                                           (self.name_column, 'name_column', 'suggested_name_column')):
                combo.setCurrentIndex(max(0, combo.findData(mapping.get(key, table[suggestion]))))
            del blockers
            self.mapping_box.show()
            self._update_mapping_status()
        else:
            self.mapping_box.hide()
        self._valid_ids = {record['record_id'] for record in library['records'] if record['valid']}
        self._page = 0
        self._render_page()
        self.review.setVisible(library.get('mapping_approved', True))
        self._changed()

    def _update_mapping_status(self):
        approved = self.library and self.library.get('mapping_approved', False)
        valid = self.smiles_column.currentData() is not None and self.smiles_column.currentData() != self.name_column.currentData()
        self.approve_columns.setEnabled(bool(valid and not self.loading and not approved))
        self.mapping_status.setText('Columns approved. Changing a column requires approval again and clears selection.' if approved
                                   else 'Suggested columns only — review and click Use these columns before compounds load.')

    def _mapping_changed(self, *_args):
        if not self.library or 'table' not in self.library:
            return
        self.library['mapping_approved'] = False
        self.library['records'] = []
        self.library.pop('column_mapping', None)
        self._selected_ids.clear()
        self._valid_ids.clear()
        self.table.setRowCount(0)
        self.preview.clear()
        self.review.hide()
        self._update_mapping_status()
        self._changed()

    def _sheet_changed(self, *_args):
        if self.library and 'table' in self.library:
            self._mapping_changed()
            self.sheetRequested.emit(self.sheet_combo.currentText())

    def _approve_mapping(self):
        if not self.library or self.loading or not self.approve_columns.isEnabled():
            return
        table = self.library['table']
        self.columnsApprovalRequested.emit({'source_sha256': table['source_sha256'], 'sheet': table['sheet'],
                                           'smiles_column': self.smiles_column.currentData(),
                                           'name_column': self.name_column.currentData()})

    def _render_page(self):
        if self.library is None:
            return
        count = len(self.library['records'])
        size = self.page_size.currentData()
        pages = max(1, (count + size - 1) // size)
        self._page = max(0, min(self._page, pages - 1))
        start = self._page * size
        visible = self.library['records'][start:start + size]
        blocker = QtCore.QSignalBlocker(self.table)
        self.table.clearContents()
        self.table.setRowCount(len(visible))
        self.table.setCurrentCell(-1, -1)
        self.table.setVerticalHeaderLabels([str(start + i + 1) for i in range(len(visible))])
        from pathlib import Path
        for index, record in enumerate(visible):
            check = QtWidgets.QTableWidgetItem()
            check.setData(QtCore.Qt.ItemDataRole.UserRole, record["record_id"])
            if record["valid"]:
                check.setFlags(check.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(QtCore.Qt.CheckState.Checked if record['record_id'] in self._selected_ids
                                    else QtCore.Qt.CheckState.Unchecked)
            else:
                check.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.table.setItem(index, 0, check)
            location = (f"{record.get('source_sheet') or Path(record['source']).name} / row {record['source_row']}"
                        if 'source_row' in record else f"{Path(record['source']).name} / {record['source_record']}")
            values = (record["name"], location,
                      record["formula"], str(record["formal_charge"]),
                      "Ready" if record["valid"] else record["error"])
            for col, value in enumerate(values, 1):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, col, item)
        del blocker
        page_blocker = QtCore.QSignalBlocker(self.page_number)
        self.page_number.setRange(1, pages)
        self.page_number.setValue(self._page + 1)
        del page_blocker
        self.page_total.setText(f"of {pages}")
        self.page_range.setText(f"Records {start + 1 if count else 0}–{start + len(visible)} of {count}")
        self.previous_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(self._page + 1 < pages)
        self._pixmap = None
        self.preview.clear()
        self.preview.setText("Click a compound to inspect its 2D structure.")

    def set_page(self, page):
        self._page = page
        self._render_page()

    def _page_size_changed(self, *_args):
        self._page = 0
        self._render_page()

    def selection(self):
        if self.library is None:
            return None
        chosen = [record['record_id'] for record in self.library['records']
                  if record['record_id'] in self._selected_ids]
        result = {"fingerprint": self.library["fingerprint"], "record_ids": chosen}
        if self.library.get('mapping_approved'):
            result['column_mapping'] = self.library['column_mapping']
        return result

    def set_all(self, checked):
        self._selected_ids = set(self._valid_ids) if checked else set()
        blocker = QtCore.QSignalBlocker(self.table)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        del blocker
        self._changed()

    def _changed(self, item=None):
        if item is not None and item.column() == 0:
            identifier = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if identifier in self._valid_ids and item.checkState() == QtCore.Qt.CheckState.Checked:
                self._selected_ids.add(identifier)
            else:
                self._selected_ids.discard(identifier)
        if self.library is not None:
            invalid = len(self.library['records']) - len(self._valid_ids)
            self.summary.setText(f"{len(self._selected_ids)} of {len(self.library['records'])} records selected across all pages"
                                 + (f"; {invalid} invalid record(s) cannot be selected." if invalid else "."))
            if not self.library.get('mapping_approved', True):
                self.summary.setText('Column approval required. No compounds loaded or selected.')
        self.selectionChanged.emit()

    def current_record_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None

    def _inspect(self, row, *_args):
        if row >= 0 and self.library:
            self.previewRequested.emit(self.current_record_id())

    def set_preview(self, result):
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(QtCore.QByteArray.fromBase64(result["png_base64"].encode())):
            raise ValueError("The host returned an unreadable compound preview")
        self._pixmap = pixmap
        self._fit_preview()

    def _fit_preview(self):
        if self._pixmap is not None:
            self.preview.setPixmap(self._pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_preview()
