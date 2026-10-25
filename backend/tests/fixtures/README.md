# Import fixtures

`golden_sales.csv` deliberately uses a non-default column order and semicolon
delimiter. The golden financial test parses it through the production CSV parser.
The XLSX counterpart is constructed with `openpyxl` in the same test to ensure its
binary workbook is valid and formula-free without keeping generated binary files in
source control.
