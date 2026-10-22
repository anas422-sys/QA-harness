from pathlib import Path
import pythoncom
import win32com.client

source = str(Path("Daily_Software_Testing_Guide.docx").resolve())
target = str(Path("Daily_Software_Testing_Guide_QA.pdf").resolve())
pythoncom.CoInitialize()
word = win32com.client.DispatchEx("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
word.AutomationSecurity = 3
document = None
try:
    document = word.Documents.Open(
        source,
        ConfirmConversions=False,
        ReadOnly=True,
        AddToRecentFiles=False,
        NoEncodingDialog=True,
    )
    document.SaveAs2(target, FileFormat=17, AddToRecentFiles=False)
finally:
    if document is not None:
        document.Close(SaveChanges=False)
    word.Quit(SaveChanges=False)
    pythoncom.CoUninitialize()
print(target)
