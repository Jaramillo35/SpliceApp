# Short Demonstration

## 1) Start the app

```bash
python -m streamlit run app.py
```

## 2) DTx Compare demo

- Open DTx Compare Report.
- Upload one OLD workbook and one NEW workbook.
- Click Generate report.
- Download the generated comparison workbook.

Expected result:
- Connector and summary sheets identify Added, Removed, and Modified records.

## 3) Splice Generation demo

- Open Splice Generation.
- Upload a workbook containing Complexity and OptionPerCkt sheets.
- Run generation.
- Download the generated splice output workbook.

Expected result:
- Generated connections include normalized sales code expressions.

## 4) Feedback demo

- Submit a ticket from the sidebar form.
- Confirm a new JSON entry is written to `data/tickets.json` in source mode, or
  `%LOCALAPPDATA%\SpliceApp\tickets.json` in the Windows executable.
