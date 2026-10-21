"""Choose and order multiple PDFs before touching the current workspace."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QDialog,QDialogButtonBox,
    QFileDialog,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QMessageBox,QPushButton,QVBoxLayout)


class MergeDialog(QDialog):
    def __init__(self, parent=None, has_document=False):
        super().__init__(parent)
        self.setWindowTitle("دمج ملفات PDF")
        self.resize(650, 470)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout=QVBoxLayout(self)
        heading=QLabel("اختر عدة ملفات، ثم اسحبها بالترتيب المطلوب.")
        heading.setWordWrap(True);layout.addWidget(heading)
        self.files=QListWidget()
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.files,1)
        controls=QHBoxLayout()
        for title,callback in [("إضافة ملفات…",self.choose_files),("إزالة من القائمة",self.remove_selected),("نقل للأعلى",lambda:self.move(-1)),("نقل للأسفل",lambda:self.move(1))]:
            button=QPushButton(title);button.clicked.connect(callback);controls.addWidget(button)
        layout.addLayout(controls)
        self.append_current=QCheckBox("إضافة الملفات بعد صفحات المستند الحالي")
        self.append_current.setVisible(has_document);self.append_current.setChecked(has_document)
        layout.addWidget(self.append_current)
        self.count=QLabel("لم تُضف ملفات بعد");layout.addWidget(self.count)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("بدء الدمج")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.validate);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.files.model().rowsInserted.connect(self.update_count)
        self.files.model().rowsRemoved.connect(self.update_count)

    def paths(self):
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]

    def add_paths(self, paths):
        for path in paths:
            if str(path).lower().endswith('.pdf'):
                item=QListWidgetItem(Path(path).name)
                item.setToolTip(str(path));item.setData(Qt.ItemDataRole.UserRole,str(path));self.files.addItem(item)

    def choose_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,"اختيار ملفات للدمج","","PDF (*.pdf)")
        self.add_paths(paths)

    def remove_selected(self):
        for row in sorted((self.files.row(i) for i in self.files.selectedItems()),reverse=True):
            self.files.takeItem(row)

    def move(self, direction):
        row=self.files.currentRow()
        if 0<=row+direction<self.files.count():
            item=self.files.takeItem(row);self.files.insertItem(row+direction,item);self.files.setCurrentRow(row+direction)

    def update_count(self,*_):
        self.count.setText(f"{self.files.count()} ملف • يمكنك تكرار الملف لإدراج صفحاته أكثر من مرة")

    def validate(self):
        if not self.files.count():
            QMessageBox.information(self,"اختيار الملفات","أضف ملف PDF واحدًا على الأقل.");return
        self.accept()
