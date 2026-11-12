# Print labels from a spreadsheet

[All guides](README.md) · [Project overview](../README.md)

Use CSV runs when you need many labels with different text. Save or export your spreadsheet as a CSV file: its first row should name the columns, and each following row provides the values for a label. Creating a preview does not print anything.

## Import your file

1. Open **CSV runs**, or select **Use with CSV** on a template.
2. Upload your CSV file or paste its contents. Choose the separator used by your
   spreadsheet: comma, semicolon or tab. Select **Read CSV**.
3. Match each spreadsheet column to a template field. For example, match your
   spreadsheet's **Name** column to the template's **Name** field.
4. Select the rows to print, set the number of copies and arrange their order.

Files must use UTF-8 text encoding. Quoted separators and multiline values are
supported. Numeric fields use a decimal point; yes/no (boolean) fields
accept `true`, `false`, `1`, or `0` (case insensitive). Blank non-text cells are
absent values. Image fields map each distinct CSV cell to an uploaded image;
URLs and filesystem paths are not fetched automatically.

## Check the labels before printing

**Validate and preview run** saves a draft only if every selected record is valid.
The draft saves a fixed copy of the design and entered values, so later template
changes do not alter the labels you have reviewed.
Review individual labels and the ordered run before choosing **Submit entire run**.
All selected labels are added to the queue together; retrying the same submission
does not add duplicates. They still wait for the usual printing threshold and any
printer hold to be cleared. See [printing and the queue](PRINTING.md).

## File limits

Imports are limited to 1 MB, 250 data records, 40 columns, 2000 characters per cell,
and 1000 copies per run. Reported record numbers include the header and count
logical CSV records, including multiline cells. Unsubmitted drafts can be deleted;
submitted runs remain in history, with queued copies cancellable from the queue.
