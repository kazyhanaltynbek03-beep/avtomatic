import * as XLSX from "xlsx";

const normalize = (value) => String(value ?? "").trim().toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9]/gi, "");
const aliases = {
  sku: ["sku", "артикулпродавца", "артикул", "кодтовара", "vendorcode"],
  name: ["model", "модель", "название", "наименование", "товар"],
  brand: ["brand", "бренд", "производитель"],
  price: ["price", "цена", "ценатовара", "ценапродажи"],
  preorder: ["preorder", "предзаказ", "срокпредзаказа", "срокпредзаказ"],
};
let workbook = null;
let sheetName = null;
let headerRow = 0;
let columns = null;

function number(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const parsed = Number.parseFloat(String(value).replace(/[\s\u00a0\u202f₸]/g, "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function stockValue(value) {
  if (value == null || value === "") return null;
  const text = String(value).trim().toLowerCase();
  if (["yes", "да", "true", "1", "есть"].includes(text)) return true;
  if (["no", "нет", "false", "0", "нет в наличии"].includes(text)) return false;
  const numeric = number(text);
  return numeric == null ? null : numeric > 0;
}

function inspectSheet(name) {
  const sheet = workbook.Sheets[name];
  const fullRange = XLSX.utils.decode_range(sheet["!ref"] || "A1:A1");
  if (fullRange.e.r + 1 > 20025) throw new Error("В прайс-листе больше 20 000 строк. Разделите файл, чтобы сохранить быструю работу на телефоне.");
  const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "", raw: true, blankrows: true });
  if (!matrix.length) throw new Error("В выбранном листе нет строк.");
  let best = -1;
  let bestScore = -1;
  for (let row = 0; row < Math.min(matrix.length, 25); row += 1) {
    const headers = matrix[row].map(normalize);
    const hasSku = headers.some((h) => aliases.sku.includes(h));
    const hasPrice = headers.some((h) => aliases.price.includes(h));
    const score = Number(hasSku) * 4 + Number(hasPrice) * 3 + Number(headers.some((h) => aliases.name.includes(h))) * 2 + headers.filter(Boolean).length / 100;
    if (score > bestScore) { best = row; bestScore = score; }
  }
  if (best < 0 || bestScore < 3) throw new Error("Не нашёл заголовки SKU и цены. Выберите оригинальный ACTIVE.xlsx из Kaspi.");
  const rawHeaders = matrix[best].map((x) => String(x ?? "").trim());
  const normalized = rawHeaders.map(normalize);
  const find = (keys) => normalized.findIndex((h) => keys.includes(h));
  const sku = find(aliases.sku);
  const price = find(aliases.price);
  if (sku < 0 || price < 0) throw new Error("В файле обязательны столбцы SKU и Цена.");
  const pointColumns = normalized.map((h, i) => {
    const match = h.match(/^pp([1-5])$/);
    return match ? { point: Number(match[1]), column: i, label: rawHeaders[i] || `PP${match[1]}`} : null;
  }).filter(Boolean).sort((a, b) => a.point - b.point);
  const preorder = find(aliases.preorder);
  columns = { sku, name: find(aliases.name), brand: find(aliases.brand), price, preorder, points: pointColumns };
  headerRow = best;
  const rows = [];
  for (let i = best + 1; i < matrix.length; i += 1) {
    const source = matrix[i] || [];
    if (source.every((cell) => cell == null || String(cell).trim() === "")) continue;
    const skuText = String(source[sku] ?? "").trim();
    if (!skuText) continue;
    rows.push({
      id: i + 1,
      excelRow: i + 1,
      sku: skuText,
      name: columns.name < 0 ? "" : String(source[columns.name] ?? "").trim(),
      brand: columns.brand < 0 ? "" : String(source[columns.brand] ?? "").trim(),
      price: number(source[price]),
      stock: pointColumns.map(({ column }) => stockValue(source[column])),
      preorder: preorder < 0 ? 0 : Math.max(0, Math.round(number(source[preorder]) ?? 0)),
    });
  }
  if (!rows.length) throw new Error("В таблице нет товаров со SKU.");
  const warnings = [];
  if (!pointColumns.length) warnings.push("Столбцы PP1–PP5 не найдены: наличие по точкам нельзя изменить.");
  if (preorder < 0) warnings.push("Столбец предзаказа отсутствует; он будет добавлен при выгрузке, если вы измените срок.");
  const duplicateSkus = rows.reduce((counts, row) => counts.set(row.sku.toLowerCase(), (counts.get(row.sku.toLowerCase()) || 0) + 1), new Map());
  const duplicates = [...duplicateSkus.values()].filter((count) => count > 1).length;
  if (duplicates) warnings.push(`В файле есть повторяющиеся SKU (${duplicates} групп). Они сохранены отдельными строками.`);
  return { sheetName: name, sheetNames: workbook.SheetNames, headers: rawHeaders, headerRow: best + 1, pointLabels: pointColumns.map((p) => p.label), rows, warnings, total: rows.length };
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "parse") {
      const buffer = await data.file.arrayBuffer();
      workbook = XLSX.read(buffer, { type: "array", cellDates: true, cellStyles: true });
      sheetName = workbook.SheetNames[0];
      self.postMessage({ type: "parsed", ...inspectSheet(sheetName) });
      return;
    }
    if (data.type === "select-sheet") {
      if (!workbook?.Sheets[data.sheetName]) throw new Error("Лист не найден.");
      sheetName = data.sheetName;
      self.postMessage({ type: "parsed", ...inspectSheet(sheetName) });
      return;
    }
    if (data.type === "export") {
      if (!workbook || !columns) throw new Error("Сначала загрузите прайс-лист.");
      const sheet = workbook.Sheets[sheetName];
      const range = XLSX.utils.decode_range(sheet["!ref"] || "A1:A1");
      const edits = data.edits || [];
      const needsPreorderColumn = columns.preorder < 0 && edits.some((row) => Object.hasOwn(row, "preorder"));
      const preorderColumn = needsPreorderColumn ? Math.max(range.e.c + 1, columns.price + 1) : columns.preorder;
      if (needsPreorderColumn) {
        const headerAddress = XLSX.utils.encode_cell({ r: headerRow, c: preorderColumn });
        const styleSource = sheet[XLSX.utils.encode_cell({ r: headerRow, c: columns.price })];
        sheet[headerAddress] = { ...(styleSource?.s ? { s: styleSource.s } : {}), t: "s", v: "preorder" };
        range.e.c = Math.max(range.e.c, preorderColumn);
      }
      for (const row of edits) {
        const r = row.excelRow - 1;
        if (Object.hasOwn(row, "price")) writeCell(sheet, r, columns.price, row.price);
        if (Object.hasOwn(row, "preorder") && preorderColumn >= 0) writeCell(sheet, r, preorderColumn, row.preorder);
        for (const [pointIndex, value] of Object.entries(row.stock || {})) {
          const point = columns.points[Number(pointIndex)];
          if (point) writeCell(sheet, r, point.column, value ? "yes" : "no");
        }
      }
      sheet["!ref"] = XLSX.utils.encode_range(range);
      const output = XLSX.write(workbook, { type: "array", bookType: "xlsx", cellStyles: true });
      self.postMessage({ type: "exported", buffer: output }, [output]);
    }
  } catch (error) {
    self.postMessage({ type: "error", message: error instanceof Error ? error.message : "Не удалось обработать файл." });
  }
};

function writeCell(sheet, row, column, value) {
  const address = XLSX.utils.encode_cell({ r: row, c: column });
  const old = sheet[address] || {};
  const numeric = value !== "" && value != null && Number.isFinite(Number(value));
  sheet[address] = { ...old, t: numeric ? "n" : "s", v: numeric ? Number(value) : String(value ?? "") };
}
